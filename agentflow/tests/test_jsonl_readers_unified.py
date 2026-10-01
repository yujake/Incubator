# -*- coding: utf-8 -*-
"""JSONL 读法只有一个实现（`draft/36` 的 T-6）。

`artifacts.read_ledger` / `signatures.read_ledger` / `sessions.read_session` 合并前三者
各写了一份完整实现（连"坏行逐条报出、不静默跳过"的注释都一样），差别只有一句措辞。
合并之后它们都转发到 `jsonlfile.read_jsonl`。

这条判据钉两件不同的事，缺一条就退化：

1. 语义：在 7 组夹具上，三个入口给出的 `(记录, 坏行说明)` 必须逐字相同。
   钳的是"同一份坏文件，`verify` 说它坏、`session show` 说它好"这类漂移；
   它同时也是"合并之后语义没变"的凭据（夹具覆盖缺文件 / 空文件 / 空行 /
   合法行 / 非法 JSON / 合法但不是对象 / 混合）。
2. 只有一个实现：三个入口的源码里必须出现对 `read_jsonl` 的调用 ——
   这一条防的是"将来有人把手写的循环又抄回来"。没有它，第 1 条在"三份拷贝恰好一致"
   的时候照样绿（而那正是要被消灭的形态）。

另有一条负控：拿一段内联拷贝去喂第 2 条的判据，必须红 ——
否则"源码里有 `read_jsonl`"可能只是恰好被注释里的字面量满足。
"""
from __future__ import annotations

import inspect
import json
import pathlib

import pytest

from agentflow import artifacts as A
from agentflow import jsonlfile as J
from agentflow import sessions as SS
from agentflow import signatures as SG

SID = "2026-10-01"

#: 7 组夹具：`(名字, 文件内容 or None（表示不建文件）)`。
CASES: tuple[tuple[str, str | None], ...] = (
    ("missing", None),
    ("empty", ""),
    ("blank-only", "\n   \n\t\n"),
    ("one-good", '{"a": 1}\n'),
    ("invalid-json", '{"a": 1\n'),
    ("non-object", "[1, 2, 3]\n"),
    ("mixed", '{"a": 1}\n\n[1, 2]\n{"a": 1\n{"b": 2}\n'),
)


def _write_case(root: pathlib.Path, content: str | None) -> pathlib.Path:
    """把同一份内容写进三处：产物台账 / 签名台账 / 会话记录。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    paths = {
        "artifacts": root / A.LEDGER_NAME,
        "signatures": root / SG.LEDGER_NAME,
        "sessions": root / "sessions" / f"{SID}.jsonl",
    }
    for p in paths.values():
        if content is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(content, encoding="utf-8", newline="\n")
    return paths["signatures"]


@pytest.mark.parametrize("name,content", CASES, ids=[c[0] for c in CASES])
def test_the_three_entry_points_agree_on_every_fixture(tmp_path: pathlib.Path,
                                                       name: str, content: str | None) -> None:
    """判据 1：三个入口在 7 组夹具上给出的 `(记录, 坏行说明)` 必须逐字相同。"""
    root = tmp_path / name
    sig_path = _write_case(root, content)

    got_a = A.read_ledger(root)
    got_s = SG.read_ledger(sig_path)
    got_e = J.read_jsonl(root / "sessions" / f"{SID}.jsonl")
    got_sess = SS.read_session(root, SID)

    assert got_a == got_s == got_e == got_sess, {
        "artifacts": got_a, "signatures": got_s, "jsonlfile": got_e, "sessions": got_sess}


def test_the_fixtures_really_exercise_both_problem_kinds() -> None:
    """反真空：夹具必须真的产出"读不出来"与"不是对象"两类问题。

    没有这条，上面那条可能在"7 组夹具全都不报问题"的情况下照样绿 ——
    而"坏行要报"正是这次合并要保住的东西。
    """
    import tempfile

    kinds: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="jsonl-fixtures-") as td:
        for name, content in CASES:
            p = pathlib.Path(td) / f"{name}.jsonl"
            if content is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(content, encoding="utf-8", newline="\n")
            _records, problems = J.read_jsonl(p)
            for prob in problems:
                kinds.add("unreadable" if "读不出来" in prob else "not-object")
    assert kinds == {"unreadable", "not-object"}, (
        f"夹具只覆盖了 {sorted(kinds)} 类问题 ⇒ 判据的判别力不完整")


def _delegates_to_the_shared_reader(fn) -> bool:
    """这个入口是不是转发到 `read_jsonl`（而不是自己又写了一份循环）。"""
    src = inspect.getsource(fn)
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    return any("read_jsonl(" in ln for ln in code_lines)


def test_all_three_entry_points_delegate_to_the_shared_reader() -> None:
    """判据 2：三个入口都转发到 `jsonlfile.read_jsonl`（不许再抄一份循环）。"""
    for fn in (A.read_ledger, SG.read_ledger, SS.read_session):
        assert _delegates_to_the_shared_reader(fn), (
            f"{fn.__module__}.{fn.__name__} 没有转发到 `read_jsonl` —— "
            "要么它自己又写了一份循环，要么这次合并没有落到位")


def test_the_delegation_probe_is_not_vacuous() -> None:
    """负控：把一段内联拷贝喂给上面那条探针，它必须说"没转发"。

    没有这条，"源码里出现了 `read_jsonl(`"可能只是被注释或字符串满足，
    判据 2 就成了一条恒真的断言。
    """

    def inlined(path):
        """一份手写循环（模拟"有人把实现抄回来"）。"""
        p = pathlib.Path(path)
        if not p.is_file():
            return [], []
        records, problems = [], []
        for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except ValueError as e:
                problems.append(f"第 {i} 行读不出来（{type(e).__name__}: {e}）")
                continue
            if not isinstance(obj, dict):
                problems.append(f"第 {i} 行不是对象")
                continue
            records.append(obj)
        return records, problems

    assert not _delegates_to_the_shared_reader(inlined), (
        "探针把一份内联拷贝认成了『转发』⇒ 判据 2 是真空的")
