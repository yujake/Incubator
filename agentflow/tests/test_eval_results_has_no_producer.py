"""`eval_results` 这一档的边界：产品代码里没有产出方（所有者 2026-10-07 裁定「题 4 选 C」＝如实登记 `na`）。

现算读数（2026-10-07，命令见本文件末）：
- 产品代码（`src/`、`tools/`、`scripts/`）里 0 个 `eval_results` 的写入方
  （AST 扫 `tx.upsert(...)` / `insert(...)` 这类实调，不数注释、不数字符串）；
- 真机工作区（`agentflow/projects` 58 个 + 旧根 `projects` 23 个 = 81 个 `eval_results.json`）
  的 `rows` 全为空（每个文件都是 `{"schema_version": 1, "rows": []}`）；
- 全盘唯一 12 个 `rows` 非空的落在 `temp/audit/bt/**`，是测试夹具写出来的合成行
  （内容形如 `created_by: "agent-E"`、`date: "2026-01-01"`），不是真机产出。

所以"这一档 0 行"的准确含义是 没有产出方，不是"评测 0 分"，也不是"没问题"（三态里的第三态）。

为什么这条边界需要一条判据看着：`verify.py` 里 `evals = store.rows("eval_results")` 之后，
**0 行就不进任何检查** ⇒ 一份"审计干净"的报告会被读成"评测这一档没问题"。
而 `verify.py` 在 FC-27 禁改区，动它要人审 —— 所以这条边界钉在测试侧：
一旦有人真的补上产出方（那是好事），这条判据会红，逼人回来把真正的评测判据与这份登记一起补上，
而不是让"0 行"悄悄变成"有几行、但那几行没人验收"。

复算命令（三条，逐条可在 `D:\\Incubator` 下跑）：
```
# ① 产品代码里的写入方（AST 实调）
python -B -c "import ast,pathlib;hits=[(str(p),n.lineno) for p in pathlib.Path('agentflow/src').rglob('*.py') for n in ast.walk(ast.parse(p.read_text(encoding='utf-8'))) if isinstance(n,ast.Call) and getattr(n.func,'attr','') in ('upsert','insert') and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='eval_results'];print(hits or '（无）')"
# ② 真机根下的文件数与"rows 非空"的文件数
python -B -c "import pathlib,re;fs=[p for r in ('agentflow/projects','projects') for p in pathlib.Path(r).rglob('eval_results.json')];ne=[p for p in fs if not re.search(r'\\\"rows\\\":\\s*\\[\\s*\\]', p.read_text(encoding='utf-8'))];print(len(fs),'个文件；rows 非空',len(ne))"
# ③ 全盘非空的那几个是谁
python -B -c "import pathlib,re;fs=pathlib.Path('.').rglob('eval_results.json');ne=[str(p) for p in fs if not re.search(r'\\\"rows\\\":\\s*\\[\\s*\\]', p.read_text(encoding='utf-8'))];print(len(ne));print('\\n'.join(ne[:14]))"
```
"""

from __future__ import annotations

import ast
import pathlib
from typing import Iterable

REPO = pathlib.Path(__file__).resolve().parents[1]
#: "产品代码"的范围（判据只对这三处断言"没有写入方"）。
_PRODUCT_DIRS = ("src", "tools", "scripts")
#: 写表的调用名（本仓的写入入口就这几个；`store.tx(...)` 是上下文管理器，不算写入调用）。
_WRITE_METHODS = ("upsert", "insert", "write")


def eval_writers_in_source(src: str, where: str) -> list[str]:
    """源码串里"真写 `eval_results`"的调用点。纯函数：正控与负控都调它。

    为什么用 AST 而不 grep：`eval_results` 在注释、docstring、类型名里到处出现
    （本文件自己就写了几十次）—— 数它们等于数空气。
    """
    out: list[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:  # 读不动就如实报"没查成"，不折成"干净"
        return [f"{where}: 解析失败（SyntaxError）⇒ 没查成"]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", "") not in _WRITE_METHODS:
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "eval_results":
            out.append(f"{where}:{node.lineno} {getattr(node.func, 'attr', '')}(eval_results)")
    return out


def eval_writers_in(files: Iterable[pathlib.Path]) -> list[str]:
    """一批文件里的写入点（逐文件调用 `eval_writers_in_source`）。"""
    out: list[str] = []
    for p in files:
        out += eval_writers_in_source(p.read_text(encoding="utf-8"), str(p))
    return out


def _py_files(*dirs: str) -> list[pathlib.Path]:
    return sorted(p for d in dirs for p in (REPO / d).rglob("*.py"))


def test_no_product_code_writes_eval_results() -> None:
    """正控：产品代码里不许有 `eval_results` 的写入方（今天如实是 0）。"""
    hits = eval_writers_in(_py_files(*_PRODUCT_DIRS))
    assert not hits, (
        "产品代码里出现了 `eval_results` 的写入方：\n  " + "\n  ".join(hits)
        + "\n这是好消息，但必须一起做三件事（否则它会静默地变成'有几行、没人验收'）：\n"
        "  ① 把真正的评测判据补上（这一档今天在 `verify.py` 里读到 0 行就什么都不报）；\n"
        "  ② 更新本文件的边界登记（`draft/69 §5` 的那一行写的是 `na`＝没有产出方）；\n"
        "  ③ 把这条判据换成'写入方是谁、写出来的行被谁验收'。"
    )


def test_the_writer_scanner_is_not_vacuous() -> None:
    """反真空：同一个扫描器在测试面上必须能扫出真的写入点来。

    否则"产品代码里 0 个"可能只是"扫描器根本看不见写入"
    （本仓踩过这个形态：探针静默吞掉异常、每处都读成 0，报告照样全绿）。
    测试面今天确实有写入点（`tests/test_fc05_contract.py` 等会真写这一张表）。
    """
    hits = eval_writers_in(_py_files("tests"))
    assert hits, (
        "同一个扫描器在 tests/ 里一个写入点都没扫到 ⇒ 它看不见写入，"
        "所以上面那条「产品代码 0 个」不构成证据（空集永远是子集）"
    )


def test_the_scanner_catches_a_synthetic_writer() -> None:
    """负控：喂一段带写入调用的源码 ⇒ 必须报出来；两种写法都要认。"""
    src = (
        "with store.tx('eval_results', actor='x') as tx:\n"
        "    tx.upsert('eval_results', row)\n"          # 位置参数写法
        "store.insert(table='eval_results', row=row)\n"  # 关键字写法
        "store.upsert('literature', row)\n"              # 写别的表：不许误报
    )
    hits = eval_writers_in_source(src, "synthetic")
    assert any("upsert(eval_results)" in h for h in hits), hits
    assert not any("literature" in h for h in hits), hits


def test_the_eval_table_is_a_real_table_so_the_empty_scan_means_something() -> None:
    """反真空的另一半：`eval_results` 必须是真的注册表 —— 否则"没人写它"是因为它不存在。"""
    from agentflow import schema as S

    assert "eval_results" in S.TABLES, sorted(S.TABLES)
    assert S.TABLES["eval_results"] is not None, "schema 里 `eval_results` 的登记是空的"
    assert hasattr(S, "EvalResult"), "schema 里读不到 `EvalResult` 行类型 ⇒ 这条边界失去对象"
