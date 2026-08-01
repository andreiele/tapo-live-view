from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import threading
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import messagebox, ttk

from app_common import (
    APP_NAME,
    build_rtsp_url,
    fatal_dialog,
    find_executable,
    get_password,
    load_config,
    setup_logging,
    test_port,
)
from ptz import DEFAULT_ONVIF_PORT, PTZController

CREATE_NO_WINDOW = 0x08000000
SW_HIDE = 0
SW_SHOW = 5
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000

user32 = ctypes.windll.user32 if os.name == "nt" else None


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
        self.ptz_pad: tk.Frame | None = None

        camera_name = config["camera_name"]
        root.title(f"{camera_name} — {APP_NAME}")
        root.geometry(f"{config.get('window_width', 1100)}x{config.get('window_height', 700)}")
        root.minsize(640, 400)
        root.configure(bg="#111111")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<F11>", lambda _event: self.toggle_fullscreen())
        root.bind("<Escape>", lambda _event: self.leave_fullscreen())

        toolbar = ttk.Frame(root, padding=(10, 8))
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text=camera_name, font=("Segoe UI", 11, "bold")).pack(side="left")
        self.status = tk.StringVar(value="Connecting…")
        ttk.Label(toolbar, textvariable=self.status).pack(side="left", padx=16)

        ttk.Button(toolbar, text="Reconnect", command=self.restart).pack(side="right", padx=(6, 0))
        ttk.Button(toolbar, text="Fullscreen", command=self.toggle_fullscreen).pack(side="right", padx=(6, 0))
        self.mute_button = ttk.Button(toolbar, text="Unmute", command=self.toggle_mute)
        self.mute_button.pack(side="right", padx=(6, 0))
        self.quality_button = ttk.Button(toolbar, text=self.quality_label(), command=self.toggle_quality)
        self.quality_button.pack(side="right", padx=(6, 0))

        self.video = tk.Frame(root, bg="#000000")
        self.video.pack(fill="both", expand=True)
        self.video.bind("<Configure>", self.resize_player)

        self.overlay = tk.Label(
            self.video,
            text="Connecting to camera…",
            bg="#000000",
            fg="#eeeeee",
            font=("Segoe UI", 14),
        )
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")
        self.build_ptz_pad()
        root.after(150, self.start)
        root.after(150, self.init_ptz)

    def build_ptz_pad(self) -> None:
        pad = tk.Frame(self.video, bg="#1a1a1a", padx=6, pady=6)
        directions = [
            ("↖", -1, -1), ("↑", 0, -1), ("↗", 1, -1),
            ("←", -1, 0), ("⌂", 0, 0), ("→", 1, 0),
            ("↙", -1, 1), ("↓", 0, 1), ("↘", 1, 1),
        ]
        for index, (symbol, dx, dy) in enumerate(directions):
            row, col = divmod(index, 3)
            button = tk.Button(
                pad,
                text=symbol,
                width=3,
                font=("Segoe UI", 12),
                bg="#2a2a2a",
                fg="#eeeeee",
                activebackground="#444444",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
            )
            button.grid(row=row, column=col, padx=1, pady=1)
            if dx == 0 and dy == 0:
                button.configure(command=self.ptz_home)
            else:
                button.bind("<ButtonPress-1>", lambda _e, dx=dx, dy=dy: self.ptz_press(dx, dy))
                button.bind("<ButtonRelease-1>", lambda _e: self.ptz_release())
        self.ptz_pad = pad

    def init_ptz(self) -> None:
        threading.Thread(target=self._init_ptz_worker, daemon=True).start()

    def _init_ptz_worker(self) -> None:
        ok = self.ptz.connect()
        if ok:
            self.root.after(0, self.show_ptz_pad)
        else:
            logging.info("Pan/tilt not available for %s: %s", self.config["camera_name"], self.ptz.error)

    def show_ptz_pad(self) -> None:
        if self.ptz_pad is not None:
            self.ptz_pad.place(relx=1.0, rely=1.0, x=-14, y=-14, anchor="se")

    def ptz_press(self, dx: int, dy: int) -> None:
        pan = dx * self.ptz_speed
        tilt = -dy * self.ptz_speed
        threading.Thread(target=self.ptz.continuous_move, args=(pan, tilt), daemon=True).start()

    def ptz_release(self) -> None:
        threading.Thread(target=self.ptz.stop, daemon=True).start()

    def ptz_home(self) -> None:
        threading.Thread(target=self.ptz.goto_home, daemon=True).start()

    def quality_label(self) -> str:
        return "High quality" if self.stream == "stream1" else "Standard quality"

    def start(self) -> None:
        self.stop_player()
        self.overlay.configure(text="Connecting to camera…")
        self.overlay.place(relx=0.5, rely=0.5, anchor="center")
        self.status.set("Checking network…")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self) -> None:
        ok, detail = test_port(self.config["host"], int(self.config.get("port", 554)))
        if not ok:
            self.root.after(0, lambda: self.show_error(detail))
            return
        url = build_rtsp_url(self.config, self.password, self.stream)
        title = f"TapoPlayer-{os.getpid()}-{int(time.time() * 1000)}"
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
        logging.info("Starting ffplay for %s using %s", self.config["camera_name"], self.stream)
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
        self.watch_process()

    def resize_player(self, _event=None) -> None:
        if self.player_hwnd and user32:
            width = max(1, self.video.winfo_width())
            height = max(1, self.video.winfo_height())
            user32.MoveWindow(self.player_hwnd, 0, 0, width, height, True)

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
        self.mute_button.configure(text="Unmute" if self.muted else "Mute")
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
        if self.ptz.available:
            threading.Thread(target=self.ptz.stop, daemon=True).start()
        self.root.destroy()


def main() -> None:
    setup_logging()
    if os.name != "nt":
        fatal_dialog("This build is for Windows because it embeds ffplay using the Win32 API.")
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
