# -*- coding: utf-8 -*-
"""判据：按角色的错误动作计数（`agentflow.errorstats`）。

这六条判据各钉一件事，缺一条这个统计量就会以某种方式说谎：

1. 按角色分开计数 —— A 派 V 越权，错算 A 的，不算 V 的；三类真实拒绝各进自己的类目。
2. 同一事件命中两条判据只算一次 —— 主码规则（类目表靠前的优先，同类目里长码优先）。
3. 空工作区 ⇒ 全 0 且 `state="checked"` —— 正控：0 不是 unknown。
4. 工作区不存在 / 事件流读不到 / 会话文件读不明白 ⇒ `checked=False`、`state="unknown"` ——
   负控：不许把"没读到"折成 0。
5. 反真空 —— 把码到类目那张表打桩成空，第 1 条判据必须红（否则计数是硬编码出来的）。
6. 类目不凭空造 —— 每一类（错误类目与过程读数类目两张表）都要有一个码，且那个码真的出现在
   `src/agentflow/` 的某个文件里（扫的时候排除 `errorstats.py` 本身）。

第 6 条为什么必须排除本模块：`CODE_TABLE` 自己就写着那些码，不排除的话"表里有的码
一定在源码里"是同一句话的自己证明自己，防不住"编出来的类目"。

两张类目表的分工见 `errorstats` 模块 docstring（错误类目进 total；`PROCESS_CATEGORIES`
是拆分的过程读数、不进 total —— 业主 D-65）。第 6 条对两张表一视同仁：
过程读数也不许是编出来的名字，它的码同样要能在生产侧找到。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import errorstats as ES

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"


# ---------------------------------------------------------------- 夹具（真实拒绝形状）


def _task(task_id: str, role: str, called_by: str, *, outcome: str = "refused",
          refusal_reason: str | None = None, detail: str = "",
          error: str | None = None) -> dict:
    """一行 `tasks`（键序与盘上真行一致；真机现场见 `projects/r34d` 的 t-000019）。"""
    return {
        "task_id": task_id, "role": role, "action": "unknown", "called_by": called_by,
        "parent_task_id": None, "depth": 3, "input_key": f"@{task_id}",
        "status": "done", "outcome": outcome, "refusal_reason": refusal_reason,
        "instance": "", "detail": detail, "error": error,
        "started_at": "2026-10-24T05:20:09+08:00", "ended_at": "2026-10-24T05:20:09+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
        "kind": "", "expects": "", "item_state": "", "item_close": "",
        "seen_by": "", "seen_step": None, "keep_alive": False,
    }


def _write_events(root: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    """把若干 `tasks` 行写成事件流（一行一个 upsert，与 `Store._append_events` 同形）。"""
    path = root / "data" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for seq, row in enumerate(rows, 1):
        lines.append(json.dumps({
            "seq": seq, "ts": "2026-10-24T05:20:09+08:00", "batch": f"2026-10-24T05:20:09+08:00-1-{seq}",
            "op": "upsert", "table": "tasks", "row": row, "actor": "conductor",
            "note": f"refused:{row.get('refusal_reason') or ''}",
        }, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_sessions(root: pathlib.Path, records: list[dict]) -> pathlib.Path:
    """写一份会话记录（`agent_step` / `llm_call` / `agent_message` 三种真形状）。"""
    path = root / "sessions" / "s1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                    encoding="utf-8")
    return path


def _fixture_workspace(root: pathlib.Path) -> pathlib.Path:
    """三类真实拒绝 + 一条会话侧的工具面拒绝。四条都属于四个不同的角色。"""
    root.mkdir(parents=True, exist_ok=True)
    _write_events(root, [
        # ① 结构性拒绝：A 越权派 V（真机拒信原文形态，见 `policy.py:455`）
        _task("t-000001", "V", "A", refusal_reason="forbidden_edge",
              detail="A → V 不在策略允许的边里（A 只能召唤 ['B', 'D']）；"
                     "改派 B —— 它能替你派 V（政策指定的绕路，别再重试这条边）"),
        # ② 写库野路：B 拿通用写口直写 statements（`store.DIRECT_WRITE_REFUSED`）
        _task("t-000002", "B", "M", refusal_reason="invalid_params",
              detail="direct_write_refused：`statements` 不由通用写口直写"
                     "（table.create / table.update 以及任何带 tool: 记号的裸事务）"
                     "—— 它只有一条正路：Secretary.record_statement"),
        # ③ 写入期 schema 校验失败（`tools/table_tools.py:116` 的 ToolError 原文）
        _task("t-000003", "B", "M", refusal_reason="invalid_params",
              detail="relations 行校验失败：concept_ids 声明为集合但未升序去重：['000003', '000002']"),
    ])
    _write_sessions(root, [
        # ④ 工具面没有这件工具（真机原文，见 `tools/base.py:802`）
        {"kind": "agent_step", "role": "C", "index": 7, "shape": "tool",
         "payload": {"name": "analysis.register_conjecture"},
         "result": {"tool": "analysis.register_conjecture", "ok": False,
                    "error": "没有名为 'register_conjecture' 的工具；"
                             "并列候选（1 个）：['analysis.register_conjecture']"}},
    ])
    return root


# ---------------------------------------------------------------- ① 按角色分开计数


def test_rejections_are_counted_per_role_and_per_category(tmp_path: pathlib.Path) -> None:
    """三类真实拒绝各进自己的类目，且记在"错的那一方"头上。"""
    ws = _fixture_workspace(tmp_path / "ws")
    stats = ES.error_action_stats(ws)

    assert stats.checked is True
    assert stats.state == "checked"
    assert stats.reason == ""

    # A 派 V 越权 ⇒ 算 A 的错
    assert stats.count("A", "forbidden_edge") == 1
    # V 只是被派的那一方：一条都不该记到它头上（这条是"按角色记"的全部意义）
    assert stats.by_role.get("V", {}) == {}
    assert stats.role_total.get("V", 0) == 0
    # B 的两条各进自己的类目，且没有互相串味
    assert stats.count("B", "direct_write") == 1
    assert stats.count("B", "schema_invalid") == 1
    assert stats.count("B", "controlled_refusal") == 0
    assert stats.role_total["B"] == 2
    # 会话侧的"没有这件工具"记在 C 头上
    assert stats.count("C", "unknown_tool") == 1
    assert stats.total == 4
    # 类目合计与角色合计是同一份数的两个投影
    assert stats.category_total("direct_write") == 1
    assert sum(stats.role_total.values()) == stats.total


def test_the_machine_readable_shape_carries_the_three_state(tmp_path: pathlib.Path) -> None:
    """`as_dict()` 必须同时给 by_role / role_total / total / checked / state / reason。"""
    stats = ES.error_action_stats(_fixture_workspace(tmp_path / "ws"))
    payload = stats.as_dict()
    assert set(payload) >= {"by_role", "role_total", "total", "checked", "state", "reason",
                            "sources"}
    assert payload["by_role"]["A"] == {"forbidden_edge": 1}
    assert payload["role_total"]["B"] == 2
    assert payload["total"] == 4
    assert payload["checked"] is True and payload["state"] == "checked"
    assert json.loads(ES.stats_json(stats))["total"] == 4


def test_counts_come_from_the_actor_that_attempted_the_call(tmp_path: pathlib.Path) -> None:
    """召唤期结构判据记 called_by；角色自己回执的那一档记 role。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    _write_events(ws, [
        # 召唤期：G 派 B 被禁边拒 ⇒ 记 G
        _task("t-000001", "B", "G", refusal_reason="forbidden_edge",
              detail="G → B 不在策略允许的边里（G 只能召唤 ['A', 'D', 'E', 'F']）"),
        # 角色自己的动作回执：B 这条 invalid_params 不是"谁派错了边" ⇒ 记 B
        _task("t-000002", "B", "G", refusal_reason="invalid_params",
              detail="proof_text 不能为空"),
    ])
    stats = ES.error_action_stats(ws)
    assert stats.count("G", "forbidden_edge") == 1
    assert stats.count("B", "controlled_refusal") == 1
    assert stats.count("B", "forbidden_edge") == 0


# ---------------------------------------------------------------- ② 一条只算一次


def test_one_record_hits_two_criteria_but_counts_once(tmp_path: pathlib.Path) -> None:
    """同一行同时带两层码（invalid_params + 行校验失败 + direct_write_refused）⇒ 只算一次。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    _write_events(ws, [
        _task("t-000001", "B", "M", refusal_reason="invalid_params",
              detail="direct_write_refused：`statements` 不由通用写口直写；"
                     "另：relations 行校验失败：concept_ids 未升序去重"),
    ])
    stats = ES.error_action_stats(ws)
    # 三次命中、一条记录 ⇒ 只 +1，且落在类目表最靠前的那一类（写库野路）
    assert stats.total == 1
    assert stats.count("B", "direct_write") == 1
    assert stats.count("B", "schema_invalid") == 0
    assert stats.count("B", "controlled_refusal") == 0


def test_the_primary_code_rule_is_pinned() -> None:
    """主码规则本身：类目表靠前的类目优先，同类目里字数长的码优先。"""
    # 结构性判据压过写入期判据（根因先看）
    assert ES.primary_code("forbidden_edge", "relations 行校验失败：…") == (
        "forbidden_edge", "forbidden_edge")
    # 写入期判据压过"受控拒绝"这个粗码
    assert ES.primary_code("invalid_params", "relations 行校验失败：…") == (
        "行校验失败", "schema_invalid")
    # 同类目里长码胜出（judge_not_wired 不会被 not_wired 抢先）
    assert ES.primary_code("judge_not_wired") == ("judge_not_wired", "not_wired")
    # 没命中就是没命中，不许猜一个类目出来
    assert ES.primary_code("执行完成") is None
    assert ES.primary_code(None, "", "  ") is None


# ---------------------------------------------------------------- ③ 空工作区是正控


def test_an_empty_workspace_is_all_zero_and_checked(tmp_path: pathlib.Path) -> None:
    """正控：0 是"查过了、一条都没有"，不是 unknown。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "events.jsonl").write_text("", encoding="utf-8")
    stats = ES.error_action_stats(ws)
    assert stats.checked is True
    assert stats.state == "checked"
    assert stats.total == 0
    assert stats.by_role == {}
    assert stats.role_total == {}
    # 没有 sessions 目录是"这个工作区没有会话记录"的正常形态，不许当成"读不到"
    assert stats.sources["sessions"]["checked"] is True
    assert stats.sources["sessions"]["files"] == 0


# ---------------------------------------------------------------- ④ 三态负控


def test_a_missing_workspace_is_unknown_not_zero(tmp_path: pathlib.Path) -> None:
    """工作区不在盘上 ⇒ unknown（不是 0）。"""
    stats = ES.error_action_stats(tmp_path / "nowhere")
    assert stats.checked is False
    assert stats.state == "unknown"
    assert stats.total == 0
    assert "工作区不存在" in stats.reason


def test_a_missing_event_stream_is_unknown_not_zero(tmp_path: pathlib.Path) -> None:
    """工作区在、事件流不在 ⇒ unknown（不是 0）。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    stats = ES.error_action_stats(ws)
    assert stats.checked is False
    assert stats.state == "unknown"
    assert "事件流不存在" in stats.reason


def test_an_unreadable_event_stream_is_unknown_not_zero(tmp_path: pathlib.Path) -> None:
    """事件流每一行都读不明白 ⇒ unknown（不是 0）。"""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    (ws / "data" / "events.jsonl").write_text("这不是 JSON\n也不是\n", encoding="utf-8")
    stats = ES.error_action_stats(ws)
    assert stats.checked is False
    assert stats.state == "unknown"
    assert stats.sources["events"]["bad_lines"] == 2


def test_an_unreadable_session_file_is_unknown_not_zero(tmp_path: pathlib.Path) -> None:
    """事件流读得动、会话文件一个都读不明白 ⇒ 仍然是 unknown（半份读数不许冒充全量）。"""
    ws = _fixture_workspace(tmp_path / "ws")
    (ws / "sessions" / "s1.jsonl").write_bytes(b"\xff\xfe\x00bad bytes")
    stats = ES.error_action_stats(ws)
    assert stats.checked is False
    assert stats.state == "unknown"
    assert stats.sources["sessions"]["checked"] is False
    # 事件流那三行仍然被数出来 —— 但整份读数标成 unknown，不许当成"全量 3 条"
    assert stats.total == 3


# ---------------------------------------------------------------- ⑤ 反真空


def test_the_code_table_is_load_bearing(monkeypatch: pytest.MonkeyPatch,
                                        tmp_path: pathlib.Path) -> None:
    """把码到类目那张表打桩成空 ⇒ 第 1 条判据必红（计数不是硬编码出来的）。"""
    ws = _fixture_workspace(tmp_path / "ws")
    assert ES.error_action_stats(ws).total == 4
    # `_MATCH_ORDER` 是 `CODE_TABLE` 的唯一派生（同一个表的物化形态），一起清空。
    monkeypatch.setattr(ES, "CODE_TABLE", ())
    monkeypatch.setattr(ES, "_MATCH_ORDER", ())
    stubbed = ES.error_action_stats(ws)
    assert stubbed.total == 0
    assert stubbed.by_role == {}
    assert stubbed.checked is True, "打桩只该让计数变空，不该顺手把三态也弄成 unknown"


# ---------------------------------------------------------------- ⑥ 类目不许凭空造


def _source_texts() -> dict[str, str]:
    """`src/agentflow/` 下每个 .py 的正文（排除本模块自己，理由见文件 docstring）。"""
    out: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        if path.name == "errorstats.py":
            continue
        out[str(path)] = path.read_text(encoding="utf-8", errors="replace")
    return out


def test_every_category_has_a_code_that_really_exists_in_the_source() -> None:
    """每个类目都要有一个真实拒绝码，且那个码就在出处文件里（防"编出来的类目"）。

    两张类目表都查：错误类目与过程读数类目（拆分那两格也是读数，名字同样不许凭空造）。
    """
    source = _source_texts()
    assert source, "夹具前提变了：扫不到 src/agentflow 下的 .py"
    for category, meaning in ES.ERROR_CATEGORIES + ES.PROCESS_CATEGORIES:
        assert meaning.strip(), f"类目 {category} 没有写含义"
        assert "\n" not in meaning
        codes = [code for code, cat, _w in ES.CODE_TABLE if cat == category]
        assert codes, f"类目 {category} 在 CODE_TABLE 里一个码都没有 —— 那就是编出来的类目"
        found = False
        for code in codes:
            where = ES.CODE_PROVENANCE[code]
            paths = re.findall(r"src/agentflow/[\w/]+\.py", where)
            assert paths, f"{code} 的出处没写文件名：{where!r}"
            # `R-BE4`（2026-10-27 业主批准）：出处的口径从 `file:行号` 换成 `file::符号名`
            # —— 行号在并行开发下几十分钟就漂，而这条判据只看"有没有行号"，于是 80 行里
            # 64 行指着无关代码它也照样绿。符号名那一半由
            # `tests/test_errorstats_provenance_symbols_exist.py` 逐条核（文件里真有那个符号）。
            assert re.search(r"\.py::[A-Za-z_]", where), (
                f"{code} 的出处没给符号名（口径是 `file::symbol`）：{where!r}")
            for rel in paths:
                path = SRC.parents[1] / rel
                assert path.is_file(), f"{code} 的出处指向一个不存在的文件：{rel}"
                if code in source.get(str(path), ""):
                    found = True
        assert found, (
            f"类目 {category} 的码 {codes} 在出处文件里一个都找不到 —— "
            "要么码是编的，要么出处写错了")


def test_the_category_table_has_no_duplicate_or_unknown_categories() -> None:
    """表本身的自洽：码不重复、每个码的类目都在两张类目表里、类目无重复。

    两张表合起来就是 `ALL_CATEGORIES`（错误 ＋ 过程读数），码的类目只能落在这两者里 ——
    落不进去说明码表里有一个谁也不认的类目名（那种名字永远不会被数出来）。
    """
    cats = [cat for cat, _why in ES.ALL_CATEGORIES]
    assert len(cats) == len(set(cats)), f"类目重复：{cats}"
    assert ES.ALL_CATEGORIES == ES.ERROR_CATEGORIES + ES.PROCESS_CATEGORIES
    assert not (set(c for c, _w in ES.ERROR_CATEGORIES)
                & set(c for c, _w in ES.PROCESS_CATEGORIES)), "两张类目表不许有交集"
    codes = [code for code, _c, _w in ES.CODE_TABLE]
    assert len(codes) == len(set(codes)), "同一个码登记了两次（主码就不确定了）"
    for code, cat, where in ES.CODE_TABLE:
        assert cat in cats, f"{code} 的类目 {cat} 不在 ALL_CATEGORIES 里"
        assert where.strip(), f"{code} 没写出处"
    assert ES.CODE_TO_CATEGORY == {c: cat for c, cat, _w in ES.CODE_TABLE}


# ---------------------------------------------------------------- 呈现与 CLI 出口


def test_the_rendered_table_carries_roles_totals_and_the_three_state(
        tmp_path: pathlib.Path) -> None:
    """人读的那张小表必须带：角色行、合计行、类目释义、三态那一行。"""
    stats = ES.error_action_stats(_fixture_workspace(tmp_path / "ws"))
    text = "\n".join(ES.render_text(stats))
    assert "checked=True" in text and "state=checked" in text
    for needle in ("角色", "合计", "A", "B", "forbidden_edge", "写库野路"):
        assert needle in text, f"表里缺 {needle}\n{text}"
    assert "类目释义" in text
    # 合计那一行必须等于 total（同一份数的两种投影不许打架）
    total_line = [ln for ln in ES.render_text(stats) if ln.startswith("合计")][0]
    assert total_line.split()[-1] == str(stats.total), total_line

    unknown = ES.error_action_stats(tmp_path / "nowhere")
    unknown_text = "\n".join(ES.render_text(unknown))
    assert "state=unknown" in unknown_text
    assert "不是" in unknown_text and "没查成" in unknown_text, unknown_text


def test_the_cli_exit_code_separates_zero_from_unknown(tmp_path: pathlib.Path,
                                                       capsys) -> None:
    """`stats errors` 的退出码只分两档：0 查过了（含全 0）/ 2 没查成。"""
    from agentflow.cli import main as cli_main

    ws = _fixture_workspace(tmp_path / "ws")
    assert cli_main(["stats", "errors", "--root", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "错误动作计数" in out and "checked=True" in out

    # 机器可读那一份必须是可解析的 JSON，且三态跟着走
    assert cli_main(["stats", "errors", "--root", str(ws), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 4 and payload["state"] == "checked"

    # 工作区不存在 ⇒ 2（没查成），不是 0（"没有错误动作"）
    assert cli_main(["stats", "errors", "--root", str(tmp_path / "nowhere")]) == 2
    captured = capsys.readouterr()
    assert "unknown" in captured.err and "不是" in captured.err
    assert "错误动作计数" in captured.out, "人读的表仍然要打出来（0 与没读到要看得见）"
