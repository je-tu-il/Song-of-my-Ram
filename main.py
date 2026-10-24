#!/usr/bin/env python3
"""
Song-of-my-Ram — RAM Synthesis & Audio Engine
Translate live Windows RAM memory pages into audible real-time MIDI concerto & raw PCM synthesis.
"""

import sys
import os
import time
import threading
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, messagebox
import psutil

# Optional PyAudio for Raw PCM Mode
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    pyaudio = None
    PYAUDIO_AVAILABLE = False


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def request_admin():
    if not is_admin():
        try:
            params = " ".join([f'"{arg}"' for arg in sys.argv])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            sys.exit(0)
        except Exception as e:
            messagebox.showerror(
                "Privilèges insuffisants",
                f"L'accès en lecture à la mémoire des processus nécessite les droits Administrateur.\nErreur : {e}"
            )
            sys.exit(1)


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.windll.winmm


class ProcessReader:
    def __init__(self, pid):
        self.handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        self.address = 0
        self.current_region_end = 0

    def read_byte(self, step=512):
        if not self.handle:
            return 0

        while True:
            if self.address >= self.current_region_end:
                mbi = MEMORY_BASIC_INFORMATION()
                if not kernel32.VirtualQueryEx(
                    self.handle, ctypes.c_void_p(self.address), ctypes.byref(mbi), ctypes.sizeof(mbi)
                ):
                    self.address = 0
                    self.current_region_end = 0
                    return 0

                base_addr = mbi.BaseAddress or 0
                self.current_region_end = base_addr + mbi.RegionSize

                if mbi.State != MEM_COMMIT or (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                    self.address = self.current_region_end
                    continue

            buffer = ctypes.create_string_buffer(1)
            bytes_read = ctypes.c_size_t(0)
            success = kernel32.ReadProcessMemory(
                self.handle, ctypes.c_void_p(self.address), buffer, 1, ctypes.byref(bytes_read)
            )
            self.address += step

            if success and bytes_read.value > 0:
                return buffer.raw[0]
            else:
                self.address = self.current_region_end

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None


class RAMOrchestrator:
    def __init__(self, root):
        self.root = root
        self.root.title("Song-of-my-Ram — RAM Audio Engine")
        self.root.geometry("580x480")
        self.root.minsize(520, 420)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.is_playing = False
        self.audio_thread = None
        self.bpm = 60
        self.max_processes = 10
        self.readers = []

        self.scales = {
            "bass": [36, 38, 40, 43, 45],
            "chord": [(48, 52, 55), (50, 53, 57), (52, 55, 59), (55, 59, 62), (57, 60, 64)],
            "arpeggio": [60, 62, 64, 67, 69, 72],
            "melody": [72, 74, 76, 79, 81, 84],
        }

        self.roles = [
            {"name": "Cello", "channel": 0, "instrument": 42, "dur_mult": 1.0, "scale": "bass", "vol": 0.9},
            {"name": "Electric Piano", "channel": 1, "instrument": 4, "dur_mult": 0.5, "scale": "chord", "vol": 0.7},
            {"name": "Marimba", "channel": 2, "instrument": 12, "dur_mult": 0.25, "scale": "arpeggio", "vol": 0.6},
            {"name": "Alto Sax", "channel": 3, "instrument": 65, "dur_mult": 0.125, "scale": "melody", "vol": 0.8},
            {"name": "Synth Pad", "channel": 4, "instrument": 88, "dur_mult": 2.0, "scale": "chord", "vol": 0.5},
            {"name": "Clean Guitar", "channel": 5, "instrument": 27, "dur_mult": 0.5, "scale": "arpeggio", "vol": 0.6},
            {"name": "Glockenspiel", "channel": 6, "instrument": 9, "dur_mult": 0.25, "scale": "melody", "vol": 0.7},
            {"name": "Synth Bass", "channel": 7, "instrument": 38, "dur_mult": 1.0, "scale": "bass", "vol": 0.8},
            {"name": "Clarinet", "channel": 8, "instrument": 71, "dur_mult": 0.125, "scale": "melody", "vol": 0.7},
            {"name": "Pizzicato", "channel": 10, "instrument": 45, "dur_mult": 0.5, "scale": "chord", "vol": 0.6},
        ]

        self.target_processes = []

        self.setup_ui()
        self.auto_select_processes()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_lbl = ttk.Label(main_frame, text="RAM Synthesis & Orchestration", font=("Segoe UI", 13, "bold"))
        title_lbl.pack(pady=(0, 8))

        # Mode selection
        self.mode_var = tk.StringVar(value="midi")
        mode_frame = ttk.LabelFrame(main_frame, text="Mode de Rendu Audio", padding="8")
        mode_frame.pack(fill=tk.X, pady=5)

        ttk.Radiobutton(
            mode_frame,
            text="Concerto (Instruments MIDI natifs Windows)",
            variable=self.mode_var,
            value="midi"
        ).pack(anchor=tk.W, pady=2)

        pcm_label = "Électronique (Raw PCM direct)"
        if not PYAUDIO_AVAILABLE:
            pcm_label += " [Nécessite PyAudio]"
        ttk.Radiobutton(
            mode_frame,
            text=pcm_label,
            variable=self.mode_var,
            value="pcm"
        ).pack(anchor=tk.W, pady=2)

        # Tempo slider
        bpm_frame = ttk.Frame(main_frame)
        bpm_frame.pack(pady=8, fill=tk.X)
        ttk.Label(bpm_frame, text="Tempo (BPM) :", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.bpm_var = tk.IntVar(value=self.bpm)
        self.bpm_slider = ttk.Scale(bpm_frame, from_=20, to=200, variable=self.bpm_var, command=self.update_bpm)
        self.bpm_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.bpm_label = ttk.Label(bpm_frame, text=f"{self.bpm} BPM", width=8)
        self.bpm_label.pack(side=tk.LEFT)

        # Process list display
        list_header = ttk.Frame(main_frame)
        list_header.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(list_header, text="Processus ciblés (Top RAM) :", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Button(list_header, text="🔄 Rafraîchir", command=self.auto_select_processes, width=12).pack(side=tk.RIGHT)

        self.info_text = tk.Text(
            main_frame, height=9, width=64, state=tk.DISABLED, bg="#f8f9fa", font=("Consolas", 9), relief=tk.SOLID, borderwidth=1
        )
        self.info_text.pack(fill=tk.BOTH, expand=True, pady=4)

        # Action buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)

        self.btn_play = ttk.Button(btn_frame, text="▶ Démarrer la Lecture", command=self.play, width=22)
        self.btn_play.pack(side=tk.LEFT, padx=8)

        self.btn_pause = ttk.Button(btn_frame, text="⏸ Pause", command=self.stop, width=16)
        self.btn_pause.pack(side=tk.LEFT, padx=8)

        # Status footer
        self.status_var = tk.StringVar(value="Prêt.")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, font=("Segoe UI", 8))
        status_bar.pack(fill=tk.X, pady=(5, 0))

    def update_bpm(self, val):
        self.bpm = int(float(val))
        self.bpm_label.config(text=f"{self.bpm} BPM")

    def auto_select_processes(self):
        procs = []
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                pid = proc.info["pid"]
                if proc.info["memory_info"] is None or pid == 0:
                    continue

                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    procs.append(proc.info)
            except Exception:
                continue

        procs.sort(key=lambda x: x["memory_info"].rss, reverse=True)
        self.target_processes = procs[: self.max_processes]

        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        for i, p in enumerate(self.target_processes):
            ram_mb = p["memory_info"].rss / (1024 * 1024)
            role_name = self.roles[i % len(self.roles)]["name"]
            self.info_text.insert(tk.END, f"[{role_name:<14}] {p['name']:<24} (PID: {p['pid']:<6} | {ram_mb:6.1f} Mo)\n")
        self.info_text.config(state=tk.DISABLED)
        self.status_var.set(f"{len(self.target_processes)} processus détectés et prêts pour la synthèse.")

    def play(self):
        if self.is_playing:
            return

        if not self.target_processes:
            self.auto_select_processes()
            if not self.target_processes:
                messagebox.showwarning("Aucun processus", "Impossible de détecter des processus lisibles.")
                return

        selected_mode = self.mode_var.get()
        if selected_mode == "pcm" and not PYAUDIO_AVAILABLE:
            messagebox.showwarning(
                "PyAudio Requis",
                "Le mode brut PCM nécessite le module 'pyaudio'.\n"
                "Installez-le avec : pip install pyaudio\n\n"
                "Le mode 'Concerto MIDI' fonctionne immédiatement sans aucune dépendance supplémentaire !"
            )
            self.mode_var.set("midi")
            selected_mode = "midi"

        self.is_playing = True
        self.btn_play.configure(state=tk.DISABLED)
        self.status_var.set(f"Lecture en cours (Mode: {'MIDI' if selected_mode == 'midi' else 'Raw PCM'})...")

        if selected_mode == "pcm":
            self.audio_thread = threading.Thread(target=self.electronic_audio_loop, daemon=True)
        else:
            self.audio_thread = threading.Thread(target=self.midi_audio_loop, daemon=True)
        self.audio_thread.start()

    def stop(self):
        self.is_playing = False
        self.btn_play.configure(state=tk.NORMAL)
        self.status_var.set("Lecture en pause.")

    def on_close(self):
        self.stop()
        for r in self.readers:
            try:
                r.close()
            except Exception:
                pass
        self.root.destroy()

    def electronic_audio_loop(self):
        if not PYAUDIO_AVAILABLE or not self.target_processes:
            self.stop()
            return

        pid = self.target_processes[0]["pid"]
        process_handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not process_handle:
            self.stop()
            return

        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paUInt8, channels=1, rate=44100, output=True)
        except Exception as e:
            self.stop()
            messagebox.showerror("Erreur Audio PCM", f"Impossible d'initialiser PyAudio : {e}")
            kernel32.CloseHandle(process_handle)
            return

        address = 0
        mbi = MEMORY_BASIC_INFORMATION()

        while self.is_playing and kernel32.VirtualQueryEx(
            process_handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            if mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                buffer = ctypes.create_string_buffer(mbi.RegionSize)
                bytes_read = ctypes.c_size_t(0)

                success = kernel32.ReadProcessMemory(
                    process_handle, ctypes.c_void_p(address), buffer, mbi.RegionSize, ctypes.byref(bytes_read)
                )

                if success and bytes_read.value > 0:
                    try:
                        stream.write(buffer.raw[: bytes_read.value])
                    except Exception:
                        pass
            address += mbi.RegionSize

        try:
            stream.stop_stream()
            stream.close()
            p.terminate()
        except Exception:
            pass
        kernel32.CloseHandle(process_handle)
        self.stop()

    def midi_audio_loop(self):
        hMidiOut = ctypes.c_void_p()
        res = winmm.midiOutOpen(ctypes.byref(hMidiOut), 0, 0, 0, 0)
        if res != 0:
            self.stop()
            messagebox.showerror("Erreur MIDI", "Impossible d'ouvrir le périphérique MIDI Windows.")
            return

        # Initialize instruments for each channel
        for config in self.roles:
            msg = 0xC0 | config["channel"] | (config["instrument"] << 8)
            winmm.midiOutShortMsg(hMidiOut, msg)

        self.readers = [ProcessReader(p["pid"]) for p in self.target_processes]
        next_tick_time = time.perf_counter()
        tick = 0
        active_notes = []

        while self.is_playing:
            now = time.perf_counter()
            tick_duration = (60.0 / max(20, self.bpm)) / 8

            remaining_notes = []
            for off_time, channel, note in active_notes:
                if now >= off_time:
                    msg = 0x80 | channel | (note << 8)
                    winmm.midiOutShortMsg(hMidiOut, msg)
                else:
                    remaining_notes.append((off_time, channel, note))
            active_notes = remaining_notes

            if now >= next_tick_time:
                for i, reader in enumerate(self.readers):
                    config = self.roles[i % len(self.roles)]
                    tick_interval = int(config["dur_mult"] / 0.125)
                    if tick_interval == 0:
                        tick_interval = 1

                    if tick % tick_interval == 0:
                        val = reader.read_byte(step=2048)
                        if val != 0:
                            scale = self.scales[config["scale"]]
                            item = scale[val % len(scale)]

                            channel = config["channel"]
                            vol = int(config["vol"] * 127)
                            note_duration = config["dur_mult"] * (60.0 / self.bpm) * 0.9

                            notes_to_play = item if isinstance(item, tuple) else (item,)
                            for note in notes_to_play:
                                msg = 0x90 | channel | (note << 8) | (vol << 16)
                                winmm.midiOutShortMsg(hMidiOut, msg)
                                active_notes.append((now + note_duration, channel, note))

                tick += 1
                next_tick_time += tick_duration
            else:
                time.sleep(0.001)

        # Silence remaining notes
        for _, channel, note in active_notes:
            msg = 0x80 | channel | (note << 8)
            winmm.midiOutShortMsg(hMidiOut, msg)

        winmm.midiOutClose(hMidiOut)
        for r in self.readers:
            r.close()
        self.readers = []
        self.stop()


def main():
    if os.name == "nt":
        request_admin()
    root = tk.Tk()
    app = RAMOrchestrator(root)
    root.mainloop()


if __name__ == "__main__":
    main()
