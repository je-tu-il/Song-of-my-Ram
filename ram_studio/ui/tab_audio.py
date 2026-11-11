"""Audio RAM tab — Simple playback + Advanced real-time synthesis & MIDI controls."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from ram_studio.audio_engine import (
    AudioEngine,
    NOTE_NAMES,
    PROGRESSIONS,
    SAMPLE_RATES,
    SCALE_INTERVALS,
    WAVEFORMS,
)
from ram_studio.ram_source import RAMEntropyPool
from ram_studio.ui.theme import COLORS, GeneratorTabShell


class AudioTab(GeneratorTabShell):
    """Audio RAM synthesis & MIDI orchestration tab."""

    def __init__(self, parent: tk.Misc, ram_pool: RAMEntropyPool):
        super().__init__(
            parent,
            title="Audio RAM",
            subtitle="Transforme en direct les octets de la RAM en concerto MIDI ou synthèse sonore.",
        )
        self.ram_pool = ram_pool
        self.engine = AudioEngine(ram_pool)
        self.engine.on_stop_callback = self._on_engine_stopped
        self._after_id: Optional[str] = None
        self._destroyed = False

        self._build_simple()
        self._build_advanced()
        self._build_stage()
        self._push_config()
        self._schedule_viz()

    def _build_simple(self) -> None:
        sf = self.simple_frame

        ttk.Label(sf, text="Moteur Audio :", style="Section.TLabel").pack(anchor="w")
        self.mode_var = tk.StringVar(value="midi")
        ttk.Radiobutton(
            sf,
            text="Concerto MIDI (Instruments natifs Windows)",
            variable=self.mode_var,
            value="midi",
            command=self._push_config,
        ).pack(anchor="w", pady=(4, 2))
        ttk.Radiobutton(
            sf,
            text="Synthétiseur RAM (Ondes PCM temps réel)",
            variable=self.mode_var,
            value="synth",
            command=self._push_config,
        ).pack(anchor="w", pady=(0, 8))

        vol_row = ttk.Frame(sf, style="Card.TFrame")
        vol_row.pack(fill=tk.X, pady=(2, 8))
        ttk.Label(vol_row, text="Volume :", style="Card.TLabel").pack(side=tk.LEFT)
        self.vol_lbl = ttk.Label(vol_row, text="75%", style="CardMuted.TLabel", width=6)
        self.vol_lbl.pack(side=tk.RIGHT)

        self.vol_var = tk.DoubleVar(value=0.75)
        ttk.Scale(
            sf,
            from_=0.0,
            to=1.0,
            variable=self.vol_var,
            command=lambda _v: self._on_volume_slide(),
        ).pack(fill=tk.X, pady=(0, 10))

        btn_row = ttk.Frame(sf, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(2, 0))
        self.btn_play = ttk.Button(btn_row, text="▶ Lecture", style="Success.TButton", command=self.play)
        self.btn_play.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.btn_stop = ttk.Button(btn_row, text="⏹ Stop", style="Danger.TButton", command=self.stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

    def _build_advanced(self) -> None:
        af = self.advanced_frame

        def add_combo(label: str, var: tk.Variable, values: list) -> ttk.Combobox:
            row = ttk.Frame(af, style="Card.TFrame")
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label, style="Card.TLabel", width=15).pack(side=tk.LEFT)
            cb = ttk.Combobox(row, textvariable=var, values=values, state="readonly")
            cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
            cb.bind("<<ComboboxSelected>>", lambda _e: self._push_config())
            return cb

        self.waveform_var = tk.StringVar(value="sine")
        add_combo("Forme d'onde :", self.waveform_var, WAVEFORMS)

        self.key_var = tk.StringVar(value="C")
        add_combo("Tonique :", self.key_var, NOTE_NAMES)

        self.scale_var = tk.StringVar(value="Majeur")
        add_combo("Gamme :", self.scale_var, list(SCALE_INTERVALS.keys()))

        self.prog_var = tk.StringVar(value="Original (I-vi-IV-V)")
        add_combo("Progression :", self.prog_var, list(PROGRESSIONS.keys()))

        self.sr_var = tk.StringVar(value="44100")
        add_combo("Sample Rate :", self.sr_var, [str(s) for s in SAMPLE_RATES])

        # Tempo BPM
        bpm_hdr = ttk.Frame(af, style="Card.TFrame")
        bpm_hdr.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(bpm_hdr, text="Tempo (BPM) :", style="Card.TLabel").pack(side=tk.LEFT)
        self.bpm_lbl = ttk.Label(bpm_hdr, text="76 BPM", style="CardMuted.TLabel")
        self.bpm_lbl.pack(side=tk.RIGHT)
        self.bpm_var = tk.IntVar(value=76)
        ttk.Scale(af, from_=20, to=220, variable=self.bpm_var, command=lambda _v: self._push_config()).pack(fill=tk.X)

        # Reverb
        rev_hdr = ttk.Frame(af, style="Card.TFrame")
        rev_hdr.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(rev_hdr, text="Réverbération :", style="Card.TLabel").pack(side=tk.LEFT)
        self.rev_lbl = ttk.Label(rev_hdr, text="40", style="CardMuted.TLabel")
        self.rev_lbl.pack(side=tk.RIGHT)
        self.reverb_var = tk.IntVar(value=40)
        ttk.Scale(af, from_=0, to=127, variable=self.reverb_var, command=lambda _v: self._push_config()).pack(fill=tk.X)

        # Voices & Raw mix
        v_row = ttk.Frame(af, style="Card.TFrame")
        v_row.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(v_row, text="Voix / Canaux :", style="Card.TLabel", width=15).pack(side=tk.LEFT)
        self.voices_var = tk.IntVar(value=6)
        sp_v = ttk.Spinbox(v_row, from_=1, to=10, textvariable=self.voices_var, width=6, command=self._push_config)
        sp_v.pack(side=tk.LEFT)
        sp_v.bind("<Return>", lambda _e: self._push_config())
        sp_v.bind("<FocusOut>", lambda _e: self._push_config())

        raw_hdr = ttk.Frame(af, style="Card.TFrame")
        raw_hdr.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(raw_hdr, text="Mix Grain RAM Brut :", style="Card.TLabel").pack(side=tk.LEFT)
        self.raw_lbl = ttk.Label(raw_hdr, text="8%", style="CardMuted.TLabel")
        self.raw_lbl.pack(side=tk.RIGHT)
        self.raw_mix_var = tk.DoubleVar(value=0.08)
        ttk.Scale(af, from_=0.0, to=1.0, variable=self.raw_mix_var, command=lambda _v: self._push_config()).pack(fill=tk.X)

        step_row = ttk.Frame(af, style="Card.TFrame")
        step_row.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(step_row, text="Pas Lecture RAM :", style="Card.TLabel", width=15).pack(side=tk.LEFT)
        self.step_var = tk.IntVar(value=2048)
        sp_step = ttk.Spinbox(step_row, from_=128, to=16384, increment=256, textvariable=self.step_var, width=8, command=self._push_config)
        sp_step.pack(side=tk.LEFT)
        sp_step.bind("<Return>", lambda _e: self._push_config())
        sp_step.bind("<FocusOut>", lambda _e: self._push_config())

        # Toggles
        self.quantize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="Quantifier sur la gamme (harmonique)", variable=self.quantize_var, command=self._push_config).pack(anchor="w", pady=2)
        self.humanize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="Humaniser vélocité & durée", variable=self.humanize_var, command=self._push_config).pack(anchor="w", pady=2)
        self.swing_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(af, text="Rythme Swing", variable=self.swing_var, command=self._push_config).pack(anchor="w", pady=2)

        ttk.Button(af, text="💾 Exporter Extrait WAV (5s)", command=self.export_wav).pack(fill=tk.X, pady=(8, 0))

    def _build_stage(self) -> None:
        hdr = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=10)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="Oscilloscope & Télémétrie Audio RAM", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.backend_lbl = tk.Label(hdr, text="Prêt", bg=COLORS["card"], fg=COLORS["accent"], font=("Consolas", 9))
        self.backend_lbl.pack(side=tk.RIGHT)

        self.scope_canvas = tk.Canvas(self.stage_frame, bg="#060A14", highlightthickness=0)
        self.scope_canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

        footer = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=8)
        footer.grid(row=2, column=0, sticky="ew")
        self.chord_lbl = tk.Label(footer, text="Accord : —", bg=COLORS["card"], fg=COLORS["success"], font=("Consolas", 10, "bold"))
        self.chord_lbl.pack(side=tk.LEFT)
        self.notes_lbl = tk.Label(footer, text="Notes : —", bg=COLORS["card"], fg=COLORS["text_muted"], font=("Consolas", 9))
        self.notes_lbl.pack(side=tk.RIGHT)

    def _on_volume_slide(self) -> None:
        self.vol_lbl.configure(text=f"{int(self.vol_var.get() * 100)}%")
        self._push_config()

    def _push_config(self) -> None:
        bpm = max(20, min(220, int(self.bpm_var.get())))
        rev = max(0, min(127, int(self.reverb_var.get())))
        raw_mix = max(0.0, min(1.0, float(self.raw_mix_var.get())))
        self.bpm_lbl.configure(text=f"{bpm} BPM")
        self.rev_lbl.configure(text=str(rev))
        self.raw_lbl.configure(text=f"{int(raw_mix * 100)}%")
        try:
            sr = int(self.sr_var.get())
        except ValueError:
            sr = 44100
        try:
            voices = max(1, min(10, int(self.voices_var.get())))
        except Exception:
            voices = 6
        try:
            step = max(64, int(self.step_var.get()))
        except Exception:
            step = 2048

        self.engine.update_config(
            mode=self.mode_var.get(),
            volume=float(self.vol_var.get()),
            bpm=bpm,
            waveform=self.waveform_var.get(),
            key_name=self.key_var.get(),
            scale_name=self.scale_var.get(),
            progression_name=self.prog_var.get(),
            sample_rate=sr,
            voices=voices,
            reverb=rev,
            quantize=bool(self.quantize_var.get()),
            humanize=bool(self.humanize_var.get()),
            swing=bool(self.swing_var.get()),
            read_step=step,
            raw_byte_mix=raw_mix,
        )

    def play(self) -> None:
        self._push_config()
        self.engine.start()
        self.btn_play.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)

    def stop(self) -> None:
        self.engine.stop()
        self.btn_play.configure(state=tk.NORMAL)
        self.btn_stop.configure(state=tk.DISABLED)

    def _on_engine_stopped(self) -> None:
        if not self._destroyed:
            try:
                self.after(0, self._sync_stopped_buttons)
            except Exception:
                pass

    def _sync_stopped_buttons(self) -> None:
        if not self._destroyed:
            self.btn_play.configure(state=tk.NORMAL)
            self.btn_stop.configure(state=tk.DISABLED)

    def export_wav(self) -> None:
        self._push_config()
        path = filedialog.asksaveasfilename(
            title="Exporter l'audio RAM en WAV",
            defaultextension=".wav",
            filetypes=[("Audio WAV", "*.wav")],
            initialfile="ram_symphony.wav",
        )
        if not path:
            return
        try:
            out = self.engine.export_wav(path, duration_sec=5.0)
            messagebox.showinfo("Export WAV réussi", f"Fichier enregistré :\n{out}")
        except Exception as exc:
            messagebox.showerror("Erreur Export WAV", str(exc))

    def _schedule_viz(self) -> None:
        if self._destroyed:
            return
        self._draw_scope()
        self._after_id = self.after(55, self._schedule_viz)

    def _draw_scope(self) -> None:
        c = self.scope_canvas
        w = max(200, c.winfo_width())
        h = max(140, c.winfo_height())
        c.delete("all")

        # Subtle grid lines
        mid_y = h / 2.0
        for frac in (0.25, 0.5, 0.75):
            y = h * frac
            c.create_line(0, y, w, y, fill="#1E293B", dash=(3, 5))
        for frac in (0.25, 0.5, 0.75):
            x = w * frac
            c.create_line(x, 0, x, h, fill="#1E293B", dash=(3, 5))

        tele = self.engine.get_telemetry()
        self.backend_lbl.configure(text=tele["backend"] if tele["is_playing"] else "En pause")
        self.chord_lbl.configure(text=f"Accord : {tele['current_chord']}")
        notes_str = " · ".join(tele["active_notes"]) if tele["active_notes"] else "En attente"
        self.notes_lbl.configure(text=f"Voix actives : {notes_str}")

        samples = tele["preview"]
        if not tele["is_playing"]:
            c.create_line(12, mid_y, w - 12, mid_y, fill="#334155", width=2)
            c.create_text(
                w / 2,
                mid_y - 20,
                text="Cliquez sur ▶ Lecture pour écouter la RAM en direct",
                fill=COLORS["text_muted"],
                font=("Segoe UI", 10),
            )
            return

        # Draw waveform polyline
        pts = []
        n = len(samples)
        pad_x = 14
        usable_w = max(10, w - pad_x * 2)
        amp_y = h * 0.36
        for i, s in enumerate(samples):
            x = pad_x + (i / max(1, n - 1)) * usable_w
            y = mid_y - s * amp_y
            pts.extend((x, y))

        if len(pts) >= 4:
            c.create_line(*pts, fill=COLORS["accent"], width=2.4, smooth=True)

        # Peak meter bar along bottom
        peak = max(0.0, min(1.0, tele["peak_level"]))
        bar_w = int((w - 28) * peak)
        c.create_rectangle(14, h - 18, w - 14, h - 10, fill="#1E293B", outline="")
        if bar_w > 0:
            col = COLORS["success"] if peak < 0.75 else (COLORS["warning"] if peak < 0.92 else COLORS["danger"])
            c.create_rectangle(14, h - 18, 14 + bar_w, h - 10, fill=col, outline="")

    def shutdown(self) -> None:
        self._destroyed = True
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self.engine.stop()
