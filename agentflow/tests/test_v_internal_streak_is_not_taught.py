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
"""
from __future__ import annotations

import pathlib

from agentflow import agent_skills as AS
from agentflow.agent_b import register_statement as RS

PROJECT = pathlib.Path(__file__).resolve().parents[1]

#: V 内部连判的教程式说法（模型拿不到这些，也不该被要求推断）。
FORBIDDEN: tuple[str, ...] = ("三转", "连判", "连续三次", "连续 3 次", "连续3次", "第 1、2 次")

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
    for word in FORBIDDEN:
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
