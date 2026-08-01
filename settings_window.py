from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from app_common import APP_NAME, update_config
from theme import apply_style, palette, set_window_icon


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk, config: dict, on_change: Callable[[dict], None]) -> None:
        super().__init__(parent)
        self.config_data = config
        self.on_change = on_change
        self.colors = palette(config.get("theme"))

        self.title(f"Settings — {APP_NAME}")
        self.geometry("380x420")
        self.resizable(False, False)
        self.transient(parent)
        set_window_icon(self)
        self.configure(bg=self.colors["bg"])
        apply_style(self, self.colors)

        self.theme_var = tk.StringVar(value=config.get("theme", "dark"))
        self.branding_var = tk.BooleanVar(value=config.get("show_branding", True))
        self.date_var = tk.BooleanVar(value=config.get("show_date", True))
        self.ptz_var = tk.BooleanVar(value=config.get("show_ptz", True))

        outer = ttk.Frame(self, padding=22)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Settings", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Changes apply immediately and are saved automatically.",
            style="Dim.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        self._section(outer, "Appearance")
        theme_row = ttk.Frame(outer)
        theme_row.pack(fill="x", pady=(6, 14))
        ttk.Radiobutton(
            theme_row, text="Dark", value="dark", variable=self.theme_var, command=self._changed
        ).pack(side="left")
        ttk.Radiobutton(
            theme_row, text="Light", value="light", variable=self.theme_var, command=self._changed
        ).pack(side="left", padx=(16, 0))

        self._section(outer, "On-screen display")
        ttk.Checkbutton(
            outer, text="Show “Tapo Live View” branding", variable=self.branding_var, command=self._changed
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            outer, text="Show today's date", variable=self.date_var, command=self._changed
        ).pack(anchor="w", pady=4)

        self._section(outer, "Controls")
        ttk.Checkbutton(
            outer, text="Show pan/tilt (PTZ) control pad", variable=self.ptz_var, command=self._changed
        ).pack(anchor="w", pady=4)

        ttk.Separator(outer).pack(fill="x", pady=16)
        ttk.Button(outer, text="Close", style="Accent.TButton", command=self.destroy).pack(anchor="e")

    def _section(self, parent: ttk.Frame, title: str) -> None:
        ttk.Label(parent, text=title.upper(), style="Dim.TLabel").pack(anchor="w", pady=(4, 0))

    def _changed(self) -> None:
        changes = {
            "theme": self.theme_var.get(),
            "show_branding": self.branding_var.get(),
            "show_date": self.date_var.get(),
            "show_ptz": self.ptz_var.get(),
        }
        update_config(self.config_data, **changes)
        self.colors = palette(changes["theme"])
        apply_style(self, self.colors)
        self.configure(bg=self.colors["bg"])
        self.on_change(changes)
