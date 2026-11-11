"""RAM-driven video generator supporting instant clips and continuous live streams."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import threading
from typing import Callable, Dict, Optional, Tuple

from ram_studio.audio_engine import AudioConfig, SynthState, synthesize_pcm_block
from ram_studio.codecs import HAS_NUMPY, VideoStreamWriter, np, save_wav
from ram_studio.image_engine import (
    ImageConfig,
    ImageState,
    PALETTE_LUTS,
    generate_image_frame,
)
from ram_studio.ram_source import RAMEntropyPool

VIDEO_STYLES: Dict[str, str] = {
    "plasma_flow": "Ondes Plasma Fluides",
    "julia_morph": "Fractale Julia Évolutive",
    "voronoi_drift": "Cristaux Voronoi Mobiles",
    "cellular_life": "Automate Cellulaire Cinétique",
    "wave_field": "Champs d'Ondes RAM",
    "oscilloscope_spectrum": "Spectre & Rubans RAM",
}

VIDEO_RESOLUTIONS: Dict[str, Tuple[int, int]] = {
    "320x240": (320, 240),
    "480x360": (480, 360),
    "640x360 (HD Lite)": (640, 360),
    "800x450": (800, 450),
    "1280x720 (HD)": (1280, 720),
}

VIDEO_FORMATS = ["mp4", "gif", "avi"]


@dataclass
class VideoConfig:
    """Configuration for Video RAM generation."""

    fmt: str = "mp4"
    style: str = "plasma_flow"
    palette_name: str = "Cyberpunk"
    width: int = 480
    height: int = 360
    fps: int = 24
    duration_sec: float = 4.0
    complexity: int = 5
    symmetry: str = "none"
    include_audio: bool = True
    read_step: int = 512
    output_path: str = ""


def _render_oscilloscope_frame(
    w: int,
    h: int,
    ram_bytes: bytes,
    palette_name: str,
    frame_idx: int,
    complexity: int,
) -> bytes:
    """Render layered harmonic ribbons and RAM waveform glow."""
    lut = PALETTE_LUTS.get(palette_name, PALETTE_LUTS["Cyberpunk"])
    bg = lut[8]
    c1 = lut[120]
    c2 = lut[200]
    c3 = lut[245]
    if not ram_bytes:
        ram_bytes = b"\x80" * 128

    phase = frame_idx * 0.16
    energy = sum(ram_bytes[:64]) / max(1, min(64, len(ram_bytes))) / 255.0

    if HAS_NUMPY and np is not None:
        buf = np.empty((h, w, 3), dtype=np.uint8)
        buf[:, :] = bg
        xs = np.linspace(0.0, 1.0, w, dtype=np.float32)

        # Draw layered translucent glow bands
        n_bands = 3 + complexity // 2
        for b in range(n_bands):
            col = np.array(lut[min(255, 70 + b * (170 // max(1, n_bands)))], dtype=np.float32)
            freq = 1.5 + b * 0.65
            amp = h * (0.08 + 0.14 * energy)
            y_center = (
                h * (0.22 + 0.56 * (b / max(1, n_bands - 1)))
                + np.sin(xs * math.tau * freq + phase + b * 0.8) * amp
                + np.cos(xs * math.tau * (freq * 1.7) - phase * 0.6) * (amp * 0.35)
            )
            ys = np.arange(h, dtype=np.float32)[:, None]
            dist = np.abs(ys - y_center[None, :])
            intensity = np.exp(-dist * 0.28) * 0.65
            buf = np.clip(buf.astype(np.float32) + intensity[:, :, None] * col[None, None, :], 0, 255).astype(np.uint8)

        # Crisp live RAM waveform line across center
        sample_idx = (np.linspace(0, len(ram_bytes) - 1, w)).astype(np.int32)
        raw = np.frombuffer(ram_bytes, dtype=np.uint8)[sample_idx].astype(np.float32) / 255.0
        wy = (h * 0.5 + (raw - 0.5) * h * 0.45).astype(np.int32)
        wy = np.clip(wy, 1, h - 2)
        x_idx = np.arange(w)
        buf[wy, x_idx] = c3
        buf[wy - 1, x_idx] = c2
        buf[wy + 1, x_idx] = c1
        return buf.tobytes()

    # Pure-Python fallback
    out = bytearray([bg[0], bg[1], bg[2]] * (w * h))
    n_bands = 3 + complexity // 2
    for b in range(n_bands):
        col = lut[min(255, 70 + b * (170 // max(1, n_bands)))]
        freq = 1.5 + b * 0.65
        amp = h * (0.08 + 0.14 * energy)
        base_y = h * (0.22 + 0.56 * (b / max(1, n_bands - 1)))
        for x in range(w):
            nx = x / max(1, w - 1)
            yc = int(base_y + math.sin(nx * math.tau * freq + phase + b * 0.8) * amp)
            for dy in range(-2, 3):
                yy = yc + dy
                if 0 <= yy < h:
                    idx = (yy * w + x) * 3
                    fade = 1.0 - abs(dy) * 0.25
                    out[idx] = min(255, int(out[idx] * 0.4 + col[0] * fade))
                    out[idx + 1] = min(255, int(out[idx + 1] * 0.4 + col[1] * fade))
                    out[idx + 2] = min(255, int(out[idx + 2] * 0.4 + col[2] * fade))
    for x in range(w):
        val = ram_bytes[(x * len(ram_bytes)) // max(1, w)] / 255.0
        yy = max(1, min(h - 2, int(h * 0.5 + (val - 0.5) * h * 0.42)))
        idx = (yy * w + x) * 3
        out[idx : idx + 3] = bytes(c3)
    return bytes(out)


def render_video_frame(
    ram_bytes: bytes,
    config: VideoConfig,
    img_state: ImageState,
) -> Tuple[int, int, bytes]:
    """Render one RGB24 frame for the configured video shader style."""
    style = config.style
    if style == "oscilloscope_spectrum":
        w, h = max(64, int(config.width)), max(64, int(config.height))
        rgb = _render_oscilloscope_frame(w, h, ram_bytes, config.palette_name, img_state.frame_index, config.complexity)
        img_state.frame_index += 1
        return w, h, rgb

    style_to_alg = {
        "plasma_flow": "plasma",
        "julia_morph": "julia",
        "voronoi_drift": "voronoi",
        "cellular_life": "cellular",
        "wave_field": "reaction_wave",
    }
    alg = style_to_alg.get(style, "plasma")
    img_cfg = ImageConfig(
        algorithm=alg,
        palette_name=config.palette_name,
        width=config.width,
        height=config.height,
        complexity=config.complexity,
        symmetry=config.symmetry,
        speed=1.1,
        read_step=config.read_step,
    )
    return generate_image_frame(ram_bytes, img_cfg, state=img_state, one_shot=(img_state.frame_index == 0))


def render_video_clip(
    ram_pool: RAMEntropyPool,
    config: VideoConfig,
    progress_cb: Optional[Callable[[int, int, bytes], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """Render a finite RAM-driven video clip (MP4/GIF/AVI) and return final output path."""
    fps = max(5, min(60, int(config.fps)))
    duration = max(0.5, min(300.0, float(config.duration_sec)))
    total_frames = max(2, int(round(fps * duration)))
    w = max(64, int(config.width))
    h = max(64, int(config.height))
    fmt = config.fmt.lower().lstrip(".")

    out_path = config.output_path.strip()
    if not out_path:
        out_path = os.path.join(os.getcwd(), f"ram_video.{fmt}")

    wav_path = None
    audio_chunks = bytearray()
    audio_cfg = AudioConfig(mode="synth", volume=0.65, waveform="fm_pad", sample_rate=22050, voices=4)
    audio_state = SynthState()
    samples_per_frame = max(256, int(audio_cfg.sample_rate / fps))
    if config.include_audio and fmt == "mp4":
        wav_path = os.path.splitext(out_path)[0] + "_tmp_audio.wav"

    img_state = ImageState()
    writer = VideoStreamWriter(out_path, w, h, fps=fps, fmt=fmt, audio_wav_path=wav_path)
    try:
        for frame_idx in range(total_frames):
            if stop_event and stop_event.is_set():
                break
            ram_bytes = ram_pool.sample_bytes(512, step=config.read_step)
            _, _, rgb = render_video_frame(ram_bytes, config, img_state)
            writer.write_frame(rgb)

            if wav_path is not None:
                pcm, _ = synthesize_pcm_block(ram_bytes, audio_cfg, audio_state, block_samples=samples_per_frame)
                audio_chunks.extend(pcm)

            if progress_cb:
                progress_cb(frame_idx + 1, total_frames, rgb)

        if wav_path is not None and audio_chunks:
            save_wav(wav_path, bytes(audio_chunks), sample_rate=audio_cfg.sample_rate, channels=1)

        final_path = writer.close()
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass
    return final_path
