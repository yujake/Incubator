# -*- coding: utf-8 -*-
"""判据：收工门八格只有一台计算机器（网页与命令行取的是同一个函数）。

## 现场（业主 2026-11-14：「做好多端口径对齐」）

同一份工作区的收工门读数有两个出口：

- 命令行：`agentflow stats gates` 走 `readouts.gates_readout`（`agentflow inspect stats` 同名）；
- 网页：`/api/package`（以及 `/api/acceptance`）走 `webui/readers._closing_block`。

改前这两个出口各自写了一遍同一个循环（遍历 `closing.DEFAULT_CHECKS`、把词表外的
状态折成 `unknown`、逐档累加）。“同一份 `rep.status` 数出两个 counts”这件事因此
没有任何结构保证：一处改了归一化规则，另一处照旧，而两边都“对”。

## 这一组钉住的两件事

| 判据 | 查什么 | 反真空 |
|---|---|---|
| a | 同一份工作区、同一批入参 ⇒ 网页的 `closing.gates` 与 `readouts.gates_readout` 的 `cells` / `counts` / `machine_pass` 逐字相等 | —— |
| b | 两个出口都真的调用 `readouts.gate_cells`：把它打桩成一份标记读数 ⇒ 两边同时变成那份标记 | 网页自己又数一遍 ⇒ 只有命令行变、这条红 |

b 是这条判据的存在理由：只做 a 的话，两个入口碰巧数得一样也能过 —— 而“碰巧一样”
正是下一次分叉的来源（P16 的真空通过）。

## 已知未对齐（待业主裁，不是这条判据放过的）

两个出口的缺省入参不同，于是同一份工作区在两边给出两套读数（2026-11-14 实测，
空工作区：命令行 `{pass:2, fail:1, unknown:4, na:1}`；网页 `{pass:5, fail:1, unknown:1, na:1}`）：

- 命令行（`cmd_closing` / `stats gates`）：`project_dir=""`、`report_path=""`
  ⇒ `paper` / `report_shape` / `acceptance` / `artifact_ledger` 四格记 `unknown`
  （“没给项目根”是没查成，不是通过 —— 退出码因此是 2）；
- 网页（`package_face` / `acceptance_face`）：缺省取工作区根 `.` 与
  `out/review/REPORT.md` ⇒ 同一批格子按真实落点判出 `pass`。

两边各自都有理由（一边要 fail-closed，一边要页面开箱有读数），所以这一格是
口径裁定题，不是本判据能单方面改的：改哪一边都会改 `agentflow closing` 的退出码
语义。本判据只要求“入参相同时必须逐字相等”，把缺省那一格留给裁定；
登记在这里是为了让它可被看见，而不是被 a/b 两条的绿掩盖。
"""
from __future__ import annotations

import pathlib

from agentflow import readouts as RD
from agentflow.store import Store
from agentflow.webui import readers as R

#: 两个出口都认的同一批入参（缺省值刻意不在这里：见文件头“已知未对齐”）。
PROJECT_DIR = "."
REPORT_PATH = "out/review/REPORT.md"


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个刚初始化、还没有任何产物的工作区（两端的入参都指得进去）。"""
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    return root


def _cells_without_source(cells: list[dict]) -> list[dict]:
    """网页那端的每一格多一格 `source`（呈现面）；比读数时把它摘掉。

    摘的是网页自己补的那一格，不是共享读数里的任何一格：摘完之后两边的格
    必须逐字相等 —— 这条就是“网页不许在共享读数之外改格形状”的机器形态。
    """
    return [{k: v for k, v in cell.items() if k != "source"} for cell in cells]


def test_a_same_inputs_give_verbatim_equal_cells(tmp_path: pathlib.Path) -> None:
    """a：同一批入参 ⇒ 两个出口的八格与计数逐字相等。"""
    root = _workspace(tmp_path)
    readout = RD.gates_readout(root, project_dir=PROJECT_DIR, report_path=REPORT_PATH)
    assert readout["checked"], f"命令行那端没查成（判据失去对象）：{readout['reason']}"
    assert readout["data"]["cells"], "命令行那端八格是空的（判据失去对象）"

    package = R.package_face(root, project_dir=PROJECT_DIR, report_path=REPORT_PATH)
    gates = package["closing"]["gates"]
    assert gates["cells"], (
        f"网页那端八格是空的（判据失去对象）：tri={package.get('tri')} "
        f"reason={package.get('reason')}")

    assert _cells_without_source(gates["cells"]) == readout["data"]["cells"], (
        "同一份工作区、同一批入参，网页与命令行的八格不逐字相等 ⇒ 两端各算了一套")
    assert gates["counts"] == readout["data"]["counts"], (
        f"计数分叉：网页 {gates['counts']} vs 命令行 {readout['data']['counts']}")
    assert bool(gates["machine_pass"]) == bool(readout["data"]["machine_pass"]), (
        "machine_pass 分叉（它只是读数，但两端必须是同一个读数）")


def test_b_both_ends_read_the_one_computer(tmp_path: pathlib.Path,
                                           monkeypatch) -> None:
    """b（反真空）：把 `readouts.gate_cells` 打桩 ⇒ 两个出口都必须变成那份标记。"""
    root = _workspace(tmp_path)
    marker_name = "__one_computer__"
    marker_cells = [{"name": marker_name, "status": "pass", "detail": "打桩"}]
    marker_counts = {"pass": 1, "fail": 0, "unknown": 0, "na": 0}
    seen: list[int] = []

    def fake_gate_cells(report):
        seen.append(1)
        return ([dict(c) for c in marker_cells], dict(marker_counts))

    monkeypatch.setattr(RD, "gate_cells", fake_gate_cells)

    readout = RD.gates_readout(root, project_dir=PROJECT_DIR, report_path=REPORT_PATH)
    assert readout["data"]["cells"] == marker_cells, (
        "命令行那端没走 `readouts.gate_cells`（打桩没生效）⇒ 它自己又数了一遍")

    package = R.package_face(root, project_dir=PROJECT_DIR, report_path=REPORT_PATH)
    gates = package["closing"]["gates"]
    names = [str(c.get("name") or "") for c in gates.get("cells") or []]
    assert names == [marker_name], (
        "网页那端自己又数了一遍八格（没调 `readouts.gate_cells`）⇒ 两台计算机器："
        f"打桩的标记 {marker_name!r} 没出现在 {names} 里")
    assert gates["counts"] == marker_counts, (
        f"网页的计数没跟着 `gate_cells` 走：{gates['counts']} vs {marker_counts}")
    assert seen, (
        "打桩的计数器一次都没被调到 —— 这条反真空失去对象（两个出口都没走它）")
