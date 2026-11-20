# -*- coding: utf-8 -*-
"""收工门读数：`na`（不适用）不许被折成 `unknown`（没查成），两读口 counts 必须逐格相等。

## 这一份补的是什么

`readouts.CELL_STATES` 改前只有 `pass` / `fail` / `unknown`，而 `closing` 早就会写第四档
`na`（`load_bearing` 在「形式化已关闭」的项目上记 `na`）。`gates_readout` 于是把它折成
`unknown` —— 同一现场两个出口给出两套 counts：

```text
closing 侧（rep.status 逐格）  pass2 fail1 unknown4 na1
读数侧（data.counts）          pass2 fail1 unknown5          ← na 被折进来，且没有 na 这个键
```

真机读数（2026-11-01）：`agentflow stats gates` 在 `projects/paper-rewrite-81` 上打出
`load_bearing unknown`，而那一格自己的原话写着「T3 判据不适用（不是通过，也不是失败）」；
扫全库 158 个工作区，`load_bearing` 那一格 158/158 都是 `na` —— 不是某个工作区的
怪数据，是读数层少了一档词。

## 四条判据

| # | 判据 | 守的是 |
|---|---|---|
| ① | 真工作区端到端：空工作区上六格记 `na`（没有可判对象），`counts` 与 `closing` 逐格相等（格数跟 `DEFAULT_CHECKS` 走） | 业主原话「同一现场两读口 counts 逐格相等」；用的是真的 `check_closing`，不是打桩门 |
| ② | 打桩混合（pass4/fail1/unknown1/na1）：`data.counts` 与 `Counter(rep.status)` 字典相等 | 不是"sum 相等"：折一格时总数照样等于格数，只有逐格比对看得见 |
| ③ | 负控：把 `CELL_STATES` 打回改前三项 ⇒ 同一条比对必红（`na` 消失、`unknown` +1） | 业主原话「把 na 映射回 unknown ⇒ 红」；也证明 ①② 不是恒绿 |
| ④ | 类判据：AST 扫 `closing.py` 里 `rep.status[…] = <字面量>`（含 `IfExp` 两支）⇒ 集合 ⊆ `CELL_STATES`，且 `na` 在集合里 | 下一个新状态加进 `closing` 而忘了读数层 ⇒ 红；同时守住 2026-11-20 那一刀（"没有可判对象"必须有自己的状态，不许折进 pass / unknown） |

语义纪律（业主 2026-11-01 的第三条要求）另有一条：`unknown` 与 `na` 各自的含义必须在
同一个 docstring 里写清（`unknown` = 没查成、`na` = 不适用），判据读源码断言这两句。

## 2026-11-14（业主拍板）：门不再写 `na`，读数层仍认它

`load_bearing` 改前在 Lean 关（产品缺省）时记 `na`；2026-11-14 起那一格照旧判 ——
零承重断言记 `pass` + 读数 `state="not_applicable"`，有承重断言而拿不出背书记 `fail`
（判据 `tests/test_load_bearing_without_lean.py`）。于是"真工作区造一个 `na`"这条路
当时没有了：① 改成"真工作区跑一遍、两读口仍逐格相等"；②③ 用打桩的状态证明读数层
仍能把「历史盘上」的 `na` 原样保留。

## 2026-11-20（EMPTYCELL）：`na` 回来了，含义与 2026-11-14 撤掉的那个不同

改前的 `na` 说的是"这一档对这个项目天然不成立"（Lean 关 ⇒ 没有 T3 可判），而它让
`machine_pass` 在缺省配置下永远是假 —— 那是把"配置"记成"判定"。EMPTYCELL 的 `na`
说的是另一件事：「这一格依赖的东西整个不存在」（表不在 / 表在盘上零行 / 没有会话记录）
⇒ 没有可判对象。空工作区上六格 `pass` 的真空通过（`counts={pass:6, fail:2}`）
就是它要拆的东西：状态栏说"过"，而其实一格都没判过。

于是两条口径同时成立：`na` 不是 pass（八格全 na ⇒ `closing_verdict` 落 unknown）、
也不是 fail / unknown（真 fail 的格照样 fail）；它不进 pass / fail 计数，也不进分母。
"""

from __future__ import annotations

import ast
import collections
import pathlib

import pytest

from agentflow import closing as CL
from agentflow import readouts as R
from agentflow import settings as SET
from agentflow.store import Store

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
READOUTS = REPO / "src" / "agentflow" / "readouts.py"
CLOSING = REPO / "src" / "agentflow" / "closing.py"

#: 打桩用的混合状态（恰好一格 na、一格 unknown、一格 fail —— 任何折叠都看得见）。
#: 2026-11-14：`paper` 退出收工判定（业主裁定）⇒ 打桩的格表跟着 `DEFAULT_CHECKS` 走。
#: 2026-11-16（Q1）：加第八格 `literature_pending`（待入库文献表清空才许收工）。
MIXED: dict[str, str] = {
    "contradictions": "pass", "load_bearing": "na",
    "report_shape": "unknown", "user_pending": "pass", "substance": "pass",
    "acceptance": "fail", "artifact_ledger": "pass", "literature_pending": "pass",
}


def _closing_counts(status: dict[str, str]) -> dict[str, int]:
    """closing 侧的 counts：按 `DEFAULT_CHECKS` 逐格取原值再数（不给任何一格特判）。"""
    return dict(collections.Counter(status[name] for name in CL.DEFAULT_CHECKS))


def _parity_problems(got: dict, status: dict[str, str]) -> list[str]:
    """两读口的逐格比对：cells 里的 status 与 counts 的分布都要与 closing 侧一致。"""
    cells = {str(c["name"]): str(c["status"]) for c in got["data"]["cells"]}
    want = _closing_counts(status)
    problems: list[str] = []
    for name in CL.DEFAULT_CHECKS:
        if cells.get(name) != status[name]:
            problems.append(f"逐格不等：{name} 读数是 {cells.get(name)!r}，门是 {status[name]!r}")
    if got["data"]["counts"] != want:
        problems.append(f"counts 不等：读数是 {got['data']['counts']}，门是 {want}")
    if set(got["data"]["counts"]) != set(R.CELL_STATES):
        problems.append(
            f"counts 的键不是 CELL_STATES：{sorted(got['data']['counts'])} vs "
            f"{list(R.CELL_STATES)}")
    return problems


# ====================================================================== ① 真工作区
def test_a_real_gate_on_an_empty_workspace_writes_na_and_the_reading_side_still_matches(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：真的收工门在空工作区上把六格记 `na`，两读口逐格相等。

    2026-11-20（EMPTYCELL）：改前这六格是 `pass`（"没有东西可判"冒充"判过且合格"）。
    这一条钉四件事：

    ① 空工作区上六格 `na`；`substance` 仍 `fail`、没给报告路径时 `report_shape` 是
      `unknown` —— 真 fail 与真没查成都留在自己的档里，没有被 `na` 吞掉；
    ② 每一格 `na` 都带 why（`closing_verdict` 的 `cells[].why` 说出"没有可判对象"）；
    ③ `gates_readout` 与 `closing` 的逐格 counts 仍相等，`counts["na"] == 6`；
    ④ `machine_pass` 是假（没有一格判过 —— `na` 不是 `pass`）。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    assert SET.lean_enabled()[0] is False, "夹具前提变了：Lean 关不掉就测不到缺省那一档"

    # 两个出口给同一批入参（`project_dir="."` 才会跑到 acceptance / artifact_ledger 两格；
    # `report_path` 不给 ⇒ report_shape 记 unknown，正好用来证明 na 没把 unknown 吞掉）。
    rep = CL.check_closing(Store(ws), project_dir=".", sid=None)
    na_want = ("contradictions", "load_bearing", "user_pending", "acceptance",
               "artifact_ledger", "literature_pending")
    assert {n: rep.status.get(n) for n in na_want} == {n: "na" for n in na_want}, rep.status
    assert rep.status.get("substance") == "fail", rep.status
    assert rep.status.get("report_shape") == "unknown", rep.status

    verdict = CL.closing_verdict(rep)
    assert verdict["counts"] == {"pass": 0, "fail": 1, "unknown": 1, "na": 6}, verdict["counts"]
    verdict_cells = {c["check"]: c for c in verdict["cells"]}
    for name in na_want:
        assert verdict_cells[name]["status"] == "na", verdict_cells[name]
        assert "没有可判对象" in str(verdict_cells[name]["why"]), verdict_cells[name]
    assert rep.machine_pass is False, rep.to_dict()

    # 会话号显式给 `None`（运维口径：读缺省会话）：读数缺省现在是"没给运行号"的
    # unknown（见 `gates_readout` 的 `sid` 三态，判据
    # `test_a_gate_readout_without_a_run_says_unknown.py`），两个出口要比同一档才是同一批入参。
    got = R.gates_readout(ws, project_dir=".", sid=None)
    assert got["checked"] is True, got["reason"]

    state = dict(rep.status)
    # 反真空：这一份现场真的混着三档（na / fail / unknown），不是"全是 na"的空转。
    assert set(state.values()) == {"na", "fail", "unknown"}, state
    # 逐格相等：cell 一格不差；counts 那一栏是"四档一张表"（0 也占一格），所以拿掉
    # 零值再比 —— 比的是同一份分布，不是让读数的形状跟着门的分布走。
    cells_by_name = {str(c["name"]): str(c["status"]) for c in got["data"]["cells"]}
    assert cells_by_name == {name: state[name] for name in CL.DEFAULT_CHECKS}, cells_by_name
    assert {k: v for k, v in got["data"]["counts"].items() if v} == _closing_counts(state), (
        got["data"]["counts"], _closing_counts(state))
    assert set(got["data"]["counts"]) == set(R.CELL_STATES), got["data"]["counts"]
    # na 不进 pass 计数、也不进 fail 计数：空工作区上两格都是 0。
    assert got["data"]["counts"] == {"pass": 0, "fail": 1, "unknown": 1, "na": 6}, \
        got["data"]["counts"]


# ====================================================================== ② 打桩八格
def _stub_gates(monkeypatch: pytest.MonkeyPatch, ws: pathlib.Path) -> dict:
    """把门打桩成 `MIXED` 那一份（只换门，不换读数层）。"""

    class _Report:
        status = dict(MIXED)
        findings: list[object] = []
        machine_pass = False
        m_says_done = False
        can_close = None
        closable = False
        m_verdict = None
        refusal = None

    monkeypatch.setattr(CL, "check_closing", lambda *a, **k: _Report())
    monkeypatch.setattr(CL, "machine_feeders", lambda *a, **k: {})
    return R.gates_readout(ws)


def test_counts_are_the_closing_statuses_cell_by_cell(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """打桩八格混合：`data.counts` 与 `Counter(rep.status)` 字典相等，且 na 单独一格。"""
    ws = tmp_path / "ws"
    Store(ws).init()
    got = _stub_gates(monkeypatch, ws)
    assert _parity_problems(got, MIXED) == [], _parity_problems(got, MIXED)
    assert got["data"]["counts"] == {"pass": 5, "fail": 1, "unknown": 1, "na": 1}, \
        got["data"]["counts"]
    assert got["data"]["counts"]["na"] == 1, got["data"]["counts"]
    # 每格都要被数到（sum 相等是必要条件，不是充分条件 —— 见负控）
    assert sum(got["data"]["counts"].values()) == len(CL.DEFAULT_CHECKS) == 8


# ====================================================================== ③ 负控
def test_negative_control_folding_na_back_into_unknown_turns_it_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：把词表打回改前的三项 ⇒ 同一条比对必红（na 消失、unknown +1）。

    这正是改前那一版的行为（业主原话：「负控：把 na 映射回 unknown ⇒ 红」）。
    它同时证明上面那两条不是恒绿：判据真的在比逐格，而不是在比总数。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    got = _stub_gates(monkeypatch, ws)
    assert _parity_problems(got, MIXED) == []

    monkeypatch.setattr(R, "CELL_STATES", ("pass", "fail", "unknown"))
    folded = R.gates_readout(ws)
    problems = _parity_problems(folded, MIXED)
    assert problems, "词表退回三项之后，逐格比对居然还是绿的 —— 这条判据没有接线"
    assert any("load_bearing" in p for p in problems), problems
    assert folded["data"]["counts"].get("na") is None, folded["data"]["counts"]
    assert folded["data"]["counts"]["unknown"] == 2, folded["data"]["counts"]
    # 总数没变（8）：所以"sum 相等"抓不到这个缺陷，只有逐格比对抓得到
    assert sum(folded["data"]["counts"].values()) == 8


# ====================================================================== ④ 类判据（词表覆盖门的状态值）
def _status_literals(path: pathlib.Path) -> set[str]:
    """`rep.status[…] = <字面量>` 的全部取值（`IfExp` 两支都收；非字面量单独报出来）。

    只读 AST，不 import、不执行 —— 扫的是"closing 会写出哪些状态词"，与它怎么算是两件事。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    unknown_values: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and target.value.attr == "status"):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.add(value.value)
            elif isinstance(value, ast.IfExp):
                for branch in (value.body, value.orelse):
                    if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                        found.add(branch.value)
                    else:
                        unknown_values.append(type(branch).__name__)
            else:
                unknown_values.append(type(value).__name__)
    assert not unknown_values, (
        "有 `rep.status[…]` 赋的不是字符串字面量（判据的扫描器要跟着升级）："
        f"{unknown_values}")
    return found


def test_the_cell_vocabulary_covers_every_status_the_gate_can_write() -> None:
    """类判据：`closing` 能写出的每个状态词都必须在 `CELL_STATES` 里（今天是四档）。

    2026-11-20（EMPTYCELL）：`na` 回到门里 —— 含义是"这一格依赖的东西整个不存在
    （没有可判对象）"，不是 2026-11-14 撤掉的"这一档对这个项目天然不成立"。所以这条
    判据钉三句：
    ① `closing` 今天写出的词一个都不许落在词表外（新加一档而读数层不认 ⇒ 红）；
    ② `na` 必须在写出的词里（删掉那一档 ⇒ "没有可判对象"又只能折回 pass/unknown）；
    ③ 读数层词表仍是四档（加档要同时改这里与判据）。
    """
    written = _status_literals(CLOSING)
    # 反真空：真的扫到了字面量，而且词表外一个都没有
    assert len(written) >= 4, written
    assert "na" in written, (
        "`closing.py` 不再写 `na` 了 —— \"这一格没有可判对象\"没有自己的状态，就只能折回 "
        f"`pass`（真空通过）或 `unknown`（没查成）；今天写到的是 {sorted(written)}")
    missing = sorted(written - set(R.CELL_STATES))
    assert not missing, (
        f"`closing` 会写这些状态词，而读数层的词表没有：{missing}。"
        "少了它，那一格会被折成 `unknown`「没查成」（改前 na 就是这么丢的）")
    # 词表里仍然认 `na`：历史盘上的读数不能因为门改了写法就被折成 unknown
    assert "na" in R.CELL_STATES, (
        "`na` 从读数层词表里消失了 —— 历史盘上的旧读数会被折成 `unknown`"
        f"（今天词表是 {list(R.CELL_STATES)}）")
    assert set(R.CELL_STATES) == {"pass", "fail", "unknown", "na"}, (
        f"词表变了：{R.CELL_STATES}（真身是四档；加档要同时改这里与判据）")


# ====================================================================== 语义纪律
def test_unknown_and_na_are_documented_as_two_different_things() -> None:
    """`unknown` 与 `na` 各自的语义必须写在同一处（unknown=没查成；na=不适用）。

    为什么把它做成判据：这两档一旦在注释里也含糊，下一个人就会把"不适用"折进
    "没查成"（改前正是这样），而所有测试照样绿（改前那 158 个工作区就是证据）。
    """
    src = READOUTS.read_text(encoding="utf-8")
    start = src.index("CELL_STATES: tuple[str, ...]")
    # 常量正上方那一整块 `#:` 注释就是它的 docstring
    block_start = src.rindex("\n\n", 0, start) if "\n\n" in src[:start] else 0
    block = src[block_start:start]
    assert "unknown" in block and "na" in block, block[-400:]
    assert "没查成" in block, "词表注释里没写清 unknown = 没查成"
    assert "不适用" in block, "词表注释里没写清 na = 不适用"
    # 两条语义必须在同一块里成对出现（分到两处就会各自漂）
    assert block.index("没查成") < block.index("不适用"), block[-400:]

    # gates_readout 自己的 docstring 也要说清 na 不是 unknown
    doc = R.gates_readout.__doc__ or ""
    assert "na` 与 `unknown` 分得开" in doc or ("na" in doc and "没查成" in doc), doc[:400]
