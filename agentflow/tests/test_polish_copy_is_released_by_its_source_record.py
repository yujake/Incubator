# -*- coding: utf-8 -*-
"""2026-11-13 业主裁定：`b-proof` 的「优化副本」按来源记录放行，不再靠稿头命题号。

## 业主口径（逐字）

> 「不是从 E 和 F 侧进（随 D 进）的，且不是 B 做优化表述的（这个命题已保证在台账上
> 肯定审过），其它手稿录入。」

Z2 之后「稿里没有命题号，任何稿里都没有命题号」⇒ 收方（B 的按稿收录）不能再靠
`head_statement_id` 认「这是优化副本」。改成认 `open_polish_copy` 写下的事实记录：

```
tasks.artifacts 里一枚 mss:<新稿号>#kind=polish#source=<源稿号>#path=<副本路径>#at=<时刻>
```

记录是"谁复制了谁"（事实），不是判断；不加新表、不加新列。

## 判据

| # | 判据 | 用例 |
|---|---|---|
| a | 复制成功 ⇒ 那一行 task 的 `artifacts` 里有来源记录（`kind=polish`、`source=<源稿号>`、`path=<副本>`）；`polish_source_reading` 认得出；`_manuscript_form_refusal` 对它放行（不判、0 次模型、台账不新增） | `test_a_*` |
| b | 反真空：把那条记录从 `artifacts` 里拿掉 ⇒ 它又落回形态闸（判不过 ⇒ 受控拒、台账留一行） | `test_b_*` |
| c | 记录是事实：源稿号是源、副本路径是副本；源稿一个字节没动，记录不是判断（没有模型调用） | `test_c_*` |
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import conductor as CND
from agentflow import manuscriptids as MID
from agentflow import manuscriptform as MF
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

import _credential_fixture as CF
import conftest

SID = "000005"
#: 源稿（F）的稿号：刻意与 B 的稿号段不同 —— "source" 那一格必须是源稿号。
MID_F = "000777"
REL_F = f"reports/f-proof-{MID_F}.md"
BODY = "由定义直接得到：任取 x ∈ X，按定义展开即得。"
SIGN_LINE = ("- V 签：已签=true；判词=成立；连续=3/3；正文sha={sha}；"
             "时间=2026-11-02T10:00:00+08:00；签名者=V；"
             "台账=verifications/000001.jsonl#v-000003；命题号=stmt:000001；手稿号=" + MID_F)

MANUSCRIPT = f"""# F 的证明手稿：夹具命题

{SIGN_LINE.format(sha="__SHA__")}
- 依赖面洗稿：已洗=true；洗的人=secretary:F；补写=无

## 命题

夹具命题。

## 证明

{BODY}

## 依赖

| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |
|---|---|---|
（这一份证明没有引用任何在册命题 —— 空表就是声明。）
"""

TS = "2026-11-13T10:00:00+08:00"


class _BadFormSeam:
    """秘书模型缝的替身：形态那一问判「不是命题」，其余照旧。"""

    class _Call:
        ok = True
        problem = ""
        detail = ""
        text = ""
        model = "fake"
        prompt_version = "t"
        prompt_sha256 = "0" * 64

    def __init__(self) -> None:
        self.form_calls: list[str] = []

    def ask_json(self, prompt, *, system="", task_id="", note=""):
        n = str(note or "")
        if n.endswith("secretary:proposition_form"):
            self.form_calls.append(str(prompt))
            return ({"well_formed": False, "conditions": "", "conclusion": "",
                     "problems": ["这是修订说明，不是命题"], "decision": "不是命题"},
                    self._Call())
        return ({"decision": "different", "canonical_name": "夹具", "same_as": "",
                 "route": "", "condition": "夹具", "conclusion": "夹具",
                 "reason": "夹具", "basis": ["夹具"]}, self._Call())


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    conftest.seed_statement_row(st, stmt_id=SID, statement_full="夹具命题。",
                                kind="conjecture")
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", S.Task(
            task_id="t-000001", role="B", action="run", called_by="user",
            status="running", input_key="B.run", detail="夹具：B 的优化任务行",
            started_at=TS).to_dict())
    return st


def _signed_source(st: Store, *, body: str = BODY) -> str:
    """写一份「已拿签」的 F 稿（签块 + 颁发表两份都在），返回它的路径。"""
    sha = PR.proof_sha(body)
    text = MANUSCRIPT.replace("__SHA__", sha).replace(BODY, body)
    (pathlib.Path(st.root) / REL_F).write_text(text, encoding="utf-8")
    CF.issue_credential(st.root, proof_text=body, statement_id=SID,
                        manuscript=REL_F, artifact_path=REL_F)
    return REL_F


def _b(st: Store, seam: _BadFormSeam) -> AgentB:
    sec = SEC.Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    return AgentB(st, extractor=None, extract_text=None, config={}, secretary=sec)


def _copy(st: Store) -> dict:
    """在 B 自己的任务上下文里开一份优化副本（记录要落到那一行 task 上）。"""
    with CND.calling_as("t-000001", "B"):
        return _b(st, _BadFormSeam()).open_polish_copy(statement_id=SID)


def _reading(statement: str = "夹具命题。") -> dict:
    """一份"没有稿头命题号"的稿读数（Z2 之后所有新稿都是这个形状）。"""
    return {"cells": {"statement_full": {"outcome": "present", "value": statement}},
            "head_statement_id": "", "declared_kind": "conjecture"}


def _artifacts(st: Store) -> list[str]:
    row = next(dict(r) for r in st.rows("tasks")
               if str(r.get("task_id")) == "t-000001")
    return list(row.get("artifacts") or ())


# ---------------------------------------------------------------- a 记录 ⇒ 放行
def test_a_the_polish_source_record_releases_the_copy(tmp_path) -> None:
    """a：复制成功 ⇒ 记一条来源；收方按记录放行（不判、0 调用、台账不新增）。"""
    st = _store(tmp_path)
    _signed_source(st)
    got = _copy(st)

    assert got.get("ok") is True, got
    record = dict(got.get("polish_source") or {})
    assert record.get("recorded") is True, record
    token = str(record.get("token") or "")
    assert token.startswith("mss:"), token
    assert "kind=polish" in token, token
    assert f"source={MID_F}" in token, token
    assert token in _artifacts(st), _artifacts(st)

    from agentflow.agent_b.open_polish_copy import polish_source_reading

    reading = polish_source_reading(st, manuscript=str(got.get("path") or ""))
    assert reading.get("checked") is True and reading.get("found") is True, reading
    assert reading.get("source_manuscript_id") == MID_F, reading

    seam = _BadFormSeam()
    b = _b(st, seam)
    rows_before = len(SEC.proposition_form_rows(st.root))
    refusal, read = b._manuscript_form_refusal(
        reading=_reading(), family="b-proof", rel=str(got.get("path") or ""))
    assert refusal == {}, refusal
    assert read.get("released") is True, read
    assert read.get("release_basis") == "polish_source", read
    assert read.get("source_manuscript_id") == MID_F, read
    assert read.get("model_calls") == 0 and read.get("ledger_appended") is False, read
    assert seam.form_calls == [], "按来源记录放行却问了形态闸"
    assert len(SEC.proposition_form_rows(st.root)) == rows_before, SEC.proposition_form_rows(st.root)


# ---------------------------------------------------------------- b 反真空
def test_b_removing_the_record_puts_it_back_under_the_gate(tmp_path) -> None:
    """b：把记录拿掉 ⇒ 同一份稿又落回形态闸（判不过 ⇒ 受控拒）。"""
    st = _store(tmp_path)
    _signed_source(st)
    got = _copy(st)
    rel = str(got.get("path") or "")
    assert got.get("ok") is True, got

    with st.tx("tasks", actor="probe") as tx:
        cur = tx.find("tasks", task_id="t-000001")
        cur["artifacts"] = [a for a in (cur.get("artifacts") or ())
                            if "kind=polish" not in str(a)]
        tx.upsert("tasks", cur, note="probe:drop-polish-record")
    assert not [a for a in _artifacts(st) if "kind=polish" in str(a)], _artifacts(st)

    from agentflow.agent_b.open_polish_copy import polish_source_reading

    read_rec = polish_source_reading(st, manuscript=rel)
    assert read_rec.get("checked") is True and read_rec.get("found") is False, read_rec

    seam = _BadFormSeam()
    b = _b(st, seam)
    refusal, read = b._manuscript_form_refusal(
        reading=_reading(), family="b-proof", rel=rel)
    assert refusal, (
        "把来源记录拿掉之后仍然放行 ⇒ a 的绿证明不了「记录」在承重", read)
    assert str(refusal.get("refused")) == "proposition_form_refused", refusal
    assert seam.form_calls, "落回形态闸却没有问模型（判据没跑）"
    assert read.get("judged") is True, read


# ---------------------------------------------------------------- c 记录是事实
def test_c_the_record_is_a_fact_not_a_judgement(tmp_path) -> None:
    """c：source 是源稿号、path 是副本；源稿一个字节没动，记录本身不花模型。"""
    st = _store(tmp_path)
    src = _signed_source(st)
    before = (pathlib.Path(st.root) / src).read_bytes()
    got = _copy(st)
    after = (pathlib.Path(st.root) / src).read_bytes()
    assert before == after, "开优化副本动了源稿"

    record = dict(got.get("polish_source") or {})
    token = str(record.get("token") or "")
    copy_mid = str(got.get("manuscript_id") or "")
    copy_rel = str(got.get("path") or "")
    assert copy_rel == MID.canonical_rel(copy_mid, family="b-proof"), (copy_rel, copy_mid)
    assert f"source={MID_F}" in token and MID_F != copy_mid, (token, copy_mid)
    assert f"path={copy_rel}" in token, token

    # 记录读得回、且不需要任何模型调用（它只是 artifacts 里的一行字）。
    from agentflow.agent_b.open_polish_copy import polish_source_reading

    reading = polish_source_reading(st, manuscript=copy_rel)
    assert reading.get("found") is True and reading.get("token") == token, reading
    assert not MF.formal_shape_problem((pathlib.Path(st.root) / copy_rel).read_text(
        encoding="utf-8"))[0], "副本不是一份正式手稿形状"
    assert VS.SIGN_MARK not in (pathlib.Path(st.root) / copy_rel).read_text(
        encoding="utf-8"), "副本里的签没清"
