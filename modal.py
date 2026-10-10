"""In-window modal panels (Settings, About) and the small widgets they use.

The live view embeds native ffplay windows, which would paint over ordinary
Tk frames, so a panel is made of two borderless windows owned by the main
window: a translucent backdrop that covers its client area and a card centred
on top. Both follow the main window when it moves or resizes, so the panel
always looks like it lives inside the app.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable


def unbind_one(widget: tk.Misc, sequence: str, funcid: str) -> None:
    """Remove a single binding added with ``add="+"``.

    ``Misc.unbind(sequence, funcid)`` drops *every* binding for the sequence
    on Python < 3.13, which would also remove other screens' handlers.
    """
    script = widget.bind(sequence)
    if script:
        kept = [line for line in script.split("\n") if funcid not in line]
        widget.bind(sequence, "\n".join(kept))
    try:
        widget.deletecommand(funcid)
    except Exception:
        pass


class ModalPanel:
    def __init__(
        self,
        root: tk.Tk,
        colors: dict,
        title: str,
        width: int,
        height: int,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.colors = colors
        self.title = title
        self.width = width
        self.height = height
        self.on_close = on_close
        self.closed = False

        self.backdrop = tk.Toplevel(root)
        self.backdrop.overrideredirect(True)
        self.backdrop.transient(root)
        self.backdrop.configure(bg="#000000", cursor="arrow")
        try:
            self.backdrop.attributes("-alpha", 0.55)
        except Exception:
            pass
        self.backdrop.bind("<Button-1>", lambda _e: self.close())

        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.transient(root)
        self.window.bind("<Escape>", lambda _e: self.close())

        self._configure_id = root.bind("<Configure>", lambda _e: self._follow(), add="+")
        self._build_frame()
        self.build(self.body)
        self._fit()
        self._follow()
        self.window.lift()
        self.window.focus_force()
        self._keep_in_place()

    def _keep_in_place(self) -> None:
        # <Configure> covers normal moves/resizes; this also catches changes Tk
        # doesn't report (e.g. the window still settling right after launch).
        if self.closed:
            return
        self._follow(lift=False)
        self.root.after(250, self._keep_in_place)

    # ---------------------------------------------------------------- frame
    def _build_frame(self) -> None:
        colors = self.colors
        self.window.configure(bg=colors["border"])
        self.card = tk.Frame(self.window, bg=colors["bg"])
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(self.card, bg=colors["bg"], padx=24, pady=18)
        header.pack(fill="x")
        tk.Label(
            header, text=self.title, bg=colors["bg"], fg=colors["text"], font=("Segoe UI Semibold", 16)
        ).pack(side="left")
        close = tk.Label(
            header, text="✕", bg=colors["bg"], fg=colors["text_dim"], font=("Segoe UI", 12), cursor="hand2", padx=6
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self.close())
        close.bind("<Enter>", lambda _e: close.configure(fg=colors["text"]))
        close.bind("<Leave>", lambda _e: close.configure(fg=colors["text_dim"]))
        tk.Frame(self.card, bg=colors["border"], height=1).pack(fill="x")

        self.body = tk.Frame(self.card, bg=colors["bg"], padx=24, pady=18)
        self.body.pack(fill="both", expand=True)

    def rebuild(self, colors: dict) -> None:
        """Re-render with a new palette (used when the theme changes)."""
        self.colors = colors
        self.card.destroy()
        self._build_frame()
        self.build(self.body)
        self._fit()
        self._follow()

    def _fit(self) -> None:
        """Grow the card to fit its content (``height`` is only a minimum)."""
        self.card.update_idletasks()
        self.height = max(self.height, self.card.winfo_reqheight() + 2)

    def build(self, body: tk.Frame) -> None:  # overridden by subclasses
        pass

    def _follow(self, lift: bool = True) -> None:
        if self.closed:
            return
        root = self.root
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        card_w = min(self.width, w - 32)
        card_h = min(self.height, h - 32)
        backdrop = f"{w}x{h}+{x}+{y}"
        card = f"{card_w}x{card_h}+{x + (w - card_w) // 2}+{y + (h - card_h) // 2}"
        if self.backdrop.geometry() != backdrop:
            self.backdrop.geometry(backdrop)
        if self.window.geometry() != card:
            self.window.geometry(card)
        if lift:
            self.backdrop.lift()
            self.window.lift()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        unbind_one(self.root, "<Configure>", self._configure_id)
        self.window.destroy()
        self.backdrop.destroy()
        if self.on_close is not None:
            self.on_close()

    # -------------------------------------------------------------- helpers
    def section(self, parent: tk.Misc, text: str, first: bool = False) -> None:
        tk.Label(
            parent,
            text=text.upper(),
            bg=self.colors["bg"],
            fg=self.colors["text_dim"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w", pady=(0 if first else 16, 6))

    def button(self, parent: tk.Misc, text: str, command: Callable[[], None], accent: bool = True) -> tk.Label:
        colors = self.colors
        bg = colors["accent"] if accent else colors["surface"]
        hover = colors["accent_hover"] if accent else colors["surface_hover"]
        fg = colors["accent_text"] if accent else colors["text"]
        label = tk.Label(
            parent, text=text, bg=bg, fg=fg, font=("Segoe UI Semibold", 10), padx=18, pady=7, cursor="hand2"
        )
        label.bind("<Button-1>", lambda _e: command())
        label.bind("<Enter>", lambda _e: label.configure(bg=hover))
        label.bind("<Leave>", lambda _e: label.configure(bg=bg))
        return label


class Switch(tk.Canvas):
    """A pill-shaped on/off toggle bound to a BooleanVar."""

    W, H = 40, 22

    def __init__(self, parent: tk.Misc, colors: dict, variable: tk.BooleanVar, command: Callable[[], None]) -> None:
        super().__init__(
            parent, width=self.W, height=self.H, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2"
        )
        self.colors = colors
        self.variable = variable
        self.command = command
        self.bind("<Button-1>", self._toggle)
        self._draw()

    def _toggle(self, _event=None) -> None:
        self.variable.set(not self.variable.get())
        self._draw()
        self.command()

    def _draw(self) -> None:
        self.delete("all")
        on = self.variable.get()
        track = self.colors["accent"] if on else self.colors["border"]
        r = self.H // 2
        self.create_oval(0, 0, self.H, self.H, fill=track, outline=track)
        self.create_oval(self.W - self.H, 0, self.W, self.H, fill=track, outline=track)
        self.create_rectangle(r, 0, self.W - r, self.H, fill=track, outline=track)
        knob_x = self.W - r if on else r
        self.create_oval(knob_x - r + 3, 3, knob_x + r - 3, self.H - 3, fill="#ffffff", outline="#ffffff")


class Segmented(tk.Frame):
    """A row of mutually exclusive options, e.g. Dark | Light."""

    def __init__(
        self,
        parent: tk.Misc,
        colors: dict,
        options: list[tuple[str, str]],
        variable: tk.StringVar,
        command: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=colors["surface"], padx=3, pady=3)
        self.colors = colors
        self.variable = variable
        self.command = command
        self.labels: dict[str, tk.Label] = {}
        for value, text in options:
            label = tk.Label(self, text=text, font=("Segoe UI", 10), padx=16, pady=5, cursor="hand2")
            label.pack(side="left")
            label.bind("<Button-1>", lambda _e, v=value: self._select(v))
            self.labels[value] = label
        self._paint()

    def _select(self, value: str) -> None:
        if value == self.variable.get():
            return
        self.variable.set(value)
        self._paint()
        self.command()

    def _paint(self) -> None:
        for value, label in self.labels.items():
            selected = value == self.variable.get()
            label.configure(
                bg=self.colors["accent"] if selected else self.colors["surface"],
                fg=self.colors["accent_text"] if selected else self.colors["text"],
            )
