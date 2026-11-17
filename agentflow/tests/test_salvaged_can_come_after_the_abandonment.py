# -*- coding: utf-8 -*-
"""放弃之后按正常流程注册新命题 —— 业主 2026-11-15 语义的判据。

业主逐字（本次施工的唯一依据）：

> 「我明确一下因证明太困难放弃，后拆出可用引理这条的语义：以difficulty为理由放弃命题，
>   后按照正常流程注册新命题进行攻坚，这些新命题可以是对原命题在加强条件下的证明，或是
>   取出中间部分逻辑链整理成命题，或是陈述负面事实等等。总之不是机械的」

三步：① 以 `difficulty` 放弃命题 T；② 之后按正常流程注册新命题去攻坚；
③ 那些新命题各自走自己的流程（登记 → 形态闸 → 送 V 签 → 收编）。

## 本文件守的五件事

| # | 判据 | 用例 |
|---|---|---|
| a | 登记 T ⇒ difficulty 放弃 T（不指向任何引理）⇒ 事后注册引理 L（lemma，过形态闸）⇒ 在后续动作里把它记为该次放弃的可取之处 ⇒ 走得通，不产生任何"必须早于"的拒绝 | `test_a_*` |
| b | 三种形态各一条：① T 的加强条件版 ② 原证明抽出的中间逻辑链 ③ 负面事实 ⇒ 都能按正常流程注册、都能被认成攻坚方向（记成可取之处），且不因为"晚于 T"被拒 | `test_b_*` |
| c | 放弃那一刻现造一条空壳（正文空 / 无证明 / 无人认领 / 不在册）⇒ 仍被拒；理由必须是"它不成其为一条在册、可复核的引理"，不是"时间戳不对" | `test_c_*` |
| d | 把秘书语义判定（`genuine & salvaged_from_proof`）打桩成恒真 ⇒ c 仍红（证明 c 的拒不是靠时间戳、也不是靠秘书那一问）；把"可复核"那一问也打桩掉 ⇒ 它才变绿（证明是这一问在承重） | `test_d_*` |
| e | 既有反真空 `test_abandon_reason_is_structured.py::test_e_removing_the_salvaged_check_makes_c_red` 仍绿 | 那个文件；本文件不重写它 |

## 零真模型调用

形态闸用替身（`_FormStub`，与 `test_abandon_gate_is_not_bypassable.py` 同一形状）；
难度语义判定用替身（恒真）。登记本身走生产路：`AgentF._hand_proof` 落稿（过形态闸）
→ `sign_before_registration` 落一份 pending 签 → `AgentB.register_statement` 收录。
"""
from __future__ import annotations

import pathlib

import pytest
from conftest import sign_before_registration, ensure_basis_stmt

from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import secretary as SEC
from agentflow import statementabandon as SA
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.store import Store
from conftest import ensure_basis_lit

T_AT = "2026-11-15T09:00:00+08:00"       # 放弃 T 的时刻（早于所有新命题）
LATER_AT = "2026-11-15T10:00:00+08:00"   # 事后补记"可取之处"的时刻
SID = "000001"

DIFF = dict(abandon_kind="difficulty",
            abandon_basis="卡在 Ball 的 Brascamp–Lieb 型积分不等式上，本地无全文、册内无引理",
            difficulty="缺 Ball 的 BL 型积分不等式这一条引理；试过三条路都绕不过去")

#: 三种"攻坚方向"的正文（① 加强条件版 / ② 原证明抽出的中间逻辑链 / ③ 负面事实）。
BODY_STRENGTHENED = ("引理（加强条件版）：设 n ∈ N、a ∈ S^{n−1}，且 a 满足额外条件 "
                     "a·a^{(2)} ≥ 0。则 A_{n,∞}(a) ≤ √2 − δ(n)，其中 δ(n) > 0 只依赖 n。")
BODY_CHAIN = ("引理：Ball 的 BL 型积分不等式的中间一步 —— 对每个 n 与每个 a，"
              "A_{n,∞}(a) 关于 a 的极大值在 a^{(2)} 处取到。")
BODY_NEGATIVE = ("引理（负面事实）：不存在 n ≥ 3 与 a ∈ S^{n−1} 使 A_{n,∞}(a) > √2。")
FORMS = [("① 加强条件版", BODY_STRENGTHENED),
         ("② 中间逻辑链", BODY_CHAIN),
         ("③ 负面事实", BODY_NEGATIVE)]
BODY_TARGET = ("猜想：设 n ∈ N，a ∈ S^{n−1}。记 A_{n,∞}(a) 为 n 维立方体被以 a 为法向的"
               "过原点超平面所截得的 (n−1) 维体积。则对所有 n 与所有 a 成立 "
               "A_{n,∞}(a) ≤ A_{n,∞}(a^{(2)}) = √2。")


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _genuine(**_kw) -> dict:
    """秘书语义判定的替身：真困难 + 从原证明里拆出（两问都判"是"）。"""
    return {"checked": True, "genuine": True, "where": "缺 Ball 的 BL 型积分不等式",
            "salvaged_from_proof": True, "problems": [], "decision": "夹具：难度判定",
            "refused": "", "reason": "夹具：难度判定"}


def _put(st: Store, sid: str = SID, *, kind: str = "conjecture",
         body: str = BODY_TARGET, created: str = "2026-11-15T08:00:00+08:00",
         proof: str = "证明：夹具正文。") -> dict:
    """把 T（或空壳）直接写进盘（不经登记路 —— 空壳那条负控要的正是这个）。"""
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
    row = {"stmt_id": sid, "origin": "own_result", "source_lit_id": ensure_basis_lit(st), "kind": kind,
           "label": f"探针 {sid}", "statement_full": body, "statement_text": body,
           "proof_text": proof, "status": "active", "created_at": created,
           "created_by": "test", "bits": {}, "quote_verified": None,
           "quote_reason": "夹具：自产命题"}
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _row(st: Store, sid: str = SID) -> dict:
    return next(dict(x) for x in st.rows("statements") if str(x.get("stmt_id")) == sid)


def _abandon(st: Store, *, at: str = T_AT, salvaged=(), judge=_genuine) -> dict:
    return SA.apply_abandonment(
        st, statement_id=SID, reason="夹具：放弃标记", at=at, actor="test",
        difficulty_judge=judge, salvaged=list(salvaged), **DIFF)


class _FormStub:
    """F 的秘书替身：只实现形态判定这一问（与 abandon_gate 那份同形）。"""

    role = "F"
    seam = object()

    def judge_proposition_form(self, **kw):
        return {"checked": True, "well_formed": True,
                "conditions": "设序列紧", "conclusion": "则每个子列有收敛子列",
                "problems": [], "decision": "夹具：形态判定", "refused": "",
                "reason": "夹具：形态判定", "cached": False}

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        return {"checked": True, "text": str(text), "actor": "fake-F-secretary",
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def _register_new_proposition(st: Store, *, sid: str, full: str, proof: str,
                              label: str) -> str:
    """按正常流程登记一条新命题：落稿（过形态闸）→ 落 pending 签 → B 收录。

    返回落盘后的 `stmt_id`。这条路的每一格都是生产实现：
    - `AgentF._hand_proof` 写 `reports/f-proof-*.md`，`## 命题` 过形态闸（替身）；
    - `sign_before_registration` 落一份 V 的 pending 签（未签的正文 B 不收）；
    - `AgentB.register_statement` 收录，`kind` 从手稿头 `- 命题类型：lemma` 落成 lemma。
    """
    f = AgentF(st, config={"workspace_root": str(st.root), "plan_id": "0000"})
    f.f_secretary = _FormStub()
    got = f._hand_proof(
        full=full, text=full, body=proof, sid=sid,
        plan={"plan_id": "0000", "problem_key": "PK"},
        sg={"sid": sid, "text": full, "kind": "lemma"},
        proposition=full,
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
        statement_full=full, statement_text=full, origin="own_result", source_lit_id=ensure_basis_lit(st), kind="conjecture",
        label=label, proof_text=body, proof_manuscript=manuscript,
        line_range={"label": str(got["manuscript_path"])},
        quote_reason="夹具：V 的 pending 签在盘上")
    assert first.get("ok") is True, first
    sid_out = str(first["stmt_id"])
    row = _row(st, sid_out)
    assert row["kind"] == "lemma", row
    return sid_out


# ---------------------------------------------------------------- a 业主语义主路径
def test_a_abandon_then_register_a_lemma_then_record_it_as_the_salvaged_asset(tmp_path):
    """a：放弃 T（不指任何引理）⇒ 事后注册 lemma L ⇒ 再把它记成这次放弃的可取之处。

    每一步都必须走得通，尤其不许出现"L 比 T 晚"的拒绝（那恰好否掉业主语义）。
    """
    st = _ws(tmp_path)
    _put(st, SID)
    # 第 1 步：以 difficulty 放弃 T，不指向任何引理。
    first = _abandon(st)
    assert first["checked"] is True and first["abandoned"] is True, first
    parsed0 = SA.parse_abandon_reason(_row(st)["quote_reason"])
    assert parsed0["complete"] is True and parsed0["salvaged"] == [], parsed0
    # 第 2 步：事后按正常流程注册引理 L（lemma，过形态闸）。
    lemma_id = _register_new_proposition(
        st, sid="s1", full=BODY_CHAIN, proof="证明：由 BL 不等式的对称性，极大值在 a^(2) 取到。",
        label="引理：BL 型积分不等式的中间一步")
    lemma = _row(st, lemma_id)
    assert lemma["created_at"] > _row(st, SID)["created_at"], (lemma["created_at"], T_AT)
    # 第 3 步：在后续动作里把它记为该次放弃的可取之处（改写标记，保留原放弃时刻）。
    second = _abandon(st, at=LATER_AT, salvaged=[{"label": lemma["label"],
                                                 "stmt_id": lemma_id}])
    assert second["checked"] is True, second
    row = _row(st, SID)
    parsed = SA.parse_abandon_reason(row["quote_reason"])
    assert parsed["complete"] is True and parsed["abandon_kind"] == "difficulty", parsed
    assert parsed["salvaged"][0]["stmt_id"] == lemma_id, parsed
    assert parsed["at"] == T_AT, "补记可取之处不改「几时放下的」那一刻"
    assert "after" not in str(second.get("refused") or ""), second


# ---------------------------------------------------------------- b 三种攻坚方向
def test_b_three_forms_registered_after_the_abandonment_are_accepted(tmp_path):
    """b：① 加强条件版 / ② 中间逻辑链 / ③ 负面事实 —— 各一条，都晚于 T，都不被拒。

    "被认成攻坚方向"落在盘上的形态是：它们是当真在册的 lemma（登记路 + 形态闸），
    并且能在后续动作里被记成这次放弃的可取之处（`salvaged` 收下）。
    """
    st = _ws(tmp_path)
    _put(st, SID)
    assert _abandon(st)["checked"] is True
    entries = []
    for i, (name, full) in enumerate(FORMS, start=1):
        lemma_id = _register_new_proposition(
            st, sid=f"s{i}", full=full,
            proof=f"证明（{name}）：由原证明第 {i + 1} 步取中间量，按 BL 不等式放缩。",
            label=f"夹具：{name}")
        lemma = _row(st, lemma_id)
        assert lemma["created_at"] > _row(st, SID)["created_at"], (name, lemma["created_at"])
        entries.append({"label": lemma["label"], "stmt_id": lemma_id})
        got = _abandon(st, at=LATER_AT, salvaged=entries)
        assert got["checked"] is True, (name, got)
        parsed = SA.parse_abandon_reason(_row(st, SID)["quote_reason"])
        assert [one["stmt_id"] for one in parsed["salvaged"]] == \
            [one["stmt_id"] for one in entries], (name, parsed)
        assert "after" not in str(got.get("refused") or ""), (name, got)


# ---------------------------------------------------------------- c 空壳
SHELL_CASES = [
    ("不在册", {"stmt_id": "000099"}),
    ("无证明", {"stmt_id": "000002", "kind": "lemma", "body": BODY_CHAIN, "proof": ""}),
]


@pytest.mark.parametrize("name, shape", SHELL_CASES)
def test_c_a_shell_lemma_is_refused_as_not_a_reviewable_lemma(tmp_path, name, shape):
    """c 负控：空壳（无证明 / 不在册）⇒ 仍被拒。

    拒绝理由必须是「它不成其为一条在册、可复核的引理」，不是"时间戳不对"：
    这一组夹具的 `created_at` 全都早于放弃时刻（若有时间戳判据反而放行）。
    """
    st = _ws(tmp_path)
    _put(st, SID)
    if shape["stmt_id"] != "000099":
        _put(st, shape["stmt_id"], kind=shape["kind"], body=shape["body"],
             proof=shape["proof"], created="2026-11-15T07:00:00+08:00")
    got = _abandon(st, salvaged=[{"label": name, "stmt_id": shape["stmt_id"]}])
    assert got["checked"] is False, got
    assert got["refused"] in (SA.ABANDON_SALVAGED_NOT_REVIEWABLE,
                              "abandon_salvaged_not_registered"), got
    assert "不成其为一条在册、可复核的引理" in str(got["why"]), got["why"]
    assert "时间戳" not in str(got["why"]).split("注意判据不是时间戳")[0], got["why"]
    assert _row(st, SID)["status"] == "active", _row(st, SID)


def test_c_the_bodyless_shape_is_caught_before_it_reaches_disk():
    """c 负控（正文空）：这一形态在落盘那一层就被 `schema` 挡了，本模块是第二道。

    为什么这样测：`status=active` 的行不许 `statement_full` 为空（`schema.Statement.validate`），
    所以"正文空"的空壳根本写不进盘 —— 写盘那一层已经拒了它。但判据不能只有那一层：
    `_salvaged_reviewability_problems` 是读侧的第二道（对任何读进来的行都要说得清
    "这一条立不立得住"），这里直调它把那一格钉住。
    """
    problems = SA._salvaged_reviewability_problems(
        {"statement_full": "", "statement_text": "", "proof_text": "证明：x",
         "created_by": "test"})
    assert problems == ["正文是空的"], problems


def test_c_a_shell_with_no_owner_is_refused(tmp_path):
    """c 负控（无人认领）：正文与证明都在、但 `created_by` 空 ⇒ 没人能对它负责 ⇒ 拒。"""
    st = _ws(tmp_path)
    _put(st, SID)
    basis_lit = ensure_basis_lit(st)     # 先落来路行：放进下面的事务里会撞锁
    with st.tx("statements", actor="") as tx:      # actor 空 ⇒ created_by 保持空
        tx.upsert("statements", {
            "stmt_id": "000002", "origin": "own_result", "source_lit_id": basis_lit, "kind": "lemma",
            "label": "无主引理", "statement_full": BODY_CHAIN,
            "statement_text": BODY_CHAIN, "proof_text": "证明：夹具正文。",
            "status": "active", "created_at": "2026-11-15T07:00:00+08:00",
            "created_by": "", "bits": {}, "quote_verified": None,
            "quote_reason": "夹具：现造"})
    got = _abandon(st, salvaged=[{"label": "无主引理", "stmt_id": "000002"}])
    assert got["checked"] is False, got
    assert got["refused"] == SA.ABANDON_SALVAGED_NOT_REVIEWABLE, got
    assert "无人认领" in str(got["why"]) and "可复核的引理" in str(got["why"]), got["why"]


# ---------------------------------------------------------------- d 反真空
class _GenuineSecretary:
    """秘书语义判定的恒真替身：`genuine` 与 `salvaged_from_proof` 都恒真。"""

    def __call__(self, **_kw) -> dict:
        """两问都返回"是"（不许有第三态）。"""
        return _genuine()


def test_d_stubbing_the_judgement_as_always_true_keeps_c_red(tmp_path):
    """d：把秘书语义判定打桩成恒真 ⇒ 空壳仍被拒（c 不是靠秘书那一问、更不是靠时间戳）。

    第二半是反真空：把「可复核」那一问也打桩掉 ⇒ 同一条空壳当场变绿 ——
    那才证明空壳的拒是这一问在承重。
    """
    st = _ws(tmp_path)
    _put(st, SID)
    _put(st, "000002", kind="lemma", body=BODY_CHAIN, proof="")   # 无证明的空壳
    always_true = _GenuineSecretary()
    got = _abandon(st, salvaged=[{"label": "空壳", "stmt_id": "000002"}],
                   judge=always_true)
    assert got["checked"] is False, got
    assert got["refused"] == SA.ABANDON_SALVAGED_NOT_REVIEWABLE, got
    # ---- 反真空：摘掉「可复核」这一问 ⇒ 同一笔变绿
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(SA, "_salvaged_reviewability_problems", lambda row: [])
        green = _abandon(st, salvaged=[{"label": "空壳", "stmt_id": "000002"}],
                         judge=always_true)
    finally:
        mp.undo()
    assert green["checked"] is True, (
        "反真空失效：打桩掉「可复核」这一问之后仍然拒 ⇒ 空壳那条负控证明不了它在承重", green)


def test_d_the_production_path_is_refused_even_with_a_constant_true_secretary(tmp_path):
    """d 的另一半：走生产的 `table.update` → 秘书那条路，恒真判定下空壳仍拒。

    这一条把 `Secretary.judge_abandon_difficulty` 整条换成恒真（不是 `apply_abandonment`
    的形参），证明闸不依赖调用方老实传判定面。
    """
    st = _ws(tmp_path)
    _put(st, SID)
    _put(st, "000002", kind="lemma", body=BODY_CHAIN, proof="")
    real = SEC.Secretary.judge_abandon_difficulty

    def _judge(self, **_kw):
        return _genuine()

    SEC.Secretary.judge_abandon_difficulty = _judge
    try:
        from agentflow.tools import table_tools
        from agentflow.tools.base import ToolRegistry

        reg = ToolRegistry(name="tables")
        reg.bound_role = "B"
        table_tools.register(reg, store=st)
        with CND.calling_as("t-sv", "B"):
            res = reg.call("table.update", table="statements", id=SID,
                           patch={"status": "abandoned"},
                           salvaged=[{"label": "空壳", "stmt_id": "000002"}], **DIFF)
    finally:
        SEC.Secretary.judge_abandon_difficulty = real
    assert res.ok is False, res
    assert dict(res.meta or {}).get("kind") == SA.ABANDON_SALVAGED_NOT_REVIEWABLE, res.meta
    assert _row(st, SID)["status"] == "active", _row(st, SID)
