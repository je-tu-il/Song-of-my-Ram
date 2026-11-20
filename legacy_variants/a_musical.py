import tkinter as tk
from tkinter import ttk
import ctypes
from ctypes import wintypes
import pyaudio
import numpy as np
import threading
import time
import random
import math
import psutil
import sys

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    sys.exit()

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

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
winmm = ctypes.windll.winmm

# ---------------------------------------------------------------------------
# Théorie musicale : gammes, accords, progressions.
# Tout est exprimé en demi-tons par rapport à une tonique choisie par l'utilisateur,
# ce qui permet de transposer l'ensemble du morceau sans dupliquer de code.
# ---------------------------------------------------------------------------

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALE_INTERVALS = {
    "Majeur":            [0, 2, 4, 5, 7, 9, 11],
    "Mineur naturel":    [0, 2, 3, 5, 7, 8, 10],
    "Dorien":            [0, 2, 3, 5, 7, 9, 10],
    "Mixolydien":        [0, 2, 4, 5, 7, 9, 10],
    "Pentatonique maj.": [0, 2, 4, 7, 9],
    "Pentatonique min.": [0, 3, 5, 7, 10],
}

CHORD_TYPES = {
    "maj":   [0, 4, 7],
    "min":   [0, 3, 7],
    "dim":   [0, 3, 6],
    "maj7":  [0, 4, 7, 11],
    "min7":  [0, 3, 7, 10],
    "dom7":  [0, 4, 7, 10],
}

# Progressions exprimées en (degré en demi-tons depuis la tonique, qualité d'accord)
PROGRESSIONS = {
    "Original (I-vi-IV-V)": [(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")],
    "Pop (I-V-vi-IV)":      [(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")],
    "Melancolique (i-VI-III-VII)": [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")],
    "Jazz (ii-V-I-vi)":     [(2, "min7"), (7, "dom7"), (0, "maj7"), (9, "min7")],
}

def build_chord(root_note, quality):
    return tuple(root_note + iv for iv in CHORD_TYPES[quality])

def nearest_scale_note(note, key_root, scale_intervals):
    """Ramène 'note' à la note de la gamme la plus proche, pour éviter les fausses notes."""
    best = note
    best_dist = 999
    for octave in (-12, 0, 12):
        for iv in scale_intervals:
            candidate = key_root + iv + octave
            # on cherche l'octave de candidate la plus proche de note
            while candidate < note - 6:
                candidate += 12
            while candidate > note + 6:
                candidate -= 12
            dist = abs(candidate - note)
            if dist < best_dist:
                best_dist = dist
                best = candidate
    return best


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
                if not kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(self.address), ctypes.byref(mbi), ctypes.sizeof(mbi)):
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
            success = kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(self.address), buffer, 1, ctypes.byref(bytes_read))
            self.address += step

            if success and bytes_read.value > 0:
                return buffer.raw[0]
            else:
                self.address = self.current_region_end

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)


class RAMOrchestrator:
    def __init__(self, root):
        self.root = root
        self.root.title("RAM Music Engine")
        self.root.geometry("620x560")

        style = ttk.Style()
        style.theme_use('clam')

        self.is_playing = False
        self.audio_thread = None
        self.bpm = 72
        self.max_processes = 10

        # --- paramètres musicaux ---
        self.key_root_base = 48          # C3
        self.key_offset = 0              # ajouté par la sélection de tonique
        self.scale_name = "Majeur"
        self.progression_name = "Original (I-vi-IV-V)"
        self.humanize = True
        self.swing = True
        self.reverb_amount = 40          # 0-127, CC91
        self.max_polyphony_per_channel = 4

        self.roles = [
            {"name": "Cello",          "channel": 0,  "instrument": 42, "dur_mult": 1.0,   "scale_role": "bass",     "vol": 0.9, "pan": 40,  "sustain": False},
            {"name": "Electric Piano", "channel": 1,  "instrument": 4,  "dur_mult": 0.5,   "scale_role": "chord",   "vol": 0.7, "pan": 90,  "sustain": True},
            {"name": "Marimba",        "channel": 2,  "instrument": 12, "dur_mult": 0.25,  "scale_role": "arpeggio","vol": 0.6, "pan": 30,  "sustain": False},
            {"name": "Alto Sax",       "channel": 3,  "instrument": 65, "dur_mult": 0.125, "scale_role": "melody",  "vol": 0.8, "pan": 100, "sustain": False},
            {"name": "Synth Pad",      "channel": 4,  "instrument": 88, "dur_mult": 2.0,   "scale_role": "chord",   "vol": 0.5, "pan": 60,  "sustain": True},
            {"name": "Clean Guitar",   "channel": 5,  "instrument": 27, "dur_mult": 0.5,   "scale_role": "arpeggio","vol": 0.6, "pan": 20,  "sustain": False},
            {"name": "Glockenspiel",   "channel": 6,  "instrument": 9,  "dur_mult": 0.25,  "scale_role": "melody",  "vol": 0.7, "pan": 110, "sustain": False},
            {"name": "Synth Bass",     "channel": 7,  "instrument": 38, "dur_mult": 1.0,   "scale_role": "bass",    "vol": 0.8, "pan": 64,  "sustain": False},
            {"name": "Clarinet",       "channel": 8,  "instrument": 71, "dur_mult": 0.125, "scale_role": "melody",  "vol": 0.7, "pan": 80,  "sustain": False},
            {"name": "Pizzicato",      "channel": 10, "instrument": 45, "dur_mult": 0.5,   "scale_role": "chord",   "vol": 0.6, "pan": 50,  "sustain": False},
        ]

        self.target_processes = []

        self.setup_ui()
        self.auto_select_processes()

    # -------------------------------------------------------------- UI ----
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="RAM Synthesis & Orchestration", font=("Segoe UI", 12, "bold")).pack(pady=5)

        self.mode_var = tk.StringVar(value="midi")
        mode_frame = ttk.Frame(main_frame)
        mode_frame.pack(pady=5)
        ttk.Radiobutton(mode_frame, text="Ambiante (synthèse continue)", variable=self.mode_var, value="pcm").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(mode_frame, text="Concerto (MIDI)", variable=self.mode_var, value="midi").pack(side=tk.LEFT, padx=10)

        # Tonique / gamme / progression
        theory_frame = ttk.LabelFrame(main_frame, text="Harmonie")
        theory_frame.pack(pady=8, fill=tk.X)

        row1 = ttk.Frame(theory_frame); row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="Tonique :", width=12).pack(side=tk.LEFT)
        self.key_var = tk.StringVar(value="C")
        key_combo = ttk.Combobox(row1, textvariable=self.key_var, values=NOTE_NAMES, width=6, state="readonly")
        key_combo.pack(side=tk.LEFT, padx=5)
        key_combo.bind("<<ComboboxSelected>>", self.on_key_change)

        ttk.Label(row1, text="Gamme :", width=10).pack(side=tk.LEFT, padx=(15, 0))
        self.scale_var = tk.StringVar(value=self.scale_name)
        scale_combo = ttk.Combobox(row1, textvariable=self.scale_var, values=list(SCALE_INTERVALS.keys()), width=16, state="readonly")
        scale_combo.pack(side=tk.LEFT, padx=5)
        scale_combo.bind("<<ComboboxSelected>>", self.on_scale_change)

        row2 = ttk.Frame(theory_frame); row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="Progression :", width=12).pack(side=tk.LEFT)
        self.progression_var = tk.StringVar(value=self.progression_name)
        prog_combo = ttk.Combobox(row2, textvariable=self.progression_var, values=list(PROGRESSIONS.keys()), width=24, state="readonly")
        prog_combo.pack(side=tk.LEFT, padx=5)
        prog_combo.bind("<<ComboboxSelected>>", self.on_progression_change)

        # Tempo
        bpm_frame = ttk.Frame(main_frame)
        bpm_frame.pack(pady=5, fill=tk.X)
        ttk.Label(bpm_frame, text="Tempo (BPM):").pack(side=tk.LEFT)
        self.bpm_var = tk.IntVar(value=self.bpm)
        self.bpm_slider = ttk.Scale(bpm_frame, from_=20, to=200, variable=self.bpm_var, command=self.update_bpm)
        self.bpm_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.bpm_label = ttk.Label(bpm_frame, text=str(self.bpm))
        self.bpm_label.pack(side=tk.LEFT)

        # Reverb
        reverb_frame = ttk.Frame(main_frame)
        reverb_frame.pack(pady=5, fill=tk.X)
        ttk.Label(reverb_frame, text="Réverbération:").pack(side=tk.LEFT)
        self.reverb_var = tk.IntVar(value=self.reverb_amount)
        reverb_slider = ttk.Scale(reverb_frame, from_=0, to=127, variable=self.reverb_var, command=self.update_reverb)
        reverb_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        # Humanisation / swing
        opts_frame = ttk.Frame(main_frame)
        opts_frame.pack(pady=5)
        self.humanize_var = tk.BooleanVar(value=self.humanize)
        ttk.Checkbutton(opts_frame, text="Humaniser (timing/vélocité)", variable=self.humanize_var).pack(side=tk.LEFT, padx=10)
        self.swing_var = tk.BooleanVar(value=self.swing)
        ttk.Checkbutton(opts_frame, text="Swing", variable=self.swing_var).pack(side=tk.LEFT, padx=10)

        self.info_text = tk.Text(main_frame, height=8, width=68, state=tk.DISABLED, bg="#f0f0f0", font=("Consolas", 9))
        self.info_text.pack(pady=10)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Lecture", command=self.play, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Pause", command=self.stop, width=15).pack(side=tk.RIGHT, padx=10)

    def on_key_change(self, event=None):
        self.key_offset = NOTE_NAMES.index(self.key_var.get())

    def on_scale_change(self, event=None):
        self.scale_name = self.scale_var.get()

    def on_progression_change(self, event=None):
        self.progression_name = self.progression_var.get()

    def update_bpm(self, val):
        self.bpm = int(float(val))
        self.bpm_label.config(text=str(self.bpm))

    def update_reverb(self, val):
        self.reverb_amount = int(float(val))

    # ----------------------------------------------------------- setup ----
    def auto_select_processes(self):
        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                pid = proc.info['pid']
                if proc.info['memory_info'] is None:
                    continue

                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    procs.append(proc.info)
            except:
                continue

        procs.sort(key=lambda x: x['memory_info'].rss, reverse=True)
        self.target_processes = procs[:self.max_processes]

        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        for i, p in enumerate(self.target_processes):
            ram_mb = p['memory_info'].rss / (1024 * 1024)
            role_name = self.roles[i % len(self.roles)]['name']
            self.info_text.insert(tk.END, f"[{role_name}] {p['name']} ({ram_mb:.1f} MB)\n")
        self.info_text.config(state=tk.DISABLED)

    def current_progression_chords(self):
        key_root = self.key_root_base + self.key_offset
        prog = PROGRESSIONS[self.progression_name]
        return [build_chord(key_root + deg, quality) for deg, quality in prog]

    def play(self):
        if self.is_playing or not self.target_processes:
            return

        self.is_playing = True
        if self.mode_var.get() == "pcm":
            self.audio_thread = threading.Thread(target=self.ambient_audio_loop, daemon=True)
        else:
            self.audio_thread = threading.Thread(target=self.midi_audio_loop, daemon=True)
        self.audio_thread.start()

    def stop(self):
        self.is_playing = False

    # ------------------------------------------------- mode "ambiante" ----
    def ambient_audio_loop(self):
        """
        Au lieu de rejouer le flux d'octets brut (qui sonne comme du bruit statique),
        chaque processus RAM pilote un oscillateur dont la fréquence est quantifiée
        sur la gamme/l'accord courant. La phase est continue d'un bloc à l'autre
        pour éviter tout clic, et un léger filtre passe-bas + une envelope douce
        donnent un pad/drone évolutif.
        """
        readers = [ProcessReader(p['pid']) for p in self.target_processes[:6]]
        if not readers:
            self.is_playing = False
            return

        sample_rate = 44100
        block_samples = 1024

        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paFloat32, channels=1, rate=sample_rate, output=True)

        phases = [0.0 for _ in readers]
        current_freqs = [220.0 for _ in readers]
        target_freqs = [220.0 for _ in readers]
        smoothed_vals = [128.0 for _ in readers]
        lp_state = 0.0  # état du filtre passe-bas global

        tick = 0
        next_chord_time = time.perf_counter()
        chords = self.current_progression_chords()
        chord_index = 0

        while self.is_playing:
            now = time.perf_counter()
            chord_change_period = (60.0 / self.bpm) * 4  # un accord toutes les 4 temps
            if now >= next_chord_time:
                chords = self.current_progression_chords()
                chord_index = (chord_index + 1) % len(chords)
                next_chord_time = now + chord_change_period

            chord = chords[chord_index]
            key_root = self.key_root_base + self.key_offset
            scale_intervals = SCALE_INTERVALS[self.scale_name]

            mix = np.zeros(block_samples, dtype=np.float32)

            for i, reader in enumerate(readers):
                raw = reader.read_byte(step=4096)
                smoothed_vals[i] = smoothed_vals[i] * 0.9 + raw * 0.1

                # on choisit une note de l'accord courant, décalée selon la valeur RAM,
                # puis on la ramène sur la gamme pour rester consonant
                chord_tone = chord[i % len(chord)]
                octave_shift = int(smoothed_vals[i] // 64) * 12 - 24
                target_note = nearest_scale_note(chord_tone + octave_shift, key_root, scale_intervals)
                target_freqs[i] = 440.0 * (2.0 ** ((target_note - 69) / 12.0))

                # glissement doux vers la nouvelle fréquence (pas de saut brutal)
                current_freqs[i] += (target_freqs[i] - current_freqs[i]) * 0.02

                amplitude = 0.06 + 0.05 * (smoothed_vals[i] / 255.0)
                t = (np.arange(block_samples) / sample_rate)
                phase_inc = 2 * math.pi * current_freqs[i] / sample_rate
                wave = np.sin(phases[i] + np.arange(block_samples) * phase_inc)
                phases[i] = (phases[i] + block_samples * phase_inc) % (2 * math.pi)

                mix += (wave * amplitude).astype(np.float32)

            # petit filtre passe-bas one-pole pour adoucir le mélange (moins "numérique")
            filtered = np.empty_like(mix)
            alpha = 0.2
            state = lp_state
            for n in range(block_samples):
                state = state + alpha * (mix[n] - state)
                filtered[n] = state
            lp_state = state

            # évite l'écrêtage
            peak = np.max(np.abs(filtered)) or 1.0
            if peak > 0.9:
                filtered = filtered / peak * 0.9

            try:
                stream.write(filtered.tobytes())
            except IOError:
                pass

            tick += 1

        stream.stop_stream()
        stream.close()
        p.terminate()
        for r in readers:
            r.close()

    # ----------------------------------------------------- mode "midi" ----
    def midi_audio_loop(self):
        hMidiOut = ctypes.c_void_p()
        winmm.midiOutOpen(ctypes.byref(hMidiOut), 0, 0, 0, 0)

        def send(msg):
            winmm.midiOutShortMsg(hMidiOut, msg)

        # patch + réglages initiaux par rôle (panoramique, reverb, instrument, sustain off)
        for config in self.roles:
            ch = config["channel"]
            send(0xC0 | ch | (config["instrument"] << 8))
            send(0xB0 | ch | (10 << 8) | (config["pan"] << 16))     # CC10 pan
            send(0xB0 | ch | (91 << 8) | (self.reverb_amount << 16))  # CC91 reverb send
            send(0xB0 | ch | (64 << 8) | (0 << 16))                 # sustain off

        readers = [ProcessReader(p['pid']) for p in self.target_processes]

        next_tick_time = time.perf_counter()
        tick = 0
        smoothed_values = [128.0 for _ in readers]
        smoothed_values_slow = [128.0 for _ in readers]  # second étage, plus lent -> anti-nervosité

        active_notes = []          # (off_time, channel, note)
        notes_on_per_channel = {}  # channel -> set(note) pour limiter la polyphonie
        sustain_state = {}         # channel -> bool

        chords = self.current_progression_chords()
        last_progression_name = self.progression_name
        last_key_offset = self.key_offset
        last_scale_name = self.scale_name

        while self.is_playing:
            now = time.perf_counter()

            # met à jour reverb / humanize / swing en direct depuis l'UI
            reverb_now = self.reverb_var.get()
            humanize_on = self.humanize_var.get()
            swing_on = self.swing_var.get()

            if (self.progression_name != last_progression_name or
                    self.key_offset != last_key_offset or
                    self.scale_name != last_scale_name):
                chords = self.current_progression_chords()
                last_progression_name = self.progression_name
                last_key_offset = self.key_offset
                last_scale_name = self.scale_name

            base_tick_duration = (60.0 / self.bpm) / 8  # une double-croche
            if swing_on and tick % 2 == 1:
                tick_duration = base_tick_duration * 1.5
            elif swing_on:
                tick_duration = base_tick_duration * 0.5
            else:
                tick_duration = base_tick_duration

            # extinction des notes arrivées à échéance
            remaining_notes = []
            for off_time, channel, note in active_notes:
                if now >= off_time:
                    send(0x80 | channel | (note << 8))
                    notes_on_per_channel.get(channel, set()).discard(note)
                else:
                    remaining_notes.append((off_time, channel, note))
            active_notes = remaining_notes

            if now >= next_tick_time:
                key_root = self.key_root_base + self.key_offset
                scale_intervals = SCALE_INTERVALS[self.scale_name]
                chord = chords[(tick // 32) % len(chords)]

                for i, reader in enumerate(readers):
                    config = self.roles[i % len(self.roles)]
                    channel = config["channel"]
                    tick_interval = max(1, int(config["dur_mult"] / 0.125))

                    # gestion du sustain (pédale) pour les rôles "pad"
                    want_sustain = config["sustain"]
                    if sustain_state.get(channel) != want_sustain:
                        send(0xB0 | channel | (64 << 8) | ((127 if want_sustain else 0) << 16))
                        sustain_state[channel] = want_sustain

                    if reverb_now != getattr(config, "_last_reverb", None):
                        send(0xB0 | channel | (91 << 8) | (reverb_now << 16))
                        config["_last_reverb"] = reverb_now

                    if tick % tick_interval == 0:
                        val = reader.read_byte(step=2048)
                        smoothed_values[i] = smoothed_values[i] * 0.75 + val * 0.25
                        smoothed_values_slow[i] = smoothed_values_slow[i] * 0.95 + smoothed_values[i] * 0.05
                        energy = smoothed_values_slow[i]

                        # probabilité de jouer une note plutôt qu'un déclenchement binaire figé
                        play_probability = min(0.95, max(0.05, energy / 255.0))
                        if random.random() < play_probability and energy > 4:
                            notes_on_per_channel.setdefault(channel, set())
                            if len(notes_on_per_channel[channel]) >= self.max_polyphony_per_channel:
                                continue  # on évite d'empiler trop de notes sur un canal

                            vol = int(config["vol"] * (60 + energy / 3))
                            if humanize_on:
                                vol += random.randint(-8, 8)
                            vol = max(20, min(127, vol))

                            note_duration = config["dur_mult"] * (60.0 / self.bpm) * 0.9
                            if humanize_on:
                                note_duration *= random.uniform(0.9, 1.05)

                            timing_offset = random.uniform(0, 0.012) if humanize_on else 0.0

                            if config["scale_role"] == "bass":
                                raw_note = chord[0] - 12
                                item = (nearest_scale_note(raw_note, key_root, scale_intervals),)
                            elif config["scale_role"] == "chord":
                                item = tuple(nearest_scale_note(n, key_root, scale_intervals) for n in chord)
                            elif config["scale_role"] == "arpeggio":
                                extended = chord + (chord[0] + 12,)
                                raw_note = extended[tick % len(extended)]
                                item = (nearest_scale_note(raw_note, key_root, scale_intervals),)
                            else:  # melody
                                melody_degrees = [chord[0] + 24, chord[1] + 24, chord[2] + 24,
                                                   chord[1] + 36, chord[2] + 36]
                                raw_note = melody_degrees[(int(energy) // 16 + tick + i) % len(melody_degrees)]
                                item = (nearest_scale_note(raw_note, key_root, scale_intervals),)

                            for note in item:
                                note = max(0, min(127, note))
                                if note in notes_on_per_channel[channel]:
                                    continue

                                def fire(ch=channel, n=note, v=vol, dur=note_duration, delay=timing_offset):
                                    if delay > 0:
                                        time.sleep(delay)
                                    send(0x90 | ch | (n << 8) | (v << 16))

                                if timing_offset > 0:
                                    threading.Thread(target=fire, daemon=True).start()
                                else:
                                    send(0x90 | channel | (note << 8) | (vol << 16))

                                notes_on_per_channel[channel].add(note)
                                active_notes.append((now + note_duration + timing_offset, channel, note))

                tick += 1
                next_tick_time += tick_duration
            else:
                time.sleep(0.001)

        # extinction propre : notes actives + all-notes-off + sustain off par canal utilisé
        for _, channel, note in active_notes:
            send(0x80 | channel | (note << 8))
        used_channels = {config["channel"] for config in self.roles}
        for ch in used_channels:
            send(0xB0 | ch | (123 << 8))  # All Notes Off
            send(0xB0 | ch | (64 << 8))   # Sustain off

        winmm.midiOutClose(hMidiOut)
        for r in readers:
            r.close()


if __name__ == "__main__":
    root = tk.Tk()
    app = RAMOrchestrator(root)
    root.mainloop()
