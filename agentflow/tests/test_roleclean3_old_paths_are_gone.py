# -*- coding: utf-8 -*-
"""ROLECLEAN3：M / H / L / V 的旧路残留清扫（正控 + 反真空）。

本文件守四组「文案说的与实现不是一件事」—— 形态与
`tests/test_m_prompt_has_no_stale_design.py` / `tests/test_g_h_v_l_prompt_has_no_stale_design.py`
同源：每组有一个纯检查函数（吃一份语料、吐问题清单），正控断言今天的树干净，
负控拿改前那段原文喂同一个函数、断言它必红。只断言"今天没有那句话"无法区分
"真修了"与"那句话被删光了"。

四组：
| 组 | 守什么 | 改前的形态 |
|---|---|---|
| A | 收工门是一份权威结论（`closing_verdict`） | M 的工具说明 / 手册还把 `can_close` 说成"机器口径"、把八格说成"读数"，M 的判断是另一条轴（2026-10-09 的口径，已被 2026-11-19 推翻） |
| B | 发签的计数与门槛由框架现数（`sign_counting`） | V 的声明 / 手册还写"发不发签由你的秘书判定"（2026-11-17 之前的口径） |
| C | L 只有"开着"这一种存在形态 | `formal.formalize` 与 L 的声明还把"开关关着"列为 unknown 的原因；L 的自检表还教它"改走逐行审阅" |
| D | H 的四处死/旧文案 | 零引用常量 `_MATERIAL_KEYS`、指向不存在的 `agent_h/selftest.py`、"documents.json 唯一变化点是 status"、把 `review_report` 说成"审报告" |

零模型：不联网、不起子进程、不写工作区。
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow import schema as S
from agentflow.tools import build_registry

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "agentflow"
TASK = "把这一条链路走一遍"
WS = "D:/x"


def _src(rel: str) -> str:
    return (PKG / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def registry():
    return build_registry().registry


@pytest.fixture(scope="module")
def prompts(registry) -> dict[str, str]:
    return {role: AP.system_prompt(role, registry=registry, task=TASK, workspace_root=WS)
            for role in ("M", "H", "V", "L")}


def _handbook(role: str) -> str:
    return "\n".join(f"{s.slug}\n{s.title}\n{s.summary}\n{s.when}\n{s.body}"
                     for s in AS.CATALOG[role])


def _squash(text: str) -> str:
    return re.sub(r"[\s*`]+", "", text)


# ============================================================ A 收工门：一份权威结论
#: 改前那几句（逐字）。只列"已被 2026-11-19 推翻"的那几条，不列正常的"读数"用法。
_M_CLOSING_STALE: tuple[str, ...] = (
    "can_close` 是**机器口径**",
    "can_close 是机器口径",
    "收工由你判 ⇒ 先说清目标是什么",
    "收工由 M 判（业主 2026-10-09）",
    "门是读数不是判决",
    "不认它就写明理由",
    "机器七格退成读数",
    "can_close` = M 自己交的判据",
)
#: 改后必须读到的几层。
_M_CLOSING_REQUIRED: tuple[str, ...] = (
    "closing_verdict",
    "八格",
    "m_says_done",
    "blocker",
)


def check_m_closing(text: str) -> list[str]:
    """这段 M 面文字里还留着几条"两条轴"的旧口径、缺哪几层新口径。"""
    flat = _squash(text)
    out = [f"仍写着旧口径 {old!r}" for old in _M_CLOSING_STALE if old in text]
    out += [f"读不到新口径 {need!r}" for need in _M_CLOSING_REQUIRED
            if _squash(need) not in flat]
    return out


def test_a_m_closing_says_one_authoritative_verdict(prompts: dict[str, str]) -> None:
    """A 正控：M 的提示词 / 收工手册 / `conductor.closing` 声明都不再说"两条轴"。"""
    from agentflow.tools import conductor_tools as CT

    spec = CT.conductor_closing.__tool_spec__
    corpus = {
        "M 的提示词": prompts["M"],
        "M 的收工手册": _handbook("M"),
        "conductor.closing 声明": "\n".join([
            spec.summary, repr(spec.params), repr(spec.returns)]),
    }
    for where, text in corpus.items():
        assert check_m_closing(text) == [], f"{where}：\n" + "\n".join(check_m_closing(text))


def test_a_the_old_two_axis_wording_goes_red() -> None:
    """A 反真空：把改前那几句塞回去 ⇒ 同一个检查必须点出来。"""
    old = ("收工由 M 判（业主 2026-10-09）「是否收工不要用机械判据…」；"
           "`can_close` 是**机器口径**；机器七格退成读数；门是读数不是判决。")
    broken = old + "\nclosing_verdict 八格 m_says_done blocker"
    problems = check_m_closing(broken)
    assert problems, "把 2026-10-09 的旧口径塞回去，检查却一声不吭 ⇒ 这一条是橡皮图章"
    assert any("旧口径" in p for p in problems), problems


# ============================================================ B 发签：框架现数
_V_STALE: tuple[str, ...] = (
    "发不发签由 V 的秘书决定",
    "在册档发不发由 V 的秘书判",
    "发不发签由你的秘书判定并落盘",
    "在册档签由秘书判定并落盘",
    "只有连续三次审核通过",
)
_V_REQUIRED: tuple[str, ...] = (
    "sign_counting",
    "框架从台账现数",
)


def check_v_issuance(text: str, *, require_new: bool = True) -> list[str]:
    flat = _squash(text)
    out = [f"仍写着旧口径 {old!r}" for old in _V_STALE if old in text]
    if require_new:
        out += [f"读不到新口径 {need!r}" for need in _V_REQUIRED if _squash(need) not in flat]
    return out


def test_b_v_issuance_is_counted_by_the_framework(prompts: dict[str, str]) -> None:
    """B 正控：`specs/v.py` / V 的提示词与手册 / `vsigns` docstring 都改成框架现数。"""
    corpus = {
        "specs/v.py": (_src("specs/v.py"), True),
        "V 的提示词": (prompts["V"], True),
        "V 的手册": (_handbook("V"), True),
        # `vsigns` 的模块 docstring 只讲"一稿一签"与三处落点；计数实现那一句在
        # `issue` 的 docstring（不在这份语料里）⇒ 这里只查旧口径已不在。
        "vsigns.py docstring": (_src("vsigns.py").split('"""')[1], False),
    }
    for where, (text, require_new) in corpus.items():
        problems = check_v_issuance(text, require_new=require_new)
        assert problems == [], f"{where}：\n" + "\n".join(problems)


def test_b_the_old_secretary_decision_wording_goes_red() -> None:
    """B 反真空：把"发不发签由你的秘书判定并落盘"塞回去 ⇒ 必红。"""
    broken = ("在册档：发不发签由你的秘书判定并落盘（`decide_sign_issuance` 判「发不发」）。"
              "sign_counting 框架从台账现数")
    problems = check_v_issuance(broken)
    assert problems, "塞回旧口径，检查却没报 ⇒ 这一条证明不了任何事"
    assert any("旧口径" in p for p in problems), problems


# ============================================================ C L：没有"关着"这一档
_L_STALE: tuple[str, ...] = (
    "带原因：开关关着",
    "（开关关着 / 自检不过 / 检查器不存在 / 超时）",
    "改走逐行审阅",
    "你只在开关开着时在场",
)
_L_REQUIRED: tuple[str, ...] = (
    "自检不是 usable",
)


def check_l_off_tier(text: str, *, require_new: bool = True) -> list[str]:
    flat = _squash(text)
    out = [f"仍写着不可达的 off 档 {old!r}" for old in _L_STALE if old in text]
    if require_new:
        out += [f"读不到 {need!r}" for need in _L_REQUIRED if _squash(need) not in flat]
    return out


def test_c_l_does_not_teach_a_tier_that_does_not_exist(prompts: dict[str, str]) -> None:
    """C 正控：L 的声明 / 工具说明 / 自检表都不再教"关着时怎么办"。"""
    from agentflow.tools import formal_tools as FT

    spec = FT._formal_formalize.__tool_spec__
    corpus = {
        "specs/l.py": (_src("specs/l.py"), True),
        "L 的提示词": (prompts["L"], True),
        "formal.formalize 声明": (spec.summary, True),
        "agent_l/_support.py": (_src("agent_l/_support.py"), False),
    }
    for where, (text, require_new) in corpus.items():
        problems = check_l_off_tier(text, require_new=require_new)
        assert problems == [], f"{where}：\n" + "\n".join(problems)


def test_c_the_old_off_tier_wording_goes_red() -> None:
    """C 反真空：把"开关关着 / 改走逐行审阅"塞回去 ⇒ 必红。"""
    broken = ("unknown（没查成，带原因：开关关着 / 自检不过 / 检查器不存在 / 超时）；"
              "自检状态 off ⇒ 改走逐行审阅")
    problems = check_l_off_tier(broken)
    assert problems, "塞回 off 档文案，检查却没报 ⇒ 这一条没有牙"


# ============================================================ D H：死代码 / 旧文案
def test_d_h_dead_constant_is_gone() -> None:
    """D1：两个零引用符号已经删掉（AST 级，不看注释）。"""
    for rel, name in (("agent_h/judge_quote_semantics.py", "_MATERIAL_KEYS"),
                      ("agent_h/mapping_judge.py", "is_objective")):
        tree = ast.parse(_src(rel))
        names = {t.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 for t in node.targets if isinstance(t, ast.Name)}
        names |= {node.name for node in ast.walk(tree)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert name not in names, f"{rel} 里的零引用符号 {name} 又回来了"


def test_d_h_main_docstring_points_at_the_real_selftest() -> None:
    """D2：`agent_h/__main__.py` 不再指向不存在的 `agent_h/selftest.py`。"""
    text = _src("agent_h/__main__.py")
    assert "agent_h/selftest.py" not in text, "docstring 又指向一个不存在的文件"
    assert "agent_h/core.py" in text, "docstring 没指出自检本体的真实落点"


def test_d_h_package_docstring_counts_the_review_axis() -> None:
    """D3：`agent_h/__init__.py` 的"documents.json 变化点"要与自检逐格对上。"""
    text = _src("agent_h/__init__.py")
    assert "唯一变化点是 `status`" not in text, "又写成「只改 status」了（审核轴与轮次也写）"
    for needle in ("review_verdict", "reviewed_at", "reviewed_by", "review_rounds"):
        assert needle in text, f"docstring 没点名 {needle}"


def test_d_h_review_report_is_not_a_review_of_a_report() -> None:
    """D4：H 的手册把 `review_report` 说成「产出审校报告」，不是「审报告」。"""
    body = next(s for s in AS.CATALOG["H"] if "review_report" in s.body).body
    assert "**审报告** —— 判一份报告站不站得住" not in body, (
        "H 的手册又把 `review_report` 说成「审一份报告」了")
    assert "产出审校报告" in body, "H 的手册没写清 `review_report` 产出的是什么"


#: D 组的三句旧文案与它们的正确落点。
_H_OLD: tuple[tuple[str, str], ...] = (
    ("`H.review_report`：**审报告** —— 判一份报告站不站得住", "产出审校报告"),
    ("documents.json` 的唯一变化点是 `status`", "review_verdict"),
    ("agent_h/selftest.py", "agent_h/core.py"),
)


def check_h_old(text: str) -> list[str]:
    """这份 H 面文字里还留着几句旧文案、缺哪几个正确落点。"""
    return ([f"仍写着旧文案 {old!r}" for old, _new in _H_OLD if old in text]
            + [f"读不到正确落点 {new!r}" for _old, new in _H_OLD if new not in text])


def test_d_the_old_h_wording_goes_red() -> None:
    """D 反真空：把三句旧 H 文案一起塞进同一个读法 ⇒ 每一句都必须被点到。"""
    broken = "\n".join(old for old, _new in _H_OLD)
    problems = check_h_old(broken)
    assert len(problems) >= len(_H_OLD), problems
    assert all(any(old in p for p in problems) for old, _new in _H_OLD), problems
