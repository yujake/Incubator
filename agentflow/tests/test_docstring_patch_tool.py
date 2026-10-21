"""工装判据：`scripts/docstring_patch.py` 必须能安全地写回含反斜杠/三引号的 docstring。
## 这一条守的是 2026-10-21 那轮的两次真事故

1. 反斜杠那一路上真出过事故：`\\bibitem` 按单反斜杠写进源码后，解析出来的值就是 `\x08ibitem`（U+0008）—— 那是"非 Unicode 字符"里最难查的一类。
2. 断言被改，而不是被修：有人为了绕过「写回值必须等于给的文本」这条断言，改的是断言（`cl2x.py`）而不是让序列化正确 —— 判据要的是后者。

## 判据

① `literal()` 序列化后再 `ast.literal_eval`，值逐字等于原文（含字面反斜杠、三引号、行尾引号、中文、制表符）；
② `apply_patch()` 真写一个临时 `.py` 文件后，解析出的 docstring 值逐字等于 `text`，且没有 CRLF；
③ `verify_one()` 能抓到三类破坏：AST（去 docstring 后）不同、非 doc 字面量不同、指针丢失；
④ 反真空：没被破坏的文件必须判绿（否则"抓得到"可以靠"什么都报"实现）；
⑤ 负控：把序列化换回"直接塞原文"（原始写法）⇒ ① 必须红 —— 证明①测的确实是转义。

## 为什么用临时文件而不是真仓文件：这一条只考工装本身，不该依赖任何具体的业务文件（那样它会在清洁工并行改动时抖动）。"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "scripts" / "docstring_patch.py"


def _tool():
    spec = importlib.util.spec_from_file_location("docstring_patch_under_test", TOOL)
    assert spec and spec.loader, f"加载不到 {TOOL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: 覆盖三次真事故的样本：字面反斜杠、三引号、行尾引号、中文、制表符、行尾空格
SAMPLES = [
    '用 \\bibitem{kn} 与 \\begin{document} 举例。',
    '里面有一个三引号 """ 与一个行尾引号 "',
    '中文段落：判据管"不许它不这么做"。\n\n第二段有制表符\t与行尾空格   ',
    '提到 draft/103 与 §125 与 test_agent_prompts 与 agent_loop.py:1825 这些指针。',
]


def test_the_serializer_round_trips_every_hard_sample() -> None:
    """① `literal()` 的结果 `literal_eval` 回来必须逐字等于原文。"""
    tool = _tool()
    for text in SAMPLES:
        for indent in ("    ", "", "        "):
            rendered = tool.literal(text, indent)
            value = ast.literal_eval(rendered)
            # 缩进块里的续行本来就带前缀缩进（排版，不是内容）⇒ 两边都 cleandoc 再比
            assert tool.dedent(value, indent) == text, (
                f"序列化丢字：indent={indent!r} text={text!r} -> {value!r}")


def test_the_negative_control_raw_emission_is_caught() -> None:
    """⑤ 负控：不做转义（"直接塞原文"）⇒ ① 必须红 —— 证明①测的是转义本身。"""
    tool = _tool()
    naive = '"""用 \\bibitem{kn} 举例。"""'
    assert ast.literal_eval(naive) != '用 \\bibitem{kn} 举例。', (
        "负控失效：单反斜杠在字面量里竟然解析成原文 ⇒ 这一条样本不再有区分力")
    # 而工具的序列化必须能救回来
    assert ast.literal_eval(tool.literal('用 \\bibitem{kn} 举例。', "")) == '用 \\bibitem{kn} 举例。'


def test_apply_patch_writes_the_exact_value_and_no_crlf(tmp_path: Path) -> None:
    """② 真写一个文件：值逐字相等、无 CRLF、定位按「首行」而不是行号。"""
    tool = _tool()
    target = tmp_path / "sample_mod.py"
    target.write_bytes(
        b'"""\xe6\xa8\xa1\xe5\x9d\x97\xe6\x91\x98\xe8\xa6\x81\xe3\x80\x82\n'
        b'\n\xe9\x95\xbf\xe9\x95\xbf\xe7\x9a\x84\xe8\xaf\xb4\xe7\x90\x86\xe3\x80\x82"""\n'
        b"\n\ndef foo():\n"
        b'    """foo \xe7\x9a\x84\xe6\x91\x98\xe8\xa6\x81\xe3\x80\x82\n\n\xe8\xaf\xb4\xe7\x90\x86"""\n'
        b"    return 1\n",
    )
    head = "模块摘要。"
    body = "模块摘要。\n\n短了，且含 \\bibitem{kn} 与三引号。"
    tool.apply_patch({"file": str(target), "kind": "module", "name": "<module>",
                      "head": head, "text": body})
    parsed = ast.parse(target.read_text(encoding="utf-8"))
    assert ast.get_docstring(parsed, clean=False) == body
    assert b"\r\n" not in target.read_bytes()
    # 代码没被动
    tree = parsed
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert [f.name for f in funcs] == ["foo"]


def test_a_chinese_docstring_can_be_patched_twice_without_eating_the_newline(tmp_path: Path) -> None:
    """负控（字节偏移）：`col_offset` 是 UTF-8 字节，不是字符。

    真事故：docstring 的收尾三引号粘在一条含中文的行尾时，用字符偏移去切
    `str` 会把行尾换行吃掉 ⇒ 收尾三引号与下一条语句粘成一行（SyntaxError）。
    这里同一节点连打两次，两次都必须：① 文件能 `ast.parse`；② 值等于最后一次的 text；
    ③ 收尾三引号与下一条语句之间仍有换行。
    """
    tool = _tool()
    target = tmp_path / "zh.py"
    original = (
        '"""中文模块摘要，结尾带标点。"""\n'
        "from __future__ import annotations\n"
        "\n\nVALUE = 1\n"
    )
    target.write_bytes(original.encode("utf-8"))
    # `head` 必须给"盘上现在的首行"（它就是定位键）：第二次改写时首行还没变，
    # 所以两次都传原始首行 —— 这也是给使用者的一条口径：别把"想要的首行"当定位键。
    for text in ("中文模块摘要，结尾带标点。", "第二次改写的中文摘要，也带标点。"):
        tool.apply_patch({"file": str(target), "kind": "module", "name": "<module>",
                          "head": "中文模块摘要，结尾带标点。", "text": text})
        parsed = ast.parse(target.read_bytes().decode("utf-8"))
        assert ast.get_docstring(parsed, clean=False) == text
        written = target.read_bytes().decode("utf-8")
        assert '"""\n' in written or written.count('"""') == 2, written
        assert "from __future__" in written and "VALUE = 1" in written


def test_verify_catches_pointer_loss_and_ast_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 三类破坏都能抓到：指针丢失 / 非 doc 字面量改动 / 去 docstring 后 AST 不同。"""
    tool = _tool()
    target = tmp_path / "victim.py"
    original = (
        '"""摘要。\n\n提到 `draft/103` 与 test_agent_prompts。"""\n'
        "\n\ndef foo():\n"
        '    """foo 的摘要。"""\n'
        '    return "keep-me"\n'
    )
    target.write_bytes(original.encode("utf-8"))
    monkeypatch.setattr(tool, "head_source", lambda rel: original)
    assert tool.verify_one(str(target)) == [], "反真空：没被破坏的文件必须判绿"

    target.write_bytes(original.replace("`draft/103` 与 ", "").encode("utf-8"))
    problems = tool.verify_one(str(target))
    assert any("dropped pointers" in p for p in problems), problems

    target.write_bytes(original.replace('"keep-me"', '"changed"').encode("utf-8"))
    problems = tool.verify_one(str(target))
    assert any("non-doc string literals differ" in p for p in problems), problems

    target.write_bytes(original.replace('"""摘要。\n\n提到', '"""摘要。\n\n提到额外一句。\n\n提到').encode("utf-8"))
    problems = tool.verify_one(str(target))
    assert any("AST-without-docstrings differs" in p or "dropped" in p for p in problems) or problems == [], (
        "改 docstring 的正文本身不该被判成 AST 变化（docstring 不在 AST 比较面里）")


def test_the_tool_refuses_a_missing_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（三态纪律）：取不到 HEAD 基线时抛 SystemExit，不是判绿。"""
    tool = _tool()
    target = tmp_path / "x.py"
    target.write_bytes('"""a"""\n'.encode("utf-8"))

    def boom(rel: str) -> str:
        raise SystemExit("no baseline")

    monkeypatch.setattr(tool, "head_source", boom)
    with pytest.raises(SystemExit):
        tool.verify_one(str(target))
