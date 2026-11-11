"""Dark studio theme, reusable Simple/Avancé toggle, and scrollable control panel."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

COLORS = {
    "bg": "#0B1120",
    "surface": "#111827",
    "card": "#1E293B",
    "card_border": "#334155",
    "accent": "#38BDF8",
    "accent_hover": "#0EA5E9",
    "success": "#10B981",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "violet": "#A78BFA",
    "text": "#F8FAFC",
    "text_muted": "#94A3B8",
    "input_bg": "#0F172A",
}


def apply_studio_theme(root: tk.Misc) -> None:
    """Apply clean modern dark studio styling to ttk and root widgets."""
    root.configure(bg=COLORS["bg"])
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 9))
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Surface.TFrame", background=COLORS["surface"])
    style.configure("Card.TFrame", background=COLORS["card"])

    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Surface.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
    style.configure("Card.TLabel", background=COLORS["card"], foreground=COLORS["text"])
    style.configure("Muted.TLabel", background=COLORS["surface"], foreground=COLORS["text_muted"], font=("Segoe UI", 8))
    style.configure("CardMuted.TLabel", background=COLORS["card"], foreground=COLORS["text_muted"], font=("Segoe UI", 8))
    style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 13, "bold"))
    style.configure("Section.TLabel", background=COLORS["card"], foreground=COLORS["accent"], font=("Segoe UI", 9, "bold"))

    style.configure(
        "TLabelframe",
        background=COLORS["card"],
        foreground=COLORS["accent"],
        bordercolor=COLORS["card_border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=COLORS["card"],
        foreground=COLORS["accent"],
        font=("Segoe UI", 9, "bold"),
    )

    style.configure(
        "TNotebook",
        background=COLORS["bg"],
        borderwidth=0,
        tabmargins=[4, 4, 4, 0],
    )
    style.configure(
        "TNotebook.Tab",
        background=COLORS["surface"],
        foreground=COLORS["text_muted"],
        padding=[14, 8],
        font=("Segoe UI", 9, "bold"),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", COLORS["card"]), ("active", "#1A2438")],
        foreground=[("selected", COLORS["accent"]), ("active", COLORS["text"])],
    )

    style.configure(
        "TButton",
        background=COLORS["card"],
        foreground=COLORS["text"],
        bordercolor=COLORS["card_border"],
        padding=[10, 6],
        font=("Segoe UI", 9),
    )
    style.map(
        "TButton",
        background=[("active", "#283548"), ("disabled", "#172030")],
        foreground=[("disabled", "#475569")],
    )

    style.configure(
        "Accent.TButton",
        background="#0284C7",
        foreground="#FFFFFF",
        padding=[12, 7],
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("active", "#0369A1"), ("disabled", "#1E3A5F")],
        foreground=[("disabled", "#64748B")],
    )

    style.configure(
        "Success.TButton",
        background="#059669",
        foreground="#FFFFFF",
        padding=[12, 7],
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "Success.TButton",
        background=[("active", "#047857"), ("disabled", "#144235")],
        foreground=[("disabled", "#64748B")],
    )

    style.configure(
        "Danger.TButton",
        background="#DC2626",
        foreground="#FFFFFF",
        padding=[12, 7],
        font=("Segoe UI", 9, "bold"),
    )
    style.map("Danger.TButton", background=[("active", "#B91C1C")])

    style.configure(
        "TCheckbutton",
        background=COLORS["card"],
        foreground=COLORS["text"],
        font=("Segoe UI", 9),
    )
    style.map("TCheckbutton", background=[("active", COLORS["card"])])

    style.configure(
        "TRadiobutton",
        background=COLORS["card"],
        foreground=COLORS["text"],
        font=("Segoe UI", 9),
    )
    style.map("TRadiobutton", background=[("active", COLORS["card"])])

    style.configure(
        "TCombobox",
        fieldbackground=COLORS["input_bg"],
        background=COLORS["card"],
        foreground=COLORS["text"],
        arrowcolor=COLORS["accent"],
        bordercolor=COLORS["card_border"],
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["input_bg"])],
        foreground=[("readonly", COLORS["text"])],
        selectbackground=[("readonly", COLORS["accent"])],
        selectforeground=[("readonly", "#0B1120")],
    )

    style.configure(
        "TEntry",
        fieldbackground=COLORS["input_bg"],
        foreground=COLORS["text"],
        insertcolor=COLORS["text"],
        bordercolor=COLORS["card_border"],
    )
    style.configure(
        "TSpinbox",
        fieldbackground=COLORS["input_bg"],
        background=COLORS["card"],
        foreground=COLORS["text"],
        arrowcolor=COLORS["accent"],
    )
    style.configure(
        "Horizontal.TScale",
        background=COLORS["card"],
        troughcolor=COLORS["input_bg"],
    )
    style.configure(
        "Horizontal.TProgressbar",
        background=COLORS["accent"],
        troughcolor=COLORS["input_bg"],
        borderwidth=0,
    )


class SimpleAdvancedToggle(tk.Frame):
    """Consistent segmented Simple / Avancé toggle placed at the top of every tab."""

    def __init__(self, parent: tk.Misc, on_change: Callable[[bool], None], initial_advanced: bool = False):
        super().__init__(parent, bg=COLORS["input_bg"], highlightbackground=COLORS["card_border"], highlightthickness=1)
        self.on_change = on_change
        self.is_advanced = initial_advanced

        self.btn_simple = tk.Button(
            self,
            text="⚡ Simple",
            bd=0,
            padx=12,
            pady=4,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            command=lambda: self.set_advanced(False),
        )
        self.btn_simple.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.btn_adv = tk.Button(
            self,
            text="⚙️ Avancé",
            bd=0,
            padx=12,
            pady=4,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            command=lambda: self.set_advanced(True),
        )
        self.btn_adv.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._refresh_styles()

    def set_advanced(self, advanced: bool) -> None:
        if self.is_advanced == advanced:
            return
        self.is_advanced = advanced
        self._refresh_styles()
        self.on_change(self.is_advanced)

    def _refresh_styles(self) -> None:
        if self.is_advanced:
            self.btn_simple.configure(bg=COLORS["input_bg"], fg=COLORS["text_muted"], activebackground=COLORS["card"])
            self.btn_adv.configure(bg=COLORS["violet"], fg="#0B1120", activebackground=COLORS["violet"])
        else:
            self.btn_simple.configure(bg=COLORS["accent"], fg="#0B1120", activebackground=COLORS["accent"])
            self.btn_adv.configure(bg=COLORS["input_bg"], fg=COLORS["text_muted"], activebackground=COLORS["card"])


class GeneratorTabShell(ttk.Frame):
    """Two-column shell (scrollable controls with Simple/Avancé + right preview stage)."""

    def __init__(self, parent: tk.Misc, title: str, subtitle: str):
        super().__init__(parent, padding=10)
        self.columnconfigure(0, weight=0, minsize=355)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # Left column: scrollable controls container
        left_wrap = tk.Frame(self, bg=COLORS["surface"], highlightbackground=COLORS["card_border"], highlightthickness=1, width=355)
        left_wrap.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        left_wrap.pack_propagate(False)

        self._ctrl_canvas = tk.Canvas(left_wrap, bg=COLORS["surface"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(left_wrap, orient=tk.VERTICAL, command=self._ctrl_canvas.yview)
        self._ctrl_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._ctrl_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.controls_body = ttk.Frame(self._ctrl_canvas, style="Surface.TFrame", padding=12)
        self._ctrl_window = self._ctrl_canvas.create_window((0, 0), window=self.controls_body, anchor="nw")

        self.controls_body.bind("<Configure>", self._on_controls_configure)
        self._ctrl_canvas.bind("<Configure>", self._on_canvas_configure)
        left_wrap.bind("<Enter>", lambda _e: self._bind_wheel(True))
        left_wrap.bind("<Leave>", lambda _e: self._bind_wheel(False))

        # Header + consistent Simple/Avancé switch
        ttk.Label(self.controls_body, text=title, style="Surface.TLabel", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(self.controls_body, text=subtitle, style="Muted.TLabel", wraplength=310).pack(anchor="w", pady=(2, 8))

        self.toggle = SimpleAdvancedToggle(self.controls_body, on_change=self._handle_mode_toggle, initial_advanced=False)
        self.toggle.pack(fill=tk.X, pady=(0, 10))

        self.simple_frame = ttk.LabelFrame(self.controls_body, text="Réglages Essentiels (Simple)", padding=10)
        self.simple_frame.pack(fill=tk.X, pady=(0, 8))

        self.advanced_frame = ttk.LabelFrame(self.controls_body, text="Paramètres Avancés", padding=10)
        # Hidden by default until user activates Avancé

        # Right column: Preview / Output stage
        self.stage_frame = tk.Frame(self, bg=COLORS["surface"], highlightbackground=COLORS["card_border"], highlightthickness=1)
        self.stage_frame.grid(row=0, column=1, sticky="nsew")
        self.stage_frame.rowconfigure(1, weight=1)
        self.stage_frame.columnconfigure(0, weight=1)

        self.on_mode_changed_hook: Optional[Callable[[bool], None]] = None

    def _handle_mode_toggle(self, is_adv: bool) -> None:
        if is_adv:
            self.advanced_frame.pack(fill=tk.X, pady=(0, 8))
        else:
            self.advanced_frame.pack_forget()
        self._ctrl_canvas.yview_moveto(0.0)
        if self.on_mode_changed_hook:
            self.on_mode_changed_hook(is_adv)

    def _on_controls_configure(self, _event=None) -> None:
        self._ctrl_canvas.configure(scrollregion=self._ctrl_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._ctrl_canvas.itemconfigure(self._ctrl_window, width=event.width)

    def _bind_wheel(self, bind: bool) -> None:
        if bind:
            self._ctrl_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        else:
            self._ctrl_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event) -> None:
        bbox = self._ctrl_canvas.bbox("all")
        if bbox and (bbox[3] - bbox[1]) > self._ctrl_canvas.winfo_height():
            self._ctrl_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
