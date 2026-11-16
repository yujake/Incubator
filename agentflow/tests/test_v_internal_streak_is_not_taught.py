# -*- coding: utf-8 -*-
"""判据：模型可见面只说「拿没拿到 V 签」，不教 V 内部连判了几次（业主 2026-11-04 裁定 D 第二段）。

## 业主原话（逐字）

    就说拿到 V 签，不需要知道 V 内部会连续三次审

## 为什么这句要进判据

V 内部一次 `verify_proof` 会自己连判 `SIGN_STREAK_NEED` 轮 —— 那是框架的事，
模型既拿不到「第几转」，也不该被要求推断还有几转。改前的手册 / 拒信却在教它：
「连续三次「成立」之后才轮到秘书判」「连判三转都「成立」才算过」「三转成立后签落回稿」。
模型照这些句子走，会去做三件它做不到的事：数转数、把「第 1、2 次成立」读成「还差一次就签」、
把「我写了成立」读成「签上了」。

可观察的只有一件事：签到位了没有（签块 / `out/vsigns/<sha>.json` / 第 3 位）。
所以这一条钉的是"嘴上说的是签、不是转数"，不是把"签到位才算审过"这个判断删掉 ——
判据 c/d 反过来钉住它：删了那句判断 ⇒ 红。

## 范围（只量模型可见面）

| 面 | 怎么取的 | 模型在哪看到它 |
|---|---|---|
| V 手册「产出-只产意见-签分两档」 | `agent_skills.skills_for("V")` 的 `title` + `summary` + `body` | 索引行进提示词、正文落 `skills/V/…md` 由它 `fs.read` |
| E 手册「穷举证明-拿签与上报收养」 | `agent_skills.skills_for("E")` 同上 | 同上（`skills/E/…md`） |
| `_needs_v_reason` 的四种结局 | 现调 `register_statement._needs_v_reason(state=…)` | 拒信里的「建议：…」那一句 |
| 三道闸的拒信建议 | 源码里的那三句（`三转成立后签落回稿` / `三转成立后由收方秘书` / `连续 N 次「成立」`） | 同上 |

开发者 docstring / 注释不在面上：`_needs_v_reason` 的 docstring 里仍写着"连续 3 次"是
`verifications.SIGN_STREAK_NEED`（那是给人看的实现说明，业主口径：不改）。所以这一条
按"运行时那几句话"取，而不是按整份源码的文字取。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 四个面都不出现「三转 / 连判 / 连续三次 / 连续 3 次 / 第 1、2 次」这类教程式说法 | 改前 V 手册 4 处、E 手册 3 处、`_needs_v_reason` 3 处、三道闸 3 处 |
| b | 反真空：往任一面塞回一句教程式说法 ⇒ 校验函数必须红 | 证明 a 的绿来自"这些词不在"，不是来自别的字 |
| c | 「签到位才算审过」这个判断本身还在（V「签到位才叫签上了」、E「签到位才算过」、B 拒信「拿 V 签」/「签到位后签块由收方秘书落回稿」/「签到位后带这份稿重交 `own.register_statement`」） | —— |
| d | 反真空（c）：把任一句判断删掉 ⇒ 校验函数必须红 | 证明 c 不是"有个「签」字就算过" |
| e | V 的真实入口（`verifications.cold_start_prompt`）含四件口径：按这一趟算 / 跨趟不累计 / 任一转 fault 即终局 / V 稿投给被审者且不用 ack；且不含 `FORBIDDEN` 里任何一个词 | 改前真入口只写了「轮数与门槛由框架按这一趟送审自己数」，后三件一个字都没有 |
| f | 反真空（e）：把那一节删掉 ⇒ e 红；把「三转」塞回去 ⇒ e 红 | 证明 e 的绿来自那一节本身，不是来自别的字 |

## 2026-11-17（PA3）：V 的真实入口也归这一条管

`specs/v.py` 的 policy 只渲染进 `system_prompt("V")`，而 `agent_v/core.py::verify_proof`
拼的是 `verifications.cold_start_prompt`（全仓没有生产路径渲染 `system_prompt("V")`）——
只在 policy 里写，真机上的 V 一个字都读不到。所以 e/f 量的是那个入口，词表复用下面
同一份 `FORBIDDEN`（不另抄一份）。

## 2026-11-10（D1，`4273a273`）：B 拒信那一句换了口径，判据跟着换

D1 之前 B 的 `stale` / `unsigned` 两句写的是「⇒ 签到位后签文件落在
`out/vsigns/<正文sha>.json`，kind 会自动抬成 theorem；这一版已经在盘上，不必再按
`kind="conjecture"` 交一次」/「不必再交一次登记」。那套话成立的前提是"登记会顺手把
正文落到盘上"——D1 把这个顺手动作拆掉了（被拒的登记盘上零新增，落稿改为显式的
`AgentB.land_manuscript`）。前提一没，旧句就变成错的：签到位不等于正文在盘上/在册，
B 必须先显式落稿、再派 V 审、签块由收方秘书落回稿，最后带这份稿重交一次登记。

所以判据 c 钉的第三句从「签到位后签文件落在」换成新口径的两句（hold 那句
「签到位后签块由收方秘书落回稿」+ stale 那句「签到位后带这份稿重交
`own.register_statement`」），同时把旧句登记成"必须不在"（`REFUSAL_STALE`）——
两个方向都量：新话不在 ⇒ 红，旧话还在 ⇒ 也红。这不是把判据放松，而是把"钉的那句话"
从"已经为假的那句"换成"现在为真的那句"，并且多钉一个方向。

## 2026-11-17（PA4）：扫尾的其余模型可见面也归这一条管

判据 a–f 只量了 V/E 手册、`_needs_v_reason`、三道闸与 V 的真实入口。PA4 把全仓
扫了一遍，又扫出十三处同类（F 的 policy、B 的 policy、各角色的操作手册、优化提示词
正文与 `done_when`、B 的概念稿拒信、优化候选的下一步建议两支、概念良定义的下一步
建议三支、V 送审工具的参数说明、holding 的 `why`、V 秘书的发签材料、签文件的复算
读数、V 的审阅通知、V 的 `verify_proof` 返回面、未在册散文那一支的返回）。它们都是
模型读得到的文案（prompt 常量 / 拒信 / 建议 / 工具参数说明 / 工具返回的 `detail` /
手册正文 / 通知）⇒ 并进同一条：g 复用同一份 `FORBIDDEN`（外加 `STREAK_VARIANTS`
里那几个「3 转 / 3/3 / pending 三行 / 连续 clean」的变体），h 对每个面塞回任一
`FORBIDDEN` 词、或删掉任一正句，都必须红。

这一批里 `specs/f.py` 与 `specs/b.py` 的 policy 进 `_surface_digest`（B / F 的
提示词段）⇒ 本笔把 `PROMPT_VERSION` p288 → p289、重冻十一格与那两格摘要
（changed = ['B', 'F']）；其余面（手册正文、拒信、建议、工具参数说明、工具返回的
`detail` / 通知）都不进摘要（手册正文只在 `SKILLS_INDEX` 里印 slug + 一句话；
工具的 `params` 说明本来就不进摘要），不参与版本号。
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap
from typing import Any

import pytest

from agentflow import agent_skills as AS
from agentflow import verifications as VR
from agentflow.agent_b import register_statement as RS

PROJECT = pathlib.Path(__file__).resolve().parents[1]

#: V 内部连判的教程式说法（模型拿不到这些，也不该被要求推断）。
FORBIDDEN: tuple[str, ...] = ("三转", "连判", "连续三次", "连续 3 次", "连续3次", "第 1、2 次")

#: 2026-11-17（PA4）：`FORBIDDEN` 之外、同样会让人推断内部轮数的"数字式"说法。
#: 单列而不是塞回 `FORBIDDEN`：这几条是上一轮把「三转」改写成「3 转 / 3/3」留下的
#: 变体（`f507b528` 改了 `specs/f.py` 的教法、F/E 手册写了 pending 的行数），
#: 词形不同、语义相同 —— 只看 `FORBIDDEN` 会漏掉它们，正是 PA4 扫出来的那几处。
STREAK_VARIANTS: tuple[str, ...] = (
    "连续 3 转", "3 转 clean", "连续=3/3", "pending 三行", "连续 clean",
)

V_SLUG = "产出-只产意见-签分两档"
E_SLUG = "穷举证明-拿签与上报收养"

#: 每一面必须保住的那句判断（判据 c；删掉 ⇒ d 红）。
V_NEEDLES: tuple[str, ...] = ("签到位才叫签上了", "签到位之后秘书才发得出这一签")
E_NEEDLES: tuple[str, ...] = ("签到位才算过", "签到位后由收方落签块")
REFUSAL_NEEDLES: tuple[str, ...] = (
    "请重新拿 V 签", "请拿 V 签",
    # 2026-11-10（D1）：签住的那一下是"签块由收方秘书落回稿"，落完之后 B 还要带稿重交
    # （登记不再顺手落稿）—— 这两句取代了改前那句「签到位后签文件落在…不必再交一次」。
    "签到位后签块由收方秘书落回稿",
    "签到位后带这份稿重交 own.register_statement",
    # T1 把 `own.land_manuscript` 注册成工具后，这两句可能要同步。
)
#: 改前那句旧口径（「签到位后签文件落在…kind 自动抬、这一版已经在盘上不必再交」）。
#: 它把"签落地"说成"文件落地 + 不用重交"，与 D1 之后的路相反 ⇒ 必须不在（判据 c 的另一半）。
REFUSAL_STALE: tuple[str, ...] = ("签到位后签文件落在",)
GATE_NEEDLES: tuple[str, ...] = ("签到位后签落回稿", "签到位后由收方秘书", "签到位后再来替换")

#: 三句闸建议改前各有的教程式说法（这三串只在代码字符串里出现，docstring 里没有）。
GATE_STALE: tuple[str, ...] = ("三转成立后", "连判 3 次干净成立", "审够次数（第 1、2 次")

#: 拒信建议的三种结局（`rejected` 那句本来就没提转数，一并量着免得只改一半）。
STATES: tuple[str, ...] = ("stale", "unsigned", "rejected", "holding")


def _skill_text(role: str, slug: str) -> str:
    for s in AS.skills_for(role):
        if s.slug == slug:
            return "\n".join((s.title, s.summary, s.body))
    raise AssertionError(f"{role} 的技能表里没有 {slug!r} ⇒ 这一条判据失去对象")


def _refusal_text() -> str:
    return "\n".join(
        RS._needs_v_reason(sid="stmt-1", sha12="deadbeef1234", state=st, streak=2, need=3)
        for st in STATES)


def _register_source() -> str:
    return (PROJECT / "src" / "agentflow" / "agent_b" / "register_statement.py").read_text(
        encoding="utf-8")


def _surfaces() -> dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]]:
    """名字 → `(这一面模型看得到的文字, 必须保住的那几句, 必须不在的那几句旧口径)`。"""
    return {
        f"V 手册（{V_SLUG}）": (_skill_text("V", V_SLUG), V_NEEDLES, ()),
        f"E 手册（{E_SLUG}）": (_skill_text("E", E_SLUG), E_NEEDLES, ()),
        "B 的 `_needs_v_reason` 四句建议": (_refusal_text(), REFUSAL_NEEDLES, REFUSAL_STALE),
    }


def _problems(text: str, needles: tuple[str, ...],
              stale: tuple[str, ...] = ()) -> list[str]:
    """这一面离「只说签、不说转数」还差什么（空列表 = 合格）。"""
    out: list[str] = []
    for word in FORBIDDEN + STREAK_VARIANTS:
        if word in text:
            out.append(f"仍在教 V 的内部机制：{word!r}")
    for word in stale:
        if word in text:
            out.append(f"仍留着旧口径（签一落地就算签住、不必重交）：{word!r}")
    for needle in needles:
        if needle not in text:
            out.append(f"删掉了「签到位才算审过」这个判断：缺 {needle!r}")
    return out


def _gate_problems(src: str) -> list[str]:
    """三道闸的拒信建议（源码里那三句）离口径还差什么。"""
    out: list[str] = [f"仍在教 V 的内部机制：{w!r}" for w in GATE_STALE if w in src]
    out += [f"删掉了「签到位才算审过」这个判断：缺 {n!r}" for n in GATE_NEEDLES if n not in src]
    return out


# ============================================================ a + c 四个面同口径
def test_a_model_text_says_the_sign_landed_not_the_streak() -> None:
    """a+c：四个面都只说签到位，且那句判断还在（缺任一半就红）。"""
    for name, (text, needles, stale) in _surfaces().items():
        problems = _problems(text, needles, stale)
        assert problems == [], f"{name}：\n  - " + "\n  - ".join(problems)
    gate = _gate_problems(_register_source())
    assert gate == [], "三道闸的拒信建议：\n  - " + "\n  - ".join(gate)


# ============================================================ b 反真空（a）
def test_b_putting_the_tutorial_line_back_turns_it_red() -> None:
    """b：往任一面里塞回一句教程式说法 / 塞回旧口径 ⇒ 校验函数必须红（a 不是空转）。"""
    for name, (text, needles, stale) in _surfaces().items():
        assert _problems(text, needles, stale) == []
        poisoned = text + "\n（改前口径）V 连判三转「成立」之后才发签。"
        assert _problems(poisoned, needles, stale) != [], (
            f"{name}：塞回教程式说法之后校验仍然绿 —— a 量的不是这个词表")
        if stale:
            # 旧口径那句（D1 之前 B 拒信里说"签到位后签文件落在…这一版已经在盘上，
            # 不必再交一次"）：塞回去必须红 —— 判据 c 的"旧话不在"那一半不是空转。
            old = text + ("\n（改前口径）⇒ 签到位后签文件落在 out/vsigns/<正文sha>.json，"
                          "kind 会自动抬成 theorem；这一版已经在盘上，不必再交一次。")
            assert _problems(old, needles, stale) != [], (
                f"{name}：把旧口径塞回去之后校验仍然绿 —— 判据 c 没在量「旧话不在」")
    src = _register_source()
    assert _gate_problems(src) == []
    poisoned_src = src + '\n_X = "三转成立后签落回稿"\n'
    assert _gate_problems(poisoned_src) != [], (
        "三道闸：塞回「三转成立后」之后校验仍然绿 —— a 量的不是这句话")


# ============================================================ c 反真空（判断本身）
def test_c_deleting_the_sign_judgment_turns_it_red() -> None:
    """d：把任一句「签到位…」判断删掉 ⇒ 校验函数必须红（c 不是"有个签字就算"）。"""
    for name, (text, needles, stale) in _surfaces().items():
        for needle in needles:
            assert needle in text, f"{name}：盘上没有 {needle!r} ⇒ 反真空打不中"
            broken = text.replace(needle, "")
            assert _problems(broken, needles, stale) != [], (
                f"{name}：删掉 {needle!r} 之后校验仍然绿 —— c 量的不是那句话")
    src = _register_source()
    for needle in GATE_NEEDLES:
        broken_src = src.replace(needle, "")
        assert broken_src != src, f"三道闸：盘上没有 {needle!r} ⇒ 反真空打不中"
        assert _gate_problems(broken_src) != [], (
            f"三道闸：删掉 {needle!r} 之后校验仍然绿 —— c 量的不是那句话")


# ============================================================ e + f V 的真实入口

#: V 的真实入口（`verifications.cold_start_prompt`）必须含的四件口径
#: （业主 2026-11-04 的同一裁定）：门槛按这一趟算 / 跨趟不累计 / 任一转 fault 即终局 /
#: V 稿投给被审者且不用 ack。数字与轮次只由框架数 —— 所以这里只钉语义，不钉任何转数。
COLD_NEEDLES: tuple[str, ...] = (
    "按这一趟算",
    "跨趟不累计",
    "按这一趟送审的门槛判",
    "判 `fault` ⇒ 立刻终止",
    "那一转就是终局",
    "v-review-NNNNNN.md",
    "不要求你或他再 ack",
)


def _cold_start_text() -> str:
    """V 的真实入口这一次渲染出来的文字（`agent_v/core.py::verify_proof` 用的就是它）。"""
    return VR.cold_start_prompt("对任意正整数 n，R(3,4)=9。",
                                "1. 由定义直接得到。", readonly_facts="- 夹具")


def _cold_problems(text: str) -> list[str]:
    """这一份真入口离「只说拿到签、不说内部几转」还差什么（空列表 = 合格）。"""
    out = [f"仍在教 V 的内部机制：{w!r}" for w in FORBIDDEN + STREAK_VARIANTS
           if w in text]
    out += [f"V 的真实入口漏了送审门槛的一件口径：缺 {n!r}" for n in COLD_NEEDLES
            if n not in text]
    return out


def test_e_the_real_entry_says_the_gate_is_per_submission() -> None:
    """e（a+b）：真入口含四件口径，且不含 `FORBIDDEN` 里任何一个词。"""
    problems = _cold_problems(_cold_start_text())
    assert problems == [], "V 的真实入口：\n  - " + "\n  - ".join(problems)


def test_f_deleting_the_gate_section_or_putting_the_streak_back_turns_it_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """f（c）：删掉那一节 ⇒ e 红；塞回「三转」⇒ e 红（两条都走真渲染路径）。"""
    gate = VR._cold_start_submission_gate()
    text = _cold_start_text()
    assert gate and gate in text, "盘上找不到送审门槛那一节 ⇒ 反真空打不中"
    assert _cold_problems(text) == []

    # 反真空 ①：把这一节删掉（打桩成空串 ⇒ 真渲染出来的文字里它就不在了）
    monkeypatch.setattr(VR, "_cold_start_submission_gate", lambda: "")
    removed = _cold_start_text()
    assert "按这一趟算" not in removed, (
        "删掉那一节之后真入口仍留着「按这一趟算」⇒ 反真空打不中（别处也写了这句）")
    assert _cold_problems(removed) != [], (
        "删掉送审门槛那一节之后校验仍然绿 —— e 量的不是那一节")
    monkeypatch.undo()

    # 反真空 ②：把改前的教程式说法塞回这一节
    monkeypatch.setattr(VR, "_cold_start_submission_gate",
                        lambda: gate + "\n（改前口径）V 连判三转「成立」之后才发签。")
    poisoned = _cold_start_text()
    assert _cold_problems(poisoned) != [], (
        "塞回「三转」之后校验仍然绿 —— e 量的不是 FORBIDDEN 那份词表")


# ============================================================ g + h PA4：扫尾的其余模型可见面
#
# 2026-11-17（PA4）：a–f 只量了 V/E 手册、`_needs_v_reason`、三道闸与 V 的真实入口。
# 全仓再扫一遍，另找到十三处同类文案（含 `specs/f.py` / `specs/b.py` 的 policy、各角色
# 手册正文与 V 的审阅通知；前两者进 `_surface_digest` ⇒ 本笔 p288 → p289，其余不进摘要）。
# 它们都是模型读得到的字，于是并进同一条：g 与 a 共用同一份 `FORBIDDEN`（外加
# `STREAK_VARIANTS` 那几个变体，不另抄一份词表），h 与 b/c 同形（塞回词 / 删掉正句都得红）。


def _docstring_ids(tree: ast.AST) -> set[int]:
    """AST 里所有 docstring 常量节点的 id（那一层是开发者说明，不在模型可见面上）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))
    return ids


def _runtime_strings(source: str) -> str:
    """源码里除 docstring 之外的字符串常量（注释不在 AST 里 ⇒ 自动不算）。"""
    tree = ast.parse(textwrap.dedent(source))
    skip = _docstring_ids(tree)
    return "\n".join(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in skip)


def _module_strings(module: Any) -> str:
    """一个模块里所有运行时字符串常量（模块级常量、prompt、拒信、建议、工具说明…）。"""
    return _runtime_strings(inspect.getsource(module))


def _function_strings(func: Any) -> str:
    """一个函数里所有运行时字符串常量（docstring 不算）。"""
    return _runtime_strings(inspect.getsource(func))


def _returned_strings(func: Any) -> str:
    """函数写进返回字典 `out` 的字符串（`out[...] = …` / `out.update(…)`）。

    只取返回面而不是整份函数：`_emit` 那几条是开发者日志，不在模型读得到的字里，
    按"赋值目标是不是 `out`"取，正好把返回的 `reason` / `detail` 收进来、把日志排除。
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    skip = _docstring_ids(tree)
    parts: list[str] = []

    def take(node: ast.AST) -> None:
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                    and id(sub) not in skip):
                parts.append(sub.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                   and t.value.id == "out" for t in node.targets):
                take(node.value)
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                    and target.value.id == "out" and node.value is not None):
                take(node.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "update"
              and isinstance(node.func.value, ast.Name) and node.func.value.id == "out"):
            for arg in node.args:
                take(arg)
    return "\n".join(parts)


def _pa4_surfaces() -> dict[str, tuple[str, tuple[str, ...]]]:
    """PA4 扫出的其余模型可见面：名字 → `(这一面模型看得到的文字, 必须保住的正句)`。"""
    from agentflow import closing as _CL
    from agentflow import conceptrows as _CR
    from agentflow import secretary as _SEC
    from agentflow import vsigns as _VS
    from agentflow import vreviews as _VRV
    from agentflow.agent_b import optimize_prompts as _OP
    from agentflow.agent_v.core import AgentV as _AgentV
    from agentflow.specs import f as _SF
    from agentflow.tools import verify_tools as _VT

    return {
        "F 的 policy（specs/f.py）": (
            _module_strings(_SF), ("由框架数满门槛",)),
        "各角色的操作手册（agent_skills.py）": (
            _module_strings(AS), ("这一趟的判定各一行",)),
        "B 的优化提示词（三档）": (
            _module_strings(_OP), ("V 的签盖在", "送去 V 拿签")),
        "优化候选的下一步建议": (
            _module_strings(_CL), ("重派 V 拿签", "派 V 拿签")),
        "概念良定义的下一步建议": (
            _module_strings(_CR), ("派 V 拿签",)),
        "B 的概念稿拒信": (
            _module_strings(RS), ("派 V 拿签", "签回来之后")),
        "V 送审工具的参数说明": (
            _module_strings(_VT), ("签到位后签块由收方秘书",)),
        "台账读数的 holding why": (
            _module_strings(VR), ("门槛由框架按这一趟送审自己数", "跨趟不累计")),
        "V 秘书的发签材料": (
            _module_strings(_SEC), ("门槛由框架按这一趟送审自己数",)),
        "V 的审阅通知（vreviews.py）": (
            _module_strings(_VRV), ("这一签已到位",)),
        "签文件的复算读数": (
            _module_strings(_VS), ("这几份不是同一份正文的票",)),
        "V 的 verify_proof 返回面": (
            _returned_strings(_AgentV.verify_proof), ("跨趟不累计", "这一趟到此为止")),
        "未在册散文那一支的返回": (
            _function_strings(_AgentV._review_unregistered_prose), ("判定读数照给",)),
    }


#: 反真空用的改前句子（每一句都含 `FORBIDDEN` 或 `STREAK_VARIANTS` 里的词；与 b/c 的毒句同一形态）。
PA4_STALE_SENTENCES: tuple[str, ...] = (
    "（改前口径）V 连判三转「成立」之后才发签。",
    "（改前口径）派 V 三转签，签回来之后收录。",
    "（改前口径）连续 3 次没问题才发签。",
    "（改前口径）同一趟送审里连续 3 转 clean。",
    "（改前口径）稿上签块写 连续=3/3。",
)


def test_g_the_rest_of_the_model_visible_copy_says_the_sign_not_the_streak() -> None:
    """g（a 的续）：PA4 扫出的其余模型可见面同口径 —— 只说签 / 门槛按这一趟数。"""
    surfaces = _pa4_surfaces()
    assert len(surfaces) >= 10, (
        f"只扫出 {len(surfaces)} 个面 ⇒ 这条判据退化成只看一处")
    for name, (text, needles) in surfaces.items():
        assert text.strip(), f"{name}：取不到文字 ⇒ 这一面是真空的"
        problems = _problems(text, needles)
        assert problems == [], f"{name}：\n  - " + "\n  - ".join(problems)


def test_h_putting_any_forbidden_word_or_dropping_a_needle_turns_it_red() -> None:
    """h（b/c 的续）：每个面塞回任一 `FORBIDDEN` 词 / 改前句子、或删任一正句，都必须红。"""
    for name, (text, needles) in _pa4_surfaces().items():
        assert _problems(text, needles) == []
        for word in FORBIDDEN + STREAK_VARIANTS:
            assert _problems(text + "\n" + word, needles) != [], (
                f"{name}：塞回 {word!r} 之后校验仍然绿 —— g 量的不是 FORBIDDEN")
        for stale in PA4_STALE_SENTENCES:
            assert _problems(text + "\n" + stale, needles) != [], (
                f"{name}：塞回改前句子 {stale!r} 之后校验仍然绿")
        for needle in needles:
            assert needle in text, f"{name}：盘上没有 {needle!r} ⇒ 反真空打不中"
            assert _problems(text.replace(needle, ""), needles) != [], (
                f"{name}：删掉 {needle!r} 之后校验仍然绿 —— g 量的不是那句话")
