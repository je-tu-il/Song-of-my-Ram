"""Modèle 3D RAM tab — One-shot & continuous evolving 3D meshes with live interactive preview."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from ram_studio.model3d_engine import (
    COLOR_THEMES,
    Mesh3D,
    Model3DConfig,
    RENDER_MODES,
    TOPOLOGIES,
    export_obj,
    export_stl,
    generate_mesh_from_bytes,
    project_mesh_for_canvas,
)
from ram_studio.ram_source import RAMEntropyPool
from ram_studio.ui.theme import COLORS, GeneratorTabShell


class Model3DTab(GeneratorTabShell):
    """Interactive 3D RAM model generator with OBJ/STL export."""

    def __init__(self, parent: tk.Misc, ram_pool: RAMEntropyPool):
        super().__init__(
            parent,
            title="Modèle 3D RAM",
            subtitle="Sculpture 3D procédurale alimentée par la RAM avec aperçu interactif et export OBJ/STL.",
        )
        self.ram_pool = ram_pool
        self._topo_label_to_key = {v: k for k, v in TOPOLOGIES.items()}
        self._rmode_label_to_key = {v: k for k, v in RENDER_MODES.items()}

        self.yaw = 0.65
        self.pitch = 0.42
        self.zoom = 1.05
        self.morph_phase = 0.0
        self.is_continuous = False
        self._dragging = False
        self._drag_last = (0, 0)
        self._destroyed = False
        self._after_id: Optional[str] = None
        self.current_mesh: Optional[Mesh3D] = None

        self._build_simple()
        self._build_advanced()
        self._build_stage()
        self.generate_one_shot()
        self._schedule_tick()

    def _build_simple(self) -> None:
        sf = self.simple_frame

        ttk.Label(sf, text="Topologie 3D :", style="Card.TLabel").pack(anchor="w")
        self.topo_var = tk.StringVar(value=TOPOLOGIES["supershape"])
        cb_topo = ttk.Combobox(sf, textvariable=self.topo_var, values=list(TOPOLOGIES.values()), state="readonly")
        cb_topo.pack(fill=tk.X, pady=(3, 8))
        cb_topo.bind("<<ComboboxSelected>>", lambda _e: self.generate_one_shot())

        btn_row = ttk.Frame(sf, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(btn_row, text="🧊 1 Modèle", style="Accent.TButton", command=self.generate_one_shot).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
        )
        self.btn_cont = ttk.Button(btn_row, text="♾️ Continu", style="Success.TButton", command=self.toggle_continuous)
        self.btn_cont.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        exp_row = ttk.Frame(sf, style="Card.TFrame")
        exp_row.pack(fill=tk.X)
        ttk.Button(exp_row, text="💾 Export .OBJ", command=self.save_obj).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(exp_row, text="💾 Export .STL", command=self.save_stl).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

    def _build_advanced(self) -> None:
        af = self.advanced_frame

        row_rm = ttk.Frame(af, style="Card.TFrame")
        row_rm.pack(fill=tk.X, pady=3)
        ttk.Label(row_rm, text="Rendu :", style="Card.TLabel", width=13).pack(side=tk.LEFT)
        self.rmode_var = tk.StringVar(value=RENDER_MODES["hybrid"])
        cb_rm = ttk.Combobox(row_rm, textvariable=self.rmode_var, values=list(RENDER_MODES.values()), state="readonly")
        cb_rm.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cb_rm.bind("<<ComboboxSelected>>", lambda _e: self._render_viewport())

        row_col = ttk.Frame(af, style="Card.TFrame")
        row_col.pack(fill=tk.X, pady=3)
        ttk.Label(row_col, text="Thème :", style="Card.TLabel", width=13).pack(side=tk.LEFT)
        self.theme_var = tk.StringVar(value="Cyber Cyan")
        cb_col = ttk.Combobox(row_col, textvariable=self.theme_var, values=list(COLOR_THEMES.keys()), state="readonly")
        cb_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        cb_col.bind("<<ComboboxSelected>>", lambda _e: self._render_viewport())

        # Subdivisions & Smoothing
        row_ss = ttk.Frame(af, style="Card.TFrame")
        row_ss.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(row_ss, text="Subdivisions :", style="Card.TLabel").pack(side=tk.LEFT)
        self.subdiv_var = tk.IntVar(value=14)
        ttk.Spinbox(row_ss, from_=6, to=26, textvariable=self.subdiv_var, width=5, command=self.generate_one_shot).pack(
            side=tk.LEFT, padx=(4, 10)
        )
        ttk.Label(row_ss, text="Lissage :", style="Card.TLabel").pack(side=tk.LEFT)
        self.smooth_var = tk.IntVar(value=1)
        ttk.Spinbox(row_ss, from_=0, to=3, textvariable=self.smooth_var, width=4, command=self.generate_one_shot).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        # Amplitude / Frequency / Twist
        def add_slider(label: str, from_: float, to: float, var: tk.DoubleVar, fmt: str) -> tk.Label:
            hdr = ttk.Frame(af, style="Card.TFrame")
            hdr.pack(fill=tk.X, pady=(4, 0))
            ttk.Label(hdr, text=label, style="Card.TLabel").pack(side=tk.LEFT)
            val_lbl = tk.Label(hdr, text=fmt.format(var.get()), bg=COLORS["card"], fg=COLORS["text_muted"], font=("Segoe UI", 8))
            val_lbl.pack(side=tk.RIGHT)
            scale = ttk.Scale(
                af,
                from_=from_,
                to=to,
                variable=var,
                command=lambda _v, l=val_lbl, f=fmt, vr=var: l.configure(text=f.format(vr.get())),
            )
            scale.pack(fill=tk.X)
            scale.bind("<ButtonRelease-1>", lambda _e: self.generate_one_shot() if not self.is_continuous else None)
            return val_lbl

        self.amp_var = tk.DoubleVar(value=0.8)
        add_slider("Amplitude relief :", 0.1, 2.0, self.amp_var, "{:.2f}")

        self.freq_var = tk.DoubleVar(value=2.5)
        add_slider("Fréquence harmonique :", 0.5, 6.0, self.freq_var, "{:.2f}")

        self.twist_var = tk.DoubleVar(value=0.6)
        add_slider("Torsion / Twist :", 0.0, 3.0, self.twist_var, "{:.2f}")

        self.morph_speed_var = tk.DoubleVar(value=0.8)
        add_slider("Vitesse évolution continue :", 0.1, 2.5, self.morph_speed_var, "{:.1f}x")

        self.auto_rot_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="Rotation automatique de la vue", variable=self.auto_rot_var).pack(anchor="w", pady=(6, 2))

        self.stl_binary_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(af, text="Exporter STL en format Binaire (compact)", variable=self.stl_binary_var).pack(anchor="w", pady=2)

        ttk.Button(af, text="🎯 Réinitialiser Caméra & Appliquer", command=self._reset_and_regen).pack(fill=tk.X, pady=(6, 0))

    def _build_stage(self) -> None:
        hdr = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=10)
        hdr.grid(row=0, column=0, sticky="ew")
        tk.Label(hdr, text="Viewport 3D Interactif (Glisser = Rotation • Molette = Zoom)", bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.sig_lbl = tk.Label(hdr, text="—", bg=COLORS["card"], fg=COLORS["accent"], font=("Consolas", 9))
        self.sig_lbl.pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(self.stage_frame, bg="#050811", highlightthickness=0, cursor="fleur")
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<MouseWheel>", self._on_zoom)
        self.canvas.bind("<Configure>", lambda _e: self._render_viewport())

        footer = tk.Frame(self.stage_frame, bg=COLORS["card"], padx=14, pady=8)
        footer.grid(row=2, column=0, sticky="ew")
        self.stats_lbl = tk.Label(footer, text="Prêt.", bg=COLORS["card"], fg=COLORS["text_muted"], font=("Consolas", 9))
        self.stats_lbl.pack(side=tk.LEFT)

    def _on_drag_start(self, event) -> None:
        self._dragging = True
        self._drag_last = (event.x, event.y)

    def _on_drag_move(self, event) -> None:
        dx = event.x - self._drag_last[0]
        dy = event.y - self._drag_last[1]
        self._drag_last = (event.x, event.y)
        self.yaw += dx * 0.012
        self.pitch = max(-1.45, min(1.45, self.pitch + dy * 0.012))
        self._render_viewport()

    def _on_drag_end(self, _event) -> None:
        self._dragging = False

    def _on_zoom(self, event) -> None:
        factor = 1.08 if event.delta > 0 else 0.92
        self.zoom = max(0.35, min(3.2, self.zoom * factor))
        self._render_viewport()

    def _reset_and_regen(self) -> None:
        self.yaw = 0.65
        self.pitch = 0.42
        self.zoom = 1.05
        self.generate_one_shot()

    def _current_config(self) -> Model3DConfig:
        return Model3DConfig(
            topology=self._topo_label_to_key.get(self.topo_var.get(), "supershape"),
            color_theme=self.theme_var.get(),
            render_mode=self._rmode_label_to_key.get(self.rmode_var.get(), "hybrid"),
            subdivisions=max(6, min(26, int(self.subdiv_var.get()))),
            amplitude=float(self.amp_var.get()),
            frequency=float(self.freq_var.get()),
            twist=float(self.twist_var.get()),
            smoothing=max(0, min(3, int(self.smooth_var.get()))),
            auto_rotate=bool(self.auto_rot_var.get()),
            morph_speed=float(self.morph_speed_var.get()),
        )

    def generate_one_shot(self) -> None:
        cfg = self._current_config()
        ram_bytes = self.ram_pool.sample_bytes(512, step=cfg.read_step)
        self.current_mesh = generate_mesh_from_bytes(ram_bytes, cfg, phase=self.morph_phase)
        self._render_viewport()

    def toggle_continuous(self) -> None:
        if self.is_continuous:
            self.is_continuous = False
            self.btn_cont.configure(text="♾️ Continu", style="Success.TButton")
        else:
            self.is_continuous = True
            self.btn_cont.configure(text="⏹ Stop Continu", style="Danger.TButton")

    def _schedule_tick(self) -> None:
        if self._destroyed:
            return
        changed = False
        if self.is_continuous:
            cfg = self._current_config()
            self.morph_phase += 0.10 * cfg.morph_speed
            ram_bytes = self.ram_pool.sample_bytes(512, step=cfg.read_step)
            self.current_mesh = generate_mesh_from_bytes(ram_bytes, cfg, phase=self.morph_phase)
            changed = True
        if self.auto_rot_var.get() and not self._dragging:
            self.yaw += 0.032
            changed = True
        if changed:
            self._render_viewport()
        self._after_id = self.after(40, self._schedule_tick)

    def _render_viewport(self) -> None:
        if self._destroyed or self.current_mesh is None:
            return
        c = self.canvas
        w = max(200, c.winfo_width())
        h = max(180, c.winfo_height())
        cfg = self._current_config()
        proj = project_mesh_for_canvas(
            self.current_mesh,
            width=w,
            height=h,
            yaw=self.yaw,
            pitch=self.pitch,
            zoom=self.zoom,
            render_mode=cfg.render_mode,
            color_theme=cfg.color_theme,
        )

        c.delete("all")
        # Subtle floor horizon reference
        c.create_oval(w * 0.25, h * 0.72, w * 0.75, h * 0.9, outline="#1E293B", dash=(4, 6))

        if proj["mode"] == "wireframe":
            wcol = proj["wire_color"]
            for x0, y0, x1, y1 in proj["lines"]:
                c.create_line(x0, y0, x1, y1, fill=wcol, width=1.1)
        else:
            for coords, fill_hex, out_hex in proj["polys"]:
                c.create_polygon(*coords, fill=fill_hex, outline=out_hex, width=1)

        m = self.current_mesh
        self.sig_lbl.configure(text=f"Signature RAM: {m.ram_signature}")
        mode_txt = "Évolution continue" if self.is_continuous else "One-Shot"
        self.stats_lbl.configure(
            text=f"{TOPOLOGIES.get(m.topology)} • {m.vertex_count} sommets • {m.triangle_count} triangles • {mode_txt}"
        )

    def save_obj(self) -> None:
        if self.current_mesh is None:
            return
        path = filedialog.asksaveasfilename(
            title="Exporter le modèle 3D (.OBJ)",
            defaultextension=".obj",
            filetypes=[("Wavefront OBJ", "*.obj")],
            initialfile=f"ram_{self.current_mesh.topology}.obj",
        )
        if not path:
            return
        try:
            out = export_obj(self.current_mesh, path)
            messagebox.showinfo("Export OBJ réussi", f"Modèle exporté :\n{out}")
        except Exception as exc:
            messagebox.showerror("Erreur Export OBJ", str(exc))

    def save_stl(self) -> None:
        if self.current_mesh is None:
            return
        path = filedialog.asksaveasfilename(
            title="Exporter le modèle 3D (.STL)",
            defaultextension=".stl",
            filetypes=[("Stereolithography STL", "*.stl")],
            initialfile=f"ram_{self.current_mesh.topology}.stl",
        )
        if not path:
            return
        try:
            out = export_stl(self.current_mesh, path, binary=bool(self.stl_binary_var.get()))
            messagebox.showinfo("Export STL réussi", f"Modèle exporté :\n{out}")
        except Exception as exc:
            messagebox.showerror("Erreur Export STL", str(exc))

    def shutdown(self) -> None:
        self._destroyed = True
        self.is_continuous = False
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
