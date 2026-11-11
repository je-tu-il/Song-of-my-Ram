"""Texte RAM tab — Algorithmic Markov, Haiku, Poem, Prose & Kernel Poetry synthesizer."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from ram_studio.ram_source import RAMEntropyPool
from ram_studio.text_engine import (
    LANGUAGES,
    LENGTH_PRESETS,
    TEXT_STYLES,
    TextConfig,
    TextResult,
    generate_text,
)
from ram_studio.ui.theme import COLORS, GeneratorTabShell


class TextTab(GeneratorTabShell):
    """Algorithmic RAM-seeded text generator tab."""

    def __init__(self, parent: tk.Misc, ram_pool: RAMEntropyPool):
        super().__init__(
            parent,
            title="Texte RAM",
            subtitle="Synthèse algorithmique (Markov, Haïku, Poésie, Prose) guidée par l'entropie RAM.",
        )
        self.ram_pool = ram_pool
        self._style_label_to_key = {v: k for k, v in TEXT_STYLES.items()}
        self._lang_label_to_key = {v: k for k, v in LANGUAGES.items()}
        self._len_label_map = {"Court": "short", "Moyen": "medium", "Long": "long"}
        self._last_result: Optional[TextResult] = None

        self._build_simple()
        self._build_advanced()
        self._build_stage()
        self.generate()

    def _build_simple(self) -> None:
        sf = self.simple_frame

        ttk.Label(sf, text="Style Algorithmique :", style="Card.TLabel").pack(anchor="w")
        self.style_var = tk.StringVar(value=TEXT_STYLES["markov"])
        cb_style = ttk.Combobox(sf, textvariable=self.style_var, values=list(TEXT_STYLES.values()), state="readonly")
        cb_style.pack(fill=tk.X, pady=(3, 8))
        cb_style.bind("<<ComboboxSelected>>", lambda _e: self.generate())

        row_ll = ttk.Frame(sf, style="Card.TFrame")
        row_ll.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row_ll, text="Langue :", style="Card.TLabel").pack(side=tk.LEFT)
        self.lang_var = tk.StringVar(value=LANGUAGES["fr"])
        cb_lang = ttk.Combobox(row_ll, textvariable=self.lang_var, values=list(LANGUAGES.values()), state="readonly", width=10)
        cb_lang.pack(side=tk.LEFT, padx=(4, 10))
        cb_lang.bind("<<ComboboxSelected>>", lambda _e: self.generate())

        ttk.Label(row_ll, text="Taille :", style="Card.TLabel").pack(side=tk.LEFT)
        self.len_var = tk.StringVar(value="Moyen")
        cb_len = ttk.Combobox(row_ll, textvariable=self.len_var, values=list(self._len_label_map.keys()), state="readonly", width=8)
        cb_len.pack(side=tk.LEFT, padx=(4, 0), fill=tk.X, expand=True)
        cb_len.bind("<<ComboboxSelected>>", lambda _e: self._sync_length_preset())

        btn_row = ttk.Frame(sf, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btn_row, text="✨ Générer", style="Accent.TButton", command=self.generate).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
        ttk.Button(btn_row, text="📋 Copier", style="Success.TButton", command=self.copy_text).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0)
        )
        ttk.Button(sf, text="💾 Exporter .TXT", command=self.export_txt).pack(fill=tk.X)

    def _build_advanced(self) -> None:
        af = self.advanced_frame

        temp_hdr = ttk.Frame(af, style="Card.TFrame")
        temp_hdr.pack(fill=tk.X)
        ttk.Label(temp_hdr, text="Température (Créativité) :", style="Card.TLabel").pack(side=tk.LEFT)
        self.temp_lbl = ttk.Label(temp_hdr, text="0.85", style="CardMuted.TLabel")
        self.temp_lbl.pack(side=tk.RIGHT)
        self.temp_var = tk.DoubleVar(value=0.85)
        ttk.Scale(af, from_=0.1, to=2.0, variable=self.temp_var, command=lambda _v: self._update_adv_labels()).pack(fill=tk.X)

        rep_hdr = ttk.Frame(af, style="Card.TFrame")
        rep_hdr.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(rep_hdr, text="Anti-répétition :", style="Card.TLabel").pack(side=tk.LEFT)
        self.rep_lbl = ttk.Label(rep_hdr, text="45%", style="CardMuted.TLabel")
        self.rep_lbl.pack(side=tk.RIGHT)
        self.rep_var = tk.DoubleVar(value=0.45)
        ttk.Scale(af, from_=0.0, to=0.95, variable=self.rep_var, command=lambda _v: self._update_adv_labels()).pack(fill=tk.X)

        row_mo = ttk.Frame(af, style="Card.TFrame")
        row_mo.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(row_mo, text="Ordre Markov :", style="Card.TLabel").pack(side=tk.LEFT)
        self.order_var = tk.IntVar(value=2)
        ttk.Spinbox(row_mo, from_=1, to=2, textvariable=self.order_var, width=4).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row_mo, text="Lignes :", style="Card.TLabel").pack(side=tk.LEFT)
        self.lines_var = tk.IntVar(value=8)
        ttk.Spinbox(row_mo, from_=2, to=30, textvariable=self.lines_var, width=5).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(af, text="Amorce / Début de phrase :", style="Card.TLabel").pack(anchor="w", pady=(4, 2))
        self.seed_prompt_var = tk.StringVar(value="")
        ttk.Entry(af, textvariable=self.seed_prompt_var).pack(fill=tk.X)

        ttk.Label(af, text="Graine manuelle optionnelle (vide = RAM Live) :", style="Card.TLabel").pack(anchor="w", pady=(6, 2))
        self.seed_override_var = tk.StringVar(value="")
        ttk.Entry(af, textvariable=self.seed_override_var).pack(fill=tk.X)

        ttk.Label(af, text="Corpus personnalisé additionnel :", style="Card.TLabel").pack(anchor="w", pady=(6, 2))
        self.custom_corpus_text = tk.Text(
            af,
            height=4,
            bg=COLORS["input_bg"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            font=("Segoe UI", 8),
            relief=tk.FLAT,
            padx=6,
            pady=4,
        )
        self.custom_corpus_text.pack(fill=tk.X)

    def _build_stage(self) -> None:
        hdr = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=10)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="Sortie Textuelle Algorithmique", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.seed_lbl = tk.Label(hdr, text="Seed: —", bg=COLORS["card"], fg=COLORS["accent"], font=("Consolas", 9))
        self.seed_lbl.pack(side=tk.RIGHT)

        self.output_text = tk.Text(
            self.stage_frame,
            bg="#060A14",
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            font=("Georgia", 11),
            wrap=tk.WORD,
            padx=22,
            pady=18,
            relief=tk.FLAT,
            spacing2=4,
            spacing3=6,
        )
        self.output_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

        footer = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=8)
        footer.grid(row=2, column=0, sticky="ew")
        self.meta_lbl = tk.Label(footer, text="Prêt.", bg=COLORS["card"], fg=COLORS["text_muted"], font=("Consolas", 9))
        self.meta_lbl.pack(side=tk.LEFT)

    def _sync_length_preset(self) -> None:
        key = self._len_label_map.get(self.len_var.get(), "medium")
        self.lines_var.set(LENGTH_PRESETS[key])
        self.generate()

    def _update_adv_labels(self) -> None:
        self.temp_lbl.configure(text=f"{self.temp_var.get():.2f}")
        self.rep_lbl.configure(text=f"{int(self.rep_var.get() * 100)}%")

    def _current_config(self) -> TextConfig:
        style_key = self._style_label_to_key.get(self.style_var.get(), "markov")
        lang_key = self._lang_label_to_key.get(self.lang_var.get(), "fr")
        len_key = self._len_label_map.get(self.len_var.get(), "medium")
        return TextConfig(
            style=style_key,
            language=lang_key,
            length=len_key,
            line_count=max(2, min(40, int(self.lines_var.get()))),
            temperature=float(self.temp_var.get()),
            markov_order=max(1, min(2, int(self.order_var.get()))),
            repetition_penalty=float(self.rep_var.get()),
            seed_text=self.seed_prompt_var.get(),
            custom_corpus=self.custom_corpus_text.get("1.0", tk.END),
            seed_override=self.seed_override_var.get(),
        )

    def generate(self) -> None:
        cfg = self._current_config()
        res = generate_text(self.ram_pool, cfg)
        self._last_result = res

        self.output_text.configure(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", res.text)
        font_use = ("Consolas", 10) if cfg.style == "code_log" else ("Georgia", 11)
        self.output_text.configure(font=font_use, state=tk.DISABLED)

        self.seed_lbl.configure(text=f"Seed RAM: {res.seed_hex}")
        self.meta_lbl.configure(
            text=f"Style : {TEXT_STYLES.get(cfg.style)} • {res.tokens_generated} mots/jetons • Entropie : {res.ram_shannon_entropy:.2f} b/o"
        )

    def copy_text(self) -> None:
        txt = self.output_text.get("1.0", tk.END).strip()
        if not txt:
            return
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.meta_lbl.configure(text="✅ Texte copié dans le presse-papiers !")

    def export_txt(self) -> None:
        txt = self.output_text.get("1.0", tk.END).strip()
        if not txt:
            return
        path = filedialog.asksaveasfilename(
            title="Exporter le texte RAM",
            defaultextension=".txt",
            filetypes=[("Fichier Texte", "*.txt")],
            initialfile="ram_texte.txt",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(txt + "\n")
            messagebox.showinfo("Export réussi", f"Texte enregistré :\n{path}")
        except Exception as exc:
            messagebox.showerror("Erreur Export", str(exc))

    def shutdown(self) -> None:
        pass
