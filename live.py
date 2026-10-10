from __future__ import annotations

import ctypes
import itertools
import logging
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Callable

from about_window import AboutPanel
from app_common import (
    APP_NAME,
    ROOT,
    build_rtsp_url,
    camera_id,
    test_port,
    update_config,
)
from ptz import DEFAULT_ONVIF_PORT, PTZController
from modal import ModalPanel, unbind_one
from settings_window import SettingsPanel
from theme import apply_style, palette

CREATE_NO_WINDOW = 0x08000000
SW_SHOW = 5
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000

user32 = ctypes.windll.user32 if os.name == "nt" else None

PTZ_DIRECTIONS = [
    ("↖", -1, -1), ("↑", 0, -1), ("↗", 1, -1),
    ("←", -1, 0), ("⌂", 0, 0), ("→", 1, 0),
    ("↙", -1, 1), ("↓", 0, 1), ("↘", 1, 1),
]

# Each player window gets a unique title so it can be found and embedded,
# even when several tiles start within the same millisecond.
_player_ids = itertools.count(1)


def _kill_process(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


class CameraTile:
    """One camera's embedded ffplay player, status overlay and PTZ link."""

    def __init__(self, view: "LiveView", parent: tk.Misc, camera: dict, password: str | None, stream: str) -> None:
        self.view = view
        self.root = view.root
        self.camera = camera
        self.password = password
        self.stream = stream
        self.muted = True
        self.process: subprocess.Popen | None = None
        self.player_hwnd: int | None = None
        self.closed = False
        self.state = "connecting"  # connecting | live | error
        self._generation = 0  # bumped on every (re)start so stale workers bail out
        self.ptz = PTZController(
            camera["host"],
            int(camera.get("onvif_port", DEFAULT_ONVIF_PORT)),
            camera["username"],
            password or "",
        )
        self.ptz_supported = False
        self.ptz_speed = float(camera.get("ptz_speed", 0.5))

        colors = view.colors
        self.frame = tk.Frame(parent, bg=colors["bg"], highlightthickness=2, highlightbackground=colors["bg"])

        self.header = tk.Frame(self.frame, bg=colors["bg_alt"], padx=8, pady=4, cursor="hand2")
        self.dot = tk.Label(self.header, text="●", font=("Segoe UI", 9), bg=colors["bg_alt"], fg=colors["text_dim"])
        self.dot.pack(side="left")
        self.name_label = tk.Label(
            self.header,
            text=camera["camera_name"],
            font=("Segoe UI Semibold", 10),
            bg=colors["bg_alt"],
            fg=colors["text"],
        )
        self.name_label.pack(side="left", padx=(4, 0))
        self.audio_label = tk.Label(self.header, text="", font=("Segoe UI", 9), bg=colors["bg_alt"], fg=colors["text"])
        self.audio_label.pack(side="right")
        self.state_label = tk.Label(
            self.header, text="Connecting…", font=("Segoe UI", 9), bg=colors["bg_alt"], fg=colors["text_dim"]
        )
        self.state_label.pack(side="right", padx=(0, 6))

        self.video = tk.Frame(self.frame, bg=colors["video_bg"])
        self.video.pack(fill="both", expand=True)
        self.video.bind("<Configure>", self.resize_player)

        self.overlay = tk.Frame(self.video, bg=colors["video_bg"])
        self.overlay_label = tk.Label(
            self.overlay,
            text="",
            bg=colors["video_bg"],
            fg="#eeeeee",
            font=("Segoe UI", 13),
            justify="center",
        )
        self.overlay_label.pack()
        self.overlay_bar = ttk.Progressbar(
            self.overlay, mode="indeterminate", length=180, style="Video.Horizontal.TProgressbar"
        )

        for widget in (self.header, self.dot, self.name_label, self.state_label, self.audio_label,
                       self.video, self.overlay, self.overlay_label):
            widget.bind("<Button-1>", lambda _e: self.view.select_tile(self))
        for widget in (self.header, self.dot, self.name_label, self.state_label):
            widget.bind("<Double-Button-1>", lambda _e: self.view.show_camera(self.camera))

    @property
    def name(self) -> str:
        return self.camera["camera_name"]

    def show_header(self, visible: bool) -> None:
        if visible:
            self.header.pack(fill="x", before=self.video)
        else:
            self.header.pack_forget()

    def apply_theme(self, colors: dict) -> None:
        self.frame.configure(bg=colors["bg"])
        for widget in (self.header, self.dot, self.name_label, self.state_label, self.audio_label):
            widget.configure(bg=colors["bg_alt"])
        self.name_label.configure(fg=colors["text"])
        self.audio_label.configure(fg=colors["text"])
        self._paint_state()

    # ------------------------------------------------------------ overlay --
    def _show_overlay(self, text: str, busy: bool) -> None:
        self.overlay_label.configure(text=text, font=("Segoe UI", 13 if busy else 11))
        if busy:
            self.overlay_bar.pack(pady=(14, 0))
            self.overlay_bar.start(12)
        else:
            self.overlay_bar.stop()
            self.overlay_bar.pack_forget()
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")

    def _hide_overlay(self) -> None:
        self.overlay_bar.stop()
        self.overlay.place_forget()

    def _set_state(self, state: str) -> None:
        self.state = state
        self._paint_state()
        self.view.refresh_status()

    def _paint_state(self) -> None:
        colors = self.view.colors
        text, color = {
            "connecting": ("Connecting…", colors["text_dim"]),
            "live": ("Live", colors["success"]),
            "error": ("Offline", colors["danger"]),
        }[self.state]
        self.dot.configure(fg=color)
        self.state_label.configure(text=text, fg=color if self.state != "connecting" else colors["text_dim"])
        self.audio_label.configure(text="" if self.muted else "🔊")

    # -------------------------------------------------------------- player --
    def start(self) -> None:
        self._generation += 1
        generation = self._generation
        self.stop_player()
        self._set_state("connecting")
        self._show_overlay(f"Connecting to {self.name}…", busy=True)
        threading.Thread(target=self._start_worker, args=(generation,), daemon=True).start()

    def _stale(self, generation: int) -> bool:
        return self.closed or generation != self._generation

    def _start_worker(self, generation: int) -> None:
        title = f"TapoPlayer-{os.getpid()}-{next(_player_ids)}"
        if self.view.demo:
            time.sleep(0.4)
            args = [sys.executable, str(ROOT / "demo_player.py"), title]
        else:
            if self.password is None:
                self._post_error(
                    generation,
                    "This camera's password is not saved in Windows Credential Manager.\n"
                    "Remove it from the camera list and add it again.",
                )
                return
            ok, detail = test_port(self.camera["host"], int(self.camera.get("port", 554)))
            if not ok:
                self._post_error(generation, detail)
                return
            url = build_rtsp_url(self.camera, self.password, self.stream)
            args = [
                self.view.ffplay,
                "-hide_banner",
                "-loglevel", "warning",
                "-nostats",
                "-rtsp_transport", self.camera.get("rtsp_transport", "tcp"),
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-framedrop",
                "-noborder",
                # Open off-screen so the window never flashes before it is embedded.
                "-left", "-10000",
                "-top", "-10000",
                "-window_title", title,
            ]
            if self.muted:
                args.append("-an")
            args.append(url)
        if self._stale(generation):
            return
        logging.info("Starting player for %s using %s", self.name, self.stream)
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
                text=True,
            )
        except Exception as exc:
            self._post_error(generation, f"Could not start ffplay: {exc}")
            return
        if self._stale(generation):
            _kill_process(process)
            return
        self.process = process

        hwnd = self._wait_for_window(title, process, generation, timeout=12)
        if self._stale(generation):
            _kill_process(process)
            return
        if hwnd is None:
            error = "ffplay started but its video window was not found."
            if process.poll() is not None and process.stderr:
                output = process.stderr.read().strip()
                if output:
                    error = output[-700:]
            self._post_error(generation, error)
            return
        self.root.after(0, lambda: self._embed(generation, process, hwnd))

    def _wait_for_window(self, title: str, process: subprocess.Popen, generation: int, timeout: float) -> int | None:
        if os.name != "nt":
            return None
        deadline = time.time() + timeout
        while time.time() < deadline and not self._stale(generation):
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                return int(hwnd)
            if process.poll() is not None:
                return None
            time.sleep(0.1)
        return None

    def _embed(self, generation: int, process: subprocess.Popen, hwnd: int) -> None:
        if self._stale(generation) or not self.video.winfo_exists():
            _kill_process(process)
            return
        self.player_hwnd = hwnd
        self.video.update_idletasks()
        user32.SetParent(hwnd, self.video.winfo_id())
        user32.SetWindowLongW(hwnd, GWL_STYLE, WS_CHILD | WS_VISIBLE)
        user32.ShowWindow(hwnd, SW_SHOW)
        self.resize_player()
        self._hide_overlay()
        self._set_state("live")
        self.view.on_tile_live(self)
        self._watch(generation)

    def resize_player(self, _event=None) -> None:
        width = max(1, self.video.winfo_width())
        height = max(1, self.video.winfo_height())
        self.overlay_label.configure(wraplength=max(160, width - 40))
        if self.player_hwnd and user32:
            user32.MoveWindow(self.player_hwnd, 0, 0, width, height, True)
        if self is self.view.active_tile:
            self.view.position_ptz_overlay()

    def _watch(self, generation: int) -> None:
        if self._stale(generation) or not self.process:
            return
        if self.process.poll() is not None:
            self.player_hwnd = None
            self.show_error("The camera stream stopped. Click Reconnect to try again.")
            return
        self.root.after(1000, lambda: self._watch(generation))

    def _post_error(self, generation: int, detail: str) -> None:
        def show() -> None:
            if not self._stale(generation):
                self.show_error(detail)

        self.root.after(0, show)

    def show_error(self, detail: str) -> None:
        logging.error("%s: %s", self.name, detail)
        self._set_state("error")
        self._show_overlay(f"Could not open {self.name}\n\n{detail}", busy=False)

    def stop_player(self) -> None:
        self.player_hwnd = None
        process, self.process = self.process, None
        if process and process.poll() is None:
            # terminate() is immediate on Windows, so the player is gone even if the
            # app exits right after; only the follow-up wait happens off the UI thread.
            try:
                process.terminate()
            except Exception:
                pass
            threading.Thread(target=_kill_process, args=(process,), daemon=True).start()

    def close(self) -> None:
        self.closed = True
        self._generation += 1
        self.stop_player()
        if self.ptz.available:
            threading.Thread(target=self.ptz.stop, daemon=True).start()

    # ----------------------------------------------------------------- PTZ --
    def init_ptz(self) -> None:
        threading.Thread(target=self._init_ptz_worker, daemon=True).start()

    def _init_ptz_worker(self) -> None:
        if self.view.demo:
            time.sleep(float(os.environ.get("TAPO_DEMO_PTZ_DELAY", "1.5")))
            ok = True
        else:
            ok = self.password is not None and self.ptz.connect()
        if self.closed:
            return
        if ok:
            self.root.after(0, self._on_ptz_ready)
        else:
            logging.info("Pan/tilt not available for %s: %s", self.name, self.ptz.error)

    def _on_ptz_ready(self) -> None:
        if self.closed:
            return
        self.ptz_supported = True
        self.view.on_tile_ptz_ready(self)


class LiveView:
    """The live-view screen: toolbar plus one camera, or a grid of all of them.

    Lives inside ``container`` (a frame in the main window) so the app can
    switch between the loading screen, camera list and live view without
    opening new windows. Call :meth:`teardown` before leaving the screen.
    """

    def __init__(
        self,
        root: tk.Tk,
        container: tk.Misc,
        config: dict,
        passwords: dict[str, str | None],
        ffplay: str,
        mode: str = "single",
        camera: dict | None = None,
        on_back: Callable[[], None] | None = None,
        on_theme_change: Callable[[dict], None] | None = None,
        demo: bool = False,
    ) -> None:
        self.root = root
        self.config = config
        self.cameras: list[dict] = config["cameras"]
        self.passwords = passwords
        self.ffplay = ffplay
        self.on_back = on_back
        self.on_theme_change = on_theme_change
        self.demo = demo
        self.mode = mode if len(self.cameras) > 1 else "single"
        self.current_camera = camera or self.cameras[0]
        self.single_stream = self.current_camera.get("stream", "stream1")
        self.multi_stream = config.get("multiview_stream", "stream2")
        self.tiles: list[CameraTile] = []
        self.active_tile: CameraTile | None = None
        self.closing = False
        self.fullscreen = False
        self.session_start = time.monotonic()
        self.colors = palette(config.get("theme"))
        self.ptz_buttons: list[tk.Button] = []
        self.ptz_overlay: tk.Toplevel | None = None
        self.panel: ModalPanel | None = None

        self.frame = ttk.Frame(container)
        self.frame.pack(fill="both", expand=True)

        self._bindings: list[tuple[str, str]] = []
        self._bind("<F11>", lambda _e: self.toggle_fullscreen())
        self._bind("<Escape>", lambda _e: self.leave_fullscreen())
        self._bind("<Configure>", lambda _e: self.position_ptz_overlay())
        self._bind("<FocusOut>", lambda _e: self._set_overlay_visible(False))
        self._bind("<FocusIn>", lambda _e: self._set_overlay_visible(True))
        self._bind("<Unmap>", lambda _e: self._set_overlay_visible(False))

        self._build_ui()
        self.build_ptz_overlay()
        self.root.after(50, self._build_tiles)
        self.root.after(1000, self._tick_session)

    def _bind(self, sequence: str, handler) -> None:
        self._bindings.append((sequence, self.root.bind(sequence, handler, add="+")))

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self) -> None:
        colors = self.colors

        self.brand_row = ttk.Frame(self.frame, style="Toolbar.TFrame", padding=(14, 8))
        self.brand_row.pack(fill="x")

        self.brand_box = ttk.Frame(self.brand_row, style="Toolbar.TFrame")
        self.brand_box.pack(side="left")

        try:
            from theme import ICON_PNG

            logo_img = tk.PhotoImage(file=str(ICON_PNG)).subsample(12, 12)
            self.logo_label = tk.Label(self.brand_box, image=logo_img, bg=colors["bg_alt"])
            self.logo_label.image = logo_img
            self.logo_label.pack(side="left", padx=(0, 8))
        except Exception:
            self.logo_label = None

        self.brand_label = ttk.Label(self.brand_box, text="Tapo Live View", style="Brand.TLabel")
        self.brand_label.pack(side="left")
        ttk.Label(self.brand_box, text="  •  ", style="Dim.TLabel").pack(side="left")

        self._camera_name_label = ttk.Label(self.brand_row, text="", style="Brand.TLabel")
        self._camera_name_label.pack(side="left")

        self.date_label = ttk.Label(self.brand_row, text="", style="Dim.TLabel")
        self.date_label.pack(side="right", padx=(12, 0))
        self.timer_label = ttk.Label(self.brand_row, text="Session 00:00:00", style="Dim.TLabel")
        self.timer_label.pack(side="right", padx=(12, 0))
        self.status = tk.StringVar(value="Connecting…")
        ttk.Label(self.brand_row, textvariable=self.status, style="Status.TLabel").pack(side="right", padx=(12, 0))

        self.control_row = ttk.Frame(self.frame, style="Toolbar.TFrame", padding=(14, 0, 14, 8))
        self.control_row.pack(fill="x")

        if self.on_back is not None:
            ttk.Button(self.control_row, text="◀ Cameras", style="Icon.TButton", command=self.go_back).pack(
                side="left", padx=(0, 6)
            )
        self.camera_var = tk.StringVar(value=camera_id(self.current_camera))
        self.camera_button = ttk.Menubutton(self.control_row, text="", style="Icon.TMenubutton")
        self.camera_menu = tk.Menu(self.camera_button, tearoff=0)
        self.camera_button.configure(menu=self.camera_menu)
        self.camera_button.pack(side="left", padx=(0, 6))
        self._build_camera_menu()

        self.multi_button = ttk.Button(self.control_row, text="▦ Multi view", style="Icon.TButton", command=self.toggle_multi)
        self.multi_button.pack(side="left", padx=(0, 6))
        self.ptz_toggle_button = ttk.Button(
            self.control_row, text="🕹 PTZ", style="Icon.TButton", command=self.toggle_ptz_visibility
        )
        self.ptz_toggle_button.pack(side="left")

        ttk.Button(self.control_row, text="ℹ About", style="Icon.TButton", command=self.open_about).pack(side="right")
        ttk.Button(self.control_row, text="⚙ Settings", style="Icon.TButton", command=self.open_settings).pack(
            side="right", padx=(6, 6)
        )
        ttk.Separator(self.control_row, orient="vertical").pack(side="right", fill="y", padx=6, pady=2)
        ttk.Button(self.control_row, text="⟳ Reconnect", style="Icon.TButton", command=self.restart).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(self.control_row, text="⛶ Fullscreen", style="Icon.TButton", command=self.toggle_fullscreen).pack(
            side="right", padx=(6, 0)
        )
        self.mute_button = ttk.Button(self.control_row, text="🔇 Unmute", style="Icon.TButton", command=self.toggle_mute)
        self.mute_button.pack(side="right", padx=(6, 0))
        self.quality_button = ttk.Button(self.control_row, text="", style="Icon.TButton", command=self.toggle_quality)
        self.quality_button.pack(side="right", padx=(6, 0))

        self.video_area = tk.Frame(self.frame, bg=colors["video_bg"])
        self.video_area.pack(fill="both", expand=True)

        self._apply_display_settings()
        self._refresh_date()

    def _build_camera_menu(self) -> None:
        colors = self.colors
        menu = self.camera_menu
        menu.configure(
            bg=colors["surface"],
            fg=colors["text"],
            activebackground=colors["accent"],
            activeforeground=colors["accent_text"],
            selectcolor=colors["accent"],
            bd=0,
            font=("Segoe UI", 10),
        )
        menu.delete(0, "end")
        for camera in self.cameras:
            menu.add_radiobutton(
                label=camera["camera_name"],
                value=camera_id(camera),
                variable=self.camera_var,
                command=lambda cam=camera: self.show_camera(cam),
            )
        if len(self.cameras) > 1:
            menu.add_separator()
            menu.add_command(label="▦  All cameras (multi view)", command=lambda: self.set_mode("multi"))

    def quality_label(self) -> str:
        stream = self.multi_stream if self.mode == "multi" else self.single_stream
        return "🎞 HD" if stream == "stream1" else "🎞 SD"

    def _refresh_toolbar(self) -> None:
        if self.mode == "multi":
            self._camera_name_label.configure(text=f"Multi view · {len(self.tiles)} cameras")
            self.camera_button.configure(text="📷 All cameras")
            self.camera_var.set("")
            self.multi_button.configure(text="▦ Multi view", style="Active.TButton")
            self.root.title(f"Multi view — {APP_NAME}")
        else:
            name = self.current_camera["camera_name"]
            self._camera_name_label.configure(text=name)
            self.camera_button.configure(text=f"📷 {name}")
            self.camera_var.set(camera_id(self.current_camera))
            self.multi_button.configure(text="▦ Multi view", style="Icon.TButton")
            self.root.title(f"{name} — {APP_NAME}")
        self.quality_button.configure(text=self.quality_label())
        self._refresh_mute_button()

    def _refresh_mute_button(self) -> None:
        muted = self.active_tile is None or self.active_tile.muted
        self.mute_button.configure(text="🔇 Unmute" if muted else "🔊 Mute")

    def refresh_status(self) -> None:
        if not self.tiles:
            return
        if self.mode == "multi":
            live = sum(1 for tile in self.tiles if tile.state == "live")
            self.status.set(f"{live}/{len(self.tiles)} live")
            return
        state = self.tiles[0].state
        self.status.set({"connecting": "Connecting…", "live": "Live", "error": "Not connected"}[state])

    # -------------------------------------------------------------- tiles --
    def _build_tiles(self) -> None:
        if self.closing:
            return
        for tile in self.tiles:
            tile.close()
            tile.frame.destroy()
        self.tiles = []
        self.active_tile = None
        self._set_overlay_visible(False)

        multi = self.mode == "multi"
        cameras = self.cameras if multi else [self.current_camera]
        stream = self.multi_stream if multi else self.single_stream
        columns = math.ceil(math.sqrt(len(cameras)))
        rows = math.ceil(len(cameras) / columns)
        for index in range(8):
            self.video_area.columnconfigure(index, weight=0, uniform="")
            self.video_area.rowconfigure(index, weight=0, uniform="")
        for index in range(columns):
            self.video_area.columnconfigure(index, weight=1, uniform="tile")
        for index in range(rows):
            self.video_area.rowconfigure(index, weight=1, uniform="tile")

        gap = 2 if multi else 0
        for index, camera in enumerate(cameras):
            tile = CameraTile(self, self.video_area, camera, self.passwords.get(camera_id(camera)), stream)
            row, column = divmod(index, columns)
            tile.frame.grid(row=row, column=column, sticky="nsew", padx=gap, pady=gap)
            tile.show_header(multi)
            self.tiles.append(tile)
            if camera_id(camera) == camera_id(self.current_camera):
                self.active_tile = tile
        if self.active_tile is None:
            self.active_tile = self.tiles[0]

        self._highlight_active()
        self._refresh_toolbar()
        for tile in self.tiles:
            tile.start()
            tile.init_ptz()

    def _highlight_active(self) -> None:
        for tile in self.tiles:
            active = self.mode == "multi" and tile is self.active_tile
            tile.frame.configure(highlightbackground=self.colors["accent"] if active else self.colors["bg"])

    def select_tile(self, tile: CameraTile) -> None:
        if tile is self.active_tile or tile not in self.tiles:
            return
        self.active_tile = tile
        self.current_camera = tile.camera
        self._highlight_active()
        self._refresh_mute_button()
        self._set_overlay_visible(True)

    def show_camera(self, camera: dict) -> None:
        if self.mode == "single" and camera_id(camera) == camera_id(self.current_camera):
            return
        self.mode = "single"
        self.current_camera = camera
        self.single_stream = camera.get("stream", "stream1")
        self._build_tiles()

    def set_mode(self, mode: str) -> None:
        if mode == "multi" and len(self.cameras) < 2:
            messagebox.showinfo(
                APP_NAME, "Multi view needs at least two cameras. Go back to the camera list to add another one."
            )
            return
        if mode == self.mode:
            return
        if mode == "single" and self.active_tile is not None:
            self.current_camera = self.active_tile.camera
            self.single_stream = self.current_camera.get("stream", "stream1")
        self.mode = mode
        self._build_tiles()

    def toggle_multi(self) -> None:
        self.set_mode("single" if self.mode == "multi" else "multi")

    def on_tile_live(self, tile: CameraTile) -> None:
        if tile is self.active_tile:
            self._set_overlay_visible(True)

    def on_tile_ptz_ready(self, tile: CameraTile) -> None:
        if tile is self.active_tile:
            self._set_overlay_visible(True)

    # ---------------------------------------------------- PTZ pad overlay --
    def build_ptz_overlay(self) -> None:
        colors = self.colors
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        try:
            overlay.attributes("-alpha", 0.96)
        except Exception:
            pass
        overlay.withdraw()

        pad = tk.Frame(overlay, bg=colors["surface"], highlightthickness=1, highlightbackground=colors["border"])
        pad.pack(padx=0, pady=0)
        inner = tk.Frame(pad, bg=colors["surface"], padx=8, pady=8)
        inner.pack()

        self.ptz_buttons = []
        for index, (symbol, dx, dy) in enumerate(PTZ_DIRECTIONS):
            row, col = divmod(index, 3)
            button = tk.Button(
                inner,
                text=symbol,
                width=3,
                font=("Segoe UI", 13),
                bg=colors["bg_alt"],
                fg=colors["text"],
                activebackground=colors["accent"],
                activeforeground=colors["accent_text"],
                relief="flat",
                bd=0,
                cursor="hand2",
            )
            button.grid(row=row, column=col, padx=2, pady=2)
            if dx == 0 and dy == 0:
                button.configure(command=self.ptz_home)
            else:
                button.bind("<ButtonPress-1>", lambda _e, dx=dx, dy=dy: self.ptz_press(dx, dy))
                button.bind("<ButtonRelease-1>", lambda _e: self.ptz_release())
            self.ptz_buttons.append(button)

        self.ptz_overlay = overlay
        self.ptz_overlay_frame = pad

    def _ptz_wanted(self) -> bool:
        tile = self.active_tile
        return bool(tile and tile.ptz_supported and self.config.get("show_ptz", True))

    def position_ptz_overlay(self) -> None:
        if self.ptz_overlay is None or not self.ptz_overlay.winfo_exists() or self.active_tile is None:
            return
        video = self.active_tile.video
        if not video.winfo_exists():
            return
        video.update_idletasks()
        self.ptz_overlay.update_idletasks()
        margin = 14
        vw, vh = video.winfo_width(), video.winfo_height()
        vx, vy = video.winfo_rootx(), video.winfo_rooty()
        ow = self.ptz_overlay.winfo_reqwidth()
        oh = self.ptz_overlay.winfo_reqheight()
        x = vx + vw - ow - margin
        y = vy + vh - oh - margin
        self.ptz_overlay.geometry(f"{ow}x{oh}+{max(vx, x)}+{max(vy, y)}")

    def _set_overlay_visible(self, visible: bool) -> None:
        if self.ptz_overlay is None or not self.ptz_overlay.winfo_exists():
            return
        if visible and not self.closing and self.panel is None and self._ptz_wanted():
            self.position_ptz_overlay()
            self.ptz_overlay.deiconify()
            self.ptz_overlay.lift()
        else:
            self.ptz_overlay.withdraw()

    def toggle_ptz_visibility(self) -> None:
        new_value = not self.config.get("show_ptz", True)
        update_config(self.config, show_ptz=new_value)
        self._set_overlay_visible(new_value)
        if new_value and not (self.active_tile and self.active_tile.ptz_supported):
            messagebox.showinfo(APP_NAME, "This camera does not report pan/tilt support.")

    def ptz_press(self, dx: int, dy: int) -> None:
        tile = self.active_tile
        if tile is None:
            return
        pan = dx * tile.ptz_speed
        tilt = -dy * tile.ptz_speed
        threading.Thread(target=tile.ptz.continuous_move, args=(pan, tilt), daemon=True).start()

    def ptz_release(self) -> None:
        if self.active_tile is not None:
            threading.Thread(target=self.active_tile.ptz.stop, daemon=True).start()

    def ptz_home(self) -> None:
        if self.active_tile is not None:
            threading.Thread(target=self.active_tile.ptz.goto_home, daemon=True).start()

    # ------------------------------------------------------- settings/about
    def open_settings(self) -> None:
        self._open_panel(lambda done: SettingsPanel(self.root, self.config, self._on_settings_changed, on_close=done))

    def open_about(self) -> None:
        self._open_panel(lambda done: AboutPanel(self.root, self.config.get("theme"), on_close=done))

    def _open_panel(self, factory) -> None:
        if self.panel is not None:
            self.panel.close()
        self._set_overlay_visible(False)
        self.panel = factory(self._on_panel_closed)

    def _on_panel_closed(self) -> None:
        self.panel = None
        if not self.closing:
            self._set_overlay_visible(True)

    def _on_settings_changed(self, changes: dict) -> None:
        if "theme" in changes:
            self.apply_theme(changes["theme"])
            if self.on_theme_change is not None:
                self.on_theme_change(self.colors)
        self._apply_display_settings()
        self._set_overlay_visible(True)

    def _apply_display_settings(self) -> None:
        if self.config.get("show_branding", True):
            self.brand_box.pack(side="left", before=self._camera_name_label)
        else:
            self.brand_box.pack_forget()
        if self.config.get("show_date", True):
            self.date_label.pack(side="right", padx=(12, 0))
        else:
            self.date_label.pack_forget()

    def _refresh_date(self) -> None:
        if self.closing:
            return
        self.date_label.configure(text=datetime.now().strftime("%a, %d %b %Y"))
        self.root.after(60_000, self._refresh_date)

    def _tick_session(self) -> None:
        if self.closing:
            return
        elapsed = int(time.monotonic() - self.session_start)
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        self.timer_label.configure(text=f"Session {hours:02d}:{minutes:02d}:{seconds:02d}")
        self.root.after(1000, self._tick_session)

    def apply_theme(self, theme_name: str) -> None:
        self.colors = palette(theme_name)
        colors = self.colors
        apply_style(self.root, colors)
        self.root.configure(bg=colors["bg"])
        self.video_area.configure(bg=colors["video_bg"])
        if self.logo_label is not None:
            self.logo_label.configure(bg=colors["bg_alt"])
        self._build_camera_menu()
        for tile in self.tiles:
            tile.apply_theme(colors)
        self._highlight_active()
        if self.ptz_overlay is not None and self.ptz_overlay.winfo_exists():
            self.ptz_overlay_frame.configure(bg=colors["surface"], highlightbackground=colors["border"])
            for child in self.ptz_overlay_frame.winfo_children():
                child.configure(bg=colors["surface"])
            for button in self.ptz_buttons:
                button.configure(
                    bg=colors["bg_alt"],
                    fg=colors["text"],
                    activebackground=colors["accent"],
                    activeforeground=colors["accent_text"],
                )

    # ------------------------------------------------------------ controls
    def restart(self) -> None:
        for tile in self.tiles:
            tile.start()

    def toggle_quality(self) -> None:
        if self.mode == "multi":
            self.multi_stream = "stream2" if self.multi_stream == "stream1" else "stream1"
            stream = self.multi_stream
        else:
            self.single_stream = "stream2" if self.single_stream == "stream1" else "stream1"
            stream = self.single_stream
        self.quality_button.configure(text=self.quality_label())
        for tile in self.tiles:
            tile.stream = stream
            tile.start()

    def toggle_mute(self) -> None:
        tile = self.active_tile
        if tile is None:
            return
        if tile.muted:
            # Only one camera plays audio at a time.
            for other in self.tiles:
                if other is not tile and not other.muted:
                    other.muted = True
                    other.start()
        tile.muted = not tile.muted
        tile.start()
        self._refresh_mute_button()

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def leave_fullscreen(self) -> None:
        if self.fullscreen:
            self.fullscreen = False
            self.root.attributes("-fullscreen", False)

    def go_back(self) -> None:
        self.teardown()
        if self.on_back is not None:
            self.on_back()

    def teardown(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.leave_fullscreen()
        if self.panel is not None:
            self.panel.close()
        for tile in self.tiles:
            tile.close()
        self.tiles = []
        if self.ptz_overlay is not None and self.ptz_overlay.winfo_exists():
            self.ptz_overlay.destroy()
        for sequence, funcid in self._bindings:
            unbind_one(self.root, sequence, funcid)
        self._bindings = []
        if self.frame.winfo_exists():
            self.frame.destroy()


def main() -> None:
    # The app now always starts through the wizard's loading screen and
    # camera list; this entry point is kept for TAPO_DEMO=1 runs and old shortcuts.
    from wizard import main as wizard_main

    wizard_main()


if __name__ == "__main__":
    main()
