"""HistoryStore: append (newest-first), cap, tolerant load, clear."""
from tsconverter.history import HistoryEntry, HistoryStore, MAX_ENTRIES


def _store(tmp_path):
    return HistoryStore(tmp_path / "history.json")


def test_add_is_newest_first_and_roundtrips(tmp_path):
    s = _store(tmp_path)
    s.add(HistoryEntry(timestamp="t1", src="a.ts", out="a.mp4", result="Done",
                       encoder="remux", duration=3.0, size=1234))
    s.add(HistoryEntry(timestamp="t2", src="b.ts", out="", result="Failed",
                       error="boom"))
    items = s.all()
    assert [e.src for e in items] == ["b.ts", "a.ts"]   # newest first
    assert items[1].encoder == "remux" and items[1].size == 1234
    assert items[0].result == "Failed" and items[0].error == "boom"


def test_cap_keeps_only_max_entries(tmp_path):
    s = _store(tmp_path)
    for i in range(MAX_ENTRIES + 25):
        s.add(HistoryEntry(timestamp=f"t{i}", src=f"{i}.ts", result="Done"))
    items = s.all()
    assert len(items) == MAX_ENTRIES
    assert items[0].src == f"{MAX_ENTRIES + 24}.ts"     # most recent retained


def test_clear_empties_store(tmp_path):
    s = _store(tmp_path)
    s.add(HistoryEntry(src="a.ts", result="Done"))
    s.clear()
    assert s.all() == []


def test_load_tolerates_garbage_file(tmp_path):
    p = tmp_path / "history.json"
    p.write_text("not json at all", encoding="utf-8")
    s = HistoryStore(p)
    assert s.all() == []           # no crash
    s.add(HistoryEntry(src="x.ts", result="Done"))
    assert len(s.all()) == 1


def test_from_dict_ignores_unknown_and_missing_keys():
    e = HistoryEntry.from_dict({"src": "a.ts", "bogus": 1})
    assert e.src == "a.ts" and e.result == "" and e.duration == 0.0
