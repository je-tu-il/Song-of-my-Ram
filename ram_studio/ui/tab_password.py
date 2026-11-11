"""Mots de Passe RAM tab — RAM-seeded passwords + live entropy pool visualization."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ram_studio.password_engine import PasswordConfig, PasswordResult, generate_passwords
from ram_studio.ram_source import RAMEntropyPool
from ram_studio.ui.theme import COLORS, GeneratorTabShell

MODE_LABELS = {
    "password": "Mot de passe classique",
    "passphrase": "Passphrase mémorisable",
    "hex": "Clé Hexadécimale",
    "base64": "Token Base64 URL",
    "pin": "Code PIN numérique",
}


class PasswordTab(GeneratorTabShell):
    """RAM-seeded password and passphrase generator tab."""

    def __init__(self, parent: tk.Misc, ram_pool: RAMEntropyPool):
        super().__init__(
            parent,
            title="Mots de Passe RAM",
            subtitle="Génère des secrets robustes alimentés par l'entropie brute de votre mémoire vive.",
        )
        self.ram_pool = ram_pool
        self._label_to_mode = {v: k for k, v in MODE_LABELS.items()}
        self._last_result: Optional[PasswordResult] = None

        self._build_simple()
        self._build_advanced()
        self._build_stage()
        self.generate()

    def _build_simple(self) -> None:
        sf = self.simple_frame

        len_hdr = ttk.Frame(sf, style="Card.TFrame")
        len_hdr.pack(fill=tk.X)
        ttk.Label(len_hdr, text="Longueur :", style="Card.TLabel").pack(side=tk.LEFT)
        self.len_lbl = ttk.Label(len_hdr, text="18 caractères", style="CardMuted.TLabel")
        self.len_lbl.pack(side=tk.RIGHT)

        self.len_var = tk.IntVar(value=18)
        ttk.Scale(sf, from_=4, to=96, variable=self.len_var, command=lambda _v: self._on_len_change()).pack(
            fill=tk.X, pady=(4, 10)
        )

        btn_row = ttk.Frame(sf, style="Card.TFrame")
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="⚡ Générer", style="Accent.TButton", command=self.generate).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
        ttk.Button(btn_row, text="📋 Copier", style="Success.TButton", command=self.copy_primary).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0)
        )

    def _build_advanced(self) -> None:
        af = self.advanced_frame

        row_mode = ttk.Frame(af, style="Card.TFrame")
        row_mode.pack(fill=tk.X, pady=3)
        ttk.Label(row_mode, text="Format :", style="Card.TLabel", width=13).pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value=MODE_LABELS["password"])
        cb_mode = ttk.Combobox(row_mode, textvariable=self.mode_var, values=list(MODE_LABELS.values()), state="readonly")
        cb_mode.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cb_mode.bind("<<ComboboxSelected>>", lambda _e: self.generate())

        # Character rules
        self.lower_var = tk.BooleanVar(value=True)
        self.upper_var = tk.BooleanVar(value=True)
        self.digits_var = tk.BooleanVar(value=True)
        self.symbols_var = tk.BooleanVar(value=True)
        self.no_ambig_var = tk.BooleanVar(value=False)
        self.req_each_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(af, text="Minuscules (a-z)", variable=self.lower_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(af, text="Majuscules (A-Z)", variable=self.upper_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(af, text="Chiffres (0-9)", variable=self.digits_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(af, text="Symboles (!@#$...)", variable=self.symbols_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(af, text="Exclure caractères ambigus (0O1lI|)", variable=self.no_ambig_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(af, text="Garantir 1 caractère de chaque classe", variable=self.req_each_var).pack(anchor="w", pady=1)

        sym_row = ttk.Frame(af, style="Card.TFrame")
        sym_row.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(sym_row, text="Symboles :", style="Card.TLabel", width=13).pack(side=tk.LEFT)
        self.custom_sym_var = tk.StringVar(value="!@#$%^&*-_=+?")
        ttk.Entry(sym_row, textvariable=self.custom_sym_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Passphrase rules
        pp_row = ttk.Frame(af, style="Card.TFrame")
        pp_row.pack(fill=tk.X, pady=3)
        ttk.Label(pp_row, text="Mots (phrase) :", style="Card.TLabel", width=13).pack(side=tk.LEFT)
        self.words_var = tk.IntVar(value=5)
        ttk.Spinbox(pp_row, from_=3, to=12, textvariable=self.words_var, width=5).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(pp_row, text="Sép. :", style="Card.TLabel").pack(side=tk.LEFT)
        self.sep_var = tk.StringVar(value="-")
        ttk.Combobox(pp_row, textvariable=self.sep_var, values=["-", "_", ".", " "], width=4, state="readonly").pack(side=tk.LEFT, padx=(4, 0))

        self.cap_words_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="Majuscule sur chaque mot (Passphrase)", variable=self.cap_words_var).pack(anchor="w", pady=2)

        # Entropy & batch
        batch_row = ttk.Frame(af, style="Card.TFrame")
        batch_row.pack(fill=tk.X, pady=3)
        ttk.Label(batch_row, text="Lot généré :", style="Card.TLabel", width=13).pack(side=tk.LEFT)
        self.count_var = tk.IntVar(value=4)
        ttk.Spinbox(batch_row, from_=1, to=12, textvariable=self.count_var, width=5).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(batch_row, text="Octets RAM :", style="Card.TLabel").pack(side=tk.LEFT)
        self.sample_var = tk.IntVar(value=256)
        ttk.Spinbox(batch_row, from_=64, to=2048, increment=64, textvariable=self.sample_var, width=6).pack(side=tk.LEFT, padx=(4, 0))

        self.mix_urandom_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            af,
            text="Blanchiment cryptographique (RAM + os.urandom)",
            variable=self.mix_urandom_var,
        ).pack(anchor="w", pady=(4, 0))

    def _build_stage(self) -> None:
        hdr = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=10)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="Secrets Générés & Pool d'Entropie RAM", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.strength_lbl = tk.Label(hdr, text="—", bg=COLORS["card"], fg=COLORS["success"], font=("Consolas", 9, "bold"))
        self.strength_lbl.pack(side=tk.RIGHT)

        body = tk.Frame(self.stage_frame, bg=COLORS["surface"], padx=14, pady=12)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(3, weight=1)

        # Primary password highlight box
        self.primary_var = tk.StringVar(value="")
        entry = tk.Entry(
            body,
            textvariable=self.primary_var,
            bg="#060A14",
            fg=COLORS["accent"],
            font=("Consolas", 14, "bold"),
            relief=tk.FLAT,
            readonlybackground="#060A14",
            state="readonly",
            justify="center",
        )
        entry.grid(row=0, column=0, sticky="ew", ipady=10, pady=(0, 8))

        self.strength_bar = ttk.Progressbar(body, maximum=140, value=0)
        self.strength_bar.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # Batch list
        self.batch_text = tk.Text(
            body,
            height=6,
            bg="#060A14",
            fg=COLORS["text"],
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )
        self.batch_text.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        # Entropy pool visualizer canvas (16x16 byte heatmap + histogram)
        self.entropy_canvas = tk.Canvas(body, bg="#060A14", highlightthickness=1, highlightbackground=COLORS["card_border"])
        self.entropy_canvas.grid(row=3, column=0, sticky="nsew")
        self.entropy_canvas.bind("<Configure>", lambda _e: self._draw_entropy_pool())

        footer = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=8)
        footer.grid(row=2, column=0, sticky="ew")
        self.meta_lbl = tk.Label(footer, text="Prêt.", bg=COLORS["card"], fg=COLORS["text_muted"], font=("Consolas", 9))
        self.meta_lbl.pack(side=tk.LEFT)

    def _on_len_change(self) -> None:
        n = int(self.len_var.get())
        self.len_lbl.configure(text=f"{n} caractères")

    def _current_config(self) -> PasswordConfig:
        mode = self._label_to_mode.get(self.mode_var.get(), "password")
        return PasswordConfig(
            mode=mode,
            length=int(self.len_var.get()),
            use_lower=bool(self.lower_var.get()),
            use_upper=bool(self.upper_var.get()),
            use_digits=bool(self.digits_var.get()),
            use_symbols=bool(self.symbols_var.get()),
            custom_symbols=self.custom_sym_var.get(),
            exclude_ambiguous=bool(self.no_ambig_var.get()),
            require_each_class=bool(self.req_each_var.get()),
            word_count=int(self.words_var.get()),
            separator=self.sep_var.get(),
            capitalize_words=bool(self.cap_words_var.get()),
            sample_size=int(self.sample_var.get()),
            mix_os_urandom=bool(self.mix_urandom_var.get()),
            count=max(1, min(12, int(self.count_var.get()))),
        )

    def generate(self) -> None:
        res = generate_passwords(self.ram_pool, self._current_config())
        self._last_result = res
        self.primary_var.set(res.passwords[0] if res.passwords else "")
        self.strength_lbl.configure(text=f"{res.strength_label} ({res.entropy_bits:.0f} bits)")
        self.strength_bar.configure(value=min(140, res.entropy_bits))

        self.batch_text.configure(state=tk.NORMAL)
        self.batch_text.delete("1.0", tk.END)
        for idx, pwd in enumerate(res.passwords, 1):
            self.batch_text.insert(tk.END, f"[{idx}] {pwd}\n")
        self.batch_text.configure(state=tk.DISABLED)

        self.meta_lbl.configure(text=f"{res.source_summary} • Hex: {res.ram_sample_hex[:35]}...")
        self._draw_entropy_pool()

    def copy_primary(self) -> None:
        val = self.primary_var.get()
        if not val:
            return
        self.clipboard_clear()
        self.clipboard_append(val)
        self.meta_lbl.configure(text="✅ Mot de passe copié dans le presse-papiers !")

    def _draw_entropy_pool(self) -> None:
        c = self.entropy_canvas
        w = max(200, c.winfo_width())
        h = max(120, c.winfo_height())
        c.delete("all")
        if not self._last_result:
            return

        data = self._last_result.ram_bytes[:256]
        cols, rows = 16, 16
        grid_size = min(h - 24, int(w * 0.45))
        cell = max(4, grid_size // 16)
        ox, oy = 14, (h - cell * 16) // 2

        c.create_text(ox, max(8, oy - 10), text="Matrice Octets RAM (256 B)", anchor="w", fill=COLORS["text_muted"], font=("Consolas", 8))
        for i, b in enumerate(data):
            r, col_i = divmod(i, cols)
            x0 = ox + col_i * cell
            y0 = oy + r * cell
            # Map byte value 0..255 to sleek cyan-violet glow
            cr = int(20 + (b / 255.0) * 150)
            cg = int(35 + ((b * 2) % 255) * 0.72)
            cb = int(95 + (b / 255.0) * 160)
            color = f"#{cr:02x}{cg:02x}{cb:02x}"
            c.create_rectangle(x0, y0, x0 + cell - 1, y0 + cell - 1, fill=color, outline="")

        # Right side: 32-bin byte frequency spectrum
        hx0 = ox + cell * 16 + 24
        hw = max(60, w - hx0 - 16)
        hy0 = oy
        hh = cell * 16
        c.create_text(hx0, max(8, oy - 10), text="Distribution Entropie RAM", anchor="w", fill=COLORS["text_muted"], font=("Consolas", 8))
        bins = [0] * 32
        for b in self._last_result.ram_bytes:
            bins[b >> 3] += 1
        max_bin = max(1, max(bins))
        bw = max(2, hw / 32.0)
        for i, cnt in enumerate(bins):
            bh = (cnt / max_bin) * max(10, hh - 10)
            x0 = hx0 + i * bw
            y0 = hy0 + hh - bh
            c.create_rectangle(x0, y0, x0 + max(1, bw - 2), hy0 + hh, fill=COLORS["accent"], outline="")

    def shutdown(self) -> None:
        pass
