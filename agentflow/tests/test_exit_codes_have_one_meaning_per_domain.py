# -*- coding: utf-8 -*-
"""判据：同一个退出码在不同命令里"什么意思"，只许有一处登记（`R-BE1` 的 ③-6）。

## 这一份守什么（2026-10-27，业主批准）

改前同一个 `1` 在四条命令里含义不同（loop 是"行为异常"、pipeline 是"预算熔断"、gate 是
"被 M 拦住"、门禁是"requires_human"），而这件事只散在四处 docstring 的散文里 ——
没有一处能对拍，于是"同码不同义"既看不出来也测不出来。

现在 `stop_reasons.EXIT_CODE_DOMAINS` 是那张唯一的登记表，`EXIT_CODE_UNIFIED` 是三条上位
口径。本判据的期望值全部从表里取（测试里不手抄第二份）：产出方那边只提供"它可能吐出
哪些码"，与表对拍。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① 三条上位口径 | 每个域都给出 `0/1/2`，且每域三句话互不相同、非空 | 某个域把 `2` 写成"没问题"，三态又被折平 |
| ② `3/4/5` 只属 loop | 别的域登记 `3/4/5` 就红 | 管线域借一个 `3` 表示"没 key"，两种"没查成"混成一档 |
| ③ loop 域覆盖 | `STOP_REASONS` 的 live 码、`AUTONOMY_ONLY_EXIT_CODE`、`EXIT_CODE_WHEN_UNKNOWN`、`rounds` 的两档都 ⊆ loop 域 | 新增一档停止理由而表没登记 |
| ④ pipeline 域覆盖 | `runflow._exit_code_for` 对 `RUN_TOPIC_REASON_LITERALS` × 成功/不成功、以及 `modelgw` 两张词表吐的码都 ⊆ pipeline 域 | 管线新增一条 reason 落到未登记的码 |
| ⑤ gate / readout 域覆盖 | `closing.tri_state_exit_code` 三种形态、`cmd_stats` 四条读数实跑返回的码 ⊆ 各自域 | 某一格开始吐 `1`（或 `3`）而表里没有 |
| ⑥ 反真空 | 未登记的 reason ⇒ 落 `1`（loop / pipeline 两边），且 `1` 必须在表里 | 未登记的故障被折成 `0`（"做完了"） |
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import cli as CLI
from agentflow import closing as CL
from agentflow import readouts as RO
from agentflow import runflow as RF
from agentflow import stop_reasons as SR
from agentflow.store import Store

DOMAINS = SR.EXIT_CODE_DOMAINS
UNIFIED = SR.EXIT_CODE_UNIFIED


class _Args:
    """`cmd_stats` 要的最小参数面（只读；不给项目根，收工门那格如实记 unknown）。"""

    def __init__(self, root: pathlib.Path, kind: str) -> None:
        self.root = str(root)
        self.stats_cmd = kind
        self.json = True
        self.readout = True
        self.project_dir = ""
        self.report = ""


# ---------------------------------------------------------------- ① 三条上位口径


def test_every_domain_states_the_three_unified_codes_distinctly() -> None:
    """每个域都要给 `0` 与 `2`，给了的码各自一句话、互不相同；`1` 只在 readout 域缺席。

    readout 域刻意没有 `1`：那一层不是判据，它不判"错误太多"（`cmd_stats` 的 docstring
    也这么写）。除了它，每个域都必须给全 `0/1/2` —— 少一格就意味着某一态被折进别的码。
    """
    assert set(UNIFIED) == {0, 1, 2}, UNIFIED
    for domain, cells in DOMAINS.items():
        assert {0, 2} <= set(cells), (domain, sorted(cells))
        assert all(str(m).strip() for m in cells.values()), (domain, cells)
        meanings = list(cells.values())
        assert len(set(meanings)) == len(meanings), (
            f"{domain} 域里有两格说法一样 ⇒ 三态被折平了", cells)
        if domain == "readout":
            assert 1 not in cells, "readout 不是判据，不该有 1"
        else:
            assert {0, 1, 2} <= set(cells), (domain, sorted(cells))


# ---------------------------------------------------------------- ② 3/4/5 只属 loop


def test_only_the_loop_domain_may_use_three_four_five() -> None:
    """`3/4/5` 只在 `loop` 域：它们回答"下一步谁动"，别的域借一个就等于改语义。"""
    for domain, cells in DOMAINS.items():
        extra = set(cells) - {0, 1, 2}
        if domain == "loop":
            assert extra == {3, 4, 5}, (domain, sorted(extra))
        else:
            assert not extra, (
                f"{domain} 域登记了 {sorted(extra)}：只有 loop 域可以用 3/4/5")


# ---------------------------------------------------------------- ③ loop 域覆盖


class _Run:
    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason
        self.reports: list = []


def _loop_codes() -> set[int]:
    codes: set[int] = set(CLI.EXIT_CODE_BY_STOP.values())
    codes |= set(CLI.AUTONOMY_ONLY_EXIT_CODE.values())
    codes.add(CLI.EXIT_CODE_WHEN_UNKNOWN)
    for reason in list(SR.STOP_REASONS) + ["rounds", "resumed_done"]:
        codes.add(CLI._autonomy_exit_code(_Run(reason)))
        codes.add(CLI._run_agent_exit_code(_Run(reason)))
    return codes


def test_the_loop_domain_covers_every_code_the_loop_can_emit() -> None:
    """循环那一侧能吐的码，必须都登记在 `EXIT_CODE_DOMAINS["loop"]` 里。"""
    codes = _loop_codes()
    assert codes, "循环那一侧一个码都没扫到（反真空）"
    assert codes <= set(DOMAINS["loop"]), (
        "循环吐了未登记的码", sorted(codes - set(DOMAINS["loop"])))
    # 与 `STOP_REASONS` 同源：live 的那些档的码必须都在
    live_codes = {row[0] for row in SR.STOP_REASONS.values() if row[3]}
    assert live_codes <= codes and live_codes <= set(DOMAINS["loop"]), live_codes


# ---------------------------------------------------------------- ④ pipeline 域覆盖


def _pipeline_codes() -> set[int]:
    from agentflow.modelgw import MODEL_ERROR_KINDS, NOT_CHECKED

    reasons = set(RF.RUN_TOPIC_REASON_LITERALS) | set(MODEL_ERROR_KINDS) | set(NOT_CHECKED)
    reasons |= {"success", "no_call", "budget_exhausted", "", "cancelled", "error"}
    codes: set[int] = set()
    for reason in reasons:
        for successes in (0, 1):
            codes.add(RF._exit_code_for(reason, successes=successes))
    return codes


def test_the_pipeline_domain_covers_every_code_the_pipeline_can_emit() -> None:
    """管线那一侧能吐的码，必须都登记在 `EXIT_CODE_DOMAINS["pipeline"]` 里。"""
    codes = _pipeline_codes()
    assert codes, "管线那一侧一个码都没扫到（反真空）"
    assert codes <= set(DOMAINS["pipeline"]), (
        "管线吐了未登记的码", sorted(codes - set(DOMAINS["pipeline"])))


# ---------------------------------------------------------------- ⑤ gate / readout 域


def test_the_gate_domain_covers_the_three_shapes(tmp_path: pathlib.Path) -> None:
    """`tri_state_exit_code` 的三种形态（达成 / 没判 / 判了没达成）都 ⊆ gate 域。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    Store(ws).init()
    rep = CL.check_closing(Store(ws), project_dir="", report_path="")
    codes = {CL.tri_state_exit_code(rep)}
    rep_met = CL.check_closing(Store(ws), project_dir="", report_path="", goal_met=True)
    rep_not = CL.check_closing(Store(ws), project_dir="", report_path="", goal_met=False)
    codes |= {CL.tri_state_exit_code(rep_met), CL.tri_state_exit_code(rep_not)}
    assert codes == {0, 1, 2}, codes
    assert codes <= set(DOMAINS["gate"]), sorted(codes - set(DOMAINS["gate"]))


def test_the_readout_domain_covers_what_stats_returns(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """四条读数实跑返回的码 ⊆ readout 域（这一域刻意没有 1）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    Store(ws).init()
    codes: set[int] = set()
    for kind in ("errors", "flow", "cost", "gates", "all"):
        codes.add(CLI.cmd_stats(_Args(ws, kind)))       # 空但初始化过 ⇒ 0（正控）
        codes.add(CLI.cmd_stats(_Args(tmp_path / "none", kind)))  # 工作区不存在 ⇒ 2
        capsys.readouterr()
    assert codes == {0, 2}, codes
    assert codes <= set(DOMAINS["readout"]), sorted(codes - set(DOMAINS["readout"]))
    assert 1 not in DOMAINS["readout"], "readout 域不该有 1：它不是判据"
    assert set(RO.READOUTS) == {"errors", "flow", "cost", "gates"}


# ---------------------------------------------------------------- ⑥ 反真空


def test_an_unknown_reason_lands_in_one_and_that_one_is_registered() -> None:
    """未登记的 reason ⇒ 落 `1`（两边），而 `1` 必须在各自域里登记过。"""
    assert RF._exit_code_for("__no_such_reason__", successes=0) == 1
    assert CLI._run_agent_exit_code(_Run("__no_such_reason__")) == 1
    assert 1 in DOMAINS["pipeline"] and 1 in DOMAINS["loop"]
    assert UNIFIED[1].startswith("查过、结论是坏"), UNIFIED[1]
