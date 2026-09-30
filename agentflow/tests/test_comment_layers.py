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
DEV = REPO / "DEVELOPMENT.md"

#: 判据点名的样板文件（`DEVELOPMENT.md` §0.3d 里逐字列了同样四个）。
SAMPLES: tuple[str, ...] = (
    "src/agentflow/agent_d.py",
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


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


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
    """每个样板文件里三层都要出现过 —— 样板的意义就是"三种都示范一次"。"""
    text = _text(rel)
    found = {tag for tag in LAYERS if re.search(r"\[" + tag + r"\]", text)}
    missing = sorted(set(LAYERS) - found)
    assert not missing, (
        f"{rel} 缺这几层标签：{missing}。样板文件要三层各示范一次"
        f"（`DEVELOPMENT.md` §0.3d 是约定；若这一层在这个文件里确实不存在，"
        "请换一个样板文件，而不是放宽判据）")


@pytest.mark.parametrize("rel", SAMPLES)
def test_every_incident_tag_can_be_traced_to_a_reading(rel: str) -> None:
    """`[踩过]` 必须追得到出处：同行或随后三行里有日期，或 `§NNN` / `draft/N` 这样的编号。"""
    lines = _text(rel).splitlines()
    bad: list[str] = []
    for i, line in enumerate(lines):
        if "[踩过]" not in line:
            continue
        window = "\n".join(lines[i:i + 4])
        if not _TRACE_RE.search(window):
            bad.append(f":{i + 1} {line.strip()[:80]}")
    assert not bad, (
        "这些 `[踩过]` 没有出处（读者无法判断它是当次读数还是旧事）："
        + "；".join(bad)
        + "。请在同行或随后三行里写上观测日期（2026-09-29）或 `draft/28` §NNN"
    )


@pytest.mark.parametrize("rel", SAMPLES)
def test_tags_live_only_in_comments_and_docstrings(rel: str) -> None:
    """标签只出现在注释/文档串里：数量必须对得上（多出来的就是落在代码上了）。"""
    text = _text(rel)
    total = len(_TAG_RE.findall(text))
    assert total > 0, f"{rel} 一个标签都没有"

    in_comment = 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                in_comment += len(_TAG_RE.findall(tok.string))
    except (tokenize.TokenError, IndentationError) as exc:  # pragma: no cover
        pytest.fail(f"{rel} 语法坏了，tokenize 跑不动：{exc}")

    lines = text.splitlines()
    in_docstring = 0
    for a, b in _docstring_spans(text):
        in_docstring += len(_TAG_RE.findall("\n".join(lines[a - 1:b])))

    assert in_comment + in_docstring == total, (
        f"{rel} 有 {total - in_comment - in_docstring} 处标签不在注释或文档串里 —— "
        "标签是给人读的标记，落到代码上要么是语法错、要么是字符串污染")


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
# 两条负控都用 `monkeypatch` 把 `_text` 换成一段合成的源码：判据的输入面被换掉，
# 但被检验的是同一条实现。没有这两条，上面那些断言可能只是"永远为真"。


def test_negative_control_an_incident_tag_without_a_source_is_caught(monkeypatch) -> None:
    """负控 ①：`[踩过]` 不写日期也不写编号 ⇒ 出处那条判据必须红。"""
    import sys

    fake = "# [踩过] 去年这里踩过一次坑，具体哪天忘了\nX = 1\n"
    monkeypatch.setattr(sys.modules[__name__], "_text", lambda _rel: fake)
    with pytest.raises(AssertionError):
        test_every_incident_tag_can_be_traced_to_a_reading("合成文件.py")


def test_negative_control_a_misspelled_tag_is_caught(monkeypatch) -> None:
    """负控 ②：`[为什幺]` 这种手滑标签必须被闭词表抓住（它不会让任何东西报错）。"""
    import sys

    fake = "# [为什幺] 这一层写错了字，而它照样能被 grep 到\nX = 1\n"
    monkeypatch.setattr(sys.modules[__name__], "_text", lambda _rel: fake)
    with pytest.raises(AssertionError):
        test_the_layer_vocabulary_is_closed("合成文件.py")


def test_negative_control_a_tag_on_a_code_line_is_caught(monkeypatch) -> None:
    """负控 ③：标签落在代码行上（比如塞进字符串）必须被 tokenize 那条抓住。"""
    import sys

    fake = '"""docstring 里有一个 [契约]。"""\nX = "[契约] 这是字符串里的标签"\n'
    monkeypatch.setattr(sys.modules[__name__], "_text", lambda _rel: fake)
    with pytest.raises(AssertionError):
        test_tags_live_only_in_comments_and_docstrings("合成文件.py")
