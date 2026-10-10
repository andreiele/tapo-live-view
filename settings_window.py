from __future__ import annotations

import tkinter as tk
from typing import Callable

from app_common import update_config
from modal import ModalPanel, Segmented, Switch
from theme import palette


class SettingsPanel(ModalPanel):
    """Settings, shown as a card inside the main window. Changes apply and save immediately."""

    def __init__(
        self,
        root: tk.Tk,
        config: dict,
        on_change: Callable[[dict], None],
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.config_data = config
        self.on_change = on_change
        self.theme_var = tk.StringVar(value=config.get("theme", "dark"))
        self.branding_var = tk.BooleanVar(value=config.get("show_branding", True))
        self.date_var = tk.BooleanVar(value=config.get("show_date", True))
        self.ptz_var = tk.BooleanVar(value=config.get("show_ptz", True))
        super().__init__(root, palette(config.get("theme")), "Settings", width=460, height=0, on_close=on_close)

    def build(self, body: tk.Frame) -> None:
        colors = self.colors

        self.section(body, "Appearance", first=True)
        row = self._row(body, "Theme", "Applies to every window in the app.")
        Segmented(row, colors, [("dark", "Dark"), ("light", "Light")], self.theme_var, self._changed).pack(side="right")

        self.section(body, "On-screen display")
        self._switch_row(body, "App branding", "Show “Tapo Live View” and the logo in the toolbar.", self.branding_var)
        self._switch_row(body, "Today's date", "Show the date next to the session timer.", self.date_var)

        self.section(body, "Controls")
        self._switch_row(body, "Pan/tilt pad", "Show the PTZ pad on cameras that can move.", self.ptz_var)

        footer = tk.Frame(body, bg=colors["bg"])
        footer.pack(side="bottom", fill="x", pady=(18, 0))
        tk.Label(
            footer, text="Changes are saved automatically.", bg=colors["bg"], fg=colors["text_dim"], font=("Segoe UI", 9)
        ).pack(side="left")
        self.button(footer, "Done", self.close).pack(side="right")

    def _row(self, parent: tk.Misc, title: str, description: str) -> tk.Frame:
        colors = self.colors
        row = tk.Frame(parent, bg=colors["surface"], padx=14, pady=10)
        row.pack(fill="x", pady=(0, 6))
        text = tk.Frame(row, bg=colors["surface"])
        text.pack(side="left", fill="x", expand=True)
        tk.Label(text, text=title, bg=colors["surface"], fg=colors["text"], font=("Segoe UI Semibold", 10)).pack(
            anchor="w"
        )
        tk.Label(
            text, text=description, bg=colors["surface"], fg=colors["text_dim"], font=("Segoe UI", 9)
        ).pack(anchor="w")
        return row

    def _switch_row(self, parent: tk.Misc, title: str, description: str, variable: tk.BooleanVar) -> None:
        row = self._row(parent, title, description)
        Switch(row, self.colors, variable, self._changed).pack(side="right", padx=(12, 0))

    def _changed(self) -> None:
        changes = {
            "theme": self.theme_var.get(),
            "show_branding": self.branding_var.get(),
            "show_date": self.date_var.get(),
            "show_ptz": self.ptz_var.get(),
        }
        theme_changed = changes["theme"] != self.colors["name"]
        update_config(self.config_data, **changes)
        self.on_change(changes)
        if theme_changed:
            # Re-render after the click handler returns; it lives in the old widgets.
            self.root.after_idle(lambda: self.rebuild(palette(changes["theme"])))
