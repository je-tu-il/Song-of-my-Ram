"""Main Song-of-my-Ram Studio tabbed desktop application."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

from ram_studio import __app_name__, __version__
from ram_studio.ram_source import ProcessInfo, RAMEntropyPool, elevate_admin, is_admin
from ram_studio.ui.tab_audio import AudioTab
from ram_studio.ui.tab_image import ImageTab
from ram_studio.ui.tab_model3d import Model3DTab
from ram_studio.ui.tab_password import PasswordTab
from ram_studio.ui.tab_text import TextTab
from ram_studio.ui.tab_video import VideoTab
from ram_studio.ui.theme import COLORS, apply_studio_theme


class SongOfRamStudioApp:
    """Top-level multi-tab Studio controller for Song-of-my-Ram."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{__app_name__} v{__version__}")
        self.root.geometry("1120x740")
        self.root.minsize(880, 600)
        apply_studio_theme(self.root)

        self.ram_pool = RAMEntropyPool(max_processes=12)
        self._proc_map: Dict[str, Optional[int]] = {}
        self.tabs: List = []

        self._build_header()
        self._build_notebook()
        self._refresh_process_dropdown()
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

    def _build_header(self) -> None:
        hdr = tk.Frame(self.root, bg=COLORS["surface"], highlightbackground=COLORS["card_border"], highlightthickness=1, padx=14, pady=10)
        hdr.pack(fill=tk.X, padx=10, pady=(10, 0))

        # Brand block
        brand = tk.Frame(hdr, bg=COLORS["surface"])
        brand.pack(side=tk.LEFT)
        tk.Label(
            brand,
            text="🎵 Song of my RAM — Studio Créatif",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="Audio · Images · Mots de Passe · Vidéo · Texte · Modèle 3D",
            bg=COLORS["surface"],
            fg=COLORS["text_muted"],
            font=("Segoe UI", 8),
        ).pack(anchor="w")

        # Right side controls: Target RAM process selector + Admin badge
        right = tk.Frame(hdr, bg=COLORS["surface"])
        right.pack(side=tk.RIGHT)

        tk.Label(right, text="Source RAM :", bg=COLORS["surface"], fg=COLORS["text_muted"], font=("Segoe UI", 9)).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        self.proc_var = tk.StringVar(value="Auto (Mix Top RAM)")
        self.proc_combo = ttk.Combobox(right, textvariable=self.proc_var, state="readonly", width=34)
        self.proc_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.proc_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_select_process())

        ttk.Button(right, text="🔄", width=3, command=self._refresh_process_dropdown).pack(side=tk.LEFT, padx=(0, 8))

        if is_admin():
            tk.Label(
                right,
                text="🛡️ Admin",
                bg="#064E3B",
                fg="#6EE7B7",
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=4,
            ).pack(side=tk.LEFT)
        elif os.name == "nt":
            ttk.Button(right, text="🛡️ Mode Admin", command=self._request_elevation).pack(side=tk.LEFT)

    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        tab_audio = AudioTab(self.notebook, self.ram_pool)
        tab_image = ImageTab(self.notebook, self.ram_pool)
        tab_password = PasswordTab(self.notebook, self.ram_pool)
        tab_video = VideoTab(self.notebook, self.ram_pool)
        tab_text = TextTab(self.notebook, self.ram_pool)
        tab_model3d = Model3DTab(self.notebook, self.ram_pool)

        self.tabs = [tab_audio, tab_image, tab_password, tab_video, tab_text, tab_model3d]

        self.notebook.add(tab_audio, text="  🎵 Audio RAM  ")
        self.notebook.add(tab_image, text="  🖼️ Images RAM  ")
        self.notebook.add(tab_password, text="  🔐 Mots de Passe  ")
        self.notebook.add(tab_video, text="  🎬 Vidéo RAM  ")
        self.notebook.add(tab_text, text="  📜 Texte RAM  ")
        self.notebook.add(tab_model3d, text="  🧊 Modèle 3D  ")

    def _refresh_process_dropdown(self) -> None:
        procs: List[ProcessInfo] = self.ram_pool.refresh_processes()
        auto_label = f"Auto (Mix Top {len(procs)} processus)"
        self._proc_map = {auto_label: None}
        labels = [auto_label]
        for p in procs:
            lbl = p.label
            self._proc_map[lbl] = p.pid
            labels.append(lbl)
        self.proc_combo.configure(values=labels)
        if self.proc_var.get() not in self._proc_map:
            self.proc_var.set(auto_label)
            self.ram_pool.set_selected_pid(None)

    def _on_select_process(self) -> None:
        pid = self._proc_map.get(self.proc_var.get())
        self.ram_pool.set_selected_pid(pid)

    def _request_elevation(self) -> None:
        if elevate_admin():
            self.shutdown()
            sys.exit(0)
        else:
            messagebox.showinfo(
                "Mode Standard",
                "L'élévation Administrateur a été annulée.\nL'application continue en mode utilisateur standard.",
            )

    def shutdown(self) -> None:
        for tab in self.tabs:
            try:
                tab.shutdown()
            except Exception:
                pass
        try:
            self.ram_pool.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


def launch_studio(force_admin: bool = False) -> None:
    """Launch the Song-of-my-Ram Studio GUI."""
    if force_admin and os.name == "nt" and not is_admin():
        if elevate_admin():
            sys.exit(0)
    root = tk.Tk()
    SongOfRamStudioApp(root)
    root.mainloop()
