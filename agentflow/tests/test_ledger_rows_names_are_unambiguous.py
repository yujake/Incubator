# -*- coding: utf-8 -*-
"""A2FIX 判据：一个键名只指一件事 —— `ledger_rows` 拆成三个自解释的名字。

## 改前现场（同一工作区、同一时刻，从产出点现读）

| 面 | 旧键名 | 值 | 它数的是 |
|---|---|---|---|
| `GET /api/acceptance` 的 `auxiliary` | `ledger_rows` | `"55"`（字符串） | 概念图三张表：文献 + 概念 + 关系 |
| `GET /api/package` 的 `structure.ledger` | `ledger_rows` | `22`（数字） | `statements` 表行数 |
| `GET /api/package` 的 `closing.cost`（与 `modelcost.reconcile_usage`） | `ledger_rows` | `663`（数字） | `usage_ledger` 表行数 |

页面把后两个都印成「台账行 / 账本行」⇒ 读者无法区分。改了三个名字：

- `concept_graph_rows`（验收辅助读数，文本面 ⇒ 字符串）
- `statement_ledger_rows`（命题台账 ⇒ 数字 / `null`）
- `usage_ledger_rows`（用量账本 ⇒ 数字 / `null`）

## 三条

1. `test_each_new_name_means_exactly_one_thing`：四个面现读，每个新名字对回盘上
   同一份表的行数（独立复算），并断言这个名字只出现在它该出现的那一处；
2. `test_the_old_key_name_is_gone_from_every_key_position`：AST 扫
   `src/` + `scripts/` 的键位置（dict 键 / 下标 / `.get` 参数），文本扫
   `tests/`、`ui/src`、生成物 `types.ts`、已构建静态包；
3. `test_putting_the_old_key_back_turns_it_red`：负控 —— 真源码副本里塞回一处 ⇒
   AST 扫描必红；真装配路径里塞回一处（`_closing_cost` 返回的 dict）⇒
   动态扫描必红。
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
from typing import Any

from agentflow import modelcost as MC
from agentflow import reviewaccept as RX
from agentflow.store import Store
from agentflow.webui import readers as R

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"
TYPES_TS = REPO / "ui" / "src" / "types.ts"
UI_SRC = REPO / "ui" / "src"
STATIC = SRC / "agentflow" / "web" / "static"

#: 旧键名（判据的负控要把它塞回去；它只以常量出现，不作为任何 dict 的键）。
OLD = "ledger_rows"
#: 三个新名字，各自只有一个意思。
NEW = ("concept_graph_rows", "statement_ledger_rows", "usage_ledger_rows")

_TS = "2026-11-19T10:00:00+08:00"
_SID = "2026-11-19"
_TASK = "t-000001"

#: 旧名作为键出现的样子（`review_ledger_rows` 不匹配：`_` 是词字符，前面没有词边界）。
_OLD_KEY = re.compile(r"\bledger_rows\b")


# ====================================================================== 夹具
def _write_rows(root: pathlib.Path, table: str, rows: list[dict[str, Any]]) -> None:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / f"{table}.json").write_text(
        json.dumps({"schema_version": 2, "rows": rows}, ensure_ascii=False),
        encoding="utf-8")


def _workspace(tmp_path: pathlib.Path) -> tuple[pathlib.Path, Store]:
    """最小工作区：概念图三张表 4 行、statements 2 行、usage_ledger 3 行。

    这三个数刻意互不相等（4 / 2 / 3）：旧名把它们都叫 `ledger_rows`，谁读错一位
    都能从值上看出来。
    """
    root = tmp_path / "ws"
    (root / "sessions").mkdir(parents=True)
    (root / "out" / "paper").mkdir(parents=True)
    events = [
        {"kind": "agent_run_start", "ts": _TS, "role": "F", "task_id": _TASK,
         "task": "夹具", "sid": _SID},
        {"kind": "agent_run_end", "ts": _TS, "role": "F", "task_id": _TASK,
         "stop_reason": "final", "steps": 0},
    ]
    (root / "sessions" / f"{_SID}.jsonl").write_text(
        "".join(json.dumps(one, ensure_ascii=False) + "\n" for one in events),
        encoding="utf-8")
    (root / "out" / "paper" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{theorem}\\label{thm:a} A. \\end{theorem}\n"
        "\\begin{proof} P. \\end{proof}\n\\end{document}\n",
        encoding="utf-8")
    _write_rows(root, "literature", [
        {"lit_id": "L000001", "title": "一", "status": "admitted"},
        {"lit_id": "L000002", "title": "二", "status": "admitted"},
    ])
    _write_rows(root, "relations", [
        {"rel_id": "R000001", "src": "c000000", "dst": "c000001", "kind": "uses"},
    ])
    _write_rows(root, "statements", [
        {"stmt_id": "000001", "kind": "theorem", "label": "thm:a",
         "statement_full": "A.", "statement_text": "A."},
        {"stmt_id": "000000", "kind": "concept", "label": "室图",
         "statement_full": "d", "statement_text": "室图"},
    ])
    _write_rows(root, "tasks", [
        {"task_id": _TASK, "role": "F", "status": "ok", "usd": 1.5, "inputs": []},
    ])
    _write_rows(root, "usage_ledger", [
        {"usage_id": "000000", "scope": "reason", "role": "F", "task_id": _TASK,
         "tokens_in": 1, "tokens_out": 1, "tokens_total": 2, "usd": 0.5,
         "attempts": 1, "at": _TS, "note": "", "idem_key": "idem-a"},
        {"usage_id": "000001", "scope": "summon", "role": "M", "task_id": _TASK,
         "tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "usd": 0.5,
         "attempts": 1, "at": _TS, "note": "", "idem_key": "idem-b"},
        {"usage_id": "000002", "scope": "extract", "role": "B", "task_id": _TASK,
         "tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "usd": 0.5,
         "attempts": 1, "at": _TS, "note": "", "idem_key": "idem-c"},
    ])
    return root, Store(root)


def _payloads(root: pathlib.Path, store: Store) -> dict[str, Any]:
    """四个产出点各现读一次（判据与负控共用这一份装配）。"""
    acc = R.acceptance_face(root, store, project_dir=".",
                            report_path="out/review/REPORT.md")
    pkg = R.package_face(root, store, project_dir=".",
                         report_path="out/review/REPORT.md")
    return {
        "acceptance": acc,
        "structure": pkg["structure"]["ledger"],
        "cost": pkg["closing"]["cost"],
        "reconcile": MC.reconcile_usage(store),
        "reviewaccept": RX.check_review(store, project_dir=".",
                                        report_path="out/review/REPORT.md"),
    }


# ====================================================================== 扫描器
def _key_paths(node: Any, prefix: str = "") -> list[str]:
    """递归收集一份 payload 里全部 dict 键的路径（列表下钻，其余叶子不看）。"""
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.append(path)
            out.extend(_key_paths(value, path))
    elif isinstance(node, list):
        for item in node:
            out.extend(_key_paths(item, prefix))
    return out


def _ast_old_key_offenders(path: pathlib.Path) -> list[tuple[int, str]]:
    """AST 扫一个 .py：旧名出现在键位置（dict 键 / 下标 / `.get` 参数）就记一条。

    只认键位置，不认标识符：`claims.ledger_rows` 是函数名（一个意思：断言台账行），
    `_ledger_rows` 是读表助手 —— 它们不是发给页面/脚本的键，不在本判据的范围里。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == OLD:
                    found.append((int(node.lineno), "dict 键"))
        elif isinstance(node, ast.Subscript):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value == OLD:
                found.append((int(node.lineno), "下标"))
        elif isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr in ("get", "pop", "setdefault")
                    and node.args):
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value == OLD:
                    found.append((int(node.lineno), f".{func.attr}() 参数"))
    return found


def _python_old_key_offenders(roots: tuple[pathlib.Path, ...]) -> list[str]:
    offenders: list[str] = []
    for base in roots:
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for lineno, where in _ast_old_key_offenders(path):
                offenders.append(f"{path.relative_to(REPO)}:{lineno}（{where}）")
    return offenders


# ====================================================================== 判据 1
def test_each_new_name_means_exactly_one_thing(tmp_path: pathlib.Path) -> None:
    """正控：三个新名字各自对回盘上同一份表；名字只出现在该出现的那一处。"""
    root, store = _workspace(tmp_path)
    got = _payloads(root, store)

    statements = store.rows("statements")
    graph_rows = (len(store.rows("literature"))
                  + len([r for r in statements if str(r.get("kind") or "") == "concept"])
                  + len(store.rows("relations")))
    usage_rows = len(store.rows("usage_ledger"))

    # ---- 面 1：/api/acceptance 的 auxiliary（文本面 ⇒ 字符串）
    aux = got["acceptance"]["auxiliary"]
    assert OLD not in aux, aux
    assert aux["concept_graph_rows"].isdigit(), aux
    assert int(aux["concept_graph_rows"]) == graph_rows, aux
    # 同一个读数在 Python 侧是 int（CLI 出口与这一面是同一件事的两种呈现）
    py_aux = got["reviewaccept"].auxiliary
    assert py_aux["concept_graph_rows"] == graph_rows, py_aux
    assert isinstance(py_aux["concept_graph_rows"], int), py_aux
    assert "concept_graph_rows_problem" not in py_aux, py_aux

    # ---- 面 2：/api/package 的 structure.ledger（数字）
    ledger = got["structure"]
    assert OLD not in ledger, ledger
    assert ledger["statement_ledger_rows"] == len(statements), ledger
    assert isinstance(ledger["statement_ledger_rows"], int), ledger

    # ---- 面 3/4：closing.cost 与 reconcile_usage（同一件事：usage_ledger 行数）
    cost = got["cost"]
    assert OLD not in cost, cost
    assert cost["usage_ledger_rows"] == usage_rows, cost
    assert isinstance(cost["usage_ledger_rows"], int), cost
    assert got["reconcile"]["usage_ledger_rows"] == usage_rows, got["reconcile"]
    assert cost["usage_ledger_rows"] == got["reconcile"]["usage_ledger_rows"]
    note = cost["reconciliation"]["note"]
    assert "usage_ledger_rows" in note, note
    assert _OLD_KEY.search(note) is None, note

    # ---- 名字只出现在该出现的那一处（一个名字一件事，不是"到处都能读到"）
    scalar = {"acceptance": {"auxiliary": aux},
              "structure": {"ledger": ledger},
              "cost": cost, "reconcile": got["reconcile"]}
    paths = _key_paths(scalar)
    where = {name: sorted(p for p in paths if p.rsplit(".", 1)[-1] == name) for name in NEW}
    assert where["concept_graph_rows"] == ["acceptance.auxiliary.concept_graph_rows"], where
    assert where["statement_ledger_rows"] == ["structure.ledger.statement_ledger_rows"], where
    assert where["usage_ledger_rows"] == ["cost.usage_ledger_rows",
                                          "reconcile.usage_ledger_rows"], where

    # ---- 类型：两个数字口径在生成物里是数字（字符串"55"那种混用不再有）
    text = TYPES_TS.read_text(encoding="utf-8")
    assert "statement_ledger_rows: number | null;" in text, "types.ts 没同步命题台账那一格"
    assert "usage_ledger_rows: number | null;" in text, "types.ts 没同步用量账本那一格"
    assert not re.search(r"(?m)^\s*ledger_rows\b", text), "types.ts 里旧名字还在"


# ====================================================================== 判据 2
def test_the_old_key_name_is_gone_from_every_key_position() -> None:
    """老名字不许再作为键出现：源码 AST / 测试 / 前端源码 / 生成物 / 构建产物。"""
    offenders = _python_old_key_offenders((SRC, REPO / "scripts"))
    assert offenders == [], "这些地方的旧键名还在：\n- " + "\n- ".join(offenders)

    # 测试与前端源码用文本扫（`C.ledger_rows(...)` 这类函数名/局部变量不是键，不抓；
    # 只抓引号里的旧键名与 `ledger_rows:` 这种键写法）
    quoted = re.compile(r"""["']ledger_rows["']""")
    hits: list[str] = []
    for path in sorted((REPO / "tests").rglob("*.py")):
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if quoted.search(line):
                hits.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()}")
    for path in sorted(UI_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx") or path.name == "types.ts":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _OLD_KEY.search(line):
                hits.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()}")
    assert hits == [], "旧键名还在：\n- " + "\n- ".join(hits)

    # 构建产物：改了 ui/src 就必须重建 web/static，否则页面还读旧名（这里就是那条读数）
    bundles = sorted((STATIC / "assets").glob("*.js"))
    assert bundles, "web/static/assets 里没有已构建的包 ⇒ 前端没重建"
    for path in bundles:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not _OLD_KEY.search(text), f"{path.name} 还带着旧键名 ⇒ 没有重建"


# ====================================================================== 判据 3（负控）
def test_putting_the_old_key_back_turns_it_red(
        tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    """负控：把老键名塞回一处，两条扫描都必须红 —— 否则"干净"只是没查。"""
    real_readers = SRC / "agentflow" / "webui" / "readers.py"
    assert _ast_old_key_offenders(real_readers) == [], "正控不成立：真源码本来就红"

    doctored = tmp_path / "readers_doctored.py"
    doctored.write_text(
        real_readers.read_text(encoding="utf-8")
        + '\n\ndef _negative_control():\n    return {"ledger_rows": None}\n',
        encoding="utf-8")
    assert _ast_old_key_offenders(doctored), "负控没红：源码里塞回旧键名，AST 扫描仍说干净"

    # 动态：在真装配路径上塞回一处（`_closing_cost` 返回的 dict）
    root, store = _workspace(tmp_path)
    real_cost = R._closing_cost  # noqa: SLF001 —— 负控要包住真产出点

    def doctored_cost(*args: Any, **kwargs: Any) -> dict[str, Any]:
        out = real_cost(*args, **kwargs)
        out[OLD] = 0
        return out

    monkeypatch.setattr(R, "_closing_cost", doctored_cost)
    pkg = R.package_face(root, store, project_dir=".",
                         report_path="out/review/REPORT.md")
    paths = _key_paths({"cost": pkg["closing"]["cost"]})
    assert [p for p in paths if p.rsplit(".", 1)[-1] == OLD] == ["cost.ledger_rows"], (
        "负控没红：装配路径里塞回旧键名，动态扫描没抓住")
