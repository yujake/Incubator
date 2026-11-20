# -*- coding: utf-8 -*-
"""② "读不全"是读得出来的事实：销号名单的四态读数只从这一次的返回值读。

## 这一条钉的是什么（2026-11-20 取证，复算见 `temp/sdfect/00-before.txt`）

`retired_ledger` 的返回值本来就带着 `checked` / `bad` / `unattributable` / `reason`
四态与逐行读数。改前它另外写过一格实例字段（`self.last_retired_ledger`），
docstring 逐字承诺「坏行 / 认不出来的行留在 `self.last_retired_ledger` 里，
读不全从此是读得出来的事实」。取证读数（AST 扫 `src/agentflow`）：

- 那一格：写 2 处（`__init__` 初值 + `retired_ledger` 末尾），读 0 处；
- 同一份事实在调用方那一层有活的孪生格 `Conductor.last_retired_reading`：
  写 2 处、读 4 处（`_retired_unchecked_note` / `_retired_reason` /
  `_retired_first_problem()`）。

所以处置是删字段，不是补一个读点：实例字段只保留"最后一次"，而调用方拿到的
永远是"这一次"的返回值；两者并存时"这是哪一次读的"没有答案，加一个读者只是把
这个歧义钉进盘上。承诺兑现的方式是把它改成"从返回值读"，并且由本判据钉住。

## 本文件钉三件事

1. 字段与承诺都不在：`last_retired_ledger` 在 `src/agentflow` 里 0 处（含注释与
   docstring）；`retired_ledger` / `_retired_used` / `_is_retired` 三处 docstring
   写的是"从这一次的返回值读"。
2. 事实本身没跟着消失：坏行 / 认不出来的行仍让 `checked=False`，读得出来的行照读；
   调用方那层的 `last_retired_reading` 仍有读者。
3. 反真空：把旧字段与旧承诺句喂回检查器 ⇒ 必报；把坏行打桩成"读得出来" ⇒ 第 2 条必红。
"""
from __future__ import annotations

import ast
import pathlib
import warnings

import pytest

from agentflow import jsonlfile as JF
from agentflow import secretary as SEC
import _secretary_home as HOME  # 打桩打在定义处（搬家后 SEC 那一格只是再导出）


REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "agentflow"

#: 被删掉的那一格（本判据要它 0 处）。
DEAD_FIELD = "last_retired_ledger"

#: 同一份事实在调用方那一层的活读口（它有读者，留作对照）。
READER_TWIN = "last_retired_reading"

#: 三处必须写明"从返回值读"的 docstring（承诺的新落点）。
PROMISE_DOCS: tuple[str, ...] = ("retired_ledger", "_retired_used", "_is_retired")


def _parse(text: str) -> ast.AST:
    """`ast.parse` 的薄壳：压掉历史源码里无效转义带来的告警。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text)


def _field_hits(text: str) -> list[tuple[int, str]]:
    """`text` 里提到那一格的地方：`[(行号, 那一行)]`。"""
    return [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1)
            if DEAD_FIELD in line]


def _docstrings() -> dict[str, str]:
    """`PROMISE_DOCS` 里那几个函数的 docstring（找不到 ⇒ 判据失去对象，红）。"""
    wanted = set(PROMISE_DOCS)
    out: dict[str, str] = {}
    for path in sorted(SRC.glob("secretary*.py")):
        tree = _parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
                out[node.name] = ast.get_docstring(node) or ""
    return out


# ---------------------------------------------------------------- 1 字段与承诺


def test_the_dead_field_and_its_promise_are_gone() -> None:
    """字段 0 处（含注释 / docstring）；三处 docstring 都改写成"从返回值读"。"""
    hits: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for line_no, line in _field_hits(path.read_text(encoding="utf-8", errors="replace")):
            hits.append(f"{path.relative_to(REPO).as_posix()}:{line_no}  {line}")
    assert not hits, (
        "`last_retired_ledger` 又被写回来了（它没有读者；承诺必须兑现，不许留空头文案）：\n"
        + "\n".join("  " + h for h in hits))

    docs = _docstrings()
    assert set(docs) == set(PROMISE_DOCS), (
        f"三处 docstring 应当都在：拿到 {sorted(docs)}")
    for name, doc in docs.items():
        assert "返回值" in doc, (
            f"{name} 的 docstring 不再说清'读不全'从哪读 —— 若改成"
            "另一格字段，那正是这一条要挡的空头承诺：\n" + doc)


# ---------------------------------------------------------------- 2 事实还在


def test_the_incomplete_reading_is_still_a_fact(tmp_path: pathlib.Path) -> None:
    """行为：坏行 / 认不出来的行让 `checked=False`；读得出来的行照读。"""
    root = tmp_path / "ws"
    sec = SEC.Secretary("M", root=root)
    path = SEC.retired_path(root, "t-000001")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"task_id": "t-000009", "name": "F1", "owner": "t-000001"}\n'
        '{"reason": "认不出这是哪一号"}\n'
        '{不是 JSON\n',
        encoding="utf-8")
    got = sec.retired_ledger("t-000001", trusted_shard=True)
    assert got["checked"] is False, got
    assert got["bad"], ("坏行没有被报出来 ⇒ '读不全'又被吞了", got)
    assert got["unattributable"], ("认不出来的行没有进这一档", got)
    assert "读不全" in str(got["reason"]), got
    # 读得出来的行照读（它既没被整份丢弃，也没被折成"这一片没有销号"）。
    names = [str(r.get("name") or "") for r in got["rows"] if str(r.get("name") or "")]
    assert names == ["F1"], got
    assert [r for r in got["rows"] if str(r.get("task_id") or "") == "t-000009"], got


def test_the_reader_side_twin_is_live() -> None:
    """对照：同一份事实在调用方那一层有读者（`getattr` 那 4 处是读点）。"""
    tree = _parse((SRC / "conductor.py").read_text(encoding="utf-8"))
    reads: list[str] = []
    writes = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == READER_TWIN:
            if isinstance(node.ctx, ast.Store):
                writes += 1
            else:
                reads.append(f"属性读 @{node.lineno}")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) >= 2
              and isinstance(node.args[1], ast.Constant)
              and node.args[1].value == READER_TWIN):
            reads.append(f"getattr 读 @{node.lineno}")
    assert writes >= 1, f"{READER_TWIN} 没有写点 ⇒ 判据失去对象"
    assert len(reads) >= 3, (
        f"{READER_TWIN} 的读者只剩 {len(reads)} 处（{reads}）—— 那一格也在退化成死读数")


# ---------------------------------------------------------------- 3 反真空


#: 改前那两处写点（逐字来自 2026-11-20 的盘上源码）。
OLD_FIELD_LINES = (
    "        self.last_retired_ledger: dict[str, Any] = {}\n"
    "        self.last_retired_ledger = dict(out)\n"
)

#: 改前那句承诺（逐字来自 `_retired_used` 的 docstring）。
OLD_PROMISE = ("`bad` / `unattributable` 不再被 `_bad` 丢掉 —— 它们留在 "
               "`self.last_retired_ledger` 里，'这一格读不全'从此是一个读得出来的事实")


def test_putting_the_field_and_promise_back_turns_a_red() -> None:
    """反真空：旧字段两处写 + 旧承诺句 ⇒ 检查器必报；真源码一条都不命中。"""
    assert [n for n, _line in _field_hits(OLD_FIELD_LINES)] == [1, 2], _field_hits(OLD_FIELD_LINES)
    assert _field_hits(OLD_PROMISE), "旧承诺句里居然没有那一格 —— 夹具写错了"
    # 正控：真源码这一条现在命中 0 处（不是"什么都没扫到"）。
    real = HOME.family_text()
    assert _field_hits(real) == [], _field_hits(real)
    assert "def bind_task(" in real, "夹具前提变了：秘书家族里找不到 bind_task"


def test_stubbing_the_bad_lines_away_makes_the_fact_disappear(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把坏行打桩成"读得出来"（改前那一半）⇒ 第 2 条必红。"""
    monkeypatch.setattr(JF, "read_jsonl_state",
                        lambda path: ([{"task_id": "t-000009", "name": "F1",
                                        "owner": "t-000001"}], [], "ok"))
    with pytest.raises(AssertionError):
        test_the_incomplete_reading_is_still_a_fact(tmp_path)
