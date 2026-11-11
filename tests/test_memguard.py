import subprocess
import sys
import time

import pytest

from src.memguard import available_gb, start_guard, stop_guard, watch


def test_watch_kills_when_memory_falls_below_the_floor():
    readings = iter([6.0, 5.5, 0.6, 9.9])
    killed, said = [], []
    out = watch(1.0, parent_exited=lambda: False, read=lambda: next(readings),
                kill=lambda: killed.append(1), say=lambda *a, **k: said.append(a[0]))
    assert out == "killed" and killed == [1]
    assert "MEMORY GUARD" in said[0] and "0.60 GB" in said[0]


def test_watch_stops_quietly_when_the_parent_exits():
    polls = iter([False, False, True])
    killed = []
    out = watch(1.0, parent_exited=lambda: next(polls), read=lambda: 8.0, kill=lambda: killed.append(1))
    assert out == "parent_exited" and not killed


def test_watch_ignores_an_unreadable_memory_figure():
    polls = iter([False, True])
    killed = []
    assert watch(1.0, parent_exited=lambda: next(polls), read=lambda: None, kill=lambda: killed.append(1)) == "parent_exited"
    assert not killed


def test_start_guard_is_off_without_a_floor():
    assert start_guard(None) is None and start_guard(0) is None
    stop_guard(None)                                         # no-op


@pytest.mark.skipif(sys.platform != "win32", reason="the guard reads memory through the Windows API")
def test_guard_process_terminates_its_parent_when_the_floor_is_above_free_memory():
    assert available_gb() > 0
    # a throwaway parent that starts a guard with an impossible floor (1e6 GB) and then just sleeps
    code = ("import sys, time; sys.path.insert(0, '.'); from src.memguard import start_guard; "
            "start_guard(1e6, interval_s=0.2); time.sleep(60)")
    t0 = time.time()
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=45)
    assert p.returncode == 3 and time.time() - t0 < 40      # terminated by the guard, not by the sleep ending
    assert "MEMORY GUARD" in p.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="the guard reads memory through the Windows API")
def test_guard_process_can_be_stopped_and_leaves_the_parent_alone():
    g = start_guard(0.000001, interval_s=0.2)                # floor far below any real reading: never fires
    time.sleep(1.0)
    assert g.poll() is None                                  # still watching, parent (this test) still alive
    stop_guard(g)
    assert g.poll() is not None
    stop_guard(g)                                            # second call is harmless
