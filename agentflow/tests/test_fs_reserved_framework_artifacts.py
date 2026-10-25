# -*- coding: utf-8 -*-
"""保留路径：F 的证明手稿 / D 的研究手稿只许经框架动作生成（不许手写）。

## 改前是什么形态（真机读数，业主已看过）

```text
F 用 fs.write 直接写了 reports/f-proof-sylow1.md（自由格式、无四列依赖表、无洗稿元信息）
D 手写 reports/RESEARCH.md（没有携带单）
⇒ 框架的「渲染手稿 / 秘书洗稿 / D 携带」整条链没有入口
⇒ B 只登记 1 条 conjecture、dependencies 0 行
```

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a F 写 `reports/f-proof-x.md` | 受控拒绝 `reserved_framework_artifact`，盘上零写入 | 改前写得进去 |
| b D 写 `reports/RESEARCH.md` / `reports/0001-research.md` | 同上 | 改前写得进去 |
| c F 写 `notes/x.md`（正控） | 放行 —— 保留表不许扩成"谁都不许写文件" | —— |
| d 反真空 | 把保留表打桩成空 ⇒ a/b 必红（于是 a/b 的绿来自那张表） | —— |
| e `fs.edit` 同一条闸 | 改正文等于绕过同一条保留表 ⇒ 也拒（且盘上那一份逐字未动） | 改前改得进去 |
| m-a M 写 `reports/f-proof-x.md` | 拒（业主 2026-10-27 裁定：主控更不该绕过框架） | 改前写得进去（实测 `start --mode research` 那一趟就是 M 写的） |
| m-b M 写 `reports/RESEARCH.md` | 拒（同上） | 改前写得进去 |
| m-c M 写 `notes/m-plan.md` / `reports/m-review.md`（正控） | 放行 —— 别把主控的正常产出也堵了 | —— |
| m-d 反真空 | 把表里 M 那三行摘掉 ⇒ m-a/m-b 必红 | —— |

表上三个角色各有各的理由（F 写内容 / D 交研究稿 / M 是主控，三类都不许手写框架产物）；
G/L 的排版产物与 M 的其它报告不在表上（c、m-c 与"G 写 reports/ 下的 `f-proof-*.md`
放行"一起钉住"别扩大"）。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import fs_tools as FT

#: 逐字要求的那句拒信（前半句）。
MESSAGE = "这一份是框架渲染的产物（证明手稿 / 研究手稿），不许手写"
#: 受控码。
KIND = "reserved_framework_artifact"


def _ws(path: pathlib.Path):
    root = path / "ws"
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry
    return root, reg


def _call(reg, role: str, tool: str, **params):
    """按某个角色的身份调一次工具（"我是谁"由 `calling_as` 挂上，与真机同一条路）。"""
    with calling_as("t-probe", role):
        return reg.call(tool, role=role, **params)


def test_a_f_cannot_hand_write_his_proof_manuscript(tmp_path: pathlib.Path) -> None:
    """a 判据：F 用 `fs.write` 写 `reports/f-proof-*.md` ⇒ 拒、零写入。

    两个时刻都不许写：登记前的 `f-proof-plan-<plan>.md` 与登记后的 `f-proof-<号>.md`
    （它们是同一件东西的两个名字）。
    """
    root, reg = _ws(tmp_path)
    for rel in ("reports/f-proof-x.md", "reports/f-proof-plan-000000.md"):
        res = _call(reg, "F", "fs.write", path=rel, content="手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert MESSAGE in str(res.error or ""), (rel, res.error)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


def test_b_d_cannot_hand_write_his_research_manuscript(tmp_path: pathlib.Path) -> None:
    """b 判据：D 写研究报告那几条命名 ⇒ 拒（`RESEARCH.md` 与 `*-research.md` 两种都在表上）。"""
    root, reg = _ws(tmp_path)
    for rel in ("reports/RESEARCH.md", "reports/000001-research.md"):
        res = _call(reg, "D", "fs.write", path=rel, content="手写的研究报告")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


def test_c_other_paths_are_not_touched(tmp_path: pathlib.Path) -> None:
    """c 判据（正控）：保留表不许扩成"谁都不许写文件"。

    三件事一起钉：F 写 `notes/x.md` 放行；D 写别处的报告放行；
    G/L（排版产物）写 `reports/` 下同样名字的文件也放行 —— 表只对表上那三行角色负责。
    """
    root, reg = _ws(tmp_path)
    res = _call(reg, "F", "fs.write", path="notes/x.md", content="自由笔记")
    assert res.ok is True, res
    assert (root / "notes" / "x.md").is_file()

    res = _call(reg, "D", "fs.write", path="notes/d-scratch.md", content="草稿")
    assert res.ok is True, res

    res = _call(reg, "G", "fs.write", path="reports/f-proof-g.md", content="G 的排版产物")
    assert res.ok is True, ("G 的排版产物被误伤了", res)

    res = _call(reg, "L", "fs.write", path="reports/RESEARCH.md", content="L 的排版产物")
    assert res.ok is True, ("L 的排版产物被误伤了", res)


def test_m_a_m_cannot_hand_write_the_proof_manuscript(tmp_path: pathlib.Path) -> None:
    """m-a 判据：M 写 `reports/f-proof-*.md` ⇒ 拒、零写入。

    业主 2026-10-27 裁定逐字：「把 M 也纳入保留表 …… 它是主控，更不该绕过框架」。
    改前红：实测 `start --mode research` 那一趟（M→F 不是允许边）就是 M 自己用
    `fs.write` 把 `reports/f-proof-cli.md` 写进了盘 —— 这一条判据把它关掉。
    """
    root, reg = _ws(tmp_path)
    for rel in ("reports/f-proof-x.md", "reports/f-proof-plan-000000.md"):
        res = _call(reg, "M", "fs.write", path=rel, content="主控手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert res.meta.get("role") == "M", (rel, res.meta)
        assert MESSAGE in str(res.error or ""), (rel, res.error)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


def test_m_b_m_cannot_hand_write_the_research_manuscript(tmp_path: pathlib.Path) -> None:
    """m-b 判据：M 写研究手稿那几条命名 ⇒ 拒（与 D 同一张表、同一个受控码）。"""
    root, reg = _ws(tmp_path)
    for rel in ("reports/RESEARCH.md", "reports/000001-research.md"):
        res = _call(reg, "M", "fs.write", path=rel, content="主控手写的研究报告")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"
    # `fs.edit` 也是同一条闸（能改正文就等于绕过它）
    rel = "reports/RESEARCH.md"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / rel).write_text("# 原件\n\n原来的正文\n", encoding="utf-8")
    res = _call(reg, "M", "fs.edit", path=rel, old_string="原来的正文", new_string="改过的")
    assert res.ok is False and res.meta.get("kind") == KIND, res
    assert (root / rel).read_text(encoding="utf-8") == "# 原件\n\n原来的正文\n"


def test_m_c_m_other_outputs_are_not_touched(tmp_path: pathlib.Path) -> None:
    """m-c 判据（正控）：别把主控的正常产出也堵了。

    M 的日常产出（计划、评审、汇总）不在保留表上：`notes/m-plan.md` 与
    `reports/m-review.md` 都必须写得进去 —— 表只认"证明手稿 / 研究手稿"两类文件名。
    """
    root, reg = _ws(tmp_path)
    res = _call(reg, "M", "fs.write", path="notes/m-plan.md", content="主控的计划")
    assert res.ok is True, ("M 的正常产出被误伤了", res)
    assert (root / "notes" / "m-plan.md").is_file()

    res = _call(reg, "M", "fs.write", path="reports/m-review.md", content="主控的评审摘要")
    assert res.ok is True, ("M 写 reports/ 下的其它报告被误伤了", res)
    assert (root / "reports" / "m-review.md").is_file()

    res = _call(reg, "M", "fs.write", path="reports/summary.md", content="主控的汇总")
    assert res.ok is True, ("M 写 reports/summary.md 被误伤了", res)


def test_m_d_dropping_the_m_rows_turns_m_a_and_m_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """m-d 判据（反真空）：把表里 M 那三行摘掉 ⇒ m-a/m-b 必红。

    打桩点还是那张表（只留 F/D 那三行 = 裁定前的状态）：同一条路径必须写得进去 ——
    于是 "M 被拒绝" 这件事的来源是表上 M 那三行，而不是别处顺手写的判断。
    """
    only_fd = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE if row[0] in ("F", "D"))
    assert only_fd, "表里连 F/D 都没有 ⇒ 这条反真空打桩点在核一个空表"
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", only_fd)
    root, reg = _ws(tmp_path)
    res = _call(reg, "M", "fs.write", path="reports/f-proof-x.md", content="主控手写稿")
    assert res.ok is True, ("M 那几行被摘掉了却还是拒绝 ⇒ m-a 的绿不来自那几行", res)
    res = _call(reg, "M", "fs.write", path="reports/RESEARCH.md", content="主控手写报告")
    assert res.ok is True, ("M 那几行被摘掉了却还是拒绝 ⇒ m-b 的绿不来自那几行", res)


def test_d_stubbing_the_reserved_table_out_turns_a_and_b_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """d 判据（反真空）：把保留表打桩成空 ⇒ a/b 必红。

    打桩点就是那张表（`fs_tools.RESERVED_ARTIFACT_TABLE`）：清空它之后同一条路径
    必须写得进去 —— 于是"保留路径被拒绝"这件事的来源是那张表，而不是别处顺手写的
    某个判断。
    """
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", ())
    root, reg = _ws(tmp_path)
    res = _call(reg, "F", "fs.write", path="reports/f-proof-x.md", content="手写稿")
    assert res.ok is True, ("表被清空了却还是拒绝 ⇒ a 的绿不来自那张表", res)
    res = _call(reg, "D", "fs.write", path="reports/RESEARCH.md", content="手写报告")
    assert res.ok is True, ("表被清空了却还是拒绝 ⇒ b 的绿不来自那张表", res)


def test_e_fs_edit_is_the_same_gate(tmp_path: pathlib.Path) -> None:
    """e 判据：`fs.edit` 也是同一条闸（能改正文就等于能绕过保留表），且零改动。"""
    root, reg = _ws(tmp_path)
    rel = "reports/f-proof-y.md"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / rel).write_text("# 手写稿\n\n原来的正文\n", encoding="utf-8")
    res = _call(reg, "F", "fs.edit", path=rel,
                old_string="原来的正文", new_string="被改过的正文")
    assert res.ok is False, res
    assert res.meta.get("kind") == KIND, res.meta
    assert (root / rel).read_text(encoding="utf-8") == "# 手写稿\n\n原来的正文\n", (
        "被拒了却改了盘上那一份")


def test_the_table_names_match_the_one_definition(tmp_path: pathlib.Path) -> None:
    """漂移判据：保留表里的名字必须与 `depsection` 那套约定同源（不是两份字面量）。

    `depsection` 是手稿路径的唯一权威（`MANUSCRIPT_STMT_PREFIX` / `D_REPORT_NAMES` /
    `D_WORKING_SUFFIX`）：这里一旦改名而保留表没跟，2 那条闸就会对新名字静默失效 ——
    而那种失效的形态是"写得进去、没人报错"。
    """
    rules = " ".join(rule for _role, rule in FT.RESERVED_ARTIFACT_TABLE)
    assert DS.MANUSCRIPT_STMT_PREFIX in rules, rules
    assert DS.MANUSCRIPT_DIR == FT._RESERVED_DIR, (DS.MANUSCRIPT_DIR, FT._RESERVED_DIR)
    assert DS.D_REPORT_NAMES[0].casefold() in rules.casefold(), rules
    assert DS.D_WORKING_SUFFIX in rules, rules
