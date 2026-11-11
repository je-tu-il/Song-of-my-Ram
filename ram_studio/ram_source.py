"""Live RAM inspection and cross-process entropy sampling utilities."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import math
import os
import sys
import threading
import time
from typing import Dict, List, Optional

import psutil

IS_WINDOWS = os.name == "nt"

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

if IS_WINDOWS:
    from ctypes import wintypes

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
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.VirtualQueryEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION),
        ctypes.c_size_t,
    ]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t
    kernel32.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
else:
    MEMORY_BASIC_INFORMATION = None
    kernel32 = None


@dataclass(frozen=True)
class ProcessInfo:
    """Metadata for an inspectable process."""

    pid: int
    name: str
    rss_mb: float
    readable: bool = True

    @property
    def label(self) -> str:
        return f"{self.name} (PID {self.pid} — {self.rss_mb:.1f} Mo)"


def is_admin() -> bool:
    """Return True if running with elevated administrator privileges on Windows."""
    if not IS_WINDOWS:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate_admin() -> bool:
    """Attempt to relaunch the current script with UAC admin privileges.

    Returns True if elevation was initiated (caller should exit), False otherwise.
    """
    if not IS_WINDOWS or is_admin():
        return False
    try:
        params = " ".join(f'"{arg}"' for arg in sys.argv)
        res = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return int(res) > 32
    except Exception:
        return False


def shannon_entropy(data: bytes) -> float:
    """Calculate Shannon entropy in bits per byte (0.0 to 8.0)."""
    if not data:
        return 0.0
    length = len(data)
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    entropy = 0.0
    for count in counts:
        if count:
            p = count / length
            entropy -= p * math.log2(p)
    return entropy


def list_readable_processes(limit: int = 16) -> List[ProcessInfo]:
    """List processes sorted by RSS descending that can be queried for RAM."""
    procs: List[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            pid = proc.info["pid"]
            mem = proc.info["memory_info"]
            if mem is None or pid <= 0:
                continue
            readable = False
            if IS_WINDOWS and kernel32 is not None:
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    readable = True
            else:
                # On POSIX, self or /proc/<pid>/mem readability check
                if pid == os.getpid():
                    readable = True
                elif os.path.exists(f"/proc/{pid}/mem") and os.access(f"/proc/{pid}/mem", os.R_OK):
                    readable = True
            if readable:
                procs.append(
                    ProcessInfo(
                        pid=pid,
                        name=proc.info.get("name") or f"pid_{pid}",
                        rss_mb=mem.rss / (1024 * 1024),
                        readable=True,
                    )
                )
        except Exception:
            continue

    procs.sort(key=lambda item: item.rss_mb, reverse=True)
    if not procs:
        # Ensure current process is always available as a safe fallback
        try:
            cur = psutil.Process(os.getpid())
            rss_mb = cur.memory_info().rss / (1024 * 1024)
            procs.append(ProcessInfo(pid=os.getpid(), name=cur.name(), rss_mb=rss_mb, readable=True))
        except Exception:
            procs.append(ProcessInfo(pid=os.getpid(), name="python", rss_mb=32.0, readable=True))
    return procs[:limit]


class ProcessReader:
    """Safe sequential and block reader over a process's committed virtual memory."""

    def __init__(self, pid: int):
        self.pid = int(pid)
        self.handle = None
        self.address = 0
        self.current_region_end = 0
        self._chunk_cache = bytearray()
        self._chunk_offset = 0
        self._last_step = 0
        if IS_WINDOWS and kernel32 is not None:
            self.handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, self.pid)

    def _find_next_region(self) -> bool:
        if not self.handle or not IS_WINDOWS or kernel32 is None:
            return False
        mbi = MEMORY_BASIC_INFORMATION()
        for _ in range(128):
            if not kernel32.VirtualQueryEx(
                self.handle,
                ctypes.c_void_p(self.address),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            ):
                self.address = 0
                self.current_region_end = 0
                return False

            base_addr = mbi.BaseAddress or 0
            region_end = base_addr + mbi.RegionSize
            if region_end <= self.address:
                self.address = 0
                self.current_region_end = 0
                return False

            self.current_region_end = region_end
            if mbi.State == MEM_COMMIT and not (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)):
                if self.address < base_addr:
                    self.address = base_addr
                return True
            self.address = region_end
        return False

    def read_bytes(self, count: int, step: int = 256) -> bytes:
        """Read `count` bytes sampled from live process memory, falling back cleanly if unavailable."""
        if count <= 0:
            return b""

        step = max(1, int(step))
        collected = bytearray()

        if self.handle and IS_WINDOWS and kernel32 is not None:
            # Read in larger contiguous chunks and stride inside Python for speed
            attempts = 0
            while len(collected) < count and attempts < 64:
                attempts += 1
                if self.address >= self.current_region_end:
                    if not self._find_next_region():
                        # Wrap back to start once on end-of-address-space
                        if attempts > 1:
                            break
                        if not self._find_next_region():
                            break

                remaining_needed = count - len(collected)
                region_avail = max(0, self.current_region_end - self.address)
                if region_avail == 0:
                    self.address = self.current_region_end
                    continue

                if step <= 64:
                    # Contiguous block read then stride
                    span = min(region_avail, max(256, remaining_needed * step), 65536)
                    buf = ctypes.create_string_buffer(span)
                    bytes_read = ctypes.c_size_t(0)
                    ok = kernel32.ReadProcessMemory(
                        self.handle,
                        ctypes.c_void_p(self.address),
                        buf,
                        span,
                        ctypes.byref(bytes_read),
                    )
                    if ok and bytes_read.value > 0:
                        raw = buf.raw[: bytes_read.value]
                        sampled = raw[::step]
                        take = min(len(sampled), remaining_needed)
                        collected.extend(sampled[:take])
                        self.address += max(step, take * step)
                    else:
                        self.address = self.current_region_end
                else:
                    # Large stride: sample a 16-byte micro-slice per jump
                    micro = min(16, region_avail, remaining_needed)
                    buf = ctypes.create_string_buffer(micro)
                    bytes_read = ctypes.c_size_t(0)
                    ok = kernel32.ReadProcessMemory(
                        self.handle,
                        ctypes.c_void_p(self.address),
                        buf,
                        micro,
                        ctypes.byref(bytes_read),
                    )
                    self.address += step
                    if ok and bytes_read.value > 0:
                        collected.extend(buf.raw[: bytes_read.value])
                    else:
                        self.address = self.current_region_end

        if len(collected) < count:
            # Safe fallback using live process counters + system memory state + urandom
            needed = count - len(collected)
            collected.extend(self._fallback_entropy(needed))

        return bytes(collected[:count])

    def read_byte(self, step: int = 512) -> int:
        """Read a single byte from process RAM (buffered internally for low overhead)."""
        step = max(1, int(step))
        if self._chunk_offset >= len(self._chunk_cache) or self._last_step != step:
            self._chunk_cache = bytearray(self.read_bytes(64, step=step))
            self._chunk_offset = 0
            self._last_step = step
        val = self._chunk_cache[self._chunk_offset]
        self._chunk_offset += 1
        return val

    def _fallback_entropy(self, needed: int) -> bytes:
        vm = psutil.virtual_memory()
        seed_material = f"{self.pid}:{time.perf_counter_ns()}:{vm.available}:{vm.percent}".encode()
        out = bytearray()
        counter = 0
        while len(out) < needed:
            digest = hashlib.blake2b(
                seed_material + counter.to_bytes(4, "little") + os.urandom(16),
                digest_size=64,
            ).digest()
            out.extend(digest)
            counter += 1
        return bytes(out[:needed])

    def close(self) -> None:
        if self.handle and IS_WINDOWS and kernel32 is not None:
            try:
                kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None

    def __enter__(self) -> "ProcessReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


class RAMEntropyPool:
    """Thread-safe RAM sampler shared across all Song-of-my-Ram generator tabs."""

    def __init__(self, max_processes: int = 10):
        self.max_processes = max_processes
        self._lock = threading.Lock()
        self.processes: List[ProcessInfo] = []
        self.selected_pid: Optional[int] = None  # None = Auto mix across top processes
        self._readers: Dict[int, ProcessReader] = {}
        self._cursor = 0
        self.last_telemetry: dict = {
            "source_pids": [],
            "source_names": [],
            "shannon_entropy": 0.0,
            "sample_hex": "",
            "total_bytes": 0,
            "live_ram": False,
        }
        self.refresh_processes()

    def refresh_processes(self) -> List[ProcessInfo]:
        """Rescan readable processes and refresh internal readers."""
        procs = list_readable_processes(limit=max(self.max_processes, 16))
        with self._lock:
            self.processes = procs
            valid_pids = {p.pid for p in procs}
            if self.selected_pid is not None and self.selected_pid not in valid_pids:
                self.selected_pid = None
            # Close stale readers
            for pid in list(self._readers.keys()):
                if pid not in valid_pids:
                    self._readers.pop(pid).close()
        return procs

    def set_selected_pid(self, pid: Optional[int]) -> None:
        with self._lock:
            self.selected_pid = pid

    def get_active_processes(self, pid: Optional[int] = None) -> List[ProcessInfo]:
        with self._lock:
            if not self.processes:
                self.processes = list_readable_processes(limit=self.max_processes)
            target = pid if pid is not None else self.selected_pid
            if target is not None:
                matched = [p for p in self.processes if p.pid == target]
                if matched:
                    return matched
            return self.processes[: self.max_processes]

    def _get_reader(self, pid: int) -> ProcessReader:
        reader = self._readers.get(pid)
        if reader is None:
            reader = ProcessReader(pid)
            self._readers[pid] = reader
        return reader

    def sample_bytes(
        self,
        count: int,
        step: int = 512,
        pid: Optional[int] = None,
        non_zero_bias: bool = False,
    ) -> bytes:
        """Sample `count` bytes from live RAM across selected/top processes."""
        if count <= 0:
            return b""

        with self._lock:
            targets = self.processes[: self.max_processes]
            effective_pid = pid if pid is not None else self.selected_pid
            if effective_pid is not None:
                matched = [p for p in self.processes if p.pid == effective_pid]
                if matched:
                    targets = matched
            if not targets:
                targets = list_readable_processes(limit=self.max_processes)
                self.processes = targets

            # Round-robin slices from active readers to blend processes
            out = bytearray()
            used_pids: List[int] = []
            used_names: List[str] = []
            live_any = False

            per_proc = max(16, math.ceil(count / max(1, min(len(targets), 4))))
            rounds = 0
            while len(out) < count and rounds < 8:
                rounds += 1
                for idx in range(len(targets)):
                    proc = targets[(self._cursor + idx) % len(targets)]
                    reader = self._get_reader(proc.pid)
                    if reader.handle:
                        live_any = True
                    chunk = reader.read_bytes(min(per_proc, count - len(out) + (per_proc if non_zero_bias else 0)), step=step)
                    if non_zero_bias:
                        nz = bytes(b for b in chunk if b != 0)
                        if len(nz) >= max(4, len(chunk) // 8):
                            chunk = nz
                    take = min(len(chunk), count - len(out))
                    out.extend(chunk[:take])
                    if proc.pid not in used_pids:
                        used_pids.append(proc.pid)
                        used_names.append(proc.name)
                    if len(out) >= count:
                        break
                self._cursor = (self._cursor + 1) % max(1, len(targets))

            result = bytes(out[:count])
            ent = shannon_entropy(result)
            self.last_telemetry = {
                "source_pids": used_pids,
                "source_names": used_names,
                "shannon_entropy": round(ent, 3),
                "sample_hex": result[:32].hex(" ").upper(),
                "total_bytes": self.last_telemetry["total_bytes"] + len(result),
                "live_ram": live_any,
            }
            return result

    def close(self) -> None:
        with self._lock:
            for reader in self._readers.values():
                reader.close()
            self._readers.clear()
