"""独立验证：`agentflow rebuild` 会不会丢掉诊断字段（`_keys` / `_quote_check`）。

报告 §附录B 把这条列为"未实跑验证"。这里把它跑实：
rebuild 的事件折叠走 `schema.row_from_dict()`，而它只保留 dataclass 字段 ——
所以带下划线前缀的非 schema 诊断字段应当会丢。

结论无论正反都有用：证实 → 报告该缺口成立；证伪 → 报告不该写这条。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentflow.store import Store  # noqa: E402


def main() -> int:
    td = Path(tempfile.mkdtemp(prefix="agentflow-rebuild-"))
    try:
        st = Store(td / "ws")
        st.init()

        # 造两行：一行文献带 _keys，一行关系带 _quote_check
        with st.tx("literature", actor="probe") as tx:
            tx.upsert(
                "literature",
                {
                    "lit_id": "0000",
                    "title": "Probe paper",
                    "type": "J",
                    "summary": "",
                    "path": None,
                    "processed": True,
                    "source_request_ids": [],
                    "dedup_key": "doi:10.1/probe",
                    "doi": "10.1/probe",
                    "year": 2000,
                    "authors": [],
                    "venue": None,
                    "language": None,
                    "added_at": "2026-01-01T00:00:00+00:00",
                    "download": {},
                    "claimed_by": None,
                    "lease_until": None,
                    "mine_attempts": 0,
                    "last_mine_error": None,
                    "_keys": ["doi:10.1/probe", "title:probe paper|2000", "title:probe paper|*"],
                },
            )
        with st.tx("concepts", "relations", actor="probe") as tx:
            for cid, name in (("0000", "group"), ("0001", "abelian group")):
                tx.upsert("concepts", {
                    "concept_id": cid, "name": name, "definition": "d",
                    "related_concepts": ["0001"] if cid == "0000" else ["0000"],
                    "normalized_name": name, "aliases": [],
                    "definition_source_lit_id": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                })
            tx.upsert("relations", {
                "relation_id": "0000", "concept_ids": ["0000", "0001"],
                "description": "d", "lit_id": "0000",
                "page_range": {"start": 1, "end": 1, "label": "p. 1"},
                "quote": "An abelian group is a group.", "quote_normalized": "an abelian group is a group",
                "quote_verified": True, "statement": "d",
                "concept_group_key": "0000|0001", "dedup_key": "0000|0001::x",
                "status": "active", "duplicate_of": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "_quote_check": {"verified": True, "reason": "substring_match"},
            })

        def snapshot() -> dict:
            lit = json.loads((st.data / "literature.json").read_text(encoding="utf-8"))["rows"][0]
            rel = json.loads((st.data / "relations.json").read_text(encoding="utf-8"))["rows"][0]
            return {
                "lit._keys": lit.get("_keys"),
                "rel._quote_check": rel.get("_quote_check"),
            }

        before = snapshot()
        out = st.rebuild(backup=False)
        after = snapshot()

        print("=== rebuild 前 ===")
        print(f"  literature._keys      = {before['lit._keys']}")
        print(f"  relations._quote_check= {before['rel._quote_check']}")
        print(f"=== rebuild 后（applied={out['applied']}, skipped={out['skipped']}）===")
        print(f"  literature._keys      = {after['lit._keys']}")
        print(f"  relations._quote_check= {after['rel._quote_check']}")

        lost_keys = before["lit._keys"] is not None and after["lit._keys"] is None
        lost_qc = before["rel._quote_check"] is not None and after["rel._quote_check"] is None
        print()
        print(f"结论：_keys 丢失 = {lost_keys}；_quote_check 丢失 = {lost_qc}")

        # 顺带验证：丢了 _keys 之后，判重是否还能工作（它还有 dedup_key / doi 兜底）
        from agentflow import dedup as D

        lit_after = json.loads((st.data / "literature.json").read_text(encoding="utf-8"))["rows"]
        hit, key = D.find_existing_literature(lit_after, "完全不同标题", 1999, "https://doi.org/10.1/PROBE")
        print(f"判重是否仍能命中（靠 doi 兜底）：hit={hit is not None} key={key}")
        return 0
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
