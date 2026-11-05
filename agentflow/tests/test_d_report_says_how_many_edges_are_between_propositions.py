# -*- coding: utf-8 -*-
"""D 的交接口执必须说清"依赖边 N 条（其中命题→命题 M 条）"（缺陷 1c 的 D 半边）。

## 现场（`temp/dep_probe/REPORT-dependency-surface.md` 第三节 B 表）

盘上五个工作区的 `dependencies` 一共 3 行，`source_stmt_id` 非空 0 行 ——
全是文献来的边。改前 D 的报告只有一列「依赖边 0/1/3」，读者看不出"这条定理在依赖
图上有没有上游"，也看不出"依赖面建起来了"与"只有文献边"的区别。

## 口径

- 那一列拆成两个数：`全部 / 其中命题→命题`（台账口径：`used_by="stmt:<号>[#pN]"`、
  `source_stmt_id` 非空才算命题→命题）；
- 合计写一行逐字 `依赖边 N 条（其中命题→命题 M 条）`；
- 三态：台账读不出来 ⇒ 写「未读到」，不写 0（没查成不是零依赖）。

判据逐条钉住这三件事，包括反真空（把两个数并回一个好读的数 ⇒ 第一条红）。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import schema as S
from agentflow.agent_d.write_report import _WriteReport
from agentflow.store import Store

TS = "2026-11-05T10:00:00+08:00"
SID = "000000"


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _ws(root: pathlib.Path, deps: list[dict]) -> pathlib.Path:
    root = pathlib.Path(root)
    Store(root).init(force=True)
    _dump(root / "data" / str(S.TABLES["dependencies"]["file"]),
          {"schema_version": 2, "rows": deps})
    return root


def _dep(no: int, *, used_by: str, lit: str = "", stmt: str = "") -> dict:
    return {
        "dep_id": f"{no:06d}", "used_by": used_by, "path_group": 1,
        "kind": "theorem", "label": f"依赖 {no}", "status": "closed",
        "source_stmt_id": stmt, "source_lit_id": lit,
        "source_experiment_id": "", "source_doc_id": "",
        "created_at": TS, "created_by": "test",
    }


def _section_text(lines: list[str]) -> str:
    return "\n".join(lines)


def _delivery() -> dict:
    return {
        "checked": True, "rows": 1, "delivered": 1,
        "results": [{"statement_id": SID, "ok": True,
                     "manuscript_source": f"reports/f-proof-{SID}.md",
                     "manuscript_washed": True, "kind": "theorem", "deps_written": 3}],
        "addressed": [],
    }


def _render(store: Store) -> str:
    """只跑那一节的渲染（不写整份报告）：`_delivery_section` 只用到 `self.store`。"""
    obj = _WriteReport.__new__(_WriteReport)
    obj.store = store
    return _section_text(obj._delivery_section(_delivery()))


def test_the_receipt_splits_total_edges_from_statement_to_statement_edges(tmp_path):
    """正控：1 条文献边 + 2 条命题→命题边 ⇒ 「依赖边 3 条（其中命题→命题 2 条）」。"""
    root = _ws(tmp_path / "ws", [
        _dep(0, used_by=f"stmt:{SID}", lit="000042"),
        _dep(1, used_by=f"stmt:{SID}", stmt="000001"),
        _dep(2, used_by=f"stmt:{SID}#p2", stmt="000002"),
    ])
    text = _render(Store(root))
    assert "依赖边 3 条（其中命题→命题 2 条）" in text, text
    # 同一份读数在逐行那一格里也分得开（不是只在合计行里）。
    assert f"| stmt:{SID} | 收下 | 3 / 2 |" in text, text


def test_the_multi_proof_tail_counts_once_per_proposition(tmp_path):
    """`used_by` 的 `#pN` 尾巴：`stmt:000000#p2` 与 `stmt:000000` 是同一条命题的边。"""
    root = _ws(tmp_path / "ws", [
        _dep(0, used_by=f"stmt:{SID}#p2", stmt="000001"),
        _dep(1, used_by=f"stmt:{SID}#p3", stmt="000002"),
    ])
    text = _render(Store(root))
    assert "依赖边 2 条（其中命题→命题 2 条）" in text, text


def test_an_unreadable_ledger_says_unread_not_zero(tmp_path):
    """三态：台账读不出来 ⇒ 「未读到」，不是「0 条边」。"""
    root = _ws(tmp_path / "ws", [])
    store = Store(root)
    real = store.rows

    def _boom(table, *a, **kw):
        if table == "dependencies":
            raise RuntimeError("半截表")
        return real(table, *a, **kw)

    store.rows = _boom  # type: ignore[assignment]
    text = _render(store)
    assert "依赖边：未读到" in text, text
    assert f"| stmt:{SID} | 收下 | 未读到 |" in text, text
    assert "依赖边 0 条" not in text, "读不到被折成 0 了"
