# -*- coding: utf-8 -*-
"""p205（2026-10-27 第二批）那一批提示词与工具声明的逐句对拍。

## 这个文件修的是什么

那一批新增/改动了九件 `clock.*`、`conductor.retire_child` 的四格、`conductor.guide`
的链式读数、`table.get` / `table.list` 的 `route` / `proof_routes`、以及
`verify.verify_proof` 的引用核实三格。它们各自的单测都是绿的，但绿回答的是
「这条路径跑得通」，不是「提示词里那句话与代码是同一套口径」。两类缺口因此不会被
任何既有判据抓到：

  1. 提示词里的例子与代码的输出逐字不同（模型照抄那个例子去断言，必错）；
  2. 声明（`returns` 就是模型看得见的 description）漏掉实现真给的键 ——
     `tests/test_tools_returns_declaration.py` 的两条键集合判据都只走「探针那一条分支」，
     而本次新增的几格恰好长在探针走不到的分支上（成功支 / 预算拒收支）。

## 判据分两档，强度都已升级

- 不加标记的：守的是「别把已经对齐的东西改漂」（改动即红）；
- 原先带 `xfail(strict=True)` 的两条（`delivered_to` 的形状、`clock.wait_any` 的行为口径）
  已在 p206 收口那一批补齐落点：strict 的语义正是"修好了就 XPASS 变红，提醒摘标记"，
  于是本批把标记摘掉，两条现在是不加标记的判据（15 passed / 0 xfailed）。
  历史缺口逐字留在各自的 docstring 里 —— 那不是"允许失败"，是"这个坑有多深"的读数。

判据只读：读提示词渲染、读模块常量、在 tmp 工作区跑一次工具；不改功能代码、
不改提示词正文、不碰 golden 与 `PROMPT_VERSION`。
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from agentflow import agent_prompts as AP
from agentflow import attackround as AR
from agentflow import clock as C
from agentflow import conductor as CD
from agentflow import depsection as DS
from agentflow import schema as S
from agentflow.agent_v import AgentV
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry

#: 声明里「键名」的唯一取法（与 `tests/test_tools_audit_fixes.parse_declared_keys` 同一条正则）。
_KEY = re.compile(r"'([a-z_][a-z0-9_]*)'")


def _declared(registry, name: str) -> set:
    return set(_KEY.findall(registry.get(name).returns))


@pytest.fixture(scope="module")
def registry():
    return build_registry().registry


@pytest.fixture(scope="module")
def prompts(registry):
    return {role: AP.system_prompt(role, registry=registry) for role in AP.roles_covered()}


def _tmp_workspace() -> tuple:
    tmp = Path(tempfile.mkdtemp(prefix="aftruth-"))
    store = Store(tmp)
    store.init()
    return store, tmp


# ---------------------------------------------------------------- 不加标记的判据


def test_every_role_carries_the_same_clock_paragraph(prompts) -> None:
    """时钟那一段在十个角色里逐字相同（M 把它并进了自己的挂机条，故不在内）。

    为什么值得一条：这一段是同一份文本在十个 spec 文件里各存一份，漂一个字都不会
    有任何东西报 —— 而模型按「我这一格的政策」行动，两个角色拿到两套口径就是两套规则。
    """
    begins = "**要等就用时钟，别空转**"
    ends = "**计时只有时钟这一处**"
    bodies = {}
    for role in ("A", "B", "C", "D", "E", "F", "G", "H", "L", "V"):
        text = prompts[role]
        start = text.find(begins)
        stop = text.find(ends, start)
        assert start >= 0 and stop > start, f"{role} 的时钟段不见了"
        bodies[role] = text[start:stop]
    first = bodies["A"]
    assert len(first) > 200, "时钟段短得不像那一段（判据可能抽到了别处）"
    for role, body in bodies.items():
        assert body == first, f"{role} 的时钟段与 A 的不同"


def test_every_role_is_told_how_to_supply_a_missing_purpose(prompts) -> None:
    """十一个角色的提示词都要说清「漏填目的不报错、补一句走 timer_purpose」。"""
    for role, text in prompts.items():
        assert "purpose_missing" in text, f"{role} 没被告知读数里有 purpose_missing"
        assert "clock.timer_purpose" in text, f"{role} 没被告知补目的的入口"


def test_the_due_message_skeleton_in_the_prompt_is_the_one_clock_prints(prompts) -> None:
    """提示词里那句到点示例的骨架，与 `clock.due_message` 的骨架逐字同形。

    骨架取「三样都在同一句里」的那三处前缀与括号。单位的取法（分钟 / 分）不在这条里
    —— 那一格由下面那条判据（`human_sec(1180)` 逐字）单独钉。
    """
    sample = C.due_message(purpose="等 D1 交回命题 3 的证明", waited_sec=1180,
                           created_at="2026-01-01T14:02:10+08:00",
                           fired_at="2026-01-01T14:21:50+08:00")
    assert sample.startswith("时间到："), sample
    for needle in ("｜等了 ", "（起于 ", "，到于 "):
        assert needle in sample, f"due_message 的骨架里没有 {needle!r}：{sample}"
        for role in ("A", "M"):
            assert needle in prompts[role], f"{role} 的示例缺 {needle!r}"
    patrol = C.due_message(purpose="周期性巡查", waited_sec=None, created_at=None,
                           fired_at=None, every_sec=1200, fires=1)
    assert patrol == "巡查时间到：周期性巡查｜每 20 分钟一次（第 1 次）", patrol
    # M 那一格对巡视的写法：唯一的写法是 every_sec=1200 加 purpose，不许写成「睡 20 分钟」。
    assert "every_sec=1200" in prompts["M"] and "周期性巡查" in prompts["M"]


def test_e_policy_quotes_budget_unreadable_note_verbatim(prompts) -> None:
    """E 那一段必须逐字含 `attackround.BUDGET_UNREADABLE_NOTE`（同一句话，不许各写一份）。"""
    note = AR.BUDGET_UNREADABLE_NOTE
    assert note, "常量空了 —— 这条判据会变成真空通过"
    assert note in prompts["E"], "E 的政策里没有那句原话"
    others = sorted(role for role, text in prompts.items() if note in text and role != "E")
    assert not others, f"那句话只该在 E 那一格，实际还出现在 {others}"


def test_f_dependency_table_example_parses_with_the_real_parser(prompts) -> None:
    """F 提示词里那张四列表的例子，喂给真解析器必须一把过（列名 / 顺序 / 形状）。"""
    text = prompts["F"]
    start = text.find(DS.SECTION_HEADING)
    assert start >= 0, "F 的提示词里没有 `## 依赖` 那一段"
    tail = text[start:]
    fences = [i for i in range(len(tail)) if tail.startswith("```", i)]
    assert len(fences) >= 2, "那一段没有被围栏包起来（判据抽不到可照抄的那几行）"
    block = tail[:fences[1]]
    sample = "\n".join(line for line in block.splitlines()
                       if not line.strip().startswith("```"))
    parsed = DS.parse_dependency_section(sample)
    assert parsed["present"], parsed
    assert not parsed["problems"], parsed
    assert parsed["refused"] == "", parsed
    assert len(parsed["rows"]) == 1, parsed
    row = parsed["rows"][0]
    assert row["stmt_id"] == S.format_id(0), row
    assert row["path_group"] == 1, row


def test_retire_child_states_and_refusal_code_are_the_conductor_constants(registry) -> None:
    """`retire_child` 的摘要与 `returns` 必须与 `conductor` 的三态常量同名同值。"""
    spec = registry.get("conductor.retire_child")
    for label in ("在飞", "待机", "静默"):
        assert label in spec.summary, f"摘要里没有 {label!r}"
        assert CD.AGENT_STATE_LABELS and label in CD.AGENT_STATE_LABELS.values()
    assert CD.RETIRE_REFUSAL_TARGET_NOT_SILENT in spec.summary
    assert CD.RETIRE_REFUSAL_TARGET_NOT_SILENT in spec.returns
    for key in ("target_state", "target_state_label", "blocking", "refusal_code"):
        assert f"'{key}'" in spec.returns, f"returns 少了 {key}"
    assert "silent" in spec.returns and "standby" in spec.returns


def test_wait_any_handoff_sentence_is_the_park_gate(registry) -> None:
    """`clock.wait_any` 摘要里那句「等于交差、框架向父代理报告」必须有实现那一条。"""
    summary = registry.get("clock.wait_any").summary
    assert "交差" in summary, summary
    loop = Path(__file__).resolve().parents[1] / "src" / "agentflow" / "agent_loop.py"
    body = loop.read_text(encoding="utf-8")
    assert 'decision="handoff"' in body, "摘要说交差，而 _park_gate 里没有 handoff 这一档"
    assert "_hand_off(" in body, "交差那一档没有向父代理报告的实现"


def test_purpose_missing_readings_are_the_declared_three(prompts) -> None:
    """起表漏填目的时那三格（purpose / purpose_missing / purpose_prompt）实跑就是声明的样子。"""
    store, tmp = _tmp_workspace()
    reg = build_registry(store=store, workspace_root=tmp).registry
    row = S.Task(task_id="t-000001", role="M", action="run", status="running",
                 depth=1, detail="判据", started_at=S.now_iso()).to_dict()
    with store.tx("tasks", actor="audit") as tx:
        tx.upsert("tasks", row)
    C.use(C.FakeClock(wall="2026-01-01T00:00:00+00:00"))
    try:
        with calling_as("t-000001", "M"):
            res = reg.get("clock.timer_start").handler(after_sec=60)
        assert res.ok, res.error
        assert res.data["purpose_missing"] is True
        assert res.data["purpose_prompt"] == C.PURPOSE_PROMPT
        assert res.data["purpose"] == ""
        assert res.data["timer_id"].startswith("tm-")
    finally:
        C.use(C.RealClock())


def test_citation_problem_blocks_the_verdict_and_the_signature(monkeypatch) -> None:
    """依赖台账读不出来（`citation_gate.problem` 非空）必须真挡签，不许折成"没有引用"。

    为什么值得一条：`citation_gate` 的 docstring 与 V 的注释都说 `problem` 也挡住签字，
    而改前 `apply_citation_gate` 只在 `blocking` 非空时改判、`signs_bit3` 只读
    `citation_checks` 里的档 ⇒ `problem` 非空 + `citation_checks` 空时，结论仍是「成立」、
    `signed_bit3` 仍是真。提示词那一侧还把这一档印成"给空数组"（空数组什么都不挡），
    于是"没查成"被折成"没有引用"，一条证明可以在依赖台账读不到的情况下签出「成立」。

    夹具走真路径：`agent_v.core._citation_material` 打桩成"读不到"（它就是
    `dependencies` / `statements` 台账那两个 `except` 的返回口）。
    反真空在同一份夹具里现做：把同一个桩换成"读得出、没有引用"⇒ 这一签本来就签得住
    （结论「成立」、`signed_bit3` 真）—— 于是上面那几条断言不是在真空里通过的。
    """
    from agentflow import verifications as VR
    from agentflow.agent_v import core as AVC

    store, tmp = _tmp_workspace()
    sid = S.format_id(0)
    statement = S.Statement(stmt_id=sid, origin="own_result", kind="theorem",
                            statement_full="若 G 是有限群，则 |G| 有限。",
                            proof_text="1. 由定义直接得到。", status="active",
                            evidence_kind="heuristic",
                            quote_reason="判据夹具：还没有可比对的引文").to_dict()
    with store.tx("statements", actor="audit") as tx:
        tx.upsert("statements", statement)

    class _Seam:
        def complete(self, prompt: str) -> str:
            return json.dumps({"verdict": "成立", "defect_step": None, "quote": "",
                               "why": "判据：无缺陷", "findings": [],
                               "citation_checks": []}, ensure_ascii=False)

    problem = "dependencies 台账读不到（判据打桩）"
    monkeypatch.setattr(AVC, "_citation_material", lambda *_a, **_k: ([], problem))
    out = dict(AgentV(store, workspace_root=tmp, llm=_Seam()).verify_proof(
        statement_id=sid) or {})
    assert out.get("checked") is True, out.get("reason")
    assert out["citation_gate"]["problem"] == problem, out["citation_gate"]
    assert out["citation_gate"]["ok"] is False, out["citation_gate"]
    assert out["verdict"] != "成立", out
    assert out["signed_bit3"] is False, out
    # 台账那一行也不许是「成立」：读侧硬闸与写侧同一道（`signs_bit3` 读 `citation_gate`）。
    rows, problems = VR.list_verifications(tmp, statement_id=sid)
    assert not problems, problems
    row = rows[-1]
    assert row["citation_gate"]["problem"] == problem, row
    assert VR.signs_bit3(row) is False, row
    assert VR.bit3_payload(row) == {}, row
    # 手写的成立行（不经过 V）也过同一道闸：`citation_gate.problem` 非空 ⇒ 不签。
    hand = {"statement_id": sid, "verdict": "成立", "unresolved_errors": 0,
            "citation_checks": [], "citation_gate": {"ok": False, "problem": problem}}
    assert VR.signs_bit3(hand) is False, hand

    # ---------------- 反真空：同一份夹具，problem 为空 ⇒ 这一签本来就签得住 ----------------
    monkeypatch.setattr(AVC, "_citation_material", lambda *_a, **_k: ([], ""))
    clean = dict(AgentV(store, workspace_root=tmp, llm=_Seam()).verify_proof(
        statement_id=sid) or {})
    assert clean.get("checked") is True, clean.get("reason")
    assert clean["verdict"] == "成立" and clean["signed_bit3"] is True, clean
    rows, _ = VR.list_verifications(tmp, statement_id=sid)
    assert VR.signs_bit3(rows[-1]) is True, rows[-1]


# ---------------------------------------------------------------- p205 挂过 xfail、p206 收口的两条


def test_the_clock_example_is_what_human_sec_prints(prompts) -> None:
    """提示词里那句到点示例的等待时长，与 `clock.human_sec` 打印的逐字相同。

    这条原先挂 `xfail(strict=True)` 登记缺口（十一格写「19 分 40 秒」，而
    `human_sec(1180)` 是「19 分钟 40 秒」）。改完之后摘掉标记：strict 的语义正是
    "修好了就 XPASS 变红，提醒摘标记"。
    """
    printed = C.human_sec(1180)
    assert printed == "19 分钟 40 秒", printed
    for role, text in prompts.items():
        assert printed in text, f"{role} 的到点示例不是 human_sec 会打印的那一句"


def test_verify_proof_declares_every_key_of_its_success_branch() -> None:
    """`verify.verify_proof` 成功支给出的每一格，`returns=` 里都要声明。

    `returns` 会拼进 function-calling 的 description ⇒ 声明里没有的字段，模型不知道
    它存在。这一条原先挂 `xfail(strict=True)`（成功支多一格 `review_write`，而
    `returns` 没有它）；改完之后摘掉标记。
    """
    store, tmp = _tmp_workspace()
    sid = S.format_id(0)
    statement = S.Statement(stmt_id=sid, origin="own_result", kind="theorem",
                            statement_full="若 G 是有限群，则 |G| 有限。",
                            proof_text="1. 由定义直接得到。", status="active",
                            evidence_kind="heuristic",
                            quote_reason="判据夹具：还没有可比对的引文").to_dict()
    with store.tx("statements", actor="audit") as tx:
        tx.upsert("statements", statement)

    class _Seam:
        def complete(self, prompt: str) -> str:
            return json.dumps({"verdict": "成立", "defect_step": None, "quote": "",
                               "why": "判据：无缺陷", "findings": [],
                               "citation_checks": []}, ensure_ascii=False)

    data = dict(AgentV(store, workspace_root=tmp, llm=_Seam()).verify_proof(
        statement_id=sid) or {})
    assert data.get("checked") is True, data.get("reason")
    declared = _declared(build_registry(store=store, workspace_root=tmp).registry,
                         "verify.verify_proof")
    assert sorted(set(data) - declared) == []


def test_create_plan_declares_the_keys_of_its_budget_refusal() -> None:
    """`attack.create_plan` 预算拒收支给出的每一格，`returns=` 里都要声明。

    这一条原先挂 `xfail(strict=True)`（拒收支多 `missing` / `kind` / `error` /
    `refusal_reason` 四格，而 `returns` 只写了成功支那八个键）；改完之后摘掉标记。
    同一条判据现在也守着"四条分支键集合相同"：声明只有一套键，两套键之间必然有一格
    是"声明了却永远不出现"或"出现了却没声明"。
    """
    store, tmp = _tmp_workspace()
    reg = build_registry(store=store, workspace_root=tmp).registry
    spec = reg.get("attack.create_plan")
    with calling_as("t-000001", "F"):
        res = spec.handler(problem="P", problem_key="pk", budget={"max_rounds": 4})
    data = dict(res.data or {})
    assert data.get("ok") is False, data
    assert sorted(set(data) - _declared(reg, "attack.create_plan")) == []


def test_table_tools_advertise_the_statements_route_cells(registry) -> None:
    """`table.get` / `table.list` 的摘要要告诉模型 `route` / `proof_routes` 这两格。

    派生格在 `table_tools._with_proof_routes` 里现算（注释自己说"模型读得到行、读不到
    那句话"）。这一条原先挂 `xfail(strict=True)`；两件的 summary 补上之后摘掉标记。
    """
    for name in ("table.get", "table.list"):
        spec = registry.get(name)
        blob = spec.summary + spec.returns
        assert "proof_routes" in blob, name
        assert "route" in blob, name


def test_m_says_delivered_to_is_a_list(prompts) -> None:
    """M 那一格必须把 `delivered_to` 写成列表（实跑是只含一个元素的列表）。

    原先挂 `xfail(strict=True)`：M 的 policy 正文写着「链尾那个绝对编号」（读起来是标量），
    而链那条判据断言 `delivered_to == [chain[-1]]` —— 模型照字面读会去比较一个字符串。
    p206 收口那一批把 `specs/m.py` 改成「列表，只有一个元素 = 链尾那一个的绝对编号
    （不是标量；读它先取 [0]）」，与 `conductor.guide` 的实跑同形，标记随之摘掉。
    """
    text = prompts["M"]
    i = text.find("delivered_to")
    assert i > 0, "M 的提示词里没有 delivered_to"
    assert "列表" in text[i:i + 80], text[i - 40:i + 80]


def test_the_wait_any_rule_reaches_some_policy_cell() -> None:
    """`clock.wait_any` 的行为口径必须落在 policy 正文里（不只落在工具摘要里）。

    原先挂 `xfail(strict=True)`：`clock.wait_any`（第九件）的工具摘要已经写清
    「已无事可做且一条计时器都没有时起这个意图，等于交差 —— requested=true /
    waiting=false 说的就是这一档，它不是没在等」，而十一个角色的 policy 正文里
    一句都没有。p206 收口那一批把这一句并进十一份 specs 的时钟段（十个可召唤角色
    逐字相同、M 并进它已有的挂机那一条），标记随之摘掉。

    这条只要求"至少有一格 policy 说到它"，逐字一致那一半由
    `test_every_role_carries_the_same_clock_paragraph` 与 `tests/test_agent_prompts.py`
    的冻结摘要钉着。
    """
    from agentflow.specs import builtin_specs

    specs = builtin_specs()
    assert len(specs) >= 11, sorted(specs)
    for role, spec in specs.items():
        blob = "\n".join(spec.brief.policy)
        if "clock.wait_any" in blob:
            return
    pytest.fail("十一份 policy 正文都没有 clock.wait_any 的口径")
