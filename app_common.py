from __future__ import annotations

import json
import logging
import os
import socket
import sys
from pathlib import Path
from urllib.parse import quote

APP_NAME = "Tapo Live View"
SERVICE_NAME = "tapo-live-view"
ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
LOG_PATH = ROOT / "tapo-live.log"


def setup_logging() -> None:
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError("config.json is missing. Run Setup.bat first.")
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    required = ("camera_name", "host", "username", "stream")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"config.json is missing: {', '.join(missing)}")
    return apply_display_defaults(data)


def save_config(data: dict) -> None:
    temp = CONFIG_PATH.with_suffix(".json.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    temp.replace(CONFIG_PATH)


DISPLAY_DEFAULTS = {
    "theme": "dark",
    "show_branding": True,
    "show_date": True,
    "show_ptz": True,
}


def apply_display_defaults(config: dict) -> dict:
    for key, value in DISPLAY_DEFAULTS.items():
        config.setdefault(key, value)
    return config


def update_config(config: dict, **changes) -> dict:
    config.update(changes)
    save_config(config)
    return config


def credential_key(config: dict) -> str:
    return f"{config['username']}@{config['host']}"


def save_password(config: dict, password: str) -> None:
    import keyring

    keyring.set_password(SERVICE_NAME, credential_key(config), password)


def get_password(config: dict) -> str:
    import keyring

    password = keyring.get_password(SERVICE_NAME, credential_key(config))
    if password is None:
        raise RuntimeError("Camera password is not in Windows Credential Manager. Run Setup.bat again.")
    return password


def build_rtsp_url(config: dict, password: str, stream: str | None = None) -> str:
    selected_stream = stream or config.get("stream", "stream1")
    username = quote(str(config["username"]), safe="")
    encoded_password = quote(password, safe="")
    host = str(config["host"]).strip()
    port = int(config.get("port", 554))
    return f"rtsp://{username}:{encoded_password}@{host}:{port}/{selected_stream}"


def test_port(host: str, port: int = 554, timeout: float = 2.5) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "Camera RTSP port is reachable."
    except socket.gaierror:
        return False, "The camera address could not be resolved. Check the IP address or hostname."
    except TimeoutError:
        return False, "The connection timed out. Confirm the PC and camera are on the same network."
    except OSError as exc:
        return False, f"Could not connect to {host}:{port}: {exc}"


def find_executable(name: str) -> str | None:
    from shutil import which

    found = which(name)
    if found:
        return found
    common = [
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "ffmpeg" / "bin" / name,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / name,
        ROOT / "ffmpeg" / "bin" / name,
    ]
    for path in common:
        if path.exists():
            return str(path)
    return None


def fatal_dialog(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)
