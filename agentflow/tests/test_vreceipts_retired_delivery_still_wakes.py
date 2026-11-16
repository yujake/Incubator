# -*- coding: utf-8 -*-
"""判据：V 回执的投递层退场之后，「V 判有毛病 ⇒ 送审者仍能收到」这条链还在。

业主 2026-11-16 裁定逐字：「vreceipts 退场」。退场的理由是一条被推翻的诊断：

    旧诊断：「投递发生在收件人下一次起跑那一刻 ⇒ 收件人不醒，回执就不存在」。
    核实（业主逐字）：「怎么可能收件人不醒，难道不是任何一条消息或计时器返回都会唤醒吗
    （来消息就是兜底计时器返回）？」

于是 `vreceipts.py`（outbox 意图 → 开板项 → 收工前补投）整层删除；判词送达只剩既有的
板项路。这一份钉四件事（每条都能单独红）：

| # | 它要证明的事 | 它能怎么红 |
|---|---|---|
| a | `agentflow.vreceipts` 这个模块已经不在（不是"改名了但 import 还能进"） | 谁把模块加回来（哪怕只是空壳）⇒ 当场红 |
| b | V 判有毛病 ⇒ 送审者名下出现 V 的判词项（`v-review@` notice），且它会被渲染进送审者的下一步（`board_digest`） | 把 `vreviews.deliver_review` 换成空转 ⇒ 板上没有这一项 |
| c | 同一现场还开着一条 `v-resubmit@<命题>@<sha>` 工作项（重送义务）；拿到干净的「成立」⇒ 收口 | 退场时把义务一起删 ⇒ 这条红 |
| d | 反真空：摘掉送达链（`vreviews.deliver_review`）⇒ b 的读数必须变红，而 c 的义务不受影响 | 摘掉之后 b 还绿 ⇒ b 量的是"盘上本来就有" |

## 为什么 b 用 `board_digest` 而不是"再看一眼 tasks"

`tasks` 里有一行不等于收件人收得到。真正决定"它会不会被唤醒"的是投递点
（`agent_loop._deliver_mailbox` → `mailbox_digest` → `board_digest` 的同一份读法）：
板项挂了但读不进上下文，与没开这一项在行为上同形。所以这一条读的是渲染结果。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

from agentflow import agent_loop as AL
from agentflow import conductor as CND
from agentflow import obligations as OBL
from agentflow import verifications as VR
from agentflow import vreviews as VRV
from agentflow.agent_v import AgentV
from agentflow.store import Store
from agentflow.tools.conductor_tools import conductor_for

TS = "2026-11-16T21:00:00+08:00"
SID = "000031"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
REPLY_DEFECT = json.dumps({
    "verdict": "有毛病", "defect_step": 5, "why": "第 5 步没有依据",
    "findings": [{"level": "error", "step": 5, "kind": "无依据的步骤",
                  "detail": "第 5 步直接用了结论"}],
}, ensure_ascii=False)
REPLY_CLEAN = json.dumps({"verdict": "成立", "why": "逐步核过，没有缺陷"},
                         ensure_ascii=False)


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """V 的那条缝：只喂审阅结论（不联网）。"""

    wired = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)

    def ask(self, prompt: str = "", **_kw) -> _Call:
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call


class _JudgeStub:
    """V 的秘书替身：轴由它给（p247），洗稿返回一段可转达的文本。"""

    def judge_v_reply(self, *, reply="", verdict="", defect_step=None, **_kw):
        bad = "有毛病" in str(verdict) or "有毛病" in str(reply)
        return {"checked": True, "axis": "fault" if bad else "clean",
                "decision": "有缺陷要指出" if bad else "没问题",
                "reason": "夹具：秘书语义判定", "basis": ["夹具"],
                "defect_step": (defect_step if isinstance(defect_step, int) else 5)
                if bad else None}

    def wash_v_reply(self, **_kw):
        return {"checked": True, "washed": True, "text": "第 5 步没有依据：补齐后重送 V。",
                "findings": [], "dropped": [], "refused": ""}

    def decide_sign_issuance(self, *, within_call=None, **_kw):
        return {"checked": True, "issue": False, "issued": False,
                "decision": "夹具：不签", "streak": int(within_call or 0),
                "projected": 0, "need": int(VR.SIGN_STREAK_NEED), "streak_ok": False,
                "reason": "夹具：这一组不量发签", "basis": ["夹具"]}


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = SID, *, proof: str = PROOF) -> None:
    row = {
        "stmt_id": sid, "origin": "own_result", "kind": "theorem",
        "label": f"探针命题 {sid}", "statement_full": FULL,
        "statement_text": FULL, "proof_text": proof,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "夹具：自产命题",
        "created_at": TS, "created_by": "test", "bits": {},
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def _agent_row(st: Store, *, role: str = "F", parent: str = "t-root",
               depth: int = 2) -> str:
    return CND.Conductor._write_new_row(
        conductor_for(st), {
            "task_id": "", "role": role, "action": "", "called_by": "M",
            "parent_task_id": parent, "depth": depth,
            "input_key": f"@t:{role}:{SID}", "status": "done", "outcome": "ok",
            "refusal_reason": None, "instance": f"{role}#1", "detail": "夹具",
            "error": None, "started_at": TS, "ended_at": TS, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [],
        }, note="probe:agent")


def _manuscript(st: Store, sid: str, proof: str) -> str:
    rel = f"reports/f-proof-{sid}.md"
    target = pathlib.Path(str(st.root)) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"# F 的证明手稿\n\n\n## 命题\n\n{FULL}\n\n"
        f"## 证明\n\n{proof}\n\n"
        "## 依赖\n\n| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n",
        encoding="utf-8")
    return rel


def _verify_v(st: Store, sid: str, *, parent: str, proof: str = PROOF,
              reply: str = REPLY_DEFECT) -> dict:
    agent = AgentV(st, workspace_root=st.root, llm=_Seam(reply), secretary=_JudgeStub())
    rel = _manuscript(st, sid, proof)
    with CND.calling_as("t-v1", "V", parent_task_id=parent, parent_role="F"):
        return agent.verify_proof(sid, proof_text=proof, proof_manuscript=rel)


def _items(st: Store, prefix: str) -> list[dict]:
    return [dict(r) for r in st.rows("tasks")
            if str(r.get("input_key") or "").startswith(prefix)]


def _board_text(st: Store, task_id: str) -> str:
    """送审者下一步会读到的板摘要（与 `_deliver_mailbox` 同一份读法）。"""
    text, _ids, _problems = AL.board_digest(conductor_for(st), my_task_id=task_id)
    return text


# ============================================================ a 模块已不在

def test_a_the_vreceipts_module_is_gone() -> None:
    """a：`import agentflow.vreceipts` 不存在（退场不是改名换壳）。"""
    assert importlib.util.find_spec("agentflow.vreceipts") is None, (
        "`agentflow.vreceipts` 还能 import —— 投递层没有退场（或退场后退路留了壳）")
    ss = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "vreceipts.py"
    assert not ss.is_file(), f"模块文件还在：{ss}"
    # 反真空：新家必须在（"没有 vreceipts"不许只是"什么都没了"）。
    assert importlib.util.find_spec("agentflow.obligations") is not None


# ============================================================ b/c 送达与义务

def test_b_a_fault_still_reaches_the_submitter_without_vreceipts(tmp_path):
    """b：V 判有毛病 ⇒ 送审者名下出现 V 的判词项，且它进得了送审者的下一步。

    判词项由 `vreviews.deliver_review` 在判定那一刻开出（`v-review@` notice）；
    这里读的是 `board_digest` 的渲染结果 —— 能进上下文才算"收得到"。
    """
    st = _ws(tmp_path)
    conductor_for(st)
    submitter = _agent_row(st)
    _put(st)
    got = _verify_v(st, SID, parent=submitter)
    assert got.get("checked") is True, got

    review = [r for r in _items(st, VRV.REVIEW_PREFIX)
              if str(r.get("parent_task_id") or "") == submitter]
    assert len(review) == 1, (review, [(r.get("input_key"), r.get("parent_task_id"))
                                      for r in _items(st, VRV.REVIEW_PREFIX)])
    text = _board_text(st, submitter)
    assert "V 的审阅报告" in text, text[:1200]
    assert str(review[0].get("task_id") or "") in text or "v-review@" in text, text[:1200]


def test_c_the_resubmit_duty_survives_and_closes_on_a_clean_sign(tmp_path):
    """c：退场只退投递 —— 有毛病 ⇒ 有重送项；干净「成立」⇒ 收口。"""
    st = _ws(tmp_path)
    conductor_for(st)
    submitter = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=submitter)
    items = _items(st, OBL.RESUBMIT_PREFIX)
    assert len(items) == 1, [r.get("input_key") for r in items]
    item = items[0]
    assert str(item.get("parent_task_id") or "") == submitter, item
    assert str(item.get("expects") or "") == "work", item
    # 送审者的下一步读得到它（与 b 同一条读法；义务本身也是唤醒源）。
    assert "必须重送" in _board_text(st, submitter)

    # 改稿 + 干净成立 ⇒ 义务按证据收口（不是 ack）。
    with st.tx("statements", actor="test") as tx:
        row = next(dict(r) for r in tx.rows("statements") if r["stmt_id"] == SID)
        row["proof_text"] = PROOF + "\n补一句：δ 取 ε 即可。"
        tx.upsert("statements", row)
    _verify_v(st, SID, parent=submitter, proof=row["proof_text"], reply=REPLY_CLEAN)
    after = [dict(r) for r in st.rows("tasks")
             if str(r.get("task_id") or "") == str(item.get("task_id"))][0]
    assert str(after.get("item_state") or "") == "done", after
    assert str(after.get("item_close") or "") == "completed", after


# ============================================================ d 反真空

def test_d_without_the_delivery_chain_the_reading_goes_red(tmp_path, monkeypatch):
    """d：把 `vreviews.deliver_review` 摘掉 ⇒ b 量到的那一项必须消失（义务照旧）。"""
    calls: list[dict] = []

    def _no_delivery(store, **kwargs):
        calls.append(dict(kwargs))
        return {"checked": False, "state": "not_written", "item_id": "", "key": "",
                "role": "", "parent_task_id": "", "reason": "反真空：送达链被摘掉",
                "detail_path": "", "existing": False}

    monkeypatch.setattr(VRV, "deliver_review", _no_delivery)
    st = _ws(tmp_path)
    conductor_for(st)
    submitter = _agent_row(st)
    _put(st)
    _verify_v(st, SID, parent=submitter)
    assert calls, "送达链连一次都没被调到 ⇒ 这条反真空测的不是那条链"
    assert not [r for r in _items(st, VRV.REVIEW_PREFIX)
                if str(r.get("parent_task_id") or "") == submitter], (
        "送达链被摘掉之后判词项还在 ⇒ b 量的是盘上本来就有，不是这条链")
    # 义务不受送达链影响（两条路分开实现：摘掉一条不该让另一条消失）。
    assert len(_items(st, OBL.RESUBMIT_PREFIX)) == 1


# ============================================================ e B 收录不送审

def test_e_the_registration_path_never_calls_verify_proof():
    """B 的收录路径不许发起送审（业主 2026-11-01：B 只读签、不送审）。

    用 AST 判据：`secretary.record_statement` 与 `agent_b/register_statement.py` 里
    不许出现任何对 `verify_proof` 的调用（属性调用或裸名都算）。
    """
    import ast

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
    targets = [root / "secretary.py", root / "agent_b" / "register_statement.py"]
    hits: list[str] = []
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute) else
                        fn.id if isinstance(fn, ast.Name) else "")
                if name == "verify_proof":
                    hits.append(f"{path.name}:{getattr(node, 'lineno', '?')}")
    assert hits == [], f"B 的收录路径在发起送审：{hits}"


# ============================================================ f 历史行的补开

def test_f_reconcile_opens_a_missing_resubmit_for_a_historical_fault(tmp_path):
    """收工对账仍能把"判定已在台账、义务没开"的历史行补开（幂等：只一条）。

    退场删掉的是 outbox 与补投回执，不是这条收敛能力：漏开的 `v-resubmit@` 由
    `obligations.reconcile` 按"那一拍唯一一趟 V 的台账号"解析送审者后补开。
    """
    st = _ws(tmp_path)
    conductor_for(st)
    submitter = _agent_row(st)
    _put(st)
    # 历史现场：台账那一行在，但没有任何 AgentV 发起的义务。
    VR.record_verification(
        st.root, statement_id=SID, proof_text=PROOF,
        verdict={"verdict": "有毛病", "defect_step": 5,
                 "findings": [{"level": "error", "step": 5, "kind": "无依据的步骤",
                               "detail": "第 5 步直接用了结论"}]},
        verifier="agent-V", store=st, proof_no=1, secretary_judge={
            "checked": True, "axis": "fault", "decision": "有缺陷要指出",
            "reason": "夹具：这一行判的是「有毛病」，秘书的轴跟着是 fault"})
    # 那一拍唯一一趟 V：`resolve_recipient` 靠它的时间窗认送审者。
    # `started_at` 落在判定之前、`ended_at` 留空（这一趟还没写终点）⇒ 窗口覆盖判定时刻。
    v_task = CND.Conductor._write_new_row(conductor_for(st), {
        "task_id": "", "role": "V", "action": "", "called_by": "F",
        "parent_task_id": submitter, "depth": 2, "input_key": "@t:V:hist",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "V#1", "detail": "夹具", "error": None,
        "started_at": "2026-01-01T00:00:00+08:00", "ended_at": None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="probe:agent")
    assert v_task
    first = OBL.reconcile(store=st, root=st.root)
    assert first["checked"] is True, first
    items = _items(st, OBL.RESUBMIT_PREFIX)
    assert len(items) == 1, (first, [r.get("input_key") for r in st.rows("tasks")])
    assert str(items[0].get("parent_task_id") or "") == submitter, items[0]
    # 幂等：再对一次账不会长出第二条，也不会把已开的换负责人。
    again = OBL.reconcile(store=st, root=st.root)
    assert again["checked"] is True, again
    assert len(_items(st, OBL.RESUBMIT_PREFIX)) == 1
