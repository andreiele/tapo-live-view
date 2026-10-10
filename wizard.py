from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from app_common import (
    APP_NAME,
    ROOT,
    apply_display_defaults,
    camera_id,
    fatal_dialog,
    find_executable,
    get_password,
    has_cameras,
    load_config,
    remove_camera,
    set_app_user_model_id,
    setup_logging,
    test_port,
)
from theme import apply_style, palette, set_window_icon

CREATE_NO_WINDOW = 0x08000000
VENV_DIR = ROOT / ".venv"
DEMO = os.environ.get("TAPO_DEMO") == "1"


def venv_python(name: str = "python.exe") -> Path:
    return VENV_DIR / "Scripts" / name


def running_under_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except Exception:
        return False


def deps_installed() -> bool:
    return importlib.util.find_spec("keyring") is not None and importlib.util.find_spec("onvif") is not None


def initial_stage(force_setup: bool) -> str:
    if DEMO:
        return "app"
    if running_under_venv() and deps_installed():
        if force_setup or not has_cameras():
            return "setup"
        return "app"
    return "install"


def demo_config() -> dict:
    """Stand-in cameras for TAPO_DEMO=1 runs (screenshots/QA, no hardware)."""
    names = ("Demo Lion", "Front Door", "Garden", "Garage")
    cameras = [
        {"camera_name": name, "host": f"127.0.0.{index}", "port": 554, "username": "demo", "stream": "stream1"}
        for index, name in enumerate(names, start=1)
    ]
    return apply_display_defaults({"cameras": cameras})


def app_geometry() -> str:
    try:
        config = load_config()
    except Exception:
        config = apply_display_defaults({})
    return f"{config['window_width']}x{config['window_height']}"


class Wizard:
    """The app's single window: install → setup → loading → cameras → live."""

    def __init__(self, root: tk.Tk, force_setup: bool, geometry: str | None) -> None:
        self.root = root
        self.force_setup = force_setup
        self.colors = palette("dark")
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.config: dict | None = None
        self.passwords: dict[str, str | None] = {}
        self.ffplay = ""
        self.statuses: dict[str, tuple[str, str]] = {}
        self.live = None
        self.panel = None

        stage = initial_stage(force_setup)
        if stage == "app" and not DEMO:
            try:
                self.colors = palette(load_config().get("theme"))
            except Exception:
                pass
        root.title(APP_NAME if stage == "app" else f"{APP_NAME} Setup")
        root.geometry(geometry or (app_geometry() if stage == "app" else "680x560"))
        root.minsize(560, 520)
        set_window_icon(root)
        apply_style(root, self.colors)
        root.configure(bg=self.colors["bg"])
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.container = ttk.Frame(root, padding=0)
        self.container.pack(fill="both", expand=True)

        if stage == "install":
            self.show_install_stage()
        elif stage == "setup":
            self.show_setup_stage()
        else:
            self.show_loading_stage()

    def _clear(self) -> None:
        self._close_panel()
        if self.live is not None:
            self.live.teardown()
            self.live = None
        for child in self.container.winfo_children():
            child.destroy()

    def _close_panel(self) -> None:
        if self.panel is not None:
            panel, self.panel = self.panel, None
            panel.close()

    def close(self) -> None:
        self._close_panel()
        if self.live is not None:
            self.live.teardown()
            self.live = None
        self.root.destroy()

    # -------------------------------------------------------------- install
    def show_install_stage(self) -> None:
        self._clear()
        colors = self.colors

        pad = ttk.Frame(self.container, padding=24)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text="Setting up Tapo Live View", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            pad,
            text="This only happens once. Installing a local Python environment and dependencies…",
            style="Dim.TLabel",
        ).pack(anchor="w", pady=(2, 14))

        self.progress = ttk.Progressbar(pad, mode="indeterminate")
        self.progress.pack(fill="x", pady=(0, 12))
        self.progress.start(12)

        log_frame = tk.Frame(pad, bg="#0c0e10", highlightthickness=1, highlightbackground=colors["border"])
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_frame,
            bg="#0c0e10",
            fg="#c7f7d4",
            insertbackground="#c7f7d4",
            font=("Consolas", 10),
            relief="flat",
            padx=10,
            pady=8,
            state="disabled",
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True)

        self.install_status = ttk.Label(pad, text="Starting…", style="Dim.TLabel")
        self.install_status.pack(anchor="w", pady=(10, 0))

        threading.Thread(target=self._run_install, daemon=True).start()
        self.root.after(100, self._drain_log)

    def _log(self, line: str) -> None:
        self.log_queue.put(line)

    def _drain_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", line + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        if getattr(self, "_install_done", False):
            return
        self.root.after(100, self._drain_log)

    def _stream(self, args: list[str]) -> int:
        try:
            process = subprocess.Popen(
                args,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._log(f"! Could not start: {exc}")
            return 1
        assert process.stdout is not None
        for line in process.stdout:
            self._log(line.rstrip())
        return process.wait()

    def _find_system_python(self) -> list[str]:
        for candidate in (["py", "-3"], ["python"], ["python3"]):
            if shutil.which(candidate[0]):
                return candidate
        return [sys.executable]

    def _run_install(self) -> None:
        self._log(f"{APP_NAME} — first-time setup")
        self._log("=" * 40)
        try:
            if not venv_python().exists():
                self._log("Creating a local Python environment (.venv)…")
                base = self._find_system_python()
                code = self._stream(base + ["-m", "venv", str(VENV_DIR)])
                if code != 0 or not venv_python().exists():
                    self._fail("Could not create the Python virtual environment.")
                    return
                self._log("Environment created.")
            else:
                self._log("Python environment already present.")

            self._log("")
            self._log("Upgrading pip…")
            self._stream([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"])

            self._log("")
            self._log("Installing required packages (keyring, onvif-zeep)…")
            code = self._stream(
                [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")]
            )
            if code != 0:
                self._fail("Package installation failed. Check your internet connection and try again.")
                return

            self._log("")
            if shutil.which("ffplay"):
                self._log("FFmpeg / ffplay found on PATH.")
            else:
                self._log("FFmpeg / ffplay was not found.")
                if shutil.which("winget"):
                    self._log("Installing FFmpeg with winget (this can take a minute)…")
                    self._stream(
                        ["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--accept-package-agreements", "--accept-source-agreements"]
                    )
                else:
                    self._log("Install FFmpeg manually from https://www.gyan.dev/ffmpeg/builds/ before using the live view.")

            self._log("")
            self._log("Setup complete. Continuing…")
            self.root.after(0, self._relaunch_under_venv)
        except Exception as exc:
            self._fail(f"Unexpected error: {exc}")

    def _fail(self, message: str) -> None:
        self._install_done = True
        self._log("")
        self._log(f"ERROR: {message}")
        self.root.after(0, lambda: self.install_status.configure(text=message))
        self.root.after(0, self.progress.stop)

    def _relaunch_under_venv(self) -> None:
        self._install_done = True
        self.progress.stop()
        try:
            geometry = f"{self.root.winfo_width()}x{self.root.winfo_height()}+{self.root.winfo_x()}+{self.root.winfo_y()}"
        except Exception:
            geometry = None
        args = [str(venv_python("pythonw.exe")), str(ROOT / "wizard.py")]
        if self.force_setup:
            args.append("--setup")
        if geometry:
            args.append(f"--geometry={geometry}")
        try:
            subprocess.Popen(args, cwd=str(ROOT), creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except Exception as exc:
            fatal_dialog(f"Could not continue setup: {exc}")
        self.root.destroy()

    # ---------------------------------------------------------------- setup
    def show_setup_stage(self) -> None:
        from first_run import SetupWindow

        self._clear()
        count = len(self.config["cameras"]) if self.config else 0
        self.root.title(f"{APP_NAME} Setup")
        SetupWindow(
            self.root,
            container=self.container,
            on_saved=self._on_setup_saved,
            theme_name=self.colors["name"],
            on_cancel=self.show_selector if count else None,
            default_name="Living Room" if count == 0 else f"Camera {count + 1}",
        )

    def _on_setup_saved(self, _camera: dict) -> None:
        self._clear()
        colors = self.colors
        screen = ttk.Frame(self.container, padding=24)
        screen.pack(fill="both", expand=True)
        center = ttk.Frame(screen)
        center.place(relx=0.5, rely=0.5, anchor="center")
        check = tk.Label(center, text="✓", font=("Segoe UI", 48, "bold"), fg=colors["success"], bg=colors["bg"])
        check.pack()
        ttk.Label(center, text="Connected", style="Heading.TLabel").pack(pady=(6, 0))
        ttk.Label(center, text="Loading your cameras…", style="Dim.TLabel").pack()
        self.root.after(1100, lambda: self.show_loading_stage("Loading cameras…"))

    # -------------------------------------------------------------- loading
    def show_loading_stage(self, message: str = "Starting…") -> None:
        from selector import LoadingScreen

        self._clear()
        self._grow_to_app_size()
        self.root.title(APP_NAME)
        self.loading = LoadingScreen(self.container, self.colors, message)
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _grow_to_app_size(self) -> None:
        """Coming from the compact setup window, grow to the live-view size."""
        self.root.update_idletasks()
        width, height = (int(value) for value in app_geometry().split("x"))
        current_w, current_h = self.root.winfo_width(), self.root.winfo_height()
        if current_w < width - 50 or current_h < height - 50:
            x = max(0, self.root.winfo_x() - (width - current_w) // 2)
            y = max(0, self.root.winfo_y() - (height - current_h) // 2)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(720, 520)

    def _set_loading_status(self, text: str) -> None:
        self.root.after(0, lambda: self.loading.set_status(text))

    def _load_worker(self) -> None:
        try:
            if DEMO:
                config = demo_config()
                passwords = {camera_id(camera): "demo" for camera in config["cameras"]}
                ffplay = "demo"
            else:
                self._set_loading_status("Reading configuration…")
                config = load_config()
                self._set_loading_status("Looking for FFmpeg…")
                ffplay = find_executable("ffplay.exe")
                if not ffplay:
                    raise RuntimeError(
                        "ffplay.exe was not found. Install FFmpeg with 'winget install Gyan.FFmpeg', "
                        "then close and reopen the app."
                    )
                self._set_loading_status("Unlocking camera credentials…")
                passwords = {}
                for camera in config["cameras"]:
                    try:
                        passwords[camera_id(camera)] = get_password(camera)
                    except Exception as exc:
                        logging.warning("No password for %s: %s", camera["camera_name"], exc)
                        passwords[camera_id(camera)] = None
        except Exception as exc:
            message = str(exc)
            self.root.after(0, lambda: self._fatal(message))
            return
        self.root.after(0, lambda: self._on_loaded(config, passwords, ffplay))

    def _fatal(self, message: str) -> None:
        messagebox.showerror(APP_NAME, message)
        self.close()

    def _on_loaded(self, config: dict, passwords: dict, ffplay: str) -> None:
        self.config = config
        self.passwords = passwords
        self.ffplay = ffplay
        self.statuses = {}
        self._apply_theme(palette(config.get("theme")))
        if config["cameras"]:
            self.show_selector()
        else:
            self.show_setup_stage()

    def _apply_theme(self, colors: dict) -> None:
        self.colors = colors
        apply_style(self.root, colors)
        self.root.configure(bg=colors["bg"])

    # ------------------------------------------------------------- selector
    def _probe(self, camera: dict) -> tuple[bool, str]:
        if DEMO:
            return True, "Demo camera"
        return test_port(camera["host"], int(camera.get("port", 554)))

    def show_selector(self) -> None:
        from about_window import AboutPanel
        from selector import CameraSelector

        self._clear()
        self.root.title(APP_NAME)
        CameraSelector(
            self.root,
            self.container,
            self.config,
            self.colors,
            self.statuses,
            probe=self._probe,
            on_open=lambda camera: self.show_live("single", camera),
            on_multi=lambda: self.show_live("multi"),
            on_add=self.show_setup_stage,
            on_remove=self._remove_camera,
            on_settings=self._open_settings,
            on_about=lambda: self._show_panel(AboutPanel(self.root, self.config.get("theme"))),
        )

    def _show_panel(self, panel) -> None:
        self._close_panel()
        self.panel = panel

    def _open_settings(self) -> None:
        from settings_window import SettingsPanel

        def changed(changes: dict) -> None:
            if palette(changes.get("theme"))["name"] != self.colors["name"]:
                self._apply_theme(palette(changes.get("theme")))
                panel, self.panel = self.panel, None  # keep the open panel across the re-render
                self.show_selector()
                self.panel = panel

        self._show_panel(SettingsPanel(self.root, self.config, changed))

    def _remove_camera(self, camera: dict) -> None:
        if DEMO:
            return
        confirmed = messagebox.askyesno(
            APP_NAME,
            f"Remove “{camera['camera_name']}” ({camera['host']}) from {APP_NAME}?\n\n"
            "Its saved password is deleted too. You can add it again any time.",
        )
        if not confirmed:
            return
        remove_camera(self.config, camera)
        self.passwords.pop(camera_id(camera), None)
        self.statuses.pop(camera_id(camera), None)
        if self.config["cameras"]:
            self.show_selector()
        else:
            self.show_setup_stage()

    # ----------------------------------------------------------------- live
    def show_live(self, mode: str, camera: dict | None = None) -> None:
        from live import LiveView

        self._clear()
        self.live = LiveView(
            self.root,
            self.container,
            self.config,
            self.passwords,
            self.ffplay,
            mode=mode,
            camera=camera,
            on_back=self._back_to_selector,
            on_theme_change=self._apply_theme,
            demo=DEMO,
        )

    def _back_to_selector(self) -> None:
        self.live = None
        self.show_selector()


def main() -> None:
    setup_logging()
    set_app_user_model_id()
    if os.name != "nt":
        fatal_dialog("This build is for Windows because it embeds ffplay using the Win32 API.")
        return

    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--geometry", default=None)
    args = parser.parse_args()

    root = tk.Tk()
    Wizard(root, force_setup=args.setup, geometry=args.geometry)
    root.mainloop()


if __name__ == "__main__":
    main()
