"""Images RAM tab — Instant one-shot and continuous algorithmic RAM image generator."""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional, Tuple

from ram_studio.codecs import HAS_NUMPY, rgb_bytes_to_ppm
from ram_studio.image_engine import (
    ALGORITHMS,
    ImageConfig,
    ImageState,
    PALETTE_STOPS,
    SYMMETRIES,
    generate_image_frame,
    save_image_png,
)
from ram_studio.ram_source import RAMEntropyPool
from ram_studio.ui.theme import COLORS, GeneratorTabShell


class ImageTab(GeneratorTabShell):
    """Images RAM tab with instant one-shot and continuous non-stop generation."""

    def __init__(self, parent: tk.Misc, ram_pool: RAMEntropyPool):
        super().__init__(
            parent,
            title="Images RAM",
            subtitle="Génération instantanée ou continue d'art algorithmique nourri par la RAM.",
        )
        self.ram_pool = ram_pool
        self.state = ImageState()
        self.is_continuous = False
        self._busy = False
        self._after_id: Optional[str] = None
        self._destroyed = False
        self._last_frame: Optional[Tuple[int, int, bytes]] = None
        self._photo_ref: Optional[tk.PhotoImage] = None
        self.autosave_dir = ""

        self._alg_label_to_key = {v: k for k, v in ALGORITHMS.items()}
        self._sym_label_to_key = {v: k for k, v in SYMMETRIES.items()}

        self._build_simple()
        self._build_advanced()
        self._build_stage()
        self.after(120, self.generate_one_shot)

    def _build_simple(self) -> None:
        sf = self.simple_frame

        ttk.Label(sf, text="Algorithme :", style="Card.TLabel").pack(anchor="w")
        self.alg_var = tk.StringVar(value=ALGORITHMS["plasma"])
        cb_alg = ttk.Combobox(sf, textvariable=self.alg_var, values=list(ALGORITHMS.values()), state="readonly")
        cb_alg.pack(fill=tk.X, pady=(3, 8))
        cb_alg.bind("<<ComboboxSelected>>", lambda _e: self._on_param_change())

        btn_row = ttk.Frame(sf, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btn_row, text="⚡ 1 Image", style="Accent.TButton", command=self.generate_one_shot).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
        self.btn_cont = ttk.Button(btn_row, text="♾️ Continu", style="Success.TButton", command=self.toggle_continuous)
        self.btn_cont.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        ttk.Button(sf, text="💾 Enregistrer PNG", command=self.save_current_png).pack(fill=tk.X, pady=(2, 0))

    def _build_advanced(self) -> None:
        af = self.advanced_frame

        row_pal = ttk.Frame(af, style="Card.TFrame")
        row_pal.pack(fill=tk.X, pady=3)
        ttk.Label(row_pal, text="Palette :", style="Card.TLabel", width=14).pack(side=tk.LEFT)
        self.pal_var = tk.StringVar(value="Cyberpunk")
        cb_pal = ttk.Combobox(row_pal, textvariable=self.pal_var, values=list(PALETTE_STOPS.keys()), state="readonly")
        cb_pal.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cb_pal.bind("<<ComboboxSelected>>", lambda _e: self._on_param_change())

        row_sym = ttk.Frame(af, style="Card.TFrame")
        row_sym.pack(fill=tk.X, pady=3)
        ttk.Label(row_sym, text="Symétrie :", style="Card.TLabel", width=14).pack(side=tk.LEFT)
        self.sym_var = tk.StringVar(value=SYMMETRIES["none"])
        cb_sym = ttk.Combobox(row_sym, textvariable=self.sym_var, values=list(SYMMETRIES.values()), state="readonly")
        cb_sym.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cb_sym.bind("<<ComboboxSelected>>", lambda _e: self._on_param_change())

        row_res = ttk.Frame(af, style="Card.TFrame")
        row_res.pack(fill=tk.X, pady=3)
        ttk.Label(row_res, text="Résolution :", style="Card.TLabel", width=14).pack(side=tk.LEFT)
        self.res_var = tk.StringVar(value="256x256")
        cb_res = ttk.Combobox(
            row_res,
            textvariable=self.res_var,
            values=["192x192", "256x256", "384x384", "512x512"],
            state="readonly",
        )
        cb_res.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cb_res.bind("<<ComboboxSelected>>", lambda _e: self._on_param_change())

        comp_hdr = ttk.Frame(af, style="Card.TFrame")
        comp_hdr.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(comp_hdr, text="Complexité :", style="Card.TLabel").pack(side=tk.LEFT)
        self.comp_lbl = ttk.Label(comp_hdr, text="5", style="CardMuted.TLabel")
        self.comp_lbl.pack(side=tk.RIGHT)
        self.comp_var = tk.IntVar(value=5)
        ttk.Scale(af, from_=1, to=10, variable=self.comp_var, command=lambda _v: self._update_labels()).pack(fill=tk.X)

        spd_hdr = ttk.Frame(af, style="Card.TFrame")
        spd_hdr.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(spd_hdr, text="Vitesse :", style="Card.TLabel").pack(side=tk.LEFT)
        self.spd_lbl = tk.Label(spd_hdr, text="1.0x", bg=COLORS["card"], fg=COLORS["text_muted"], font=("Segoe UI", 8))
        self.spd_lbl.pack(side=tk.RIGHT)
        self.spd_var = tk.DoubleVar(value=1.0)
        ttk.Scale(af, from_=0.2, to=3.0, variable=self.spd_var, command=lambda _v: self._update_labels()).pack(fill=tk.X)

        int_hdr = ttk.Frame(af, style="Card.TFrame")
        int_hdr.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(int_hdr, text="Intervalle (ms) :", style="Card.TLabel").pack(side=tk.LEFT)
        self.int_lbl = ttk.Label(int_hdr, text="70 ms", style="CardMuted.TLabel")
        self.int_lbl.pack(side=tk.RIGHT)
        self.int_var = tk.IntVar(value=70)
        ttk.Scale(af, from_=30, to=500, variable=self.int_var, command=lambda _v: self._update_labels()).pack(fill=tk.X)

        step_row = ttk.Frame(af, style="Card.TFrame")
        step_row.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(step_row, text="Pas Lecture RAM :", style="Card.TLabel", width=15).pack(side=tk.LEFT)
        self.step_var = tk.IntVar(value=256)
        ttk.Spinbox(step_row, from_=64, to=4096, increment=64, textvariable=self.step_var, width=8).pack(side=tk.LEFT)

        self.autosave_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            af,
            text="Auto-sauvegarder en continu (PNG)",
            variable=self.autosave_var,
            command=self._choose_autosave_if_needed,
        ).pack(anchor="w", pady=(4, 0))

    def _build_stage(self) -> None:
        hdr = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=10)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="Aperçu Visuel Temps Réel", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        accel = "NumPy Accéléré" if HAS_NUMPY else "Moteur Pur Python"
        self.badge_lbl = tk.Label(hdr, text=accel, bg=COLORS["card"], fg=COLORS["accent"], font=("Consolas", 9))
        self.badge_lbl.pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(self.stage_frame, bg="#050811", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        self.canvas.bind("<Configure>", lambda _e: self._redraw_last_frame())

        footer = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=8)
        footer.grid(row=2, column=0, sticky="ew")
        self.status_lbl = tk.Label(footer, text="Prêt.", bg=COLORS["card"], fg=COLORS["text_muted"], font=("Consolas", 9))
        self.status_lbl.pack(side=tk.LEFT)

    def _update_labels(self) -> None:
        self.comp_lbl.configure(text=str(int(self.comp_var.get())))
        self.spd_lbl.configure(text=f"{self.spd_var.get():.1f}x")
        self.int_lbl.configure(text=f"{int(self.int_var.get())} ms")

    def _on_param_change(self) -> None:
        self._update_labels()
        if not self.is_continuous:
            self.generate_one_shot()

    def _choose_autosave_if_needed(self) -> None:
        if self.autosave_var.get() and not self.autosave_dir:
            chosen = filedialog.askdirectory(title="Dossier d'auto-sauvegarde PNG")
            if chosen:
                self.autosave_dir = chosen
            else:
                self.autosave_var.set(False)

    def _current_config(self) -> ImageConfig:
        alg_key = self._alg_label_to_key.get(self.alg_var.get(), "plasma")
        sym_key = self._sym_label_to_key.get(self.sym_var.get(), "none")
        res_str = self.res_var.get()
        try:
            w, h = [int(x) for x in res_str.split("x")]
        except Exception:
            w, h = 256, 256
        try:
            step = max(32, int(self.step_var.get()))
        except Exception:
            step = 256
        return ImageConfig(
            algorithm=alg_key,
            palette_name=self.pal_var.get(),
            width=w,
            height=h,
            complexity=max(1, min(10, int(self.comp_var.get()))),
            symmetry=sym_key,
            speed=float(self.spd_var.get()),
            read_step=step,
            interval_ms=max(30, int(self.int_var.get())),
        )

    def generate_one_shot(self) -> None:
        if self._busy or self._destroyed:
            return
        self._busy = True
        cfg = self._current_config()

        def worker() -> None:
            ram_bytes = self.ram_pool.sample_bytes(2048, step=cfg.read_step)
            w, h, rgb = generate_image_frame(ram_bytes, cfg, state=self.state, one_shot=True)
            if not self._destroyed:
                self.after(0, lambda: self._display_frame(w, h, rgb, cfg))

        threading.Thread(target=worker, daemon=True).start()

    def toggle_continuous(self) -> None:
        if self.is_continuous:
            self.stop_continuous()
        else:
            self.is_continuous = True
            self.btn_cont.configure(text="⏹ Stop Continu", style="Danger.TButton")
            self._schedule_next_frame()

    def stop_continuous(self) -> None:
        self.is_continuous = False
        self.btn_cont.configure(text="♾️ Continu", style="Success.TButton")
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _schedule_next_frame(self) -> None:
        if not self.is_continuous or self._destroyed:
            return
        if not self._busy:
            self._busy = True
            cfg = self._current_config()

            def worker() -> None:
                ram_bytes = self.ram_pool.sample_bytes(1024, step=cfg.read_step)
                w, h, rgb = generate_image_frame(ram_bytes, cfg, state=self.state, one_shot=False)
                if self.autosave_var.get() and self.autosave_dir:
                    fname = os.path.join(self.autosave_dir, f"ram_{cfg.algorithm}_{self.state.frame_index:05d}.png")
                    try:
                        save_image_png(fname, w, h, rgb)
                    except Exception:
                        pass
                if not self._destroyed:
                    self.after(0, lambda: self._display_frame(w, h, rgb, cfg))

            threading.Thread(target=worker, daemon=True).start()
        self._after_id = self.after(max(30, int(self.int_var.get())), self._schedule_next_frame)

    def _display_frame(self, w: int, h: int, rgb: bytes, cfg: ImageConfig) -> None:
        self._busy = False
        if self._destroyed:
            return
        self._last_frame = (w, h, rgb)
        self._render_to_canvas(w, h, rgb)
        tele = self.ram_pool.last_telemetry
        self.status_lbl.configure(
            text=f"Image #{self.state.frame_index} • {w}x{h} • {ALGORITHMS.get(cfg.algorithm)} • Entropie {tele.get('shannon_entropy', 0.0):.2f} b/o"
        )

    def _redraw_last_frame(self) -> None:
        if self._last_frame and not self._destroyed:
            w, h, rgb = self._last_frame
            self._render_to_canvas(w, h, rgb)

    def _render_to_canvas(self, w: int, h: int, rgb: bytes) -> None:
        ppm = rgb_bytes_to_ppm(w, h, rgb)
        photo = tk.PhotoImage(data=ppm, format="PPM")
        cw = max(w, self.canvas.winfo_width())
        ch = max(h, self.canvas.winfo_height())
        zoom_factor = min(max(1, cw // w), max(1, ch // h))
        if zoom_factor > 1:
            photo = photo.zoom(zoom_factor, zoom_factor)
        self._photo_ref = photo
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=photo, anchor=tk.CENTER)

    def save_current_png(self) -> None:
        if not self._last_frame:
            messagebox.showwarning("Aucune image", "Générez d'abord une image.")
            return
        w, h, rgb = self._last_frame
        path = filedialog.asksaveasfilename(
            title="Enregistrer l'image RAM en PNG",
            defaultextension=".png",
            filetypes=[("Image PNG", "*.png")],
            initialfile=f"ram_{self._current_config().algorithm}.png",
        )
        if not path:
            return
        try:
            out = save_image_png(path, w, h, rgb)
            messagebox.showinfo("Image enregistrée", f"PNG sauvegardé :\n{out}")
        except Exception as exc:
            messagebox.showerror("Erreur PNG", str(exc))

    def shutdown(self) -> None:
        self._destroyed = True
        self.stop_continuous()
