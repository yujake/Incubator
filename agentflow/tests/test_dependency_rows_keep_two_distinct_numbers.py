# -*- coding: utf-8 -*-
"""依赖行的两个号各管一件事：`proof_no` 是出处，`path_group` 是组号。

## 为什么需要这一条（2026-11-12 逐行读证之后）

审计时我一度把 `proof_no` 与 `path_group` 当成"同一个数的两个名字"，并据此合并过一次来源。
逐行读代码 + 跑既有判据之后，那个前提是错的，两者各有语义：

| 名字 | 语义 | 从哪来 | 落到哪 |
|---|---|---|---|
| `proof_no` | 这条依赖出自第几份证明正文 | 收录入参（这份正文是第几份；产出侧不写稿头、不标路径号） | `used_by` 的 `#pN` 尾巴（`proofloc.used_by_of`） |
| `path_group` | 同一份证明里的第几条可选路径（组内 AND / 组间 OR） | 手稿依赖段的组号／收录分配的路径号 | `dependencies.path_group` 那一列 |

两条入口给的组合不一样，而且都合法：

- 手稿 `## 依赖` 段那一路：`depsection.deps_groups` 把两格赋同一个值（它 docstring 里
  "组号 = 路径号"说的是那一路的性质），于是 `used_by` 带 `#pN` 尾巴；
- 证明正文里分段扫出来的那一路：`path_group` 是 1、2…，而 `proof_no` 仍是 1
  （这几条依赖都出自同一份证明正文）⇒ `used_by` 不带尾巴。
  既有判据 `test_the_secretary_scans_the_proof.py::test_explicit_proof_paths_become_path_groups`
  钉的正是这个形态（期望 `{"lit:0003": 1, "lit:0004": 2, "stmt:…": 2}`）。

把两者并成一个数的后果是实测出来的：上面那条判据当场红（第 2 组的依赖顶着 `#p2` 写进去，
而它实际出自第 1 份证明），所以"合并成一个来源"的改法已撤回。

## 判据（钉住"各管一件事"，不是钉住"永远相等"）

| # | 判据 | 它钉住什么 |
|---|---|---|
| a | 正控：step 给 `proof_no=2, path_group=5` ⇒ `used_by` 以 `#p2` 结尾、`path_group=5` | 两个号互不覆盖（合并就没这一格） |
| b | 正控：step 只给 `path_group=2` ⇒ `used_by` 不带尾巴、`path_group=2` | 分段扫出来的那一路的形态 |
| c | 负控（canonical）：两格都不给 ⇒ 不带尾巴、`path_group=1` | 老写法逐字不变 |
| d | 解析侧：`depsection.deps_groups` 的手稿那一路两格相等 | 那一路的性质不变（谁把它拆开就红） |
| e | 源码面：唯一决定这两个号的地方（秘书 `_stamp_path_number`）里两格仍由两个表达式分别给出 | 防止有人（包括我）再"顺手合并"一次 |
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agentflow import depsection as DS
from agentflow import secretary as SEC

REPO = Path(__file__).resolve().parents[1]


class _Tx:
    """最小事务替身：只记 `dependencies` 落了什么、号怎么发。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []
        self._next = 0

    def alloc_id(self, kind: str) -> str:
        self._next += 1
        return f"{self._next:06d}"

    def upsert(self, table: str, row: Mapping[str, Any], *, note: str = "") -> None:
        self.rows.append((table, dict(row)))


def _step(**extra: Any) -> dict[str, Any]:
    """一条合法的依赖步骤：`Dependency.validate` 要求 `closed` 行必须指向已入库来源。"""
    base: dict[str, Any] = {"stmt_id": "1", "source_stmt_id": "000001", "status": "closed"}
    base.update(extra)
    return base


def _write(steps: list[dict[str, Any]]) -> _Tx:
    tx = _Tx()
    sec = object.__new__(SEC.Secretary)
    sec.role = "B"                      # type: ignore[attr-defined]
    sec._write_dep_steps(tx, steps, stmt_id="000004", body={})
    return tx


def _deps(tx: _Tx) -> list[dict[str, Any]]:
    return [row for table, row in tx.rows if table == "dependencies"]


def test_a_the_two_numbers_do_not_overwrite_each_other():
    """a：出处号与组号各自落进自己那一格。"""
    deps = _deps(_write([_step(proof_no=2, path_group=5)]))
    assert len(deps) == 1
    assert deps[0]["used_by"] == "stmt:000004#p2"
    assert deps[0]["path_group"] == 5


def test_b_a_path_group_without_a_proof_no_keeps_the_row_canonical():
    """b：分段扫出来的那一路（只有组号）⇒ `used_by` 不带尾巴。"""
    deps = _deps(_write([_step(path_group=2)]))
    assert deps[0]["used_by"] == "stmt:000004"
    assert deps[0]["path_group"] == 2


def test_c_no_numbers_at_all_stays_canonical():
    """c：两格都没有 ⇒ 第 1 份证明的第 1 条路径，`used_by` 与改前逐字相同。"""
    deps = _deps(_write([_step()]))
    assert deps[0]["used_by"] == "stmt:000004"
    assert deps[0]["path_group"] == 1


def test_d_the_manuscript_dependency_section_gives_both_numbers_the_same_value():
    """d：手稿 `## 依赖` 那一路两格相等（它 docstring 里"组号 = 路径号"说的是这一路）。"""
    rows = [{"line": 3, "stmt_id": "000001", "quote": "由引理 1", "path_group": 3},
            {"line": 4, "stmt_id": "000002", "quote": "由引理 2"}]
    groups = DS.deps_groups(rows, {"000001": "lemma", "000002": "lemma"})
    flat = [step for group in groups for step in group]
    assert flat, "反真空：这一段必须真的解析出步骤"
    for step in flat:
        assert int(step["proof_no"]) == int(step["path_group"]), step


def test_e_the_single_writer_still_sources_the_two_numbers_separately():
    """e：源码面 —— 唯一决定这两个号的地方两格仍取自两个表达式。

    这一条防的是"顺手合并"。2026-11-12 之后"写入路径号"只剩一处：B 的秘书在收录事务
    里调 `_stamp_path_number`（`register_statement` 里那两处 `dict(step, proof_no=…,
    path_group=…)` 已随分配下沉一起删掉）。所以扫描面从 B 的那个文件挪到这里：
    两格仍是两条赋值、右端仍是两个不同的来源（`proof_no` = 这一份证明正文，
    `path_group` = 这一条可选路径），而且 `path_group` 只在该盖的那一档盖
    （证明正文分段扫出来的那一路保留段落下标）。谁把它们并成一个表达式，这条就红。
    """
    import inspect

    src = inspect.getsource(SEC._stamp_path_number)
    assert 'one["proof_no"] = int(proof_no)' in src, src
    assert 'one["path_group"] = int(path_group)' in src, src
    # 分段扫出来的那一路：`path_group` 不被盖（保留段落下标）。
    assert "proof_scan" in src and "single_group" in src, src
