from __future__ import annotations

import ipaddress
import tkinter as tk
from tkinter import messagebox, ttk

from app_common import APP_NAME, save_config, save_password, setup_logging, test_port
from ptz import DEFAULT_ONVIF_PORT


class SetupWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_NAME} Setup")
        root.geometry("540x540")
        root.resizable(False, False)

        self.name = tk.StringVar(value="Living Room")
        self.host = tk.StringVar()
        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.stream = tk.StringVar(value="stream1")
        self.onvif_port = tk.StringVar(value=str(DEFAULT_ONVIF_PORT))
        self.status = tk.StringVar(value="Enter the camera account details created in the Tapo app.")

        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Tapo Live View", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Connect directly to a Tapo camera on your home network.",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 20))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        self._field(form, 0, "Camera name", self.name)
        self._field(form, 1, "Camera IP address", self.host)
        self._field(form, 2, "Camera account username", self.username)
        self._field(form, 3, "Camera account password", self.password, show="•")

        ttk.Label(form, text="Default quality").grid(row=4, column=0, sticky="w", pady=8)
        quality = ttk.Frame(form)
        quality.grid(row=4, column=1, sticky="w", pady=8)
        ttk.Radiobutton(quality, text="High (stream1)", variable=self.stream, value="stream1").pack(side="left")
        ttk.Radiobutton(quality, text="Standard (stream2)", variable=self.stream, value="stream2").pack(side="left", padx=(14, 0))
        self._field(form, 5, "Pan/tilt (ONVIF) port", self.onvif_port)
        form.columnconfigure(1, weight=1)

        note = (
            "In the Tapo app open Camera Settings → Advanced Settings → Camera Account. "
            "Create a separate username and password there; do not use your TP-Link login.\n"
            "If your camera physically pans and tilts, on-screen controls appear automatically "
            "in the live view — leave the ONVIF port at 2020 unless you changed it on the camera."
        )
        ttk.Label(outer, text=note, wraplength=485, foreground="#555555").pack(anchor="w", pady=(18, 8))
        ttk.Label(outer, textvariable=self.status, wraplength=485).pack(anchor="w", pady=(4, 14))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", side="bottom")
        ttk.Button(buttons, text="Test connection", command=self.test).pack(side="left")
        ttk.Button(buttons, text="Save setup", command=self.save).pack(side="right")

    @staticmethod
    def _field(parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, show: str | None = None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=8, padx=(0, 16))
        entry = ttk.Entry(parent, textvariable=variable, show=show, width=35)
        entry.grid(row=row, column=1, sticky="ew", pady=8)

    def values(self) -> dict:
        host = self.host.get().strip()
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("Enter the camera's numeric IP address, for example 192.168.1.52.") from exc
        if not self.name.get().strip():
            raise ValueError("Enter a camera name.")
        if not self.username.get().strip():
            raise ValueError("Enter the camera account username.")
        if not self.password.get():
            raise ValueError("Enter the camera account password.")
        onvif_text = self.onvif_port.get().strip() or str(DEFAULT_ONVIF_PORT)
        try:
            onvif_port = int(onvif_text)
        except ValueError as exc:
            raise ValueError("ONVIF port must be a number, for example 2020.") from exc
        return {
            "camera_name": self.name.get().strip(),
            "host": host,
            "port": 554,
            "username": self.username.get().strip(),
            "stream": self.stream.get(),
            "rtsp_transport": "tcp",
            "window_width": 1100,
            "window_height": 700,
            "onvif_port": onvif_port,
        }

    def test(self) -> bool:
        try:
            config = self.values()
        except ValueError as exc:
            messagebox.showwarning(APP_NAME, str(exc))
            return False
        self.status.set("Testing camera connection…")
        self.root.update_idletasks()
        ok, detail = test_port(config["host"], config["port"])
        self.status.set(detail)
        if not ok:
            messagebox.showerror(APP_NAME, detail)
        return ok

    def save(self) -> None:
        try:
            config = self.values()
            if not self.test():
                return
            save_config(config)
            save_password(config, self.password.get())
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Setup could not be saved:\n\n{exc}")
            return
        messagebox.showinfo(APP_NAME, "Setup saved. You can now run Run.bat or create the Desktop shortcut.")
        self.root.destroy()


def main() -> None:
    setup_logging()
    root = tk.Tk()
    SetupWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
