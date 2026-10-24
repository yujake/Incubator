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

## 第二批：7 个词看不见的那些行

第一批只清了含那 7 个词的 5 处句子，清完仍有 4 份 md / 5 行把 L 当成能干活的角色：F 的工具清单
（「`L` 的形式化」）、G 的「L 的形式化产物只作凭据」与 H 审校判据里那半句、shared 的
「`formal`（L 签）」与「`L.formalize`（形式化那一档归 L）」。它们一个命中词都不含，所以第一批的
读数是绿的。第二批按"行里有独立的 `L`、且同一行在讲形式化 / 检查器 / 派 / 那一岗"这条口径清，
并把这条口径固化成判据 5；业主原话那一行逐字保留（进允许清单，写清为什么）。

## 判据（改前的读数写在第四列）

| # | 判据 | 判据要挡住的错 | 改前 |
|---|---|---|---|
| 1 | 关档 `materialize` 到临时工作区，所有 md 里 7 个命中词 0 次 | 手册正文从"按需读的文档"这个后门把 L 放回来 | 5 处（F 一份 / M 两份 / V 一份） |
| 2 | 开档 `materialize`，`B → L` 仍在至少 1 份 md 里 | 反过来的错：把关档那一改写漏到开档（开档的协作面必须逐字不变） | 绿（表缺席时本判据不会红，见判据 3） |
| 3 | 每条 replacement 的原串在开档渲染出的某份 md 里逐字存在，且替身不带命中词 | 表空转：原串对不上，`str.replace` 静默地什么也不做 | 红（表不存在） |
| 4 | 关档下 `skills/L/` 目录不落盘（负控：开档时它在） | 回归：L 的整本手册被落盘 | 绿（既有行为） |
| 5 | 关档下这些手册里 L 不再作为"能干活的角色"出现（行内有独立 `L` 且同一行讲形式化 / 检查器 / 派 / 那一岗），允许清单只有业主原话那一行；同时每条原串不许还留在关档手册里 | 7 词探针看不见的那些指路（第二批那 5 行） | 红：G 两行 + F 一行 + shared 两行 |
| 6 | 反真空：删掉一条替换 ⇒ 判据 5 必红 | 判据 5 若读的是一段恒真的空集，删条也全绿 | 红（前半句"完整表下判据 5 是绿的"就先红） |

## 零模型 / 零真机

只调 `materialize` 往 `tmp_path` 写；不碰 `projects/` 下的真机工作区，不调模型、不起子进程。
"""
from __future__ import annotations

import pathlib
import re

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

#: 判据 5 的口径：一行里出现独立的 `L`，且同一行在讲它干的活（形式化 / 检查器 / 派 / 那一岗）。
#: 为什么边界是"ASCII 词字符"而不是 `\\b`：Python 的 `re` 把中日韩字算作 `\\w`，于是
#: `角色 L` 里那个 L 与左边的汉字之间没有词边界；而 `Lean` / `Mathlib` 里的 L 后面还跟着字母，
#: 按这条边界不算（这两件事在 `tests/test_l_is_isolated_when_lean_is_off.py` 里已经踩过一次）。
L_SUBJECT_RE = re.compile(r"(?<![A-Za-z0-9_])L(?![A-Za-z0-9_])")
L_SUBJECT_MARKS: tuple[str, ...] = ("形式化", "检查器", "派", "那一岗")

#: 允许清单：关档手册里唯一允许出现"L 作为能干活的角色"的行，逐字登记并写清为什么。
#: 为什么这一行不能改：它是业主原话的逐字引用（2026-10-24 的 D-40 口径）。改引文比留一个
#: 角色名更坏 —— 引文一改，读的人就分不清"这是业主说的"还是"我们转述的"。
#: 判据 5 会断言这一行仍然逐字在盘上（允许清单不许腐烂成一条永不生效的豁免）。
ALLOWED_L_LINES: tuple[tuple[str, str], ...] = (
    ("业主原话：「G 的写作只参照 B 侧收录的证明，如果参照 L 侧的形式化会切割太细。」",
     "业主原话逐字引用（D-40，2026-10-24）：改引文比留一个角色名更坏"),
)


def _l_as_subject(books: dict[str, str]) -> dict[str, list[str]]:
    """手册里"把 L 当成能干活的角色"的行 ⇒ `{相对路径: [行, …]}`（允许清单里的不算）。"""
    allowed = {line.strip() for line, _why in ALLOWED_L_LINES}
    found: dict[str, list[str]] = {}
    for rel, text in books.items():
        for line in text.splitlines():
            if not L_SUBJECT_RE.search(line):
                continue
            if not any(mark in line for mark in L_SUBJECT_MARKS):
                continue
            if line.strip() in allowed:
                continue
            found.setdefault(rel, []).append(line.strip())
    return found


def _stray_l(books: dict[str, str]) -> dict[str, list[str]]:
    """更严的一刀：允许清单之外，一处独立的 `L` 都不许有 ⇒ `{相对路径: [行, …]}`。

    为什么除了那条"带标记词"的口径还要这一条：第二批那 5 行里有一行（shared 的
    「`formal`（L 签）」）一个标记词都不含 —— 只按标记词扫，它会从判据的指缝里漏过去。
    今天关档手册里只剩业主原话那一行，所以这一刀不留口子；将来谁要再加豁免，登记进
    允许清单并写清理由，而不是放宽这里。
    """
    allowed = {line.strip() for line, _why in ALLOWED_L_LINES}
    found: dict[str, list[str]] = {}
    for rel, text in books.items():
        for line in text.splitlines():
            if L_SUBJECT_RE.search(line) and line.strip() not in allowed:
                found.setdefault(rel, []).append(line.strip())
    return found


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


# ============================================================ 判据 5（第二批口径）
def test_lean_off_books_never_make_l_the_subject(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """关档：手册里不许再有"L 能干这件活"的行；允许清单只有业主原话那一行。"""
    books = _materialize(tmp_path / "off", monkeypatch, on=False)
    assert _l_as_subject(books) == {}, f"关档下这些手册仍把 L 当成能干活的角色：{_l_as_subject(books)}"
    # 同一件事的更严一刀：标记词扫不到的那一行（`formal`（L 签））在这里一样红
    assert _stray_l(books) == {}, f"关档手册里还有独立的 L（允许清单之外）：{_stray_l(books)}"

    # 反真空 1：这条口径在开档手册上必须真的会命中（否则它可能在读一段没人会踩的文本）
    on_books = _materialize(tmp_path / "on", monkeypatch, on=True)
    assert _l_as_subject(on_books), "开档下一行都命不中 ⇒ 这条判据挡不住任何东西"

    # 反真空 2：允许清单不许腐烂 —— 登记的那一行必须还在盘上逐字存在
    for line, why in ALLOWED_L_LINES:
        assert any(line in text for text in books.values()), \
            f"允许清单里那一行已经不在盘上了（这条豁免从此永不生效）：{why}"

    # 反真空 3：表里每一条原串都不许还留在关档手册里 —— 替换真的生效，而不是"没被正则看见"
    leftovers = [old for old, _new in TABLE if any(old in text for text in books.values())]
    assert not leftovers, f"这些原串还留在关档手册里（替换没生效）：{[o[:24] for o in leftovers]}"


# ============================================================ 判据 6（反真空）
def test_dropping_one_replacement_turns_the_subject_judge_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """删掉一条替换 ⇒ 判据 5 必红（证明它读的就是这张表，而不是一段恒真的空集）。"""
    table = getattr(AS, "NO_LEAN_SKILL_REPLACEMENTS", ())
    assert table, "改写表是空的"
    clean = _materialize(tmp_path / "full", monkeypatch, on=False)
    assert _l_as_subject(clean) == {}, "完整表下判据 5 本来就不是绿的，这条反真空说明不了任何事"
    assert _stray_l(clean) == {}, "完整表下判据 5 的更严那一刀本来就不是绿的"

    victims = [pair for pair in table if "`L` 的形式化" in pair[0]]
    assert victims, "表里找不到 F 工具清单那一条（换了写法的话，这条判据要跟着改）"
    monkeypatch.setattr(AS, "NO_LEAN_SKILL_REPLACEMENTS",
                        tuple(pair for pair in table if pair != victims[0]))
    dropped = _materialize(tmp_path / "drop", monkeypatch, on=False)
    assert _l_as_subject(dropped) != {}, "删掉一条改写之后判据 5 仍然全绿 ⇒ 它读的不是这张表"
    assert _stray_l(dropped) != {}, "删掉一条改写之后更严那一刀仍然全绿 ⇒ 它读的不是这张表"

