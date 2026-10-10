"""Loading screen and camera list shown before the live view.

Both are plain frames packed into the main window, so the app moves from
"starting up" to "choose a camera" to the live feed without ever opening a
new window.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from app_common import APP_NAME, camera_id
from theme import ICON_PNG


def _logo(parent: tk.Misc, bg: str, factor: int) -> tk.Label | None:
    try:
        image = tk.PhotoImage(file=str(ICON_PNG)).subsample(factor, factor)
    except Exception:
        return None
    label = tk.Label(parent, image=image, bg=bg)
    label.image = image
    return label


def _hover(card: tk.Frame, colors: dict) -> None:
    """Accent border while the pointer is anywhere over the card."""

    def leave(_e) -> None:
        widget = card.winfo_containing(*card.winfo_pointerxy())
        if widget is None or not str(widget).startswith(str(card)):
            card.configure(highlightbackground=colors["border"])

    card.bind("<Enter>", lambda _e: card.configure(highlightbackground=colors["accent"]))
    card.bind("<Leave>", leave)


class LoadingScreen:
    def __init__(self, parent: tk.Misc, colors: dict, message: str = "Starting…") -> None:
        self.frame = tk.Frame(parent, bg=colors["bg"])
        self.frame.pack(fill="both", expand=True)

        center = tk.Frame(self.frame, bg=colors["bg"])
        center.place(relx=0.5, rely=0.45, anchor="center")

        logo = _logo(center, colors["bg"], 3)
        if logo is not None:
            logo.pack(pady=(0, 14))
        ttk.Label(center, text=APP_NAME, style="Heading.TLabel").pack()
        self.status = tk.StringVar(value=message)
        tk.Label(
            center,
            textvariable=self.status,
            bg=colors["bg"],
            fg=colors["text_dim"],
            font=("Segoe UI", 10),
        ).pack(pady=(4, 16))
        self.progress = ttk.Progressbar(center, mode="indeterminate", length=260)
        self.progress.pack()
        self.progress.start(12)

    def set_status(self, text: str) -> None:
        if self.frame.winfo_exists():
            self.status.set(text)


class CameraSelector:
    """Grid of camera cards with live reachability, plus Add / Multi view."""

    COLUMNS = 3

    def __init__(
        self,
        root: tk.Tk,
        parent: tk.Misc,
        config: dict,
        colors: dict,
        statuses: dict[str, tuple[str, str]],
        probe: Callable[[dict], tuple[bool, str]],
        on_open: Callable[[dict], None],
        on_multi: Callable[[], None],
        on_add: Callable[[], None],
        on_remove: Callable[[dict], None],
        on_settings: Callable[[], None],
        on_about: Callable[[], None],
    ) -> None:
        self.root = root
        self.config = config
        self.colors = colors
        self.statuses = statuses
        self.probe = probe
        self.on_open = on_open
        self.cards: dict[str, dict] = {}

        self.frame = tk.Frame(parent, bg=colors["bg"])
        self.frame.pack(fill="both", expand=True)

        toolbar = ttk.Frame(self.frame, style="Toolbar.TFrame", padding=(14, 8))
        toolbar.pack(fill="x")
        brand = ttk.Frame(toolbar, style="Toolbar.TFrame")
        brand.pack(side="left")
        logo = _logo(brand, colors["bg_alt"], 12)
        if logo is not None:
            logo.pack(side="left", padx=(0, 8))
        ttk.Label(brand, text=APP_NAME, style="Brand.TLabel").pack(side="left")
        ttk.Button(toolbar, text="ℹ About", style="Icon.TButton", command=on_about).pack(side="right")
        ttk.Button(toolbar, text="⚙ Settings", style="Icon.TButton", command=on_settings).pack(side="right", padx=6)
        ttk.Button(toolbar, text="⟳ Refresh", style="Icon.TButton", command=self.refresh).pack(side="right")

        body = tk.Frame(self.frame, bg=colors["bg"], padx=28, pady=22)
        body.pack(fill="both", expand=True)

        header = tk.Frame(body, bg=colors["bg"])
        header.pack(fill="x")
        titles = tk.Frame(header, bg=colors["bg"])
        titles.pack(side="left")
        ttk.Label(titles, text="Your cameras", style="Heading.TLabel").pack(anchor="w")
        tk.Label(
            titles,
            text="Pick a camera to watch, or open them all side by side in multi view.",
            bg=colors["bg"],
            fg=colors["text_dim"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 0))

        cameras = config["cameras"]
        multi = ttk.Button(header, text=f"▦ Multi view ({len(cameras)})", style="Accent.TButton", command=on_multi)
        multi.pack(side="right")
        if len(cameras) < 2:
            multi.state(["disabled"])
        ttk.Button(header, text="＋ Add camera", command=on_add).pack(side="right", padx=(0, 8))

        grid = tk.Frame(body, bg=colors["bg"])
        grid.pack(fill="both", expand=True, pady=(22, 0))
        for column in range(self.COLUMNS):
            grid.columnconfigure(column, weight=1, uniform="card")

        for index, camera in enumerate(cameras):
            row, column = divmod(index, self.COLUMNS)
            card = self._card(grid, camera, on_remove)
            card.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        row, column = divmod(len(cameras), self.COLUMNS)
        self._add_card(grid, on_add).grid(row=row, column=column, sticky="nsew", padx=6, pady=6)

        for camera in cameras:
            if camera_id(camera) not in self.statuses:
                self._probe(camera)
            else:
                self._paint(camera_id(camera))

    # --------------------------------------------------------------- cards --
    def _card(self, parent: tk.Misc, camera: dict, on_remove: Callable[[dict], None]) -> tk.Frame:
        colors = self.colors
        surface = colors["surface"]
        card = tk.Frame(
            parent,
            bg=surface,
            highlightthickness=1,
            highlightbackground=colors["border"],
            padx=16,
            pady=14,
            cursor="hand2",
        )
        top = tk.Frame(card, bg=surface)
        top.pack(fill="x")
        dot = tk.Label(top, text="●", font=("Segoe UI", 11), bg=surface, fg=colors["text_dim"])
        dot.pack(side="left")
        name = tk.Label(top, text=camera["camera_name"], font=("Segoe UI Semibold", 13), bg=surface, fg=colors["text"])
        name.pack(side="left", padx=(6, 0))
        remove = tk.Label(top, text="✕", font=("Segoe UI", 10), bg=surface, fg=colors["text_dim"], cursor="hand2")
        remove.pack(side="right")
        remove.bind("<Button-1>", lambda _e: on_remove(camera))
        remove.bind("<Enter>", lambda _e: remove.configure(fg=colors["danger"]))
        remove.bind("<Leave>", lambda _e: remove.configure(fg=colors["text_dim"]))

        host = tk.Label(
            card,
            text=camera["host"],
            font=("Segoe UI", 9),
            bg=surface,
            fg=colors["text_dim"],
            wraplength=240,
            justify="left",
        )
        host.pack(anchor="w", pady=(4, 12))

        bottom = tk.Frame(card, bg=surface)
        bottom.pack(fill="x")
        state = tk.Label(bottom, text="Checking…", font=("Segoe UI", 9, "bold"), bg=surface, fg=colors["text_dim"])
        state.pack(side="left")
        open_label = tk.Label(bottom, text="Watch ▸", font=("Segoe UI Semibold", 10), bg=surface, fg=colors["accent"])
        open_label.pack(side="right")

        for widget in (card, top, dot, name, host, bottom, state, open_label):
            widget.bind("<Button-1>", lambda _e: self.on_open(camera))
        _hover(card, colors)

        self.cards[camera_id(camera)] = {"dot": dot, "state": state, "host": host, "camera": camera}
        return card

    def _add_card(self, parent: tk.Misc, on_add: Callable[[], None]) -> tk.Frame:
        colors = self.colors
        card = tk.Frame(
            parent,
            bg=colors["bg"],
            highlightthickness=1,
            highlightbackground=colors["border"],
            padx=16,
            pady=14,
            cursor="hand2",
        )
        plus = tk.Label(card, text="＋", font=("Segoe UI", 20), bg=colors["bg"], fg=colors["text_dim"])
        plus.pack(pady=(4, 0))
        label = tk.Label(card, text="Add camera", font=("Segoe UI", 10), bg=colors["bg"], fg=colors["text_dim"])
        label.pack(pady=(0, 6))
        for widget in (card, plus, label):
            widget.bind("<Button-1>", lambda _e: on_add())
        _hover(card, colors)
        return card

    # -------------------------------------------------------------- status --
    def refresh(self) -> None:
        for camera in self.config["cameras"]:
            self.statuses.pop(camera_id(camera), None)
            self._paint(camera_id(camera))
            self._probe(camera)

    def _probe(self, camera: dict) -> None:
        key = camera_id(camera)

        def worker() -> None:
            ok, detail = self.probe(camera)
            self.statuses[key] = ("online" if ok else "offline", detail)
            self.root.after(0, lambda: self._paint(key))

        threading.Thread(target=worker, daemon=True).start()

    def _paint(self, key: str) -> None:
        card = self.cards.get(key)
        if card is None or not card["dot"].winfo_exists():
            return
        colors = self.colors
        status, detail = self.statuses.get(key, ("checking", ""))
        text, color = {
            "checking": ("Checking…", colors["text_dim"]),
            "online": ("Online", colors["success"]),
            "offline": ("Offline", colors["danger"]),
        }[status]
        card["dot"].configure(fg=color)
        card["state"].configure(text=text, fg=color)
        host = card["camera"]["host"]
        card["host"].configure(text=f"{host}  ·  {detail}" if status == "offline" else host)

    def destroy(self) -> None:
        if self.frame.winfo_exists():
            self.frame.destroy()
