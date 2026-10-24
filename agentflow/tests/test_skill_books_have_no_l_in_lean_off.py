# -*- coding: utf-8 -*-
"""关档时，落盘的技能手册正文不许再把模型指向 L。

业主 2026-10-24 的口径：形式化要不要做由用户指定、指定之后由 B 逐条安排、回执由 B 带回；
Lean 开关关着时 L 不存在（`leanscope`），于是 `<工作区>/skills/<角色>/<slug>.md` 里也不许
出现"找 L / 派 L / `B → L`"这类指路 —— 模型会 `fs.read` 这些正文，一句指路就是一个把 L
拉回来的后门（`materialize` 那一层的判据见 `agent_skills.materialize` 的 docstring）。

## 为什么这张改写表要有一条自己的判据

上一版把改写表写坏了：一条长串里把 `；` 写成 `，`，于是那一条整条空转（原串在正文里找不到，
`str.replace` 静默地什么也不做）；另外三句只提到 L、不含那 7 个命中词，于是"命中词为 0"的
读数照样是 0。两种失效都不会让任何既有判据变红。所以这里把"表不是空转的"单独做成判据 2 的
后半条，并要求替身自己也不许带着命中词（否则改写只是把 L 从一句挪到另一句）。

## 判据（改前的读数写在第四列）

| # | 判据 | 判据要挡住的错 | 改前 |
|---|---|---|---|
| 1 | 关档 `materialize` 到临时工作区，所有 md 里 7 个命中词 0 次 | 手册正文从"按需读的文档"这个后门把 L 放回来 | 5 处（F 一份 / M 两份 / V 一份） |
| 2 | 开档 `materialize`，`B → L` 仍在至少 1 份 md 里 | 反过来的错：把关档那一改写漏到开档（开档的协作面必须逐字不变） | 绿（表缺席时本判据不会红，见判据 3） |
| 3 | 每条 replacement 的原串在开档渲染出的某份 md 里逐字存在，且替身不带命中词 | 表空转：原串对不上，`str.replace` 静默地什么也不做 | 红（表不存在） |
| 4 | 关档下 `skills/L/` 目录不落盘（负控：开档时它在） | 回归：L 的整本手册被落盘 | 绿（既有行为） |

## 零模型 / 零真机

只调 `materialize` 往 `tmp_path` 写；不碰 `projects/` 下的真机工作区，不调模型、不起子进程。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import agent_skills as AS
from agentflow import leanscope
from agentflow import settings as SET

#: 真机探针用的 7 个命中词（业主 2026-10-24 的清单，逐字照抄）。
L_WORDS: tuple[str, ...] = (
    "派 L", "找 L", "L 那一岗", "L.check_formal", "formal.record", "B → L", "run-agent L",
)

#: 关档改写表（缺席读成空元组，由判据 3 报成"表空转"，不折叠成没问题）。
TABLE: tuple[tuple[str, str], ...] = getattr(AS, "NO_LEAN_SKILL_REPLACEMENTS", ())


def _materialize(root: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *, on: bool) -> dict[str, str]:
    """在给定开关档位下 materialize 到一个空目录，返回 `{相对路径: 正文}`。

    为什么每次都断言 `leanscope.lean_on()` 与请求的档位一致：`settings` 的开关梯子是
    "环境变量 > 设置文件 > 缺省"，本机设置文件里可能已经把 Lean 钉成某一档。不先断言，
    一个"两档跑的是同一档"的错会让两条判据同时读到同一批 md，而它们都会"通过"。
    """
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1" if on else "0")
    assert leanscope.lean_on() is on, "开关没落在请求的档位上（环境变量没压过设置文件？）"
    root.mkdir(parents=True, exist_ok=True)
    written = AS.materialize(root)
    assert written, f"一份都没落盘（{root}）"
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*.md"))}


def _expected_book_count() -> int:
    """这一档下应该落盘几份手册（反真空用的期望值，随 CATALOG 现算而不是写死）。"""
    return sum(len(rows) for owner, rows in AS.CATALOG.items() if not leanscope.is_hidden(owner))


# ============================================================ 判据 1
def test_lean_off_skill_books_carry_none_of_the_l_words(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """关档：所有落盘的 md 里，7 个命中词一次都不许出现。"""
    books = _materialize(tmp_path / "off", monkeypatch, on=False)
    assert len(books) == _expected_book_count(), "落盘的份数与目录对不上（先查 materialize）"
    found: dict[str, list[str]] = {}
    for rel, text in books.items():
        for word in L_WORDS:
            if word in text:
                found.setdefault(word, []).append(rel)
    assert found == {}, f"关档下手册正文里还有指向 L 的句子：{found}"


# ============================================================ 判据 2（负控）
def test_lean_on_skill_books_still_point_at_the_b_to_l_channel(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """开档：`B → L` 必须还在至少一份 md 里 —— 关档的改写不许漏到开档。"""
    books = _materialize(tmp_path / "on", monkeypatch, on=True)
    hits = [rel for rel, text in books.items() if "B → L" in text]
    assert hits, "开档下 B → L 一处都没有了：改写把开档那一档也改了（负控失败）"


# ============================================================ 判据 3（反真空）
def test_every_replacement_matches_the_lean_on_books_verbatim(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """表不许空转：每条原串都要在开档渲染出的某份 md 里逐字找得到，替身不带命中词。"""
    assert TABLE, ("agent_skills.NO_LEAN_SKILL_REPLACEMENTS 缺席或为空："
                   "关档那 5 处会原样留在手册里（空表不是没问题）")
    books = _materialize(tmp_path / "on", monkeypatch, on=True)
    problems: list[str] = []
    for i, (old, new) in enumerate(TABLE, 1):
        if not old:
            problems.append(f"第 {i} 条：原串是空的")
            continue
        homes = [rel for rel, text in books.items() if old in text]
        if not homes:
            problems.append(f"第 {i} 条：原串在开档手册里一个字都找不到（空转）—— {old[:40]!r}")
        if old == new:
            problems.append(f"第 {i} 条：原串与替身相同（这条不做事）")
        carried = [word for word in L_WORDS if word in new]
        if carried:
            problems.append(f"第 {i} 条：替身自己还带着命中词 {carried}")
    assert not problems, problems


# ============================================================ 判据 4（防回归）
def test_lean_off_lays_down_no_l_skills_directory(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """关档：`skills/L/` 不落盘；开档：它在（负控，否则上面那条在一个空目录上恒真）。"""
    off_root = tmp_path / "off"
    _materialize(off_root, monkeypatch, on=False)
    assert not (off_root / AS.SKILLS_DIR / "L").exists(), "关档下 L 的手册被落盘了"

    on_root = tmp_path / "on"
    _materialize(on_root, monkeypatch, on=True)
    assert (on_root / AS.SKILLS_DIR / "L").is_dir(), "开档下 L 的手册反而没落盘（负控失败）"
