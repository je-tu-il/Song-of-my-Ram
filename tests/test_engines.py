# -*- coding: utf-8 -*-
"""Comprehensive headless unit & UI smoke tests for Song-of-my-Ram Studio."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
import wave

import tkinter as tk

from ram_studio.audio_engine import (
    AudioConfig,
    AudioEngine,
    SynthState,
    WAVEFORMS,
    nearest_scale_note,
    synthesize_pcm_block,
)
from ram_studio.codecs import (
    HAS_NUMPY,
    PureAVIWriter,
    PureGIFWriter,
    encode_png,
    rgb_bytes_to_ppm,
    save_wav,
)
from ram_studio.image_engine import (
    ALGORITHMS,
    ImageConfig,
    ImageState,
    generate_image_frame,
    save_image_png,
)
from ram_studio.model3d_engine import (
    TOPOLOGIES,
    Model3DConfig,
    export_obj,
    export_stl,
    generate_mesh_from_bytes,
    project_mesh_for_canvas,
)
from ram_studio.password_engine import (
    AMBIGUOUS_CHARS,
    PasswordConfig,
    generate_passwords,
    generate_passwords_from_bytes,
)
from ram_studio.ram_source import (
    ProcessReader,
    RAMEntropyPool,
    list_readable_processes,
    shannon_entropy,
)
from ram_studio.text_engine import (
    TEXT_STYLES,
    TextConfig,
    generate_text,
    generate_text_from_bytes,
)
from ram_studio.video_engine import (
    VIDEO_STYLES,
    VideoConfig,
    render_video_clip,
    render_video_frame,
)


class TestRAMSource(unittest.TestCase):
    def test_list_and_sample_self(self):
        procs = list_readable_processes(limit=8)
        self.assertGreaterEqual(len(procs), 1)
        self.assertGreater(procs[0].rss_mb, 0.0)

        with ProcessReader(os.getpid()) as reader:
            data = reader.read_bytes(128, step=64)
            self.assertEqual(len(data), 128)
            single = reader.read_byte(step=64)
            self.assertTrue(0 <= single <= 255)

    def test_entropy_pool_and_shannon(self):
        self.assertEqual(shannon_entropy(b""), 0.0)
        self.assertEqual(shannon_entropy(b"\x00" * 64), 0.0)
        self.assertAlmostEqual(shannon_entropy(bytes(range(256))), 8.0, places=3)

        pool = RAMEntropyPool(max_processes=4)
        try:
            chunk = pool.sample_bytes(256, step=256)
            self.assertEqual(len(chunk), 256)
            self.assertGreaterEqual(pool.last_telemetry["shannon_entropy"], 0.0)
        finally:
            pool.close()


class TestCodecs(unittest.TestCase):
    def test_png_ppm_wav_gif_avi(self):
        w, h = 24, 16
        f1 = bytes(((x * 11 + y * 5) % 256 for y in range(h) for x in range(w) for _ in range(3)))
        f2 = bytes(((x * 7 + y * 13) % 256 for y in range(h) for x in range(w) for _ in range(3)))

        ppm = rgb_bytes_to_ppm(w, h, f1)
        self.assertTrue(ppm.startswith(b"P6\n24 16\n255\n"))
        self.assertEqual(len(ppm), len(b"P6\n24 16\n255\n") + w * h * 3)

        png = encode_png(w, h, f1)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IEND", png)

        with tempfile.TemporaryDirectory() as tmp:
            gif_path = os.path.join(tmp, "out.gif")
            g = PureGIFWriter(gif_path, w, h, fps=10)
            g.write_frame(f1)
            g.write_frame(f2)
            g.close()
            with open(gif_path, "rb") as f:
                raw_gif = f.read()
            self.assertTrue(raw_gif.startswith(b"GIF89a"))
            self.assertTrue(raw_gif.endswith(b"\x3B"))

            avi_path = os.path.join(tmp, "out.avi")
            a = PureAVIWriter(avi_path, w, h, fps=10)
            a.write_frame(f1)
            a.write_frame(f2)
            a.close()
            with open(avi_path, "rb") as f:
                raw_avi = f.read()
            self.assertTrue(raw_avi.startswith(b"RIFF"))
            self.assertEqual(raw_avi[8:12], b"AVI ")
            self.assertIn(b"idx1", raw_avi)

            wav_path = os.path.join(tmp, "out.wav")
            save_wav(wav_path, b"\x00\x01" * 512, sample_rate=22050)
            with wave.open(wav_path, "rb") as wf:
                self.assertEqual(wf.getframerate(), 22050)
                self.assertEqual(wf.getnframes(), 512)


class TestAudioEngine(unittest.TestCase):
    def test_nearest_scale_note_and_waveforms(self):
        snapped = nearest_scale_note(61, 60, [0, 2, 4, 5, 7, 9, 11])
        self.assertIn(snapped % 12, [0, 2, 4, 5, 7, 9, 11])

        ram_sample = bytes((i * 17) % 256 for i in range(128))
        outputs = {}
        for wf in WAVEFORMS:
            cfg = AudioConfig(mode="synth", waveform=wf, volume=0.8, sample_rate=22050, quantize=True)
            pcm, preview = synthesize_pcm_block(ram_sample, cfg, SynthState(), block_samples=512)
            self.assertEqual(len(pcm), 512 * 2)
            self.assertGreater(len(preview), 0)
            self.assertTrue(any(b != 0 for b in pcm))
            outputs[wf] = pcm

        self.assertNotEqual(outputs["sine"], outputs["square"])

        # Volume 0 yields silence
        silent_cfg = AudioConfig(mode="synth", volume=0.0)
        pcm_zero, _ = synthesize_pcm_block(ram_sample, silent_cfg, SynthState(), block_samples=256)
        self.assertEqual(pcm_zero, b"\x00" * 512)

    def test_export_wav_clip(self):
        pool = RAMEntropyPool(max_processes=2)
        try:
            eng = AudioEngine(pool)
            eng.update_config(sample_rate=22050, waveform="fm_pad", volume=0.7)
            with tempfile.TemporaryDirectory() as tmp:
                out = eng.export_wav(os.path.join(tmp, "clip.wav"), duration_sec=0.5)
                self.assertTrue(os.path.exists(out))
                self.assertGreater(os.path.getsize(out), 4096)
        finally:
            pool.close()


class TestImageEngine(unittest.TestCase):
    def test_all_algorithms_and_symmetry(self):
        ram_bytes = bytes((i * 29 + 7) % 256 for i in range(512))
        for alg in ALGORITHMS:
            for pure in ([True, False] if HAS_NUMPY else [True]):
                cfg = ImageConfig(algorithm=alg, width=64, height=64, complexity=4, symmetry="none")
                st = ImageState()
                w, h, rgb1 = generate_image_frame(ram_bytes, cfg, state=st, one_shot=True, force_pure_python=pure)
                self.assertEqual((w, h), (64, 64))
                self.assertEqual(len(rgb1), 64 * 64 * 3)
                # Continuous step evolves
                _, _, rgb2 = generate_image_frame(ram_bytes[::-1], cfg, state=st, one_shot=False, force_pure_python=pure)
                self.assertEqual(len(rgb2), 64 * 64 * 3)
                if alg != "memory_mosaic":
                    self.assertNotEqual(rgb1, rgb2)

        # Mirror symmetry validation
        cfg_sym = ImageConfig(algorithm="plasma", width=48, height=48, symmetry="mirror_xy")
        _, _, rgb_sym = generate_image_frame(ram_bytes, cfg_sym, state=ImageState(), one_shot=True)
        # Top-left pixel equals top-right & bottom-left pixel
        stride = 48 * 3
        self.assertEqual(rgb_sym[0:3], rgb_sym[stride - 3 : stride])
        self.assertEqual(rgb_sym[0:3], rgb_sym[(47 * stride) : (47 * stride) + 3])

        with tempfile.TemporaryDirectory() as tmp:
            p = save_image_png(os.path.join(tmp, "img.png"), 48, 48, rgb_sym)
            with open(p, "rb") as f:
                self.assertTrue(f.read(8).startswith(b"\x89PNG"))


class TestPasswordEngine(unittest.TestCase):
    def test_password_modes_and_rules(self):
        ram_bytes = bytes((i * 43 + 11) % 256 for i in range(256))

        cfg = PasswordConfig(
            mode="password",
            length=20,
            exclude_ambiguous=True,
            require_each_class=True,
            mix_os_urandom=False,
            count=3,
        )
        res1 = generate_passwords_from_bytes(ram_bytes, cfg)
        res2 = generate_passwords_from_bytes(ram_bytes, cfg)
        self.assertEqual(res1.passwords, res2.passwords)  # Pure deterministic RAM mode
        self.assertEqual(len(res1.passwords), 3)
        for pwd in res1.passwords:
            self.assertEqual(len(pwd), 20)
            self.assertFalse(any(ch in AMBIGUOUS_CHARS for ch in pwd))
            self.assertTrue(any(c.islower() for c in pwd))
            self.assertTrue(any(c.isupper() for c in pwd))
            self.assertTrue(any(c.isdigit() for c in pwd))

        # Passphrase, Hex, Base64, PIN
        pp = generate_passwords_from_bytes(ram_bytes, PasswordConfig(mode="passphrase", word_count=5, separator="-"))
        self.assertEqual(len(pp.passwords[0].split("-")), 5)

        hx = generate_passwords_from_bytes(ram_bytes, PasswordConfig(mode="hex", length=32))
        self.assertEqual(len(hx.passwords[0]), 32)
        int(hx.passwords[0], 16)

        b64 = generate_passwords_from_bytes(ram_bytes, PasswordConfig(mode="base64", length=24))
        self.assertEqual(len(b64.passwords[0]), 24)

        pin = generate_passwords_from_bytes(ram_bytes, PasswordConfig(mode="pin", length=6))
        self.assertEqual(len(pin.passwords[0]), 6)
        self.assertTrue(pin.passwords[0].isdigit())

    def test_live_pool_password(self):
        pool = RAMEntropyPool(max_processes=2)
        try:
            res = generate_passwords(pool, PasswordConfig(length=16))
            self.assertEqual(len(res.passwords[0]), 16)
            self.assertGreater(res.entropy_bits, 80)
        finally:
            pool.close()


class TestVideoEngine(unittest.TestCase):
    def test_video_styles_and_clip_export(self):
        ram_bytes = bytes((i * 31) % 256 for i in range(512))
        for style in VIDEO_STYLES:
            st = ImageState()
            cfg = VideoConfig(style=style, width=96, height=72, fps=10, duration_sec=0.5)
            w, h, rgb = render_video_frame(ram_bytes, cfg, st)
            self.assertEqual((w, h), (96, 72))
            self.assertEqual(len(rgb), 96 * 72 * 3)

        pool = RAMEntropyPool(max_processes=2)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for fmt in ("gif", "avi", "mp4"):
                    out_p = os.path.join(tmp, f"clip.{fmt}")
                    cfg = VideoConfig(
                        fmt=fmt,
                        style="oscilloscope_spectrum",
                        width=96,
                        height=72,
                        fps=10,
                        duration_sec=0.4,
                        include_audio=False,
                        output_path=out_p,
                    )
                    actual = render_video_clip(pool, cfg)
                    self.assertTrue(os.path.exists(actual))
                    self.assertGreater(os.path.getsize(actual), 500)
        finally:
            pool.close()


class TestTextEngine(unittest.TestCase):
    def test_text_styles_and_determinism(self):
        ram_bytes = bytes((i * 19 + 5) % 256 for i in range(256))
        for style in TEXT_STYLES:
            for lang in ("fr", "en"):
                cfg = TextConfig(style=style, language=lang, line_count=4, temperature=0.8)
                r1 = generate_text_from_bytes(ram_bytes, cfg)
                r2 = generate_text_from_bytes(ram_bytes, cfg)
                self.assertEqual(r1.text, r2.text)
                self.assertGreater(len(r1.text.strip()), 10)
                self.assertEqual(len(r1.seed_hex), 16)

        # Seed override reproducibility
        pool = RAMEntropyPool(max_processes=2)
        try:
            r_ov1 = generate_text(pool, TextConfig(style="markov", seed_override="Constellation42", line_count=4))
            r_ov2 = generate_text(pool, TextConfig(style="markov", seed_override="Constellation42", line_count=4))
            self.assertEqual(r_ov1.text, r_ov2.text)
        finally:
            pool.close()


class TestModel3DEngine(unittest.TestCase):
    def test_topologies_projection_and_exports(self):
        ram_bytes = bytes((i * 37 + 9) % 256 for i in range(512))
        with tempfile.TemporaryDirectory() as tmp:
            for topo in TOPOLOGIES:
                cfg = Model3DConfig(topology=topo, subdivisions=10, smoothing=1)
                mesh = generate_mesh_from_bytes(ram_bytes, cfg, phase=0.4)
                self.assertGreater(mesh.vertex_count, 10)
                self.assertGreater(mesh.triangle_count, 10)
                for face in mesh.faces:
                    for idx in face:
                        self.assertTrue(0 <= idx < mesh.vertex_count)

                for rmode in ("shaded", "hybrid", "wireframe"):
                    proj = project_mesh_for_canvas(mesh, 400, 300, render_mode=rmode)
                    if rmode == "wireframe":
                        self.assertGreater(len(proj["lines"]), 0)
                    else:
                        self.assertGreater(len(proj["polys"]), 0)

                obj_p = export_obj(mesh, os.path.join(tmp, f"{topo}.obj"))
                with open(obj_p, encoding="utf-8") as f:
                    obj_txt = f.read()
                self.assertIn("v ", obj_txt)
                self.assertIn("f ", obj_txt)

                stl_asc = export_stl(mesh, os.path.join(tmp, f"{topo}_asc.stl"), binary=False)
                with open(stl_asc, encoding="utf-8") as f:
                    asc_txt = f.read()
                self.assertIn("solid ram_", asc_txt)
                self.assertIn("endsolid ram_", asc_txt)

                stl_bin = export_stl(mesh, os.path.join(tmp, f"{topo}_bin.stl"), binary=True)
                with open(stl_bin, "rb") as f:
                    bin_raw = f.read()
                tri_count = struct.unpack("<I", bin_raw[80:84])[0]
                self.assertEqual(tri_count, mesh.triangle_count)
                self.assertEqual(len(bin_raw), 84 + 50 * tri_count)


class TestStudioUIHeadless(unittest.TestCase):
    def test_entrypoint_imports(self):
        import a
        import main
        import ram_audio

        self.assertTrue(callable(main.main))
        self.assertTrue(callable(ram_audio.main))
        self.assertTrue(callable(a.main))

    def test_app_tabs_and_simple_advanced_toggles(self):
        from ram_studio.ui.app import SongOfRamStudioApp

        root = tk.Tk()
        root.withdraw()
        app = SongOfRamStudioApp(root)
        try:
            root.update_idletasks()
            self.assertEqual(len(app.tabs), 6)
            self.assertEqual(app.notebook.index("end"), 6)

            for tab in app.tabs:
                self.assertFalse(tab.toggle.is_advanced)
                tab.toggle.set_advanced(True)
                self.assertTrue(tab.toggle.is_advanced)
                tab.toggle.set_advanced(False)
                self.assertFalse(tab.toggle.is_advanced)

            # Live Audio parameter updates
            audio_tab = app.tabs[0]
            audio_tab.waveform_var.set("fm_pad")
            audio_tab.bpm_var.set(110)
            audio_tab.quantize_var.set(False)
            audio_tab._push_config()
            cfg = audio_tab.engine.get_config_copy()
            self.assertEqual(cfg.waveform, "fm_pad")
            self.assertEqual(cfg.bpm, 110)
            self.assertFalse(cfg.quantize)

            # Trigger non-blocking one-shot generators
            app.tabs[2].generate()  # Password
            self.assertTrue(len(app.tabs[2].primary_var.get()) > 0)
            app.tabs[4].generate()  # Text
            self.assertTrue(len(app.tabs[4].output_text.get("1.0", tk.END).strip()) > 0)
            app.tabs[5].generate_one_shot()  # 3D Model
            self.assertIsNotNone(app.tabs[5].current_mesh)
        finally:
            app.shutdown()


if __name__ == "__main__":
    unittest.main()
