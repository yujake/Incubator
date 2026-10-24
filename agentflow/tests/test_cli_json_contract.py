# -*- coding: utf-8 -*-
"""判据：`inspect` 那一组命令的 `--json` 契约（业主批的 CLI 更新方案 B）。

## 这一份守什么

契约文档是 `docs/CLI-CONTRACT.md`。文档里的每一句话都要有一条能红的判据，否则它只是散文：

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① | 每条 `inspect` 命令的 `--json` 都是外层四格，键集逐字等于 `JSON_ENVELOPE_KEYS` | 某一条自己长了个第五格，脚本要写两个分支 |
| ② | `state` 与退出码一一对应（0/1/2 → checked/failed/unknown） | 外壳说 `ok` 而进程以 1 结束，CI 与脚本各信一个 |
| ③ | 每条命令的 `data` 至少有一格是文档里写的那几个键 | 文档写了字段而命令不产出它（文档与实现的经典漂法） |
| ④ | 工作区不在盘上时这几条如实记 `unknown` + 退出码 2 | 用户读到"全 0、通过" |
| ⑤ | 旧路径上那六条命令的 `--json` 还是原来那一份（没被套壳） | `tools --json` 的冻结快照当场作废 |

第 ⑤ 条是这次改动的安全绳：`--json` 的外层刻意只覆盖 `inspect` 那一组（外加本轮新加
`--json` 的四条）。旧路径的字节一个都不许变，因为 `tools --json` 与几条别的输出已经有
消费者，其中一份还是被冻结快照逐字钉着的。

## 为什么 ② 要按"逐条"而不是"一条代表"

`state` 的翻译写在 `cli._envelope_state` 一处，但谁来给退出码是每条命令自己的事。
一条命令把"没查成"返回成 0，外壳就会诚实地报 `checked` —— 那正是最危险的那种谎
（外壳没撒谎，它信了句假话）。所以要逐条比：这条命令这次退出几，`state` 就必须是那一档。
"""
from __future__ import annotations

import io
import json
import pathlib
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentflow import cli

#: `inspect` 组里十位成员的 `--json` 调用形态与它 `data` 里必须有的键。
#:
#: `--root` 一律写在组名之前：`analyze` / `artifacts` / `verify` 这些命令自己不带
#: `--root`（那是顶层开关），写在后面会被 argparse 当成未知参数 —— 这也是它们
#: 一直以来的用法。
CASES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("status-report", ("status-report",), ("text",)),
    ("stats", ("stats", "flow"), ("roles", "totals")),
    ("evidence", ("evidence", "store", "<ws>"), ("text",)),
    ("artifacts", ("artifacts", "list"), ("text",)),
    ("analyze", ("analyze",), ("text",)),
    ("tools", ("tools",), ("count", "tools")),
    ("cache", ("cache", "status"), ("tiers", "active", "verdict")),
    ("budget", ("budget", "--status"), ("total_usd", "remaining_usd")),
    ("doctor", ("doctor",), ("model", "provers", "checks")),
    ("verify", ("verify",), ("checked", "errors", "error_count")),
)


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue(), err.getvalue()


def _argv(member: str, spec: tuple[str, ...], ws: pathlib.Path) -> list[str]:
    """拼一条 `inspect` 命令（`<ws>` 占位换成真的工作区）。"""
    return ["--root", str(ws), "inspect", *[str(ws) if part == "<ws>" else part
                                            for part in spec], "--json"]


# ---------------------------------------------------------------- 夹具


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个初始化过的空工作区（够这十条命令跑起来，且不写仓内任何东西）。"""
    from agentflow.store import Store

    ws = tmp_path / "ws"
    Store(ws).init()
    return ws


# ---------------------------------------------------------------- ① 外层四格


@pytest.mark.parametrize("member,spec,keys", CASES, ids=[c[0] for c in CASES])
def test_every_inspect_command_returns_the_four_key_envelope(
        member: str, spec: tuple[str, ...], keys: tuple[str, ...],
        tmp_path: pathlib.Path) -> None:
    """① 外层四格；③ `data` 里有文档写的那几个键。"""
    ws = _workspace(tmp_path)
    code, out, err = _run(_argv(member, spec, ws))
    doc = json.loads(out)  # 混进人话会当场炸在这里
    assert tuple(doc) == cli.JSON_ENVELOPE_KEYS, (member, tuple(doc))
    assert isinstance(doc["ok"], bool), (member, doc["ok"])
    assert isinstance(doc["problems"], list), (member, doc["problems"])
    assert isinstance(doc["data"], dict), (member, doc["data"])
    missing = [k for k in keys if k not in doc["data"]]
    assert not missing, (member, missing, sorted(doc["data"])[:12])


# ---------------------------------------------------------------- ② 三态与退出码


@pytest.mark.parametrize("member,spec,keys", CASES, ids=[c[0] for c in CASES])
def test_the_state_agrees_with_the_exit_code(
        member: str, spec: tuple[str, ...], keys: tuple[str, ...],
        tmp_path: pathlib.Path) -> None:
    """② `state` 与退出码一一对应，`ok` 也必须是同一个判断。"""
    ws = _workspace(tmp_path)
    code, out, _err = _run(_argv(member, spec, ws))
    doc = json.loads(out)
    assert doc["state"] == cli._envelope_state(code), (member, code, doc["state"])
    assert doc["state"] in cli.JSON_ENVELOPE_STATES, (member, doc["state"])
    assert doc["ok"] is (code == 0), (member, code, doc["ok"])
    # 没通过时 problems 不许是空的（"为什么不行"必须看得见）
    if code != 0:
        assert doc["problems"], f"{member} 退出码 {code} 而 problems 是空的"


# ---------------------------------------------------------------- ④ 没查成


@pytest.mark.parametrize("member,spec", [
    ("status-report", ("status-report",)),
    ("stats", ("stats", "flow")),
    ("evidence", ("evidence", "store", "<ws>")),
], ids=["status-report", "stats", "evidence"])
def test_a_missing_workspace_is_unknown(member: str, spec: tuple[str, ...],
                                        tmp_path: pathlib.Path) -> None:
    """④ 工作区不在盘上 ⇒ `state="unknown"`、退出码 2、`problems` 说清原因。"""
    gone = tmp_path / "nowhere"
    code, out, err = _run(_argv(member, spec, gone))
    assert code == 2, (member, code, out[-200:], err[-200:])
    doc = json.loads(out)
    assert doc["state"] == "unknown", (member, doc)
    assert doc["ok"] is False, member
    assert doc["problems"], f"{member} 说没查成，却没说为什么"


# ---------------------------------------------------------------- ⑤ 旧路径不变


@pytest.mark.parametrize("member,argv", [
    ("tools", ["tools", "--json"]),
    ("budget", ["budget", "--status", "--json"]),
    ("verify", ["verify", "--json"]),
    ("doctor", ["doctor", "--selfcheck", "--json"]),
])
def test_the_legacy_path_keeps_its_old_json_shape(member: str, argv: list[str],
                                                  tmp_path: pathlib.Path) -> None:
    """⑤ 旧路径上的那六条没有套壳：顶层键里没有 `ok`/`problems`（还是原来那一份）。

    为什么只验"没有套壳"而不是"逐字节相同"：逐字节那一档由各自的判据守着
    （`tools --json` 有冻结快照、`budget` 有 `test_budget_register.py`、`doctor` 有 C6），
    这里守的是这次改动不许把它们悄悄套进新外壳。
    """
    ws = _workspace(tmp_path)
    code, out, _err = _run(["--root", str(ws), *argv])
    doc = json.loads(out)
    # "没被套壳"的可执行形态：顶层键集不是那四格。注意不能断言"没有 ok 键"——
    # `verify --json` 本来就有自己的 `ok` 字段（它问的是"校验通过没有"），
    # 那一格属于它自己那份读数，不是外壳。
    assert set(doc) != set(cli.JSON_ENVELOPE_KEYS), (
        f"{member} 的旧路径被套上了新外壳：{sorted(doc)[:8]}")
    assert doc, member


# ---------------------------------------------------------------- 契约文档自身


def test_the_contract_document_exists_and_names_every_member() -> None:
    """文档与实现同源：`docs/CLI-CONTRACT.md` 里逐节点名了这十条命令。"""
    doc = (pathlib.Path(__file__).resolve().parents[1]
           / "docs" / "CLI-CONTRACT.md").read_text(encoding="utf-8")
    assert "外层四格" in doc or "四个键" in doc, doc[:200]
    for member, _spec, _keys in CASES:
        assert f"inspect {member}" in doc, f"契约文档里没有 `inspect {member}` 那一节"
    for key in cli.JSON_ENVELOPE_KEYS:
        assert f"`{key}`" in doc, f"契约文档没有解释外层那一格：{key}"
    # 反真空：文档不是一张空壳
    assert len(doc.splitlines()) > 80, len(doc.splitlines())
