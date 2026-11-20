# -*- coding: utf-8 -*-
"""前置判据（SECSPLIT，2026-11-20）：两处「构造之后补写的字段」改成显式的口。

## 为什么有这一条

拆 `secretary.py` 之前必须先把跨模块的共享可变状态显式化（`temp/splitdesign/04-STATE-ORDER.md`
甲类）。本文件钉其中两处：

- `model_source`：改前是"先造 Secretary、再 `sec.model_source = source`"，于是补写之前的
  任何一次 `judge()` 读到的都是空串 —— 读数里少了「为什么没有判断面」那一句。现在它是
  `__init__(model_source=...)` 的构造参数：与 `seam=` 同生，没有来源就没有那条缝。
- `last_repair_named`：改前是实例字段，写侧在 `roster_repair`、读侧在 `retire` 与
  `conductor._register_roster` 的下一句，靠"刚跑完就立刻读"这个时间窗。现在它是
  `roster_repair(*, owner, named=None)` 的出参：读数归调用方，字段删掉。

## 本文件钉四件事

1. 结构：`model_source` 是构造参数（`grep` 层面：`src/`、`tools/`、`scripts/` 里
   `X.model_source = ...` 的写点只剩 `Secretary.__init__` 一处）；`last_repair_named`
   这个名字在全仓不再存在。
2. 行为：`Secretary(..., model_source=...)` 之后 `judge()` 的 `checked=False` 里带着
   那句装配读数；`roster_repair(..., named=names)` 把"补成了谁"写进调用方的清单。
3. 回执：`retire` 的 `why` 里仍然有"补名：<号> 补成 <名>"（读数没有因为搬出字段而丢）。
4. 反真空：把构造参数打桩成不写（子类 `__init__` 吞掉它）⇒ 第 2 条的断言必红；
   把 `roster_repair` 打桩成"只回条数、不写出参" ⇒ 第 3 条的回执必红。

零模型：夹具只有台账与名册；工作区在 `tmp_path` 里自建。
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest

from agentflow import secretary as SEC
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store

REPO = pathlib.Path(__file__).resolve().parents[1]
SCAN_ROOTS: tuple[str, ...] = ("src", "tools", "scripts")
BR = "2026-11-20T09:00:00+08:00"


def _sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in SCAN_ROOTS:
        base = REPO / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out[path.relative_to(REPO).as_posix()] = path.read_text(
                encoding="utf-8", errors="replace")
    return out


def _enclosing_spans(tree: ast.AST) -> list[tuple[int, int, int, str]]:
    """每个函数 / 类的 (起点, 终点, 名字长度, qualname)；按行号取最内层，见 `_at`。"""
    out: list[tuple[int, int, int, str]] = []

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = ".".join(stack + [child.name])
                out.append((child.lineno, child.end_lineno or child.lineno, len(q), q))
                walk(child, stack + [child.name])
            else:
                walk(child, stack)

    walk(tree, [])
    return out


def _at(spans: list[tuple[int, int, int, str]], line: int) -> str:
    best, best_len = "", -1
    for start, end, length, q in spans:
        if start <= line <= end and length > best_len:
            best, best_len = q, length
    return best


def _writes(sources: dict[str, str], attr: str) -> list[tuple[str, str, int]]:
    """`X.<attr> = ...` 的全部写点：(模块, 所在 qualname, 行号)。"""
    found: list[tuple[str, str, int]] = []
    for module, text in sorted(sources.items()):
        if f".{attr}" not in text:
            continue
        tree = ast.parse(text)
        spans = _enclosing_spans(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == attr:
                    found.append((module, _at(spans, node.lineno), node.lineno))
    return found


# ---------------------------------------------------------------- 1 结构：写点


def test_model_source_is_written_only_by_the_constructor() -> None:
    """结构：产品代码里 `model_source` 的写点只剩 `Secretary.__init__` 一处。"""
    sources = _sources()
    assert len(sources) >= 200, f"只扫到 {len(sources)} 个 .py ⇒ 扫描面没接上"
    writes = _writes(sources, "model_source")
    bad = [w for w in writes if not (w[0] == "src/agentflow/secretary.py"
                                     and w[1] == "Secretary.__init__")]
    assert not bad, ("model_source 又出现了构造之后补写的写点（只许 __init__）：\n"
                     + "\n".join(f"  {m}:{ln}  {q}" for m, q, ln in bad))
    # 正控：构造函数那一处必须在扫描面里（否则上面那条是真空的）。
    assert any(m == "src/agentflow/secretary.py" and q == "Secretary.__init__"
               for m, q, _ln in writes), writes


def test_last_repair_named_is_gone_everywhere() -> None:
    """结构：`last_repair_named` 的读写点一个不剩（读数改走调用方给的出参）。"""
    bad: list[str] = []
    for module, text in sorted(_sources().items()):
        if "last_repair_named" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "last_repair_named"):
                bad.append(f"{module}:{node.lineno}")
    assert not bad, bad
    # 正控：`named` 这个出参确实在写侧出现过（否则上面那条是真空的）。
    src = (REPO / "src/agentflow/secretary.py").read_text(encoding="utf-8")
    assert "named.append(" in src, "补名的出参不见了 ⇒ 上面的'字段已消失'没有对象"


def test_the_factory_hands_the_source_to_the_constructor() -> None:
    """结构：两个装配点都用构造参数，而不是"造完再补"。"""
    tree = ast.parse((REPO / "src/agentflow/secretary.py").read_text(encoding="utf-8"))
    names = _enclosing_spans(tree)
    calls: list[tuple[str, dict[str, str]]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Secretary"):
            calls.append((_at(names, node.lineno),
                          {kw.arg or "": ast.unparse(kw.value) for kw in node.keywords}))
    got = [kw for q, kw in calls if q == "for_role_wired"]
    assert got, "for_role_wired 里找不到构造 Secretary 的那一句"
    assert any(kw.get("model_source") == "source" for kw in got), got
    loop = (REPO / "src/agentflow/agent_loop.py").read_text(encoding="utf-8")
    assert "model_source=source" in loop, "agent_loop 的装配点又退回构造之后补写了"
    assert "sec.model_source = source" not in loop


# ---------------------------------------------------------------- 2 行为


def test_the_construction_argument_reaches_the_judge_reading(
        tmp_path: pathlib.Path) -> None:
    """行为：构造期给的来源，在"没有缝"那一格里读得出来。"""
    sec = SEC.Secretary("M", root=tmp_path,
                        model_source="none（夹具：秘书那一档没有配 key）")
    got = sec.judge("duplicate_retry", {"key": "k"})
    assert got.get("checked") is False, got
    assert "装配读数：none（夹具：秘书那一档没有配 key）" in str(got.get("reason") or ""), got


def test_wired_factory_records_its_source_without_a_post_write(tmp_path: pathlib.Path) -> None:
    """行为：`for_role_wired` 造出来的秘书，来源已经在构造期落定。"""
    sec = SEC.for_role_wired("M", root=tmp_path, seam=None)
    assert sec.model_source.startswith("none"), sec.model_source


def test_dropping_the_constructor_argument_turns_the_reading_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把构造口打桩成不写（子类吞掉 model_source）⇒ 上一条必红。"""
    real = SEC.Secretary

    class _DropsModelSource(real):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kw: Any) -> None:
            kw.pop("model_source", None)
            super().__init__(*args, **kw)

    monkeypatch.setattr(SEC, "Secretary", _DropsModelSource)
    sec = SEC.for_role_wired("M", root=tmp_path, seam=None)
    assert sec.model_source == "", "打桩之后仍然读得到来源 ⇒ 上一条断言没有咬住构造口"


# ---------------------------------------------------------------- 3 出参与回执


def _env(tmp_path: pathlib.Path) -> tuple[Conductor, str]:
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    cond.secretary = Secretary("M", root=ws, store=st, enable_model=False)
    cond.roster_sink = cond.secretary
    return cond, str(cond.open_top_level_run("M", "前置：显式状态"))


def _child(cond: Conductor, parent: str, *, tag: str, status: str = "done") -> str:
    return str(cond._write_new_row({
        "role": "D", "action": "research", "called_by": "M",
        "parent_task_id": parent, "depth": 1, "input_key": f"explicit:{tag}",
        "status": status, "outcome": "ok" if status == "done" else None,
        "refusal_reason": None, "instance": "", "detail": "前置判据夹具",
        "error": None, "started_at": BR, "ended_at": BR if status == "done" else None,
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note="explicit:child"))


def test_roster_repair_writes_the_names_into_the_callers_list(tmp_path: pathlib.Path) -> None:
    """行为：出参拿到"补成了谁"；不传出参时只回条数，且实例上没有那个字段。"""
    cond, parent = _env(tmp_path)
    sec = cond.secretary
    orphan = _child(cond, parent, tag="orphan")
    assert not hasattr(sec, "last_repair_named")
    names: list[dict[str, Any]] = []
    fixed, why, skipped = sec.roster_repair(owner=parent, named=names)
    assert (fixed, why, skipped) == (1, "", []), (fixed, why, skipped)
    assert [str(x.get("task_id")) for x in names] == [orphan], names
    assert str(names[0].get("name") or ""), names
    assert not hasattr(sec, "last_repair_named"), "字段又被写回来了"

    # 不传出参的那一档：读数不留在实例上（第二次已经没有可补的行）。
    assert sec.roster_repair(owner=parent) == (0, "", [])


def test_retire_receipt_still_names_the_repaired_child(tmp_path: pathlib.Path) -> None:
    """行为：补名的回执仍然在（读数从字段搬到出参，内容一字不少）。"""
    cond, parent = _env(tmp_path)
    sec = cond.secretary
    first = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=first, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    orphan = _child(cond, parent, tag="orphan")
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="前置判据")
    assert got.get("ok") is True, got
    assert any("补名" in str(w) and orphan in str(w) for w in (got.get("why") or [])), got


def test_stubbing_the_out_parameter_loses_the_note(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：`roster_repair` 只回条数、不写出参 ⇒ 上一条回执断言必红。"""
    def bare(self: Any, *, owner: str, named: list[dict[str, Any]] | None = None
             ) -> tuple[int, str, list[str]]:
        return 1, "", []

    monkeypatch.setattr(Secretary, "roster_repair", bare)
    cond, parent = _env(tmp_path)
    sec = cond.secretary
    first = _child(cond, parent, tag="first")
    made = sec.roster_add(owner=parent, role="D", task_id=first, brief="第一件活",
                          task="做研究", want_name="D1")
    assert made.get("problem") == "", made
    _child(cond, parent, tag="orphan")
    got = sec.retire(owner=parent, name="D1", by_task_id=parent, reason="前置判据")
    assert got.get("ok") is True, got
    assert not any("补名" in str(w) for w in (got.get("why") or [])), got
