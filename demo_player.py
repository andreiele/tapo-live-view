"""Standalone window used only by TAPO_DEMO=1 runs.

Stands in for ffplay so the embedding/PTZ-overlay code path can be exercised
(screenshots, QA) without a real camera: it opens a normal top-level window
containing the placeholder lion image, which live.py then finds by title and
reparents exactly like it does with the real ffplay window.
"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    title = sys.argv[1] if len(sys.argv) > 1 else "TapoDemoPlayer"
    root = tk.Tk()
    root.title(title)
    root.geometry("960x540")
    root.configure(bg="black")
    img = tk.PhotoImage(file=str(ROOT / "assets" / "lion.png"))
    label = tk.Label(root, image=img, bg="black")
    label.image = img
    label.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
