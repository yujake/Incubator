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
`load_bearing unknown`，而那一格自己的原话写着「T3 判据**不适用**（不是通过，也不是失败）」；
扫全库 158 个工作区，`load_bearing` 那一格 **158/158 都是 `na`** —— 不是某个工作区的
怪数据，是读数层少了一档词。

## 四条判据

| # | 判据 | 守的是 |
|---|---|---|
| ① | 真工作区端到端：`na` 那格在读数侧仍是 `na`，且 `counts` 与 `closing` 逐格相等（八格，含 na 键） | 业主原话「同一现场两读口 counts 逐格相等（含 na）」；用的是真的 `check_closing`（只把 Lean 开关拔到关，那是这副夹具造 na 的唯一办法，不是打桩门） |
| ② | 打桩八格混合（pass4/fail1/unknown1/na1）：`data.counts` 与 `Counter(rep.status)` **字典相等** | 不是"sum 相等"：折一格时总数照样是 8，只有逐格比对看得见 |
| ③ | 负控：把 `CELL_STATES` 打回改前三项 ⇒ 同一条比对必红（`na` 消失、`unknown` +1） | 业主原话「把 na 映射回 unknown ⇒ 红」；也证明 ①② 不是恒绿 |
| ④ | 类判据：AST 扫 `closing.py` 里 `rep.status[…] = <字面量>`（含 `IfExp` 两支）⇒ 集合 ⊆ `CELL_STATES`，且必须含 `na` | 下一个新状态（今天是 `na`）加进 `closing` 而忘了读数层 ⇒ 红；钉的是"词表覆盖门的状态值"，不是一个状态 |

语义纪律（业主 2026-11-01 的第三条要求）另有一条：`unknown` 与 `na` 各自的含义必须在
同一个 docstring 里写清（`unknown` = 没查成、`na` = 不适用），判据读源码断言这两句。
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

#: 打桩用的八格混合状态（恰好一格 na、一格 unknown、一格 fail —— 任何折叠都看得见）。
MIXED: dict[str, str] = {
    "paper": "pass", "contradictions": "pass", "load_bearing": "na",
    "report_shape": "unknown", "user_pending": "pass", "substance": "pass",
    "acceptance": "fail", "artifact_ledger": "pass",
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
def test_a_real_gate_that_says_na_stays_na_on_the_reading_side(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：一个真的会记 `na` 的收工门，读数侧那格必须仍是 `na`，counts 逐格相等。

    造 `na` 的办法是业主 2026-10-12 那条真实开关：把 Lean 形式化关掉 ⇒ `load_bearing`
    记 `na`（"这一格问的东西这一趟不适用"）。这里拔的是 `settings` 的开关，**不是**把
    `check_closing` 打桩 —— 门是真的跑过的，八格是真的现算的，`na` 是门自己写的。
    空工作区就是这副夹具：没有东西要交付 ⇒ 另外几格多数是 unknown / fail，正好不是"全 pass"。
    """
    ws = tmp_path / "ws"
    Store(ws).init()
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "0")
    assert SET.lean_enabled()[0] is False, "夹具前提变了：Lean 关不掉就造不出 na"

    rep = CL.check_closing(Store(ws))
    assert rep.status.get("load_bearing") == "na", rep.status
    got = R.gates_readout(ws)
    assert got["checked"] is True, got["reason"]

    state = dict(rep.status)
    # 反真空：这一份现场真的混着好几档、且含 na（否则"逐格相等"是空转）
    assert "na" in set(state.values()), state
    assert len(set(state.values())) >= 3, state
    assert _parity_problems(got, state) == [], _parity_problems(got, state)

    # 逐字钉住那一格（业主点名要看的那一格）
    cells = {str(c["name"]): c for c in got["data"]["cells"]}
    assert cells["load_bearing"]["status"] == "na", cells["load_bearing"]
    assert got["data"]["counts"]["na"] == 1, got["data"]["counts"]
    # 那一格的原话本身就写着"不适用"：状态栏必须与它同口径（改前状态栏写 unknown）
    assert "不适用" in str(cells["load_bearing"]["detail"]), cells["load_bearing"]


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
    # 8 格不能因为多了一档而被数丢（sum 相等是必要条件，不是充分条件 —— 见负控）
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
    """类判据：`closing` 能写出的每个状态词都必须在 `CELL_STATES` 里（今天是四档）。"""
    written = _status_literals(CLOSING)
    # 反真空：真的扫到了字面量，而且就包含那一档（否则下面那句"覆盖"是空谈）
    assert len(written) >= 3, written
    assert "na" in written, (
        "`closing.py` 里已经没有一个写 `na` 的地方了 —— 是这一格被删了，还是扫描器过期了？"
        f"（扫到的是 {sorted(written)}）")
    missing = sorted(written - set(R.CELL_STATES))
    assert not missing, (
        f"`closing` 会写这些状态词，而读数层的词表没有：{missing}。"
        "少了它，那一格会被折成 `unknown`「没查成」（改前 na 就是这么丢的）")
    assert set(R.CELL_STATES) == {"pass", "fail", "unknown", "na"}, (
        f"词表变了：{R.CELL_STATES}（真身是 closing 能写出的四档；加档要同时改这里与判据）")


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
    # 两条语义必须在**同一块**里成对出现（分到两处就会各自漂）
    assert block.index("没查成") < block.index("不适用"), block[-400:]

    # gates_readout 自己的 docstring 也要说清 na 不是 unknown
    doc = R.gates_readout.__doc__ or ""
    assert "na` 与 `unknown` 分得开" in doc or ("na" in doc and "没查成" in doc), doc[:400]
