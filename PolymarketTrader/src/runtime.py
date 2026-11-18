"""Keeping the job light on the PC it shares with other work (the stock trader's daily job, a sweep, games).

The cycle is one Python process doing a few dozen small HTTP requests and, at most, one Claude process at a
time; it holds a few megabytes. These guards cover the ways it could still get in the way:

  single instance   a lock file, so a slow cycle and the next scheduled one never overlap
  quiet windows     local-time ranges in which the job exits at once (default: the stock trader's evening run)
  low priority      below-normal process priority, so anything interactive wins the CPU
  free memory       the job does not start if the machine is already short of RAM
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


class Busy(RuntimeError):
    """Another cycle is running, or this is not a time to run."""


def in_quiet_window(windows: list[str] | None, now: datetime | None = None) -> str | None:
    """windows like ["17:15-18:20"] in local time (a window may cross midnight). Returns the matching one."""
    now = now or datetime.now()
    hm = now.hour * 60 + now.minute
    for w in windows or []:
        try:
            a, b = str(w).split("-")
            (ah, am), (bh, bm) = a.strip().split(":"), b.strip().split(":")
            lo, hi = int(ah) * 60 + int(am), int(bh) * 60 + int(bm)
        except ValueError:
            raise ValueError(f"runtime.quiet_windows entry {w!r} is not of the form HH:MM-HH:MM") from None
        if (lo <= hm < hi) if lo <= hi else (hm >= lo or hm < hi):
            return w
    return None


def lower_priority() -> None:
    """Below-normal priority. Best effort: never an error."""
    try:
        if sys.platform == "win32":
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except Exception:
        pass


def free_memory_gb() -> float | None:
    """Free physical memory in GB, or None when it cannot be read (no extra dependency is installed for this)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX()
            st.dwLength = ctypes.sizeof(st)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return None
            return st.ullAvailPhys / 2 ** 30
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 2 ** 20
    except Exception:
        return None
    return None


class Lock:
    """data/cycle.lock holds the PID and start time. The running cycle touches it as it works (`touch`), so a lock
    whose file has not changed for `stale_hours` belongs to a run that died and is taken over."""

    def __init__(self, path: str | Path, stale_hours: float = 3.0):
        self.path, self.stale_s = Path(path), stale_hours * 3600.0
        self.held = False
        self.tag = f"pid {os.getpid()} started {time.strftime('%Y-%m-%d %H:%M:%S')} id {uuid.uuid4().hex[:8]}"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime < self.stale_s:
            raise Busy(f"another cycle holds {self.path} ({self.path.read_text(encoding='utf-8', errors='replace').strip()})")
        self.path.write_text(self.tag, encoding="utf-8")
        self.held = True
        return self

    def touch(self) -> None:
        """Called between slow steps: shows the cycle is alive, so a long run is never mistaken for a dead one."""
        if self.held and self.ours():
            try:
                os.utime(self.path, None)
            except OSError:
                pass

    def ours(self) -> bool:
        try:
            return self.path.read_text(encoding="utf-8", errors="replace").strip() == self.tag
        except OSError:
            return False

    def __exit__(self, *exc):
        if self.held and self.ours():               # never remove a lock another run has taken over
            try:
                self.path.unlink()
            except OSError:
                pass
        return False


def preflight(cfg: dict | None, root: str | Path = ".") -> None:
    """Raise Busy when the job should not run now. Call before anything else."""
    rt = (cfg or {}).get("runtime") or {}
    w = in_quiet_window(rt.get("quiet_windows"))
    if w:
        raise Busy(f"quiet window {w}")
    need = rt.get("min_free_gb")
    free = free_memory_gb()
    if need and free is not None and free < float(need):
        raise Busy(f"only {free:.1f} GB of memory free (needs {float(need):g} GB)")
    if rt.get("low_priority", True):
        lower_priority()
