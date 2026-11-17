# -*- coding: utf-8 -*-
"""放弃命题那道闸：五条绕行 / 两个锁死 / 三条证据质量（业主 2026-11-07 收口批）。

依据是只读审计 `temp/_audit_newdesign_gates1.md`。本文件逐条钉它：
改前通过（实跑读数见 `temp/_owner_probe_after.out.txt` 的对照）→ 改后受控拒。

## 判据一览

| # | 造什么 | 期望（受控拒码 / 正控） |
|---|---|---|
| a1 | 同一笔 patch 里 `kind=concept` + `status=abandoned` + 自由文本 | `abandon_kind_change_in_same_patch`，盘上 kind/status 一个字节没动 |
| a2 | 两步走：先 `kind=concept`，再 `status=abandoned` + 自由文本 | 第二步 `abandon_reason_missing`（判档读盘上原 kind，含改 kind 的历史） |
| a3 | 登记时写词表外的 kind（`example` / `remark`）再自由文本放弃 | `abandon_reason_missing`（只放行 concept/definition） |
| a4 | 已 abandoned 的历史行再写一段自由文本 | `abandon_reason_missing`；同一个标记原样重放 ⇒ 幂等放行；换一份结构化理由 ⇒ 过闸才写 |
| b1 | `difficulty="做不动了"` + 无关旧引理 | `abandon_difficulty_not_genuine`（秘书语义判定） |
| b2 | 秘书判「不是从原证明拆出来的」 | `abandon_salvaged_not_from_proof` |
| b3 | 判定没判成（没缝 / 超时 / 坏 JSON / 非布尔） | `abandon_difficulty_not_judged`（两态 fail-closed） |
| b4 | 正控：真困难 + 从原证明拆出的 active lemma | 过闸（`checked=True`，`structured/complete`） |
| c1 | `defect_ref` 引用另一条命题的「有毛病」行 | `abandon_defect_ref_other_statement` |
| c2 | `defect_ref` 的判词是对旧稿的（改稿后 stale） | `abandon_defect_ref_stale` |
| c3 | `salvaged` 里出现被放弃的这条自己 | `abandon_salvaged_self_reference` |
| c4 | `salvaged` 指的是一条空壳（`kind=lemma` 但正文空 / 无证明 / 无人认领） | `abandon_salvaged_not_reviewable`（理由必须是「不成其为一条在册、可复核的引理」，不是时间戳） |
| c5 | 正控（2026-11-15 业主语义）：引理登记在被放弃的那一条之后（甚至晚于放弃时刻） | 过 —— 业主原话「以 difficulty 为理由放弃命题，后按照正常流程注册新命题进行攻坚」｜
| d | 反真空：把「放行面」改宽 / 把 `defect_ref` 绑定判据摘掉 | 对应负控当场变绿（证明那两条判据在承重） |
| e | 锁死 1：F 登记引理 → V 签 → B 收录 `kind=lemma` → 可被 `salvaged` 引用 | 正控走通 |
| f | 锁死 2：F 秘书不可用 / 超时 / 坏 JSON | 受控拒 且形态台账各写一行（`judged` 不与「没跑过闸」混） |
| g | F→B 的 `register_statement` 绕行 | 仍受控拒 `f_proposition_must_be_a_manuscript`（上一笔已封，这里只确认） |

零真模型调用：difficulty 那一问在本文件里是替身（dict 或 callable）；形态闸同样用替身。
"""
from __future__ import annotations

import pathlib
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from conftest import seed_statement_row, sign_before_registration

from agentflow import closing as CL
from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import secretary as SEC
from agentflow import statementabandon as SA
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.store import Store

TS = "2026-11-07T09:00:00+08:00"
LATE = "2026-11-07T23:00:00+08:00"
SID = "000001"
LEMMA = "000002"
FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
#: 夹具里的"旧稿引理"正文：不许与被放弃的 SID 那条逐字相同（2026-11-14 起
#: `abandon_salvaged_copies_the_abandoned_statement` 挡这个；同一句话换个号不叫拆出引理）。
LEMMA_FULL = "引理：若 K 在 Re u>=1 有速降，则主链的界一致。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
NEW_PROOF = "换一条路：用有限覆盖，区间分成有限段。"
DEFECT_SELF = "verifications/000001.jsonl#v-000001"
DEFECT_OTHER = "verifications/000002.jsonl#v-000001"
MATH = dict(abandon_kind="math_error",
            abandon_basis="第 5 步直接用了结论：那一步的界对不上，断言不成立")
DIFF = dict(abandon_kind="difficulty",
            abandon_basis="缺一条 K 在 Re u>=1 的速降假设；三条路都试过",
            difficulty="缺一条 K 的速降假设；试过解析延拓、围道、显式估计三条路")
GENUINE = {"checked": True, "genuine": True, "where": "卡在 K 的速降假设",
           "salvaged_from_proof": True, "problems": [], "decision": "真困难",
           "refused": "", "reason": "夹具：难度判定"}


# ---------------------------------------------------------------- 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(st: Store, sid: str = SID, *, kind: str = "theorem", label: str = "",
         status: str = "active", created_at: str = TS,
         proof_text: str = PROOF, quote_reason: str = "夹具：自产命题",
         full: str = FULL) -> dict:
    row = {
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
        "stmt_id": sid, "origin": "own_result", "derived_from": ["999999"], "kind": kind,
        "label": label or f"探针命题 {sid}", "statement_full": full,
        "statement_text": full, "proof_text": proof_text,
        "evidence_kind": "heuristic", "status": status,
        "quote_verified": None, "quote_reason": quote_reason,
        "created_at": created_at, "created_by": "test", "bits": {},
    }
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _just_after(stamp: str) -> str:
    """比 `stamp` 晚一分钟的时刻（夹具时钟：放弃发生在引理真在册之后）。

    2026-11-15 起 `salvaged` 的判据不看时间戳（业主语义：放弃之后再按正常流程
    注册新命题才是主路径），所以这一格不再是"撞不撞某道闸"的关键，只是让夹具的
    时间顺序像一次真实的放弃。e 这一条里的引理是由「真登记路」写进来的 ⇒ 它的
    `created_at` 是墙钟；放弃时刻相对它算，读起来才是一个说得通的场景。
    """
    return (datetime.fromisoformat(str(stamp)) + timedelta(minutes=1)).isoformat()


def _verify(st: Store, sid: str = SID, *, verdict: str = "有毛病",
            fault: bool = True, step: int | None = 5,
            proof_text: str = PROOF) -> dict:
    findings = ([{"detail": "夹具：第 5 步的断言不成立", "level": "error", "step": step}]
                if verdict == "有毛病" else [])
    return VR.record_verification(
        st.root, statement_id=sid, proof_text=proof_text,
        verdict={"verdict": verdict, "defect_step": step, "findings": findings},
        secretary_judge={"axis": "fault" if fault else "clean", "checked": True,
                         "reason": "夹具：秘书的语义判定"},
        flip=False)


def _registry(st: Store):
    from agentflow.tools import table_tools
    from agentflow.tools.base import ToolRegistry

    reg = ToolRegistry(name="tables")
    reg.bound_role = "B"
    table_tools.register(reg, store=st)
    return reg


@contextmanager
def _judge_as(verdict):
    """把难度语义判定换成替身（dict 或 `(**kw) -> dict`）；退出时原样还回去。"""
    real = SEC.Secretary.judge_abandon_difficulty

    def _stub(self, **kw):
        return dict(verdict(**kw) if callable(verdict) else verdict)

    SEC.Secretary.judge_abandon_difficulty = _stub
    try:
        yield
    finally:
        SEC.Secretary.judge_abandon_difficulty = real


def _call(st: Store, sid: str = SID, *, judge=None, **kw):
    """走生产的通用写口（`table.update` → `Secretary.amend_statement_meta`）。"""
    with _judge_as(GENUINE if judge is None else judge):
        reg = _registry(st)
        with CND.calling_as("t-b1", "B"):
            return reg.call("table.update", table="statements", id=sid, **kw)


def _row(st: Store, sid: str = SID) -> dict:
    return next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)


def _abandoned(st: Store) -> dict:
    return CL.statements_abandoned_reading(st)


# ---------------------------------------------------------------- a1 同笔改 kind

def test_a1_a_kind_change_in_the_same_abandon_patch_is_refused(tmp_path):
    """a1：同一笔把 kind 改成 concept + status=abandoned ⇒ 受控拒，盘上原样。"""
    st = _ws(tmp_path)
    _put(st, kind="conjecture", label="lem:cancel")
    before = _row(st)
    free = SA.abandon_marker(at=TS, reason="无干净依据：verifications/ 下不存在 000001.jsonl")
    res = _call(st, patch={"kind": "concept", "status": "abandoned", "quote_reason": free})
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_kind_change_in_same_patch", res.meta
    assert "kind" in str(res.error or ""), res.error
    assert _row(st) == before, "受控拒必须一个字节都不写（kind 也不许落盘）"
    assert _abandoned(st)["count"] == 0, _abandoned(st)


# ---------------------------------------------------------------- a2 两步走

def test_a2_changing_the_kind_first_then_abandoning_is_still_gated(tmp_path):
    """a2：先 `kind=concept`（单独一笔，允许），再自由文本放弃 ⇒ 第二步仍受控拒。

    判档读的是盘上原 kind：`_statement_amend_history` 记着它曾经是 `conjecture`
    ⇒ 它不能靠"先改成 concept"变成概念行。改前这条路 A2 两步都 `ok=True`。
    """
    st = _ws(tmp_path)
    _put(st, kind="conjecture", label="lem:cancel")
    first = _call(st, patch={"kind": "concept"})
    assert first.ok is True, first
    assert _row(st)["kind"] == "concept", _row(st)
    free = SA.abandon_marker(at=TS, reason="无干净依据：verifications/ 下不存在 000001.jsonl")
    second = _call(st, patch={"status": "abandoned", "quote_reason": free})
    assert second.ok is False, second
    assert dict(second.meta or {}).get("kind") == "abandon_reason_missing", second.meta
    assert _row(st)["status"] == "active", _row(st)


# ---------------------------------------------------------------- a3 未识别 kind

@pytest.mark.parametrize("kind", ["example", "remark"])
def test_a3_an_unknown_kind_is_treated_as_a_proposition(tmp_path, kind):
    """a3：词表外的 kind（`example` / `remark`）⇒ 一律按命题处理（fail-closed）。"""
    st = _ws(tmp_path)
    _put(st, kind=kind, label="例 1")
    free = SA.abandon_marker(at=TS, reason="这一行不是命题，算了")
    res = _call(st, patch={"status": "abandoned", "quote_reason": free})
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_reason_missing", res.meta
    assert _row(st)["status"] == "active", _row(st)


# ---------------------------------------------------------------- a4 已 abandoned 的行

def test_a4_a_free_text_rewrite_of_an_abandoned_row_is_refused(tmp_path):
    """a4：已 abandoned 的历史行再写一段自由文本 ⇒ 受控拒；原标记一个字不动。"""
    st = _ws(tmp_path)
    legacy = SA.abandon_marker(at=TS, reason="无干净依据")
    _put(st, kind="conjecture", label="lem:cancel", status="abandoned", quote_reason=legacy)
    res = _call(st, patch={"status": "abandoned",
                           "quote_reason": SA.abandon_marker(at=TS, reason="换个说法")})
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_reason_missing", res.meta
    assert _row(st)["quote_reason"] == legacy, "已放弃的理由不许被自由文本洗掉"


def test_a4_the_same_marker_replays_idempotently(tmp_path):
    """a4 的另一半：同一个标记原样重放 ⇒ 幂等放行（不是拒，也不写）。"""
    st = _ws(tmp_path)
    legacy = SA.abandon_marker(at=TS, reason="无干净依据")
    _put(st, kind="conjecture", label="lem:cancel", status="abandoned", quote_reason=legacy)
    res = _call(st, patch={"status": "abandoned", "quote_reason": legacy})
    assert res.ok is True, (res.error, res.data)
    row = _row(st)
    assert row["quote_reason"] == legacy and row["status"] == "abandoned", row


def test_a4_a_structured_reason_can_replace_the_old_one_only_through_the_gate(tmp_path):
    """a4 的正控：已 abandoned 的行补一份结构化理由 ⇒ 过闸才写，且保留原放弃时刻。"""
    st = _ws(tmp_path)
    legacy = SA.abandon_marker(at="2026-11-01T00:00:00+08:00", reason="当时只写了散文")
    _put(st, kind="conjecture", label="lem:cancel", status="abandoned", quote_reason=legacy)
    _verify(st)
    res = _call(st, patch={"status": "abandoned"}, **MATH, defect_ref=DEFECT_SELF)
    assert res.ok is True, (res.error, res.data)
    row = _row(st)
    parsed = SA.parse_abandon_reason(row["quote_reason"])
    assert parsed["structured"] is True and parsed["complete"] is True, parsed
    assert parsed["abandon_kind"] == "math_error", parsed
    assert parsed["at"] == "2026-11-01T00:00:00+08:00", "补理由不改「几时放下的」那一刻"
    # 而自由文本仍被拒（判据没有把已 abandoned 当免检）
    again = _call(st, patch={"quote_reason": SA.abandon_marker(at=TS, reason="再换一段散文")})
    assert again.ok is False, again


# ---------------------------------------------------------------- b difficulty 语义判定

def test_b1_junk_difficulty_is_refused_by_the_secretary_judgement(tmp_path):
    """b1：`difficulty="做不动了"` + 无关旧引理 ⇒ 秘书判不是真困难 ⇒ 受控拒。"""
    st = _ws(tmp_path)
    _put(st, kind="conjecture", label="lem:cancel")
    _put(st, LEMMA, kind="lemma", label="引理 A（与本题无关）", full=LEMMA_FULL)
    bad = dict(GENUINE, genuine=False, where="", problems=["只有情绪，没有说清难在哪"])
    res = _call(st, patch={"status": "abandoned"},
                abandon_kind="difficulty", abandon_basis="做不动了",
                difficulty="做不动了", judge=bad,
                salvaged=[{"label": "引理 A（与本题无关）", "stmt_id": LEMMA}])
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_difficulty_not_genuine", res.meta
    assert "difficulty" in str(res.error or ""), res.error
    assert _row(st)["status"] == "active", _row(st)


def test_b2_salvaged_that_is_not_from_the_old_proof_is_refused(tmp_path):
    """b2：同一问判「那几条不是从原证明拆出来的」⇒ `abandon_salvaged_not_from_proof`。"""
    st = _ws(tmp_path)
    _put(st, kind="conjecture", label="lem:cancel")
    _put(st, LEMMA, kind="lemma", label="另一条无关引理", full=LEMMA_FULL)
    bad = dict(GENUINE, salvaged_from_proof=False, problems=["那条引理与本题无关"])
    res = _call(st, patch={"status": "abandoned"}, judge=bad,
                salvaged=[{"label": "另一条无关引理", "stmt_id": LEMMA}], **DIFF)
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_salvaged_not_from_proof", res.meta
    assert _row(st)["status"] == "active", _row(st)


def test_b3_a_failed_judgement_is_fail_closed(tmp_path):
    """b3：判定没判成（checked=False）⇒ `abandon_difficulty_not_judged`，一个字节不写。"""
    st = _ws(tmp_path)
    _put(st, kind="conjecture", label="lem:cancel")
    _put(st, LEMMA, kind="lemma", label="引理 A", full=LEMMA_FULL)
    res = _call(st, patch={"status": "abandoned"},
                judge={"checked": False, "refused": "abandon_difficulty_not_judged",
                       "reason": "夹具：没有判定面"},
                salvaged=[{"label": "引理 A", "stmt_id": LEMMA}], **DIFF)
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_difficulty_not_judged", res.meta
    assert _row(st)["status"] == "active", _row(st)


def test_b4_a_genuine_difficulty_with_a_lemma_from_the_proof_passes(tmp_path):
    """b4 正控：真困难 + 从原证明拆出的 active lemma ⇒ 过闸。"""
    st = _ws(tmp_path)
    _put(st, kind="conjecture", label="lem:cancel")
    _put(st, LEMMA, kind="lemma", label="引理 A：K 的速降", full=LEMMA_FULL)
    res = _call(st, patch={"status": "abandoned"},
                salvaged=[{"label": "引理 A：K 的速降", "stmt_id": LEMMA}], **DIFF)
    assert res.ok is True, (res.error, res.data)
    parsed = SA.parse_abandon_reason(_row(st)["quote_reason"])
    assert parsed["structured"] is True and parsed["complete"] is True, parsed
    assert parsed["abandon_kind"] == "difficulty", parsed
    assert parsed["salvaged"][0]["stmt_id"] == LEMMA, parsed
    assert _abandoned(st)["count"] == 1, _abandoned(st)


class _Seam:
    """模型缝的替身（`ask_json` 的形状与 `LlmSeam` 一致到本文件用到的程度）。"""

    class _Call:
        def __init__(self, *, ok: bool = True, problem: str = "", detail: str = ""):
            self.ok, self.problem, self.detail = ok, problem, detail
            self.text = ""
            self.model = "fake"
            self.prompt_version = "t"
            self.prompt_sha256 = "0" * 64
            self.cost = {}

    def __init__(self, data: dict | None = None, *, raises: BaseException | None = None,
                 ok: bool = True):
        self.data, self.raises, self.ok = dict(data or {}), raises, ok
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.prompts.append(str(prompt))
        self.systems.append(str(system))
        if self.raises is not None:
            raise self.raises
        return dict(self.data), self._Call(ok=self.ok,
                                           problem="" if self.ok else "bad_json",
                                           detail="" if self.ok else "不是 JSON")


def _judge(st: Store, seam) -> dict:
    sec = SEC.Secretary("B", root=st.root, store=st, seam=seam,
                        enable_model=seam is not None)
    return sec.judge_abandon_difficulty(
        statement=_row(st), difficulty=DIFF["difficulty"], basis=DIFF["abandon_basis"],
        salvaged=[{"stmt_id": LEMMA, "kind": "lemma", "label": "引理 A",
                   "created_at": TS, "statement_full": FULL}])


def test_b3_the_judge_itself_is_fail_closed_on_bad_replies(tmp_path):
    """b3 的第二半：判定函数自己的四档 fail-closed（没缝 / 超时 / 坏 JSON / 非布尔）。"""
    st = _ws(tmp_path)
    _put(st, kind="conjecture", label="lem:cancel")
    _put(st, LEMMA, kind="lemma", label="引理 A")
    no_seam = _judge(st, None)
    assert no_seam["checked"] is False and no_seam["refused"] == "abandon_difficulty_not_judged", \
        no_seam
    timeout = _judge(st, _Seam({"genuine": True}, raises=TimeoutError("模型超时")))
    assert timeout["checked"] is False and "没判成" in timeout["reason"], timeout
    bad_json = _judge(st, _Seam({"genuine": True}, ok=False))
    assert bad_json["checked"] is False, bad_json
    not_bool = _judge(st, _Seam({"genuine": "yes", "salvaged_from_proof": True,
                                 "where": "x", "problems": []}))
    assert not_bool["checked"] is False, not_bool
    # 「合格」却读不出难在哪 ⇒ 也按没判成（合格必须能复述「难在哪」）
    no_where = _judge(st, _Seam({"genuine": True, "salvaged_from_proof": True,
                                 "where": "", "problems": []}))
    assert no_where["checked"] is False, no_where
    good = _judge(st, _Seam({"genuine": True, "salvaged_from_proof": True,
                             "where": "卡在 K 的速降假设", "problems": [],
                             "decision": "真困难"}))
    assert good["checked"] is True and good["genuine"] is True, good
    assert good["salvaged_from_proof"] is True, good


def _call_raw(st: Store, sid: str = SID, **kw):
    """不替判定面，走 `table.update` 的整条生产接线（秘书由 `for_role_wired` 现造）。"""
    reg = _registry(st)
    with CND.calling_as("t-b1", "B"):
        return reg.call("table.update", table="statements", id=sid, **kw)


def test_b5_the_seam_is_really_reached_once_in_each_direction(tmp_path, monkeypatch):
    """b5 接线：真走 `for_role_wired` 造的秘书，`ask_json` 在过 / 不过两向各恰好 1 次。

    这一条不替 `judge_abandon_difficulty`，只替模型缝：证明闸真的把这一问接到了
    生产写口上（改前的两向打桩是 `check_abandon_reason` 本身，不是这一问）。
    """
    cases = [
        (dict(GENUINE), True, ""),
        (dict(GENUINE, genuine=False, where="", problems=["只有情绪，没有说清难在哪"]),
         False, "abandon_difficulty_not_genuine"),
    ]
    for verdict, expect_ok, expect_code in cases:
        st = _ws(tmp_path / ("ok" if expect_ok else "no"))
        _put(st, kind="conjecture", label="lem:cancel")
        _put(st, LEMMA, kind="lemma", label="引理 A：K 的速降", full=LEMMA_FULL)
        seam = _Seam(verdict)

        def _wired(role, *, root=None, store=None, **kw):
            return SEC.Secretary(str(role), root=root, store=store, seam=seam,
                                 enable_model=True)

        monkeypatch.setattr(SEC, "for_role_wired", _wired)
        try:
            res = _call_raw(st, patch={"status": "abandoned"},
                            salvaged=[{"label": "引理 A：K 的速降", "stmt_id": LEMMA}], **DIFF)
        finally:
            monkeypatch.undo()
        assert bool(res.ok) is expect_ok, (res.error, res.data)
        if expect_code:
            assert dict(res.meta or {}).get("kind") == expect_code, res.meta
        assert len(seam.prompts) == 1, f"这一问在{'过' if expect_ok else '拒'}那一向被调了 {len(seam.prompts)} 次"
        assert "难在哪" in seam.systems[0], seam.systems[0]
        assert DIFF["difficulty"] in seam.prompts[0], seam.prompts[0]


# ---------------------------------------------------------------- c 证据质量

def test_c1_a_defect_ref_to_another_statement_is_refused(tmp_path):
    """c1：放弃 000001，却引用 000002 的「有毛病」行 ⇒ `abandon_defect_ref_other_statement`。"""
    st = _ws(tmp_path)
    _put(st, "000001")
    _put(st, "000002")
    _verify(st, "000002")
    res = _call(st, "000001", patch={"status": "abandoned"},
                defect_ref=DEFECT_OTHER, **MATH)
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_defect_ref_other_statement", res.meta
    assert _row(st, "000001")["status"] == "active", _row(st, "000001")


def test_c2_a_stale_defect_ref_is_refused(tmp_path):
    """c2：V 的「有毛病」是对旧 proof 的；改稿后仍拿它放弃 ⇒ `abandon_defect_ref_stale`。"""
    st = _ws(tmp_path)
    _put(st, proof_text=PROOF)
    _verify(st, proof_text=PROOF)
    with st.tx("statements", actor="test") as tx:
        row = next(dict(r) for r in tx.rows("statements") if r["stmt_id"] == SID)
        row["proof_text"] = NEW_PROOF
        tx.upsert("statements", row)
    res = _call(st, patch={"status": "abandoned"}, defect_ref=DEFECT_SELF, **MATH)
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_defect_ref_stale", res.meta
    assert "sha256" in str(res.error or ""), res.error
    assert _row(st)["status"] == "active", _row(st)


def test_c3_a_salvaged_self_reference_is_refused(tmp_path):
    """c3：一条 kind=lemma 放弃自己并把自身列成 salvaged ⇒ `abandon_salvaged_self_reference`。"""
    st = _ws(tmp_path)
    _put(st, LEMMA, kind="lemma", label="引理 B")
    res = _call(st, LEMMA, patch={"status": "abandoned"},
                salvaged=[{"label": "引理 B", "stmt_id": LEMMA}], **DIFF)
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == "abandon_salvaged_self_reference", res.meta
    assert _row(st, LEMMA)["status"] == "active", _row(st, LEMMA)


def test_c4_a_shell_lemma_is_refused_as_not_a_reviewable_lemma(tmp_path):
    """c4：`salvaged` 指一条空壳（`kind=lemma` 但无证明 / 无人认领）⇒ 受控拒。

    2026-11-15 业主语义：放弃时可以不指任何引理；要挡的不是"晚"，是"现造一条
    空壳来交差"。所以这里的拒绝理由必须读成「不成其为一条在册、可复核的引理」，
    而不是任何时间戳判据。
    """
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", label="lem:cancel")
    # 空壳：正文在、`kind=lemma`，但没有证明（`proof_text` 空）⇒ 不可复核。
    _put(st, LEMMA, kind="lemma", label="现造的引理", full=LEMMA_FULL, proof_text="")
    got = SA.apply_abandonment(
        st, statement_id=SID, reason="理由", at=TS,
        salvaged=[{"label": "现造的引理", "stmt_id": LEMMA}], **DIFF)
    assert got["checked"] is False, got
    assert got["refused"] == SA.ABANDON_SALVAGED_NOT_REVIEWABLE, got
    assert "不成其为一条在册、可复核的引理" in str(got["why"]), got["why"]
    assert _row(st)["status"] == "active", _row(st)


def test_c5_a_lemma_registered_after_the_abandoned_statement_passes(tmp_path):
    """c5 正控（2026-11-15 业主语义）：引理晚于被放弃的那一条登记 ⇒ 过。

    改前这一条拒（`abandon_salvaged_after_the_abandoned_statement`）。业主原话是
    「以 difficulty 为理由放弃命题，后按照正常流程注册新命题进行攻坚」——
    "晚于"不是罪证，时间戳不作判据。
    """
    st = _ws(tmp_path)
    _put(st, SID, kind="conjecture", label="lem:cancel")
    _put(st, LEMMA, kind="lemma", label="事后拆出的引理", created_at=LATE, full=LEMMA_FULL)
    got = SA.apply_abandonment(
        st, statement_id=SID, reason="理由", at=TS,
        salvaged=[{"label": "事后拆出的引理", "stmt_id": LEMMA}], **DIFF)
    assert got["checked"] is True, got
    parsed = SA.parse_abandon_reason(_row(st)["quote_reason"])
    assert parsed["salvaged"][0]["stmt_id"] == LEMMA, parsed
    assert _row(st)["status"] == "abandoned", _row(st)


# ---------------------------------------------------------------- d 反真空

def test_d_widening_the_exempt_surface_makes_a3_green(tmp_path, monkeypatch):
    """d-①：把「只放行 concept/definition」改宽（放进 `example`）⇒ a3 那条负控当场变绿。"""
    st = _ws(tmp_path)
    _put(st, kind="example", label="例 1")
    free = SA.abandon_marker(at=TS, reason="这一行不是命题，算了")
    monkeypatch.setattr(SA, "abandon_exempt_kinds",
                        lambda: ("concept", "definition", "example"))
    res = _call(st, patch={"status": "abandoned", "quote_reason": free})
    assert res.ok is True, (
        "反真空失效：放行面改宽之后 example 仍被拒 ⇒ a3 证明不了「只放行两档」在承重")
    assert _row(st)["status"] == "abandoned", _row(st)
    monkeypatch.undo()
    _put(st, "000004", kind="example", label="例 2")
    again = _call(st, "000004", patch={"status": "abandoned", "quote_reason": free})
    assert dict(again.meta or {}).get("kind") == "abandon_reason_missing", again.meta


def test_d_removing_the_defect_target_check_makes_c1_green(tmp_path, monkeypatch):
    """d-②：把 `defect_ref` 的绑定判据摘掉 ⇒ c1（跨命题引用）当场变绿。"""
    st = _ws(tmp_path)
    _put(st, "000001")
    _put(st, "000002")
    _verify(st, "000002")
    monkeypatch.setattr(SA, "_defect_refusal",
                        lambda *a, **kw: ({}, "", ""))
    res = _call(st, "000001", patch={"status": "abandoned"},
                defect_ref=DEFECT_OTHER, **MATH)
    assert res.ok is True, (
        "反真空失效：摘掉 target 绑定之后仍然拒 ⇒ c1 证明不了那条绑定在承重")
    assert _row(st, "000001")["status"] == "abandoned", _row(st, "000001")


# ---------------------------------------------------------------- e/f 两个锁死

class _FormStub:
    """F 的秘书替身：只实现形态判定这一问。"""

    role = "F"
    seam = object()

    def judge_proposition_form(self, **kw):
        return {"checked": True, "well_formed": True,
                "conditions": "设 f 在 [0,1] 上连续", "conclusion": "则 f 一致连续",
                "problems": [], "decision": "夹具：形态判定", "refused": "",
                "reason": "夹具：形态判定", "cached": False}

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": "fake-F-secretary",
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def test_e_f_lemma_reaches_salvaged_after_the_v_sign(tmp_path):
    """e：F 登记一条引理 → V 签 → B 收录后 `kind=lemma` → 该行可被 `salvaged` 引用。

    改前的互锁：F 的正常交稿只落 `conjecture`，而 `salvaged` 只认 `lemma` ⇒ F 自己
    永远产不出 `salvaged` 要的那一档。上一笔按手稿头 `- 命题类型` 在 B 收录时落
    `lemma`；这一条把整条链走一遍，并用它作 `salvaged` 过放弃闸。
    """
    st = _ws(tmp_path)
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0000"})
    f.f_secretary = _FormStub()
    got = f._hand_proof(
        full=FULL, text=FULL, body="第一版：取 δ=ε。", sid="s1",
        plan={"plan_id": "0000", "problem_key": "PK"},
        sg={"sid": "s1", "text": FULL, "kind": "lemma"},
        # 2026-11-13 业主裁定 B：`## 命题` 只从 `product.proposition` 渲染，
        # 没有回退算式 ⇒ 夹具要把这一格交上来（子目标正文不是命题）。
        proposition=FULL,
        manuscript_text="", manuscript_received={"source": "param", "chars": 1,
                                                 "section_rows": 0, "refs_in_proof": 0},
        cites=[], tier={"kind": "heuristic", "why": "夹具"},
        dependency_rows=[], existing_row={})
    assert got["ok"] is True, got
    path = pathlib.Path(st.root) / str(got["manuscript_path"])
    manuscript = path.read_text(encoding="utf-8")
    body = DS.proof_body(manuscript).strip("\n")
    sign_before_registration(st.root, proof_text=body)
    b = AgentB(st, extractor=None, extract_text=None)
    first = b.register_statement(
        statement_full=FULL, statement_text=FULL, origin="own_result", derived_from=["999999"], kind="conjecture",
        label="F 攻坚 0000 子目标 s1", proof_text=body, proof_manuscript=manuscript,
        line_range={"label": str(got["manuscript_path"])},
        quote_reason="夹具：V 的 pending 签在盘上")
    assert first.get("ok") is True, first
    lemma_id = str(first["stmt_id"])
    lemma = _row(st, lemma_id)
    assert lemma["kind"] == "lemma", lemma
    assert lemma["kind"] in SEC.PROPOSITION_KINDS, lemma
    # 正控：把它当 `salvaged`，放弃另一条命题 ⇒ 过闸（改前这里会 `abandon_salvaged_kind_not_lemma`）
    # 2026-11-15 业主语义：`salvaged` 的判据不看 `created_at`（放弃之后按正常流程注册新
    # 命题本来就是主路径）。这一条正控仍按"先有一条证据齐全的引理，再有一道引用它的
    # 命题被放弃"落夹具 —— 那是这个场景的真实时间顺序，不是一道闸。
    _put(st, "000099", kind="conjecture", label="要放弃的命题",
         created_at=str(lemma["created_at"]),
         full="设 g 在 [0,1] 上连续，则 g 有界。")
    # 放弃时刻 = 这条引理真在册之后：
    at = _just_after(str(lemma["created_at"]))
    with _judge_as(GENUINE):
        result = SA.apply_abandonment(
            st, statement_id="000099", reason="理由", at=at,
            abandon_basis=DIFF["abandon_basis"], difficulty=DIFF["difficulty"],
            abandon_kind="difficulty",
            salvaged=[{"label": lemma["label"], "stmt_id": lemma_id}],
            difficulty_judge=lambda **_: dict(GENUINE))
    assert result["checked"] is True, result
    parsed = SA.parse_abandon_reason(_row(st, "000099")["quote_reason"])
    assert parsed["salvaged"][0]["stmt_id"] == lemma_id, parsed


def test_f_the_form_gate_ledger_records_no_secretary_timeout_and_bad_json(tmp_path):
    """f：F 秘书不可用 / 超时 / 坏 JSON ⇒ 受控拒 且 形态台账各写一行。

    「没秘书」那一档改前不写台账（`judged=0` 与「没跑过闸」不可分）；这一条把三档
    一起钉住：每一档都要在 `proposition_form.jsonl` 留下一行 `checked=False`。
    """
    st = _ws(tmp_path)
    before = len(SEC.proposition_form_rows(st.root))

    no_seam = SEC.Secretary("F", root=st.root, store=st, enable_model=False)
    got = no_seam.judge_proposition_form(statement_full=FULL, kind="conjecture")
    assert got["checked"] is False and got["refused"] == SEC.PROPOSITION_FORM_REFUSED, got
    assert len(SEC.proposition_form_rows(st.root)) == before + 1, "没秘书也要写台账"

    timeout = SEC.Secretary("F", root=st.root, store=st,
                            seam=_Seam({"well_formed": True}, raises=TimeoutError("超时")),
                            enable_model=True)
    got = timeout.judge_proposition_form(statement_full=FULL, kind="conjecture")
    assert got["checked"] is False, got
    assert len(SEC.proposition_form_rows(st.root)) == before + 2, "超时也要写台账"

    bad = SEC.Secretary("F", root=st.root, store=st,
                        seam=_Seam({"well_formed": True}, ok=False), enable_model=True)
    got = bad.judge_proposition_form(statement_full=FULL, kind="conjecture")
    assert got["checked"] is False, got
    rows = SEC.proposition_form_rows(st.root)
    assert len(rows) == before + 3, "坏 JSON 也要写台账"
    assert all(row["checked"] is False for row in rows[before:]), rows[before:]


# ---------------------------------------------------------------- g F→B 的路

def test_g_an_f_caller_still_cannot_register_through_b(tmp_path, monkeypatch):
    """g：上一笔封住的 F→B 派活路仍然生效（只确认，不重做）。"""
    from agentflow.agent_b import register_statement as RS

    st = _ws(tmp_path)
    b = AgentB(st, extractor=None, extract_text=None)
    monkeypatch.setattr(RS, "_caller_role", lambda: "F")
    got = b.register_statement(
        statement_full=FULL, statement_text=FULL, kind="conjecture",
        origin="own_result", derived_from=["999999"], evidence_kind="heuristic",
        quote_reason="夹具：F 直接派 B 登记")
    assert got.get("ok") is False, got
    assert got.get("kind") == RS._RegisterStatement.F_CALLER_REFUSED, got
    assert "手稿" in str(got.get("error") or ""), got
    assert len(list(st.rows("statements"))) == 0, list(st.rows("statements"))
