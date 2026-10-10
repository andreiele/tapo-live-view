from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parent
ICON_ICO = ROOT / "tapo.ico"
ICON_PNG = ROOT / "tapo.png"

ACCENT = "#2f9bf4"
ACCENT_HOVER = "#4dabf7"

DARK = {
    "name": "dark",
    "bg": "#121417",
    "bg_alt": "#1a1d21",
    "surface": "#1f2329",
    "surface_hover": "#2a2f36",
    "border": "#2c3038",
    "text": "#f2f3f5",
    "text_dim": "#9aa1ac",
    "video_bg": "#000000",
    "accent": ACCENT,
    "accent_hover": ACCENT_HOVER,
    "accent_text": "#08131f",
    "success": "#34c98f",
    "danger": "#f4544c",
    "overlay_bg": "#1a1d21",
    "overlay_fg": "#f2f3f5",
}

LIGHT = {
    "name": "light",
    "bg": "#f4f6f8",
    "bg_alt": "#e9ecef",
    "surface": "#ffffff",
    "surface_hover": "#eef1f4",
    "border": "#d7dbe0",
    "text": "#181a1c",
    "text_dim": "#5b6470",
    "video_bg": "#000000",
    "accent": ACCENT,
    "accent_hover": "#1c86e0",
    "accent_text": "#ffffff",
    "success": "#1f9d6f",
    "danger": "#d8362c",
    "overlay_bg": "#ffffff",
    "overlay_fg": "#181a1c",
}


def palette(name: str | None) -> dict:
    return LIGHT if name == "light" else DARK


def set_window_icon(window: tk.Misc) -> None:
    try:
        if ICON_ICO.exists():
            window.iconbitmap(default=str(ICON_ICO))
    except Exception:
        pass
    try:
        if ICON_PNG.exists():
            img = tk.PhotoImage(file=str(ICON_PNG))
            window.iconphoto(True, img)
            window._tapo_icon_ref = img  # keep a reference alive
    except Exception:
        pass


def apply_style(root: tk.Misc, colors: dict) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=colors["bg"])
    style.configure("Surface.TFrame", background=colors["surface"])
    style.configure("Toolbar.TFrame", background=colors["bg_alt"])

    style.configure(
        "TLabel",
        background=colors["bg"],
        foreground=colors["text"],
        font=("Segoe UI", 10),
    )
    style.configure(
        "Toolbar.TLabel",
        background=colors["bg_alt"],
        foreground=colors["text"],
        font=("Segoe UI", 10),
    )
    style.configure(
        "Brand.TLabel",
        background=colors["bg_alt"],
        foreground=colors["text"],
        font=("Segoe UI Semibold", 12),
    )
    style.configure(
        "Dim.TLabel",
        background=colors["bg_alt"],
        foreground=colors["text_dim"],
        font=("Segoe UI", 9),
    )
    style.configure(
        "DimSurface.TLabel",
        background=colors["surface"],
        foreground=colors["text_dim"],
        font=("Segoe UI", 9),
    )
    style.configure(
        "Heading.TLabel",
        background=colors["bg"],
        foreground=colors["text"],
        font=("Segoe UI Semibold", 18),
    )
    style.configure(
        "Status.TLabel",
        background=colors["bg_alt"],
        foreground=colors["success"],
        font=("Segoe UI", 9, "bold"),
    )

    style.configure(
        "TButton",
        background=colors["surface"],
        foreground=colors["text"],
        borderwidth=0,
        focusthickness=0,
        focuscolor=colors["surface"],
        padding=(10, 6),
        font=("Segoe UI", 10),
    )
    style.map(
        "TButton",
        background=[("active", colors["surface_hover"]), ("pressed", colors["surface_hover"])],
    )

    style.configure(
        "Icon.TButton",
        background=colors["bg_alt"],
        width=0,
        foreground=colors["text"],
        borderwidth=0,
        focusthickness=0,
        focuscolor=colors["bg_alt"],
        padding=(8, 6),
        font=("Segoe UI", 11),
    )
    style.map(
        "Icon.TButton",
        background=[("active", colors["surface_hover"]), ("pressed", colors["surface_hover"])],
    )

    style.configure(
        "Accent.TButton",
        background=colors["accent"],
        foreground=colors["accent_text"],
        borderwidth=0,
        focusthickness=0,
        focuscolor=colors["accent"],
        padding=(12, 7),
        font=("Segoe UI Semibold", 10),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", colors["surface"]),
            ("active", colors["accent_hover"]),
            ("pressed", colors["accent_hover"]),
        ],
        foreground=[("disabled", colors["text_dim"])],
    )

    # Icon button rendered in the "on" state (e.g. Multi view while active).
    style.configure(
        "Active.TButton",
        background=colors["accent"],
        width=0,
        foreground=colors["accent_text"],
        borderwidth=0,
        focusthickness=0,
        focuscolor=colors["accent"],
        padding=(8, 6),
        font=("Segoe UI", 11),
    )
    style.map(
        "Active.TButton",
        background=[("active", colors["accent_hover"]), ("pressed", colors["accent_hover"])],
    )

    style.configure(
        "Icon.TMenubutton",
        background=colors["bg_alt"],
        foreground=colors["text"],
        arrowcolor=colors["text"],
        borderwidth=0,
        relief="flat",
        padding=(8, 6),
        font=("Segoe UI", 11),
    )
    style.map(
        "Icon.TMenubutton",
        background=[("active", colors["surface_hover"]), ("pressed", colors["surface_hover"])],
    )

    style.configure(
        "TProgressbar",
        background=colors["accent"],
        troughcolor=colors["bg_alt"],
        bordercolor=colors["bg_alt"],
        lightcolor=colors["accent"],
        darkcolor=colors["accent"],
        thickness=6,
    )
    style.configure(
        "Video.Horizontal.TProgressbar",
        background=colors["accent"],
        troughcolor="#1c1f24",
        bordercolor="#1c1f24",
        lightcolor=colors["accent"],
        darkcolor=colors["accent"],
        thickness=4,
    )

    style.configure(
        "TEntry",
        fieldbackground=colors["surface"],
        foreground=colors["text"],
        insertcolor=colors["text"],
        borderwidth=1,
        padding=6,
    )
    style.configure("TRadiobutton", background=colors["bg"], foreground=colors["text"], font=("Segoe UI", 10))
    style.map("TRadiobutton", background=[("active", colors["bg"])])
    style.configure("TCheckbutton", background=colors["bg"], foreground=colors["text"], font=("Segoe UI", 10))
    style.map("TCheckbutton", background=[("active", colors["bg"])])

    style.configure(
        "Switch.TCheckbutton",
        background=colors["surface"],
        foreground=colors["text"],
        font=("Segoe UI", 10),
    )
    style.map("Switch.TCheckbutton", background=[("active", colors["surface"])])

    style.configure("TSeparator", background=colors["border"])

    return style
