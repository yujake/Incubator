# -*- coding: utf-8 -*-
"""缺陷 B：签了但没人收录（2026-11-05，真机 87）。

## 现场

`reports/f-proof-000000.md` 上有 `secretary:F` 的成立签、`b-proof-000000/2/3` 也已落盘，
而 `statements:000000` 仍是 `ek=heuristic / 正文=0 / reviewed=false` —— 没人登记。

盘上核过的根因：87 里 B 只被派过 1 次（`t-000027`，called_by=A，文献侧），D 从头没派
B 收录。教学里其实有那条（`specs/d.py`：「② 那一行写进你的报告之后派 B 入库」），
D 没走到 ⇒ 缺的不是"教"，是义务：签发之后没有任何东西把"这一份还没入库"摆到 B 面前。

## 这一笔补什么

与「V 打回后必须重送」（`v-resubmit@`，`t-000084/085` 那一形态）同形的一条义务：
`b-register@<命题号>@<被签正文的 sha>`，`expects="work"`，收口只有一条 ——
那一行出现正文 且 `reviewed=true`（逐份口径），或那一条被明确放弃（理由 + 时间）。

## 判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| a | 稿上有成立签、`statements` 无正文（走 V 的真入口签发） | 签发那一刻就出现义务项：键形 `b-register@<号>@<sha>`、`role=B`、`expects=work`、未终态，`detail` 点名稿路径 / 号 / 签的 sha |
| b | 收录完（正文 + `reviewed=true`） | 义务自动收口 `completed`，不靠 ack（ack 关不掉它） |
| c | 反真空：把义务生成那一步摘掉 | a 红（板上 0 条，而"还没入库"这个事实仍在） |
| d | 同一现场再加一条 V 打回 | 两条义务各一条、键前缀不同；既有的重送义务读数不受影响 |
| e | 明确不收录（`status=abandoned` + 可解析标记） | 义务作废 `expired`（不是 `completed`） |
| f | 再扫一遍 / 再落一次同 sha 的签 | 幂等：只有一条义务 |
| g | 三态：没有 store / `statements` 读不出来 / 命题不在册 | `checked=False`（不许折成"已经收录了"）与 `gap=True` 分开 |
"""
from __future__ import annotations

import json
import pathlib

from agentflow import conductor as CND
from agentflow import depsection as _DS
from agentflow import evidencebits as EB
from agentflow import secretary as SEC
from agentflow import statementabandon as SA
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow import vreceipts as VRC
from agentflow.agent_v import AgentV
from agentflow.store import Store
from agentflow.tools.conductor_tools import conductor_for

TS = "2026-11-05T02:50:58+08:00"
SID = "000001"
SID2 = "000002"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
CLEAN_REPLY = json.dumps({"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。",
                          "findings": []}, ensure_ascii=False)
FAULT_REPLY = json.dumps({
    "verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
    "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                  "detail": "第 2 步直接用了结论"}],
}, ensure_ascii=False)


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _ReviewSeam:
    """V 的审阅缝（只喂结论，不联网）。"""

    wired = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)

    def ask(self, prompt: str = "", **_kw) -> _Call:
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call


class _Seam:
    """秘书的缝：按 `note` 回预置 JSON。"""

    wired = True

    def __init__(self, answers: dict[str, list] | None = None) -> None:
        self.answers = {k: list(v) for k, v in (answers or {}).items()}

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, _Call]:
        kind = note.split(":", 1)[-1]
        queue = self.answers.get(kind) or [{}]
        doc = queue.pop(0) if len(queue) > 1 else queue[0]
        return dict(doc), _Call()


def _axis(answer: str, *, defect_step: int | None = None) -> dict:
    out = {"checked": True, "decision": answer, "reason": "夹具：照规则判",
           "basis": ["夹具"]}
    if defect_step is not None:
        out["defect_step"] = int(defect_step)
    return out


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    conductor_for(st)
    return st


def _manuscript(st: Store, sid: str) -> str:
    """写一份按号的证明稿（三列 `## 依赖` 表头不能省，空表就是声明）。"""
    rel = f"reports/f-proof-{sid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# F 的证明手稿\n\n"
                    f"- 计划：{sid} · 子目标：S3\n\n"
                    f"## 命题\n\n{FULL}\n\n## 证明\n\n{PROOF}\n\n"
                    + _DS.render_dependency_section([]), encoding="utf-8")
    return rel


def _put(st: Store, sid: str = SID, *, proof_text: str = "") -> dict:
    """87 现场那一行：在册、有命题、没有正文、`bits.reviewed=false`。"""
    row = {"stmt_id": sid, "origin": "own_result", "kind": "conjecture",
           "label": f"探针命题 {sid}", "statement_full": FULL, "statement_text": FULL,
           "proof_text": proof_text, "evidence_kind": "heuristic", "status": "active",
           "quote_verified": None,
           "quote_reason": "这一条还没有命题号 ⇒ 按最弱一档登记（V 签完之后再交一次会升档）",
           "created_at": TS, "created_by": "secretary-B",
           "bits": EB.bits_of(proof=True, proof_process=PROOF, kind="conjecture"),
           "proof_authors": ["F"]}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _agent_row(st: Store, *, role: str, status: str = "running",
               depth: int = 2, parent: str = "t-root") -> str:
    """落一条代理行（`kind` 空）：收件人 / 送审者 / 负责人用它。"""
    from agentflow.conductor import Conductor

    return Conductor._write_new_row(
        conductor_for(st), {
            "task_id": "", "role": role, "action": "", "called_by": "M",
            "parent_task_id": parent, "depth": depth,
            "input_key": f"@t:{role}:{TS}:{status}",
            "status": status, "outcome": "ok" if status == "done" else None,
            "refusal_reason": None, "instance": f"{role}#1", "detail": "夹具",
            "error": None, "started_at": TS,
            "ended_at": TS if status == "done" else None,
            "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        }, note="probe:agent")


def _verify_v(st: Store, sid: str, *, proof: str = PROOF, reply: str = CLEAN_REPLY,
              parent: str = "t-f1", axis: str = SEC.V_REPLY_CLEAN) -> dict:
    """走 V 的真入口：三转 clean（或一转打回）⇒ 秘书发签 / 落块 / 开义务。

    p247（2026-11-06）：轴只由秘书给 —— 要造"打回"，必须让秘书判
    `V_REPLY_FAULT`；只把 V 的回复写成「有毛病」而秘书判 clean 的那一拍，
    按新语义是签发（V 的判词只是陈述），不再是一条打回。
    """
    sec = SEC.Secretary("V", root=st.root, store=st,
                        seam=_Seam({"v_reply_defect": [
                                       _axis(axis,
                                             defect_step=(2 if axis == SEC.V_REPLY_FAULT
                                                          else None))],
                                    "sign_issuance": [_axis(SEC.SIGN_ISSUE)]}),
                        enable_model=True)
    agent = AgentV(st, workspace_root=st.root, llm=_ReviewSeam(reply), secretary=sec)
    rel = _manuscript(st, sid)
    with CND.calling_as("t-v1", "V", parent_task_id=parent, parent_role="F"):
        return agent.verify_proof(sid, proof_text=proof, proof_manuscript=rel)


def _register_items(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(VRC.REGISTER_PREFIX)]


def _resubmit_items(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(VRC.RESUBMIT_PREFIX)]


def _sign_row_of(st: Store, sid: str) -> dict:
    rows, problems = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert not problems, problems
    return dict(rows[-1])


# ====================================================================== a 义务出现
def test_a_a_signed_manuscript_without_a_body_opens_the_duty(tmp_path):
    """稿上有成立签、`statements` 无正文 ⇒ 签发那一刻就出现「必须收录」义务。"""
    st = _ws(tmp_path)
    _put(st)
    got = _verify_v(st, SID)
    assert got.get("checked") is True, got
    sign_row = _sign_row_of(st, SID)
    sha = str(sign_row["proof_sha256"])
    block = VS.manuscript_sign_reading(
        (pathlib.Path(st.root) / f"reports/f-proof-{SID}.md").read_text(encoding="utf-8"),
        manuscript_path=f"reports/f-proof-{SID}.md")
    assert block["signed"] is True, block

    items = _register_items(st)
    assert len(items) == 1, [r.get("input_key") for r in items]
    one = items[0]
    assert one["input_key"] == VRC.register_key(f"{SID}#p1", sha), one
    assert one["input_key"].endswith(sha), "键尾必须是被签正文的 sha"
    assert str(one.get("role")) == "B", one
    assert str(one.get("expects")) == "work", "收录是要交付的活，不是'知道了'"
    assert str(one.get("kind")) == "notice", one
    assert str(one.get("item_state")) != "done", one
    detail = str(one.get("detail") or "")
    assert f"reports/f-proof-{SID}.md" in detail, detail
    assert f"{SID}#p1" in detail, detail
    assert sha in detail, f"detail 没有点名签的 sha：{detail}"
    assert "收录" in detail, detail
    # 签发那一笔自己的读数：义务是在签发那一刻开出来的，不是收工时才发现。
    reg = ((got.get("sign_issuance") or {}).get("writeback") or {}).get("registration") or {}
    assert str(reg.get("state")) == "opened", reg
    # statements 那一行确实还没入库（义务不是凭空开的）。
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    assert not str(row.get("proof_text") or "").strip(), row
    gap = VRC.registration_gap(store=st, label=f"{SID}#p1")
    assert gap["checked"] is True and gap["gap"] is True, gap


# ====================================================================== b 自动收口
def test_b_registration_closes_the_duty_by_evidence_not_by_ack(tmp_path):
    """收录完（正文 + reviewed=true）⇒ 义务自动收口 `completed`；ack 关不掉它。"""
    st = _ws(tmp_path)
    _put(st)
    owner = _agent_row(st, role="B")            # 那一刻唯一的 B ⇒ 它接这条义务
    _verify_v(st, SID)
    one = _register_items(st)[0]
    assert str(one.get("parent_task_id")) == owner, one

    cond = conductor_for(st)
    acked = cond.ack_items([str(one["task_id"])], by_task_id=owner)
    assert not acked.get("acked"), acked
    assert str(_register_items(st)[0].get("item_state")) != "done", "ack 不许关掉收录义务"

    # 收录：正文进 statements + 按签认第 3 位（B 那一笔的最小形态）。
    rel = f"reports/f-proof-{SID}.md"
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    row["proof_text"] = PROOF
    bits, reading = VS.bits_after_sign(
        dict(row.get("bits") or {}), root=st.root, proof_text=PROOF,
        statement_id=SID, proof_no=1, kind=str(row.get("kind") or ""),
        manuscript_text=text, manuscript_path=rel, store=st)
    assert reading.get("applied") is True, reading
    row["bits"] = bits
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)

    got = VRC.backfill(store=st)
    rec = got["registration_reconcile"]
    assert rec["checked"] is True, rec
    # 收口只能由"盘上的事实"给出（回执、扫盘、对账三处都可能发现它已清）——
    # 但无论哪一处，`item_close` 必须是 `completed`，且 ack 关不掉它（上面已量）。
    closers = list(got["registration"].get("closed") or []) + \
        list(got["registration"].get("cleared") or []) + list(rec.get("closed") or [])
    assert str(one["task_id"]) in closers, (got["registration"], rec)
    closed = next(dict(r) for r in st.rows("tasks") if r["task_id"] == one["task_id"])
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "completed", closed


# ====================================================================== c 反真空
def test_c_without_the_generation_step_the_duty_never_appears(tmp_path, monkeypatch):
    """反真空：把义务生成那一步摘掉 ⇒ a 红（板上 0 条，而"还没入库"这个事实仍在）。"""
    calls: list[dict] = []

    def _no_open(**kwargs):
        calls.append(dict(kwargs))
        return {"checked": True, "state": "skipped", "key": "",
                "reason": "反真空：义务生成那一步被摘掉了"}

    monkeypatch.setattr(VRC, "ensure_registration", _no_open)
    st = _ws(tmp_path)
    _put(st)
    _verify_v(st, SID)
    assert _register_items(st) == [], [r.get("input_key") for r in _register_items(st)]
    assert calls, "连那一步都没被调到 ⇒ 这条反真空测的不是那个写口"
    # 而"这一份还没入库"这个事实仍然在（否则上面那条断言只是"什么都没发生"）。
    gap = VRC.registration_gap(store=st, label=f"{SID}#p1")
    assert gap["checked"] is True and gap["gap"] is True, gap
    sweep = VRC.sweep_registrations(store=st, root=st.root)
    assert sweep["checked"] is True and sweep["opened"] == [], sweep


# ====================================================================== d 重送不受影响
def test_d_the_resubmit_duty_is_untouched(tmp_path):
    """同一现场再加一条 V 打回 ⇒ 两条义务各一条、键前缀不同；重送读数一个字不动。"""
    st = _ws(tmp_path)
    _put(st)
    _put(st, SID2)
    # 送审者必须真的在 `tasks` 里：回执与「必须重送」义务的负责人都是它那一个台账号。
    submitter = _agent_row(st, role="F", status="done", parent="t-root")
    _verify_v(st, SID, parent=submitter)                     # 签了、没入库 ⇒ 收录义务
    # p247：打回只能由秘书判 fault 造出来；V 写「有毛病」只是陈述。
    _verify_v(st, SID2, reply=FAULT_REPLY, parent=submitter,
              axis=SEC.V_REPLY_FAULT)                        # 打回 ⇒ 重送义务
    regs = _register_items(st)
    subs = _resubmit_items(st)
    assert len(regs) == 1, [r.get("input_key") for r in regs]
    assert len(subs) == 1, [r.get("input_key") for r in subs]
    assert regs[0]["input_key"] != subs[0]["input_key"], (regs, subs)
    assert str(regs[0]["input_key"]).startswith(VRC.REGISTER_PREFIX), regs[0]
    assert str(subs[0]["input_key"]).startswith(VRC.RESUBMIT_PREFIX), subs[0]
    # 重送那一条的读数（`resubmit_digest` 与 `backfill` 的旧键）照旧。
    digest = VRC.resubmit_digest(st.root, st)
    assert digest["checked"] is True and digest["open"] == 1, digest
    got = VRC.backfill(store=st)
    assert got["resubmit_reconcile"]["checked"] is True, got["resubmit_reconcile"]
    assert len(_resubmit_items(st)) == 1, "补投把重送义务多开了一条"
    assert len(_register_items(st)) == 1, "补投把收录义务多开了一条"


# ====================================================================== e 明确不收录
def test_e_an_explicit_abandonment_expires_the_duty(tmp_path):
    """明确不收录（`status=abandoned` + 可解析标记）⇒ 义务作废 `expired`。"""
    st = _ws(tmp_path)
    _put(st)
    _verify_v(st, SID)
    one = _register_items(st)[0]
    # 2026-11-07（业主裁定）：放弃一条命题必须给结构化换号理由。
    # 这一档用 `difficulty`：把旧稿里可取之处拆成一条在册引理（`salvaged` 非空）。
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {
            "stmt_id": "000009", "origin": "own_result", "kind": "lemma",
            "label": "引理：旧稿里可取的那一步", "statement_full": FULL,
            "statement_text": FULL, "proof_text": "", "evidence_kind": "heuristic",
            "status": "active", "quote_verified": None, "quote_reason": "夹具：自产命题",
            "created_at": TS, "created_by": "test", "bits": {}})
    got = SA.apply_abandonment(st, statement_id=SID, reason="这一份稿不进册：重新做",
                               at="2026-11-05T03:00:00+08:00",
                               abandon_kind="difficulty",
                               abandon_basis="这一份稿不进册：依赖面补齐不了，重新做",
                               difficulty="V 要求的那条依赖拿不到；三条路都试过",
                               salvaged=[{"label": "引理：旧稿里可取的那一步",
                                          "stmt_id": "000009"}])
    assert got["checked"] is True and got["abandoned"] is True, got
    rec = VRC.reconcile_registrations(store=st, root=st.root)
    assert rec["checked"] is True, rec
    assert str(one["task_id"]) in rec["expired"], rec
    closed = next(dict(r) for r in st.rows("tasks") if r["task_id"] == one["task_id"])
    assert str(closed.get("item_state")) == "done", closed
    assert str(closed.get("item_close")) == "expired", closed
    # 判据那一侧：不再算"欠收录"。
    gap = VRC.registration_gap(store=st, label=f"{SID}#p1")
    assert gap["checked"] is True and gap["gap"] is False, gap
    assert gap["abandoned"] is True, gap


# ====================================================================== f 幂等
def test_f_the_duty_is_one_row_per_text(tmp_path):
    """再扫一遍 / 再判一次同 sha ⇒ 只有一条义务（幂等键不带收件人后缀）。"""
    st = _ws(tmp_path)
    _put(st)
    _verify_v(st, SID)
    first = _register_items(st)
    assert len(first) == 1, first
    VRC.backfill(store=st)
    VRC.sweep_registrations(store=st, root=st.root)
    again = _verify_v(st, SID)     # 同 sha 再判一次成立（新 v 号，签是 idempotent 的）
    assert again.get("checked") is True, again
    items = _register_items(st)
    assert len(items) == 1, [r.get("input_key") for r in items]
    assert items[0]["task_id"] == first[0]["task_id"], (items, first)
    digest = VRC.registration_digest(st.root, st)
    assert digest["checked"] is True and digest["open"] == 1, digest


# ====================================================================== g 三态
def test_g_gap_keeps_three_states(tmp_path):
    """三态：没有 store / `statements` 读不出来 ⇒ `checked=False`；命题不在册 ⇒ `gap=True`。"""
    st = _ws(tmp_path)
    no_store = VRC.registration_gap(store=None, label=f"{SID}#p1")
    assert no_store["checked"] is False and no_store["gap"] is None, no_store
    assert no_store["reason"], no_store

    class _Broken:
        root = str(st.root)

        def rows(self, table):
            raise OSError("表读不出来")

    broken = VRC.registration_gap(store=_Broken(), label=f"{SID}#p1")
    assert broken["checked"] is False, broken
    assert "读不出来" in broken["reason"], broken

    missing = VRC.registration_gap(store=st, label=f"{SID}#p1")
    assert missing["checked"] is True and missing["gap"] is True, missing
    assert "没有命题" in missing["reason"], missing

    # 未 reviewed 与没正文分开读：正文在、reviewed 不是 true ⇒ 仍是欠收录。
    _put(st, proof_text=PROOF)
    partial = VRC.registration_gap(store=st, label=f"{SID}#p1")
    assert partial["checked"] is True and partial["gap"] is True, partial
    assert partial["body"] is True and partial["reviewed"] is False, partial

    # 逐份口径：`#p2` 不借 `#p1` 的光。
    row = next(dict(r) for r in st.rows("statements") if r["stmt_id"] == SID)
    row["proofs"] = [{"proof_no": 2, "proof_text": PROOF}]
    row["bits"] = VS.bits_with_review(
        dict(row.get("bits") or {}), proof_no=1, proof_sha256=VR.text_sha(PROOF),
        kind=str(row.get("kind") or ""))
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    covered_p1 = VRC.registration_gap(store=st, label=f"{SID}#p1")
    assert covered_p1["gap"] is False, covered_p1
    uncovered_p2 = VRC.registration_gap(store=st, label=f"{SID}#p2")
    assert uncovered_p2["checked"] is True and uncovered_p2["gap"] is True, uncovered_p2
