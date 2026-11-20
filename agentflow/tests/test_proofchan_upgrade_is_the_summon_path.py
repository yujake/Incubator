# -*- coding: utf-8 -*-
"""PROOFCHAN：B→D 升级这一条，提示词 / 动作表 / 实现类三方逐条一致。

## 这一份判什么（以及为什么它必须存在）

ROLCLEAN-1 的取证把一条旧路点了名：`agent_b/proof_research.py` 的
`escalate_proof_research` —— src 调用 0 处、tests 6 处，而 `specs/b.py` 的
`PROOF_CHANNEL` 第⑥步教模型走的是 `summon` 形状。这就是"提示词已改、程序入口没跟上"
的典型残留：模型侧的路是对的，程序侧那条谁也走不到（它不在 `ACTIONS` 里 ⇒ 召唤它只会
拿到 `unknown_action`），却仍被两条判据以它为准。

2026-11-20 的处置是「甲」：程序入口退场，判据改到新路（`summon` 形状派 D），并把
"三方一致"本身钉成判据 —— 于是"两边再分家"这件事会当场变红，而不是靠下一个人记得。

## 四条判据与各自的"改前红"

| # | 判据 | 改前红 / 反真空 |
|---|---|---|
| 1 | 提示词那一侧：B 的渲染后提示词第⑥步教的是 `summon` 形状派 D，且不再点名旧入口；负控那一句（普通缺陷不进 D 的收件箱）在 | 改前红：旧入口的名字会出现在判据要断言"不在"的那一格；反真空：把锚点从一段抄来的文本里抠掉，检查函数必须报出来（不许恒绿） |
| 2 | 动作表 / 边那一侧：第⑥步点名的每个 `角色.动作` 都得是真动作，且那个角色是 B 真能派的（边 + 可召唤）；`AgentB` 上被点名的方法必须是动作表里的 handler | 改前红：旧入口若是被点名的那一个，它在 `AgentB` 上却不在 `ACTIONS` 的 handler 里 ⇒ 当场红；反真空：把 token 换成一个不存在的方法，检查函数必须报出来 |
| 3 | 实现类那一侧：src 里只剩一处 `proofreport.deliver(`，且它是 L→B；`research_request` 那套旧形态（`RESEARCH_SUBJECT` / `research_subject` / `research_body`）已从模块上消失 | 改前红：改前 src 里有第二处（B→D）；反真空：喂一段 `deliver(sender="B", to="D")` 的源码，扫描器必须报出来 |
| 4 | 读数链没断：L 的汇报正文里带着它建议的严重度（`severity`），B 才有判断素材；`severity_for` 的受控映射没变 | 改前红的无（这条是正控：severity 闸随入口退场之后，B 的判断素材不能跟着丢） |

零模型：四条都只读已渲染的提示词、`capabilities` / `policy` 的表、AST 与两个纯函数。
"""
from __future__ import annotations

import ast
import pathlib
import re

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import proofreport as PR
from agentflow import specs as SP
from agentflow.agentspec import builtin_registry
from agentflow.tools import build_registry

#: 仓库里 `src/` 的位置（AST 判据要逐文件读）。
PROJ = pathlib.Path(__file__).resolve().parents[1]
SRC = PROJ / "src" / "agentflow"

#: 第⑥步教的那条路（逐字锚点：判据认的是"读的人照着能做"的那半句，不是排版）。
SUMMON_TO_D = "用 `summon` 形状直接派 D"
SUMMON_ROLE = '`role="D"`'
SUMMON_EDGE = "`B → D` 是直接边"
#: 负控那一句（普通缺陷不打扰 D）：改后它只剩提示词这一处，所以逐字钉。
NORMAL_DEFECT_STAYS_AWAY = "普通缺陷不进 D 的收件箱"
#: 旧入口的名字（2026-11-20 退场；它出现在渲染提示词里就是旧路复活）。
RETIRED = "escalate_proof_research"


# ============================================================ 判据 1：提示词那一侧


def missing_anchors(text: str) -> list[str]:
    """这一份提示词里缺了哪几个锚点（空列表 = 都在）。

    纯函数：拿一段假文本喂进来就能给"这条判据到底在判什么"做反真空。
    """
    want = (SUMMON_TO_D, SUMMON_ROLE, SUMMON_EDGE, NORMAL_DEFECT_STAYS_AWAY)
    return [tok for tok in want if tok not in text]


def test_the_prompt_teaches_the_summon_shape_to_d() -> None:
    """判据 1：B 的渲染后提示词里，第⑥步教的是 `summon` 形状派 D。

    为什么读渲染结果而不是读常量：常量对、而它在渲染时被 `*_NO_LEAN` 换掉或拼丢，
    模型照样看不到 —— 那正是"提示词与实现分家"的另一种形态。本文件跑在
    `conftest.py` 钉住的 Lean 开着那一档，所以第⑥步在盘上。
    """
    reg = build_registry().registry
    b_text = AP.system_prompt("B", registry=reg)
    assert missing_anchors(b_text) == [], (
        f"B 的提示词里缺这几个锚点：{missing_anchors(b_text)}")
    # 旧入口不许再出现在任何一个角色的提示词里（它已退场；点名它等于教模型去调空气）
    leaked = sorted(role for role in SP.builtin_specs()
                    if RETIRED in AP.system_prompt(role, registry=reg))
    assert leaked == [], f"这些角色的提示词里还点着已退场的入口：{leaked}"


def test_the_anchor_checker_is_not_vacuous() -> None:
    """反真空：把锚点从一段文本里抠掉 ⇒ `missing_anchors` 必须报出来。

    没有这一条，`missing_anchors` 哪天退化成"永远返回空清单"（例如锚点被改成空串），
    判据 1 会以"全都对得上"的形态静默变绿。
    """
    full = f"{SUMMON_TO_D} / {SUMMON_ROLE} / {SUMMON_EDGE} / {NORMAL_DEFECT_STAYS_AWAY}"
    assert missing_anchors(full) == []

    for tok in (SUMMON_TO_D, SUMMON_ROLE, SUMMON_EDGE, NORMAL_DEFECT_STAYS_AWAY):
        doctored = full.replace(tok, "（抠掉）")
        assert missing_anchors(doctored) == [tok], (tok, missing_anchors(doctored))


# ============================================================ 判据 2：动作表 / 边那一侧

#: 第⑥步里"角色.动作"形状的 token（`V.verify_proof` 这种）。
_ROLE_ACTION = re.compile(r"`([A-Z][A-Za-z]*)\.([a-z][a-z0-9_]*)`")
#: 第⑥步里"我自己的动作"形状的 token（`own.register_statement` 这种）。
_OWN_ACTION = re.compile(r"`own\.([a-z][a-z0-9_]*)`")
#: 第⑥步里"像个标识符"的 token（用来抓"点了一个方法名"这一类）。
_SNAKE = re.compile(r"`(_?[a-z][a-z0-9_]{3,})`")


def _step_six() -> str:
    """`PROOF_CHANNEL` 的第⑥步（逐字，从常量切出来）。"""
    const = SP.b.PROOF_CHANNEL
    assert "⑥" in const, "PROOF_CHANNEL 里没有第⑥步 ⇒ 这条判据没有对象"
    return "⑥" + const.split("⑥", 1)[1]


def action_mismatches(step: str, *, actions_of: dict[str, list[str]],
                      handlers: list[str]) -> list[str]:
    """第⑥步点名的动作/方法里，与动作表对不上的那些（空列表 = 三方一致）。

    三段：
      · `角色.动作` ⇒ 那个角色得有这件动作（`CAPABILITIES` 是动作表的派生）；
      · `own.动作` ⇒ 那是 B 自己的动作，得在 B 的动作表里；
      · 被点名的方法（`AgentB` 上真有这个属性）⇒ 必须是某件动作的 handler。
        这一条正是"提示词点了一个程序入口"的显式判据：改前那个旧入口就是这样被点出来的。
    """
    from agentflow.agent_b import AgentB

    bad: list[str] = []
    for role, action in _ROLE_ACTION.findall(step):
        if role not in actions_of:
            bad.append(f"`{role}.{action}`：角色 {role} 不存在")
        elif action not in actions_of[role]:
            bad.append(f"`{role}.{action}`：{role} 的动作表里没有 {action}")
    for action in _OWN_ACTION.findall(step):
        if action not in actions_of.get("B", []):
            bad.append(f"`own.{action}`：B 的动作表里没有 {action}")
    for token in _SNAKE.findall(step):
        if hasattr(AgentB, token) and token not in handlers:
            bad.append(
                f"`{token}`：它是 `AgentB` 上真有的方法，却不在动作表的 handler 里 ⇒ "
                "模型照它调只会拿到 `unknown_action`")
    return bad


def test_what_step_six_teaches_is_reachable() -> None:
    """判据 2：第⑥步教的动作全都真能被 B 走到（动作表 + 边 + 可召唤）。

    这是"提示词 / 动作表 / 实现类三方逐条一致"的机器读数：改前那一条旧路之所以能
    藏这么久，就是因为没有任何判据把"提示词点名 ≠ 动作表里有"这件事读出来。
    """
    step = _step_six()
    actions_of = {role: [a.action for a in acts] for role, acts in C.CAPABILITIES.items()}
    handlers = [a.handler_name for a in SP.b.ACTIONS]
    assert action_mismatches(step, actions_of=actions_of, handlers=handlers) == [], (
        action_mismatches(step, actions_of=actions_of, handlers=handlers))

    # 第⑥步点名的那个"另一个角色"必须真能被 B 派出去（边在 + 可召唤）
    summonable = set(builtin_registry().summonable_roles())
    for role, _action in _ROLE_ACTION.findall(step) + [("D", "summon")]:
        assert role in C.ALLOWED_EDGES["B"], (
            f"第⑥步教 B 找 {role}，可 B 的出边里没有它：{sorted(C.ALLOWED_EDGES['B'])}")
        assert role not in C.NON_SUMMONABLE, (
            f"{role} 在不可召唤名单里 ⇒ B 派不动它：{sorted(C.NON_SUMMONABLE)}")
        assert role in summonable, summonable


def test_the_action_checker_is_not_vacuous() -> None:
    """反真空：把第⑥步的 token 换成一个不存在的方法 / 动作 ⇒ 必须报出来。

    两档各来一次：
      · 换成一个 `AgentB` 上真有的方法、却不是动作 handler（正是旧路的形态）；
      · 换成一个根本不存在的 `角色.动作`。
    """
    from agentflow.agent_b import AgentB

    # `_claim` 是 `AgentB` 上真有的方法、不是任何动作的 handler —— 旧路就是这个形态
    assert callable(getattr(AgentB, "_claim", None)), (
        "反真空的替身丢了：`AgentB` 上已经没有 `_claim`")
    doctored = "用 `_claim` 记一笔，再 `Z.no_such_action`。"
    actions_of = {"B": [a.action for a in SP.b.ACTIONS]}
    got = action_mismatches(doctored, actions_of=actions_of,
                            handlers=[a.handler_name for a in SP.b.ACTIONS])
    assert any("`_claim`" in x for x in got), got
    assert any("`Z.no_such_action`" in x for x in got), got


# ============================================================ 判据 3：实现类那一侧

def _deliver_calls(path: pathlib.Path) -> list[tuple[int, str, str]]:
    """一个文件里 `*.deliver(...)` 的 `(行号, sender, to)`（字面量才给值，否则空串）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "deliver"):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        get = lambda name: (kw[name].value  # noqa: E731 —— 一句取值，不值得为它拆函数
                            if isinstance(kw.get(name), ast.Constant)
                            and isinstance(kw[name].value, str) else "")
        out.append((node.lineno, get("sender"), get("to")))
    return sorted(out)


def test_only_one_program_entry_delivers_a_report() -> None:
    """判据 3：src 里只剩一处 `deliver(`，而且是 L→B。

    改前有两处（B→D 那一处就是退场的入口）。这一条不是"数文件"，它钉的是
    "B 不再有任何程序入口往 D 的收件箱里写东西" —— 升级改走 `summon`，D 的收件箱
    不该再由 B 这条链写。
    """
    calls = [(p.relative_to(SRC).as_posix(), line, sender, to)
             for p in sorted(SRC.rglob("*.py")) if "__pycache__" not in p.parts
             for line, sender, to in _deliver_calls(p)]
    assert len(calls) == 1, f"`deliver(` 的调用点不是一个：{calls}"
    where, _line, sender, to = calls[0]
    assert (sender, to) == ("L", "B"), f"{where} 那一处递送不是 L→B：{sender}→{to}"

    # 旧形态的构件也已退场（留着它们就是留着一条随时能被接回来的旧路）
    for gone in ("RESEARCH_SUBJECT", "research_subject", "research_body"):
        assert not hasattr(PR, gone), f"`proofreport.{gone}` 又回来了（旧路形态）"
    assert not hasattr(PR, "RESEARCH_SUBJECT")
    # `deliver` 本身还在（它是 L→B 的落点；删了它这一条会把路一起删掉而看不出来）
    assert callable(PR.deliver)


def test_the_deliver_scanner_is_not_vacuous(tmp_path: pathlib.Path) -> None:
    """反真空：喂一段 `deliver(sender="B", to="D")` 的源码 ⇒ 扫描器必须读到它。"""
    probe = tmp_path / "probe.py"
    probe.write_text(
        'PR.deliver(sender="B", to="D", item={}, subject="研究请求", body="", '
        'extra_key="research_request")\n',
        encoding="utf-8")
    got = _deliver_calls(probe)
    assert got == [(1, "B", "D")], got


# ============================================================ 判据 4：读数链没断

def test_the_report_still_carries_the_severity_reading() -> None:
    """判据 4：L 的汇报正文里带着它建议的严重度 —— B 才有判断素材。

    程序侧的 `severity` 闸随旧入口一起退场了（现在"要不要派 D"是 B 的判断），所以这一条
    钉的是判断素材还在：汇报正文里有那一句、受控映射没变。少了它，B 只能猜。
    """
    assert PR.severity_for("statement_mismatch") == "research"
    for kind in ("unfaithful_step", "missing_hypothesis", "sorry_needed"):
        assert PR.severity_for(kind) == "normal", kind
    item = PR.payload(statement_id="000001", failure_type="statement_mismatch",
                      step=3, severity=PR.severity_for("statement_mismatch"))
    body = PR.report_body(item)
    assert "research" in body, body
    assert "000001" in body, body
    assert PR.SEVERITIES == ("normal", "research")
