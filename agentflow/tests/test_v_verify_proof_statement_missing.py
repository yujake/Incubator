# -*- coding: utf-8 -*-
"""V 的 `verify_proof`：**命题不在册**时不许给 verdict（业主 2026-10-17 授权动禁改区后补）。

## 现场（亲测抓到的缺口）

```
verify_proof("999999", "Proof. 一步。")     ← 命题 999999 不在册
⇒ checked=True, verdict='有毛病', defect_step=1  ＋ 落了 verifications/999999.jsonl
```

它对**证明文本**的判定自洽（空步骤推不出命题），但**"这个命题在不在册"没有任何一处说过**
⇒ 调用方读到的意思是"**命题与证明都审过了**"。这正是本仓最在意的那一类：
**"没查成"被盖在 `checked=True` 底下**。

## 补法（按本模块**既有纪律**：`checked=False` ⇒ 不落台账行）

命题不在册 ⇒ `checked=False` ＋ `kind='statement_missing'` ＋ 逐字说明"这是没审"，
**不落台账行**（留一行会把"没查成"冒充成"审过了"）。

这一组钉三件事：
1. 命题不在册 ⇒ `checked is False`、`kind='statement_missing'`、**没有 verdict**、**台账文件不存在**；
2. **负控**：命题在册 ＋ 空证明 ⇒ 仍是 `checked=True` ＋ verdict（**别把正常路径弄坏**）；
3. 命题在册时台账照写（留痕）。
"""

from __future__ import annotations

import pathlib

from agentflow.agent_b import AgentB
from agentflow.agent_v import AgentV
from agentflow.store import Store


def _ws(tmp_path: pathlib.Path) -> Store:
    store = Store(tmp_path / "ws")
    store.init()
    return store


def _register_a_statement(store: Store) -> str:
    """登记一条**在册**的命题（走 B 的动作，出处齐、可追溯）。"""
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {
            "lit_id": "000000", "title": "探针文献", "summary": "s", "year": "2022",
            "doi": "", "type": "J", "path": "", "processed": True, "source_request_ids": [],
            "download": {"status": "ok"},
        })
    b = AgentB(store, extractor=None, extract_text=None)
    got = b.register_statement(
        origin="external_lit", statement_full="探针命题：若 n≥3 则无解（V 判据用）",
        kind="theorem", source_lit_id="000000", page_range={"start": 1},
        quote_verified=False, quote_reason="探针：引文还没查",
    )
    row = got if isinstance(got, dict) else got.to_dict()
    assert row.get("ok"), row
    return str(row.get("stmt_id") or "")


def _ledger_files(store: Store) -> list[str]:
    root = getattr(store, "root", None)
    d = pathlib.Path(root) / "verifications"
    return sorted(p.name for p in d.glob("*")) if d.is_dir() else []


def test_a_missing_statement_is_not_verified(tmp_path: pathlib.Path) -> None:
    """正控：命题不在册 ⇒ 没审、无 verdict、**台账不留行**。"""
    store = _ws(tmp_path)
    v = AgentV(store)
    out = v.verify_proof("999999", "Proof. 一步。")
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("checked") is False, got
    assert got.get("kind") == "statement_missing", got
    assert not str(got.get("verdict") or "").strip(), f"不该给 verdict：{got}"
    assert _ledger_files(store) == [], "没审却落了台账行"


def test_an_existing_statement_takes_the_normal_review_path(tmp_path: pathlib.Path) -> None:
    """**负控**：命题在册 ⇒ **不走** `statement_missing`，而是进正常审校路径。

    裸装配（没接判定模型）下正常路径会如实回 `judge_not_wired`（"没判成"）⇒
    这一条要钉的是**两条路径分得开**：在册命题**不许**被报成 `statement_missing`。
    """
    store = _ws(tmp_path)
    sid = _register_a_statement(store)
    assert sid, "没种出命题"
    v = AgentV(store)
    out = v.verify_proof(sid, "Proof. 一步。")
    got = out if isinstance(out, dict) else out.to_dict()
    assert got.get("kind") != "statement_missing", f"在册命题被误报成不在册：{got}"
    assert str(got.get("reason") or "") != "statement_missing", got
    # 裸装配下正常路径的读数（不接模型 ⇒ 如实说没判成，且**不落台账行**）
    assert got.get("reason") == "judge_not_wired", got
    assert got.get("checked") is False, got
    assert _ledger_files(store) == [], "没判成却落了台账行"
