# -*- coding: utf-8 -*-
"""判据（D-48）：B 的提示词只用「非平凡性档位 T0–T4 ＋ 未判」，不再留"是否太平凡"那一栏。

## 这条判据守什么

业主 2026-10-24 的原话：「B侧收录为什么还是有"是否太平凡"这栏？不是已经被T0到T4取代了吗？」

行为侧早就对了（拒绝码 `statement_too_trivial` 在 `agent_b/register_statement.py` 与
`schema.py` 里已无产生点），错的是措辞：B 的政策与立场里仍写着"判太平凡就降为 T0"、
"提交时要写清为什么它不平凡"、"秘书判「太平凡/合格」"——两套语言并存，读的人（人也是、
模型也是）会以为还有一道"收不收"的关，而它已经变成"判哪一档"。

## 判据四条

1. `specs/b.py` 的非注释源码里零命中 `(?<!非)平凡`；注释里允许命中，但只认同时提到
   「业主」「裁定」的历史留痕注释（引用裁定原文那一行），其余注释命中照样红 ——
   否则"注释豁免"会变成藏措辞的后门；
2. B 的职责声明（`agent_prompts.ROLE_BRIEFS["B"]` 的 duty / boundary / policy /
   signature_error / deliverable / stance）里零命中；
3. 负控（不许把档位口径一起删掉）：`T0`、`T4`、`T0–T4`、`非平凡性档位`、`未判`
   这五样仍在 B 的声明里；
4. 反真空：往声明里塞回一句"太平凡的命题不许收"⇒ 第 2 条必红；往源码里塞回一行
   字符串 ⇒ 第 1 条必红；塞进一条不带裁定留痕的注释 ⇒ 第 1 条也必红。

## 边界（这条判据不覆盖谁）

2026-10-24 之前整份 B 提示词里还剩一处命中：技能索引那一行
`skills/B/审美-太平凡的不收.md`（slug 是历史名字，归技能手册那条线）。那一天 B2 落地时
那条技能也换了口径（标题/摘要/正文改写成"按证明花的力气判档"），于是现在是 0 命中。
第 5 条判据仍写 `<= 1`：它守的是"任何新加回来的措辞当场红"，不是"必须留一行"。

`webui/readers.py` 的 hover 说明（人类在页面上看到的那句）只改字符串、不改键名，
第 6 条判据钉住这一点：档位键仍是 0..4 五个、每句仍以 `T<档>` 开头、`未判` 仍是
`NONTRIVIALITY_UNJUDGED_WORD` 的值。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import replace

import pytest

from agentflow import agent_prompts as AP
from agentflow.tools import build_registry
from agentflow.webui import readers as R

_REPO = pathlib.Path(__file__).resolve().parents[1]
_B_SPEC = _REPO / "src" / "agentflow" / "specs" / "b.py"

#: "太平凡 / 平凡"；"非平凡"不算（那是档位轴的正式名字）。
TRIVIAL_WORDING = re.compile(r"(?<!非)平凡")

#: 历史留痕注释的标记（两条同时出现才算引用裁定原文）。
HISTORY_MARKS = ("业主", "裁定")

#: B 的声明的六个字段（顺序同 `AgentBrief`）。
_BRIEF_FIELDS = ("duty", "boundary", "policy", "signature_error", "deliverable", "stance")

#: 负控要的五样档位口径（T0–T4 用区间写法钉住；逐个 T1/T2/T3 不在文案里逐字出现是允许的）。
_TIER_WORDS = ("T0", "T4", "T0–T4", "非平凡性档位", "未判")

#: 整份 B 提示词里允许残留的唯一一行（登记在案的历史技能名）。
_REGISTERED_RESIDUAL = re.compile(r"skills/B/审美-")


def _brief_pieces(brief: object | None = None) -> list[tuple[str, str]]:
    """B 的声明拆成 (字段名, 那一段正文) 的列表（str 与 tuple 两种字段形状都认）。"""
    got = brief if brief is not None else AP.ROLE_BRIEFS["B"]
    out: list[tuple[str, str]] = []
    for field in _BRIEF_FIELDS:
        value = getattr(got, field)
        if isinstance(value, str):
            out.append((field, value))
        else:
            out.extend((field, str(item)) for item in value)
    return out


def _brief_hits(brief: object | None = None) -> list[tuple[str, str]]:
    """声明里命中的那几段（空 = 干净）。"""
    return [(field, text) for field, text in _brief_pieces(brief)
            if TRIVIAL_WORDING.search(text)]


def _source_scan(path: pathlib.Path) -> tuple[list[str], list[str]]:
    """扫一个源码文件：返回 (非注释命中, 历史留痕注释命中)。"""
    bad: list[str] = []
    history: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not TRIVIAL_WORDING.search(line):
            continue
        stripped = line.lstrip()
        if stripped.startswith("#"):
            if all(mark in line for mark in HISTORY_MARKS):
                history.append(f"{number}:{stripped}")
            else:
                bad.append(f"{number}:{stripped}")
        else:
            bad.append(f"{number}:{stripped}")
    return bad, history


def _full_prompt() -> str:
    """按测试口径渲染一份 B 的提示词（不带工作区：没有 fs 工具那一档）。"""
    registry = build_registry().registry
    return AP.system_prompt("B", registry=registry, task="把这条链路走一遍",
                            workspace_root="D:/x")


@pytest.fixture(scope="module")
def b_prompt() -> str:
    return _full_prompt()


# ---------------------------------------------------------------- ① 源码


def test_b_source_has_no_trivial_wording_outside_history_comments() -> None:
    """① 非注释源码零命中；有命中的注释必须是引用业主裁定的历史留痕。

    若这条破了：B 的政策里还挂着"判太平凡就降为 T0"这类说法，读的人会以为
    还有一道"收不收"的关 —— 而行为侧早已改成"判哪一档"。
    """
    bad, history = _source_scan(_B_SPEC)
    assert bad == [], (
        "`specs/b.py` 的非注释源码里还有 '太平凡/平凡' 这套措辞（应当只用 T0–T4 ＋「未判」）：\n  "
        + "\n  ".join(bad))
    # 反真空的另一半：豁免的那几行必须真的存在（否则"历史注释"这一档没被走到，
    # 这条判据就退化成"全文件零命中"，下一次有人删掉裁定留痕也没人知道）。
    assert history, "`specs/b.py` 里一条历史留痕注释都没有 ⇒ 这一档豁免没有被走到"


def test_a_trivial_wording_smuggled_into_a_comment_is_red(tmp_path: pathlib.Path) -> None:
    """①的反真空：往注释里塞回措辞（不带裁定留痕）⇒ 必须红；塞进字符串 ⇒ 也必须红。

    若这条破了：`_source_scan` 豁免了整个注释面，"藏进注释"就成了后门。
    """
    lines = _B_SPEC.read_text(encoding="utf-8").splitlines()
    comment_variant = tmp_path / "b_comment.py"
    comment_variant.write_text(
        "\n".join(lines[:290] + ["            # 这里塞回一句：太平凡的命题不许收。"] + lines[290:]),
        encoding="utf-8")
    bare_comment, _history = _source_scan(comment_variant)
    assert bare_comment, "不带裁定留痕的注释里塞回措辞，扫描却绿了 ⇒ 注释豁免是个后门"

    string_variant = tmp_path / "b_string.py"
    string_variant.write_text(
        "\n".join(lines[:290] + ['            "这里塞回一句：太平凡的命题不许收。",'] + lines[290:]),
        encoding="utf-8")
    bad_string, _ = _source_scan(string_variant)
    assert bad_string, "往源码字符串里塞回措辞，扫描却绿了 ⇒ 这条判据没有牙"


# ---------------------------------------------------------------- ② 提示词


def test_b_brief_has_no_trivial_wording() -> None:
    """② B 的职责声明（六个字段）里零命中。

    若这条破了：模型在政策/立场里仍会读到"太平凡"这套判断，于是它照旧去猜
    "这一条会不会被拒"，而真正的口径是"判哪一档、判不了写未判"。
    """
    hits = _brief_hits()
    assert hits == [], (
        "B 的声明里还有 '太平凡/平凡' 这套措辞：\n  "
        + "\n  ".join(f"[{field}] {text[:160]}" for field, text in hits))


def test_putting_the_wording_back_into_the_brief_makes_it_red() -> None:
    """②的反真空：把一句"太平凡"塞回声明 ⇒ 同一个检查必须点名它。"""
    brief = AP.ROLE_BRIEFS["B"]
    broken = replace(brief, policy=brief.policy + ("这条命题太平凡，不许收。",))
    hits = _brief_hits(broken)
    assert hits, "塞回一句『太平凡』之后声明仍判干净 ⇒ ② 这条判据没有牙"
    assert any("太平凡" in text for _field, text in hits), hits


# ---------------------------------------------------------------- ③ 负控


def test_the_tier_language_is_still_there() -> None:
    """③ 负控：不许为了删措辞把档位口径一起删掉（T0–T4 与「未判」都得在）。

    若这条破了：B 既不知道有档位轴、也不知道判不了怎么写 —— D-48 的"改成只用
    T0–T4 的说法"就变成了"什么说法都没有"。
    """
    text = "\n".join(piece for _field, piece in _brief_pieces())
    missing = [word for word in _TIER_WORDS if word not in text]
    assert missing == [], f"B 的声明里缺了这些档位口径：{missing}"


# ---------------------------------------------------------------- ④ 残留面


def test_the_only_residue_in_the_full_prompt_is_the_registered_historical_skill(
        b_prompt: str) -> None:
    """④ 整份 B 提示词里剩下的命中只许是那行登记在案的历史技能名。

    为什么允许这一行：`agent_skills.py` 里那条技能的正文第一句就写着"本文件的 slug
    是历史名字，业主 2026-10-23 的裁定改了收场方式"——它是留痕，不是第二套口径；
    它归技能手册那条线，本批不动。判据钉的是"任何新加回来的措辞当场红"。
    """
    hits = [line.strip() for line in b_prompt.splitlines() if TRIVIAL_WORDING.search(line)]
    strange = [line for line in hits if not _REGISTERED_RESIDUAL.search(line)]
    assert strange == [], (
        "B 的提示词里出现了未登记的历史技能名以外的 '太平凡/平凡' 措辞：\n  "
        + "\n  ".join(strange))
    assert len(hits) <= 1, f"整份提示词里残留了 {len(hits)} 行（只许那行历史技能名）：{hits}"


# ---------------------------------------------------------------- ⑤ 页面 hover


def test_reader_hover_strings_are_tier_only_and_the_keys_are_unchanged() -> None:
    """⑤ `readers.py` 的 hover 说明只用档位说法，档位键仍是 0..4、`未判` 仍是那个值。

    为什么只改字符串、不改键名：那个文件另有 lane 在动，而键名（`0..4`）是读数契约；
    改键名等于改"页面按哪一格取说明"，那不是措辞问题。
    """
    assert set(R._NONTRIVIALITY_MEANINGS) == {0, 1, 2, 3, 4}, (
        f"档位键变了：{sorted(R._NONTRIVIALITY_MEANINGS)}")
    bad = {level: text for level, text in R._NONTRIVIALITY_MEANINGS.items()
           if TRIVIAL_WORDING.search(text)}
    assert bad == {}, f"hover 说明里还有 '太平凡/平凡'：{bad}"
    for level, text in R._NONTRIVIALITY_MEANINGS.items():
        assert text.startswith(f"T{level} "), f"T{level} 的 hover 说明没有以档位名开头：{text!r}"
    assert "基础定理" in R._NONTRIVIALITY_MEANINGS[0], R._NONTRIVIALITY_MEANINGS[0]
    assert R.NONTRIVIALITY_UNJUDGED_WORD == "未判", R.NONTRIVIALITY_UNJUDGED_WORD


def test_a_hover_string_with_the_old_wording_would_be_caught() -> None:
    """⑤的反真空：把旧那句 hover 塞回去 ⇒ 同一个检查必须看见。"""
    broken = dict(R._NONTRIVIALITY_MEANINGS)
    broken[0] = "T0 基础定理或初步结论（平凡但真；含由数值实验直接穷举得出的那些）"
    bad = {level: text for level, text in broken.items() if TRIVIAL_WORDING.search(text)}
    assert bad, "旧那句 hover 塞回去之后检查仍判干净 ⇒ ⑤ 没有牙"
