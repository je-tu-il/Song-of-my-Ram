"""Audio RAM synthesis & MIDI orchestration engine with live parameter modulation."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import math
import os
import random
import struct
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from ram_studio.codecs import HAS_NUMPY, PCMOutStream, np, save_wav
from ram_studio.ram_source import ProcessReader, RAMEntropyPool

IS_WINDOWS = os.name == "nt"

NOTE_NAMES: List[str] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALE_INTERVALS: Dict[str, List[int]] = {
    "Majeur": [0, 2, 4, 5, 7, 9, 11],
    "Mineur naturel": [0, 2, 3, 5, 7, 8, 10],
    "Dorien": [0, 2, 3, 5, 7, 9, 10],
    "Mixolydien": [0, 2, 4, 5, 7, 9, 10],
    "Pentatonique maj.": [0, 2, 4, 7, 9],
    "Pentatonique min.": [0, 3, 5, 7, 10],
    "Harmonique min.": [0, 2, 3, 5, 7, 8, 11],
    "Chromatique": list(range(12)),
}

CHORD_TYPES: Dict[str, List[int]] = {
    "maj": [0, 4, 7],
    "min": [0, 3, 7],
    "dim": [0, 3, 6],
    "maj7": [0, 4, 7, 11],
    "min7": [0, 3, 7, 10],
    "dom7": [0, 4, 7, 10],
    "sus2": [0, 2, 7],
}

PROGRESSIONS: Dict[str, List[Tuple[int, str]]] = {
    "Original (I-vi-IV-V)": [(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")],
    "Pop (I-V-vi-IV)": [(0, "maj"), (7, "maj"), (9, "min"), (5, "maj")],
    "Mélancolique (i-VI-III-VII)": [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")],
    "Jazz (ii-V-I-vi)": [(2, "min7"), (7, "dom7"), (0, "maj7"), (9, "min7")],
    "Ambient Drone (I-V-sus2)": [(0, "sus2"), (7, "sus2"), (5, "maj7"), (0, "sus2")],
}

WAVEFORMS: List[str] = ["sine", "triangle", "square", "sawtooth", "fm_pad"]
SAMPLE_RATES: List[int] = [22050, 44100, 48000]

ROLES: List[dict] = [
    {"name": "Cello", "channel": 0, "instrument": 42, "dur_mult": 1.0, "scale_role": "bass", "vol": 0.9, "pan": 40, "sustain": False},
    {"name": "Electric Piano", "channel": 1, "instrument": 4, "dur_mult": 0.5, "scale_role": "chord", "vol": 0.7, "pan": 90, "sustain": True},
    {"name": "Marimba", "channel": 2, "instrument": 12, "dur_mult": 0.25, "scale_role": "arpeggio", "vol": 0.6, "pan": 30, "sustain": False},
    {"name": "Alto Sax", "channel": 3, "instrument": 65, "dur_mult": 0.125, "scale_role": "melody", "vol": 0.8, "pan": 100, "sustain": False},
    {"name": "Synth Pad", "channel": 4, "instrument": 88, "dur_mult": 2.0, "scale_role": "chord", "vol": 0.5, "pan": 60, "sustain": True},
    {"name": "Clean Guitar", "channel": 5, "instrument": 27, "dur_mult": 0.5, "scale_role": "arpeggio", "vol": 0.6, "pan": 20, "sustain": False},
    {"name": "Glockenspiel", "channel": 6, "instrument": 9, "dur_mult": 0.25, "scale_role": "melody", "vol": 0.7, "pan": 110, "sustain": False},
    {"name": "Synth Bass", "channel": 7, "instrument": 38, "dur_mult": 1.0, "scale_role": "bass", "vol": 0.8, "pan": 64, "sustain": False},
    {"name": "Clarinet", "channel": 8, "instrument": 71, "dur_mult": 0.125, "scale_role": "melody", "vol": 0.7, "pan": 80, "sustain": False},
    {"name": "Pizzicato", "channel": 10, "instrument": 45, "dur_mult": 0.5, "scale_role": "chord", "vol": 0.6, "pan": 50, "sustain": False},
]


def build_chord(root_note: int, quality: str) -> Tuple[int, ...]:
    return tuple(root_note + iv for iv in CHORD_TYPES.get(quality, [0, 4, 7]))


def midi_to_freq(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69.0) / 12.0))


def nearest_scale_note(note: int, key_root: int, scale_intervals: List[int]) -> int:
    """Snap `note` to the nearest pitch in the selected scale."""
    best = note
    best_dist = 999
    for octave in (-12, 0, 12):
        for iv in scale_intervals:
            candidate = key_root + iv + octave
            while candidate < note - 6:
                candidate += 12
            while candidate > note + 6:
                candidate -= 12
            dist = abs(candidate - note)
            if dist < best_dist:
                best_dist = dist
                best = candidate
    return max(0, min(127, best))


@dataclass
class AudioConfig:
    """Configuration for Audio RAM synthesis and MIDI playback."""

    mode: str = "midi"  # "midi" or "synth"
    volume: float = 0.75
    bpm: int = 76
    waveform: str = "sine"  # sine, triangle, square, sawtooth, fm_pad
    scale_name: str = "Majeur"
    key_name: str = "C"
    progression_name: str = "Original (I-vi-IV-V)"
    quantize: bool = True
    sample_rate: int = 44100
    voices: int = 6
    reverb: int = 40  # 0..127
    humanize: bool = True
    swing: bool = False
    read_step: int = 2048
    raw_byte_mix: float = 0.08  # 0.0..1.0 subtle RAM grain texture


@dataclass
class SynthState:
    """Continuous phase and filter state between audio blocks."""

    phases: List[float] = field(default_factory=lambda: [0.0] * 10)
    mod_phases: List[float] = field(default_factory=lambda: [0.0] * 10)
    current_freqs: List[float] = field(default_factory=lambda: [220.0] * 10)
    smoothed_vals: List[float] = field(default_factory=lambda: [128.0] * 10)
    lp_state: float = 0.0
    delay_buf: List[float] = field(default_factory=lambda: [0.0] * 4096)
    delay_idx: int = 0
    chord_index: int = 0
    tick: int = 0


def _oscillator_sample_scalar(waveform: str, phase: float, mod_phase: float) -> float:
    p = phase % math.tau
    norm = p / math.tau
    if waveform == "square":
        return 1.0 if norm < 0.5 else -1.0
    if waveform == "triangle":
        return 1.0 - 4.0 * abs(norm - 0.5)
    if waveform == "sawtooth":
        return 2.0 * norm - 1.0
    if waveform == "fm_pad":
        mod = math.sin(mod_phase) * 1.4
        return 0.75 * math.sin(phase + mod) + 0.25 * math.sin(2.0 * phase)
    return math.sin(phase)


def synthesize_pcm_block(
    ram_bytes: bytes,
    config: AudioConfig,
    state: SynthState,
    block_samples: int = 1024,
) -> Tuple[bytes, List[float]]:
    """Synthesize one mono 16-bit PCM block + normalized waveform preview from RAM bytes."""
    n_voices = max(1, min(10, int(config.voices)))
    sr = max(8000, int(config.sample_rate))
    vol = max(0.0, min(1.0, float(config.volume)))
    raw_mix = max(0.0, min(1.0, float(config.raw_byte_mix)))
    reverb_gain = max(0.0, min(0.65, (config.reverb / 127.0) * 0.45))

    key_offset = NOTE_NAMES.index(config.key_name) if config.key_name in NOTE_NAMES else 0
    key_root = 48 + key_offset
    scale_intervals = SCALE_INTERVALS.get(config.scale_name, SCALE_INTERVALS["Majeur"])
    prog = PROGRESSIONS.get(config.progression_name, PROGRESSIONS["Original (I-vi-IV-V)"])

    beats_per_chord = 4
    blocks_per_chord = max(4, int((60.0 / max(20, config.bpm)) * beats_per_chord * sr / block_samples))
    if state.tick > 0 and state.tick % blocks_per_chord == 0:
        state.chord_index = (state.chord_index + 1) % len(prog)

    deg, quality = prog[state.chord_index % len(prog)]
    chord = build_chord(key_root + deg, quality)

    if not ram_bytes:
        ram_bytes = b"\x80" * max(n_voices, 32)

    # Compute target frequencies per voice from RAM bytes
    voice_freqs: List[float] = []
    voice_amps: List[float] = []
    for i in range(n_voices):
        b_val = ram_bytes[i % len(ram_bytes)]
        state.smoothed_vals[i] = state.smoothed_vals[i] * 0.85 + b_val * 0.15
        val = state.smoothed_vals[i]

        if config.quantize:
            chord_tone = chord[i % len(chord)]
            octave_shift = int(val // 64) * 12 - 24
            note = nearest_scale_note(chord_tone + octave_shift, key_root, scale_intervals)
            target_freq = midi_to_freq(note)
        else:
            # Continuous unquantized microtonal pitch mapping across 85 Hz - 880 Hz
            target_freq = 85.0 * (2.0 ** ((val / 255.0) * 3.35))

        state.current_freqs[i] += (target_freq - state.current_freqs[i]) * 0.18
        voice_freqs.append(state.current_freqs[i])
        voice_amps.append((0.35 + 0.65 * (val / 255.0)) / max(1.0, math.sqrt(n_voices)))

    if HAS_NUMPY and np is not None:
        idx = np.arange(block_samples, dtype=np.float64)
        mix = np.zeros(block_samples, dtype=np.float64)
        for i in range(n_voices):
            freq = voice_freqs[i]
            inc = math.tau * freq / sr
            ph = state.phases[i] + idx * inc
            mph = state.mod_phases[i] + idx * (inc * 0.5)
            wf = config.waveform
            if wf == "square":
                wave_arr = np.where((ph % math.tau) < math.pi, 1.0, -1.0)
            elif wf == "triangle":
                norm = (ph % math.tau) / math.tau
                wave_arr = 1.0 - 4.0 * np.abs(norm - 0.5)
            elif wf == "sawtooth":
                norm = (ph % math.tau) / math.tau
                wave_arr = 2.0 * norm - 1.0
            elif wf == "fm_pad":
                wave_arr = 0.75 * np.sin(ph + np.sin(mph) * 1.4) + 0.25 * np.sin(2.0 * ph)
            else:
                wave_arr = np.sin(ph)

            mix += wave_arr * voice_amps[i]
            state.phases[i] = float((state.phases[i] + block_samples * inc) % math.tau)
            state.mod_phases[i] = float((state.mod_phases[i] + block_samples * inc * 0.5) % math.tau)

        if raw_mix > 0.001:
            raw_arr = np.frombuffer(ram_bytes, dtype=np.uint8).astype(np.float64) / 127.5 - 1.0
            tiled = np.resize(raw_arr, block_samples)
            mix = mix * (1.0 - raw_mix * 0.6) + tiled * (raw_mix * 0.45)

        # Apply simple soft low-pass + reverb comb echo
        floats = mix.tolist()
    else:
        floats = [0.0] * block_samples
        incs = [math.tau * f / sr for f in voice_freqs]
        wf = config.waveform
        for n in range(block_samples):
            acc = 0.0
            for i in range(n_voices):
                acc += _oscillator_sample_scalar(wf, state.phases[i], state.mod_phases[i]) * voice_amps[i]
                state.phases[i] = (state.phases[i] + incs[i]) % math.tau
                state.mod_phases[i] = (state.mod_phases[i] + incs[i] * 0.5) % math.tau
            if raw_mix > 0.001:
                raw_s = (ram_bytes[n % len(ram_bytes)] / 127.5) - 1.0
                acc = acc * (1.0 - raw_mix * 0.6) + raw_s * (raw_mix * 0.45)
            floats[n] = acc

    # One-pole smoothing + feedback delay reverb + volume + int16 pack
    delay_len = len(state.delay_buf)
    d_idx = state.delay_idx
    lp = state.lp_state
    alpha = 0.35 if config.waveform in ("square", "sawtooth") else 0.55

    pcm_out = bytearray(block_samples * 2)
    preview: List[float] = []
    preview_stride = max(1, block_samples // 96)

    for n, s in enumerate(floats):
        lp = lp + alpha * (s - lp)
        if reverb_gain > 0.01:
            delayed = state.delay_buf[d_idx]
            wet = lp + delayed * reverb_gain
            state.delay_buf[d_idx] = max(-1.0, min(1.0, lp + delayed * (reverb_gain * 0.55)))
            d_idx = (d_idx + 1) % delay_len
        else:
            wet = lp

        sample_f = max(-0.98, min(0.98, math.tanh(wet * vol * 1.15)))
        if n % preview_stride == 0 and len(preview) < 96:
            preview.append(sample_f)
        struct.pack_into("<h", pcm_out, n * 2, int(sample_f * 32767))

    state.lp_state = lp
    state.delay_idx = d_idx
    state.tick += 1
    return bytes(pcm_out), preview


class AudioEngine:
    """Real-time Audio RAM playback & WAV export controller."""

    def __init__(self, ram_pool: RAMEntropyPool):
        self.ram_pool = ram_pool
        self._lock = threading.Lock()
        self.config = AudioConfig()
        self.is_playing = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.backend_status = "Prêt"
        self.preview_samples: List[float] = [0.0] * 96
        self.active_note_labels: List[str] = []
        self.current_chord_label: str = "—"
        self.peak_level: float = 0.0
        self.on_stop_callback: Optional[Callable[[], None]] = None

    def update_config(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self.config, k):
                    setattr(self.config, k, v)

    def get_config_copy(self) -> AudioConfig:
        with self._lock:
            return AudioConfig(**self.config.__dict__)

    def get_telemetry(self) -> dict:
        with self._lock:
            return {
                "is_playing": self.is_playing,
                "backend": self.backend_status,
                "preview": list(self.preview_samples),
                "active_notes": list(self.active_note_labels),
                "current_chord": self.current_chord_label,
                "peak_level": self.peak_level,
            }

    def start(self) -> None:
        if self.is_playing:
            return
        self._stop_event.clear()
        self.is_playing = True
        cfg = self.get_config_copy()
        target = self._synth_loop if cfg.mode == "synth" else self._midi_loop
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self.is_playing = False
        thread = self._thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=1.5)
        self._thread = None
        with self._lock:
            self.active_note_labels = []
            self.peak_level = 0.0

    def _midi_loop(self) -> None:
        if not IS_WINDOWS:
            # Non-Windows fallback runs live synth engine seamlessly
            self._synth_loop()
            return

        winmm = ctypes.windll.winmm
        h_midi = ctypes.c_void_p()
        res = winmm.midiOutOpen(ctypes.byref(h_midi), 0, 0, 0, 0)
        if res != 0:
            # Fall back to PCM waveform synthesis if MIDI mapper is unavailable
            self._synth_loop()
            return

        def send(msg: int) -> None:
            winmm.midiOutShortMsg(h_midi, msg)

        with self._lock:
            self.backend_status = "MIDI Concerto (WinMM)"

        for role in ROLES:
            ch = role["channel"]
            send(0xC0 | ch | (role["instrument"] << 8))
            send(0xB0 | ch | (10 << 8) | (role["pan"] << 16))
            send(0xB0 | ch | (91 << 8) | (self.config.reverb << 16))

        procs = self.ram_pool.get_active_processes()
        readers = [ProcessReader(p.pid) for p in procs[: max(1, self.config.voices)]]
        if not readers:
            readers = [ProcessReader(os.getpid())]

        smoothed = [128.0 for _ in readers]
        slow_smoothed = [128.0 for _ in readers]
        active_notes: List[Tuple[float, int, int]] = []
        notes_on: Dict[int, set] = {}
        last_reverb = -1
        tick = 0
        next_tick = time.perf_counter()

        try:
            while not self._stop_event.is_set() and self.is_playing:
                cfg = self.get_config_copy()
                # If user switched to synth mode live, transition seamlessly
                if cfg.mode == "synth":
                    break

                now = time.perf_counter()
                base_tick = (60.0 / max(20, cfg.bpm)) / 8.0
                if cfg.swing:
                    tick_dur = base_tick * (1.45 if tick % 2 == 1 else 0.55)
                else:
                    tick_dur = base_tick

                # Turn off expired notes
                remaining = []
                for off_t, ch, note in active_notes:
                    if now >= off_t:
                        send(0x80 | ch | (note << 8))
                        notes_on.get(ch, set()).discard(note)
                    else:
                        remaining.append((off_t, ch, note))
                active_notes = remaining

                if now >= next_tick:
                    key_offset = NOTE_NAMES.index(cfg.key_name) if cfg.key_name in NOTE_NAMES else 0
                    key_root = 48 + key_offset
                    scale_iv = SCALE_INTERVALS.get(cfg.scale_name, SCALE_INTERVALS["Majeur"])
                    prog = PROGRESSIONS.get(cfg.progression_name, PROGRESSIONS["Original (I-vi-IV-V)"])
                    deg, qual = prog[(tick // 32) % len(prog)]
                    chord = build_chord(key_root + deg, qual)
                    chord_lbl = f"{NOTE_NAMES[(key_offset + deg) % 12]} {qual}"

                    if cfg.reverb != last_reverb:
                        for role in ROLES:
                            send(0xB0 | role["channel"] | (91 << 8) | (max(0, min(127, cfg.reverb)) << 16))
                        last_reverb = cfg.reverb

                    active_names: List[str] = []
                    wave_preview: List[float] = [0.0] * 96
                    max_voices = max(1, min(len(readers), cfg.voices))

                    for i in range(max_voices):
                        reader = readers[i]
                        role = ROLES[i % len(ROLES)]
                        ch = role["channel"]
                        interval = max(1, int(role["dur_mult"] / 0.125))
                        if tick % interval == 0:
                            val = reader.read_byte(step=max(64, cfg.read_step))
                            smoothed[i] = smoothed[i] * 0.75 + val * 0.25
                            slow_smoothed[i] = slow_smoothed[i] * 0.92 + smoothed[i] * 0.08
                            energy = slow_smoothed[i]

                            prob = min(0.95, max(0.12, energy / 255.0))
                            if energy > 4 and random.random() < prob:
                                notes_on.setdefault(ch, set())
                                if len(notes_on[ch]) < 4:
                                    raw_vol = role["vol"] * (65 + energy / 3.0) * cfg.volume * 1.25
                                    if cfg.humanize:
                                        raw_vol += random.randint(-7, 7)
                                    midi_vol = max(1, min(127, int(raw_vol))) if cfg.volume > 0.01 else 0
                                    dur = role["dur_mult"] * (60.0 / max(20, cfg.bpm)) * 0.88
                                    if cfg.humanize:
                                        dur *= random.uniform(0.9, 1.06)

                                    if not cfg.quantize:
                                        # Unquantized chromatic mapping from raw RAM byte
                                        base_n = 36 + (val % 60)
                                        notes_tuple = (base_n,)
                                    elif role["scale_role"] == "bass":
                                        notes_tuple = (nearest_scale_note(chord[0] - 12, key_root, scale_iv),)
                                    elif role["scale_role"] == "chord":
                                        notes_tuple = tuple(nearest_scale_note(n, key_root, scale_iv) for n in chord)
                                    elif role["scale_role"] == "arpeggio":
                                        ext = chord + (chord[0] + 12,)
                                        notes_tuple = (nearest_scale_note(ext[tick % len(ext)], key_root, scale_iv),)
                                    else:
                                        mel = [chord[0] + 24, chord[1] + 24, chord[2] + 24, chord[1] + 36]
                                        n_pick = mel[(int(energy) // 16 + tick + i) % len(mel)]
                                        notes_tuple = (nearest_scale_note(n_pick, key_root, scale_iv),)

                                    for n in notes_tuple:
                                        n = max(0, min(127, n))
                                        if n not in notes_on[ch]:
                                            send(0x90 | ch | (n << 8) | (midi_vol << 16))
                                            notes_on[ch].add(n)
                                            active_notes.append((now + dur, ch, n))
                                            active_names.append(f"{NOTE_NAMES[n % 12]}{n // 12 - 1}")

                    # Synthesize synthetic preview curve matching active notes + RAM energy
                    amp = max(0.05, min(0.95, (sum(smoothed[:max_voices]) / max_voices / 255.0) * cfg.volume))
                    freq_cycles = 2.0 + (sum(smoothed[:max_voices]) % 7)
                    for p_i in range(96):
                        wave_preview[p_i] = amp * math.sin(math.tau * freq_cycles * p_i / 96.0 + tick * 0.4)

                    with self._lock:
                        self.current_chord_label = chord_lbl
                        if active_names:
                            self.active_note_labels = active_names[:8]
                        self.preview_samples = wave_preview
                        self.peak_level = amp

                    tick += 1
                    next_tick += tick_dur
                else:
                    time.sleep(0.002)
        finally:
            for _, ch, note in active_notes:
                send(0x80 | ch | (note << 8))
            for role in ROLES:
                send(0xB0 | role["channel"] | (123 << 8))
            winmm.midiOutClose(h_midi)
            for r in readers:
                r.close()

        # If stopped because user toggled mode to synth live, launch synth loop
        if not self._stop_event.is_set() and self.is_playing and self.get_config_copy().mode == "synth":
            self._synth_loop()
        else:
            self.is_playing = False
            if self.on_stop_callback:
                self.on_stop_callback()

    def _synth_loop(self) -> None:
        cfg = self.get_config_copy()
        current_sr = cfg.sample_rate
        stream = PCMOutStream(sample_rate=current_sr, channels=1)
        state = SynthState()

        with self._lock:
            self.backend_status = f"Synthèse PCM ({stream.backend} • {current_sr} Hz)"

        try:
            while not self._stop_event.is_set() and self.is_playing:
                cfg = self.get_config_copy()
                if cfg.mode == "midi" and IS_WINDOWS:
                    break
                if cfg.sample_rate != current_sr:
                    stream.close()
                    current_sr = cfg.sample_rate
                    stream = PCMOutStream(sample_rate=current_sr, channels=1)
                    with self._lock:
                        self.backend_status = f"Synthèse PCM ({stream.backend} • {current_sr} Hz)"

                block_samples = 1024
                ram_bytes = self.ram_pool.sample_bytes(max(64, block_samples // 4), step=cfg.read_step)
                pcm_bytes, preview = synthesize_pcm_block(ram_bytes, cfg, state, block_samples=block_samples)
                stream.write(pcm_bytes)

                prog = PROGRESSIONS.get(cfg.progression_name, PROGRESSIONS["Original (I-vi-IV-V)"])
                deg, qual = prog[state.chord_index % len(prog)]
                key_offset = NOTE_NAMES.index(cfg.key_name) if cfg.key_name in NOTE_NAMES else 0
                peak = max((abs(s) for s in preview), default=0.0)

                with self._lock:
                    self.preview_samples = preview
                    self.current_chord_label = f"{NOTE_NAMES[(key_offset + deg) % 12]} {qual}"
                    self.active_note_labels = [f"{int(f)} Hz" for f in state.current_freqs[: min(4, cfg.voices)]]
                    self.peak_level = peak

                if stream.backend == "null":
                    time.sleep(block_samples / current_sr)
        finally:
            stream.close()

        if not self._stop_event.is_set() and self.is_playing and self.get_config_copy().mode == "midi" and IS_WINDOWS:
            self._midi_loop()
        else:
            self.is_playing = False
            if self.on_stop_callback:
                self.on_stop_callback()

    def export_wav(self, path: str, duration_sec: float = 4.0) -> str:
        """Render a deterministic/live WAV file from current RAM entropy & audio config."""
        cfg = self.get_config_copy()
        sr = max(8000, int(cfg.sample_rate))
        total_samples = max(sr, int(duration_sec * sr))
        block_samples = 1024
        state = SynthState()
        chunks = bytearray()
        written = 0
        while written < total_samples:
            n = min(block_samples, total_samples - written)
            ram_bytes = self.ram_pool.sample_bytes(max(64, n // 4), step=cfg.read_step)
            pcm_bytes, _ = synthesize_pcm_block(ram_bytes, cfg, state, block_samples=n)
            chunks.extend(pcm_bytes)
            written += n
        return save_wav(path, bytes(chunks), sample_rate=sr, channels=1)
