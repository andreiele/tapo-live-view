from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from app_common import APP_NAME
from theme import ICON_PNG, apply_style, palette, set_window_icon

GITHUB_URL = "https://github.com/andreiele/tapo-live-view"
VERSION = "1.2.0"


class AboutWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk, theme_name: str | None = None) -> None:
        super().__init__(parent)
        colors = palette(theme_name)

        self.title(f"About — {APP_NAME}")
        self.geometry("460x620")
        self.resizable(False, False)
        self.transient(parent)
        set_window_icon(self)
        self.configure(bg=colors["bg"])
        apply_style(self, colors)

        outer = ttk.Frame(self, padding=26)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        try:
            logo = tk.PhotoImage(file=str(ICON_PNG)).subsample(4, 4)
            logo_label = tk.Label(header, image=logo, bg=colors["bg"])
            logo_label.image = logo
            logo_label.pack(side="left", padx=(0, 12))
        except Exception:
            pass
        title_box = ttk.Frame(header)
        title_box.pack(side="left")
        ttk.Label(title_box, text=APP_NAME, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(title_box, text=f"Version {VERSION}", style="Dim.TLabel").pack(anchor="w")

        ttk.Separator(outer).pack(fill="x", pady=18)

        body = (
            "Tapo Live View is a small Windows desktop app that opens a TP-Link Tapo "
            "camera's local RTSP live feed in its own window.\n\n"
            "It talks directly to the camera over your home network — there is no "
            "browser, no cloud login and no Tapo account involved. Video is decoded "
            "locally with FFmpeg/ffplay and embedded straight into the app window for "
            "low-latency playback.\n\n"
            "What it does:\n"
            "  •  One-click live view from a desktop shortcut\n"
            "  •  High / standard quality switching, mute and fullscreen\n"
            "  •  On-screen pan/tilt controls for cameras that physically move\n"
            "  •  Light and dark themes, with a session timer and settings panel\n\n"
            "Camera passwords are stored in Windows Credential Manager, never in "
            "plain text on disk."
        )
        ttk.Label(outer, text=body, wraplength=364, justify="left").pack(anchor="w")

        ttk.Separator(outer).pack(fill="x", pady=18)

        link_row = ttk.Frame(outer)
        link_row.pack(fill="x")
        ttk.Label(link_row, text="Source & documentation:").pack(side="left")
        link = tk.Label(
            link_row,
            text="github.com/andreiele/tapo-live-view",
            fg=colors["accent"],
            bg=colors["bg"],
            cursor="hand2",
            font=("Segoe UI", 10, "underline"),
        )
        link.pack(side="left", padx=(6, 0))
        link.bind("<Button-1>", lambda _e: webbrowser.open(GITHUB_URL))

        ttk.Button(outer, text="Close", style="Accent.TButton", command=self.destroy).pack(anchor="e", pady=(18, 0))
