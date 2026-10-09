# -*- coding: utf-8 -*-
"""S1r「并干净」的清单：还有哪些地方字面上在碰老表 `concepts`（机器可核）。

## 为什么要有这一条判据

落刀那一笔（`SCHEMA_VERSION 1→2` + `TABLES` 删 `concepts` + 读侧统一新标准）会一次碰到
几十处读点、写点与事务声明。漏掉任何一处都不会在那一刻报错：读老表的地方拿到的是一条
受控错（或更坏 —— 经视图拿到空列表），写老表的地方会静默失败。而"我记得要改哪些"不是判据。

所以把清单登记在案：任何新增/删除的读点、写点或事务声明，都必须在同一个提交里改这张表。
于是搬运过程单调收缩、可核对，也不会出现"改着改着漏了一处"这种事。

清单里的数字不许手改：重排用
`python -B D:\\Incubator\\temp\\_s1r_regen_registry.py`（它按盘上现算重排，并逐条保留
登记理由），改完跑本文件自检。手删容易删错一格（同一文件可能在两节里都有、值又相同，
删一次只动了一节）。

## 四个模式

| 键 | 正则 | 意思 |
|---|---|---|
| `read_store` | `store.rows("concepts")` | 无锁快照读 |
| `read_tx` | `tx.rows("concepts")` | 事务内读（写侧搬运那一批的对象） |
| `write` | `upsert("concepts", …)` | 写老表 |
| `tx_declare` | `.tx(… "concepts" …)` | 事务声明（锁与提交面） |

## 判据的口径（两件事必须一起说清，否则这张表会被读错）

1. 它数的是文本里字面上的那四种调用形态，不是"语义上碰老表的地方"：
   路径里写的 `"concepts.json"`、走常量 `CR.LEGACY_TABLE` 的调用、以及注释里引用
   这些形态，都会（或都不会）被数进来。所以 `KEEP_AFTER_FLIP` 那几处必须保留的源文件
   才需要单独列出来断"它们还提到 concepts" —— 光看这张表看不出它们；
2. 于是这张表的正确读法是"还剩多少处字面触点"，而不是"老表还有没有被碰"。
   落刀已经落了（`SCHEMA_VERSION=2`），剩下的这些是读侧搬运的剩余工作量：
   收缩到只剩 `KEEP_AFTER_FLIP` 那几处（外加迁移内核与 v1→v2 兼容那一笔）就算搬干净。
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
        "src/agentflow/agent_d/_support.py": 1,
        "src/agentflow/conceptrows.py": 1,  # 过渡层自己（落刀后保留）
        "src/agentflow/schema.py": 1,
        "tests/test_agent_b.py": 1,
    },
    "read_tx": {
        "src/agentflow/agent_b/core.py": 1,  # `_apply_merge`：事务内改老表原始行
        "src/agentflow/conceptrows.py": 2,  # 过渡层自己（落刀后保留）
        "tests/test_agent_b_gates.py": 1,
        "tests/test_agent_c_service.py": 1,
        "tests/test_the_mirror_is_complete.py": 1,  # 负控/清单引用
    },
    "write": {
        "tests/test_the_mirror_is_complete.py": 1,  # 负控/清单引用
    },
    "tx_declare": {
        "tests/test_the_mirror_is_complete.py": 1,  # 负控/清单引用
    },
}

#: 落刀之后必须保留提到 `concepts` 的四个源文件（过渡层 + 迁移内核 + v1→v2 兼容那一笔）。
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

    为什么要单列：`test_the_flip_inventory_matches_the_tree` 判的是"登记 == 盘上"，
    而四个空清单与四个空盘上扫描同样相等 —— 于是整个 `_scan` 坏掉（正则写错、
    目录找不到、文件被排除）时，那张表会以"全部一致"的形式亮绿。这里钉住每一节至少
    扫到一处，于是"扫不到东西"与"扫到了、结果干净"分得开。

    顺带钉住 `KEEP_AFTER_FLIP`：那四个文件不靠正则命中（它们走常量
    `CR.LEGACY_TABLE` / 只写路径名），所以它们不在上面那张表里；"它们还提到 concepts"
    只能单独判。等这张表收缩到只剩它们时，上面那个 `all(...)` 会红 ——
    那时把它换成"只剩 `KEEP_AFTER_FLIP` 那几处"的写法（那是下一次搬运的收尾动作，
    不是把这一条删掉）。
    """
    live = _scan()
    assert all(live[key] for key in PATTERNS), live
    for rel in KEEP_AFTER_FLIP:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "concepts" in text, f"{rel} 是落刀后必须保留提到 concepts 的文件之一"
