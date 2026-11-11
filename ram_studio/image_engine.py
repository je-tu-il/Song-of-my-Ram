"""Algorithmic RAM-seeded image generator (Plasma, Fractals, Cellular Automata, Voronoi, Waves)."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Tuple

from ram_studio.codecs import HAS_NUMPY, np, save_png

ALGORITHMS: Dict[str, str] = {
    "plasma": "Plasma Interférentiel",
    "julia": "Fractale de Julia",
    "mandelbrot": "Fractale Mandelbrot",
    "cellular": "Automate Cellulaire Cyclique",
    "voronoi": "Cristaux de Voronoi",
    "reaction_wave": "Ondes & Réaction",
    "memory_mosaic": "Mosaïque Mémoire RAM",
}

SYMMETRIES: Dict[str, str] = {
    "none": "Aucune",
    "mirror_x": "Miroir Horizontal",
    "mirror_xy": "Symétrie Quad",
    "kaleidoscope": "Kaléidoscope 8x",
}

PALETTE_STOPS: Dict[str, List[Tuple[int, int, int]]] = {
    "Cyberpunk": [(10, 12, 34), (24, 90, 157), (67, 206, 162), (189, 52, 254), (255, 224, 245)],
    "Nébuleuse": [(8, 8, 22), (61, 28, 108), (180, 48, 128), (246, 146, 86), (255, 244, 214)],
    "Océan": [(6, 20, 44), (11, 79, 108), (20, 160, 178), (118, 228, 214), (235, 252, 255)],
    "Solaire": [(18, 10, 14), (120, 22, 36), (220, 96, 30), (252, 198, 60), (255, 250, 220)],
    "Émeraude": [(8, 24, 18), (16, 84, 62), (24, 168, 114), (132, 238, 168), (236, 255, 240)],
    "Aurore": [(10, 14, 30), (16, 132, 116), (56, 189, 248), (167, 139, 250), (244, 114, 182)],
    "Monochrome": [(10, 12, 16), (52, 60, 74), (122, 134, 152), (200, 210, 222), (250, 252, 255)],
}


def _build_lut(stops: List[Tuple[int, int, int]]) -> List[Tuple[int, int, int]]:
    lut: List[Tuple[int, int, int]] = []
    segs = len(stops) - 1
    for i in range(256):
        pos = (i / 255.0) * segs
        idx = min(segs - 1, int(pos))
        frac = pos - idx
        c0 = stops[idx]
        c1 = stops[idx + 1]
        r = int(c0[0] + (c1[0] - c0[0]) * frac)
        g = int(c0[1] + (c1[1] - c0[1]) * frac)
        b = int(c0[2] + (c1[2] - c0[2]) * frac)
        lut.append((r, g, b))
    return lut


PALETTE_LUTS: Dict[str, List[Tuple[int, int, int]]] = {
    name: _build_lut(stops) for name, stops in PALETTE_STOPS.items()
}

if HAS_NUMPY and np is not None:
    PALETTE_NP_LUTS = {name: np.array(lut, dtype=np.uint8) for name, lut in PALETTE_LUTS.items()}
else:
    PALETTE_NP_LUTS = {}


@dataclass
class ImageConfig:
    """Settings for algorithmic RAM image generation."""

    algorithm: str = "plasma"
    palette_name: str = "Cyberpunk"
    width: int = 256
    height: int = 256
    complexity: int = 5  # 1..10
    symmetry: str = "none"
    speed: float = 1.0  # 0.2..3.0
    read_step: int = 256
    interval_ms: int = 75
    seed_mix: float = 0.5  # 0..1 influence of live RAM mutations vs smooth temporal motion


@dataclass
class ImageState:
    """Persistent state enabling smooth continuous cellular / wave evolution."""

    frame_index: int = 0
    cell_grid: Optional[object] = None
    cell_dims: Tuple[int, int] = (0, 0)
    wave_curr: Optional[object] = None
    wave_prev: Optional[object] = None
    wave_dims: Tuple[int, int] = (0, 0)
    voronoi_pts: Optional[List[Tuple[float, float, float, float]]] = None


def _ram_features(ram_bytes: bytes, count: int = 32) -> List[float]:
    """Extract normalized 0..1 feature scalars from arbitrary RAM byte slice."""
    if not ram_bytes:
        return [0.5] * count
    n = len(ram_bytes)
    stride = max(1, n // count)
    feats: List[float] = []
    for i in range(count):
        acc = 0
        start = (i * stride) % n
        for k in range(min(stride, 8)):
            acc += ram_bytes[(start + k) % n]
        feats.append((acc / max(1, min(stride, 8))) / 255.0)
    return feats


def _upscale_rgb(src: bytes, sw: int, sh: int, dw: int, dh: int) -> bytes:
    if sw == dw and sh == dh:
        return src
    if HAS_NUMPY and np is not None:
        arr = np.frombuffer(src, dtype=np.uint8).reshape(sh, sw, 3)
        yi = (np.arange(dh) * sh) // dh
        xi = (np.arange(dw) * sw) // dw
        return arr[yi[:, None], xi[None, :]].tobytes()

    out = bytearray(dw * dh * 3)
    x_map = [(x * sw) // dw for x in range(dw)]
    for y in range(dh):
        sy = (y * sh) // dh
        src_row = sy * sw * 3
        dst_row = y * dw * 3
        for x in range(dw):
            si = src_row + x_map[x] * 3
            di = dst_row + x * 3
            out[di] = src[si]
            out[di + 1] = src[si + 1]
            out[di + 2] = src[si + 2]
    return bytes(out)


def _apply_symmetry_rgb(rgb: bytes, w: int, h: int, symmetry: str) -> bytes:
    if symmetry == "none":
        return rgb
    if HAS_NUMPY and np is not None:
        arr = np.frombuffer(rgb, dtype=np.uint8).reshape(h, w, 3).copy()
        hw, hh = w // 2, h // 2
        if symmetry in ("mirror_x", "mirror_xy", "kaleidoscope"):
            arr[:, w - hw :] = arr[:, :hw][:, ::-1]
        if symmetry in ("mirror_xy", "kaleidoscope"):
            arr[h - hh :, :] = arr[:hh, :][::-1, :]
        if symmetry == "kaleidoscope":
            # Blend diagonal transpose in top-left quadrant then re-mirror
            s = min(hw, hh)
            if s > 1:
                quad = arr[:s, :s]
                arr[:s, :s] = ((quad.astype(np.uint16) + quad.transpose(1, 0, 2)) // 2).astype(np.uint8)
                arr[:, w - hw :] = arr[:, :hw][:, ::-1]
                arr[h - hh :, :] = arr[:hh, :][::-1, :]
        return arr.tobytes()

    arr = bytearray(rgb)
    hw, hh = w // 2, h // 2
    if symmetry in ("mirror_x", "mirror_xy", "kaleidoscope"):
        for y in range(h):
            row = y * w * 3
            for x in range(hw):
                si = row + x * 3
                di = row + (w - 1 - x) * 3
                arr[di : di + 3] = arr[si : si + 3]
    if symmetry in ("mirror_xy", "kaleidoscope"):
        for y in range(hh):
            srow = y * w * 3
            drow = (h - 1 - y) * w * 3
            arr[drow : drow + w * 3] = arr[srow : srow + w * 3]
    return bytes(arr)


def _map_scalar_field_to_rgb(field_01: List[float], w: int, h: int, lut: List[Tuple[int, int, int]]) -> bytes:
    out = bytearray(w * h * 3)
    for i, v in enumerate(field_01):
        idx = int(max(0.0, min(1.0, v)) * 255)
        r, g, b = lut[idx]
        di = i * 3
        out[di] = r
        out[di + 1] = g
        out[di + 2] = b
    return bytes(out)


def _render_plasma_np(w: int, h: int, feats: List[float], t: float, complexity: int, lut) -> bytes:
    xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    ys = np.linspace(-1.0, 1.0, h, dtype=np.float32)[:, None]
    f1 = 2.2 + feats[0] * 3.5 + complexity * 0.45
    f2 = 2.0 + feats[1] * 3.5 + complexity * 0.4
    f3 = 1.8 + feats[2] * 3.0 + complexity * 0.35
    p1 = t * 1.1 + feats[3] * math.tau
    p2 = t * 0.8 + feats[4] * math.tau
    p3 = t * 1.4 + feats[5] * math.tau

    warp = 0.28 * np.sin(ys * f2 + p2)
    v = (
        np.sin((xs + warp) * f1 + p1)
        + np.cos(ys * f2 - p2)
        + np.sin((xs + ys) * f3 + p3)
        + np.sin(np.sqrt(xs * xs + ys * ys + 0.01) * (3.5 + complexity * 0.7) - t * 1.3)
    )
    norm = np.clip((v * 0.125) + 0.5, 0.0, 1.0)
    idx = (norm * 255).astype(np.uint8)
    return lut[idx].tobytes()


def _render_fractal_np(
    w: int,
    h: int,
    feats: List[float],
    t: float,
    complexity: int,
    lut,
    mode: str,
) -> bytes:
    max_iter = 24 + complexity * 6
    if mode == "julia":
        angle = t * 0.35 + feats[0] * math.tau
        radius = 0.74 + 0.07 * math.sin(t * 0.23 + feats[1] * math.tau)
        c = complex(radius * math.cos(angle), radius * math.sin(angle))
        scale = 1.55 - 0.25 * math.sin(t * 0.15 + feats[2] * math.pi)
        x = np.linspace(-scale * (w / max(1, h)), scale * (w / max(1, h)), w, dtype=np.float64)
        y = np.linspace(-scale, scale, h, dtype=np.float64)
        Z = x[None, :] + 1j * y[:, None]
        C = np.full_like(Z, c)
    else:
        anchors = [
            (-0.743643, 0.131825),
            (-0.7453, 0.1127),
            (-0.1011, 0.9563),
            (-1.25066, 0.02012),
            (0.2817, 0.5771),
        ]
        cx, cy = anchors[int(feats[0] * 100) % len(anchors)]
        cx += (feats[1] - 0.5) * 0.012
        cy += (feats[2] - 0.5) * 0.012
        zoom = 0.04 + 0.42 * (0.5 + 0.5 * math.cos(t * 0.28))
        span_x = zoom * (w / max(1, h))
        x = np.linspace(cx - span_x, cx + span_x, w, dtype=np.float64)
        y = np.linspace(cy - zoom, cy + zoom, h, dtype=np.float64)
        C = x[None, :] + 1j * y[:, None]
        Z = np.zeros_like(C)

    smooth = np.zeros(Z.shape, dtype=np.float64)
    mask = np.ones(Z.shape, dtype=bool)
    for it in range(max_iter):
        Z[mask] = Z[mask] * Z[mask] + C[mask]
        mag2 = np.real(Z) ** 2 + np.imag(Z) ** 2
        escaped = mask & (mag2 > 16.0)
        if np.any(escaped):
            log_zn = np.log(np.maximum(mag2[escaped], 1e-9)) * 0.5
            nu = np.log(np.maximum(log_zn / math.log(2.0), 1e-9)) / math.log(2.0)
            smooth[escaped] = it + 1.0 - nu
            mask[escaped] = False
        if not np.any(mask):
            break

    # Interior coloring using final |Z| for rich texture instead of flat black
    if np.any(mask):
        interior = np.sqrt(np.real(Z[mask]) ** 2 + np.imag(Z[mask]) ** 2)
        smooth[mask] = (interior * 0.25) % 1.0 * max_iter * 0.35

    phase_shift = (t * 0.08 + feats[3] * 0.5)
    norm = np.mod(smooth / max(8.0, max_iter * 0.65) + phase_shift, 1.0)
    idx = (norm * 255).astype(np.uint8)
    return lut[idx].tobytes()


def _render_voronoi_np(w: int, h: int, feats: List[float], t: float, complexity: int, lut, state: ImageState) -> bytes:
    n_pts = 10 + complexity * 3
    if state.voronoi_pts is None or len(state.voronoi_pts) != n_pts:
        pts = []
        for i in range(n_pts):
            px = feats[i % len(feats)]
            py = feats[(i * 7 + 3) % len(feats)]
            vx = (feats[(i * 3 + 5) % len(feats)] - 0.5) * 0.025
            vy = (feats[(i * 5 + 11) % len(feats)] - 0.5) * 0.025
            pts.append([px, py, vx, vy])
        state.voronoi_pts = pts

    # Advance sites smoothly with gentle RAM nudge
    for i, pt in enumerate(state.voronoi_pts):
        nudge_x = (feats[i % len(feats)] - 0.5) * 0.004
        nudge_y = (feats[(i + 5) % len(feats)] - 0.5) * 0.004
        pt[0] = (pt[0] + pt[2] + nudge_x) % 1.0
        pt[1] = (pt[1] + pt[3] + nudge_y) % 1.0

    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :, None]
    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    px = np.array([p[0] for p in state.voronoi_pts], dtype=np.float32)[None, None, :]
    py = np.array([p[1] for p in state.voronoi_pts], dtype=np.float32)[None, None, :]

    dx = xs - px
    dy = ys - py
    dist = np.sqrt(dx * dx + dy * dy)
    part = np.partition(dist, 1, axis=2)
    d1 = part[:, :, 0]
    d2 = part[:, :, 1]
    owner = np.argmin(dist, axis=2).astype(np.float32) / n_pts

    edge = np.clip((d2 - d1) * 7.5, 0.0, 1.0)
    field = np.mod(owner * 0.55 + (1.0 - edge) * 0.45 + d1 * 1.4 + t * 0.04, 1.0)
    idx = (field * 255).astype(np.uint8)
    return lut[idx].tobytes()


def _step_cellular_np(
    w: int,
    h: int,
    ram_bytes: bytes,
    feats: List[float],
    complexity: int,
    lut,
    state: ImageState,
    one_shot: bool,
) -> bytes:
    n_states = 10
    gw = min(w, 192)
    gh = min(h, 192)
    if state.cell_grid is None or state.cell_dims != (gw, gh) or one_shot:
        raw = np.frombuffer(ram_bytes, dtype=np.uint8)
        tiled = np.resize(raw, gh * gw).reshape(gh, gw)
        grid = (tiled % n_states).astype(np.uint8)
        steps = 10 + complexity
    else:
        grid = state.cell_grid
        # Inject subtle RAM mutations proportional to complexity
        mut_count = max(8, (gw * gh) // 160)
        for i in range(mut_count):
            b1 = ram_bytes[(i * 3) % len(ram_bytes)]
            b2 = ram_bytes[(i * 5 + 1) % len(ram_bytes)]
            grid[b1 % gh, b2 % gw] = (b1 + b2) % n_states
        steps = 2

    for _ in range(steps):
        nxt = (grid + 1) % n_states
        # Count Moore neighbors in next state
        matches = np.zeros_like(grid, dtype=np.uint8)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                matches += (np.roll(np.roll(grid, dy, axis=0), dx, axis=1) == nxt)
        thresh = 2 if complexity >= 5 else 3
        grid = np.where(matches >= thresh, nxt, grid)

    state.cell_grid = grid
    state.cell_dims = (gw, gh)
    idx = ((grid.astype(np.float32) / (n_states - 1)) * 255).astype(np.uint8)
    rgb = lut[idx].tobytes()
    return _upscale_rgb(rgb, gw, gh, w, h)


def _step_wave_np(
    w: int,
    h: int,
    ram_bytes: bytes,
    feats: List[float],
    t: float,
    complexity: int,
    lut,
    state: ImageState,
    one_shot: bool,
) -> bytes:
    gw = min(w, 192)
    gh = min(h, 192)
    if state.wave_curr is None or state.wave_dims != (gw, gh) or one_shot:
        curr = np.zeros((gh, gw), dtype=np.float32)
        prev = np.zeros((gh, gw), dtype=np.float32)
        steps = 18 + complexity * 2
    else:
        curr = state.wave_curr
        prev = state.wave_prev
        steps = 3

    # Inject RAM impulses
    n_drops = 3 + complexity // 2
    for i in range(n_drops):
        bx = ram_bytes[(i * 7) % len(ram_bytes)]
        by = ram_bytes[(i * 11 + 3) % len(ram_bytes)]
        amp = (ram_bytes[(i * 13 + 5) % len(ram_bytes)] / 255.0 - 0.5) * 2.2
        px = 2 + (bx % max(1, gw - 4))
        py = 2 + (by % max(1, gh - 4))
        curr[py - 1 : py + 2, px - 1 : px + 2] += amp

    damping = 0.965
    for _ in range(steps):
        lap = (
            np.roll(curr, 1, axis=0)
            + np.roll(curr, -1, axis=0)
            + np.roll(curr, 1, axis=1)
            + np.roll(curr, -1, axis=1)
        ) * 0.5 - prev
        nxt = np.clip(lap * damping, -2.5, 2.5)
        prev, curr = curr, nxt

    state.wave_curr = curr
    state.wave_prev = prev
    state.wave_dims = (gw, gh)

    norm = np.clip(0.5 + 0.45 * np.tanh(curr * 1.4), 0.0, 1.0)
    idx = (norm * 255).astype(np.uint8)
    rgb = lut[idx].tobytes()
    return _upscale_rgb(rgb, gw, gh, w, h)


def _render_memory_mosaic(w: int, h: int, ram_bytes: bytes, lut_list: List[Tuple[int, int, int]]) -> bytes:
    """Structured block heatmap from RAM bytes (clean non-static telemetry mosaic)."""
    gw = min(w, 64)
    gh = min(h, 64)
    if not ram_bytes:
        ram_bytes = b"\x80" * 256
    n = len(ram_bytes)
    field: List[float] = []
    # Smooth adjacent bytes slightly and stretch contrast
    min_b = min(ram_bytes)
    max_b = max(ram_bytes)
    span = max(1, max_b - min_b)
    for idx in range(gw * gh):
        b0 = ram_bytes[(idx * 3) % n]
        b1 = ram_bytes[(idx * 3 + 1) % n]
        val = ((b0 * 0.7 + b1 * 0.3) - min_b) / span
        field.append(val)
    small = _map_scalar_field_to_rgb(field, gw, gh, lut_list)
    return _upscale_rgb(small, gw, gh, w, h)


def _render_pure_python(
    w: int,
    h: int,
    ram_bytes: bytes,
    feats: List[float],
    config: ImageConfig,
    state: ImageState,
    one_shot: bool,
) -> bytes:
    """Pure-Python fallback renderer using adaptive preview grid for fast zero-dep performance."""
    lut = PALETTE_LUTS.get(config.palette_name, PALETTE_LUTS["Cyberpunk"])
    alg = config.algorithm
    t = state.frame_index * 0.14 * config.speed

    if alg == "memory_mosaic":
        return _render_memory_mosaic(w, h, ram_bytes, lut)

    # Keep pure-Python compute grid compact and upscale cleanly to requested w x h
    gw = min(w, 96 if alg in ("julia", "mandelbrot") else 128)
    gh = min(h, 96 if alg in ("julia", "mandelbrot") else 128)

    if alg == "plasma":
        f1 = 2.2 + feats[0] * 3.5 + config.complexity * 0.45
        f2 = 2.0 + feats[1] * 3.5 + config.complexity * 0.4
        f3 = 1.8 + feats[2] * 3.0 + config.complexity * 0.35
        p1 = t * 1.1 + feats[3] * math.tau
        p2 = t * 0.8 + feats[4] * math.tau
        p3 = t * 1.4 + feats[5] * math.tau
        field = [0.0] * (gw * gh)
        for y in range(gh):
            ny = (y / max(1, gh - 1)) * 2.0 - 1.0
            wy = 0.28 * math.sin(ny * f2 + p2)
            cy = math.cos(ny * f2 - p2)
            row_off = y * gw
            for x in range(gw):
                nx = (x / max(1, gw - 1)) * 2.0 - 1.0
                r = math.hypot(nx, ny)
                v = (
                    math.sin((nx + wy) * f1 + p1)
                    + cy
                    + math.sin((nx + ny) * f3 + p3)
                    + math.sin(r * (3.5 + config.complexity * 0.6) - t * 1.3)
                )
                field[row_off + x] = max(0.0, min(1.0, v * 0.125 + 0.5))
        small = _map_scalar_field_to_rgb(field, gw, gh, lut)
        return _upscale_rgb(small, gw, gh, w, h)

    if alg in ("julia", "mandelbrot"):
        max_iter = 18 + config.complexity * 3
        field = [0.0] * (gw * gh)
        if alg == "julia":
            angle = t * 0.35 + feats[0] * math.tau
            rad = 0.74 + 0.07 * math.sin(t * 0.23 + feats[1] * math.tau)
            cr, ci = rad * math.cos(angle), rad * math.sin(angle)
            scale = 1.5
            for y in range(gh):
                zy0 = -scale + (2.0 * scale * y) / max(1, gh - 1)
                row_off = y * gw
                for x in range(gw):
                    zx = -scale + (2.0 * scale * x) / max(1, gw - 1)
                    zy = zy0
                    it = 0
                    while it < max_iter and zx * zx + zy * zy <= 16.0:
                        zx, zy = zx * zx - zy * zy + cr, 2.0 * zx * zy + ci
                        it += 1
                    val = it / max_iter
                    field[row_off + x] = (val + t * 0.08) % 1.0
        else:
            cx = -0.7436 + (feats[1] - 0.5) * 0.02
            cy = 0.1318 + (feats[2] - 0.5) * 0.02
            zoom = 0.08 + 0.4 * (0.5 + 0.5 * math.cos(t * 0.28))
            for y in range(gh):
                ci = cy - zoom + (2.0 * zoom * y) / max(1, gh - 1)
                row_off = y * gw
                for x in range(gw):
                    cr = cx - zoom + (2.0 * zoom * x) / max(1, gw - 1)
                    zx, zy = 0.0, 0.0
                    it = 0
                    while it < max_iter and zx * zx + zy * zy <= 16.0:
                        zx, zy = zx * zx - zy * zy + cr, 2.0 * zx * zy + ci
                        it += 1
                    field[row_off + x] = ((it / max_iter) + t * 0.08) % 1.0
        small = _map_scalar_field_to_rgb(field, gw, gh, lut)
        return _upscale_rgb(small, gw, gh, w, h)

    if alg == "voronoi":
        n_pts = 8 + config.complexity * 2
        if state.voronoi_pts is None or len(state.voronoi_pts) != n_pts:
            state.voronoi_pts = [
                [
                    feats[i % len(feats)],
                    feats[(i * 7 + 3) % len(feats)],
                    (feats[(i * 3 + 5) % len(feats)] - 0.5) * 0.03,
                    (feats[(i * 5 + 11) % len(feats)] - 0.5) * 0.03,
                ]
                for i in range(n_pts)
            ]
        for pt in state.voronoi_pts:
            pt[0] = (pt[0] + pt[2]) % 1.0
            pt[1] = (pt[1] + pt[3]) % 1.0
        pts = [(p[0], p[1]) for p in state.voronoi_pts]
        field = [0.0] * (gw * gh)
        for y in range(gh):
            ny = y / max(1, gh - 1)
            row_off = y * gw
            for x in range(gw):
                nx = x / max(1, gw - 1)
                d1, d2, owner = 9.0, 9.0, 0
                for idx, (px, py) in enumerate(pts):
                    d = math.hypot(nx - px, ny - py)
                    if d < d1:
                        d2, d1, owner = d1, d, idx
                    elif d < d2:
                        d2 = d
                edge = min(1.0, (d2 - d1) * 7.5)
                field[row_off + x] = ((owner / n_pts) * 0.55 + (1.0 - edge) * 0.45 + d1 * 1.2 + t * 0.04) % 1.0
        small = _map_scalar_field_to_rgb(field, gw, gh, lut)
        return _upscale_rgb(small, gw, gh, w, h)

    if alg == "cellular":
        gw = min(w, 80)
        gh = min(h, 80)
        n_states = 8
        if state.cell_grid is None or state.cell_dims != (gw, gh) or one_shot:
            grid = [ram_bytes[i % len(ram_bytes)] % n_states for i in range(gw * gh)]
            steps = 6
        else:
            grid = list(state.cell_grid)
            for i in range(max(4, (gw * gh) // 100)):
                b1 = ram_bytes[(i * 3) % len(ram_bytes)]
                b2 = ram_bytes[(i * 5 + 1) % len(ram_bytes)]
                grid[(b1 % gh) * gw + (b2 % gw)] = (b1 + b2) % n_states
            steps = 1

        for _ in range(steps):
            new_grid = list(grid)
            for y in range(gh):
                ym = ((y - 1) % gh) * gw
                yc = y * gw
                yp = ((y + 1) % gh) * gw
                for x in range(gw):
                    cur = grid[yc + x]
                    nxt = (cur + 1) % n_states
                    xm = (x - 1) % gw
                    xp = (x + 1) % gw
                    cnt = (
                        (grid[ym + xm] == nxt)
                        + (grid[ym + x] == nxt)
                        + (grid[ym + xp] == nxt)
                        + (grid[yc + xm] == nxt)
                        + (grid[yc + xp] == nxt)
                        + (grid[yp + xm] == nxt)
                        + (grid[yp + x] == nxt)
                        + (grid[yp + xp] == nxt)
                    )
                    if cnt >= 2:
                        new_grid[yc + x] = nxt
            grid = new_grid
        state.cell_grid = grid
        state.cell_dims = (gw, gh)
        field = [v / (n_states - 1) for v in grid]
        small = _map_scalar_field_to_rgb(field, gw, gh, lut)
        return _upscale_rgb(small, gw, gh, w, h)

    # reaction_wave fallback in pure python
    gw, gh = min(w, 96), min(h, 96)
    field = [0.0] * (gw * gh)
    centers = [
        (feats[i * 3 % len(feats)], feats[(i * 3 + 1) % len(feats)], 4.0 + feats[(i * 3 + 2) % len(feats)] * 12.0)
        for i in range(3 + config.complexity // 2)
    ]
    for y in range(gh):
        ny = y / max(1, gh - 1)
        row_off = y * gw
        for x in range(gw):
            nx = x / max(1, gw - 1)
            acc = 0.0
            for cx, cy, freq in centers:
                acc += math.sin(math.hypot(nx - cx, ny - cy) * freq * 3.0 - t * 2.0)
            field[row_off + x] = max(0.0, min(1.0, 0.5 + 0.5 * (acc / len(centers))))
    small = _map_scalar_field_to_rgb(field, gw, gh, lut)
    return _upscale_rgb(small, gw, gh, w, h)


def generate_image_frame(
    ram_bytes: bytes,
    config: ImageConfig,
    state: Optional[ImageState] = None,
    one_shot: bool = True,
    force_pure_python: bool = False,
) -> Tuple[int, int, bytes]:
    """Generate a single RGB24 frame (`(width, height, rgb_bytes)`) seeded from live RAM bytes."""
    if state is None:
        state = ImageState()
    w = max(32, int(config.width))
    h = max(32, int(config.height))
    if not ram_bytes:
        ram_bytes = b"\x5a\xa5\x3c\xc3" * 64

    feats = _ram_features(ram_bytes, count=32)
    t = state.frame_index * 0.14 * max(0.1, config.speed)

    if HAS_NUMPY and np is not None and not force_pure_python:
        lut = PALETTE_NP_LUTS.get(config.palette_name, PALETTE_NP_LUTS["Cyberpunk"])
        alg = config.algorithm
        if alg == "plasma":
            rgb = _render_plasma_np(w, h, feats, t, config.complexity, lut)
        elif alg in ("julia", "mandelbrot"):
            rgb = _render_fractal_np(w, h, feats, t, config.complexity, lut, alg)
        elif alg == "voronoi":
            rgb = _render_voronoi_np(w, h, feats, t, config.complexity, lut, state)
        elif alg == "cellular":
            rgb = _step_cellular_np(w, h, ram_bytes, feats, config.complexity, lut, state, one_shot)
        elif alg == "reaction_wave":
            rgb = _step_wave_np(w, h, ram_bytes, feats, t, config.complexity, lut, state, one_shot)
        else:
            rgb = _render_memory_mosaic(w, h, ram_bytes, PALETTE_LUTS.get(config.palette_name, PALETTE_LUTS["Cyberpunk"]))
    else:
        rgb = _render_pure_python(w, h, ram_bytes, feats, config, state, one_shot)

    rgb = _apply_symmetry_rgb(rgb, w, h, config.symmetry)
    state.frame_index += 1
    return w, h, rgb


def save_image_png(path: str, width: int, height: int, rgb_bytes: bytes) -> str:
    """Save generated RAM image frame to PNG."""
    return save_png(path, width, height, rgb_bytes)
