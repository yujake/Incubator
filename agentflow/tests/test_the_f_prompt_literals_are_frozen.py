# -*- coding: utf-8 -*-
"""F 的动作提示词字面量冻结判据。

## 它钉的是什么

`src/agentflow/agent_f/core.py` 里有大量直接面向模型的提示词与读数正文。
2026-11-20 的事故（`2ab3bbdb`）把其中 65 处的双星号强调一起清掉，而当时
101 条定向判据与 lint 全部是绿的 —— 因为那些强调藏在代码字符串字面量里，
R009 的射程（注释与 docstring）本来就够不着。

本判据把该文件里全部字符串常量（AST 口径，按源码出现顺序，docstring 除外）
冻成 `tests/fixtures/f_prompt_literals.json`：序号 + 前 80 字 + sha256。
现盘抽取值与快照在数量、顺序、sha256 三项上逐条相等才算绿。

## 为什么钉"全部"而不是只钉提示词

"哪些常量算提示词"是一个会过期的语义判断：同一个文件里动作提示词、拒信、
读数正文、字典键混在一起。只钉一个子集，下一次"只改注释"的脚本仍然可以从
子集外面走过去 —— 那正是这次事故的形态。所以这里不做语义筛选。

## 三态纪律

文件缺失 / 读不出 / 解析失败 / 抽到 0 条 / 快照缺失 / 快照读不出或结构不对，
一律判红并写明"没查成"，绝不折成通过。抽到 0 条尤其要红：一个坏掉的抽取器
与一个真的没有字面量的文件，在"比较结果为空"这一点上长得一模一样。

## 什么时候该重冻

只有真的改了提示词文案（或该文件里任何字符串常量），并且
`src/agentflow/agent_prompts.py` 的 `PROMPT_VERSION` 已同步抬号之后，才允许重冻。
重冻只有一条路径，不许手改 JSON：

    python -B tests/test_the_f_prompt_literals_are_frozen.py --write

写完先看 `git diff tests/fixtures/f_prompt_literals.json`：差在哪一条、为什么。
序号、前缀、哈希三者由同一个抽取函数同一趟生成；手改会让"快照说的"与
"现盘抽到的"分家。反过来，若只是重构（搬函数、改字典键、调整注释），
不重冻 —— 那正是要让它红的时刻。

## 重冻后的判据读数

    python -B -m pytest tests/test_the_f_prompt_literals_are_frozen.py -q
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import pathlib
import sys

import pytest

#: 被判的文件（仓库内相对路径只用于报告；判据按绝对路径读）。
CORE = (pathlib.Path(__file__).resolve().parents[1]
        / "src" / "agentflow" / "agent_f" / "core.py")

#: 冻结快照。只许由本文件末尾的 `--write` 生成。
SNAPSHOT = pathlib.Path(__file__).resolve().parent / "fixtures" / "f_prompt_literals.json"

#: 快照里每条保留的字符数（前 N 字），只为让人看懂"差的是哪一句"。
PREFIX_CHARS = 80

#: 哪些 AST 节点可以拥有 docstring（Python 语义里只有这四种作用域）。
_DOC_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


class NotChecked(RuntimeError):
    """没查成：读不到 / 解析不了 / 抽到空集 / 快照坏了。

    单独一个异常类型，是为了让"没查成"在判据里无法被当成"一致"：主判据不捕获它，
    pytest 会把消息原样打出来并记红；三态用例也用 `pytest.raises` 钉住它是异常，
    而不是一个可以继续往下的布尔值。
    """


def _read_source(path: pathlib.Path) -> str:
    """读被判文件；任何读失败都是"没查成"。"""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotChecked(
            f"没查成：读不到 {path}（{type(exc).__name__}: {exc}）"
            " —— 文件不在，不等于'没有可比的字面量'"
        ) from exc


def _docstring_ids(tree: ast.AST) -> set[int]:
    """返回四种作用域里首条 docstring 的 `id()` 集合。

    只认真正处在首条的字符串表达式；函数体中间那种裸字符串表达式不是 docstring，
    它属于"字面量"，照样进快照。
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            ids.add(id(first.value))
    return ids


def _position(node: ast.Constant) -> tuple[int, int, int, int]:
    """源码位置，用于把 AST 节点排回"出现顺序"。

    `ast.walk` 是广度优先，不是源码顺序；f-string 的多个字面片段在 Python 3.11
    里共享同一个节点位置，`list.sort` 的稳定性让它们仍按 `values` 里的先后排列。
    """
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


def extract_literals(source: str) -> list[tuple[int, str]]:
    """从源码抽出全部字符串常量，按出现顺序返回 `(行号, 值)`，docstring 除外。

    解析失败与"抽到 0 条"都抛 `NotChecked`：后者是反真空 —— 抽取器坏掉与文件里
    真的没有字面量，不能长得一样。
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        raise NotChecked(
            f"没查成：agent_f/core.py 解析不了（{type(exc).__name__}: {exc}）"
        ) from exc

    skip = _docstring_ids(tree)
    nodes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
    ]
    nodes.sort(key=_position)
    values = [(node.lineno, node.value) for node in nodes]
    if not values:
        raise NotChecked(
            "没查成：从 agent_f/core.py 抽到 0 条字符串常量"
            " —— 抽取器没接上（或文件被清空），不是'一致'"
        )
    return values


def build_snapshot(values: list[tuple[int, str]]) -> dict:
    """由抽取值生成快照。序号从 1 起；前缀与哈希由同一趟计算。"""
    entries = [
        {
            "index": index + 1,
            "prefix": value[:PREFIX_CHARS],
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
        for index, (_lineno, value) in enumerate(values)
    ]
    return {
        "about": ("agent_f/core.py 的全部字符串常量（AST，按源码出现顺序，"
                  "docstring 除外）：序号 + 前 80 字 + sha256"),
        "source": "src/agentflow/agent_f/core.py",
        "prefix_chars": PREFIX_CHARS,
        "count": len(entries),
        "total_bytes": sum(len(value.encode("utf-8")) for _lineno, value in values),
        "entries": entries,
    }


def _load_snapshot(path: pathlib.Path) -> tuple[dict, list[dict]]:
    """读并校验快照；任何结构问题都是"没查成"，不是"一致"。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotChecked(
            f"没查成：读不到冻结快照 {path}（{type(exc).__name__}: {exc}）\n"
            "生成：python -B tests/test_the_f_prompt_literals_are_frozen.py --write"
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NotChecked(f"没查成：冻结快照不是合法 JSON（{path}: {exc}）") from exc
    if not isinstance(data, dict):
        raise NotChecked(f"没查成：冻结快照顶层不是对象（{path}）")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise NotChecked(
            f"没查成：冻结快照里没有 entries（{path}）"
            " —— 没有可比对象不等于'一致'"
        )
    if data.get("count") != len(entries):
        raise NotChecked(
            f"没查成：冻结快照 count={data.get('count')!r} 与 entries 条数 "
            f"{len(entries)} 不符（{path}）"
        )
    if data.get("prefix_chars") != PREFIX_CHARS:
        raise NotChecked(
            f"没查成：冻结快照 prefix_chars={data.get('prefix_chars')!r} 与判据的 "
            f"{PREFIX_CHARS} 不符（{path}）—— 不许手改 JSON，用 --write 重冻"
        )
    for index, entry in enumerate(entries):
        if (not isinstance(entry, dict)
                or entry.get("index") != index + 1
                or not isinstance(entry.get("prefix"), str)
                or len(entry["prefix"]) > PREFIX_CHARS
                or not isinstance(entry.get("sha256"), str)
                or len(entry["sha256"]) != 64):
            raise NotChecked(
                f"没查成：冻结快照第 {index + 1} 条结构不对（{path}）"
                " —— 不许手改 JSON，用 --write 重冻"
            )
    return data, entries


def _differences(values: list[tuple[int, str]], entries: list[dict],
                 limit: int = 10) -> list[str]:
    """逐条比较数量、顺序（数组下标）、sha256；前缀用于让人看懂差在哪。"""
    bad: list[str] = []
    if len(values) != len(entries):
        bad.append(f"数量不符：现盘 {len(values)} 条 / 快照 {len(entries)} 条")
    for index in range(min(len(values), len(entries))):
        lineno, value = values[index]
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        prefix = value[:PREFIX_CHARS]
        entry = entries[index]
        if digest != entry["sha256"]:
            bad.append(
                f"第 {index + 1} 条（core.py:{lineno}）sha256 不符："
                f"快照 {entry['sha256'][:16]}… / 现盘 {digest[:16]}…；"
                f"快照前缀 {entry['prefix']!r} / 现盘前缀 {prefix!r}"
            )
        elif prefix != entry["prefix"]:
            bad.append(
                f"第 {index + 1} 条（core.py:{lineno}）前缀被改动（sha256 相同）："
                f"快照 {entry['prefix']!r} / 现盘 {prefix!r}"
            )
        if len(bad) >= limit:
            bad.append(f"……另有更多不符未列出（上限 {limit} 条）")
            break
    return bad


def test_the_f_prompt_literals_match_the_frozen_snapshot() -> None:
    """核心判据：现盘抽取值与冻结快照在数量、顺序、sha256 上逐条相等。"""
    values = extract_literals(_read_source(CORE))
    data, entries = _load_snapshot(SNAPSHOT)
    bad = _differences(values, entries)
    total_bytes = sum(len(value.encode("utf-8")) for _lineno, value in values)
    if data.get("total_bytes") != total_bytes:
        bad.append(f"快照 total_bytes={data.get('total_bytes')!r} 与现盘 {total_bytes} 不符")
    assert not bad, (
        "agent_f/core.py 的字符串常量与冻结快照不一致。\n"
        "若这一改是真的改了提示词文案：先抬 `PROMPT_VERSION`，再跑\n"
        "  python -B tests/test_the_f_prompt_literals_are_frozen.py --write\n"
        "然后逐条看 diff。若只是重构或顺手改字：不要重冻。\n"
        + "\n".join(bad)
    )


def test_the_comparison_actually_sees_a_change() -> None:
    """负控：上面那条判据真的在比内容，不是永远绿。

    分别改一条 sha256、少一条、改一条前缀，同一个比较函数都必须报出来。
    """
    values = extract_literals(_read_source(CORE))
    _data, entries = _load_snapshot(SNAPSHOT)
    assert not _differences(values, entries), "基线本身对不上 ⇒ 先按 --write 重冻"

    one = copy.deepcopy(entries)
    one[0]["sha256"] = "0" * 64
    assert _differences(values, one), "改了一条 sha256，比较函数没报"

    short = copy.deepcopy(entries[:-1])
    assert _differences(values, short), "少了一条，比较函数没报数量不符"

    prefix_only = copy.deepcopy(entries)
    prefix_only[0]["prefix"] = "被手改过的前缀"
    assert _differences(values, prefix_only), "改了一条前缀，比较函数没报"


def test_a_missing_source_is_not_checked_not_a_pass(tmp_path) -> None:
    """三态：源文件缺失 ⇒ NotChecked（没查成），不是空比对的通过。"""
    with pytest.raises(NotChecked, match="没查成"):
        _read_source(tmp_path / "core_absent.py")


def test_a_source_that_cannot_be_parsed_is_not_checked(tmp_path) -> None:
    """三态：源码解析不了 ⇒ NotChecked。"""
    broken = tmp_path / "core_broken.py"
    broken.write_text("def f(:\n", encoding="utf-8")
    with pytest.raises(NotChecked, match="没查成"):
        extract_literals(_read_source(broken))


def test_a_source_with_zero_literals_is_not_checked(tmp_path) -> None:
    """三态：抽到 0 条 ⇒ NotChecked（一个坏掉的抽取器不许看起来像'干净'）。"""
    empty = tmp_path / "core_only_docstring.py"
    empty.write_text('"""只有 docstring，没有别的字符串常量。"""\n', encoding="utf-8")
    with pytest.raises(NotChecked, match="没查成"):
        extract_literals(_read_source(empty))


def test_a_missing_or_broken_snapshot_is_not_checked(tmp_path) -> None:
    """三态：快照缺失 / 不是 JSON / 没有 entries ⇒ 都是 NotChecked。"""
    with pytest.raises(NotChecked, match="没查成"):
        _load_snapshot(tmp_path / "absent.json")

    not_json = tmp_path / "not_json.json"
    not_json.write_text("{ 这不是 JSON", encoding="utf-8")
    with pytest.raises(NotChecked, match="没查成"):
        _load_snapshot(not_json)

    no_entries = tmp_path / "no_entries.json"
    no_entries.write_text('{"count": 0, "entries": []}', encoding="utf-8")
    with pytest.raises(NotChecked, match="没查成"):
        _load_snapshot(no_entries)

    hand_edited = tmp_path / "hand_edited.json"
    hand_edited.write_text(
        '{"count": 1, "entries": [{"index": 9, "prefix": "x", "sha256": "' + "a" * 64 + '"}]}',
        encoding="utf-8",
    )
    with pytest.raises(NotChecked, match="没查成"):
        _load_snapshot(hand_edited)


def test_docstrings_are_excluded_and_body_strings_are_kept() -> None:
    """口径钉住：首条 docstring 不进快照，函数体中间的裸字符串进。"""
    source = (
        '"""模块 docstring。"""\n'
        "\n"
        "def f():\n"
        '    """函数 docstring。"""\n'
        '    "函数体里的裸字符串。",\n'
        '    return "返回值"\n'
    )
    got = [value for _lineno, value in extract_literals(source)]
    assert got == ["函数体里的裸字符串。", "返回值"], got


if __name__ == "__main__":  # pragma: no cover - 只在真的改了文案时手动跑
    if "--write" not in sys.argv:
        print(__doc__)
        raise SystemExit(2)
    _values = extract_literals(_read_source(CORE))
    _snap = build_snapshot(_values)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(_snap, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _again, _entries = _load_snapshot(SNAPSHOT)
    _bad = _differences(_values, _entries)
    if _bad:
        print("[unknown] 写入后自检不一致：\n" + "\n".join(_bad), file=sys.stderr)
        raise SystemExit(2)
    print(f"[ok] 写入快照：{SNAPSHOT}（{_snap['count']} 条，{_snap['total_bytes']} 字节）")
