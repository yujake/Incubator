# -*- coding: utf-8 -*-
"""花销"两处一致"必须同范围比（2026-10-27 业主裁定 ⑥-4）。

改前的缺陷形态：页面拿"整段会话每一趟的 `usd` 之和"去比"一份检查点的累计"。
一段会话跑过两趟、或跑过子代理时，这两个数结构上必然不等 —— 于是页面恒挂一条
红徽标"两处不一致"，而它比的根本不是同一件事（没有任何判据会因此变红，因为它
甚至在读数层都是"两个真数"）。

现在的口径：两个数都由后端给，且同范围 ——

- `checkpoint_spend_usd`：被选中的那一份检查点（`runs/agent-<角色>-<sid>.json`，
  mtime 最新的那一份）自己的累计；
- `same_run_spend_usd`：这一段会话里同一角色最后一趟的事件求和。

| 用例 | 判什么 |
|---|---|
| `test_the_two_readings_come_from_the_same_run` | 正控：同一趟两个数相等；同时把"跨趟合计"摆出来证明它与前者不是同一个数 |
| `test_a_second_run_does_not_turn_the_badge_red` | 负控（跨趟）：跑过两趟的会话里，页面对比的那两格仍然相等（旧口径会判"不一致"） |
| `test_a_checkpoint_without_its_run_is_unreadable_not_wrong` | 负控：检查点的角色在会话里没有对应的趟 ⇒ 那一格是 `None`（"没查成"），不是 0、也不是"不一致" |
| `test_no_checkpoint_means_no_same_run` | 负控：没有检查点 ⇒ 两个数都 `None`、`checkpoint_role` 是空串，不许补 0 |
| `test_the_page_compares_the_two_same_run_readings` | 页面那一侧：`Run.tsx` 比的是这两格；跨趟求和那份（`eventSum`）已删；整段合计只作参考读数 |
"""
from __future__ import annotations

import json
import pathlib

from agentflow import sessions as SS
from agentflow.webui import readers as R

#: 夹具会话号（与 `tests/test_webui_readers.py` 的 `SID` 无关，每个用例各自建工作区）。
SID = "t"

#: 页面源码（判据读它：页面是客户端渲染，Python 看不到 DOM）。
UI = pathlib.Path(__file__).resolve().parents[1] / "ui"


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


def _append(root: pathlib.Path, **event: object) -> None:
    """往会话里追加一条事件（`seq` / `ts` 由 `sessions.append` 补齐）。"""
    _path, problem = SS.append(root, event, sid=SID)
    assert problem == "", problem


def _two_runs(root: pathlib.Path) -> None:
    """造一段跑过两趟的会话：第一趟 0.5 美元、第二趟 0.25 美元（都用角色 M）。

    为什么必须两趟：一趟的会话里"整段合计"与"同一趟"恰好相等，那样的夹具分不出
    "同范围"与"跨范围"两种口径（正是改前那条判据看不见缺陷的原因）。
    """
    for task, usd in (("第一趟", 0.5), ("第二趟", 0.25)):
        _append(root, kind="agent_run_start", role="M", task=task)
        _append(root, kind="llm_call", role="M", usd=usd)
        _append(root, kind="agent_run_end", role="M", stop_reason="final")


def _checkpoint(root: pathlib.Path, *, usd: float = 0.25, role: str = "M") -> pathlib.Path:
    """落一份检查点（形状照 `agent_loop.save_run_checkpoint` 的 10 个键）。"""
    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"agent-{role}-{SID}.json"
    path.write_text(json.dumps({
        "role": role, "sid": SID, "task": "第二趟", "fingerprint": "",
        "step": 2, "stop_reason": "final", "waiting_for": "",
        "spend": {"calls": 1, "tokens_in": 10, "tokens_out": 5, "usd": usd,
                  "unknown_usd_calls": 0},
        "prompt_cache": {}, "at": "2026-10-27T00:00:00Z",
    }, ensure_ascii=False), encoding="utf-8")
    return path


# ====================================================================== 读数层
def test_the_two_readings_come_from_the_same_run(tmp_path: pathlib.Path) -> None:
    """正控：同一趟的两个数相等，而"整段合计"确实是另一个数（旧口径会判不一致）。"""
    root = _workspace(tmp_path)
    _two_runs(root)
    _checkpoint(root, usd=0.25)
    got = R.run_view(root, SID)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["checkpoint_role"] == "M", got["checkpoint_role"]
    assert got["checkpoint_spend_usd"] == 0.25, got["checkpoint_spend_usd"]
    assert got["same_run_spend_usd"] == 0.25, got["same_run_spend_usd"]
    # 第二趟的 `agent_run_start` 是第 4 条事件（下标 3）
    assert got["same_run_start_index"] == 3, got["same_run_start_index"]
    assert got["same_run_unknown_usd"] == 0, got["same_run_unknown_usd"]

    total = sum(float(one["usd"] or 0.0) for one in got["runs"])
    assert total == 0.75, total
    assert total != got["checkpoint_spend_usd"], (
        "前提没成立：跨趟合计与检查点恰好相等，这段夹具分不出两种口径")
    assert got["checkpoint_spend_usd"] == got["same_run_spend_usd"], (
        "同一趟的两个数不相等 —— 页面的徽标会挂红")


def test_a_second_run_does_not_turn_the_badge_red(tmp_path: pathlib.Path) -> None:
    """负控（跨趟）：两趟的会话里，页面要比的那两格仍然相等。

    这就是改前那条假红的形态：`整段合计(0.75) != 检查点(0.25)`，但同一趟的两个数
    都是 0.25。判据钉的是"页面比的是哪两格"，所以它必须能区分这两种比法。
    """
    root = _workspace(tmp_path)
    _two_runs(root)
    _checkpoint(root, usd=0.25)
    got = R.run_view(root, SID)
    cross_run = sum(float(one["usd"] or 0.0) for one in got["runs"])
    assert cross_run != got["checkpoint_spend_usd"]
    assert got["same_run_spend_usd"] == got["checkpoint_spend_usd"], got


def test_a_checkpoint_without_its_run_is_unreadable_not_wrong(
        tmp_path: pathlib.Path) -> None:
    """负控：检查点的角色在会话里没有对应的趟 ⇒ 那一格是 `None`（没查成）。

    为什么这条要紧：拿别的一趟顶上去会让页面拿两个不相干的数比出"不一致"；
    补 0 会让它比出"不一致"或"一致"（两种都是编）。`None` 才是"这一格没读到"。
    """
    root = _workspace(tmp_path)
    _two_runs(root)
    _checkpoint(root, usd=0.1, role="A")
    got = R.run_view(root, SID)
    assert got["checkpoint_role"] == "A", got["checkpoint_role"]
    assert got["checkpoint_spend_usd"] == 0.1, got["checkpoint_spend_usd"]
    assert got["same_run_spend_usd"] is None, got["same_run_spend_usd"]
    assert got["same_run_start_index"] is None, got["same_run_start_index"]
    assert got["same_run_unknown_usd"] == 0, got["same_run_unknown_usd"]


def test_no_checkpoint_means_no_same_run(tmp_path: pathlib.Path) -> None:
    """负控：没有检查点 ⇒ 两个数都 `None`、角色是空串（不许补 0，也不许瞎选一趟）。"""
    root = _workspace(tmp_path)
    _two_runs(root)
    got = R.run_view(root, SID)
    assert got["checkpoint_role"] == "", got["checkpoint_role"]
    assert got["checkpoint_spend_usd"] is None, got["checkpoint_spend_usd"]
    assert got["same_run_spend_usd"] is None, got["same_run_spend_usd"]
    assert got["same_run_unknown_usd"] == 0, got["same_run_unknown_usd"]


def test_the_keys_are_declared_where_the_types_are_generated() -> None:
    """反真空（接线）：这四格必须在 `RunView` 的 `type_decls()` 里，否则 `types.ts`
    生成物里没有它们，页面读到的是 `undefined`（`tsc` 也看不见）。"""
    decl = next(one for one in R._TS_TYPES if one[0] == "RunView")[2]
    names = {name for name, _ts in decl}
    for key in ("checkpoint_role", "checkpoint_spend_usd", "same_run_spend_usd",
                "same_run_unknown_usd", "same_run_start_index"):
        assert key in names, f"RunView 的 type_decls() 里没有 {key}：{sorted(names)}"


# ====================================================================== 页面那一侧
def _page(name: str = "Run") -> str:
    return (UI / "src" / "pages" / f"{name}.tsx").read_text(encoding="utf-8")


def test_the_page_compares_the_two_same_run_readings() -> None:
    """页面那一侧：比的是同范围的两格，跨趟求和那份已删。

    读源码（页面是客户端渲染，Python 判据看不到 DOM），三个读数缺一不可：
    ① 比的两格来自后端（`checkpoint_spend_usd` / `same_run_spend_usd`）；
    ② "两个都读到才比"写在代码里（`ckAmount !== null && runAmount !== null`）；
    ③ 跨趟求和（`eventSum`）不再参与判据 —— 它此前既是假红的成因，也是同一件事的
    第二份实现。整段合计仍留着，但只作参考读数（`sessionTotal`）。
    """
    src = _page()
    assert "v.checkpoint_spend_usd" in src, "页面没有读检查点那一格"
    assert "v.same_run_spend_usd" in src, "页面没有读同一趟那一格"
    assert "ckAmount !== null && runAmount !== null" in src, (
        "页面没有把「两个都读到才比」写进判据")
    assert "function eventSum(" not in src, "跨趟求和那份实现还在（判据会拿它比）"
    assert "Math.abs(ckAmount - runAmount)" in src, "比的两个量不是同范围的那两格"
    assert "sessionTotal" in src, "整段合计那一句参考读数不见了"
