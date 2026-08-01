from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from datetime import datetime
from tkinter import messagebox, ttk

from about_window import AboutWindow
from app_common import (
    APP_NAME,
    ROOT,
    apply_display_defaults,
    build_rtsp_url,
    fatal_dialog,
    find_executable,
    get_password,
    load_config,
    setup_logging,
    test_port,
)
from ptz import DEFAULT_ONVIF_PORT, PTZController
from settings_window import SettingsWindow
from theme import apply_style, palette, set_window_icon

CREATE_NO_WINDOW = 0x08000000
SW_HIDE = 0
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


class LiveView:
    def __init__(self, root: tk.Tk, config: dict, password: str, ffplay: str) -> None:
        self.root = root
        self.config = config
        self.password = password
        self.ffplay = ffplay
        self.process: subprocess.Popen | None = None
        self.player_hwnd: int | None = None
        self.closing = False
        self.stream = config.get("stream", "stream1")
        self.muted = True
        self.fullscreen = False
        self.ptz_speed = float(config.get("ptz_speed", 0.5))
        self.ptz = PTZController(
            config["host"],
            int(config.get("onvif_port", DEFAULT_ONVIF_PORT)),
            config["username"],
            password,
        )
        self.ptz_supported = False
        self.demo = os.environ.get("TAPO_DEMO") == "1"
        self.session_start = time.monotonic()
        self.colors = palette(config.get("theme"))

        self.ptz_buttons: list[tk.Button] = []
        self.ptz_overlay: tk.Toplevel | None = None

        camera_name = config["camera_name"]
        root.title(f"{camera_name} — {APP_NAME}")
        root.geometry(f"{config.get('window_width', 1100)}x{config.get('window_height', 700)}")
        root.minsize(720, 460)
        set_window_icon(root)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<F11>", lambda _event: self.toggle_fullscreen())
        root.bind("<Escape>", lambda _event: self.leave_fullscreen())
        root.bind("<Configure>", self._on_root_configure)
        root.bind("<FocusOut>", lambda _e: self._set_overlay_visible(False))
        root.bind("<FocusIn>", lambda _e: self._set_overlay_visible(self.config.get("show_ptz", True) and self.ptz_supported))
        root.bind("<Unmap>", lambda _e: self._set_overlay_visible(False))

        self.style = apply_style(root, self.colors)
        root.configure(bg=self.colors["bg"])

        self._build_ui(camera_name)
        self.build_ptz_overlay()
        root.after(150, self.start)
        root.after(150, self.init_ptz)
        root.after(1000, self._tick_session)

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self, camera_name: str) -> None:
        colors = self.colors

        self.brand_row = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(14, 8))
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

        self._camera_name_label = ttk.Label(self.brand_row, text=camera_name, style="Brand.TLabel")
        self._camera_name_label.pack(side="left")

        self.date_label = ttk.Label(self.brand_row, text="", style="Dim.TLabel")
        self.date_label.pack(side="right", padx=(12, 0))
        self.timer_label = ttk.Label(self.brand_row, text="Session 00:00:00", style="Dim.TLabel")
        self.timer_label.pack(side="right", padx=(12, 0))
        self.status = tk.StringVar(value="Connecting…")
        ttk.Label(self.brand_row, textvariable=self.status, style="Status.TLabel").pack(side="right", padx=(12, 0))

        self.control_row = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(14, 0, 14, 8))
        self.control_row.pack(fill="x")

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
        self.quality_button = ttk.Button(
            self.control_row, text=self.quality_label(), style="Icon.TButton", command=self.toggle_quality
        )
        self.quality_button.pack(side="right", padx=(6, 0))
        self.ptz_toggle_button = ttk.Button(
            self.control_row, text="🕹 PTZ", style="Icon.TButton", command=self.toggle_ptz_visibility
        )
        self.ptz_toggle_button.pack(side="left")

        self.video = tk.Frame(self.root, bg=colors["video_bg"])
        self.video.pack(fill="both", expand=True)
        self.video.bind("<Configure>", self.resize_player)

        self.overlay = tk.Label(
            self.video,
            text="Connecting to camera…",
            bg=colors["video_bg"],
            fg="#eeeeee",
            font=("Segoe UI", 14),
        )
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")

        self._apply_display_settings()
        self._refresh_date()

    def quality_label(self) -> str:
        return "🎞 High quality" if self.stream == "stream1" else "🎞 Standard quality"

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

    def _position_ptz_overlay(self) -> None:
        if self.ptz_overlay is None or not self.ptz_overlay.winfo_exists():
            return
        self.video.update_idletasks()
        self.ptz_overlay.update_idletasks()
        margin = 14
        vw = self.video.winfo_width()
        vh = self.video.winfo_height()
        vx = self.video.winfo_rootx()
        vy = self.video.winfo_rooty()
        ow = self.ptz_overlay.winfo_reqwidth()
        oh = self.ptz_overlay.winfo_reqheight()
        x = vx + vw - ow - margin
        y = vy + vh - oh - margin
        self.ptz_overlay.geometry(f"{ow}x{oh}+{max(vx, x)}+{max(vy, y)}")

    def _set_overlay_visible(self, visible: bool) -> None:
        if self.ptz_overlay is None or not self.ptz_overlay.winfo_exists():
            return
        if visible and self.ptz_supported and self.config.get("show_ptz", True):
            self._position_ptz_overlay()
            self.ptz_overlay.deiconify()
            self.ptz_overlay.lift()
        else:
            self.ptz_overlay.withdraw()

    def show_ptz_pad(self) -> None:
        self.ptz_supported = True
        self._set_overlay_visible(self.config.get("show_ptz", True))

    def toggle_ptz_visibility(self) -> None:
        from app_common import update_config

        new_value = not self.config.get("show_ptz", True)
        update_config(self.config, show_ptz=new_value)
        self._set_overlay_visible(new_value and self.ptz_supported)
        if not self.ptz_supported and new_value:
            messagebox.showinfo(APP_NAME, "This camera does not report pan/tilt support.")

    def _on_root_configure(self, _event=None) -> None:
        self._position_ptz_overlay()

    def init_ptz(self) -> None:
        threading.Thread(target=self._init_ptz_worker, daemon=True).start()

    def _init_ptz_worker(self) -> None:
        if self.demo:
            time.sleep(float(os.environ.get("TAPO_DEMO_PTZ_DELAY", "1.5")))
            self.root.after(0, self.show_ptz_pad)
            return
        ok = self.ptz.connect()
        if ok:
            self.root.after(0, self.show_ptz_pad)
        else:
            logging.info("Pan/tilt not available for %s: %s", self.config["camera_name"], self.ptz.error)

    def ptz_press(self, dx: int, dy: int) -> None:
        pan = dx * self.ptz_speed
        tilt = -dy * self.ptz_speed
        threading.Thread(target=self.ptz.continuous_move, args=(pan, tilt), daemon=True).start()

    def ptz_release(self) -> None:
        threading.Thread(target=self.ptz.stop, daemon=True).start()

    def ptz_home(self) -> None:
        threading.Thread(target=self.ptz.goto_home, daemon=True).start()

    # ------------------------------------------------------- settings/about
    def open_settings(self) -> None:
        self.settings_window = SettingsWindow(self.root, self.config, self._on_settings_changed)

    def open_about(self) -> None:
        self.about_window = AboutWindow(self.root, self.config.get("theme"))

    def _on_settings_changed(self, changes: dict) -> None:
        if "theme" in changes:
            self.apply_theme(changes["theme"])
        self._apply_display_settings()
        self._set_overlay_visible(self.config.get("show_ptz", True) and self.ptz_supported)

    def _apply_display_settings(self) -> None:
        show_branding = self.config.get("show_branding", True)
        if show_branding:
            self.brand_box.pack(side="left", before=self._camera_name_label)
        else:
            self.brand_box.pack_forget()
        show_date = self.config.get("show_date", True)
        if show_date:
            self.date_label.pack(side="right", padx=(12, 0))
        else:
            self.date_label.pack_forget()

    def _refresh_date(self) -> None:
        self.date_label.configure(text=datetime.now().strftime("%a, %d %b %Y"))
        self.root.after(60_000, self._refresh_date)

    def _tick_session(self) -> None:
        elapsed = int(time.monotonic() - self.session_start)
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        self.timer_label.configure(text=f"Session {hours:02d}:{minutes:02d}:{seconds:02d}")
        if not self.closing:
            self.root.after(1000, self._tick_session)

    def apply_theme(self, theme_name: str) -> None:
        self.colors = palette(theme_name)
        colors = self.colors
        self.style = apply_style(self.root, colors)
        self.root.configure(bg=colors["bg"])
        self.video.configure(bg=colors["video_bg"])
        self.overlay.configure(bg=colors["video_bg"])
        if self.logo_label is not None:
            self.logo_label.configure(bg=colors["bg_alt"])
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

    # --------------------------------------------------------- player/rtsp
    def start(self) -> None:
        self.stop_player()
        self.overlay.configure(text="Connecting to camera…")
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")
        self.status.set("Checking network…")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self) -> None:
        title = f"TapoPlayer-{os.getpid()}-{int(time.time() * 1000)}"
        if self.demo:
            args = [sys.executable, str(ROOT / "demo_player.py"), title]
        else:
            ok, detail = test_port(self.config["host"], int(self.config.get("port", 554)))
            if not ok:
                self.root.after(0, lambda: self.show_error(detail))
                return
            url = build_rtsp_url(self.config, self.password, self.stream)
            args = [
                self.ffplay,
                "-hide_banner",
                "-loglevel", "warning",
                "-nostats",
                "-rtsp_transport", self.config.get("rtsp_transport", "tcp"),
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-framedrop",
                "-window_title", title,
                "-an" if self.muted else "-vn",  # replaced below when unmuted
                url,
            ]
            if not self.muted:
                args.remove("-vn")
        logging.info("Starting player for %s using %s", self.config["camera_name"], self.stream)
        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
                text=True,
            )
        except Exception as exc:
            self.root.after(0, lambda: self.show_error(f"Could not start ffplay: {exc}"))
            return

        hwnd = self.wait_for_window(title, timeout=12)
        if hwnd is None:
            error = "ffplay started but its video window was not found."
            if self.process and self.process.poll() is not None and self.process.stderr:
                output = self.process.stderr.read().strip()
                if output:
                    error = output[-700:]
            self.root.after(0, lambda: self.show_error(error))
            return
        self.player_hwnd = hwnd
        self.root.after(0, self.embed_player)

    def wait_for_window(self, title: str, timeout: float) -> int | None:
        if os.name != "nt":
            return None
        deadline = time.time() + timeout
        while time.time() < deadline and not self.closing:
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                return int(hwnd)
            if self.process and self.process.poll() is not None:
                return None
            time.sleep(0.1)
        return None

    def embed_player(self) -> None:
        if not self.player_hwnd or self.closing:
            return
        self.video.update_idletasks()
        parent = self.video.winfo_id()
        user32.SetParent(self.player_hwnd, parent)
        user32.SetWindowLongW(self.player_hwnd, GWL_STYLE, WS_CHILD | WS_VISIBLE)
        user32.ShowWindow(self.player_hwnd, SW_SHOW)
        self.resize_player()
        self.overlay.place_forget()
        self.status.set("Live")
        self._set_overlay_visible(self.config.get("show_ptz", True) and self.ptz_supported)
        self.watch_process()

    def resize_player(self, _event=None) -> None:
        if self.player_hwnd and user32:
            width = max(1, self.video.winfo_width())
            height = max(1, self.video.winfo_height())
            user32.MoveWindow(self.player_hwnd, 0, 0, width, height, True)
        self._position_ptz_overlay()

    def watch_process(self) -> None:
        if self.closing or not self.process:
            return
        if self.process.poll() is not None:
            self.player_hwnd = None
            self.show_error("The camera stream stopped. Click Reconnect to try again.")
            return
        self.root.after(1000, self.watch_process)

    def show_error(self, detail: str) -> None:
        logging.error(detail)
        self.status.set("Not connected")
        self.overlay.configure(text=f"Could not open live view\n\n{detail}")
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")

    def stop_player(self) -> None:
        self.player_hwnd = None
        process, self.process = self.process, None
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def restart(self) -> None:
        self.start()

    def toggle_quality(self) -> None:
        self.stream = "stream2" if self.stream == "stream1" else "stream1"
        self.quality_button.configure(text=self.quality_label())
        self.start()

    def toggle_mute(self) -> None:
        self.muted = not self.muted
        self.mute_button.configure(text="🔇 Unmute" if self.muted else "🔊 Mute")
        self.start()

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def leave_fullscreen(self) -> None:
        if self.fullscreen:
            self.fullscreen = False
            self.root.attributes("-fullscreen", False)

    def close(self) -> None:
        self.closing = True
        self.stop_player()
        if self.ptz_overlay is not None and self.ptz_overlay.winfo_exists():
            self.ptz_overlay.destroy()
        if self.ptz.available:
            threading.Thread(target=self.ptz.stop, daemon=True).start()
        self.root.destroy()


def main() -> None:
    setup_logging()
    if os.name != "nt":
        fatal_dialog("This build is for Windows because it embeds ffplay using the Win32 API.")
        return
    if os.environ.get("TAPO_DEMO") == "1":
        config = apply_display_defaults(
            {
                "camera_name": "Demo Lion",
                "host": "127.0.0.1",
                "port": 554,
                "username": "demo",
                "stream": "stream1",
                "onvif_port": 2020,
                "ptz_speed": 0.5,
                "window_width": 1100,
                "window_height": 700,
            }
        )
        root = tk.Tk()
        LiveView(root, config, "demo", "demo")
        root.mainloop()
        return
    try:
        config = load_config()
        password = get_password(config)
        ffplay = find_executable("ffplay.exe")
        if not ffplay:
            raise RuntimeError(
                "ffplay.exe was not found. Install FFmpeg with 'winget install Gyan.FFmpeg', "
                "then close and reopen the app."
            )
    except Exception as exc:
        fatal_dialog(str(exc))
        return

    root = tk.Tk()
    LiveView(root, config, password, ffplay)
    root.mainloop()


if __name__ == "__main__":
    main()
