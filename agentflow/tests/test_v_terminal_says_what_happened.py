# -*- coding: utf-8 -*-
"""`review_passes[*].terminal` 必须说出真实结局（2026-11-01）。

## 病（题面：V 的台账行 `terminal` 字段在说谎）

`verify_proof` 的连判循环里，`if not VR.row_signable(once["row"])`（gate 支）排在
`if VR.read_verdict(once["row"]) != "成立"`（verdict 支）之前。而 `row_signable` 的第一句
就是 `read_verdict(row) != "成立" ⇒ False`（`verifications.row_signable`）—— 于是
"V 自己判了有毛病"的行必然先在 gate 断掉：

- `terminal="verdict"` 从 `d839936b`（2026-10-30 插入 gate 支）起是不可达的（死档）；
- 真机上 81 的 8 行（8/8 `verdict=有毛病`、`axis=fault`）全部被标成 `terminal="gate"`，
  而 gate 的语义是"结论成立、但这一签自己签不住" ⇒ 读的人把「有毛病」读成「成立但签不住」；
- 同一份返回里还自相矛盾：`sign_issuance.reason` 说"结论是 '有毛病'"，日志却说
  "这一签的结论是「成立」…… 这不是有毛病"。

全仓历史 `terminal` 读数只有这 8 行（及其 3 份副本，共 32 条 pass 行），100% 读错。

## 判据（改前红 → 改后绿）

| 编号 | 它要证明的事 | 改前怎么红 |
|---|---|---|
| s1 | 四个结局各出现一次、各拿自己的 terminal：成立→`signed`、有毛病→`verdict`/`fault`、成立但签不住→`gate`、不适用（已经签过）→没有 `review_passes` | 有毛病（V 自判）拿到 `gate` |
| s2 | 判「有毛病」的行，terminal 绝不在 gate 族；反过来 `terminal="gate"` 蕴含这一行的结论读出来是「成立」 | 8/8 有毛病行被标 gate |
| s3 | 反真空：a) terminal 取值集合 == 代码里所有可能赋值的集合（AST）；b) 每个取值都有活证（同文件真跑出来）；c) 分支序 =「结局先判（verdict < fault）、签不签得动后判（gate 在 signed 前）、gate 只吃成立行（gate 在 fault 后）」 | `verdict` 没有活证；`gate > fault` 不成立 |
| s4 | 同一返回里 `sign_issuance.reason` / 日志 / terminal 不许互相矛盾（有毛病行不许出现"结论是「成立」"、不许说"这不是有毛病"） | 有毛病行的日志正是这两句 |

## 这些替身量的是什么（别当成"真模型跑过"）

V 的审阅缝（`_ReviewSeam`）与秘书缝（`_Seam`）都是预置剧本，与
`test_v_reviews_three_times_before_signing.py` 同一套：它们证明的是"每一问落在哪个分支、
每种结局拿到哪个标签"，真模型一次都不调。八个场景把 `terminal` 的七个取值连同
`""`（没形成终局）全部真跑一遍 —— 没有活证的取值就是死档，这正是 s3b 要钉的。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from unittest import mock

import pytest

from agentflow import conductor as CND
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_v import AgentV

from test_v_reviews_three_times_before_signing import (
    PROOF, REL, SID, _axis, _ReviewSeam, _Seam, _put, _secretary, _ws)

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src" / "agentflow" / "agent_v" / "core.py"

#: 终态词表（`core.py` 里 `stopped` 的枚举）。p247 删掉了 `verdict` 那一档：V 的判词只是
#: 陈述，不能再拿它当一条打回；打回只有秘书判 fault 这一条路。
#: 2026-11-06（业主裁定 3）：这一格改叫 `rejected` —— 同一种结局（打回）在未在册两支里
#: 本来就叫 `rejected`，在在册这一支叫 `fault`，读的人要按分支猜名字；现在三支同一个词。
TERMINAL_VOCAB = frozenset({"", "ledger", "gate", "signed", "rejected", "unjudged"})

CLEAN = json.dumps({"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。",
                    "findings": []}, ensure_ascii=False)
#: 秘书判 fault，V 自己的结论词仍写「成立」（这一档今天走 terminal="rejected"）。
REVIEWED_FAULT = json.dumps({"verdict": "成立", "why": "整体能走通；只是第 2 步的记号没有定义。",
                             "findings": []}, ensure_ascii=False)
#: V 自己判「有毛病」（81 那 8 行的形状）。秘书这一转判 clean ⇒ 终局只由 V 的结论决定。
CONDEMNED_BY_V = json.dumps(
    {"verdict": "有毛病", "defect_step": 2,
     "why": "第 2 步把未证的 (O1) 当作依据，该步不成立。",
     "findings": [{"detail": "第 2 步以未证的 (O1) 为依据", "kind": "引用未证命题",
                   "level": "error", "step": 2}]}, ensure_ascii=False)
#: 结论「成立」、但有未解决的 error ⇒ 这一行自己签不住（gate 的正身）。
CLEAN_WITH_ERROR = json.dumps(
    {"verdict": "成立", "why": "没找到缺陷；但引述的那一步记着一条未解决的 error。",
     "findings": [{"detail": "第 2 步的引述与原文不一致", "kind": "引述",
                   "level": "error", "step": 2}]}, ensure_ascii=False)
WASHED = {"text": "第 2 步的记号没有定义：请补上记号说明之后再送 V 重签。", "step": 2,
          "findings": [{"quote": "第 2 步的记号没有定义", "why": "记号没定义就没法核这一步"}]}

#: 判「有毛病」= 秘书的语义轴是 fault（p247：V 的 `verdict` 只是陈述，不算）。

def _condemned(row: dict) -> bool:
    return VR.secretary_axis(row) == "fault"


def _run(tmp: Path, *, replies: list[str], answers: dict, twice: bool = False,
         patch=None) -> dict:
    """跑一趟 `verify_proof`，把这一趟的读数收成一个 dict（不调真模型）。"""
    st = _ws(tmp)
    _put(st)
    review = _ReviewSeam(list(replies))
    seam = _Seam(answers)
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, seam))

    def _once() -> dict:
        # 2026-11-04（业主裁定 甲）：在册命题送审必须带手稿。`_put` 已经把被审的那一份
        # 正文落成 `reports/f-proof-<号>.md`（`## 证明` 逐字一致、`## 依赖` 空表），
        # 这里带路径送审 —— 终态判据读的仍是同一趟连判，一个字没改。
        # 2026-11-08：签只落在稿上；落块要收方秘书，所以造真实送审的挂点（parent=F）。
        with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                            parent_role="F"):
            return agent.verify_proof(SID, proof_text=PROOF, proof_manuscript=REL)

    if patch is None:
        got = _once()
        if twice:
            got = _once()
    else:
        with patch:
            got = _once()
            if twice:
                got = _once()
    rows, bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not bad, bad
    passes = list(got.get("review_passes") or [])
    return {
        "got": got,
        "passes": passes,
        "terminal": (passes[-1].get("terminal") if passes else None),
        "row": (dict(rows[-1]) if rows else {}),
        "logs": list(agent.logs),
        "model_calls": review.asked(),
    }


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory) -> dict[str, dict]:
    """八个场景：把 `terminal` 的七个取值连同 `""` 各跑出一个活证。"""
    base = tmp_path_factory.mktemp("v_terminal")
    out: dict[str, dict] = {}

    # 1) 成立 ⇒ signed（三转 clean + 秘书发签）
    out["signed"] = _run(base / "s1", replies=[CLEAN], answers={
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})

    # 2) 有毛病（秘书判 fault，V 的结论词仍写成立）
    out["fault_by_secretary"] = _run(
        base / "s2", replies=[CLEAN, REVIEWED_FAULT], answers={
            "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN), _axis(SEC.V_REPLY_FAULT)],
            "wash_v_reply": [WASHED]})

    # 3) V 自己写「有毛病」、秘书判 clean —— p247：V 的判词只是陈述，轴是 clean；
    #    这一行因自己的未解决 error 签不住 ⇒ terminal=gate（不是"V 判的打回"）。
    out["fault_by_v"] = _run(base / "s3", replies=[CONDEMNED_BY_V], answers={
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
        "wash_v_reply": [WASHED]})

    # 4) 成立但签不住（有未解决的 error；秘书这一转不发签）
    out["gate"] = _run(base / "s4", replies=[CLEAN_WITH_ERROR], answers={
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
        "sign_issuance": [_axis(SEC.SIGN_WITHHOLD)]})

    # 5) 秘书这一问没查成
    out["unjudged"] = _run(base / "s5", replies=[CLEAN], answers={
        "v_reply_defect": [{"checked": False, "decision": "",
                            "reason": "夹具：这一问没答上来"}],
        "sign_issuance": [_axis(SEC.SIGN_WITHHOLD)]})

    # 6) 不适用：已经签过 ⇒ 短接，一转都不判（terminal 不在场）
    out["not_applicable"] = _run(base / "s6", replies=[CLEAN], answers={
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)]}, twice=True)

    # 7) 台账那一行没落地（只在装配坏掉时出现）
    real = VR.record_verification

    def _lost(*args, **kwargs):
        row = dict(real(*args, **kwargs))
        row["checked"] = False
        row["reason"] = "夹具：台账那一行被撤回"
        return row

    out["ledger_lost"] = _run(
        base / "s7", replies=[CLEAN], answers={
            "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
            "sign_issuance": [_axis(SEC.SIGN_WITHHOLD)]},
        patch=mock.patch.object(VR, "record_verification", _lost))

    # 8) 连判跑完两头都没有（门槛病态：这里把门槛压到 1，秘书仍不发签）
    out["no_terminal"] = _run(
        base / "s8", replies=[CLEAN], answers={
            "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
            "sign_issuance": [_axis(SEC.SIGN_WITHHOLD)]},
        patch=mock.patch.object(VR, "SIGN_STREAK_NEED", 1))
    return out


# ============================================================ s1：四个结局各拿自己的 terminal

def test_s1_the_four_outcomes_each_get_their_own_terminal(outcomes):
    """四个结局各出现一次、各拿自己的 terminal。

    不适用那一档单独判（它没有 `review_passes`，见 s1b）：给它编一个 terminal 就是把
    "这一趟没审"写成"审出了某个结局"。
    """
    want = {"signed": "signed",
            "fault_by_secretary": "rejected",
            # p247：V 写「有毛病」不再自己构成打回；轴是 clean，签不住由机械闸接住。
            "fault_by_v": "gate",
            "gate": "gate"}
    got = {name: outcomes[name]["terminal"] for name in want}
    assert got == want, (
        "四个结局的 terminal 不对："
        + json.dumps(got, ensure_ascii=False)
        + "（期望 " + json.dumps(want, ensure_ascii=False) + "）")


def test_s1b_not_applicable_has_no_terminal_at_all(outcomes):
    """不适用（已经签过 ⇒ 短接）：`review_passes` 为空 —— terminal 不在场，不许造一个假终局。"""
    na = outcomes["not_applicable"]
    assert na["passes"] == [], na["passes"]
    assert na["terminal"] is None, na["passes"]
    assert str(na["got"].get("reason") or "") == "already_signed", na["got"].get("reason")


# ============================================================ s2：有毛病不许被标成 gate

def test_s2_a_condemned_row_is_never_labelled_gate(outcomes):
    """判「有毛病」的行，terminal 绝不在 gate 族；反过来 gate 只许出现在"成立"的行上。"""
    for name in ("fault_by_secretary",):
        o = outcomes[name]
        assert _condemned(o["row"]), f"{name} 的夹具不是一条有毛病行：{o['row']}"
        term = str(o["terminal"])
        assert term != "gate" and not term.startswith("gate:"), (
            f"{name}：这一行判的是有毛病（verdict={o['row'].get('verdict')!r}、"
            f"axis={VR.secretary_axis(o['row'])!r}），terminal 却是 {term!r} —— "
            "读的人会把「有毛病」读成「成立但签不住」")
    for name, o in outcomes.items():
        if o["terminal"] == "gate":
            assert VR.secretary_axis(o["row"]) == "clean", (
                f"{name}：terminal='gate' 蕴含这一行的轴是 clean（签不住的是机械闸），"
                f"实得 axis={VR.secretary_axis(o['row'])!r}")


# ============================================================ s3：反真空（词表 / 活证 / 分支序）

def _verify_proof_node() -> ast.FunctionDef:
    tree = ast.parse(CORE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "verify_proof":
            return node
    raise AssertionError("core.py 里找不到 `verify_proof`")


def _loop_body() -> list[ast.stmt]:
    for node in ast.walk(_verify_proof_node()):
        if isinstance(node, ast.For) and "need" in ast.dump(node.iter):
            return list(node.body)
    raise AssertionError("`verify_proof` 里找不到连判循环（`for ... in range(1, need + 1)`）")


def _ast_terminal_values() -> set[str]:
    """`terminal` 一格可能被赋的全部取值：`stopped = "<字面量>"` + 字典初值 `"terminal": ""`。"""
    vals: set[str] = set()
    for node in ast.walk(_verify_proof_node()):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and any(isinstance(t, ast.Name) and t.id == "stopped"
                        for t in node.targets)):
            vals.add(node.value.value)
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "terminal"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    vals.add(v.value)
    return vals


def _branch_indexes() -> dict[str, int]:
    """连判循环体里六个 `if` 的下标（按出现次序）。"""
    idx: dict[str, int] = {}
    for i, stmt in enumerate(_loop_body()):
        if not isinstance(stmt, ast.If):
            continue
        dump = ast.dump(stmt.test)
        if "row_signable" in dump:
            idx["gate"] = i
        elif "read_verdict" in dump:
            idx["verdict"] = i
        elif "'judgment'" in dump and "'checked'" in dump:
            idx["unjudged"] = i
        elif "'row'" in dump and "'checked'" in dump:
            idx["ledger"] = i
        elif "'issue'" in dump:
            idx["signed"] = i
        elif "'fault'" in dump:
            idx["fault"] = i
    return idx


def test_s3a_terminal_vocabulary_equals_what_the_code_can_assign():
    """反真空 a：`terminal` 的取值集合 == 代码里所有可能赋值的集合（有增删必须同步改判据）。"""
    assert _ast_terminal_values() == TERMINAL_VOCAB, (
        "AST 扫出来的 terminal 取值与冻结词表不一致："
        f"{sorted(_ast_terminal_values())} vs {sorted(TERMINAL_VOCAB)}")


def test_s3b_every_terminal_value_has_a_live_witness(outcomes):
    """反真空 b：每个取值都要有一个真跑出来的场景 —— 没有活证的值就是死档。"""
    live = {o["terminal"] for o in outcomes.values() if o["passes"]}
    assert live == TERMINAL_VOCAB, (
        "terminal 有取值没有活证（死档）：" + repr(sorted(TERMINAL_VOCAB - live))
        + "；活证：" + repr(sorted(live)))


def test_s3c_the_branch_order_puts_the_outcome_before_the_signability():
    """反真空 c：分支序的三条结构断言（AST，不看注释）。

    a) verdict < fault：结局先判（V 自己判的有毛病不许被秘书那一档改写）；
    b) gate < signed：签不签得动要先判 —— 否则 (gate ∧ signed) 那一格会从 `gate`
       变成 `signed`（位没翻却报签了，那是新的谎）；
    c) gate > fault：gate 只吃"成立但签不住"的行，不许抢在"有毛病"前面。
    """
    idx = _branch_indexes()
    assert set(idx) == {"ledger", "fault", "unjudged", "gate", "signed"}, idx
    assert idx["ledger"] == min(idx.values()), f"台账那一支必须最先判：{idx}"
    assert idx["fault"] < idx["unjudged"], (
        f"fault 支({idx['fault']}) 必须排在 unjudged 支({idx['unjudged']}) 之前")
    assert idx["unjudged"] < idx["gate"], (
        f"unjudged 支({idx['unjudged']}) 必须排在 gate 支({idx['gate']}) 之前 ⇒ "
        "没有轴的行走不到 gate（它连\"签不签得动\"都没有判）")
    assert idx["gate"] < idx["signed"], (
        f"gate 支({idx['gate']}) 必须排在 signed 支({idx['signed']}) 之前 ⇒ "
        "否则（轴 clean 但签不住）会被报成「签上了」")


# ============================================================ s4：同一返回里的文本不许打架

#: "断言结论是成立"的两种写法（`stop_why` 与 `_terminal_reason` 都用中文引号/`repr`）。
_CLAIMS_ESTABLISHED = re.compile(r"结论是\s*[「'\"']成立")


def test_s4_the_reason_and_the_pass_do_not_contradict_each_other(outcomes):
    """有毛病行的文本里：不许说"结论是「成立」"，不许说"这不是有毛病"。

    改前 `gate` 支的 `stop_why` 逐字是「这一签的结论是「成立」，但它自己签不住……（这不是
    有毛病，也不是没查成）」—— 而同一份返回里 `sign_issuance.reason` 说「结论是 '有毛病'」。
    同一份读数自相矛盾，读的人只能挑一个信。
    """
    for name, o in outcomes.items():
        if not _condemned(o["row"]):
            continue
        blob = "\n".join([
            str((o["got"].get("sign_issuance") or {}).get("reason") or ""),
            str(o["got"].get("reason") or ""),
            str(o["got"].get("detail") or ""),
            *o["logs"],
        ])
        assert not _CLAIMS_ESTABLISHED.search(blob), (
            f"{name}：这一行判的是有毛病，文本里却说结论是「成立」：\n{blob}")
        assert "这不是有毛病" not in blob, (
            f"{name}：这一行判的是有毛病，文本里却说「这不是有毛病」：\n{blob}")
    # 反向：秘书判 fault 时，发签理由必须点名有毛病（不许对读者沉默）。
    o = outcomes["fault_by_secretary"]
    assert o["terminal"] == "rejected", o["passes"]
    reason = str((o["got"].get("sign_issuance") or {}).get("reason") or "")
    assert "有毛病" in reason, reason
