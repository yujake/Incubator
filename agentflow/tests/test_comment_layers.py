# -*- coding: utf-8 -*-
"""注释三层的判据（`draft/36` 的 T-2）。

`DEVELOPMENT.md` §0.3d 定了三种注释标签：`[契约]` / `[为什么]` / `[踩过]`。
这条判据钉四件事（都在同一个方向上：让标签是可信的，而不是"写了就算"）：

1. 那份约定本身还在，且三个标签逐字齐全（反真空：约定被删了、判据就该红）；
2. 判据点名的样板文件里，三层都出现过 —— 只写 `[为什么]` 的样板等于没示范分层；
3. 每个 `[踩过]` 都要追得到出处：同一行或随后三行里要有观测日期（`2026-09-29`）
   或 `draft/28` §NNN 这样的编号。事故层不写日期，读者就无法判断"这是当次读数还是三年前的事"
   —— 而那正是本仓库反复踩的"数字看起来客观，于是没人问它的口径"；
4. 标签只出现在注释与文档串里：用 `tokenize` 证明没有任何一个标签落在代码行上
   （标签落到代码里就是语法错误或字符串污染，两种都不该发生）。

另有一条"闭词表"检查：形状像标签的东西（`[xxx]`）如果出现在注释行或 docstring 标题的开头，
必须是那三个之一 —— 防的是 `[为什幺]` 这种手滑后静默失效的标签。
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
#: 2026-10 文档拆分：`§0.3d（注释三层）` 的正文搬进了 `docs/DEVELOPMENT-SPEC.md` 的
#: `§1.3`（旧编号在那个小节的迁移注里逐字保留）。判据对象、字面与强度都没变 ——
#: 变的只是"这一节住在哪个文件"，指向入口（现在只剩 42 行指针）等于指向一个空壳。
DEV = REPO / "docs" / "DEVELOPMENT-SPEC.md"

#: 判据点名的样板（`DEVELOPMENT.md` §0.3d 里逐字列了同样四个）。
#: `agent_d` 那一格是包（`goal-7f5116c1` M6 把一个 4188 行的大文件拆成一个动作一个文件），
#: 于是"样板文件"的粒度跟着从一个文件变成一个包 —— 判据按包取每个 `.py` 的文本之和
#: 检查三层标签、但逐文件做"标签只在注释/文档串里"这条（多文件拼起来不是一个合法模块）。
SAMPLES: tuple[str, ...] = (
    "src/agentflow/agent_d/",
    "src/agentflow/tools/attack_tools.py",
    "src/agentflow/claimanatomy.py",
    "src/agentflow/evidence.py",
)

LAYERS: tuple[str, ...] = ("契约", "为什么", "踩过")
_TAG_RE = re.compile(r"\[(" + "|".join(LAYERS) + r")\]")
#: 形状像标签的东西（用来抓拼错的标签）。
_TAG_SHAPE_RE = re.compile(r"\[[^\]\n]{1,8}\]")
#: 事故层的出处：观测日期，或 `draft/28` §NNN 这一类编号。
_TRACE_RE = re.compile(r"(20\d\d-\d\d(-\d\d)?)|(§\s*\d+)|(draft/\d+)")


def _sources(rel: str) -> list[tuple[str, str]]:
    """样板的一格格子 → `[(相对路径, 文本)]`。给目录就是包里的每个 `.py`（按名排序）。"""
    p = REPO / rel
    if p.is_dir():
        return [(f"{rel}{f.name}", f.read_text(encoding="utf-8"))
                for f in sorted(p.glob("*.py"))]
    return [(rel, p.read_text(encoding="utf-8"))]


def _text(rel: str) -> str:
    """整格文本（目录 = 各文件拼起来，只用于"三层标签出现过没有"这类跨文件判断）。"""
    return "\n".join(text for _name, text in _sources(rel))


def _docstring_spans(text: str) -> list[tuple[int, int]]:
    tree = ast.parse(text)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            d = body[0]
            spans.append((d.lineno, getattr(d, "end_lineno", d.lineno)))
    return spans


def _tag_lines(text: str) -> list[tuple[int, str]]:
    """带标签的行：`[(行号, 行内容)]`（同一行多个标签只记一次）。"""
    return [(i, ln) for i, ln in enumerate(text.splitlines(), 1) if _TAG_RE.search(ln)]


def test_the_convention_section_still_documents_the_three_layers() -> None:
    """反真空：`DEVELOPMENT.md` §0.3d 必须还在，且三个标签逐字齐全。"""
    text = DEV.read_text(encoding="utf-8")
    assert "0.3d" in text, "§0.3d（注释三层）不见了 —— 判据的前提没了"
    for tag in LAYERS:
        assert f"[{tag}]" in text, f"§0.3d 里少了 `[{tag}]` 这一层的定义"
    assert "tokenize" in text, "§0.3d 应当写明『标签只在注释/文档串里』这条纪律及其判据手段"


@pytest.mark.parametrize("rel", SAMPLES)
def test_every_sample_file_shows_all_three_layers(rel: str) -> None:
    """每个样板（文件或包）里三层都要出现过 —— 样板的意义就是"三种都示范一次"。"""
    text = _text(rel)
    found = {tag for tag in LAYERS if re.search(r"\[" + tag + r"\]", text)}
    missing = sorted(set(LAYERS) - found)
    assert not missing, (
        f"{rel} 缺这几层标签：{missing}。样板要三层各示范一次"
        f"（`DEVELOPMENT.md` §0.3d 是约定；若这一层在这个格子（文件/包）里确实不存在，"
        "请换一个样板，而不是放宽判据）")


@pytest.mark.parametrize("rel", SAMPLES)
def test_every_incident_tag_can_be_traced_to_a_reading(rel: str) -> None:
    """`[踩过]` 必须追得到出处：同行或随后三行里有日期，或 `§NNN` / `draft/N` 这样的编号。

    逐文件查（一个包里各文件的行号互不相干，拼起来查会把"下一个文件的头三行"
    当成上一个文件 `[踩过]` 的出处 —— 那会把判据放松成"包里有日期就行"）。
    """
    bad: list[str] = []
    for name, text in _sources(rel):
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "[踩过]" not in line:
                continue
            window = "\n".join(lines[i:i + 4])
            if not _TRACE_RE.search(window):
                bad.append(f"{name}:{i + 1} {line.strip()[:80]}")
    assert not bad, (
        "这些 `[踩过]` 没有出处（读者无法判断它是当次读数还是旧事）："
        + "；".join(bad)
        + "。请在同行或随后三行里写上观测日期（2026-09-29）或 `draft/28` §NNN"
    )


@pytest.mark.parametrize("rel", SAMPLES)
def test_tags_live_only_in_comments_and_docstrings(rel: str) -> None:
    """标签只出现在注释/文档串里：数量必须对得上（多出来的就是落在代码上了）。"""
    sources = _sources(rel)
    total = sum(len(_TAG_RE.findall(text)) for _name, text in sources)
    assert total > 0, f"{rel} 一个标签都没有"

    bad: list[str] = []
    for name, text in sources:
        in_comment = 0
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    in_comment += len(_TAG_RE.findall(tok.string))
        except (tokenize.TokenError, IndentationError) as exc:  # pragma: no cover
            pytest.fail(f"{name} 语法坏了，tokenize 跑不动：{exc}")

        lines = text.splitlines()
        in_docstring = 0
        for a, b in _docstring_spans(text):
            in_docstring += len(_TAG_RE.findall("\n".join(lines[a - 1:b])))

        here = len(_TAG_RE.findall(text))
        if in_comment + in_docstring != here:
            bad.append(f"{name}（{here - in_comment - in_docstring} 处）")

    assert not bad, (
        "这些文件里有标签不在注释或文档串里 —— "
        "标签是给人读的标记，落到代码上要么是语法错、要么是字符串污染：" + "、".join(bad))


@pytest.mark.parametrize("rel", SAMPLES)
def test_the_layer_vocabulary_is_closed(rel: str) -> None:
    """闭词表：注释行或 docstring 标题开头的 `[xxx]` 必须是那三个之一。

    防的是手滑：`[为什幺]` / `[契约 ]` 这类标签不会让任何东西报错，
    只会让那一层静默失效（读者看不到它、判据也数不到它）。
    """
    text = _text(rel)
    bad: list[str] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        head = ""
        if stripped.startswith("#"):
            head = stripped.lstrip("#").strip()
        if head.startswith("["):
            m = _TAG_SHAPE_RE.match(head)
            if m and m.group(0)[1:-1] not in LAYERS:
                bad.append(f":{i} {m.group(0)}")
    assert not bad, (
        "这些像标签的东西不在闭词表里（`契约`/`为什么`/`踩过`）："
        + "；".join(bad) + "。拼错的标签会让那一层静默失效")


# --------------------------------------------------------------------------- 负控
#
# 三条负控都用 `monkeypatch` 把 `_sources`（判据的唯一输入面）换成一段合成的源码：
# 输入被换掉，但被检验的是同一条实现。没有这几条，上面那些断言可能只是"永远为真"。


def test_negative_control_an_incident_tag_without_a_source_is_caught(monkeypatch) -> None:
    """负控 ①：`[踩过]` 不写日期也不写编号 ⇒ 出处那条判据必须红。"""
    import sys

    fake = "# [踩过] 去年这里踩过一次坑，具体哪天忘了\nX = 1\n"
    monkeypatch.setattr(sys.modules[__name__], "_sources",
                        lambda _rel: [("合成文件.py", fake)])
    with pytest.raises(AssertionError):
        test_every_incident_tag_can_be_traced_to_a_reading("合成文件.py")


def test_negative_control_a_misspelled_tag_is_caught(monkeypatch) -> None:
    """负控 ②：`[为什幺]` 这种手滑标签必须被闭词表抓住（它不会让任何东西报错）。"""
    import sys

    fake = "# [为什幺] 这一层写错了字，而它照样能被 grep 到\nX = 1\n"
    monkeypatch.setattr(sys.modules[__name__], "_sources",
                        lambda _rel: [("合成文件.py", fake)])
    with pytest.raises(AssertionError):
        test_the_layer_vocabulary_is_closed("合成文件.py")


def test_negative_control_a_tag_on_a_code_line_is_caught(monkeypatch) -> None:
    """负控 ③：标签落在代码行上（比如塞进字符串）必须被 tokenize 那条抓住。"""
    import sys

    fake = '"""docstring 里有一个 [契约]。"""\nX = "[契约] 这是字符串里的标签"\n'
    monkeypatch.setattr(sys.modules[__name__], "_sources",
                        lambda _rel: [("合成文件.py", fake)])
    with pytest.raises(AssertionError):
        test_tags_live_only_in_comments_and_docstrings("合成文件.py")
