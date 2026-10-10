from __future__ import annotations

import tkinter as tk
import webbrowser
from typing import Callable

from app_common import APP_NAME
from modal import ModalPanel
from theme import ICON_PNG, palette

GITHUB_URL = "https://github.com/andreiele/tapo-live-view"
VERSION = "1.3.0"

FEATURES = (
    "Several cameras, with a camera picker and multi view",
    "HD / SD quality switching, mute and fullscreen",
    "On-screen pan/tilt for cameras that physically move",
    "Light and dark themes, session timer and settings",
)


class AboutPanel(ModalPanel):
    def __init__(self, root: tk.Tk, theme_name: str | None = None, on_close: Callable[[], None] | None = None) -> None:
        super().__init__(root, palette(theme_name), "About", width=480, height=0, on_close=on_close)

    def build(self, body: tk.Frame) -> None:
        colors = self.colors
        bg = colors["bg"]

        header = tk.Frame(body, bg=bg)
        header.pack(fill="x")
        try:
            logo = tk.PhotoImage(file=str(ICON_PNG)).subsample(4, 4)
            logo_label = tk.Label(header, image=logo, bg=bg)
            logo_label.image = logo
            logo_label.pack(side="left", padx=(0, 14))
        except Exception:
            pass
        titles = tk.Frame(header, bg=bg)
        titles.pack(side="left")
        tk.Label(titles, text=APP_NAME, bg=bg, fg=colors["text"], font=("Segoe UI Semibold", 15)).pack(anchor="w")
        tk.Label(
            titles,
            text=f"  Version {VERSION}  ",
            bg=colors["surface"],
            fg=colors["text_dim"],
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(4, 0))

        tk.Label(
            body,
            text=(
                "Watch your TP-Link Tapo cameras live, straight from your home network. "
                "No browser, no cloud login — video is decoded locally with FFmpeg."
            ),
            bg=bg,
            fg=colors["text"],
            font=("Segoe UI", 10),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(16, 12))

        features = tk.Frame(body, bg=colors["surface"], padx=14, pady=10)
        features.pack(fill="x")
        for feature in FEATURES:
            row = tk.Frame(features, bg=colors["surface"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text="✓", bg=colors["surface"], fg=colors["success"], font=("Segoe UI Semibold", 10)).pack(
                side="left"
            )
            tk.Label(
                row, text=feature, bg=colors["surface"], fg=colors["text"], font=("Segoe UI", 10)
            ).pack(side="left", padx=(8, 0))

        tk.Label(
            body,
            text="🔒  Camera passwords live in Windows Credential Manager, never in plain text.",
            bg=bg,
            fg=colors["text_dim"],
            font=("Segoe UI", 9),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(12, 0))

        footer = tk.Frame(body, bg=bg)
        footer.pack(side="bottom", fill="x", pady=(20, 0))
        self.button(footer, "Close", self.close).pack(side="right")
        self.button(footer, "View on GitHub ↗", lambda: webbrowser.open(GITHUB_URL), accent=False).pack(side="left")
