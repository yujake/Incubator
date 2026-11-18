# -*- coding: utf-8 -*-
"""STALLFIX ②：「有毛病」的判词不许零送达 —— V 稿的写入门槛改成「这一行是对稿的否定判定」。

## 真机事故现场（`agentflow/temp/inv8/REPORT.md` §3.3 / §6 根因 3）

```text
台账行 46857051…#u-000001（19:39:24）  行上 verdict=有毛病（2 条引用）  秘书轴 axis=clean
台账行 46857051…#u-000005（19:53:30）  行上 verdict=有毛病（2 条引用）  秘书轴 axis=clean
两行：无 V 稿、无 v-review@、无 v-wash@ ⇒ F 永远不知道那两条
```

原因只有一行代码：`AgentV._v_review_should_be_written()` 只看 `secretary_judge.axis`，
而上面两行的「有毛病」是依赖面审计（`merge_dependency_audit`，`agent_v/core.py:2586`）
把 clean 折出来的。"台账上的结论"与"落不落 V 稿"用了两个不同的判据。

## 本文件钉什么

| # | 判据 | 读数 |
|---|---|---|
| e | `verdict=有毛病` 而 `axis=clean`（在册 / 未在册两支）⇒ 也写 V 稿 + 投 `v-review@` | 磁盘上一份 md、索引一行、板项一条 |
| f | 负控：axis=clean 且 verdict 干净（成立）⇒ 不写 V 稿 | 零份 md |
| g | 反真空：把判据打回"只认 axis" ⇒ e 必红 | 零份 md |

口径边界：只改"这一行是不是对稿的否定判定"这一个写入闸，不改台账行的 verdict、
不改秘书轴、不放宽任何一条签/打回判据。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from _proof_manuscript_fixture import write_proof_manuscript   # noqa: E402
from agentflow import conductor as CND                        # noqa: E402
from agentflow import evidencebits as EB                       # noqa: E402
from agentflow import secretary as SEC                         # noqa: E402
from agentflow import verifications as VR                      # noqa: E402
from agentflow import vreviews as VRV                          # noqa: E402
from agentflow.agent_v import AgentV                           # noqa: E402
from agentflow.store import Store                              # noqa: E402

TS = "2026-11-18T19:39:24+08:00"
SID = "000007"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
REL = f"reports/f-proof-{SID}.md"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"

CLEAN_REPLY = json.dumps(
    {"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。", "findings": []},
    ensure_ascii=False)

#: 依赖面审计折出来的那一条（真机 u-000001 / u-000005 的两条引用同形）。
DEPENDENCY_AUDIT = {
    "checked": True,
    "ok": False,
    "findings": [
        {"level": "error", "step": 3, "kind": "citation_level_unreadable",
         "detail": ("`stmt:000011`（在哪一步：证明正文第 3 步）· 类别：等级读不出来"
                    "（判不了）· 怎么改：先把这一条命题的证明落成一份手稿，再引它")},
    ],
    "defect_step": 3,
    "why": "依赖面：第 3 步引的 `stmt:000011` 在盘上没有手稿 ⇒ 读不到正文，也读不到签",
}


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store, *, proof_text: str = PROOF) -> dict:
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": FULL,
        "statement_text": "弦长函数不是常值", "proof_text": proof_text,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题，没有外部引文要比对",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=proof_text, kind="theorem"),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    write_proof_manuscript(store.root, SID, proof_text, statement_full=FULL)
    return row


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _ReviewSeam:
    wired = True

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)

    def ask(self, prompt: str = "", **_kw) -> _Call:
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        call = _Call()
        call.text = text
        return call


class _Seam:
    wired = True

    def __init__(self, answers: dict[str, list] | None = None) -> None:
        self.answers = {k: list(v) for k, v in (answers or {}).items()}

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict | None, _Call]:
        queue = self.answers.get(note.split(":", 1)[-1]) or [{}]
        doc = queue.pop(0) if len(queue) > 1 else queue[0]
        return dict(doc), _Call()


def _axis(answer: str) -> dict:
    return {"checked": True, "decision": answer, "reason": "夹具：照规则判",
            "basis": ["夹具"]}


def _agent(st: Store, seam: _Seam) -> AgentV:
    secretary = SEC.Secretary("V", root=st.root, store=st, seam=seam, enable_model=True)
    return AgentV(st, workspace_root=st.root, llm=_ReviewSeam([CLEAN_REPLY]),
                  secretary=secretary)


def _submit(role: str = "F"):
    return CND.calling_as("t-v-000001", "V",
                          parent_task_id=f"t-{role.lower()}-000001", parent_role=role)


class _BoardDouble:
    def __init__(self) -> None:
        self.opened: list[dict] = []

    def open_item(self, *args, **kwargs):
        item_id = f"i-{len(self.opened) + 1:06d}"
        self.opened.append({"item_id": item_id, "args": args, "kwargs": kwargs})
        return item_id

    def set_item_detail(self, item_id: str, detail: str):
        return (True, "")

    def _board_rows(self) -> list:
        return [{"task_id": o["item_id"],
                 "input_key": str(o["kwargs"].get("input_key") or "")}
                for o in self.opened]


def _folded_fault(monkeypatch) -> None:
    """依赖面审计折出 fault：秘书轴仍是 clean（真机 u-000001 / u-000005 的形态）。"""
    monkeypatch.setattr(
        AgentV, "_dependency_audit",
        lambda self, text, cited=None: {**DEPENDENCY_AUDIT,
                                        "findings": [dict(f) for f in
                                                     DEPENDENCY_AUDIT["findings"]]})


def _reviews(root) -> list[pathlib.Path]:
    return sorted((pathlib.Path(root) / VRV.REVIEWS_DIR).glob(f"{VRV.PREFIX}*.md"))


def _index(root) -> list[dict]:
    path = VRV.reviews_index_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ================================================================== e：在册那一支

def test_e_a_clean_axis_with_a_folded_fault_writes_and_delivers_a_review(
        tmp_path, monkeypatch):
    """e（在册）：行上 verdict=有毛病、秘书轴 clean ⇒ 也落 V 稿并投 v-review@。"""
    st = _ws(tmp_path)
    _put(st)
    _folded_fault(monkeypatch)
    board = _BoardDouble()
    monkeypatch.setattr(VRV, "_conductor_for", lambda _store: board)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})

    with _submit("F"):
        got = _agent(st, seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    # 改前的现场：轴 clean（所以不落稿），而台账行是「有毛病」。
    assert got["secretary_judge"]["axis"] == "clean", got["secretary_judge"]
    assert got["verdict"] == "有毛病", got["verdict"]
    assert int(got["unresolved_errors"] or 0) == 1, got["unresolved_errors"]

    files = _reviews(st.root)
    assert len(files) == 1, (
        "台账行判了「有毛病」，盘上却一份 V 稿都没有 —— 这正是 u-000001 / u-000005 的零送达",
        files)
    text = files[0].read_text(encoding="utf-8")
    assert "有毛病" in text and "stmt:000011" in text, text
    index = _index(st.root)
    assert len(index) == 1, index
    assert index[0]["verdict"] == "有毛病", index
    assert index[0]["ledger"] == f"verifications/{SID}.jsonl", index
    assert index[0]["verification_id"].startswith("v-"), index

    assert len(board.opened) == 1, board.opened
    item = board.opened[0]["kwargs"]
    assert item["kind"] == "notice" and item.get("expects") == "ack", item
    assert str(item["input_key"]).startswith(VRV.REVIEW_PREFIX), item
    assert item["role"] == "F" and item["parent_task_id"] == "t-f-000001", item


# ================================================================== e：未在册那一支

def test_e_unregistered_clean_axis_with_a_folded_fault_also_writes_a_review(
        tmp_path, monkeypatch):
    """e（未在册）：同一判据，台账锚点走 pending 路径。"""
    st = _ws(tmp_path)
    _put(st)
    _folded_fault(monkeypatch)
    board = _BoardDouble()
    monkeypatch.setattr(VRV, "_conductor_for", lambda _store: board)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})

    with _submit("F"):
        got = _agent(st, seam).verify_proof("", proof_text=PROOF, proof_manuscript=REL)

    assert got["secretary_judge"]["axis"] == "clean", got["secretary_judge"]
    assert got["verdict"] == "有毛病", got["verdict"]
    files = _reviews(st.root)
    assert len(files) == 1, ("未在册那一支同样零送达", files)
    index = _index(st.root)
    assert len(index) == 1, index
    assert index[0]["ledger"].startswith("verifications/pending/"), index
    assert index[0]["verification_id"].startswith("u-"), index
    assert len(board.opened) == 1, board.opened
    assert str(board.opened[0]["kwargs"]["input_key"]).startswith(VRV.REVIEW_PREFIX)


# ================================================================== f：负控

def test_f_a_clean_verdict_writes_no_review(tmp_path):
    """f 负控：axis=clean 且 verdict 干净（成立）⇒ 不写 V 稿（门槛没被放宽成"总是写"）。"""
    st = _ws(tmp_path)
    _put(st)
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})

    with _submit("F"):
        got = _agent(st, seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    assert got["secretary_judge"]["axis"] == "clean", got["secretary_judge"]
    assert got["verdict"] == "成立", got["verdict"]
    assert _reviews(st.root) == [], _reviews(st.root)
    assert _index(st.root) == [], _index(st.root)


# ================================================================== g：反真空

def test_g_stubbing_the_gate_back_to_axis_only_makes_e_red(tmp_path, monkeypatch):
    """g：把写入判据打回"只认秘书轴" ⇒ e 必红（零份 V 稿）。"""
    st = _ws(tmp_path)
    _put(st)
    _folded_fault(monkeypatch)
    monkeypatch.setattr(
        AgentV, "_v_review_should_be_written",
        lambda self, judgment, row=None: str((judgment or {}).get("axis") or "") == "fault")
    seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)]})

    with _submit("F"):
        got = _agent(st, seam).verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    assert got["verdict"] == "有毛病", got["verdict"]
    assert got["secretary_judge"]["axis"] == "clean", got["secretary_judge"]
    assert _reviews(st.root) == [], (
        "把判据打回只认 axis，V 稿却还是落了 —— e 这一条判据是真空的")


if __name__ == "__main__":  # pragma: no cover - 手动跑
    raise SystemExit(pytest.main([__file__, "-q"]))
