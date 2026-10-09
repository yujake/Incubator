# -*- coding: utf-8 -*-
"""S1r「并干净」那一笔的预检清单：删 `concepts` 表会碰到哪些地方（机器可核）。

## 为什么要有这一条判据

落刀那一笔（`SCHEMA_VERSION 1→2` + `TABLES` 删 `concepts` + 读侧统一新标准）实测会一次
碰到 25 个源文件 + 16 个测试文件（2026-10-09 现算，命令见 `temp/_s1r_flip_inventory.py`）。
漏掉任何一处都不会在那一刻报错：读老表的地方拿到的是一条受控错（或更坏 ——
经视图拿到空列表），写老表的地方会静默失败。而"我记得要改哪些"不是判据。

所以把清单登记在案：任何新增/删除的读点、写点或事务声明，都必须在同一个提交里改这张表。
于是搬运过程单调收缩、可核对，也不会出现"改着改着漏了一处"这种事。

## 四个模式（与 `temp/_s1r_flip_inventory.py` 逐字相同）

| 键 | 正则 | 意思 |
|---|---|---|
| `read_store` | `store.rows("concepts")` | 无锁快照读 |
| `read_tx` | `tx.rows("concepts")` | 事务内读（写侧搬运那一批的对象） |
| `write` | `upsert("concepts", …)` | 写老表 |
| `tx_declare` | `.tx(… "concepts" …)` | 事务声明（锁与提交面） |

## 落刀完成时这张表该长什么样（目标，写在这里免得只靠记忆）

- `read_store` / `read_tx` / `write` / `tx_declare` 在 `src/agentflow` 里全部为 0，
  例外只有两处必须保留的：`conceptrows.py`（过渡层的 `LEGACY_TABLE` 常量，
  读 v1 数据用）与 `migrate_concepts.py` / `store.py`（迁移内核与 v1→v2 兼容那一笔）；
- `tests/` 里的条目按两类处理：测概念语义的改读新标准；拿 `concepts` 当通用被测表的
  （`test_store_alloc_guard` / `test_store_concurrency` / `test_store_counters_commit` /
  `test_store_delete_events` / `test_tx_mark_dirty` / `test_rebuild`）换一张表或改成
  "表已删"的负控。
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]

PATTERNS: dict[str, re.Pattern[str]] = {
    "read_store": re.compile(r"store\.rows\(\s*['\"]concepts['\"]"),
    "read_tx": re.compile(r"tx\.rows\(\s*['\"]concepts['\"]"),
    "write": re.compile(r"upsert\(\s*['\"]concepts['\"]"),
    "tx_declare": re.compile(r"\.tx\([^)]*['\"]concepts['\"]"),
}

#: 登记清单：`{模式: {相对路径: 处数}}`（相对 `agentflow/`，与现算逐字一致）。
INVENTORY: dict[str, dict[str, int]] = {
    "read_store": {
        "src/agentflow/conceptrows.py": 1,      # 过渡层自己读老表（保留到落刀）
        "tests/test_agent_b.py": 3,
        "tests/test_agent_b_gates.py": 5,
        "tests/test_demo_end_to_end.py": 1,
        "tests/test_download_handoff.py": 2,
        "tests/test_store_alloc_guard.py": 3,
        "tests/test_store_concurrency.py": 1,
        "tests/test_tx_mark_dirty.py": 3,
    },
    "read_tx": {
        "src/agentflow/agent_b/core.py": 3,     # `_apply_merge`：改老表原始行（落刀时改新标准）
        "src/agentflow/agent_b/resolve_structural_duplicate.py": 1,
        "src/agentflow/agent_b/run_once.py": 1,
        "src/agentflow/cli.py": 1,              # `repair --related`（落刀时整体退役）
        "src/agentflow/conceptrows.py": 2,      # 过渡层：一处代码 + 一处 docstring 里点名这一格
        "tests/test_tx_mark_dirty.py": 3,
        "tests/test_the_mirror_is_complete.py": 1,   # docstring 里点名这一格（不是读点）
    },
    "write": {
        "src/agentflow/agent_b/core.py": 4,     # 其中 1 处是自检夹具
        "src/agentflow/agent_b/run_once.py": 3,
        "src/agentflow/agent_c/__main__.py": 4,  # 自检夹具
        "src/agentflow/agent_d/core.py": 1,      # 夹具
        "src/agentflow/agent_h/core.py": 2,      # 自检夹具（H 的权限面没被破：它在 selftest 里）
        "src/agentflow/cli.py": 1,
        "src/agentflow/faculty_checks.py": 2,    # 官能探针夹具
        "src/agentflow/pipeline.py": 1,          # 夹具
        "src/agentflow/tools/trace_tools.py": 1,
        "tests/conftest.py": 1,
        "tests/test_agent_b_gates.py": 2,
        "tests/test_agent_c_service.py": 1,
        "tests/test_coverage_agent_b.py": 2,
        "tests/test_fc05_contract.py": 1,
        "tests/test_judges.py": 2,
        "tests/test_rebuild.py": 1,
        "tests/test_release_acceptance_wiring.py": 1,
        "tests/test_review_acceptance.py": 1,
        "tests/test_store_alloc_guard.py": 7,
        "tests/test_store_concurrency.py": 7,
        "tests/test_store_counters_commit.py": 1,
        "tests/test_store_delete_events.py": 3,
        "tests/test_tx_mark_dirty.py": 1,
        "tests/test_verify_snapshot.py": 1,
        "tests/test_the_mirror_is_complete.py": 1,   # 负控：绕过镜像直接写老表
    },
    "tx_declare": {
        "src/agentflow/agent_b/core.py": 1,
        "src/agentflow/agent_b/resolve_structural_duplicate.py": 1,
        "src/agentflow/agent_b/run_once.py": 1,
        "src/agentflow/agent_c/__main__.py": 4,
        "src/agentflow/agent_d/core.py": 1,
        "src/agentflow/agent_h/core.py": 1,
        "src/agentflow/cli.py": 1,
        "src/agentflow/faculty_checks.py": 1,
        "src/agentflow/pipeline.py": 1,
        "src/agentflow/tools/trace_tools.py": 1,
        "tests/conftest.py": 1,
        "tests/test_agent_b_gates.py": 2,
        "tests/test_agent_c_service.py": 1,
        "tests/test_coverage_agent_b.py": 2,
        "tests/test_fc05_contract.py": 1,
        "tests/test_judges.py": 2,
        "tests/test_rebuild.py": 1,
        "tests/test_release_acceptance_wiring.py": 1,
        "tests/test_review_acceptance.py": 1,
        "tests/test_store_alloc_guard.py": 9,
        "tests/test_store_concurrency.py": 8,
        "tests/test_store_counters_commit.py": 3,
        "tests/test_store_delete_events.py": 6,
        "tests/test_the_concept_view_during_the_merge.py": 1,
        "tests/test_tx_mark_dirty.py": 5,
        "tests/test_verify_snapshot.py": 1,
        "tests/test_the_mirror_is_complete.py": 1,   # 负控：直接写老表那一笔
    },
}

#: 落刀之后必须保留提到 `concepts` 的三个源文件（过渡层与迁移内核）。
KEEP_AFTER_FLIP = ("src/agentflow/conceptrows.py", "src/agentflow/migrate_concepts.py",
                   "src/agentflow/store.py", "src/agentflow/schema.py")


def _scan() -> dict[str, dict[str, int]]:
    """现算（与生成器同一套正则）：`{模式: {相对路径: 处数}}`，处数为 0 的不列。

    本文件自己跳过自己：清单里的正则源码本身含 `["']concepts["']`，不跳的话
    这条判据会把自己数成一个读点（而且每次改清单都要跟着改自己一遍）。
    """
    out: dict[str, dict[str, int]] = {k: {} for k in PATTERNS}
    for root in ("src/agentflow", "tests"):
        for path in sorted((REPO / root).rglob("*.py")):
            if path.name == pathlib.Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            for key, rx in PATTERNS.items():
                n = len(rx.findall(text))
                if n:
                    out[key][rel] = n
    return out


def test_the_flip_inventory_matches_the_tree():
    """登记清单必须与盘上逐文件逐处一致（新增/删除读点写点 ⇒ 同一提交里改这张表）。"""
    live = _scan()
    for key in PATTERNS:
        assert live[key] == INVENTORY[key], (
            f"{key} 的登记清单与盘上不一致：\n  盘上多出："
            f"{ {k: v for k, v in live[key].items() if INVENTORY[key].get(k) != v} }\n"
            f"  登记里多出："
            f"{ {k: v for k, v in INVENTORY[key].items() if live[key].get(k) != v} }")


def test_the_inventory_is_not_vacuous():
    """反真空：四个模式都必须真的扫到东西（否则"清单一致"是在比两个空集）。

    落刀之后这一条会故意变红 —— 那时要把它改成"只剩 `KEEP_AFTER_FLIP` 那几处"
    （`test_the_inventory_shrinks_to_the_keep_list` 就是那一档的写法，先留在这里）。
    """
    live = _scan()
    assert all(live[key] for key in PATTERNS), live
    for rel in KEEP_AFTER_FLIP:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "concepts" in text, f"{rel} 是落刀后必须保留提到 concepts 的文件之一"
