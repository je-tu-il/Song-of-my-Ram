"""Procedural 3D RAM mesh generator, interactive 3D projector, and OBJ/STL exporter."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
import struct
from typing import Dict, List, Optional, Tuple

TOPOLOGIES: Dict[str, str] = {
    "supershape": "Supershape 3D (Gielis)",
    "terrain": "Terrain / Relief RAM",
    "geosphere": "Géosphère Harmonique",
    "torus_knot": "Tore Torsadé RAM",
    "crystal": "Cristal Facetté RAM",
}

COLOR_THEMES: Dict[str, Tuple[Tuple[int, int, int], Tuple[int, int, int], str]] = {
    "Cyber Cyan": ((14, 72, 118), (56, 224, 255), "#0ea5e9"),
    "Nébuleuse": ((72, 24, 112), (244, 114, 182), "#c084fc"),
    "Émeraude": ((12, 74, 52), (52, 245, 165), "#10b981"),
    "Solaire Or": ((98, 42, 14), (255, 208, 74), "#f59e0b"),
    "Titane": ((52, 62, 78), (226, 232, 240), "#94a3b8"),
}

RENDER_MODES: Dict[str, str] = {
    "hybrid": "Ombré + Arêtes",
    "shaded": "Solide Ombré",
    "wireframe": "Fil de Fer",
}


@dataclass
class Model3DConfig:
    """Configuration for procedural 3D RAM model generation."""

    topology: str = "supershape"  # supershape, terrain, geosphere, torus_knot, crystal
    color_theme: str = "Cyber Cyan"
    render_mode: str = "hybrid"  # shaded, wireframe, hybrid
    subdivisions: int = 16  # 6 .. 28
    amplitude: float = 0.75  # 0.1 .. 2.0
    frequency: float = 2.5  # 0.5 .. 6.0
    twist: float = 0.6  # 0.0 .. 3.0
    smoothing: int = 1  # 0 .. 3 Laplacian passes
    auto_rotate: bool = True
    rotate_speed: float = 1.0
    morph_speed: float = 0.8
    read_step: int = 256


@dataclass
class Mesh3D:
    """Indexed polygon mesh ready for live projection and OBJ/STL export."""

    vertices: List[Tuple[float, float, float]]
    faces: List[Tuple[int, ...]]  # triangles or quads (0-indexed)
    edges: List[Tuple[int, int]]
    topology: str
    closed: bool
    ram_signature: str

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def triangle_count(self) -> int:
        return sum(max(1, len(f) - 2) for f in self.faces)


def _extract_features(ram_bytes: bytes, count: int = 24) -> List[float]:
    if not ram_bytes:
        return [0.5] * count
    n = len(ram_bytes)
    out = []
    for i in range(count):
        v = ram_bytes[(i * max(1, n // count)) % n]
        out.append(v / 255.0)
    return out


def _supershape_r(angle: float, m: float, n1: float, n2: float, n3: float) -> float:
    a, b = 1.0, 1.0
    t1 = abs(math.cos(m * angle / 4.0) / a) ** max(0.25, n2)
    t2 = abs(math.sin(m * angle / 4.0) / b) ** max(0.25, n3)
    denom = (t1 + t2) ** (1.0 / max(0.25, n1))
    if denom < 1e-6 or not math.isfinite(denom):
        return 1.0
    return min(2.2, 1.0 / denom)


def _ensure_outward_winding(
    vertices: List[Tuple[float, float, float]],
    faces: List[Tuple[int, ...]],
) -> List[Tuple[int, ...]]:
    """Orient faces outward relative to origin for radial closed meshes."""
    fixed: List[Tuple[int, ...]] = []
    for face in faces:
        if len(face) < 3:
            continue
        p0 = vertices[face[0]]
        p1 = vertices[face[1]]
        p2 = vertices[face[2]]
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        cx = sum(vertices[idx][0] for idx in face) / len(face)
        cy = sum(vertices[idx][1] for idx in face) / len(face)
        cz = sum(vertices[idx][2] for idx in face) / len(face)
        if nx * cx + ny * cy + nz * cz < 0:
            fixed.append(tuple(reversed(face)))
        else:
            fixed.append(face)
    return fixed


def _smooth_vertices(
    vertices: List[Tuple[float, float, float]],
    faces: List[Tuple[int, ...]],
    passes: int,
) -> List[Tuple[float, float, float]]:
    if passes <= 0 or not vertices:
        return vertices
    adj: List[set] = [set() for _ in range(len(vertices))]
    for face in faces:
        k = len(face)
        for i in range(k):
            a, b = face[i], face[(i + 1) % k]
            adj[a].add(b)
            adj[b].add(a)

    verts = list(vertices)
    for _ in range(passes):
        nxt = []
        for i, (vx, vy, vz) in enumerate(verts):
            nbrs = adj[i]
            if not nbrs:
                nxt.append((vx, vy, vz))
                continue
            ax = sum(verts[j][0] for j in nbrs) / len(nbrs)
            ay = sum(verts[j][1] for j in nbrs) / len(nbrs)
            az = sum(verts[j][2] for j in nbrs) / len(nbrs)
            nxt.append((vx * 0.6 + ax * 0.4, vy * 0.6 + ay * 0.4, vz * 0.6 + az * 0.4))
        verts = nxt
    return verts


def _unique_edges(faces: List[Tuple[int, ...]]) -> List[Tuple[int, int]]:
    edge_set = set()
    for f in faces:
        k = len(f)
        for i in range(k):
            a, b = f[i], f[(i + 1) % k]
            edge_set.add((a, b) if a < b else (b, a))
    return sorted(edge_set)


def _normalize_mesh(vertices: List[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
    if not vertices:
        return vertices
    cx = sum(v[0] for v in vertices) / len(vertices)
    cy = sum(v[1] for v in vertices) / len(vertices)
    cz = sum(v[2] for v in vertices) / len(vertices)
    shifted = [(v[0] - cx, v[1] - cy, v[2] - cz) for v in vertices]
    max_r = max((math.sqrt(x * x + y * y + z * z) for x, y, z in shifted), default=1.0)
    scale = 1.0 / max(1e-6, max_r)
    return [(x * scale, y * scale, z * scale) for x, y, z in shifted]


def _build_terrain(ram_bytes: bytes, cfg: Model3DConfig, feats: List[float], phase: float) -> Mesh3D:
    n = max(6, min(28, int(cfg.subdivisions)))
    amp = max(0.05, float(cfg.amplitude))
    freq = max(0.3, float(cfg.frequency))
    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []
    rlen = max(1, len(ram_bytes))

    for iy in range(n):
        v = (iy / (n - 1)) * 2.0 - 1.0
        for ix in range(n):
            u = (ix / (n - 1)) * 2.0 - 1.0
            b_idx = (iy * n + ix) % rlen
            ram_h = (ram_bytes[b_idx] / 255.0 - 0.5) * 0.45
            wave_h = (
                math.sin(u * freq + phase + feats[0] * math.tau)
                * math.cos(v * freq - phase * 0.7 + feats[1] * math.tau)
                * 0.45
            )
            ridge = math.sin(math.hypot(u, v) * freq * 1.4 - phase) * 0.25
            y_h = (ram_h + wave_h + ridge) * amp
            # Slight twist in XZ plane if twist > 0
            ang = cfg.twist * 0.35 * math.hypot(u, v)
            ca, sa = math.cos(ang), math.sin(ang)
            rx = u * ca - v * sa
            rz = u * sa + v * ca
            verts.append((rx, y_h, rz))

    for iy in range(n - 1):
        for ix in range(n - 1):
            a = iy * n + ix
            b = a + 1
            c = a + n + 1
            d = a + n
            faces.append((a, b, c, d))

    verts = _smooth_vertices(verts, faces, cfg.smoothing)
    verts = _normalize_mesh(verts)
    return Mesh3D(
        vertices=verts,
        faces=faces,
        edges=_unique_edges(faces),
        topology="terrain",
        closed=False,
        ram_signature=hashlib.sha256(ram_bytes).hexdigest()[:12].upper(),
    )


def _build_supershape(ram_bytes: bytes, cfg: Model3DConfig, feats: List[float], phase: float) -> Mesh3D:
    n_lat = max(8, min(26, int(cfg.subdivisions)))
    n_lon = max(12, min(36, int(cfg.subdivisions * 1.4)))

    m1 = 2.0 + int(feats[0] * 7) + cfg.frequency * 0.8 + 0.6 * math.sin(phase * 0.5)
    n1_1 = 0.6 + feats[1] * 1.8
    n2_1 = 0.7 + feats[2] * 2.2
    n3_1 = 0.7 + feats[3] * 2.2

    m2 = 2.0 + int(feats[4] * 6) + cfg.frequency * 0.6
    n1_2 = 0.6 + feats[5] * 1.8
    n2_2 = 0.7 + feats[6] * 2.0
    n3_2 = 0.7 + feats[7] * 2.0

    verts: List[Tuple[float, float, float]] = [(0.0, 0.0, 0.0)]  # south pole idx 0
    # Compute pole radii
    r2_s = _supershape_r(-math.pi / 2.0, m2, n1_2, n2_2, n3_2)
    r2_n = _supershape_r(math.pi / 2.0, m2, n1_2, n2_2, n3_2)
    verts[0] = (0.0, -r2_s, 0.0)

    ring_count = n_lat - 1
    for i in range(1, n_lat):
        phi = -math.pi / 2.0 + math.pi * (i / n_lat)
        r2 = _supershape_r(phi, m2, n1_2, n2_2, n3_2)
        cphi, sphi = math.cos(phi), math.sin(phi)
        for j in range(n_lon):
            theta = -math.pi + math.tau * (j / n_lon)
            r1 = _supershape_r(theta, m1, n1_1, n2_1, n3_1)
            byte_mod = 1.0 + ((ram_bytes[(i * n_lon + j) % len(ram_bytes)] / 255.0) - 0.5) * 0.25 * cfg.amplitude
            twist_ang = theta + cfg.twist * phi
            x = r1 * math.cos(twist_ang) * r2 * cphi * byte_mod
            y = r2 * sphi * byte_mod
            z = r1 * math.sin(twist_ang) * r2 * cphi * byte_mod
            verts.append((x, y, z))

    north_idx = len(verts)
    verts.append((0.0, r2_n, 0.0))

    faces: List[Tuple[int, ...]] = []
    # Bottom cap
    for j in range(n_lon):
        j_nxt = (j + 1) % n_lon
        faces.append((0, 1 + j_nxt, 1 + j))
    # Middle rings
    for i in range(ring_count - 1):
        row0 = 1 + i * n_lon
        row1 = 1 + (i + 1) * n_lon
        for j in range(n_lon):
            j_nxt = (j + 1) % n_lon
            faces.append((row0 + j, row0 + j_nxt, row1 + j_nxt, row1 + j))
    # Top cap
    last_row = 1 + (ring_count - 1) * n_lon
    for j in range(n_lon):
        j_nxt = (j + 1) % n_lon
        faces.append((last_row + j, last_row + j_nxt, north_idx))

    verts = _smooth_vertices(verts, faces, cfg.smoothing)
    verts = _normalize_mesh(verts)
    faces = _ensure_outward_winding(verts, faces)
    return Mesh3D(
        vertices=verts,
        faces=faces,
        edges=_unique_edges(faces),
        topology="supershape",
        closed=True,
        ram_signature=hashlib.sha256(ram_bytes).hexdigest()[:12].upper(),
    )


def _build_geosphere(ram_bytes: bytes, cfg: Model3DConfig, feats: List[float], phase: float) -> Mesh3D:
    # Start with regular octahedron and subdivide
    verts_list: List[Tuple[float, float, float]] = [
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
    ]
    tris: List[Tuple[int, int, int]] = [
        (0, 2, 4), (4, 2, 1), (1, 2, 5), (5, 2, 0),
        (4, 3, 0), (1, 3, 4), (5, 3, 1), (0, 3, 5),
    ]

    sub_levels = 1 if cfg.subdivisions < 12 else (2 if cfg.subdivisions < 22 else 3)
    for _ in range(sub_levels):
        mid_cache: Dict[Tuple[int, int], int] = {}

        def get_mid(a: int, b: int) -> int:
            key = (a, b) if a < b else (b, a)
            if key in mid_cache:
                return mid_cache[key]
            va, vb = verts_list[a], verts_list[b]
            mx, my, mz = (va[0] + vb[0]) * 0.5, (va[1] + vb[1]) * 0.5, (va[2] + vb[2]) * 0.5
            ln = max(1e-6, math.sqrt(mx * mx + my * my + mz * mz))
            idx = len(verts_list)
            verts_list.append((mx / ln, my / ln, mz / ln))
            mid_cache[key] = idx
            return idx

        new_tris: List[Tuple[int, int, int]] = []
        for a, b, c in tris:
            ab = get_mid(a, b)
            bc = get_mid(b, c)
            ca = get_mid(c, a)
            new_tris.extend([(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)])
        tris = new_tris

    # Displace vertices along radial direction from RAM harmonics
    displaced: List[Tuple[float, float, float]] = []
    freq = cfg.frequency * 1.8
    amp = cfg.amplitude * 0.45
    for idx, (x, y, z) in enumerate(verts_list):
        b_val = ram_bytes[idx % len(ram_bytes)] / 255.0 - 0.5
        harm = (
            math.sin(x * freq + phase + feats[0] * math.tau)
            + math.cos(y * freq - phase * 0.8 + feats[1] * math.tau)
            + math.sin(z * freq + phase * 1.1 + feats[2] * math.tau)
        ) / 3.0
        r = max(0.35, 1.0 + amp * (harm * 0.75 + b_val * 0.5))
        ang = cfg.twist * y * 0.6
        ca, sa = math.cos(ang), math.sin(ang)
        displaced.append(((x * ca - z * sa) * r, y * r, (x * sa + z * ca) * r))

    faces = [tuple(t) for t in tris]
    displaced = _smooth_vertices(displaced, faces, cfg.smoothing)
    displaced = _normalize_mesh(displaced)
    faces = _ensure_outward_winding(displaced, faces)
    return Mesh3D(
        vertices=displaced,
        faces=faces,
        edges=_unique_edges(faces),
        topology="geosphere",
        closed=True,
        ram_signature=hashlib.sha256(ram_bytes).hexdigest()[:12].upper(),
    )


def _build_torus_knot(ram_bytes: bytes, cfg: Model3DConfig, feats: List[float], phase: float) -> Mesh3D:
    n_u = max(12, min(36, int(cfg.subdivisions * 1.5)))
    n_v = max(8, min(20, int(cfg.subdivisions * 0.8)))
    R = 0.72
    r_base = 0.28
    verts: List[Tuple[float, float, float]] = []
    faces: List[Tuple[int, ...]] = []
    # Compute faces with outward orientation relative to ring tube center
    tube_centers: List[Tuple[float, float, float]] = []

    for i in range(n_u):
        u = math.tau * (i / n_u)
        cx = R * math.cos(u)
        cz = R * math.sin(u)
        cy = 0.14 * cfg.amplitude * math.sin(u * max(2, int(cfg.frequency)) + phase)
        for j in range(n_v):
            v = math.tau * (j / n_v) + cfg.twist * u
            b_val = ram_bytes[(i * n_v + j) % len(ram_bytes)] / 255.0 - 0.5
            r_mod = r_base * (1.0 + 0.35 * cfg.amplitude * math.sin(v * 3.0 + u * 2.0 + phase) + b_val * 0.22 * cfg.amplitude)
            rad = R + r_mod * math.cos(v)
            x = rad * math.cos(u)
            z = rad * math.sin(u)
            y = cy + r_mod * math.sin(v)
            verts.append((x, y, z))
            tube_centers.append((cx, cy, cz))

    for i in range(n_u):
        i_nxt = (i + 1) % n_u
        for j in range(n_v):
            j_nxt = (j + 1) % n_v
            a = i * n_v + j
            b = i_nxt * n_v + j
            c = i_nxt * n_v + j_nxt
            d = i * n_v + j_nxt
            # Orient outward from local tube centerline
            p0, p1, p2 = verts[a], verts[b], verts[c]
            ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
            vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            tc = tube_centers[a]
            dx, dy, dz = p0[0] - tc[0], p0[1] - tc[1], p0[2] - tc[2]
            if nx * dx + ny * dy + nz * dz < 0:
                faces.append((a, d, c, b))
            else:
                faces.append((a, b, c, d))

    verts = _smooth_vertices(verts, faces, cfg.smoothing)
    verts = _normalize_mesh(verts)
    return Mesh3D(
        vertices=verts,
        faces=faces,
        edges=_unique_edges(faces),
        topology="torus_knot",
        closed=True,
        ram_signature=hashlib.sha256(ram_bytes).hexdigest()[:12].upper(),
    )


def _build_crystal(ram_bytes: bytes, cfg: Model3DConfig, feats: List[float], phase: float) -> Mesh3D:
    n_sides = max(6, min(20, int(cfg.subdivisions)))
    tiers = 4
    verts: List[Tuple[float, float, float]] = [(0.0, -1.0 - 0.3 * feats[0], 0.0)]
    for tier in range(1, tiers):
        y = -0.55 + (tier / tiers) * 1.15
        base_rad = 0.72 * math.sin((tier / tiers) * math.pi) + 0.22
        for j in range(n_sides):
            ang = math.tau * (j / n_sides) + tier * cfg.twist * 0.25
            b = ram_bytes[(tier * n_sides + j) % len(ram_bytes)] / 255.0
            spike = base_rad * (1.0 + (b - 0.3) * 0.65 * cfg.amplitude + 0.25 * math.sin(ang * cfg.frequency + phase))
            verts.append((spike * math.cos(ang), y, spike * math.sin(ang)))
    top_idx = len(verts)
    verts.append((0.0, 1.0 + 0.3 * feats[1], 0.0))

    faces: List[Tuple[int, ...]] = []
    for j in range(n_sides):
        j_nxt = (j + 1) % n_sides
        faces.append((0, 1 + j_nxt, 1 + j))
    for tier in range(tiers - 2):
        r0 = 1 + tier * n_sides
        r1 = 1 + (tier + 1) * n_sides
        for j in range(n_sides):
            j_nxt = (j + 1) % n_sides
            faces.append((r0 + j, r0 + j_nxt, r1 + j_nxt, r1 + j))
    last = 1 + (tiers - 2) * n_sides
    for j in range(n_sides):
        j_nxt = (j + 1) % n_sides
        faces.append((last + j, last + j_nxt, top_idx))

    verts = _normalize_mesh(verts)
    faces = _ensure_outward_winding(verts, faces)
    return Mesh3D(
        vertices=verts,
        faces=faces,
        edges=_unique_edges(faces),
        topology="crystal",
        closed=True,
        ram_signature=hashlib.sha256(ram_bytes).hexdigest()[:12].upper(),
    )


def generate_mesh_from_bytes(ram_bytes: bytes, config: Model3DConfig, phase: float = 0.0) -> Mesh3D:
    """Generate a procedural 3D Mesh3D driven by live RAM bytes."""
    if not ram_bytes:
        ram_bytes = b"\x33\x77\xbb\xef" * 64
    feats = _extract_features(ram_bytes, count=24)
    topo = config.topology.lower()
    if topo == "terrain":
        return _build_terrain(ram_bytes, config, feats, phase)
    if topo == "geosphere":
        return _build_geosphere(ram_bytes, config, feats, phase)
    if topo == "torus_knot":
        return _build_torus_knot(ram_bytes, config, feats, phase)
    if topo == "crystal":
        return _build_crystal(ram_bytes, config, feats, phase)
    return _build_supershape(ram_bytes, config, feats, phase)


def _lerp_color(c0: Tuple[int, int, int], c1: Tuple[int, int, int], t: float) -> str:
    t = max(0.0, min(1.0, t))
    r = int(c0[0] + (c1[0] - c0[0]) * t)
    g = int(c0[1] + (c1[1] - c0[1]) * t)
    b = int(c0[2] + (c1[2] - c0[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def project_mesh_for_canvas(
    mesh: Mesh3D,
    width: int,
    height: int,
    yaw: float = 0.6,
    pitch: float = 0.4,
    zoom: float = 1.0,
    render_mode: str = "hybrid",
    color_theme: str = "Cyber Cyan",
) -> dict:
    """Project 3D mesh into sorted 2D polygons/edges for snappy Tkinter Canvas rendering."""
    cy, sy = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    scale = min(width, height) * 0.42 * max(0.25, min(4.0, zoom))
    cx_2d, cy_2d = width * 0.5, height * 0.5
    cam_dist = 3.2

    transformed: List[Tuple[float, float, float]] = []
    projected: List[Tuple[float, float, float]] = []

    for x, y, z in mesh.vertices:
        # Rotate around Y (yaw)
        x1 = x * cy + z * sy
        z1 = -x * sy + z * cy
        # Rotate around X (pitch)
        y2 = y * cp - z1 * sp
        z2 = y * sp + z1 * cp
        transformed.append((x1, y2, z2))

        denom = max(0.35, cam_dist - z2)
        px = cx_2d + (x1 * scale) / denom * 2.1
        py = cy_2d - (y2 * scale) / denom * 2.1
        projected.append((px, py, z2))

    dark_col, bright_col, wire_col = COLOR_THEMES.get(color_theme, COLOR_THEMES["Cyber Cyan"])

    if render_mode == "wireframe":
        lines = []
        for a, b in mesh.edges:
            ax, ay, az = projected[a]
            bx, by, bz = projected[b]
            lines.append((ax, ay, bx, by, (az + bz) * 0.5))
        lines.sort(key=lambda item: item[4])
        return {"mode": "wireframe", "lines": [(l[0], l[1], l[2], l[3]) for l in lines], "wire_color": wire_col, "polys": []}

    # Shaded or hybrid mode: painter's algorithm depth sort
    lx, ly, lz = 0.38, 0.65, 0.66  # Normalized light vector facing camera-top-right
    polys = []
    for face in mesh.faces:
        if len(face) < 3:
            continue
        p0 = transformed[face[0]]
        p1 = transformed[face[1]]
        p2 = transformed[face[2]]
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
        if n_len < 1e-8:
            continue
        nx /= n_len
        ny /= n_len
        nz /= n_len

        if mesh.closed and nz <= -0.04:
            continue  # Backface cull closed surfaces cleanly

        intensity = nx * lx + ny * ly + nz * lz
        if not mesh.closed:
            intensity = abs(intensity)
        shade = max(0.08, min(1.0, 0.22 + 0.78 * max(0.0, intensity)))
        depth = sum(transformed[idx][2] for idx in face) / len(face)

        coords: List[float] = []
        for idx in face:
            px, py, _ = projected[idx]
            coords.extend((px, py))

        fill_hex = _lerp_color(dark_col, bright_col, shade)
        outline_hex = wire_col if render_mode == "hybrid" else fill_hex
        polys.append((depth, coords, fill_hex, outline_hex))

    polys.sort(key=lambda item: item[0])
    return {
        "mode": render_mode,
        "polys": [(p[1], p[2], p[3]) for p in polys],
        "lines": [],
        "wire_color": wire_col,
    }


def export_obj(mesh: Mesh3D, path: str) -> str:
    """Export Mesh3D to standard Wavefront .OBJ format."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Song-of-my-Ram 3D Mesh ({mesh.topology})\n")
        f.write(f"# RAM Signature: {mesh.ram_signature}\n")
        f.write(f"# Vertices: {mesh.vertex_count} | Triangles: {mesh.triangle_count}\n")
        f.write(f"o ram_{mesh.topology}\n")
        for x, y, z in mesh.vertices:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        for face in mesh.faces:
            indices = " ".join(str(idx + 1) for idx in face)
            f.write(f"f {indices}\n")
    return path


def _triangulate_faces(mesh: Mesh3D) -> List[Tuple[int, int, int]]:
    tris: List[Tuple[int, int, int]] = []
    for face in mesh.faces:
        if len(face) == 3:
            tris.append((face[0], face[1], face[2]))
        elif len(face) >= 4:
            for i in range(1, len(face) - 1):
                tris.append((face[0], face[i], face[i + 1]))
    return tris


def _tri_normal(v0: Tuple[float, float, float], v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> Tuple[float, float, float]:
    ux, uy, uz = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
    vx, vy, vz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    ln = math.sqrt(nx * nx + ny * ny + nz * nz)
    if ln < 1e-9:
        return (0.0, 0.0, 1.0)
    return (nx / ln, ny / ln, nz / ln)


def export_stl(mesh: Mesh3D, path: str, binary: bool = False) -> str:
    """Export Mesh3D to valid ASCII or Binary .STL format."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tris = _triangulate_faces(mesh)
    if binary:
        with open(path, "wb") as f:
            header = f"Song-of-my-Ram {mesh.topology} {mesh.ram_signature}".encode("ascii", errors="ignore")[:80]
            f.write(header.ljust(80, b" "))
            f.write(struct.pack("<I", len(tris)))
            for a, b, c in tris:
                v0, v1, v2 = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
                nx, ny, nz = _tri_normal(v0, v1, v2)
                f.write(struct.pack("<12fH", nx, ny, nz, *v0, *v1, *v2, 0))
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"solid ram_{mesh.topology}\n")
            for a, b, c in tris:
                v0, v1, v2 = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
                nx, ny, nz = _tri_normal(v0, v1, v2)
                f.write(f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}\n")
                f.write("    outer loop\n")
                f.write(f"      vertex {v0[0]:.6f} {v0[1]:.6f} {v0[2]:.6f}\n")
                f.write(f"      vertex {v1[0]:.6f} {v1[1]:.6f} {v1[2]:.6f}\n")
                f.write(f"      vertex {v2[0]:.6f} {v2[1]:.6f} {v2[2]:.6f}\n")
                f.write("    endloop\n")
                f.write("  endfacet\n")
            f.write(f"endsolid ram_{mesh.topology}\n")
    return path
