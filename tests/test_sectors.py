import json

from src.sectors import load_sectors


def test_load_sectors_caches_and_only_looks_up_missing(tmp_path):
    cache = tmp_path / "sectors.json"
    calls = []

    def lookup(t):
        calls.append(t)
        return {"AAA": "Energy", "BBB": None}.get(t, "Utilities")

    first = load_sectors(["AAA", "BBB"], cache, lookup=lookup)
    assert first == {"AAA": "Energy", "BBB": "Unknown"}
    assert json.loads(cache.read_text()) == {"AAA": "Energy", "BBB": "Unknown"}

    second = load_sectors(["AAA", "BBB", "CCC"], cache, lookup=lookup)
    assert second == {"AAA": "Energy", "BBB": "Unknown", "CCC": "Utilities"}
    assert calls == ["AAA", "BBB", "CCC"]           # AAA/BBB served from cache the second time


def test_lookup_errors_become_unknown(tmp_path):
    def boom(t):
        raise RuntimeError("NDU down")

    assert load_sectors(["ZZZ"], tmp_path / "s.json", lookup=boom) == {"ZZZ": "Unknown"}
