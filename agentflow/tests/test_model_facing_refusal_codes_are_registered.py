# -*- coding: utf-8 -*-
"""判据：模型面拒因码必须真的登记进 `errorstats.CODE_TABLE`，且出处指得到符号。

## 为什么单列一份

`errorstats.CODE_TABLE` 的出处口径是 `文件::符号名`（`R-BE4`）。"登记过"这件事本身
不能靠文本 grep 证明 —— 今晚已经吃过一次假绿：码只出现在一句**注释**里，`grep` 命中
而代码根本不产它。所以这一份判据走 AST：

1. 每个码都在 `CODE_TABLE` 里，类目是 `tool_refused_controlled`；
2. 出处里的 `文件::符号名` 逐条对上 EXPECTED（指到别处也红），且那个符号真的定义在
   那个文件里（函数 / 类 / 方法 / 模块级赋值都认，注释不在 AST 里）；
3. 那个**码字符串本身**真的作为 AST 字面量出现在出处文件里（不是注释里提过）。

反真空：EXPECTED 是显式清单。删掉 `CODE_TABLE` 里任意一行 ⇒ 这里当场红（第 1 条点名
那个码），不是"少了一行也照样绿"。
"""
from __future__ import annotations

import ast
import pathlib
import re

from agentflow import errorstats as ES

REPO = pathlib.Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"(src/agentflow/[\w/]+\.py)::([A-Za-z_][\w.]*)")

#: 12 个模型面拒因码 → 它们在源码里的产出符号（逐条核过；出处写符号名不写行号）。
EXPECTED: tuple[tuple[str, str, str], ...] = (
    ("target_not_silent", "src/agentflow/conductor.py",
     "RETIRE_REFUSAL_TARGET_NOT_SILENT"),
    ("not_yours", "src/agentflow/conductor.py", "Conductor.ack_items"),
    ("not_mine", "src/agentflow/agent_loop.py", "AgentLoop._do_interrupt"),
    ("not_conductor", "src/agentflow/userio.py", "ASK_NOT_CONDUCTOR"),
    ("not_caller", "src/agentflow/conductor.py", "Conductor.escalate"),
    ("public_is_not_a_conversation", "src/agentflow/agent_loop.py",
     "AgentLoop._public_face_refusal"),
    # 历史理由码：E 不再产出它，但它留在 `FORMAL_REASONS` 这张词表里（历史台账仍带着它）。
    ("formal_moved_to_l", "src/agentflow/agent_e/_support.py", "FORMAL_REASONS"),
    ("formal_not_in_e", "src/agentflow/agent_e/_support.py", "E_NO_FORMAL_REASON"),
    ("missing_relevance", "src/agentflow/litstage.py", "admission_plan"),
    ("dependency_section_missing", "src/agentflow/depsection.py",
     "REFUSED_SECTION_MISSING"),
    ("dependency_section_unreadable", "src/agentflow/depsection.py", "REFUSED_SECTION"),
    ("proof_review_without_evidence", "src/agentflow/verifications.py", "CODE_WRITE"),
)


def _defined_names(path: pathlib.Path) -> set[str]:
    """文件里"有名字的东西"：顶层/嵌套 def、class、类方法、模块级赋值名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()

    def walk(node: ast.AST, prefix: str) -> None:
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                names.add(name)
                walk(child, name + ".")
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        names.add(f"{prefix}{target.id}")
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                names.add(f"{prefix}{child.target.id}")

    walk(tree, "")
    return names


def _string_constants(path: pathlib.Path) -> set[str]:
    """文件里**会被执行到**的字符串字面量（注释不在 `ast` 里，这正是要用 AST 的理由）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_the_twelve_model_facing_codes_are_registered() -> None:
    """a：12 个码逐条在码表里，类目是新类目，出处点名的符号与 EXPECTED 逐字一致。"""
    assert len(EXPECTED) == 12, f"清单本身的条数漂了：{len(EXPECTED)}"
    bad: list[str] = []
    for code, rel, symbol in EXPECTED:
        category = ES.CODE_TO_CATEGORY.get(code)
        if category is None:
            bad.append(f"{code!r}：CODE_TABLE 里没有这一行")
            continue
        if category != "tool_refused_controlled":
            bad.append(f"{code!r}：类目是 {category!r}，不是 tool_refused_controlled")
        where = str(ES.CODE_PROVENANCE.get(code) or "")
        if f"{rel}::{symbol}" not in where:
            bad.append(f"{code!r}：出处没有点到 {rel}::{symbol} —— {where!r}")
    assert not bad, "这些模型面拒因码没有按口径登记：\n  " + "\n  ".join(bad)


def test_every_provenance_symbol_really_exists_in_its_file() -> None:
    """a（AST 那一半）：符号真的定义在那个文件里，且码本身是 AST 字面量（不是注释）。"""
    cache_def: dict[str, set[str]] = {}
    cache_const: dict[str, set[str]] = {}
    bad: list[str] = []
    for code, rel, symbol in EXPECTED:
        path = REPO / rel
        if not path.is_file():
            bad.append(f"{code!r}：{rel} 不存在")
            continue
        if rel not in cache_def:
            cache_def[rel] = _defined_names(path)
            cache_const[rel] = _string_constants(path)
        if symbol not in cache_def[rel]:
            bad.append(f"{code!r}：{rel} 里没有符号 {symbol}（AST 判的，注释不算）")
        if code not in cache_const[rel]:
            bad.append(f"{code!r}：{rel} 里没有这个码的 AST 字面量（只在注释里提过不算）")
    assert not bad, "出处/码经不起 AST 核对：\n  " + "\n  ".join(bad)


def test_a_registered_code_becomes_countable(tmp_path: pathlib.Path) -> None:
    """接线：登记之后，真形受控拒绝（`refusal_code=target_not_silent`）真的数得到。

    件 1 之前/登记之前这一条是 `unclassified["tool"]`（total 0）—— 码表不是文档，
    它决定这一类数不数得到。
    """
    import json

    (tmp_path / "data").mkdir(parents=True)
    (tmp_path / "data" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "sessions").mkdir()
    record = {
        "kind": "agent_step", "role": "B", "index": 3, "shape": "tool",
        "payload": {"name": "conductor.retire_child"},
        "result": {"ok": True, "error": None, "meta": {},
                   "data": {"checked": True, "state": "refused",
                            "refusal_code": "target_not_silent",
                            "reason": "目标还在飞，不许销号"}},
    }
    (tmp_path / "sessions" / "s1.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    stats = ES.error_action_stats(tmp_path)
    assert stats.count("B", "tool_refused_controlled") == 1, stats.by_role
    assert stats.sources["unclassified"]["tool"] == 0, stats.sources["unclassified"]
