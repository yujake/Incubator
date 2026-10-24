# -*- coding: utf-8 -*-
"""判据：四个只读读数共用同一个外层形状（`agentflow.readouts`，业主裁定的 F 那一层）。

## 这一份守什么

这一层存在的理由只有一个：同一个数不许有两份实现（CLI 一份、网页一份）。
形状统一本身不是读数，所以每条判据都翻成一个能红的断言：

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① | 四条读数逐字给齐 `checked` / `state` / `reason` / `data` / `problems` | 网页读到的那份少一格，CLI 那份多一格，两边各自"能用" |
| ② | 读不到 ⇒ `checked=False` 且 `state="unknown"`，不折成一张全 0 的表 | 用户读到"这一趟 0 次错误"，而实际是工作区不存在 |
| ③ | 反真空：把底下两处扫描打桩成"什么都没报告"，四条读数必须一起变红 | 扫描坏了，四条读数照样"全 0，通过" |
| ④ | 这一层不 import 呈现层（`cli` / `webui`） | 口径又有了两个主人（循环依赖只是症状） |
| ⑤ | 空工作区是正控：初始化过、没有内容 ⇒ 全 0 且 `checked=True` | 把"空的"与"没读到"折成同一档 |

## 为什么 ③ 要打桩在 `errorstats` 的读取函数上，而不是打桩 `readouts.scan`

`scan` 只是把 `errorstats._read_events` / `_read_sessions` 的读数拼起来 —— 那两处是
"事件流与会话记录怎么读、读不成算哪一档"的唯一真身。打桩打在真身上，才等于
"底下的扫描真的坏了"；打桩在 `scan` 上只证明 `scan` 的返回值被检查过。
四条读数都必须因此变红：一条读数说"没查成"而另一条照样给 0，就是两套三态又回来了。
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from agentflow import errorstats as ES
from agentflow import readouts as R

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"

#: 四条读数的名字（顺序即 `agentflow stats` 的呈现顺序）。
KINDS: tuple[str, ...] = ("errors", "flow", "cost", "gates")


# ---------------------------------------------------------------- 夹具


def _write_events(root: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    """写一份事件流（一行一个 upsert，与 `Store._append_events` 同形）。"""
    path = root / "data" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"seq": i, "ts": "2026-10-24T05:20:09+08:00", "op": "upsert",
                         "table": "tasks", "row": row, "actor": "conductor"},
                        ensure_ascii=False)
             for i, row in enumerate(rows, 1)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _task(task_id: str, role: str, called_by: str, **kw) -> dict:
    row = {"task_id": task_id, "role": role, "called_by": called_by, "outcome": "refused",
           "refusal_reason": None, "detail": "", "error": None}
    row.update(kw)
    return row


def _write_sessions(root: pathlib.Path, records: list[dict]) -> pathlib.Path:
    path = root / "sessions" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")
    return path


def _fixture_workspace(root: pathlib.Path) -> pathlib.Path:
    """一个四条读数都能读到东西的工作区（每条读数至少一格非 0）。"""
    root.mkdir(parents=True, exist_ok=True)
    _write_events(root, [
        _task("t-000001", "V", "A", refusal_reason="forbidden_edge",
              detail="A → V 不在策略允许的边里（A 只能召唤 ['B', 'D']）"),
        _task("t-000002", "B", "M", refusal_reason="invalid_params", outcome="failed",
              detail="relations 行校验失败：concept_ids 声明为集合但未升序去重"),
    ])
    _write_sessions(root, [
        {"kind": "agent_step", "role": "C", "index": 1, "shape": "tool",
         "payload": {"name": "analysis.hottest"},
         "result": {"tool": "analysis.hottest", "ok": True, "rows": 3}},
        {"kind": "agent_step", "role": "C", "index": 2, "shape": "tool",
         "payload": {"name": "analysis.register_conjecture"},
         "result": {"tool": "analysis.register_conjecture", "ok": False,
                    "error": "没有名为 'register_conjecture' 的工具"}},
        {"kind": "agent_step", "role": "G", "index": 3, "shape": "final",
         "payload": {"final": "交稿"}, "result": {"ok": True}},
        {"kind": "agent_message", "role": "G", "from": "G", "to": "M",
         "subject": "请代唤 V：这条边被拒，改派 V 复核"},
    ])
    # 钱：一行 summon（M 花的）、一行 review（H 花的）
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "usage_ledger.json").write_text(json.dumps({
        "schema_version": ES.S.SCHEMA_VERSION,
        "rows": [
            {"usage_id": "u-000001", "scope": "summon", "role": "M", "task_id": "t-000001",
             "tokens_in": 100, "tokens_out": 50, "tokens_total": 150, "usd": 0.0125,
             "attempts": 1, "at": "2026-10-24T05:20:09+08:00", "note": "", "idem_key": ""},
            {"usage_id": "u-000002", "scope": "review", "role": "H", "task_id": None,
             "tokens_in": 20, "tokens_out": 10, "tokens_total": 30, "usd": 0.002,
             "attempts": 2, "at": "2026-10-24T05:20:10+08:00", "note": "", "idem_key": ""},
        ]}, ensure_ascii=False), encoding="utf-8")
    return root


# ---------------------------------------------------------------- ① 五个键


def test_all_four_readouts_carry_exactly_the_five_keys(tmp_path: pathlib.Path) -> None:
    """① 四条读数都返回那五个键，且 `state` 与 `checked` 一一对应。"""
    ws = _fixture_workspace(tmp_path / "ws")
    for kind in KINDS:
        got = R.READOUTS[kind](ws)
        assert isinstance(got, dict), (kind, type(got))
        assert tuple(got) == R.READOUT_KEYS, (kind, tuple(got))
        assert set(got["data"]) == set(R.READOUT_DATA_KEYS[kind]), (
            kind, set(got["data"]) ^ set(R.READOUT_DATA_KEYS[kind]))
        assert isinstance(got["problems"], list), kind
        assert got["state"] == ("checked" if got["checked"] else "unknown"), kind
        if got["checked"]:
            assert got["reason"] == "", (kind, got["reason"])
        else:
            assert got["reason"], f"{kind} 说没查成，却没说为什么"


def test_the_readouts_are_really_non_zero_on_this_fixture(tmp_path: pathlib.Path) -> None:
    """反真空的正面：夹具里每条读数都必须有非 0 的地方（否则上面的断言是空转）。"""
    ws = _fixture_workspace(tmp_path / "ws")
    errors = R.errors_readout(ws)
    assert errors["data"]["total"] >= 2, errors["data"]["total"]
    assert "B" in errors["data"]["by_role"] or "A" in errors["data"]["by_role"]

    flow = R.flow_readout(ws)
    assert flow["data"]["totals"]["steps"] == 3, flow["data"]["totals"]
    assert flow["data"]["roles"]["C"]["blocked"] == 1, flow["data"]["roles"]
    assert flow["data"]["roles"]["G"]["relayed"] == 1, flow["data"]["roles"]

    cost = R.cost_readout(ws)
    assert cost["data"]["total"]["rows"] == 2, cost["data"]["total"]
    assert cost["data"]["total"]["tokens_total"] == 180, cost["data"]["total"]
    assert set(cost["data"]["by_scope"]) == {"summon", "review"}, cost["data"]["by_scope"]
    assert cost["data"]["by_role"]["M"]["usd"] == pytest.approx(0.0125, abs=1e-9)

    gates = R.gates_readout(ws)
    assert len(gates["data"]["cells"]) == 8, gates["data"]["cells"]
    assert {c["name"] for c in gates["data"]["cells"]} == set(
        __import__("agentflow.closing", fromlist=["_"]).DEFAULT_CHECKS)
    assert sum(gates["data"]["counts"].values()) == 8, gates["data"]["counts"]


# ---------------------------------------------------------------- ② 读不到 ⇒ unknown


def test_unreadable_workspaces_are_unknown_not_zero(tmp_path: pathlib.Path) -> None:
    """② 工作区不存在 ⇒ 四条读数全是 unknown，一条都不许折成 0 的"正常表"。"""
    missing = tmp_path / "nowhere"
    for kind in KINDS:
        got = R.READOUTS[kind](missing)
        assert got["checked"] is False, (kind, got)
        assert got["state"] == "unknown", (kind, got["state"])
        assert got["reason"], kind
    # 事件流坏了（不是不存在）：同样不许读成 0
    broken = tmp_path / "broken"
    (broken / "data").mkdir(parents=True)
    (broken / "data" / "events.jsonl").write_text("{ 这不是 JSON\n", encoding="utf-8")
    for kind in KINDS:
        got = R.READOUTS[kind](broken)
        assert got["checked"] is False, (kind, got)


# ---------------------------------------------------------------- ③ 反真空


def test_stubbing_the_bottom_scan_makes_all_four_readouts_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 反真空：底下两处扫描"什么都没报告" ⇒ 四条读数必须一起变红。

    打桩的返回值刻意给空字典（连 `checked` 都不给）：这正是"扫描没跑成"在读数上的形态。
    如果哪条读数在这种情况下还给一张全 0 且 `checked=True` 的表，它就是把
    "没扫到"读成了"没有"——那正是三态纪律禁止的那件事。
    """
    ws = _fixture_workspace(tmp_path / "ws")
    for kind in KINDS:  # 先证明这个夹具原本是查得成的（否则下面的红是假红）
        assert R.READOUTS[kind](ws)["checked"] is True, kind

    monkeypatch.setattr(ES, "_read_events", lambda *a, **k: ([], {}))
    monkeypatch.setattr(ES, "_read_sessions", lambda *a, **k: ([], {}))
    for kind in KINDS:
        got = R.READOUTS[kind](ws)
        assert got["checked"] is False, f"{kind} 在扫描什么都没报告时仍然说查过：{got}"
        assert got["state"] == "unknown", (kind, got["state"])
        assert "扫描" in got["reason"] or "没读" in got["reason"], (kind, got["reason"])


# ---------------------------------------------------------------- ④ 不 import 呈现层


def test_the_readouts_module_does_not_import_a_presentation_layer() -> None:
    """④ 这一层不 import `cli` / `webui`（口径只许有一个主人）。

    扫的是真的 import 语句（AST），不是文本里出现过那两个词：注释里写"CLI 也读它"
    是应该的，`import cli` 才是那件事。
    """
    tree = ast.parse((SRC / "readouts.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            # `from . import errorstats` 的 `module` 是空串、`level` 是 1：
            # 相对 import 必须按"包内模块"记，否则这条扫描器看不见包内依赖。
            base = str(node.module or "")
            if node.level:
                base = "agentflow" + (f".{base}" if base else "")
            if base:
                imported.add(base)
            imported |= {f"{base}.{a.name}" if base else a.name for a in node.names}
    banned = {name for name in imported
              if name.split(".")[-1] in {"cli", "webui"}
              or name.startswith(("agentflow.cli", "agentflow.webui"))
              or name.split(".")[0] in {"cli", "webui"}}
    assert not banned, f"readouts.py 里 import 了呈现层：{sorted(banned)}（口径会变成两个主人）"
    # 反真空：这份扫描器真的读到了 import（否则上面那句恒绿）
    assert any("errorstats" in name for name in imported), sorted(imported)


# ---------------------------------------------------------------- ⑤ 空工作区是正控


def test_an_empty_workspace_is_all_zero_and_checked(tmp_path: pathlib.Path) -> None:
    """⑤ 初始化过、没有内容 ⇒ 全 0 且 `checked=True`（0 与 unknown 分得开）。"""
    from agentflow.store import Store

    ws = tmp_path / "empty"
    Store(ws).init()
    for kind in KINDS:
        got = R.READOUTS[kind](ws)
        assert got["checked"] is True, (kind, got["reason"])
        assert got["state"] == "checked", kind
    assert R.errors_readout(ws)["data"]["total"] == 0
    assert R.flow_readout(ws)["data"]["totals"]["steps"] == 0
    assert R.cost_readout(ws)["data"]["total"]["usd"] == 0.0
    cells = R.gates_readout(ws)["data"]["cells"]
    assert len(cells) == 8 and all(c["status"] in R.CELL_STATES for c in cells)


# ---------------------------------------------------------------- 呈现


def test_every_readout_renders_a_table_from_its_own_data(tmp_path: pathlib.Path) -> None:
    """呈现层也只许从 `data` 取数：四条读数各自渲染得出来，且没查成时说清"不是没有"。"""
    ws = _fixture_workspace(tmp_path / "ws")
    for kind in KINDS:
        lines = R.render_readout(kind, R.READOUTS[kind](ws))
        assert lines and isinstance(lines[0], str), kind
        assert any(kind in line for line in lines), (kind, lines[:2])
    unknown = R.render_readout("errors", R.errors_readout(tmp_path / "gone"))
    assert any("不是" in line and "没查成" in line for line in unknown), unknown
