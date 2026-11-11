"""Zero-dependency media codecs and optional accelerated backend adapters."""

from __future__ import annotations

import ctypes
import os
import shutil
import struct
import subprocess
import time
import wave
import zlib
from typing import Dict, List, Optional

IS_WINDOWS = os.name == "nt"

try:
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    from PIL import Image  # type: ignore

    HAS_PIL = True
except ImportError:
    Image = None
    HAS_PIL = False

try:
    import cv2  # type: ignore

    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

try:
    import imageio.v2 as imageio  # type: ignore

    HAS_IMAGEIO = True
except ImportError:
    try:
        import imageio  # type: ignore

        HAS_IMAGEIO = True
    except ImportError:
        imageio = None
        HAS_IMAGEIO = False

try:
    import pyaudio  # type: ignore

    HAS_PYAUDIO = True
except ImportError:
    pyaudio = None
    HAS_PYAUDIO = False


def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg executable if installed on PATH."""
    return shutil.which("ffmpeg")


def available_video_backends() -> Dict[str, bool]:
    """Report available video/image/audio acceleration backends."""
    return {
        "numpy": HAS_NUMPY,
        "pil": HAS_PIL,
        "cv2": HAS_CV2,
        "imageio": HAS_IMAGEIO,
        "pyaudio": HAS_PYAUDIO,
        "ffmpeg": find_ffmpeg() is not None,
    }


def rgb_bytes_to_ppm(width: int, height: int, rgb_bytes: bytes) -> bytes:
    """Convert raw RGB24 bytes into PPM (P6) bytes for zero-dep Tk PhotoImage display."""
    header = f"P6\n{width} {height}\n255\n".encode("ascii")
    expected = width * height * 3
    if len(rgb_bytes) != expected:
        if len(rgb_bytes) < expected:
            rgb_bytes = rgb_bytes + b"\x00" * (expected - len(rgb_bytes))
        else:
            rgb_bytes = rgb_bytes[:expected]
    return header + rgb_bytes


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    chunk = tag + data
    return struct.pack("!I", len(data)) + chunk + struct.pack("!I", zlib.crc32(chunk) & 0xFFFFFFFF)


def encode_png(width: int, height: int, rgb_bytes: bytes) -> bytes:
    """Encode raw RGB24 bytes into a valid PNG byte stream using pure Python stdlib."""
    expected = width * height * 3
    if len(rgb_bytes) < expected:
        rgb_bytes = rgb_bytes + b"\x00" * (expected - len(rgb_bytes))
    elif len(rgb_bytes) > expected:
        rgb_bytes = rgb_bytes[:expected]

    stride = width * 3
    raw_scanlines = bytearray((stride + 1) * height)
    for y in range(height):
        src_off = y * stride
        dst_off = y * (stride + 1)
        raw_scanlines[dst_off] = 0  # Filter type 0 (None)
        raw_scanlines[dst_off + 1 : dst_off + 1 + stride] = rgb_bytes[src_off : src_off + stride]

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw_scanlines), level=6)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def save_png(path: str, width: int, height: int, rgb_bytes: bytes) -> str:
    """Save RGB24 bytes as a PNG file (uses PIL if available, pure-Python PNG otherwise)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if HAS_PIL and Image is not None:
        img = Image.frombytes("RGB", (width, height), rgb_bytes)
        img.save(path, format="PNG")
    else:
        with open(path, "wb") as f:
            f.write(encode_png(width, height, rgb_bytes))
    return path


def save_wav(path: str, pcm_int16_bytes: bytes, sample_rate: int = 44100, channels: int = 1) -> str:
    """Write 16-bit signed PCM audio to a standard WAV file."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm_int16_bytes)
    return path


# ---------------------------------------------------------------------------
# Pure-Python Animated GIF89a Writer (zero external dependencies)
# ---------------------------------------------------------------------------

def _build_6x6x6_palette() -> bytes:
    """216-color RGB cube + 40 grayscale levels = 256-entry GIF color table."""
    table = bytearray(256 * 3)
    idx = 0
    levels = (0, 51, 102, 153, 204, 255)
    for r in levels:
        for g in levels:
            for b in levels:
                table[idx * 3 : idx * 3 + 3] = bytes((r, g, b))
                idx += 1
    for i in range(40):
        v = int(i * 255 / 39)
        table[idx * 3 : idx * 3 + 3] = bytes((v, v, v))
        idx += 1
    return bytes(table)


_GIF_PALETTE = _build_6x6x6_palette()


def _rgb_to_palette_indices(rgb_bytes: bytes) -> bytes:
    if HAS_NUMPY and np is not None:
        arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(-1, 3)
        r = ((arr[:, 0].astype(np.uint16) * 5 + 127) // 255)
        g = ((arr[:, 1].astype(np.uint16) * 5 + 127) // 255)
        b = ((arr[:, 2].astype(np.uint16) * 5 + 127) // 255)
        return (r * 36 + g * 6 + b).astype(np.uint8).tobytes()

    out = bytearray(len(rgb_bytes) // 3)
    for i in range(len(out)):
        off = i * 3
        r = (rgb_bytes[off] * 5 + 127) // 255
        g = (rgb_bytes[off + 1] * 5 + 127) // 255
        b = (rgb_bytes[off + 2] * 5 + 127) // 255
        out[i] = r * 36 + g * 6 + b
    return bytes(out)


def _encode_gif_lzw_9bit(indices: bytes) -> bytes:
    """Encode palette indices using constant 9-bit clear-code-bounded GIF LZW."""
    bit_buf = 0
    bit_count = 0
    out = bytearray()

    def write_code(code: int) -> None:
        nonlocal bit_buf, bit_count
        bit_buf |= code << bit_count
        bit_count += 9
        while bit_count >= 8:
            out.append(bit_buf & 0xFF)
            bit_buf >>= 8
            bit_count -= 8

    write_code(256)  # Clear code
    since_clear = 0
    for val in indices:
        write_code(val)
        since_clear += 1
        if since_clear >= 248:
            write_code(256)
            since_clear = 0
    write_code(257)  # End of information
    if bit_count > 0:
        out.append(bit_buf & 0xFF)

    # Split into <=255 byte sub-blocks
    blocks = bytearray()
    for pos in range(0, len(out), 255):
        chunk = out[pos : pos + 255]
        blocks.append(len(chunk))
        blocks.extend(chunk)
    blocks.append(0)
    return bytes(blocks)


class PureGIFWriter:
    """Pure-Python GIF89a animated writer (no Pillow/ffmpeg required)."""

    def __init__(self, path: str, width: int, height: int, fps: int):
        self.path = path
        self.width = width
        self.height = height
        self.delay_cs = max(2, round(100 / max(1, fps)))
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._fp = open(path, "wb")
        # Header + Logical Screen Descriptor (Global Color Table, 256 colors)
        self._fp.write(b"GIF89a")
        self._fp.write(struct.pack("<HHBBB", width, height, 0xF7, 0, 0))
        self._fp.write(_GIF_PALETTE)
        # Netscape 2.0 loop extension (infinite loop)
        self._fp.write(b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00")

    def write_frame(self, rgb_bytes: bytes) -> None:
        indices = _rgb_to_palette_indices(rgb_bytes)
        # Graphic Control Extension (21 F9 04 packed delay_cs transparent 00)
        self._fp.write(struct.pack("<BBBBHBB", 0x21, 0xF9, 4, 0x04, self.delay_cs, 0, 0))
        # Image Descriptor (local color table disabled)
        self._fp.write(struct.pack("<BHHHHB", 0x2C, 0, 0, self.width, self.height, 0))
        # LZW min code size = 8 + compressed sub-blocks
        self._fp.write(b"\x08")
        self._fp.write(_encode_gif_lzw_9bit(indices))

    def close(self) -> None:
        if self._fp is not None:
            self._fp.write(b"\x3B")  # GIF Trailer
            self._fp.close()
            self._fp = None


# ---------------------------------------------------------------------------
# Pure-Python Uncompressed RIFF AVI Writer (zero external dependencies)
# ---------------------------------------------------------------------------

class PureAVIWriter:
    """Pure-Python 24-bit BGR RIFF AVI writer playable in VLC/FFmpeg/OpenCV."""

    def __init__(self, path: str, width: int, height: int, fps: int):
        self.path = path
        self.width = width
        self.height = height
        self.fps = max(1, int(fps))
        self.row_stride = (width * 3 + 3) & ~3
        self.frame_size = self.row_stride * height
        self.frame_count = 0
        self._offsets: List[int] = []
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._fp = open(path, "wb")
        # Write placeholder header (fixed size: 224 bytes up to movi data start)
        self._write_header(0)
        self._movi_list_start = self._fp.tell() - 4  # points right at 'movi' tag

    def _write_header(self, frame_count: int) -> None:
        us_per_frame = int(1_000_000 / self.fps)
        max_bytes_sec = self.frame_size * self.fps
        total_movi_data = 4 + frame_count * (8 + self.frame_size)

        avih = struct.pack(
            "<14I",
            us_per_frame,
            max_bytes_sec,
            0,
            0x10,  # AVIF_HASINDEX
            frame_count,
            0,
            1,
            self.frame_size,
            self.width,
            self.height,
            0,
            0,
            0,
            0,
        )
        strh = struct.pack(
            "<4s4sIHHIIIIIIIIhhhh",
            b"vids",
            b"DIB ",
            0,
            0,
            0,
            0,
            1,
            self.fps,
            0,
            frame_count,
            self.frame_size,
            0xFFFFFFFF,
            0,
            0,
            0,
            self.width,
            self.height,
        )
        strf = struct.pack(
            "<IIIHHIIIIII",
            40,
            self.width,
            self.height,
            1,
            24,
            0,
            self.frame_size,
            0,
            0,
            0,
            0,
        )

        strl_body = b"strl" + b"strh" + struct.pack("<I", len(strh)) + strh + b"strf" + struct.pack("<I", len(strf)) + strf
        strl = b"LIST" + struct.pack("<I", len(strl_body)) + strl_body
        hdrl_body = b"hdrl" + b"avih" + struct.pack("<I", len(avih)) + avih + strl
        hdrl = b"LIST" + struct.pack("<I", len(hdrl_body)) + hdrl_body

        idx1_size = (8 + frame_count * 16) if frame_count else 0
        riff_size = 4 + len(hdrl) + 8 + total_movi_data + idx1_size

        self._fp.seek(0)
        self._fp.write(b"RIFF" + struct.pack("<I", riff_size) + b"AVI ")
        self._fp.write(hdrl)
        self._fp.write(b"LIST" + struct.pack("<I", total_movi_data) + b"movi")

    def _rgb_to_dib_bgr(self, rgb_bytes: bytes) -> bytes:
        w, h = self.width, self.height
        if HAS_NUMPY and np is not None:
            arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(h, w, 3)
            bgr = arr[::-1, :, ::-1]  # bottom-up BGR
            if self.row_stride == w * 3:
                return np.ascontiguousarray(bgr).tobytes()
            padded = np.zeros((h, self.row_stride), dtype=np.uint8)
            padded[:, : w * 3] = bgr.reshape(h, w * 3)
            return padded.tobytes()

        out = bytearray(self.frame_size)
        pad = self.row_stride - w * 3
        for y in range(h):
            src_y = h - 1 - y
            src_row = src_y * w * 3
            dst_row = y * self.row_stride
            for x in range(w):
                si = src_row + x * 3
                di = dst_row + x * 3
                out[di] = rgb_bytes[si + 2]
                out[di + 1] = rgb_bytes[si + 1]
                out[di + 2] = rgb_bytes[si]
            # pad bytes remain 0
            _ = pad
        return bytes(out)

    def write_frame(self, rgb_bytes: bytes) -> None:
        dib = self._rgb_to_dib_bgr(rgb_bytes)
        rel_offset = self._fp.tell() - self._movi_list_start
        self._offsets.append(rel_offset)
        self._fp.write(b"00db" + struct.pack("<I", len(dib)) + dib)
        self.frame_count += 1

    def close(self) -> None:
        if self._fp is None:
            return
        # Write idx1 index chunk
        idx = bytearray()
        for off in self._offsets:
            idx.extend(struct.pack("<4sIII", b"00db", 0x10, off, self.frame_size))
        self._fp.write(b"idx1" + struct.pack("<I", len(idx)) + bytes(idx))
        # Patch header counts and RIFF/movi sizes
        self._write_header(self.frame_count)
        self._fp.close()
        self._fp = None


# ---------------------------------------------------------------------------
# Unified Video Stream Writer
# ---------------------------------------------------------------------------

class VideoStreamWriter:
    """Unified video writer supporting MP4, GIF, and AVI across optional/pure backends."""

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        fps: int = 24,
        fmt: str = "mp4",
        audio_wav_path: Optional[str] = None,
    ):
        self.path = path
        self.width = int(width)
        self.height = int(height)
        self.fps = max(1, int(fps))
        self.fmt = fmt.lower().lstrip(".")
        self.audio_wav_path = audio_wav_path
        self.backend_name = ""
        self._proc = None
        self._cv_writer = None
        self._imageio_writer = None
        self._pil_frames: List = []
        self._pure_writer = None
        self.actual_path = path

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._open()

    def _open(self) -> None:
        ffmpeg = find_ffmpeg()

        if self.fmt == "mp4":
            if ffmpeg:
                self.backend_name = "ffmpeg"
                self._proc = subprocess.Popen(
                    [
                        ffmpeg,
                        "-y",
                        "-f",
                        "rawvideo",
                        "-vcodec",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "-s",
                        f"{self.width}x{self.height}",
                        "-r",
                        str(self.fps),
                        "-i",
                        "-",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        self.actual_path,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                return
            if HAS_CV2 and cv2 is not None:
                self.backend_name = "opencv"
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self._cv_writer = cv2.VideoWriter(self.actual_path, fourcc, self.fps, (self.width, self.height))
                if self._cv_writer.isOpened():
                    return
                self._cv_writer.release()
                self._cv_writer = None
            if HAS_IMAGEIO and imageio is not None:
                try:
                    self.backend_name = "imageio"
                    self._imageio_writer = imageio.get_writer(self.actual_path, fps=self.fps)
                    return
                except Exception:
                    self._imageio_writer = None
            # Ultimate zero-dep fallback: switch cleanly to AVI if MP4 encoder absent
            self.actual_path = os.path.splitext(self.path)[0] + ".avi"
            self.backend_name = "pure_avi_fallback"
            self._pure_writer = PureAVIWriter(self.actual_path, self.width, self.height, self.fps)
            return

        if self.fmt == "gif":
            if HAS_PIL and Image is not None:
                self.backend_name = "pillow_gif"
                self._pil_frames = []
                return
            if ffmpeg:
                self.backend_name = "ffmpeg_gif"
                self._proc = subprocess.Popen(
                    [
                        ffmpeg,
                        "-y",
                        "-f",
                        "rawvideo",
                        "-vcodec",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "-s",
                        f"{self.width}x{self.height}",
                        "-r",
                        str(self.fps),
                        "-i",
                        "-",
                        "-vf",
                        "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                        self.actual_path,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                return
            self.backend_name = "pure_gif"
            self._pure_writer = PureGIFWriter(self.actual_path, self.width, self.height, self.fps)
            return

        # AVI
        if HAS_CV2 and cv2 is not None:
            self.backend_name = "opencv_avi"
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self._cv_writer = cv2.VideoWriter(self.actual_path, fourcc, self.fps, (self.width, self.height))
            if self._cv_writer.isOpened():
                return
            self._cv_writer.release()
            self._cv_writer = None
        if ffmpeg:
            self.backend_name = "ffmpeg_avi"
            self._proc = subprocess.Popen(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "rawvideo",
                    "-vcodec",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-s",
                    f"{self.width}x{self.height}",
                    "-r",
                    str(self.fps),
                    "-i",
                    "-",
                    "-c:v",
                    "mpeg4",
                    "-q:v",
                    "5",
                    self.actual_path,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            return

        self.backend_name = "pure_avi"
        self._pure_writer = PureAVIWriter(self.actual_path, self.width, self.height, self.fps)

    def write_frame(self, rgb_bytes: bytes) -> None:
        if self._proc is not None and self._proc.stdin is not None:
            self._proc.stdin.write(rgb_bytes)
        elif self._cv_writer is not None and HAS_NUMPY and np is not None:
            arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(self.height, self.width, 3)
            self._cv_writer.write(arr[:, :, ::-1])
        elif self._imageio_writer is not None and HAS_NUMPY and np is not None:
            arr = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape(self.height, self.width, 3)
            self._imageio_writer.append_data(arr)
        elif self.backend_name == "pillow_gif" and HAS_PIL and Image is not None:
            img = Image.frombytes("RGB", (self.width, self.height), rgb_bytes)
            self._pil_frames.append(img.quantize(colors=128))
        elif self._pure_writer is not None:
            self._pure_writer.write_frame(rgb_bytes)

    def close(self) -> str:
        if self._proc is not None:
            proc = self._proc
            self._proc = None
            try:
                if proc.stdin:
                    proc.stdin.close()
                    proc.stdin = None
                _, err = proc.communicate(timeout=45)
            except Exception as exc:
                proc.kill()
                raise RuntimeError(f"FFmpeg encodage interrompu: {exc}") from exc
            if proc.returncode:
                raise RuntimeError(f"Erreur FFmpeg: {err.decode(errors='replace')[-280:]}")
            if self.audio_wav_path and os.path.exists(self.audio_wav_path) and self.actual_path.lower().endswith(".mp4"):
                self._mux_audio_ffmpeg()
        elif self._cv_writer is not None:
            self._cv_writer.release()
            self._cv_writer = None
        elif self._imageio_writer is not None:
            self._imageio_writer.close()
            self._imageio_writer = None
        elif self.backend_name == "pillow_gif":
            if self._pil_frames:
                duration_ms = max(20, int(1000 / self.fps))
                self._pil_frames[0].save(
                    self.actual_path,
                    save_all=True,
                    append_images=self._pil_frames[1:],
                    duration=duration_ms,
                    loop=0,
                    optimize=False,
                )
            self._pil_frames.clear()
        elif self._pure_writer is not None:
            self._pure_writer.close()
            self._pure_writer = None
        return self.actual_path

    def _mux_audio_ffmpeg(self) -> None:
        ffmpeg = find_ffmpeg()
        if not ffmpeg or not self.audio_wav_path:
            return
        muxed = os.path.splitext(self.actual_path)[0] + "_mux.mp4"
        res = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                self.actual_path,
                "-i",
                self.audio_wav_path,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                muxed,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if res.returncode == 0 and os.path.exists(muxed):
            os.replace(muxed, self.actual_path)


# ---------------------------------------------------------------------------
# Zero-Dependency Windows WinMM WaveOut PCM Streamer (+ PyAudio fallback)
# ---------------------------------------------------------------------------

if IS_WINDOWS:
    from ctypes import wintypes

    class _WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", wintypes.WORD),
            ("nChannels", wintypes.WORD),
            ("nSamplesPerSec", wintypes.DWORD),
            ("nAvgBytesPerSec", wintypes.DWORD),
            ("nBlockAlign", wintypes.WORD),
            ("wBitsPerSample", wintypes.WORD),
            ("cbSize", wintypes.WORD),
        ]

    class _WAVEHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.c_void_p),
            ("dwBufferLength", wintypes.DWORD),
            ("dwBytesRecorded", wintypes.DWORD),
            ("dwUser", ctypes.c_size_t),
            ("dwFlags", wintypes.DWORD),
            ("dwLoops", wintypes.DWORD),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.c_size_t),
        ]

    _winmm = ctypes.windll.winmm
    _winmm.waveOutOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.UINT,
        ctypes.POINTER(_WAVEFORMATEX),
        ctypes.c_size_t,
        ctypes.c_size_t,
        wintypes.DWORD,
    ]
    _winmm.waveOutOpen.restype = wintypes.UINT
    _winmm.waveOutPrepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), wintypes.UINT]
    _winmm.waveOutPrepareHeader.restype = wintypes.UINT
    _winmm.waveOutWrite.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), wintypes.UINT]
    _winmm.waveOutWrite.restype = wintypes.UINT
    _winmm.waveOutUnprepareHeader.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WAVEHDR), wintypes.UINT]
    _winmm.waveOutUnprepareHeader.restype = wintypes.UINT
    _winmm.waveOutReset.argtypes = [ctypes.c_void_p]
    _winmm.waveOutReset.restype = wintypes.UINT
    _winmm.waveOutClose.argtypes = [ctypes.c_void_p]
    _winmm.waveOutClose.restype = wintypes.UINT


class PCMOutStream:
    """Real-time 16-bit mono PCM audio stream using WinMM waveOut (zero deps) or PyAudio."""

    def __init__(self, sample_rate: int = 44100, channels: int = 1, buffer_count: int = 4):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.buffer_count = buffer_count
        self._h_out = None
        self._slots: List[tuple] = []
        self._pa = None
        self._pa_stream = None
        self._closed = False
        self.backend = "null"

        if IS_WINDOWS:
            try:
                fmt = _WAVEFORMATEX(
                    1,  # WAVE_FORMAT_PCM
                    self.channels,
                    self.sample_rate,
                    self.sample_rate * self.channels * 2,
                    self.channels * 2,
                    16,
                    0,
                )
                h_out = ctypes.c_void_p()
                if _winmm.waveOutOpen(ctypes.byref(h_out), 0xFFFFFFFF, ctypes.byref(fmt), 0, 0, 0) == 0:
                    self._h_out = h_out
                    self.backend = "winmm_waveout"
                    return
            except Exception:
                self._h_out = None

        if HAS_PYAUDIO and pyaudio is not None:
            try:
                self._pa = pyaudio.PyAudio()
                self._pa_stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=self.sample_rate,
                    output=True,
                )
                self.backend = "pyaudio"
            except Exception:
                self.close()

    def write(self, pcm_int16_bytes: bytes) -> None:
        if self._closed or not pcm_int16_bytes:
            return
        if self.backend == "winmm_waveout" and self._h_out is not None:
            # Reclaim completed buffers
            while len(self._slots) >= self.buffer_count:
                reclaimed = False
                for idx, (hdr, buf) in enumerate(self._slots):
                    if hdr.dwFlags & 0x00000001:  # WHDR_DONE
                        _winmm.waveOutUnprepareHeader(self._h_out, ctypes.byref(hdr), ctypes.sizeof(_WAVEHDR))
                        self._slots.pop(idx)
                        reclaimed = True
                        break
                if not reclaimed:
                    time.sleep(0.004)
                    if self._closed:
                        return

            buf = ctypes.create_string_buffer(pcm_int16_bytes, len(pcm_int16_bytes))
            hdr = _WAVEHDR(ctypes.cast(buf, ctypes.c_void_p), len(pcm_int16_bytes), 0, 0, 0, 0, None, 0)
            if _winmm.waveOutPrepareHeader(self._h_out, ctypes.byref(hdr), ctypes.sizeof(_WAVEHDR)) == 0:
                if _winmm.waveOutWrite(self._h_out, ctypes.byref(hdr), ctypes.sizeof(_WAVEHDR)) == 0:
                    self._slots.append((hdr, buf))
                else:
                    _winmm.waveOutUnprepareHeader(self._h_out, ctypes.byref(hdr), ctypes.sizeof(_WAVEHDR))
        elif self.backend == "pyaudio" and self._pa_stream is not None:
            self._pa_stream.write(pcm_int16_bytes)

    def close(self) -> None:
        self._closed = True
        if self._h_out is not None:
            try:
                _winmm.waveOutReset(self._h_out)
                for hdr, _ in self._slots:
                    _winmm.waveOutUnprepareHeader(self._h_out, ctypes.byref(hdr), ctypes.sizeof(_WAVEHDR))
                self._slots.clear()
                _winmm.waveOutClose(self._h_out)
            except Exception:
                pass
            self._h_out = None
        if self._pa_stream is not None:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
