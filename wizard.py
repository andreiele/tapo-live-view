from __future__ import annotations

import argparse
import importlib.util
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from app_common import (
    APP_NAME,
    CONFIG_PATH,
    ROOT,
    fatal_dialog,
    find_executable,
    get_password,
    load_config,
    setup_logging,
)
from theme import apply_style, palette, set_window_icon

CREATE_NO_WINDOW = 0x08000000
VENV_DIR = ROOT / ".venv"


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
    if running_under_venv() and deps_installed():
        if force_setup or not CONFIG_PATH.exists():
            return "setup"
        return "live"
    return "install"


class Wizard:
    def __init__(self, root: tk.Tk, force_setup: bool, geometry: str | None) -> None:
        self.root = root
        self.force_setup = force_setup
        self.colors = palette("dark")
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        root.title(f"{APP_NAME} Setup")
        root.geometry(geometry or "680x560")
        root.minsize(560, 460)
        set_window_icon(root)
        apply_style(root, self.colors)
        root.configure(bg=self.colors["bg"])
        root.protocol("WM_DELETE_WINDOW", root.destroy)

        self.container = ttk.Frame(root, padding=0)
        self.container.pack(fill="both", expand=True)

        stage = initial_stage(force_setup)
        if stage == "install":
            self.show_install_stage()
        elif stage == "setup":
            self.show_setup_stage()
        else:
            self.show_live_stage()

    # -------------------------------------------------------------- install
    def show_install_stage(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()
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
        for child in self.container.winfo_children():
            child.destroy()
        from first_run import SetupWindow

        SetupWindow(self.root, container=self.container, on_saved=self._on_setup_saved, theme_name="dark")

    def _on_setup_saved(self, config: dict) -> None:
        for child in self.container.winfo_children():
            child.destroy()
        colors = self.colors
        screen = ttk.Frame(self.container, padding=24)
        screen.pack(fill="both", expand=True)
        center = ttk.Frame(screen)
        center.place(relx=0.5, rely=0.5, anchor="center")
        check = tk.Label(center, text="✓", font=("Segoe UI", 48, "bold"), fg=colors["success"], bg=colors["bg"])
        check.pack()
        ttk.Label(center, text="Connected", style="Heading.TLabel").pack(pady=(6, 0))
        ttk.Label(center, text="Opening the live view…", style="Dim.TLabel").pack()
        self.root.after(1100, lambda: self.show_live_stage(config))

    # ----------------------------------------------------------------- live
    def show_live_stage(self, config: dict | None = None) -> None:
        for child in self.container.winfo_children():
            child.destroy()
        self.container.destroy()
        from live import LiveView

        try:
            if config is None:
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
            self.root.destroy()
            return
        LiveView(self.root, config, password, ffplay)


def main() -> None:
    setup_logging()
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
