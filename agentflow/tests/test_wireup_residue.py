# -*- coding: utf-8 -*-
"""WIREUP 路：把「只登记未修」里那几条会让人照着做错的活陷阱钉住（每条都带负控）。

本文件只钉九件。每件都是同一个形状：一个纯函数收集问题，先把今天盘上那一份喂进去
（正控，必须空），再把改前那一份喂进同一个函数（负控，必须非空）。只断言「今天没有
那句话」分不出「真修了」与「删光了」，所以负控是这条判据的一半。

1. F 包的 docstring 不再说「本框架尚未接线自动推理」（SYSCLEAN N1 / N7）；
2. `attack.step` 的 summary 不把 F 也说成「推理未接线」（N1 / N7 的提示词面）；
3. 角色文档不再把 F 列进「推理未接线」那一档（ROLE-SPECS 的工具行与 F-4）；
4. `install_d_tools` 那条「绕过角色断言 ⇒ 永远拿不到」的结论已被现盘取代（N8）；
5. C 的 boundary 说「出边是空的」，不说「可召唤边是空的」（ROLECLEAN-2 的 C3）；
6. F 的 stance 说「要 D 统筹就直接派 D」，不说「你没有到 D 的出边」（F6）；
7. `proof_chain` 的分析报告今天登记得成（C5，词表在 `schema.REPORT_KINDS`）；
8. `analyze_gaps` 没有死形参 `relation_ids`（ROLECLEAN-1 的 D3）；
9. `no_change` 是步级读数、不是产物（N7 的分界，乘积侧由 `attackround.PRODUCTS` 守）。

口径：这些行号在并行开发下几十分钟就漂，所以一律按符号名 / 文本锚取，不按行号。
"""
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import attackround as AR
from agentflow import capabilities as C
from agentflow import schema as S
from agentflow.agent_c import AgentC
from agentflow.agent_d import _support as DS
from agentflow.agent_d._support import analyze_gaps
from agentflow.agent_f._support import STEP_OUTCOMES as F_STEP_OUTCOMES
from agentflow.specs.c import SPEC as C_SPEC
from agentflow.specs.f import SPEC as F_SPEC
from agentflow.store import Store

REPO = pathlib.Path(__file__).resolve().parents[1]
ROLE_SPECS = REPO / "docs" / "ROLE-SPECS.md"
ROLE_SPECS_APPENDIX = REPO / "docs" / "ROLE-SPECS-APPENDIX.md"


def _flat(text: str) -> str:
    """去空白（含全角空格）：判据按子串收，排版换行不该改变结论。"""
    return re.sub(r"\s+", "", str(text or ""))


# ------------------------------------------------------------------ 1. F 的 docstring


def _f_docstring_problems(text: str) -> list[str]:
    flat = _flat(text)
    out: list[str] = []
    for stale in ("本框架尚未接线自动推理", "尚未接线自动推理"):
        if stale in flat:
            out.append(f"[N1] F 的包 docstring 还写着「{stale}」—— 2026-10-26 起 F 的推理"
                       "是它的工作方式（缝无条件装配，见 `agent_f/_support.py` 的 "
                       "`UNWIRED_OWNERS = (\"C\",\"D\")`），这句话是改前的状态")
    if "没有开关的说法" not in flat:
        out.append("[N1] 读不到业主原话「没有开关的说法」—— 现口径唯一的那句依据不见了")
    if "四件产物" not in flat:
        out.append("[N1] 读不到「四件产物」—— 每一轮的产物约束（`attackround.PRODUCTS`）"
                   "在 docstring 里没有落点")
    return out


def test_the_f_package_docstring_says_the_current_dispatch_rule():
    from agentflow import agent_f

    assert _f_docstring_problems(agent_f.__doc__ or "") == []


def test_negative_control_the_pre_fix_f_docstring_is_caught():
    old = (
        "2. `step` 按子目标的 `owner` 分派，而\"分派\"必须落在真的被接线的动作上：`E` ⇒\n"
        "   `AgentE.run_experiment`（带 `script_path` 时）；`A` / `B` ⇒ 各自的准入闸门 + 写请求\n"
        "   行；`C`/`D`/`F` ⇒ 没有自动推理可调，记 `outcome=\"no_change\"`。最后一行是刻意的：\n"
        "   本框架尚未接线自动推理，所以 F 只能如实写\"未推进\"；\n"
    )
    problems = _f_docstring_problems(old)
    assert problems, "负控真空：把改前那段 docstring 塞回去却没点红"


# ------------------------------------------------- 2. attack.step 的 summary（提示词面）

_ATTACK_STEP_NAMES = ("C/D/F", "C/D 无推理入口", "推理未接线")


def _attack_step_summary_problems(summary: str) -> list[str]:
    flat = _flat(summary)
    out: list[str] = []
    if "C/D/F" in flat:
        out.append("[N1/N7] `attack.step` 的 summary 还把 F 列在「推理未接线」那一档里"
                   "（C/D/F）—— F 自己推，C/D 才是没有推理入口的那两个")
    if "推理未接线" in flat:
        out.append("[N1/N7] `attack.step` 的 summary 还写着「推理未接线」—— 它读起来像"
                   "「F 也可能没接」，而 `UNWIRED_OWNERS` 只有 C/D")
    if "C/D" not in flat:
        out.append("[N1/N7] summary 里读不到 C/D 那一档 —— 那两条结构事实没有落点")
    if "no_change" not in flat:
        out.append("[N7] summary 里读不到 no_change（步级读数）—— 读者会以为这一轮没有读数")
    if "product" not in flat:
        out.append("[N7] summary 里读不到 `product` —— 交证明那条路没有指路")
    return out


def test_the_attack_step_summary_does_not_call_f_unwired():
    registry = __import__("agentflow.tools", fromlist=["build_registry"]).build_registry().registry
    entry = next(d for d in registry.describe() if d["name"] == "attack.step")
    assert _attack_step_summary_problems(entry["summary"]) == [], entry["summary"]


def test_negative_control_the_pre_fix_attack_step_summary_is_caught():
    old = ("推进攻坚计划的一轮：按 owner 分派（E 做实验 / A 提检索 / B 提重抽取），"
           "C/D/F 的推理未接线则如实记 no_change。交证明用 `product`。")
    assert _attack_step_summary_problems(old), "负控真空：旧 summary 塞回去却没点红"


# ----------------------------------------------------------- 3. 角色文档里的同一句话


def _role_doc_unwired_problems(text: str) -> list[str]:
    flat = _flat(text)
    out: list[str] = []
    if "C/D/F的推理未接线" in flat:
        out.append("[N1/N7] 角色文档还写着「C/D/F 的推理未接线」—— 现盘 `UNWIRED_OWNERS`"
                   " 只有 C/D，F 的推理是它的工作方式")
    if "C/D没有可自动调用的推理入口" not in flat:
        out.append("[N1/N7] 角色文档里读不到 C/D 那一档的现口径"
                   "（C/D 没有可自动调用的推理入口 ⇒ 落 dead_end + 记 no_change）")
    return out


def test_the_role_specs_do_not_put_f_in_the_unwired_bucket():
    assert _role_doc_unwired_problems(ROLE_SPECS.read_text(encoding="utf-8")) == []


def test_negative_control_the_pre_fix_role_specs_rows_are_caught():
    old = ("| F-4 | **C/D/F 的推理未接线时如实记 `no_change`，绝不假装做了** | "
           "`attack.step` 的 `summary` 逐字 |")
    assert _role_doc_unwired_problems(old), "负控真空：旧 ROLE-SPECS 那一行塞回去却没点红"


# --------------------------------------------------- 4. install_d_tools 的历史结论（N8）


class _NoStore:
    """`_fallback_trace_tools` 只在调用工具时才碰 store —— 读 roles 不需要它。"""

    root = "."

    def rows(self, name):  # noqa: D401 —— 替身：真读到就说明装配路径变了
        raise AssertionError("这个替身不该被读到表")


def _install_bypass_problems(doc_text: str) -> list[str]:
    flat = _flat(doc_text)
    out: list[str] = []
    if "永远拿不到它们" in flat:
        out.append("[N8] 文档还在下「永远拿不到它们」这个结论 —— 现盘 3 个替身的 roles 是"
                   " (\"C\",\"D\")、`install_d_tools` 末尾调 `validate_tool_roles`")
    return out


def test_install_d_tools_is_not_described_or_implemented_as_bypassing_the_role_check():
    src = inspect.getsource(DS.install_d_tools)
    assert "validate_tool_roles(" in src, (
        "`install_d_tools` 不再在装配末尾跑 `validate_tool_roles` ⇒ 角色名拼错会静默漏工具")
    roles = [tuple(getattr(getattr(fn, "__tool_spec__", None), "roles", ()) or ())
             for fn in DS._fallback_trace_tools(_NoStore())]
    assert roles and all(r == ("C", "D") for r in roles), (
        f"3 个内置替身的 roles 不再与 schema.ROLES 逐字一致：{roles}")
    assert _install_bypass_problems(ROLE_SPECS.read_text(encoding="utf-8")) == []


def test_negative_control_the_pre_fix_install_d_tools_claim_is_caught():
    old = ("> 那 3 个替身的 `roles=(\"agent-C\",\"agent-D\")` 带 ``agent-`` 前缀，"
           "而 `install_d_tools` 又直接构造注册表 ⇒ `for_role(\"C\")`/`for_role(\"D\")` "
           "永远拿不到它们。")
    assert _install_bypass_problems(old), "负控真空：旧结论塞回去却没点红"


# --------------------------------------------------------------------- 5. C3 的措辞


def _c_boundary_problems(text: str) -> list[str]:
    flat = _flat(text)
    out: list[str] = []
    if "可召唤边" in flat:
        out.append("[C3] C 的 boundary 还写着「可召唤边」—— 它既可读成出边、也可读成入边，"
                   "而 C 的 summonable=True、`D → C` 在 ALLOWED_EDGES 里 ⇒ 按入边读是假话")
    if "出边是空的" not in flat:
        out.append("[C3] 读不到「出边是空的」—— 出边为空这件事没有写清楚")
    return out


def _brief_text(role: str, section: str) -> str:
    """从唯一渲染口取某一格正文（`brief_sections` 返回 `[(段名, order, 正文)]`，段名是大写）。

    段名带前缀（`ROLE_BOUNDARY` / `STANCE` / `ROLE_POLICY` …）⇒ 按后缀收，
    不按精确名收：判据要钉的是"那一格正文"，不是"段名怎么拼"。
    """
    want = str(section or "").upper()
    return "\n".join(text for name, _order, text in AP.brief_sections(role)
                     if str(name).upper() == want or str(name).upper().endswith("_" + want))


def test_the_c_boundary_says_out_edges_not_summon_edges():
    boundary = _brief_text("C", "boundary")
    assert boundary, "C 的 boundary 渲染不出来（段名变了？）"
    assert _c_boundary_problems(boundary) == [], boundary
    # 这句话成立的前提：C 真的唤不起任何人、而别人唤得起它
    assert C_SPEC.edges == ()
    assert C_SPEC.summonable is True
    assert "C" in C.ALLOWED_EDGES["D"]


def test_negative_control_the_pre_fix_c_boundary_is_caught():
    old = ("你是只读角色 —— 对其它智能体的产出只读：不许改别人的稿、台账、报告，"
           "也不许直接向别人发请求（你的可召唤边是空的）。")
    assert _c_boundary_problems(old), "负控真空：旧括号塞回去却没点红"


# --------------------------------------------------------------------- 6. F6 的措辞


def _f_stance_problems(text: str) -> list[str]:
    flat = _flat(text)
    out: list[str] = []
    if "没有到D的出边" in flat:
        out.append("[F6] F 的 stance 还写着「没有到 D 的出边」—— 同一份 prompt 的另一行"
                   "写着 `F → D` 是直接边，`SPEC.edges` 也含 `'D'`")
    if "conductor.escalate写进召唤者的收件箱" in flat:
        out.append("[F6] F 的 stance 还在教「用 conductor.escalate 找 D 统筹」—— "
                   "escalate 是向 M 请求指导那一格，不是找 D 的替代路")
    if "要D统筹就直接派D" not in flat:
        out.append("[F6] 读不到「要 D 统筹就直接派 D」—— 旧句删了、新路没写")
    return out


def test_f_is_told_it_has_a_direct_edge_to_d():
    stance = _brief_text("F", "stance")
    assert stance, "F 的 stance 渲染不出来（段名变了？）"
    assert _f_stance_problems(stance) == [], stance
    assert "D" in F_SPEC.edges


def test_negative_control_the_pre_fix_f_stance_is_caught():
    old = ("允许提猜想：把猜想写成可判定的形式，然后交给 E 去验"
           "（要 D 统筹就用 `conductor.escalate` 写进召唤者的收件箱 —— 你没有到 D 的出边）。")
    assert _f_stance_problems(old), "负控真空：旧 stance 塞回去却没点红"


# ------------------------------------------------- 7. C5：proof_chain 报告登记得成


def _fresh_store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def test_proof_chain_reports_are_registered(tmp_path: pathlib.Path):
    st = _fresh_store(tmp_path)
    c = AgentC(st)
    rep = c._report("proof_chain", "req", {}, summary="一条链的读数",
                    payload={"k": 1}, markdown="正文")
    assert rep.report_id, "proof_chain 的报告又没有登记（`_report` 的 ok 分支恒不命中）"
    rows = [r for r in st.rows("analysis_reports")
            if str(r.get("kind") or "") == "proof_chain"]
    assert len(rows) == 1 and rows[0].get("report_id") == rep.report_id, rows
    assert "proof_chain" in S.REPORT_KINDS


def test_negative_control_without_the_vocab_entry_it_is_not_registered(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(S, "REPORT_KINDS",
                        tuple(k for k in S.REPORT_KINDS if k != "proof_chain"))
    st = _fresh_store(tmp_path)
    c = AgentC(st)
    rep = c._report("proof_chain", "req", {}, summary="一条链的读数",
                    payload={"k": 1}, markdown="正文")
    assert not rep.report_id, "词表里没有这一档、报告却登记了 ⇒ 判据钉的不是词表那一格"
    assert [r for r in st.rows("analysis_reports")
            if str(r.get("kind") or "") == "proof_chain"] == []


# ------------------------------------------- 8. D3：analyze_gaps 没有死形参 relation_ids


def _analyze_gaps_signature_problems(params: list[str]) -> list[str]:
    out: list[str] = []
    if "relation_ids" in params:
        out.append("[D3] `analyze_gaps` 还有死形参 relation_ids —— 函数体一次都不读它，"
                   "调用点却为它现造一份号表")
    if params and params[0] != "relations":
        out.append(f"[D3] 第一个位置参数不是 relations（实际 {params[0]!r}）—— "
                   "关系行才是判据的输入")
    return out


def test_analyze_gaps_has_no_dead_first_parameter():
    params = list(inspect.signature(analyze_gaps).parameters)
    assert _analyze_gaps_signature_problems(params) == [], params
    # 行为面：旧调用形状必须当场 TypeError（而不是悄悄忽略那个实参）
    rels = [{"relation_id": "0000", "statement": "A 是 B", "quote_verified": None}]
    with pytest.raises(TypeError):
        analyze_gaps(["0000"], rels, keywords=["x"], degree=1)  # type: ignore[call-arg]


def test_negative_control_the_pre_fix_signature_is_caught():
    assert _analyze_gaps_signature_problems(["relation_ids", "relations"]), (
        "负控真空：旧签名喂进同一个判据却没点红")


# ------------------------------------------------- 9. N7 的分界：no_change 是读数不是产物


def _no_change_boundary_problems(products: tuple[str, ...],
                                 outcomes: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    if "no_change" in products:
        out.append("[N7] 一轮的产物里出现了 no_change —— 它在 2026-10-19 那一批被换成"
                   "四件产物（reduction / proof / counterexample_request / dead_end），"
                   "回到产物里就是那个被根除的形态")
    if "no_change" not in outcomes:
        out.append("[N7] 步级读数的词表里没有 no_change —— 那会把「这一轮没有新事实」"
                   "这条真读数一起删掉（它是读数，不是产物）")
    return out


def test_no_change_is_a_step_reading_and_never_a_product():
    assert _no_change_boundary_problems(AR.PRODUCTS, F_STEP_OUTCOMES) == []
    assert AR.PRODUCTS == ("reduction", "proof", "counterexample_request", "dead_end")
    with pytest.raises(AR.RoundError):
        AR.parse_round('{"product": "no_change", "strategy": "归约", "why_strategy": "x"}')
    with pytest.raises(AR.RoundError):
        AR.parse_round('{"outcome": "no_change"}')


def test_negative_control_putting_no_change_back_into_the_products_is_caught():
    dirty = tuple(AR.PRODUCTS) + ("no_change",)
    assert _no_change_boundary_problems(dirty, F_STEP_OUTCOMES), (
        "负控真空：把 no_change 塞回产物里却没点红")
    assert _no_change_boundary_problems(AR.PRODUCTS, ("progress", "blocked")), (
        "负控真空：把步级读数里的 no_change 抠掉却没点红")
