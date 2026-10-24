# -*- coding: utf-8 -*-
"""判据：`agentflow stats` 的四张读数与一条合计（业主批的 CLI 更新方案 D）。

四张表：`errors`（错误动作）／`flow`（动作、被拦、转投）／`cost`（钱与 token 的分布）／
`gates`（收工门八格三态）。它们必须一起成立才算"读数能用"：

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① | 四张各自跑得通（人读表与 `--json` 两种呈现） | 有一张只在 `--json` 那档能用 |
| ② | `--json` 的键集逐字等于 `readouts` 里那份常量 | 网页与 CLI 各自加一格，两处都"能用" |
| ③ | 空工作区 ⇒ 全 0 且 `state="checked"` | 把"空的"读成"没查到" |
| ④ | 工作区不存在 ⇒ `state="unknown"` 且退出码 2 | 用户读到"这一趟 0 次错误" |
| ⑤ | `stats all` 的三态是合取（有一条 unknown 就整条 unknown） | 三张可信一张不可信，合计说"查过了" |
| ⑥ | `stats errors` 的老形态与 `--readout` 新形态数值一致 | 两套口径同时存在，谁也不报错 |

第 ⑥ 条为什么必须有：`errors` 那一档"老形态逐字节不变"是本轮的硬纪律，而它同时又是
新四张表里的一张 —— 两处一旦算出不同的数，用户看到的就是"同一个问题两个答案"，
并且没有任何一条既有判据会因此变红。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import cli
from agentflow import readouts as R

#: 四张表的名字（顺序即 `agentflow stats all` 的呈现顺序）。
KINDS: tuple[str, ...] = ("errors", "flow", "cost", "gates")


# ---------------------------------------------------------------- 夹具


def _events(root: pathlib.Path, rows: list[dict]) -> None:
    path = root / "data" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"seq": i, "ts": "2026-10-24T05:20:09+08:00", "op": "upsert",
                         "table": "tasks", "row": row, "actor": "conductor"},
                        ensure_ascii=False) for i, row in enumerate(rows, 1)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sessions(root: pathlib.Path, records: list[dict]) -> None:
    path = root / "sessions" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")


def _ledger(root: pathlib.Path) -> None:
    from agentflow import schema as S

    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "usage_ledger.json").write_text(json.dumps({
        "schema_version": S.SCHEMA_VERSION,
        "rows": [{"usage_id": "u-000001", "scope": "summon", "role": "M", "task_id": None,
                  "tokens_in": 10, "tokens_out": 5, "tokens_total": 15, "usd": 0.5,
                  "attempts": 1, "at": "2026-10-24T05:20:09+08:00", "note": "",
                  "idem_key": ""}]}, ensure_ascii=False), encoding="utf-8")


def _fixture_workspace(root: pathlib.Path) -> pathlib.Path:
    """一个四张表都读得到东西的工作区。"""
    root.mkdir(parents=True, exist_ok=True)
    _events(root, [{"task_id": "t-000001", "role": "V", "called_by": "A", "outcome": "refused",
                    "refusal_reason": "forbidden_edge", "detail": "A → V 不在允许的边里",
                    "error": None}])
    _sessions(root, [
        {"kind": "agent_step", "role": "C", "index": 1, "shape": "tool",
         "payload": {"name": "analysis.hottest"}, "result": {"ok": True}},
        {"kind": "agent_step", "role": "C", "index": 2, "shape": "tool",
         "payload": {"name": "nope"}, "result": {"ok": False, "error": "没有这件工具"}},
    ])
    _ledger(root)
    return root


def _run(argv: list[str], capsys) -> tuple[int, str, str]:
    code = cli.main(argv)
    got = capsys.readouterr()
    return code, got.out, got.err


def _argv(kind: str, ws: pathlib.Path, *, json_out: bool = False,
          readout: bool = False) -> list[str]:
    """拼一条 stats 命令。

    `errors` 那一档有个刻意的例外：不给 `--readout` 时它按老形态打（`errorstats` 的
    原文），所以"新五键形状"的判据都要带上这个开关 —— 这不是绕路，正是本轮
    "老形态逐字节不变、新形状另开一档"那条纪律的机器读数。
    """
    argv = ["stats", kind, "--root", str(ws)]
    if kind == "errors" and readout:
        argv.append("--readout")
    if json_out:
        argv.append("--json")
    return argv


# ---------------------------------------------------------------- ① 四张各自能跑


def test_each_of_the_four_tables_runs_in_both_presentations(tmp_path: pathlib.Path,
                                                            capsys) -> None:
    """① 四张各自都能跑：人读表非空、`--json` 可解析，退出码 0。"""
    ws = _fixture_workspace(tmp_path / "ws")
    for kind in KINDS:
        code, out, err = _run(_argv(kind, ws, readout=True), capsys)
        assert code == 0, (kind, code, err)
        assert out.strip(), f"{kind} 的人读表是空的：{err}"
        code, out, err = _run(_argv(kind, ws, json_out=True, readout=True), capsys)
        assert code == 0, (kind, code, err)
        doc = json.loads(out)  # 混进人话会当场炸在这里
        assert doc["checked"] is True, (kind, doc)


# ---------------------------------------------------------------- ② 键集稳定


def test_the_json_key_sets_are_the_documented_constants(tmp_path: pathlib.Path, capsys) -> None:
    """② `--json` 的键集逐字等于 `readouts` 的那份常量（写进测试常量，不手抄）。"""
    ws = _fixture_workspace(tmp_path / "ws")
    for kind in KINDS:
        code, out, _err = _run(_argv(kind, ws, json_out=True, readout=True), capsys)
        assert code == 0, kind
        doc = json.loads(out)
        assert tuple(doc) == R.READOUT_KEYS, (kind, tuple(doc))
        assert set(doc["data"]) == set(R.READOUT_DATA_KEYS[kind]), (
            kind, set(doc["data"]) ^ set(R.READOUT_DATA_KEYS[kind]))
    code, out, _err = _run(_argv("all", ws, json_out=True), capsys)
    assert code == 0
    doc = json.loads(out)
    assert tuple(doc) == R.READOUT_KEYS, tuple(doc)
    assert tuple(doc["data"]) == R.ALL_DATA_KEYS, tuple(doc["data"])


# ---------------------------------------------------------------- ③④ 三态


def test_an_empty_workspace_is_all_zero_and_checked(tmp_path: pathlib.Path, capsys) -> None:
    """③ 空工作区 ⇒ 全 0 且 `state="checked"`（0 与 unknown 是两件事）。"""
    from agentflow.store import Store

    ws = tmp_path / "empty"
    Store(ws).init()
    for kind in KINDS:
        code, out, err = _run(["stats", kind, "--root", str(ws), "--json"], capsys)
        assert code == 0, (kind, code, err)
        assert json.loads(out)["state"] == "checked", kind
    code, out, err = _run(["stats", "cost", "--root", str(ws), "--json"], capsys)
    assert json.loads(out)["data"]["total"]["usd"] == 0.0


def test_a_missing_workspace_is_unknown_and_exits_two(tmp_path: pathlib.Path, capsys) -> None:
    """④ 工作区不存在 ⇒ `state="unknown"`、退出码 2，且 stderr 说清"0 不是没有"。"""
    gone = tmp_path / "nowhere"
    for kind in KINDS + ("all",):
        code, out, err = _run(["stats", kind, "--root", str(gone), "--json"], capsys)
        assert code == 2, (kind, code, out[-200:])
        doc = json.loads(out)
        assert doc["state"] == "unknown", (kind, doc["state"])
        assert doc["checked"] is False, kind
        assert doc["reason"], kind
        assert "没查成" in err, (kind, err[-200:])


# ---------------------------------------------------------------- ⑤ 合计是合取


def test_all_is_a_conjunction_of_the_four_tables(tmp_path: pathlib.Path,
                                                 monkeypatch: pytest.MonkeyPatch,
                                                 capsys) -> None:
    """⑤ `stats all` 的三态是合取：底下一张没查成就整条 unknown（部分成立不等于成立）。"""
    ws = _fixture_workspace(tmp_path / "ws")
    code, out, err = _run(["stats", "all", "--root", str(ws), "--json"], capsys)
    assert code == 0 and json.loads(out)["checked"] is True, (code, err)

    real = R.cost_readout
    monkeypatch.setitem(R.READOUTS, "cost",
                        lambda *_a, **_k: R._envelope(checked=False, reason="打桩：钱那一格没查成",
                                                      data=dict.fromkeys(
                                                          R.COST_DATA_KEYS, {})))
    try:
        code, out, err = _run(["stats", "all", "--root", str(ws), "--json"], capsys)
        assert code == 2, (code, out[-300:])
        doc = json.loads(out)
        assert doc["checked"] is False and doc["state"] == "unknown", doc
        assert "cost" in doc["reason"], doc["reason"]
    finally:
        monkeypatch.setitem(R.READOUTS, "cost", real)


# ---------------------------------------------------------------- ⑥ 老形态与新形态对数


def test_the_legacy_errors_shape_agrees_with_the_readout(tmp_path: pathlib.Path,
                                                         capsys) -> None:
    """⑥ `stats errors`（老形态）与 `stats errors --readout`（新五键）数值与三态一致。"""
    ws = _fixture_workspace(tmp_path / "ws")
    code, legacy, _err = _run(["stats", "errors", "--root", str(ws), "--json"], capsys)
    assert code == 0
    old = json.loads(legacy)
    code, new, _err = _run(["stats", "errors", "--root", str(ws), "--json", "--readout"], capsys)
    assert code == 0
    fresh = json.loads(new)
    assert old["total"] == fresh["data"]["total"], (old["total"], fresh["data"]["total"])
    assert old["state"] == fresh["state"], (old["state"], fresh["state"])
    assert old["by_role"] == fresh["data"]["by_role"], (old["by_role"], fresh["data"]["by_role"])
    # 反真空：这份夹具上确实是 1 条，两边都不能是 0
    assert fresh["data"]["total"] == 1, fresh["data"]["total"]


# ---------------------------------------------------------------- 人读的呈现


def test_the_human_tables_name_their_own_shape(tmp_path: pathlib.Path, capsys) -> None:
    """人读表里每一张都写着自己的名字与三态（否则四张表长得一样，读的人分不出）。"""
    ws = _fixture_workspace(tmp_path / "ws")
    for kind in KINDS + ("all",):
        code, out, err = _run(_argv(kind, ws, readout=True), capsys)
        assert code == 0, (kind, err)
        if kind == "all":
            for one in KINDS:
                assert f"读数 {one}" in out, (kind, one, out[:200])
        else:
            assert f"读数 {kind}" in out, (kind, out[:200])
            assert "三态" in out, (kind, out[:200])
