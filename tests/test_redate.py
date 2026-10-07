from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.parquet as pq
from chrono_harness import Event, EventLog, Layout

from canopy_news.documents import current_inserts
from canopy_news.redate import reconcile


def _ins(unit, valid, ingest, **attrs):
    return Event.make(corpus="sr-media", kind="insert", unit_id=unit, valid_time=valid,
                      ingest_time=ingest, content_sha256="a" * 64, pass_id="p", attrs=attrs)


def test_current_inserts_takes_the_latest_recorded_insert(tmp_path):
    log = EventLog(Layout(tmp_path).ensure().log)
    old = _ins("u1", datetime(2024, 11, 25, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    fix = _ins("u1", datetime(2024, 10, 7, tzinfo=UTC), datetime(2026, 10, 4, tzinfo=UTC),
               corrects=old.event_id)
    other = _ins("u2", datetime(2024, 12, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    log.append([old, other], shard="a")
    log.append([fix], shard="b")
    cur = {e.unit_id: e for e in current_inserts(log)}
    assert cur["u1"].event_id == fix.event_id and cur["u2"].event_id == other.event_id


def test_reconcile_remaps_drops_and_never_duplicates(tmp_path):
    pq.write_table(pa.table({"event_id": ["old", "keep", "gone"], "x": [1, 2, 3]}),
                   tmp_path / "part-a.parquet")
    pq.write_table(pa.table({"event_id": ["new"], "x": [9]}), tmp_path / "part-b.parquet")
    rep = reconcile(tmp_path, keep={"new", "keep"}, remap={"old": "new"})
    files = list(tmp_path.glob("part-*.parquet"))
    rows = sorted(pq.read_table(files[0]).to_pylist(), key=lambda r: r["event_id"])
    assert len(files) == 1 and [r["event_id"] for r in rows] == ["keep", "new"]
    assert rows[1]["x"] == 1                       # the remapped row wins over a stray copy
    assert rep == {"rows": 2, "remapped": 1, "dropped": 2}
