import ctypes
from ctypes import wintypes
import hashlib
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, ttk
import wave

import psutil
from PIL import Image, ImageDraw, ImageFilter


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD), ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD), ("Protect", wintypes.DWORD), ("Type", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class ProcessReader:
    def __init__(self, pid):
        self.handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        self.address = 0
        self.region_end = 0

    def sample(self, step=4096):
        if not self.handle:
            return 0
        for _ in range(80):
            if self.address >= self.region_end:
                info = MEMORY_BASIC_INFORMATION()
                if not kernel32.VirtualQueryEx(self.handle, ctypes.c_void_p(self.address), ctypes.byref(info), ctypes.sizeof(info)):
                    self.address = 0
                    self.region_end = 0
                    return 0
                self.region_end = (info.BaseAddress or 0) + info.RegionSize
                if info.State != MEM_COMMIT or info.Protect & (PAGE_NOACCESS | PAGE_GUARD):
                    self.address = self.region_end
                    continue
            buffer = ctypes.create_string_buffer(1)
            read = ctypes.c_size_t(0)
            success = kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(self.address), buffer, 1, ctypes.byref(read))
            self.address += step
            if success and read.value:
                return buffer.raw[0]
            self.address = self.region_end
        return 0

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)


class RamImageStudio:
    def __init__(self, root):
        self.root = root
        self.root.title("RAM Image Studio")
        self.root.geometry("600x360")
        self.running = False
        self.output_dir = os.path.join(os.path.dirname(__file__), "ram_images")
        self.output_file = "ram_memory.mp4"
        self.processes = []
        self.readers = []
        self.values = []
        self.frame = 0
        self.video_process = None
        self.audio_file = None
        self.audio_path = None
        self.audio_enabled = tk.BooleanVar(value=True)
        self.setup_ui()
        self.refresh_processes()

    def setup_ui(self):
        panel = ttk.Frame(self.root, padding=18)
        panel.pack(fill=tk.BOTH, expand=True)
        ttk.Label(panel, text="RAM Image Studio", font=("Segoe UI", 15, "bold")).pack(pady=(0, 4))
        ttk.Label(panel, text="Une video coherente, nourrie par la memoire des processus.").pack()
        settings = ttk.Frame(panel)
        settings.pack(fill=tk.X, pady=18)
        ttk.Label(settings, text="FPS").grid(row=0, column=0, sticky="w")
        self.fps = tk.IntVar(value=24)
        ttk.Spinbox(settings, from_=12, to=60, textvariable=self.fps, width=7).grid(row=0, column=1, padx=8)
        ttk.Label(settings, text="Duree (s)").grid(row=0, column=2, sticky="w", padx=(18, 0))
        self.duration = tk.DoubleVar(value=12)
        ttk.Spinbox(settings, from_=1, to=600, increment=1, textvariable=self.duration, width=7).grid(row=0, column=3, padx=8)
        ttk.Label(settings, text="Nom du fichier").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.filename = tk.StringVar(value=self.output_file)
        ttk.Entry(settings, textvariable=self.filename, width=30).grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=(12, 0))
        settings.columnconfigure(3, weight=1)
        ttk.Checkbutton(panel, text="Ajouter une bande-son RAM", variable=self.audio_enabled).pack()
        self.status = tk.StringVar(value="Pret")
        ttk.Label(panel, textvariable=self.status).pack(pady=8)
        buttons = ttk.Frame(panel)
        buttons.pack(pady=12)
        ttk.Button(buttons, text="Dossier de sortie", command=self.choose_output).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Generer la serie", command=self.start).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Arreter", command=self.stop).pack(side=tk.LEFT, padx=5)

    def refresh_processes(self):
        candidates = []
        for process in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                if process.info["memory_info"]:
                    candidates.append(process.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        self.processes = sorted(candidates, key=lambda item: item["memory_info"].rss, reverse=True)[:8]

    def choose_output(self):
        selected = filedialog.askdirectory(initialdir=self.output_dir)
        if selected:
            self.output_dir = selected

    def start(self):
        if self.running:
            return
        self.refresh_processes()
        try:
            duration = max(1, float(self.duration.get()))
            fps = max(12, int(self.fps.get()))
        except (tk.TclError, ValueError):
            self.status.set("Duree ou FPS invalide")
            return
        filename = self.filename.get().strip() or "ram_memory.mp4"
        if not filename.lower().endswith(".mp4"):
            filename += ".mp4"
        self.output_file = filename
        self.running = True
        self.frame = 0
        self.total_frames = int(duration * fps)
        self.frame_rate = fps
        self.video_path = os.path.join(self.output_dir, self.output_file)
        self.audio_path = os.path.splitext(self.video_path)[0] + ".wav"
        self.status.set("Generation en cours...")
        self.root.after(20, self.generate_series)

    def stop(self):
        self.running = False
        self.close_readers()
        error_message = None
        try:
            self.close_writer()
        except RuntimeError as error:
            error_message = str(error)
        self.close_audio()
        self.status.set(error_message or "Arretee")

    def close_writer(self):
        if self.video_process is not None:
            process = self.video_process
            self.video_process = None
            try:
                process.stdin.close()
                process.stdin = None
                _, error_output = process.communicate(timeout=30)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                process.kill()
                raise RuntimeError("FFmpeg a interrompu l'encodage video")
            if process.returncode:
                error = error_output.decode(errors="replace").strip()
                raise RuntimeError(f"Erreur FFmpeg : {error[-300:]}")

    def open_audio(self):
        if not self.audio_enabled.get():
            return
        self.audio_file = wave.open(self.audio_path, "wb")
        self.audio_file.setnchannels(1)
        self.audio_file.setsampwidth(2)
        self.audio_file.setframerate(44100)
        self.audio_phase = 0.0

    def close_audio(self):
        if self.audio_file is not None:
            self.audio_file.close()
            self.audio_file = None

    def write_audio_frame(self):
        if self.audio_file is None:
            return
        start = round(self.frame * 44100 / self.frame_rate)
        end = round((self.frame + 1) * 44100 / self.frame_rate)
        samples = bytearray()
        values = self.values or [128]
        for _ in range(end - start):
            mixed = 0.0
            for index, value in enumerate(values[:4]):
                frequency = 110.0 + value * 1.25 + index * 37.0
                mixed += math.sin(self.audio_phase * frequency * math.tau)
            mixed /= max(1, min(4, len(values)))
            samples.extend(struct.pack("<h", int(max(-1, min(1, mixed * 0.22)) * 32767)))
            self.audio_phase += 1 / 44100
        self.audio_file.writeframes(bytes(samples))

    def mux_audio(self):
        if not self.audio_enabled.get():
            return
        ffmpeg = shutil.which("ffmpeg")
        muxed_path = os.path.splitext(self.video_path)[0] + "_audio.mp4"
        result = subprocess.run(
            [ffmpeg, "-y", "-i", self.video_path, "-i", self.audio_path,
             "-c:v", "copy", "-c:a", "aac", "-shortest", muxed_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False,
        )
        if result.returncode:
            error = result.stderr.decode(errors="replace").strip()
            raise RuntimeError(f"Mixage audio impossible : {error[-300:]}")
        os.replace(muxed_path, self.video_path)
        os.remove(self.audio_path)

    def open_writer(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg est introuvable dans le PATH")
        return subprocess.Popen(
            [
                ffmpeg, "-y", "-f", "rawvideo", "-vcodec", "rawvideo",
                "-pix_fmt", "rgb24", "-s", "1280x720", "-r", str(self.frame_rate),
                "-i", "-", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                self.video_path,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def close_readers(self):
        for reader in self.readers:
            reader.close()
        self.readers = []

    def generate_series(self):
        if not self.running:
            return
        os.makedirs(self.output_dir, exist_ok=True)
        if not self.readers:
            self.readers = [ProcessReader(item["pid"]) for item in self.processes]
            self.values = [128] * len(self.readers)
            self.video_path = os.path.join(self.output_dir, self.output_file)
            try:
                self.video_process = self.open_writer()
                self.open_audio()
            except Exception as error:
                self.stop()
                self.status.set(f"Encodeur video indisponible: {error}")
                return
        if self.frame >= self.total_frames:
            self.running = False
            self.close_readers()
            try:
                self.close_writer()
                self.close_audio()
                self.mux_audio()
                self.status.set(f"Terminee : {self.video_path}")
            except RuntimeError as error:
                self.close_audio()
                self.status.set(str(error))
            return
        samples = [reader.sample() for reader in self.readers]
        for index, value in enumerate(samples):
            self.values[index] = int(self.values[index] * 0.9 + value * 0.1)
        try:
            self.video_process.stdin.write(self.render(self.frame).tobytes())
            self.write_audio_frame()
        except (BrokenPipeError, OSError) as error:
            self.stop()
            self.status.set(f"Erreur d'encodage video: {error}")
            return
        self.frame += 1
        self.status.set(f"Image {self.frame}/{self.total_frames} : {self.video_path}")
        self.root.after(max(1, int(1000 / self.frame_rate)), self.generate_series)

    def render(self, frame):
        width, height = 1280, 720
        seed_text = "|".join(str(item["pid"]) + item["name"] for item in self.processes)
        seed = int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16)
        rng = random.Random(seed)
        palette = [(18, 29, 45), (28, 74, 82), (206, 133, 72), (225, 196, 116), (109, 155, 151)]
        image = Image.new("RGB", (width, height), palette[0])
        draw = ImageDraw.Draw(image, "RGBA")
        energy = sum(self.values) / max(1, len(self.values)) / 255
        phase = frame * 0.14 + energy * 2.2
        for band in range(15):
            points = []
            base_y = 70 + band * 67
            for x in range(-30, width + 40, 16):
                wave = math.sin(x * 0.012 + phase + band * 0.55) * (24 + energy * 42)
                wave += math.sin(x * 0.027 - phase * 0.7) * 12
                points.append((x, base_y + wave))
            color = palette[1 + (band + int(energy * 3)) % (len(palette) - 1)]
            draw.line(points, fill=color + (105,), width=18 + band % 4, joint="curve")
        for index in range(22):
            angle = rng.random() * math.tau + phase * (0.2 + index / 80)
            radius = 120 + rng.random() * 360 + energy * 100
            x = width / 2 + math.cos(angle) * radius
            y = height / 2 + math.sin(angle) * radius
            size = 16 + rng.random() * 70
            color = palette[1 + index % (len(palette) - 1)]
            draw.ellipse((x - size, y - size, x + size, y + size), fill=color + (45,))
        image = image.filter(ImageFilter.GaussianBlur(1.4))
        grain = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        grain_draw = ImageDraw.Draw(grain, "RGBA")
        for _ in range(900):
            x, y = rng.randrange(width), rng.randrange(height)
            grain_draw.point((x, y), fill=(255, 255, 255, rng.randrange(5, 25)))
        return Image.alpha_composite(image.convert("RGBA"), grain).convert("RGB")


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Ce script necessite Windows.")
    root = tk.Tk()
    app = RamImageStudio(root)
    root.mainloop()