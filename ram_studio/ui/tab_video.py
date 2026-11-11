"""Vidéo RAM tab — Instant clip renderer and continuous live video stream."""

from __future__ import annotations

import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from ram_studio.codecs import VideoStreamWriter, available_video_backends, rgb_bytes_to_ppm
from ram_studio.image_engine import ImageState, PALETTE_STOPS, SYMMETRIES
from ram_studio.ram_source import RAMEntropyPool
from ram_studio.ui.theme import COLORS, GeneratorTabShell
from ram_studio.video_engine import (
    VIDEO_FORMATS,
    VIDEO_RESOLUTIONS,
    VIDEO_STYLES,
    VideoConfig,
    render_video_clip,
    render_video_frame,
)


class VideoTab(GeneratorTabShell):
    """Vidéo RAM tab supporting finite clip export and continuous non-stop streaming."""

    def __init__(self, parent: tk.Misc, ram_pool: RAMEntropyPool):
        super().__init__(
            parent,
            title="Vidéo RAM",
            subtitle="Génère des clips vidéo (MP4/GIF/AVI) ou un flux animé continu piloté par la RAM.",
        )
        self.ram_pool = ram_pool
        self.output_dir = os.path.join(os.getcwd(), "ram_outputs")
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._streaming = False
        self._rendering_clip = False
        self._destroyed = False
        self._photo_ref: Optional[tk.PhotoImage] = None

        self._style_label_to_key = {v: k for k, v in VIDEO_STYLES.items()}
        self._sym_label_to_key = {v: k for k, v in SYMMETRIES.items()}

        self._build_simple()
        self._build_advanced()
        self._build_stage()

    def _build_simple(self) -> None:
        sf = self.simple_frame

        row_fmt = ttk.Frame(sf, style="Card.TFrame")
        row_fmt.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row_fmt, text="Format :", style="Card.TLabel", width=10).pack(side=tk.LEFT)
        self.fmt_var = tk.StringVar(value="mp4")
        ttk.Combobox(row_fmt, textvariable=self.fmt_var, values=VIDEO_FORMATS, state="readonly", width=10).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        ttk.Label(sf, text="Style Effet :", style="Card.TLabel").pack(anchor="w")
        self.style_var = tk.StringVar(value=VIDEO_STYLES["plasma_flow"])
        ttk.Combobox(sf, textvariable=self.style_var, values=list(VIDEO_STYLES.values()), state="readonly").pack(
            fill=tk.X, pady=(3, 8)
        )

        btn_row = ttk.Frame(sf, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(0, 6))
        self.btn_clip = ttk.Button(btn_row, text="🎬 Générer Clip", style="Accent.TButton", command=self.start_clip)
        self.btn_clip.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        self.btn_stream = ttk.Button(btn_row, text="♾️ Flux Continu", style="Success.TButton", command=self.toggle_stream)
        self.btn_stream.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.btn_stop = ttk.Button(sf, text="⏹ Arrêter", style="Danger.TButton", command=self.stop_all, state=tk.DISABLED)
        self.btn_stop.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(sf, text="📂 Dossier de sortie...", command=self.choose_output_dir).pack(fill=tk.X)

    def _build_advanced(self) -> None:
        af = self.advanced_frame

        def add_combo(label: str, var: tk.Variable, values: list) -> ttk.Combobox:
            row = ttk.Frame(af, style="Card.TFrame")
            row.pack(fill=tk.X, pady=3)
            ttk.Label(row, text=label, style="Card.TLabel", width=14).pack(side=tk.LEFT)
            cb = ttk.Combobox(row, textvariable=var, values=values, state="readonly")
            cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return cb

        self.pal_var = tk.StringVar(value="Cyberpunk")
        add_combo("Palette :", self.pal_var, list(PALETTE_STOPS.keys()))

        self.res_var = tk.StringVar(value="480x360")
        add_combo("Résolution :", self.res_var, list(VIDEO_RESOLUTIONS.keys()))

        self.sym_var = tk.StringVar(value=SYMMETRIES["none"])
        add_combo("Symétrie :", self.sym_var, list(SYMMETRIES.values()))

        row_fd = ttk.Frame(af, style="Card.TFrame")
        row_fd.pack(fill=tk.X, pady=4)
        ttk.Label(row_fd, text="FPS :", style="Card.TLabel").pack(side=tk.LEFT)
        self.fps_var = tk.IntVar(value=24)
        ttk.Spinbox(row_fd, from_=10, to=60, textvariable=self.fps_var, width=5).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(row_fd, text="Durée (s) :", style="Card.TLabel").pack(side=tk.LEFT)
        self.dur_var = tk.DoubleVar(value=4.0)
        ttk.Spinbox(row_fd, from_=1, to=120, increment=1, textvariable=self.dur_var, width=6).pack(side=tk.LEFT, padx=(4, 0))

        comp_hdr = ttk.Frame(af, style="Card.TFrame")
        comp_hdr.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(comp_hdr, text="Complexité shader :", style="Card.TLabel").pack(side=tk.LEFT)
        self.comp_lbl = ttk.Label(comp_hdr, text="5", style="CardMuted.TLabel")
        self.comp_lbl.pack(side=tk.RIGHT)
        self.comp_var = tk.IntVar(value=5)
        ttk.Scale(af, from_=1, to=10, variable=self.comp_var, command=lambda _v: self.comp_lbl.configure(text=str(int(self.comp_var.get())))).pack(fill=tk.X)

        fn_row = ttk.Frame(af, style="Card.TFrame")
        fn_row.pack(fill=tk.X, pady=(6, 4))
        ttk.Label(fn_row, text="Nom fichier :", style="Card.TLabel", width=14).pack(side=tk.LEFT)
        self.filename_var = tk.StringVar(value="ram_video")
        ttk.Entry(fn_row, textvariable=self.filename_var).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.audio_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="Inclure bande-son synthétique RAM (MP4)", variable=self.audio_var).pack(anchor="w", pady=2)
        self.record_stream_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(af, text="Enregistrer aussi le Flux Continu vers fichier", variable=self.record_stream_var).pack(anchor="w", pady=2)

    def _build_stage(self) -> None:
        hdr = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=10)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="Moniteur Vidéo & Encodage RAM", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        bk = available_video_backends()
        caps = [k for k in ("ffmpeg", "cv2", "pil", "imageio") if bk.get(k)]
        cap_txt = f"Codecs : {', '.join(caps) if caps else 'Pur Python (AVI/GIF)'}"
        tk.Label(hdr, text=cap_txt, bg=COLORS["card"], fg=COLORS["accent"], font=("Consolas", 9)).pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(self.stage_frame, bg="#050811", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        self.canvas.create_text(
            260,
            180,
            text="Prêt pour la génération Vidéo RAM\n(Clip instantané ou Flux continu)",
            fill=COLORS["text_muted"],
            font=("Segoe UI", 10),
            justify="center",
        )

        footer = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=8)
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, maximum=100, value=0)
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.status_lbl = tk.Label(footer, text="Prêt.", bg=COLORS["card"], fg=COLORS["text_muted"], font=("Consolas", 9))
        self.status_lbl.grid(row=1, column=0, sticky="w")

    def choose_output_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.output_dir, title="Choisir le dossier de sortie vidéo")
        if chosen:
            self.output_dir = chosen
            self.status_lbl.configure(text=f"Dossier : {self.output_dir}")

    def _current_config(self) -> VideoConfig:
        fmt = self.fmt_var.get().lower().strip(".") or "mp4"
        w, h = VIDEO_RESOLUTIONS.get(self.res_var.get(), (480, 360))
        base = self.filename_var.get().strip() or "ram_video"
        base_no_ext = os.path.splitext(base)[0]
        out_path = os.path.join(self.output_dir, f"{base_no_ext}_{int(time.time())}.{fmt}")
        return VideoConfig(
            fmt=fmt,
            style=self._style_label_to_key.get(self.style_var.get(), "plasma_flow"),
            palette_name=self.pal_var.get(),
            width=w,
            height=h,
            fps=max(10, min(60, int(self.fps_var.get()))),
            duration_sec=max(1.0, min(120.0, float(self.dur_var.get()))),
            complexity=max(1, min(10, int(self.comp_var.get()))),
            symmetry=self._sym_label_to_key.get(self.sym_var.get(), "none"),
            include_audio=bool(self.audio_var.get()),
            output_path=out_path,
        )

    def _set_running_ui(self, active: bool) -> None:
        self.btn_clip.configure(state=tk.DISABLED if active else tk.NORMAL)
        self.btn_stream.configure(state=tk.DISABLED if active and self._rendering_clip else tk.NORMAL)
        self.btn_stop.configure(state=tk.NORMAL if active else tk.DISABLED)
        if not active:
            self.btn_stream.configure(text="♾️ Flux Continu", style="Success.TButton")

    def start_clip(self) -> None:
        if self._rendering_clip or self._streaming:
            return
        cfg = self._current_config()
        self._stop_event.clear()
        self._rendering_clip = True
        self._set_running_ui(True)
        self.progress.configure(value=0)
        self.status_lbl.configure(text=f"Encodage {cfg.fmt.upper()} en cours ({cfg.width}x{cfg.height} @ {cfg.fps} FPS)...")

        def on_progress(cur: int, total: int, rgb: bytes) -> None:
            if self._destroyed:
                return
            pct = (cur / max(1, total)) * 100.0
            if cur == 1 or cur == total or cur % 3 == 0:
                self.after(0, lambda: self._update_preview(cfg.width, cfg.height, rgb, pct, f"Image {cur}/{total}"))

        def worker() -> None:
            try:
                out_path = render_video_clip(
                    self.ram_pool,
                    cfg,
                    progress_cb=on_progress,
                    stop_event=self._stop_event,
                )
                if not self._destroyed:
                    self.after(0, lambda: self._on_clip_done(out_path, None))
            except Exception as exc:
                if not self._destroyed:
                    self.after(0, lambda: self._on_clip_done("", str(exc)))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _on_clip_done(self, out_path: str, err: Optional[str]) -> None:
        self._rendering_clip = False
        self._set_running_ui(False)
        if err:
            self.status_lbl.configure(text=f"Erreur : {err}")
            messagebox.showerror("Erreur Vidéo", err)
        elif self._stop_event.is_set():
            self.status_lbl.configure(text="Encodage arrêté.")
        else:
            self.progress.configure(value=100)
            self.status_lbl.configure(text=f"✅ Vidéo enregistrée : {out_path}")

    def toggle_stream(self) -> None:
        if self._streaming:
            self.stop_all()
            return
        if self._rendering_clip:
            return
        cfg = self._current_config()
        self._stop_event.clear()
        self._streaming = True
        self._set_running_ui(True)
        self.btn_stream.configure(text="⏹ Stop Flux", style="Danger.TButton")

        record = bool(self.record_stream_var.get())
        writer = VideoStreamWriter(cfg.output_path, cfg.width, cfg.height, fps=cfg.fps, fmt=cfg.fmt) if record else None
        img_state = ImageState()

        def worker() -> None:
            frame_count = 0
            try:
                while not self._stop_event.is_set() and not self._destroyed:
                    t0 = time.perf_counter()
                    live_cfg = self._current_config()
                    ram_bytes = self.ram_pool.sample_bytes(512, step=live_cfg.read_step)
                    w, h, rgb = render_video_frame(ram_bytes, live_cfg, img_state)
                    if writer is not None:
                        writer.write_frame(rgb)
                    frame_count += 1
                    if not self._destroyed:
                        msg = f"Flux direct #{frame_count} • {w}x{h}" + (f" • Enregistrement {live_cfg.fmt.upper()}" if writer else "")
                        self.after(0, lambda w_=w, h_=h, r_=rgb, m_=msg: self._update_preview(w_, h_, r_, 0, m_))
                    elapsed = time.perf_counter() - t0
                    sleep_s = max(0.01, (1.0 / max(5, live_cfg.fps)) - elapsed)
                    time.sleep(sleep_s)
            finally:
                saved = ""
                if writer is not None:
                    try:
                        saved = writer.close()
                    except Exception:
                        saved = ""
                if not self._destroyed:
                    self.after(0, lambda: self._on_stream_stopped(saved))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _on_stream_stopped(self, saved: str) -> None:
        self._streaming = False
        self._set_running_ui(False)
        self.status_lbl.configure(text=f"✅ Flux enregistré : {saved}" if saved else "Flux arrêté.")

    def _update_preview(self, w: int, h: int, rgb: bytes, pct: float, msg: str) -> None:
        if self._destroyed:
            return
        if pct > 0:
            self.progress.configure(value=pct)
        self.status_lbl.configure(text=msg)

        ppm = rgb_bytes_to_ppm(w, h, rgb)
        photo = tk.PhotoImage(data=ppm, format="PPM")
        cw = max(160, self.canvas.winfo_width())
        ch = max(120, self.canvas.winfo_height())
        # Fit nicely inside canvas using integer subsample/zoom
        if w > cw or h > ch:
            factor = max(2, (max(w // cw, h // ch) + 1))
            photo = photo.subsample(factor, factor)
        elif cw >= w * 2 and ch >= h * 2:
            photo = photo.zoom(2, 2)
        self._photo_ref = photo
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=photo, anchor=tk.CENTER)

    def stop_all(self) -> None:
        self._stop_event.set()
        self._streaming = False

    def shutdown(self) -> None:
        self._destroyed = True
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.5)
