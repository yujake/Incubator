# -*- coding: utf-8 -*-
"""L 的三个动作经 action 到 handler 的真派发（`formalize` / `check_formal` / `record`）。

## 这一份判什么

动作层：每一次都走 `Conductor.summon("L", "<动作>", {...}, by="B")` —— 它读
`specs/l.py::ACTIONS` 的 `handler_name`、经 `LocalBackend.call` 按名取到
`AgentL.<handler_name>` 再调用，并把这一趟落成 `tasks` 表一行与
`out/tasks/<task_id>.json`（这一份就是动作日志）。刻意不直接调 `AgentL` 的方法：
工具层那一路在 `tests/test_l_every_tool_and_action.py`。

| 动作 | 用例 | 正控 | 产物落盘 | 可被消费 | 可被登记 | 失败 / 拒绝路径 |
|---|---|---|---|---|---|---|
| `formalize` | `test_action_formalize_writes_the_same_artifacts_as_the_tool` | 与工具层同一剧本：返回体是工具层那一份的超集，status / checker_status / exit_code / coverage / b_library 逐格相同 | 两个工作区的 .lean 与 .steps.jsonl 的字节数 + sha256 完全一致 | `.steps.jsonl` 逐行读回（quote / lean_lines） | 同一份产物再派 `record` ⇒ experiments 一行，code_hash 与盘上一致 | `test_action_failure_and_refusal_paths_do_not_claim_ok` |
| `check_formal` | `test_action_check_formal_reads_the_checker_words_without_touching_disk` | verified=True、exit_code=0、verifier_output 是真 Lean 原话 | 只读：派发前后盘上文件清单与 .lean 的 sha256 一个字不变 | 它读的正是 `formalize` 落下的那一份 | 那段原话就是 `record` 写进那一行的同一串 | 见 `test_action_failure_and_refusal_paths_do_not_claim_ok`（`draft/146` D25 之后：failed 档不再被折成"执行中异常"且 payload 不丢；拒绝档在台账上是 `done/refused`） |
| `record` | `test_action_record_files_the_same_row_as_the_tool` | 与工具层同形：method / evidence_kind / claim_key / code_hash / exit_code / observations 逐格 | experiments 那一行的 code_hash 等于盘上 .lean 的 sha256 | 另一个 `Store` 读到、`closing` 的 proof 行读数读到 | 见左格 | `test_action_failure_and_refusal_paths_do_not_claim_ok` |

## 动作日志里能看见 tool 名

`tasks` 行与 `out/tasks/<id>.json` 记的是角色与动作（没有 tool 名这一格），所以
"不是空转"的那一条读数落在 `test_the_action_log_shows_the_tool_names`：用
`ScriptedGateway`（与真模型同接口、零次请求、零元）跑一趟 `run-agent L`，会话日志
`sessions/t.jsonl` 的每一步都带 `result.tool`，断言它真的是那两件工具名。这是
"L 的动作真的接到了工具面、没有空转"的机器读数；它不是 xfail，也不是空断言。

## 真 Lean 与零模型

真 Lean 用本机那一版绝对路径；不可用时需要检查器结论的那几条如实 skip 并写清原因。
模型调用只有最后一条（`ScriptedGateway`，价 0.0）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

#: 本机那一版真 Lean（绝对路径，不依赖 PATH）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()

CLAIM = "forall n : Nat, n + 0 = n"
STMT_ID = "000001"
LABEL = "加零不改变自然数"
STEPS = 12
LEAN_REL = "code/formal/add_zero_probe.lean"
STEPS_REL = "code/formal/add_zero_probe.steps.jsonl"
DECL_SHORT = "add_zero_probe"
DECL_FULL = "LProbe.add_zero_probe"
#: 工具层那一份返回值里的关键格（动作层的返回体是它的超集，逐格要比）。
KEY_READINGS = ("status", "checker_status", "checker_reason", "exit_code", "verified",
                "coverage", "b_library", "path", "sha256", "bytes", "steps_path",
                "statement_id", "statement_source", "faithfulness", "verifier_output")


# ============================================================ 夹具与小工具


def _proof_text(steps: int = STEPS) -> str:
    """`steps` 步的证明链：一步一段（空行分隔是切分口径的第一档）。"""
    return "\n\n".join(
        f"第 {k} 步：把第 {k - 1} 步的结论代入一次并化简。" for k in range(1, steps + 1))


def _source(mapped: int = STEPS, *, broken: bool = False) -> str:
    """Lean 源码：前 `mapped` 步各有一个独占一行的 `-- step k` 落点。"""
    body = "  exact (Nat.zero_add n)" if broken else "  rfl"
    lines = [
        "import Init.Data.Nat.Basic",
        "",
        "namespace LProbe",
        "",
        "/-- 加零不改变自然数。 -/",
        "theorem add_zero_probe (n : Nat) : n + 0 = n := by",
        body,
    ]
    for k in range(1, mapped + 1):
        lines.append(f"-- step {k}")
    lines += ["", "end LProbe", ""]
    return "\n".join(lines)


def _lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _skip_unless_usable(ws: pathlib.Path) -> None:
    from agentflow import leantoolchain as LT

    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条要真跑检查器，跳过（不伪装通过）")
    reading = LT.lean_selfcheck_reading(root=ws)
    if str(reading.get("state")) != "usable":
        pytest.skip(
            f"Lean 自检不是 usable（state={reading.get('state')}；"
            f"problems={reading.get('problems')}）⇒ 这一条要真跑检查器，跳过（不伪装通过）")


def _workspace(base: pathlib.Path) -> tuple[object, pathlib.Path]:
    """在 `base` 下建一个工作区，并让 B 登记一条 12 步证明的命题。"""
    from agentflow.store import Store

    ws = base / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    with st.tx("statements", actor="agent-B") as tx:
        tx.upsert("statements", {
            "stmt_id": STMT_ID,
            "label": LABEL,
            "statement": CLAIM,
            "statement_full": CLAIM,
            "proof_text": _proof_text(),
            "evidence_kind": "heuristic",
            "status": "active",
            "origin": "own_result",
            "quote_reason": "自产命题（这一组判据不涉及外部原文）",
        }, note="probe:statement")
    return st, ws


def _conductor(st: object, ws: pathlib.Path):
    """接了线的主控（L 在角色登记表里；B 是唯一能派它的角色）。"""
    from agentflow.host import wired_conductor
    from agentflow.tools.conductor_tools import reset_cache

    reset_cache()
    return wired_conductor(st, workspace_root=str(ws))


def _tool_layer(st: object, ws: pathlib.Path, name: str, **params: object) -> dict:
    """工具层同一剧本的那一次调用（用来与动作层的返回体逐格比）。"""
    from agentflow.agent_l import install_l_tools

    reg = install_l_tools(st, workspace_root=ws)
    res = reg.call(name, **params)
    assert res.ok is True, (name, res.ok, res.error, res.meta)
    return dict(res.data)


def _summon(cond: object, st: object, action: str, params: dict) -> tuple[object, dict, dict]:
    """派一次活，返回 `(SummonResult, payload, tasks 行)`。"""
    res = cond.summon("L", action, params, by="B")
    assert str(res.status) == "done", (res.status, res.outcome, res.detail)
    assert str(res.outcome) == "ok", (res.status, res.outcome, res.detail)
    assert isinstance(res.payload, dict), type(res.payload)
    row = next((dict(r) for r in st.rows("tasks")
                if str(r.get("task_id")) == str(res.task_id)), None)
    assert row is not None, f"派发没有落 tasks 行：{res.task_id}"
    return res, dict(res.payload), row


def _digest(ws: pathlib.Path, task_id: str) -> tuple[dict, int, str]:
    """动作日志：`out/tasks/<task_id>.json` 的真实路径 + 字节数 + sha256。"""
    path = ws / "out" / "tasks" / f"{task_id}.json"
    assert path.is_file(), f"派发没有落动作日志：{path}"
    raw = path.read_bytes()
    assert raw, f"{path} 是空文件"
    assert len(raw) == path.stat().st_size, (path, len(raw), path.stat().st_size)
    return json.loads(raw.decode("utf-8")), len(raw), hashlib.sha256(raw).hexdigest()


def _artifact(path: pathlib.Path) -> tuple[int, str]:
    assert path.is_file(), f"盘上没有 {path}"
    raw = path.read_bytes()
    assert raw, f"{path} 是空文件（0 字节的文件不是产物）"
    assert len(raw) == path.stat().st_size, (path, len(raw), path.stat().st_size)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _files(root: pathlib.Path) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            out.append((path.relative_to(root).as_posix(), len(raw),
                        hashlib.sha256(raw).hexdigest()))
    return out


def _code_files(ws: pathlib.Path) -> list[tuple[str, int, str]]:
    """工作区里 `code/` 那棵子树的清单（产物面；派发自己的台账不在这棵树下）。

    为什么不判整棵树：`Conductor.summon` 自己就要写 `tasks` 行、`out/tasks/<id>.json`
    与 `ARTIFACTS.jsonl` —— 那些是动作日志，不是 L 的产物。把它算进"只读"就算了，
    会把每一次派发都判成违约。
    """
    folder = ws / "code"
    if not folder.is_dir():
        return []
    return [(rel, size, sha) for rel, size, sha in _files(ws) if rel.startswith("code/")]


def _steps_rows(ws: pathlib.Path) -> list[dict]:
    text = (ws / STEPS_REL).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class ScriptedGateway:
    """照剧本回答的替身模型（与真模型同接口；价 0.0，一次请求都不发）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: object) -> object:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                  "error_detail": "", "error_kind": ""})()


def _drive_run_agent(ws: pathlib.Path, replies: list[str],
                     monkeypatch: pytest.MonkeyPatch, *, max_steps: int = 6) -> dict:
    """用 `run-agent L` 跑一趟（零模型：ScriptedGateway）。"""
    from argparse import Namespace

    from agentflow import cli
    from agentflow import sessions as SS
    from agentflow.llmseam import LlmSeam
    from agentflow.tools.conductor_tools import reset_cache

    def factory(role_name: str, *, root: pathlib.Path, sid: str, usd_budget: float | None,
                store: object = None) -> LlmSeam:
        gw = ScriptedGateway(list(replies))
        return LlmSeam(role=role_name, session_root=root, gateway=gw, price=(0.0, 0.0),
                       sid=sid, usd_budget=usd_budget)

    monkeypatch.setattr(cli, "_agent_seam_factory", factory)
    reset_cache()
    args = Namespace(root=str(ws), sid="t", json=False, budget_usd=None, dispatch=False,
                     role="L", task="把这条命题形式化并登记", drive=[], max_steps=max_steps,
                     rounds=1, report_every=1, resume=False, stop_file=None)
    rc = int(cli.cmd_run_agent(args))
    events, problems = SS.read_session(ws, sid="t")
    return {"rc": rc, "events": events, "problems": problems,
            "steps": [e for e in events if e.get("kind") == "agent_step"],
            "session": SS.session_path(ws, "t")}


# ============================================================ 1. 动作 formalize


def test_action_formalize_writes_the_same_artifacts_as_the_tool(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 产物 + 可被消费 + 可被登记：同一剧本走派发，结果与工具层逐格一致。

    改前红：把 `specs/l.py::ACTIONS` 里的 `formalize` 那一条摘掉（L 还没有这个动作的
    那一版）⇒ `summon` 拿到 `unknown_action`、本用例第一次派发即红。

    两个工作区（工具层一个、动作层一个）跑的是同一份源码：`.lean` 与 `.steps.jsonl`
    的字节数与 sha256 必须完全相同 —— 这条比"两边都写了文件"强得多，它把
    "派发这一路写下的东西与工具这一路写下的东西是同一份"变成机器读数。
    """
    _lean_on(monkeypatch)
    st_tool, ws_tool = _workspace(tmp_path / "tool")
    st_act, ws_act = _workspace(tmp_path / "act")
    _skip_unless_usable(ws_tool)
    _skip_unless_usable(ws_act)

    tool_data = _tool_layer(st_tool, ws_tool, "formal.formalize", claim=CLAIM,
                            source=_source(), declaration_name=DECL_SHORT,
                            statement_id=STMT_ID)
    cond = _conductor(st_act, ws_act)
    res, payload, row = _summon(cond, st_act, "formalize",
                                {"claim": CLAIM, "source": _source(),
                                 "declaration_name": DECL_SHORT,
                                 "statement_id": STMT_ID})

    # ---- 返回体形状：工具层那些关键格一个不少，且逐格相同
    missing = [k for k in KEY_READINGS if k not in payload]
    assert missing == [], missing
    assert set(tool_data) <= set(payload), sorted(set(tool_data) - set(payload))
    for key in ("status", "checker_status", "checker_reason", "exit_code", "verified",
                "path", "sha256", "bytes", "steps_path", "statement_id",
                "statement_source", "faithfulness", "verifier_output"):
        assert payload[key] == tool_data[key], (key, payload[key], tool_data[key])
    assert dict(payload["coverage"]) == dict(tool_data["coverage"]), (
        payload["coverage"], tool_data["coverage"])
    assert dict(payload["b_library"]) == dict(tool_data["b_library"]), payload["b_library"]
    assert payload["status"] == "verified", (payload["status"], payload["reason"])
    assert payload["checker_status"] == "verified", payload["checker_status"]
    assert payload["exit_code"] == 0, payload["exit_code"]
    assert dict(payload["coverage"])["steps_mapped"] == STEPS, payload["coverage"]
    assert dict(payload["b_library"])["found"] is True, payload["b_library"]

    # ---- 产物落盘：两个工作区逐字节同一份
    size, digest = _artifact(ws_act / LEAN_REL)
    tool_size, tool_digest = _artifact(ws_tool / LEAN_REL)
    assert (size, digest) == (tool_size, tool_digest), (
        (size, digest), (tool_size, tool_digest))
    assert int(payload["bytes"]) == size, (payload["bytes"], size)
    assert str(payload["sha256"]) == digest, (payload["sha256"], digest)
    assert (ws_act / LEAN_REL).read_bytes() == _source().encode("utf-8"), \
        "派发写下的 .lean 与传进来的源码不是同一串字节"
    steps_size, steps_digest = _artifact(ws_act / STEPS_REL)
    tool_steps = _artifact(ws_tool / STEPS_REL)
    assert (steps_size, steps_digest) == tool_steps, ((steps_size, steps_digest), tool_steps)

    # ---- 可被消费：对照表读回来（逐行）
    rows = _steps_rows(ws_act)
    assert len(rows) == STEPS, len(rows)
    proof_flat = " ".join(_proof_text().split())
    source_lines = (ws_act / LEAN_REL).read_text(encoding="utf-8").splitlines()
    for row_steps in rows:
        assert str(row_steps["quote"]) in proof_flat, row_steps
        first = int(row_steps["lean_lines"][0])
        assert source_lines[first - 1] == f"-- step {row_steps['proof_step']}", (
            row_steps, source_lines[first - 1])

    # ---- 动作日志：tasks 一行 + out/tasks/<id>.json（字节数 + sha256）
    assert str(row["role"]) == "L", row
    assert str(row["action"]) == "formalize", row
    assert str(row["called_by"]) == "B", row
    assert str(row["status"]) == "done" and str(row["outcome"]) == "ok", row
    assert str(row["detail"]).strip(), row
    digest_json, digest_size, digest_sha = _digest(ws_act, str(res.task_id))
    assert digest_size > 0 and len(digest_sha) == 64, (digest_size, digest_sha)
    assert str(digest_json["action"]) == "formalize", digest_json
    assert str(digest_json["outcome"]) == "ok", digest_json
    assert str(digest_json["task_id"]) == str(res.task_id), digest_json
    for key in ("path", "sha256", "coverage", "steps_path", "b_library"):
        assert key in (digest_json["payload_keys"] or []), (key, digest_json["payload_keys"])

    # ---- 可被登记：同一份产物再派一次 record，experiments 一行
    _res2, payload2, row2 = _summon(cond, st_act, "record",
                                    {"statement_id": STMT_ID, "code_path": LEAN_REL,
                                     "declaration_name": DECL_SHORT})
    assert payload2["recorded"] is True, payload2
    assert str(payload2["code_hash"]) == digest, (payload2["code_hash"], digest)
    assert str(row2["action"]) == "record", row2
    experiments = st_act.rows("experiments")
    assert len(experiments) == 1, experiments
    assert str(dict(experiments[0])["code_hash"]) == digest, experiments[0]


# ============================================================ 2. 动作 check_formal


def test_action_check_formal_reads_the_checker_words_without_touching_disk(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 只读 + 可被消费 + 可被登记：派发 `check_formal` 读的是真 Lean 原话。

    改前红：把 `specs/l.py::ACTIONS` 里的 `check_formal` 那一条摘掉 ⇒ `summon` 拿到
    `unknown_action`，本用例第一次派发即红。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    cond = _conductor(st, ws)

    _r1, made, _row1 = _summon(cond, st, "formalize",
                               {"claim": CLAIM, "source": _source(),
                                "declaration_name": DECL_SHORT,
                                "statement_id": STMT_ID})
    assert made["status"] == "verified", made["status"]
    before = _code_files(ws)
    lean_size, lean_sha = _artifact(ws / LEAN_REL)

    res, payload, row = _summon(cond, st, "check_formal",
                                {"claim": CLAIM, "script_path": LEAN_REL,
                                 "declaration_name": DECL_FULL})
    assert payload["verified"] is True, (payload["verified"], payload["reason"],
                                        payload["detail"])
    assert payload["status"] == "verified", payload["status"]
    assert payload["exit_code"] == 0, payload["exit_code"]
    out = str(payload["verifier_output"])
    assert out.strip(), "没有检查器原话的 verified 不算数"
    assert DECL_FULL in out, out
    assert "does not depend on any axioms" in out or "depends on axioms:" in out, out

    # ---- 只读：`code/` 下（L 的产物面）一个字节都没动
    assert _code_files(ws) == before, "派发 check_formal 改动了产物面（它必须只读）"
    assert _artifact(ws / LEAN_REL) == (lean_size, lean_sha), "盘上 .lean 的 sha256 变了"
    assert str(row["action"]) == "check_formal", row
    digest_json, _size, _sha = _digest(ws, str(res.task_id))
    assert str(digest_json["action"]) == "check_formal", digest_json
    assert "verifier_output" in (digest_json["payload_keys"] or []), digest_json["payload_keys"]

    # ---- 可被登记：这段原话就是 record 写进那一行的同一串
    _r3, recorded, _row3 = _summon(cond, st, "record",
                                   {"statement_id": STMT_ID, "code_path": LEAN_REL,
                                    "declaration_name": DECL_SHORT})
    assert recorded["recorded"] is True, recorded
    assert str(recorded["verifier_output"]) == out, (recorded["verifier_output"], out)
    row_exp = dict(st.rows("experiments")[0])
    assert str(row_exp["verifier_output"]) == out, (row_exp["verifier_output"], out)


# ============================================================ 3. 动作 record


def test_action_record_files_the_same_row_as_the_tool(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 可被登记 + 可被消费：派发 `record` 落的那一行与工具层同形。

    改前红：把 `specs/l.py::ACTIONS` 里的 `record` 那一条摘掉 ⇒ `summon` 拿到
    `unknown_action`，本用例第一次派发即红。
    """
    _lean_on(monkeypatch)
    st_tool, ws_tool = _workspace(tmp_path / "tool")
    st_act, ws_act = _workspace(tmp_path / "act")
    _skip_unless_usable(ws_tool)
    _skip_unless_usable(ws_act)

    tool_made = _tool_layer(st_tool, ws_tool, "formal.formalize", claim=CLAIM,
                            source=_source(), declaration_name=DECL_SHORT,
                            statement_id=STMT_ID)
    tool_row = _tool_layer(st_tool, ws_tool, "formal.record", statement_id=STMT_ID,
                           code_path=LEAN_REL, declaration_name=DECL_SHORT)
    assert tool_row["recorded"] is True, tool_row

    cond = _conductor(st_act, ws_act)
    _r1, made, _row1 = _summon(cond, st_act, "formalize",
                               {"claim": CLAIM, "source": _source(),
                                "declaration_name": DECL_SHORT,
                                "statement_id": STMT_ID})
    assert made["sha256"] == tool_made["sha256"], (made["sha256"], tool_made["sha256"])
    res, payload, row = _summon(cond, st_act, "record",
                                {"statement_id": STMT_ID, "code_path": LEAN_REL,
                                 "declaration_name": DECL_SHORT})
    assert payload["recorded"] is True, (payload["recorded"], payload["reason"],
                                        payload["detail"])
    assert str(row["action"]) == "record", row
    assert str(row["status"]) == "done" and str(row["outcome"]) == "ok", row

    experiments = st_act.rows("experiments")
    assert len(experiments) == 1, experiments
    row_exp = dict(experiments[0])
    # 两次登记的返回体与台账列逐格比（`code_path` 只在台账里，工具层那一份叫 `path`）
    for key in ("method", "evidence_kind", "claim_key", "code_hash", "exit_code",
                "result", "negation_kind", "status", "verified", "checker",
                "statement_evidence_kind_before", "verification_required"):
        assert str(tool_row.get(key)) == str(payload.get(key)), (
            key, payload.get(key), tool_row.get(key))
    assert str(tool_row["path"]) == str(row_exp["code_path"]), (
        tool_row["path"], row_exp["code_path"])
    assert str(row_exp["method"]) == "formal", row_exp
    assert str(row_exp["evidence_kind"]) == "proof", row_exp
    assert str(row_exp["claim_key"]) == f"stmt:{STMT_ID}", row_exp
    size, digest = _artifact(ws_act / LEAN_REL)
    assert str(row_exp["code_hash"]) == digest, (row_exp["code_hash"], digest)
    assert int(row_exp["exit_code"]) == 0, row_exp["exit_code"]
    observations = dict(row_exp["observations"])
    assert str(observations["checker"]).startswith("lean "), observations
    assert str(observations["tri_state"]) == "verified", observations

    # ---- 可被消费：另一个 Store 与收工门那一档的现算入口都读到它
    from agentflow import closing as CL
    from agentflow.store import Store

    fresh = Store(ws_act)
    ids = [str(r["experiment_id"]) for r in fresh.rows("experiments")]
    assert ids == [str(payload["experiment_id"])], ids
    count, detail = CL._leg_reading(fresh, "proof_experiment_rows", ws_act)
    assert count == 1, (count, detail)
    assert ids[0] in (detail.get("experiments") or []), detail
    # ---- 同一条命题的证据档不变
    assert payload["statement_evidence_kind_before"] == "heuristic", payload
    assert payload["statement_evidence_kind_after"] == "heuristic", payload
    stmt_row = next(r for r in fresh.rows("statements") if str(r.get("stmt_id")) == STMT_ID)
    assert str(stmt_row["evidence_kind"]) == "heuristic", stmt_row
    digest_json, _size, _sha = _digest(ws_act, str(res.task_id))
    assert str(digest_json["action"]) == "record", digest_json
    assert "experiment_id" in (digest_json["payload_keys"] or []), digest_json["payload_keys"]


# ============================================================ 4. 失败与拒绝路径


def test_action_failure_and_refusal_paths_do_not_claim_ok(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """失败 / 拒绝路径：派发层不许把"没成"说成 ok，被拒时盘上一个新产物都没有。

    改前红：把 `agent_l/formalize.py::_pick_statement` 退回成"不看台账、直接认"那一版
    ⇒ 不存在的编号也会写成一份 .lean，被拒那一段的 `refused` 与"没有新增文件"当场红。

    三档各自断言：
    1. 检查器说不行（`compile_error`）⇒ 这一趟的终态是 failed（不是 ok），而盘上那份
       .lean 是真的（写盘发生在检查之前）。`draft/146` D25 修好之后这一档还多两条：
       payload 不丢（检查器原话与盘上路径读得到）、行上不再写"执行中异常"
       （`error` 从 L 的 `detail` 兜底，见 `_end_from_payload` 的 failed 分支）。
    2. 命题不在台账里 ⇒ 受控拒绝（refused=True / written=False / statement_not_found），
       `code/formal` 里一个新增文件都没有；动作日志里能看见那条拒绝理由。
       D25 之后这一档在台账上是 `done/refused` + 受控的 `invalid_params`（不再是 `done/ok`）。
    3. 漏一步 ⇒ 综合结论 unknown 且盘上仍只有那一个 .lean（不产生第二份）。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    cond = _conductor(st, ws)

    # ---- 1. 检查器说不行
    res_bad = cond.summon("L", "formalize",
                          {"claim": CLAIM, "source": _source(broken=True),
                           "declaration_name": DECL_SHORT, "statement_id": STMT_ID},
                          by="B")
    assert str(res_bad.status) == "failed", (res_bad.status, res_bad.outcome, res_bad.detail)
    assert str(res_bad.outcome) == "failed", (res_bad.status, res_bad.outcome)
    rows_bad = [dict(r) for r in st.rows("tasks")
                if str(r.get("task_id")) == str(res_bad.task_id)]
    assert rows_bad and str(rows_bad[0]["outcome"]) == "failed", rows_bad
    assert str(rows_bad[0]["detail"]).strip(), rows_bad
    # D25（`draft/146`）：失败那一档的证据不许丢
    assert "执行中异常" not in str(rows_bad[0]["detail"]), rows_bad[0]["detail"]
    assert isinstance(res_bad.payload, dict), type(res_bad.payload)
    assert str(res_bad.payload.get("verifier_output") or "").strip(), res_bad.payload
    assert str(res_bad.payload.get("path") or "").endswith(".lean"), res_bad.payload.get("path")
    bad_size, bad_sha = _artifact(ws / LEAN_REL)
    assert (ws / LEAN_REL).read_bytes() == _source(broken=True).encode("utf-8"), \
        "failed 那一档盘上留下的不是这一趟那一份源码"
    assert bad_size > 0 and len(bad_sha) == 64, (bad_size, bad_sha)

    # ---- 2. 命题不在台账里：受控拒绝、不写盘
    st2, ws2 = _workspace(tmp_path / "refuse")
    cond2 = _conductor(st2, ws2)
    res_ref = cond2.summon("L", "formalize",
                           {"claim": CLAIM, "source": _source(),
                            "declaration_name": DECL_SHORT, "statement_id": "999999"},
                           by="B")
    payload_ref = dict(res_ref.payload or {})
    row_ref = next(dict(r) for r in st2.rows("tasks")
                   if str(r.get("task_id")) == str(res_ref.task_id))
    # 拒绝是第三态位：`done/refused` + 受控理由（D25 之前这里落 `done/ok`）
    assert str(res_ref.status) == "done" and str(res_ref.outcome) == "refused", (
        res_ref.status, res_ref.outcome, res_ref.detail)
    assert str(row_ref["outcome"]) == "refused", row_ref
    assert str(row_ref["refusal_reason"]) == "invalid_params", row_ref["refusal_reason"]
    assert payload_ref["refused"] is True, payload_ref
    assert payload_ref["written"] is False, payload_ref
    assert payload_ref["status"] == "unknown", payload_ref
    assert payload_ref["reason"] == "statement_not_found", payload_ref["reason"]
    assert "999999" in str(payload_ref["detail"]), payload_ref["detail"]

    added = [rel for rel, _s, _h in _files(ws2) if rel.startswith("code/")]
    assert added == [], f"被拒时 code/ 下多了文件：{added}"
    assert str(row_ref["action"]) == "formalize", row_ref
    # 拒绝在动作日志里看得见（detail 与 payload_keys 都还在）
    assert "999999" in str(row_ref["detail"]), row_ref["detail"]
    digest_json, _size, _sha = _digest(ws2, str(res_ref.task_id))
    assert "refused" in (digest_json["payload_keys"] or []), digest_json["payload_keys"]
    assert "statement_not_found" in str(digest_json["payload_preview"]), \
        digest_json["payload_preview"][:400]

    # ---- 3. 漏一步：综合结论 unknown，盘上仍只有那一个 .lean
    _r, full, _row = _summon(cond2, st2, "formalize",
                             {"claim": CLAIM, "source": _source(),
                              "declaration_name": DECL_SHORT, "statement_id": STMT_ID})
    assert full["status"] == "verified", full["status"]
    res_missed = cond2.summon("L", "formalize",
                              {"claim": CLAIM, "source": _source(STEPS - 1),
                               "declaration_name": DECL_SHORT, "statement_id": STMT_ID},
                              by="B")
    missed = dict(res_missed.payload or {})
    row_missed = next(dict(r) for r in st2.rows("tasks")
                      if str(r.get("task_id")) == str(res_missed.task_id))
    # 没查成（`draft/146` D25 之前这里落 `done/ok`，与"查过没问题"同形）
    assert str(res_missed.status) == "done" and str(res_missed.outcome) == "no_result", (
        res_missed.status, res_missed.outcome, res_missed.detail)
    assert str(row_missed["outcome"]) == "no_result", row_missed
    assert "[handler_not_checked" in str(row_missed["detail"]), row_missed["detail"]
    assert "faithfulness_incomplete" in str(row_missed["detail"]), row_missed["detail"]
    assert missed["status"] == "unknown", (missed["status"], missed["reason"])
    assert missed["reason"] == "faithfulness_incomplete", missed["reason"]
    assert dict(missed["coverage"])["unmapped"] == [STEPS], missed["coverage"]
    lean_files = sorted((ws2 / "code" / "formal").glob("*.lean"))
    assert [p.name for p in lean_files] == ["add_zero_probe.lean"], lean_files
    size, digest = _artifact(ws2 / LEAN_REL)
    assert str(missed["sha256"]) == digest, (missed["sha256"], digest)
    assert int(missed["bytes"]) == size, (missed["bytes"], size)


# ============================================================ 5. 动作日志里的 tool 名


def test_the_action_log_shows_the_tool_names(tmp_path: pathlib.Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """动作日志里能看见 tool 名（不是空转）：`run-agent L` 那一趟的会话日志。

    改前红：把 `formal.formalize` 从 `tools/formal_tools.py::_TOOL_FUNCTIONS` 里摘掉
    ⇒ 第一步的工具调用拿到 `unknown_tool`（`result.ok` 为假），本用例的
    "每一步都成功"与"experiments 一行"两条当场红。

    这一条为什么必须在动作层判：`tasks` 行与 `out/tasks/<id>.json` 记的是角色与动作，
    没有 tool 名这一格 —— 能看见 tool 名的日志只有会话日志（`sessions/<sid>.jsonl`）。
    断言的正是那一段：每一步的 `result.tool` 是工具面上的真名，且 `ok` 为真。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    replies = [
        json.dumps({"tool": "formal.formalize",
                    "args": {"claim": CLAIM, "source": _source(),
                             "declaration_name": DECL_SHORT, "statement_id": STMT_ID}},
                   ensure_ascii=False),
        json.dumps({"tool": "formal.record",
                    "args": {"statement_id": STMT_ID, "code_path": LEAN_REL,
                             "declaration_name": DECL_SHORT}},
                   ensure_ascii=False),
        json.dumps({"final": "形式化并登记完成", "evidence": []}, ensure_ascii=False),
    ]
    run = _drive_run_agent(ws, replies, monkeypatch)
    assert run["rc"] == 0, (run["rc"], run["problems"])
    assert run["problems"] == [], run["problems"]

    session = pathlib.Path(run["session"])
    raw = session.read_bytes()
    assert raw, f"会话日志是空的：{session}"
    assert len(raw) == session.stat().st_size, (session, len(raw), session.stat().st_size)
    session_sha = hashlib.sha256(raw).hexdigest()
    assert len(session_sha) == 64, session_sha

    results = [dict(e.get("result") or {}) for e in run["steps"] if e.get("role") == "L"]
    names = [str(r.get("tool") or "") for r in results]
    assert names == ["formal.formalize", "formal.record"], names
    assert all(r.get("ok") is True for r in results), results
    assert str(results[0]["data"]["status"]) == "verified", results[0]["data"].get("status")
    assert results[1]["data"]["recorded"] is True, results[1]["data"]

    # 动作真的落了盘：同一趟的产物与登记都在
    _size, digest = _artifact(ws / LEAN_REL)
    assert str(results[0]["data"]["sha256"]) == digest, results[0]["data"]["sha256"]
    experiments = st.rows("experiments")
    assert len(experiments) == 1, experiments
    assert str(dict(experiments[0])["code_hash"]) == digest, experiments[0]
