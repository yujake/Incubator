# -*- coding: utf-8 -*-
"""skills 是不是还停在旧口径上（业主 2026-10-27 那一夜改过的那九条）。

## 这一份判据守什么

`agent_skills.CATALOG` 是十条角色（含 shared）现读的 47 份操作手册。手册是"现做现读"的那一半：
提示词里只有索引，正文由角色自己 `fs.read`。于是一句过时的话不会像代码那样当场炸，
它会在下一次真跑里被照着做 —— 事后只能从台账倒推。所以这一份把"正文与最新口径对不对得上"
做成机器可查的两件事：

1. 清点：目录里每一条 skill 都必须在代码里有那一条 `slug=` 字面量、在盘上（`materialize`）有
   那份非空的 md、在索引里有一行。防的是"索引里挂着、文件没了"（模型点开是空的，
   而没有任何地方会报错）。
2. 比对：九条口径各有一组机器可查的形态（`RULES`）。命中即"这条 skill 还在讲旧口径"，
   记进 `STALE_SKILLS` 台账。

## 台账为什么是空的，以及它怎么变红

`STALE_SKILLS == {}` 是这一夜的结论：清点出来的 47 条里，过时的已经改完，剩下的都不涉及这九条
（逐条判决见本仓的审查记录）。台账按 `tests/test_green_is_not_faked.py` 的同一种写法用：
判据两向相等——

- 实测多一条（谁在正文里塞进一句旧口径）⇒ 红；
- 台账多一条（改好了却没把台账那一行删掉）⇒ 也红。

一条永远绿的判据与一条永远红的判据一样没有信息量，所以两向都要咬。

## 九条口径与它们对应的规则

| 口径 | 规则 id |
|---|---|
| 计时只有主时钟九件，旧定时工具名一律错 | `clock-tool-names` |
| 挂机 = 挂在时钟上，不轮询不睡不空转 | `wait-on-clock` |
| 挂机与定期巡查都挂在时钟上 | `parking-on-clock` |
| 三态：在飞 / 待机 / 静默（活跃 = 非静默） | `active-is-non-silent` |
| 销号只可针对静默子代理 | `retire-only-silent` |
| 消息走绝对编号链逐级转发，正文只到链尾 | `message-chain` |
| 依赖面由 F 写进手稿 `## 依赖` 四列表，B 读稿登记；引用要 proof_review 级及以上 | `dependency-section` |
| 命题同一性由秘书按条件与结论判，路线进证明层不进定理名 | `proposition-identity` |
| 非平凡度按证明花的力气判 | `nontrivial-by-effort` |
| 引用核实是六档，不要求逐字 | `citation-six-verdicts` |
| 工具与动作的读数不写死进手册 | `no-frozen-counts` |

最后一条不属于那九条，但它是同一类错：手册里抄一份"多少个工具"的读数，第二天就过时，
而且不会有任何地方跟着改（真机：`agent_skills` 的模块 docstring 挂着"60 动作 / 32 边"，
而实测早就是 64 / 35）。
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

import pytest

from agentflow import agent_skills as AS
from agentflow import leanscope as LEAN

#: 过时台账：slug -> 命中的规则 id。今天是空的（九条口径已逐条比对并改完）。
#:
#: 写这一行的人要同时交出两样东西：改的是哪一句（旧原文 -> 新原文），以及为什么改完它可以删。
#: 只删不加、或只加不删，都会被 `test_no_stale_skill_survives` 咬住。
STALE_SKILLS: dict[str, tuple[str, ...]] = {}

#: 反真空下限：清点出来的条数少于它，说明目录读坏了，而不是"没有过时的"。
MIN_INVENTORY = 40


# --------------------------------------------------------------- 目录与载体

def _rows() -> list[tuple[str, AS.Skill]]:
    """(归属, skill) 的全清单，顺序与 `CATALOG` 一致（`shared` 也在里面）。"""
    return [(role, sk) for role, skills in AS.CATALOG.items() for sk in skills]


def _clock_tools() -> frozenset[str]:
    """工具面上真实的 `clock.*`（现读注册表，不抄字面量）。

    抄一份名字清单就是给"九件"造第二个真身：加第十件时，手册里的白名单会静默把新件判成旧件。
    """
    from agentflow.tools import build_registry

    names = build_registry().registry.names()
    return frozenset(n for n in names if n.startswith("clock."))


# --------------------------------------------------------------- 规则本体
#
# 每条规则：(id, 一句人话, 判据)。判据收 (归属角色, skill)，命中就回一句证据（供报错读），
# 没命中回 None。规则只读正文，不改任何东西 —— 判据与修法是两件事。

_CLOCK_TOKEN = re.compile(r"`(clock\.[a-z0-9_]+)`")

#: 旧口径里"怎么等"的那些说法。刻意不拦"不要轮询"这种否定式写法：
#: 新手册要说"别轮询"，拦掉它就把正确写法也判成错的。
_STALE_WAIT = (
    re.compile(r"(?:靠|用|以|通过|不断|反复)\s*轮询"),
    re.compile(r"轮询(?:等待|等|检查|看)"),
    re.compile(r"睡一会儿|睡一觉|打个盹|睡上\s*\d+"),
    re.compile(r"sleep\s*\("),
    re.compile(r"\bpolling\b"),
)

#: 旧口径里"销号"被写成了可以对谁都做（只截近处：名册名退役那一档不在此列）。
_KILL_NEAR = re.compile(
    r"(?:子代理|在飞|待机|活着)[^。；\n]{0,20}销号|销号[^。；\n]{0,12}(?:子代理|在飞|待机)"
)

#: 消息那一格被取消掉的旧说法（"各级父都知道"）。
_STALE_MESSAGE = (
    "各级父", "每级父", "每个父", "父都", "各开一条板项", "层层转发", "层层通知",
    "抄送每个", "所有上级都发",
)

#: 命题同一性的旧判据（按字面判"是不是同一条"）。前置的否定词要放过：
#: 新手册写的是"不按字符串判同一"，拦掉它就把正确写法也判成错的。
_STALE_IDENTITY = (
    re.compile(r"(?<![不别非勿])按字符串"),
    re.compile(r"(?<![不别])字符串相同"),
    re.compile(r"名字相同就算"),
    re.compile(r"标题相同就是同一条"),
    re.compile(r"看标题判重"),
)

#: 依赖面里那条"F 自己写台账"的旧说法（分工是 F 写手稿、B 读稿登记）。
_F_WRITES_STATEMENTS = re.compile(r"F\s*(?:自己)?写\s*`?statements")

#: `## 依赖` 那一节的两种写法：正文里的段标题，或一句点名的行内写法。
#: 只认标题本身（`### 依赖闭合` 那种别的段不算）。
_DEP_SECTION = re.compile(r"(?m)^## 依赖\s*$")

#: 引用核实的六档（唯一真身在 `verifications.CITATION_VERDICTS`，那一份是受控词表）。
CITATION_VERDICTS = ("consistent", "weaker", "stronger", "unrelated", "inadmissible", "unknown")

#: 手册里冻结的工具/动作/边读数（`15 个动作` 这种会随权限面漂）。
_FROZEN_COUNT = re.compile(r"\d+\s*(?:个|件)\s*(?:工具|动作)|(?:\d+)\s*条边")


def _rule_clock_tool_names(role: str, sk: AS.Skill) -> str | None:
    known = _clock_tools()
    for tok in _CLOCK_TOKEN.findall(sk.body):
        if tok not in known:
            return f"正文点名了工具面上不存在的时钟工具 {tok}（九件是 {sorted(known)}）"
    return None


def _rule_wait_on_clock(role: str, sk: AS.Skill) -> str | None:
    for pat in _STALE_WAIT:
        m = pat.search(sk.body)
        if m:
            return f"旧口径的等待写法「{m.group(0)}」：等待只挂在主时钟上（clock 九件），不睡不轮询"
    return None


def _rule_parking_on_clock(role: str, sk: AS.Skill) -> str | None:
    if "挂机" in sk.body and "时钟" not in sk.body:
        return "讲了挂机却没讲它挂在时钟上（挂机 = 把这一趟挂在时钟上，不是自己空转）"
    if ("定期" in sk.body or "周期性巡查" in sk.body) and "时钟" not in sk.body:
        return "讲了定期 / 周期性巡查却没讲它挂在时钟上（计时类工作只有主时钟这一处）"
    return None


def _rule_active_is_non_silent(role: str, sk: AS.Skill) -> str | None:
    if "活跃" in sk.body and "静默" not in sk.body:
        return "用了「活跃」却没写它与三态的关系（活跃 = 非静默；三态是在飞 / 待机 / 静默）"
    return None


def _rule_retire_only_silent(role: str, sk: AS.Skill) -> str | None:
    m = _KILL_NEAR.search(sk.body)
    if m and "静默" not in sk.body:
        return f"把销号说成可以对子代理做（「{m.group(0)[:24]}」）：销号只可针对静默子代理"
    return None


def _rule_message_chain(role: str, sk: AS.Skill) -> str | None:
    for kw in _STALE_MESSAGE:
        if kw in sk.body:
            return f"旧口径「{kw}」：消息走绝对编号链逐级转发，正文只到链尾"
    if "转发" in sk.body and "链尾" not in sk.body:
        return "讲了转发却没讲「正文只到链尾」（各级父不再各自留一份）"
    return None


def _rule_dependency_section(role: str, sk: AS.Skill) -> str | None:
    m = _F_WRITES_STATEMENTS.search(sk.body)
    if m:
        return (f"旧分工「{m.group(0)}」：F 写证明手稿、B 读稿登记（F 不写 statements、不填 bits）")
    if "`## 依赖`" not in sk.body and not _DEP_SECTION.search(sk.body):
        return None
    if "四列" not in sk.body:
        return "讲了 `## 依赖` 却没给四列表（引用 / 命题号 / 用在哪一步 / 路径号）"
    if role in ("F", "B") and "proof_review" not in sk.body:
        return "讲了 `## 依赖` 却没写引用档位下限 proof_review（不够格被引 ⇒ inadmissible）"
    return None


def _rule_proposition_identity(role: str, sk: AS.Skill) -> str | None:
    for pat in _STALE_IDENTITY:
        m = pat.search(sk.body)
        if m:
            return f"旧判据「{m.group(0)}」：同一性由秘书读条件与结论判，不按字符串"
    if "定理名" in sk.body and "路线" not in sk.body:
        return "讲了定理名却没讲「路线进证明层、不进定理名」"
    return None


def _rule_nontrivial_by_effort(role: str, sk: AS.Skill) -> str | None:
    if "非平凡" in sk.body and "力气" not in sk.body:
        return "讲了非平凡度却没按「证明花的力气」判（体量 / 步骤 / 引理 / 跨度 / 绕路）"
    return None


def _rule_citation_six_verdicts(role: str, sk: AS.Skill) -> str | None:
    if role != "V":
        return None
    if "引文轴" not in sk.body and "citation_checks" not in sk.body:
        return None
    missing = [v for v in CITATION_VERDICTS if v not in sk.body]
    if missing:
        return f"引用核实缺这几档：{missing}（六档，且不要求逐字）"
    return None


def _rule_no_frozen_counts(role: str, sk: AS.Skill) -> str | None:
    m = _FROZEN_COUNT.search(sk.body)
    if m:
        return (f"手册里写死了权限面读数「{m.group(0)}」：动作、边、工具每天都在变，"
                f"读数由工具面现算，别抄进正文")
    return None


#: (规则 id, 它守的那句口径, 判据)。
RULES: tuple[tuple[str, str, object], ...] = (
    ("clock-tool-names", "计时只有主时钟九件，旧定时工具名一律错", _rule_clock_tool_names),
    ("wait-on-clock", "挂机 = 挂在时钟上，不睡不轮询", _rule_wait_on_clock),
    ("parking-on-clock", "挂机是挂在时钟上", _rule_parking_on_clock),
    ("active-is-non-silent", "三态：在飞 / 待机 / 静默（活跃 = 非静默）", _rule_active_is_non_silent),
    ("retire-only-silent", "销号只可针对静默子代理", _rule_retire_only_silent),
    ("message-chain", "消息逐级转发，正文只到链尾", _rule_message_chain),
    ("dependency-section", "依赖面写在手稿 `## 依赖` 四列表，引用要 proof_review 级", _rule_dependency_section),
    ("proposition-identity", "秘书按条件与结论判同一，路线不进定理名", _rule_proposition_identity),
    ("nontrivial-by-effort", "非平凡度按证明花的力气判", _rule_nontrivial_by_effort),
    ("citation-six-verdicts", "引用核实六档，不要求逐字", _rule_citation_six_verdicts),
    ("no-frozen-counts", "权限面读数不抄进手册", _rule_no_frozen_counts),
)

RULE_IDS: tuple[str, ...] = tuple(r[0] for r in RULES)


def stale_report() -> dict[str, tuple[str, ...]]:
    """实测的过时集合：slug -> 命中的规则 id（空 dict = 一条都没有）。

    这是判据的唯一读数口；正控、两向台账、负控都读它，避免"测的不是判的那一个"。
    """
    out: dict[str, tuple[str, ...]] = {}
    for role, sk in _rows():
        hits = tuple(sorted(rid for rid, _why, fires in RULES if fires(role, sk)))
        if hits:
            out[sk.slug] = hits
    return out


# --------------------------------------------------------------- 判据

def test_no_stale_skill_survives() -> None:
    """正控：过时集合 == 空集（与 `STALE_SKILLS` 台账两向相等）。"""
    measured = stale_report()
    newer = sorted(set(measured) - set(STALE_SKILLS))
    cleared = sorted(set(STALE_SKILLS) - set(measured))
    changed = sorted(s for s in set(measured) & set(STALE_SKILLS)
                     if measured[s] != STALE_SKILLS[s])
    assert measured == STALE_SKILLS, (
        "skills 与最新口径的比对结果与台账不符。\n"
        f"  实测命中、台账没写：{newer}\n"
        f"    逐条命中：{ {b: list(measured[b]) for b in newer} }\n"
        f"  台账写了、实测已经干净：{cleared}（改好了就把台账那一行删掉）\n"
        f"  两边都有但命中的规则变了：{ {c: [list(STALE_SKILLS[c]), list(measured[c])] for c in changed} }\n"
        "判据两侧都咬：多一条红，修好不改台账也红。"
    )


def test_the_inventory_is_not_vacuous() -> None:
    """反真空：清点得出来，且每条都指得出归属。"""
    rows = _rows()
    assert len(rows) >= MIN_INVENTORY, f"只清点到 {len(rows)} 条 skill，目录像是读坏了"
    assert len(rows) == sum(len(v) for v in AS.CATALOG.values())
    for role, sk in rows:
        assert role in (AS.SHARED, *AS.CATALOG.keys()), role
        assert sk.slug.strip() and sk.title.strip(), (role, sk.slug)
        assert sk.summary.strip() and sk.when.strip(), (role, sk.slug)


def test_every_skill_is_in_the_code_on_disk_and_in_the_index(tmp_path, monkeypatch) -> None:
    """载体三处齐全：代码里有 `slug=` 字面量、盘上有非空 md、索引里有一行。

    盘上那一档要在 Lean 开着的前提下看：关档时 L 那一族按设计不落盘（那是"它今天不存在"，
    不是"文件丢了"）。所以这里把开关钉成开，核的是载体本身。
    """
    monkeypatch.setattr(LEAN, "lean_on", lambda: True)
    monkeypatch.setattr(LEAN, "is_hidden", lambda role: False)
    AS.materialize(tmp_path)

    source = pathlib.Path(AS.__file__).read_text(encoding="utf-8")
    for role, sk in _rows():
        assert f'slug="{sk.slug}"' in source, f"{sk.slug} 在代码里找不到 slug 字面量"
        assert sk.title in source, f"{sk.slug} 的标题在代码里找不到"

        path = tmp_path / AS.SKILLS_DIR / role / f"{sk.slug}.md"
        assert path.is_file(), f"{sk.slug} 在盘上没有文件：{path}"
        text = path.read_text(encoding="utf-8")
        assert sk.title in text, (sk.slug, "落盘那一份没有标题行")
        first = next((ln.strip() for ln in sk.body.splitlines()
                      if ln.strip() and not ln.strip().startswith("#")), "")
        assert first, f"{sk.slug} 的正文是空的"
        assert first in text, (sk.slug, f"落盘那一份缺正文首行：{first[:40]}")

        assert sk.slug in AS.index_block(role), f"{sk.slug} 没有出现在 {role} 的索引里"


# --------------------------------------------------------------- 负控

#: 每条规则一句话就够咬到的反例（role, 正文片段）。少一条就说明那条规则是空转的。
RULE_NEGATIVES: dict[str, tuple[str, str]] = {
    "clock-tool-names": ("M", "等不了就 `clock.sleep` 一下。"),
    "wait-on-clock": ("M", "派完之后轮询等待，每隔几拍看一眼。"),
    "parking-on-clock": ("M", "派完之后定期回来扫一遍全树。"),
    "active-is-non-silent": ("M", "看哪些子代理活跃。"),
    "retire-only-silent": ("M", "把在飞的子代理销号，腾出并发额度。"),
    "message-chain": ("M", "每级父各开一条板项，各级父都知道。"),
    "dependency-section": ("F", "手稿里加一节 `## 依赖`，两列就够（引用 / 命题号）。"),
    "proposition-identity": ("B", "按字符串判重：标题一样就算同一条。"),
    "nontrivial-by-effort": ("B", "判非平凡看它对不对、有没有人用得上。"),
    "citation-six-verdicts": ("V", "引文轴：引用外部结论的那几步，引文是否真的在原文里。"),
    "no-frozen-counts": ("M", "现在一共 111 个工具。"),
}


def _synthetic(role: str, text: str) -> AS.Skill:
    """造一条只用来喂判据的假 skill（slug 带前缀，免得和真目录撞名）。"""
    return AS.Skill(slug="负控-假条目", title="负控", summary="一句话", when="任何时候", body=text)


def test_every_rule_has_a_negative_control_and_it_bites() -> None:
    """每条规则都要有自己的反例，而且那反例真的被它咬到。

    没有这一条，"过时集合为空"只说明规则没响 —— 而规则没响与规则坏了在输出上一模一样。
    """
    assert set(RULE_NEGATIVES) == set(RULE_IDS), "有规则没有反例，或反例没有规则"
    for rid, _why, fires in RULES:
        role, text = RULE_NEGATIVES[rid]
        hit = fires(role, _synthetic(role, text))
        assert hit, f"规则 {rid} 没咬到它自己的反例：{text}"


def test_negative_control_the_old_message_wording_turns_the_criterion_red(monkeypatch) -> None:
    """端到端负控：往一条真 skill 的正文里塞一句旧口径，判据必须变红。

    这是业主点名的那一句（「每级父各开一条板项」）：它属于消息那一格，
    而那一格今天已经取消（正文只到链尾）。
    """
    target = next(sk for _role, sk in _rows() if sk.slug == "规划-先了解全貌再定方向")
    poisoned = dataclasses.replace(
        target, body=target.body + "\n指导同时往上报，每级父各开一条板项。\n")
    monkeypatch.setitem(
        AS.CATALOG, "M",
        tuple(poisoned if sk is target else sk for sk in AS.CATALOG["M"]))

    measured = stale_report()
    assert measured != STALE_SKILLS, "旧口径塞进正文之后，判据还是绿的 —— 这条判据是空转的"
    assert "message-chain" in measured.get(poisoned.slug, ()), measured


def test_negative_control_a_cleared_ledger_entry_also_turns_red(monkeypatch) -> None:
    """另一侧：把一条已经干净的 skill 记进台账 ⇒ 判据也必须红（防"台账只加不删"）。"""
    clean = next(sk for _role, sk in _rows()
                 if not stale_report().get(sk.slug) and sk.slug == "留痕-证据先行")
    monkeypatch.setitem(STALE_SKILLS, clean.slug, ("message-chain",))
    measured = stale_report()
    assert measured != STALE_SKILLS
    assert clean.slug not in measured
