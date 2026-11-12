"""The hourly memory reading: reads /proc, names grown types, never raises."""

from collections import Counter

from tce.utils import memory_probe
from tce.utils.memory_probe import MemoryProbe, grown_types, read_status


def test_read_status_parses_kb_to_mb(tmp_path):
    p = tmp_path / "status"
    p.write_text(
        "Name:\tpython3\nVmHWM:\t 2457600 kB\nVmRSS:\t  148480 kB\nVmSwap:\t 2191360 kB\n"
    )
    assert read_status(str(p)) == {"hwm_mb": 2400.0, "rss_mb": 145.0, "swap_mb": 2140.0}


def test_read_status_missing_file_is_empty():
    assert read_status("/nonexistent/status") == {}


def test_grown_types_first_reading_is_largest():
    now = Counter({"dict": 50, "str": 90, "list": 10})
    assert grown_types(None, now, top=2) == [["str", 90, 90], ["dict", 50, 50]]


def test_grown_types_orders_by_growth_and_drops_shrunk():
    before = Counter({"dict": 100, "str": 500, "Packet": 2})
    now = Counter({"dict": 400, "str": 450, "Packet": 2002})
    assert grown_types(before, now) == [["Packet", 2002, 2000], ["dict", 400, 300]]


def test_reading_shape_and_delta_between_readings():
    probe = MemoryProbe()
    first = probe.reading()
    assert first["reading"] == 1
    assert first["objects"] > 0
    assert "error" not in first

    class _Leaky:
        pass

    held = [_Leaky() for _ in range(5000)]
    second = probe.reading()
    assert second["reading"] == 2
    names = {row[0]: row for row in second["grown_types"]}
    assert "_Leaky" in names and names["_Leaky"][2] >= 5000
    del held


def test_reading_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("gc view failed")

    monkeypatch.setattr(memory_probe, "type_counts", boom)
    out = MemoryProbe().reading()
    assert out["error"] == "RuntimeError"
    assert out["reading"] == 1


def test_tracemalloc_lines_when_asked(monkeypatch):
    import tracemalloc

    monkeypatch.setenv("TCE_TRACEMALLOC", "1")
    memory_probe.start_tracing_if_asked()
    try:
        probe = MemoryProbe()
        probe.reading()
        blob = [bytearray(1024) for _ in range(2000)]  # about 2 MB
        out = probe.reading()
        assert out["traced_mb"] >= 1
        assert any(row[2] >= 1 for row in out["top_lines"]), out["top_lines"]
        del blob
    finally:
        tracemalloc.stop()


def test_interval(monkeypatch):
    monkeypatch.delenv("TCE_MEMPROBE_SECONDS", raising=False)
    assert memory_probe.interval_seconds() == 3600
    monkeypatch.setenv("TCE_MEMPROBE_SECONDS", "0")
    assert memory_probe.interval_seconds() == 0
    monkeypatch.setenv("TCE_MEMPROBE_SECONDS", "junk")
    assert memory_probe.interval_seconds() == 3600
