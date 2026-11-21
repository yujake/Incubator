# -*- coding: utf-8 -*-
"""工作区事实必须同时看见 `source/` 与 `library/` 里"盘上有、表里没有"的本地材料。

## 为什么补这个文件（FACTSFIX，2026-11-21）

业主下一趟的场景：`--seed-literature` 把 25 份种子 PDF 投进 `library/`，
`data/literature.json` 仍是 0 行。改前 `_pending_local_materials` 只扫 `source/`
⇒ A/M 的提示词里一个字都没有"library/ 有未入编的文献"，A 只能被 M/任务点名，
或者自己 `fs.list` 一下才想到去判收。

## 守四件事（每件都带反真空）

a. `library/` 有 3 份、表 0 行 ⇒ 渲染产物里出现 "library/ 3 份未入编" 这类读数
   （改前：不出现）；
b. `library/` 3 份、已入编 2 ⇒ 报未入编 1（数对，不是把已入编的也算成未入编）；
c. 台账读不到 ⇒ 这一段沉默（不写 "0 份未入编"）；台账在盘上但读不出来 ⇒ 记"没查成"；
d. 反真空：把扫描打桩回只扫 `source/` ⇒ a 的那条检查必红。

另有三条边界：目录不存在 ⇒ 该目录那一条不写；两个目录都不存在 ⇒ 整段沉默；
两个目录各自独立计数（`source` 的已入编不会抵掉 `library` 的未入编）。
"""

from __future__ import annotations

import json
import pathlib
import shutil
from typing import Any

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry


def _workspace(tmp_path: pathlib.Path, *, library: int = 0,
               source: int = 0) -> pathlib.Path:
    """建一个真工作区（`Store.init` 会落空表与 `library/`），再往两个目录里放文件。"""
    ws = tmp_path / "ws"
    Store(ws).init()
    if source:
        (ws / "source").mkdir(parents=True, exist_ok=True)
        for i in range(source):
            (ws / "source" / f"src-{i}.pdf").write_bytes(b"%PDF-1.4 probe")
    for i in range(library):
        (ws / "library" / f"seed-{i}.pdf").write_bytes(b"%PDF-1.4 probe")
    return ws


def _register(ws: pathlib.Path, names: list[str]) -> None:
    """按 `Store` 的表文档形状登记几行（判据只读 `path` / `title`，不碰落库路径）。"""
    doc = {
        "schema_version": S.SCHEMA_VERSION,
        "rows": [
            {"lit_id": f"lit-{i + 1}", "title": f"Registered {name}",
             "path": f"library/{name}"}
            for i, name in enumerate(names)
        ],
    }
    (ws / "data" / "literature.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _prompt(role: str, ws: pathlib.Path) -> str:
    """真渲染一份提示词（与生产同一个入口、同一份工作区事实）。"""
    reg = build_registry(store=Store(ws), workspace_root=ws).registry
    return AP.system_prompt(role, registry=reg, workspace_root=str(ws))


def _materials_block(prompt: str) -> str:
    """从渲染产物里取出本地材料那两行（第一行读数、第二行判收链口径）。

    只认「工作区事实」那一段里的 bullet：M 的 policy 里也有一句 "未收编的本地材料"
    （它是在说这一格怎么读），拿整份提示词找会把它误当成本地材料读数。
    """
    lines = prompt.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("工作区事实")), None)
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("- "):
            if "未收编的本地材料" in line or "没查成" in line or "判收链" in line:
                out.append(line.strip())
            continue
        if line.strip() == "":
            # 工作区事实与本地材料是两个段（渲染时中间隔一个空行）。
            if out:
                break
            continue
        break
    return "\n".join(out)


def _library_three_problem(prompt: str) -> str:
    """判据 a 的本体：渲染产物里必须有 "library/ 3 份未入编" 这条读数（空串 = 绿）。"""
    block = _materials_block(prompt)
    if "`library/` 3 份未入编" not in block:
        return (f"渲染产物里没有 `library/` 3 份未入编 这条读数 ⇒ "
                f"下一趟 A/M 看不见 library/ 里那批未判收的种子。这一段是：{block!r}")
    return ""


# ---------------------------------------------------------------- a


def test_a_library_files_are_visible_even_with_zero_table_rows(
        tmp_path: pathlib.Path) -> None:
    """a：`library/` 3 份、literature 0 行 ⇒ 渲染产物里出现 "library/ 3 份未入编"。"""
    ws = _workspace(tmp_path, library=3)
    prompt = _prompt("M", ws)
    assert _library_three_problem(prompt) == ""
    block = _materials_block(prompt)
    assert "盘上共 3 份文件" in block, block
    assert "已入编 0 份" in block, block
    assert "seed-0.pdf" in block, block
    # 事实段必须把"接下来怎么走"写在同一个可见面里，而不是只报一个数。
    assert "判收链" in block and "不许当已入库" in block, block
    # 工具名只给 A（它是唯一拿得到 lit.* / search.ingest_local 的角色）；别的角色只
    # 读"由 A 走判收链"—— 否则它们的提示词会点名自己调不到的工具。
    a_block = _materials_block(_prompt("A", ws))
    assert "search.ingest_local" in a_block and "dry_run=True" in a_block, a_block
    assert "lit.admit_all" in a_block, a_block
    assert "search.ingest_local" not in block, block
    # 目录不存在 ⇒ 这一条不写（选"不写"，理由见报告）。
    assert "`source/`" not in block, block


def test_a_the_library_reading_reaches_a_and_m(tmp_path: pathlib.Path) -> None:
    """a（受众）：这一格是工作区事实，不是 M 专属 —— A 也读得到（它才是判收的那个）。"""
    ws = _workspace(tmp_path, library=3)
    for role in ("A", "M"):
        assert _library_three_problem(_prompt(role, ws)) == "", role


# ---------------------------------------------------------------- b


def test_b_two_of_three_registered_reports_one_pending(tmp_path: pathlib.Path) -> None:
    """b：`library/` 3 份、已入编 2 ⇒ 报未入编 1（三个数都对得上）。"""
    ws = _workspace(tmp_path, library=3)
    _register(ws, ["seed-0.pdf", "seed-1.pdf"])
    block = _materials_block(_prompt("M", ws))
    assert "`library/` 1 份未入编" in block, block
    assert "盘上共 3 份文件" in block, block
    assert "已入编 2 份" in block, block
    assert "seed-2.pdf" in block, block
    # 已入编的两份不许出现在"未入编"的举例里（否则读数自相矛盾）。
    assert "seed-0.pdf" not in block and "seed-1.pdf" not in block, block


# ---------------------------------------------------------------- c


def test_c_a_missing_ledger_is_silent_not_zero(tmp_path: pathlib.Path) -> None:
    """c：`data/literature.json` 不在盘上 ⇒ 这一段沉默，不写 "0 份未入编"。"""
    ws = _workspace(tmp_path, library=3)
    (ws / "data" / "literature.json").unlink()
    prompt = _prompt("M", ws)
    assert _materials_block(prompt) == "", _materials_block(prompt)
    assert "份未入编" not in prompt, "读不到台账却报了读数（把'没读成'写成了'都收编了'）"
    assert "0 份未入编" not in prompt


def test_c_a_present_but_corrupt_ledger_says_not_checked(tmp_path: pathlib.Path) -> None:
    """c（第二档）：台账在盘上、目录里有文件、但表读不出来 ⇒ 记"没查成"。

    这一档与"台账不在盘上"必须分开：前者是"没查成"，后者是"没有这一格"；
    两者都不许折成"没有未入编"。
    """
    ws = _workspace(tmp_path, library=3)
    (ws / "data" / "literature.json").write_text("{not json", encoding="utf-8")
    block = _materials_block(_prompt("M", ws))
    assert "没查成" in block, block
    assert "literature.json" in block, block
    assert "「没有未入编」" in block, block
    assert "0 份未入编" not in block, block


def test_c_an_empty_directory_with_a_corrupt_ledger_stays_silent(
        tmp_path: pathlib.Path) -> None:
    """c（边界）：目录里没有文件时，坏台账没有"未入编"可说 —— 仍然沉默。"""
    ws = _workspace(tmp_path)
    (ws / "data" / "literature.json").write_text("{not json", encoding="utf-8")
    assert _materials_block(_prompt("M", ws)) == ""


# ---------------------------------------------------------------- 边界 / 25 份种子


def test_the_two_directories_are_counted_independently(tmp_path: pathlib.Path) -> None:
    """边界：`source/` 的已入编不能抵掉 `library/` 的未入编，反过来也一样。"""
    ws = _workspace(tmp_path, library=2, source=2)
    _register(ws, ["seed-0.pdf", "src-0.pdf"])
    block = _materials_block(_prompt("M", ws))
    assert "`library/` 1 份未入编" in block, block
    assert "`source/` 1 份未入编" in block, block
    assert "盘上共 2 份文件" in block, block
    assert "已入编 1 份" in block, block


def test_only_the_directory_that_exists_is_written(tmp_path: pathlib.Path) -> None:
    """边界：没有 `source/` 就不写 `source/` 那一条（不是写 "source/ 0 份"）。"""
    ws = _workspace(tmp_path, library=1)
    block = _materials_block(_prompt("M", ws))
    assert "`library/` 1 份未入编" in block, block
    assert "`source/`" not in block, block


def test_no_directory_at_all_keeps_the_section_silent(tmp_path: pathlib.Path) -> None:
    """边界：两个目录都不存在 ⇒ 整段沉默（没有可报的本地材料）。"""
    ws = _workspace(tmp_path)
    shutil.rmtree(ws / "library")
    assert not (ws / "source").exists()
    assert _materials_block(_prompt("M", ws)) == ""


def test_the_seed_scenario_reads_as_twenty_five_pending(tmp_path: pathlib.Path) -> None:
    """下一趟的预期读数：25 份种子投进 `library/`、表 0 行 ⇒ "library/ 25 份未入编"。"""
    ws = _workspace(tmp_path, library=25)
    block = _materials_block(_prompt("M", ws))
    assert "`library/` 25 份未入编" in block, block
    assert "盘上共 25 份文件" in block, block
    assert "已入编 0 份" in block, block


# ---------------------------------------------------------------- d 反真空


def _source_only_scanner(root: str, role: str = "") -> str:
    """改前那一份实现（只扫 `source/`），原样搬进来当反真空的桩。"""
    root = str(root or "").strip()
    if not root:
        return ""
    base = pathlib.Path(root)
    src = base / "source"
    if not src.is_dir():
        return ""
    known: set[str] = set()
    try:
        payload = json.loads((base / "data" / "literature.json").read_text(encoding="utf-8"))
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        for row in rows or []:
            for key in ("path", "title"):
                val = str((row or {}).get(key) or "").strip()
                if val:
                    known.add(pathlib.Path(val).name.lower())
                    known.add(val.lower())
    except Exception:  # noqa: BLE001 - 读不到就是读不到（不说）
        return ""
    try:
        files = sorted(p.name for p in src.iterdir() if p.is_file())[:50]
    except OSError:
        return ""
    pending = [n for n in files if n.lower() not in known]
    if not pending:
        return ""
    head = "、".join(pending[:3]) + ("…" if len(pending) > 3 else "")
    return (f"- **未收编的本地材料**：`source/` 下有 {len(pending)} 份还没进 `literature`"
            f"（{head}）—— 派 `A.ingest_local`（参数 `books_dir=\"source\"`）收编；"
            "它按内容 sha256 幂等，**重复收不会多出行**")


def test_d_anti_vacuum_a_source_only_scanner_loses_the_library_reading(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把扫描打桩回只扫 `source/` ⇒ a 的那条检查必红（先证明它原本是绿的）。"""
    ws = _workspace(tmp_path, library=3)
    assert _library_three_problem(_prompt("M", ws)) == "", "正控先绿，反真空才有意义"

    monkeypatch.setattr(AP, "_pending_local_materials", _source_only_scanner)
    problem = _library_three_problem(_prompt("M", ws))
    assert problem, ("打桩回只扫 source/ 之后 a 仍然绿 ⇒ 这条判据没有牙"
                     "（它没有在读 library/ 那一条）")
    block = _materials_block(_prompt("M", ws))
    assert "`library/`" not in block, block
