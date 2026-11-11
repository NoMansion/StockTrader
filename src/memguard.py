"""Memory guard for the daily job: stop the run before the machine runs out of RAM.

On 2026-11-11 an unguarded daily run took free memory from 6 GB to under 1 GB in a minute while it built
features; Windows started thrashing and the PC froze until it was power-cycled. The guard is a tiny
separate process (so it keeps polling while pandas holds the interpreter) that watches free physical
memory and terminates the job when it falls below `live.min_free_gb`. The job stops the guard before it
talks to the broker, so a run is never cut off halfway through sending orders.

    guard = start_guard(1.0)     # early in the job
    ...                          # load data, build features, pick targets
    stop_guard(guard)            # before any order is submitted

Windows only (the machine this runs on); elsewhere start_guard() is a no-op.
"""
from __future__ import annotations

import subprocess
import sys

_SYNCHRONIZE, _PROCESS_TERMINATE, _WAIT_TIMEOUT = 0x00100000, 0x0001, 0x00000102


def available_gb() -> float | None:
    """Free physical memory in GB, or None when it cannot be read on this platform."""
    if sys.platform != "win32":
        return None
    import ctypes

    class _MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    st = _MemoryStatus()
    st.dwLength = ctypes.sizeof(st)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return None
    return st.ullAvailPhys / 2 ** 30


def watch(min_free_gb: float, parent_exited, read=available_gb, kill=None, say=print) -> str:
    """Poll until the parent exits ("parent_exited") or free memory drops below the floor ("killed").

    `parent_exited()` blocks for one poll interval and returns True once the parent is gone;
    `kill()` terminates the parent. Both are injected so the loop can be tested without processes."""
    while True:
        if parent_exited():
            return "parent_exited"
        free = read()
        if free is not None and free < min_free_gb:
            say(f"\nMEMORY GUARD: only {free:.2f} GB of RAM free (floor {min_free_gb} GB). Stopping the daily job "
                f"before the machine freezes. No orders were sent by this run. Free memory (stop sweep workers) "
                f"and run it again.", flush=True)
            if kill is not None:
                kill()
            return "killed"


def _watch_pid(pid: int, min_free_gb: float, interval_s: float) -> str:
    import ctypes
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(_SYNCHRONIZE | _PROCESS_TERMINATE, False, pid)
    if not handle:
        return "no_parent"
    try:
        return watch(min_free_gb,
                     parent_exited=lambda: k32.WaitForSingleObject(handle, int(interval_s * 1000)) != _WAIT_TIMEOUT,
                     kill=lambda: k32.TerminateProcess(handle, 3))
    finally:
        k32.CloseHandle(handle)


def start_guard(min_free_gb: float | None, interval_s: float = 1.0) -> subprocess.Popen | None:
    """Start the watcher for the current process. None / 0 disables it; so does a non-Windows platform."""
    if not min_free_gb or sys.platform != "win32":
        return None
    import os
    from pathlib import Path
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def real_file(stream):       # hand the job's own log to the watcher so its message lands in the same place
        try:
            stream.fileno()
            return stream
        except Exception:
            return None

    return subprocess.Popen([sys.executable, "-m", "src.memguard", str(os.getpid()), str(float(min_free_gb)), str(interval_s)],
                            creationflags=flags, cwd=str(Path(__file__).resolve().parent.parent),
                            stdin=subprocess.DEVNULL, stdout=real_file(sys.stdout), stderr=real_file(sys.stderr))


def stop_guard(proc: subprocess.Popen | None) -> None:
    """Stop the watcher (call before submitting orders). Safe to call twice or with None."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":
    _watch_pid(int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 1.0)
