"""
Login Window
============
A simple identity-capture dialog shown before the main chat window.

The user selects their PersonID from a dropdown (populated from PERSON_IDS
in config.py) and clicks Sign In. No database query or authentication is
performed here.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from config import APP_TITLE, FONT_FAMILY, PERSON_IDS

# ── Colours (mirror chat_window palette) ─────────────────────────────────────
_C_ACCENT    = "#0078D4"   # Windows blue
_C_ACCENT_FG = "#FFFFFF"
_C_BG        = "#FFFFFF"
_C_BORDER    = "#D1D1D1"
_C_SYSTEM    = "#767676"
_C_STATUS_BG = "#F0F0F0"


class LoginWindow:
    """
    Blocking login dialog.

    Usage::

        win = LoginWindow()
        person_id = win.run()   # blocks until the user signs in or closes
        if person_id is None:
            sys.exit(0)         # user cancelled

    Internally the window creates its own ``tk.Tk`` root so it is
    completely independent of the main ``ChatWindow`` root created later.
    """

    def __init__(self) -> None:
        self._result: int | None = None

        self.root = tk.Tk()
        self._configure_root()
        self._build_header()
        self._build_body()
        self._setup_bindings()

    # ── Window setup ─────────────────────────────────────────────────────────

    def _configure_root(self) -> None:
        self.root.title(f"{APP_TITLE} — Sign In")
        self.root.geometry("380x230")
        self.root.resizable(False, False)
        self.root.configure(bg=_C_BG)
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - 380) // 2
        y = (self.root.winfo_screenheight() - 230) // 2
        self.root.geometry(f"+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_cancel)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_header(self) -> None:
        """Blue title strip across the top."""
        header = tk.Frame(self.root, bg=_C_ACCENT, height=56)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text=APP_TITLE,
            bg=_C_ACCENT,
            fg=_C_ACCENT_FG,
            font=(FONT_FAMILY, 13, "bold"),
            anchor=tk.W,
            padx=18,
        ).pack(fill=tk.BOTH, expand=True)

    def _build_body(self) -> None:
        body = tk.Frame(self.root, bg=_C_BG, padx=24, pady=20)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Select your Person ID to continue:",
            bg=_C_BG,
            fg="#1A1A1A",
            font=(FONT_FAMILY, 10),
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(0, 8))

        # Dropdown for PersonID
        self._combo_var = tk.StringVar(value=str(PERSON_IDS[0]))
        self._combo = ttk.Combobox(
            body,
            textvariable=self._combo_var,
            values=[str(pid) for pid in PERSON_IDS],
            font=(FONT_FAMILY, 11),
            state="readonly",
        )
        self._combo.pack(fill=tk.X, ipady=4)
        self._combo.focus_set()

        # Buttons
        btn_frame = tk.Frame(body, bg=_C_BG)
        btn_frame.pack(fill=tk.X, pady=(18, 0))

        self._sign_in_btn = tk.Button(
            btn_frame,
            text="Sign In",
            width=10,
            font=(FONT_FAMILY, 10),
            bg=_C_ACCENT,
            fg=_C_ACCENT_FG,
            activebackground="#005A9E",
            activeforeground=_C_ACCENT_FG,
            relief=tk.FLAT,
            cursor="hand2",
            state=tk.NORMAL,
            command=self._on_sign_in,
        )
        self._sign_in_btn.pack(side=tk.RIGHT, padx=(6, 0), ipady=4)

        tk.Button(
            btn_frame,
            text="Exit",
            width=10,
            font=(FONT_FAMILY, 10),
            bg="#F0F0F0",
            fg="#1A1A1A",
            activebackground="#D0D0D0",
            relief=tk.FLAT,
            cursor="hand2",
            command=self._on_cancel,
        ).pack(side=tk.RIGHT, ipady=4)

    def _setup_bindings(self) -> None:
        self.root.bind("<Return>",  lambda _e: self._on_sign_in())
        self.root.bind("<Escape>",  lambda _e: self._on_cancel())

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_sign_in(self) -> None:
        value = self._combo_var.get().strip()
        try:
            self._result = int(value)
        except ValueError:
            return
        self.root.destroy()

    def _on_cancel(self) -> None:
        self._result = None
        self.root.destroy()

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self) -> int | None:
        """Show the dialog and block until the user signs in or cancels.

        Returns the selected PersonID (``int``) or ``None`` if the dialog
        was closed without a selection.
        """
        self.root.mainloop()
        return self._result
