# -*- coding: utf-8 -*-
"""`draft/146` 的 D25 / D26 / D27 —— 三条都是 L 的实触发测试逼出来的真缺陷。

## 这一份判什么（每条都写明"改前红"）

| 缺陷 | 用例 | 改前红（没修时会读到的原文） |
|---|---|---|
| D25（高）动作派发把三态折成两态 | `test_d25_*` 六条 | `L.formalize 执行中异常（ValueError: status=failed 时必须写 error（失败的原因不能是空白））` + `payload=None`；`unknown` / `refused` / `verified` 三种返回在动作日志上都是 `done/ok` |
| D26（中）`sole_declaration_name` 不认 namespace | `test_d26_*` 三条 | 不给声明名时 `#print axioms add_zero_probe` ⇒ 检查器报 `unknown constant` ⇒ `status=compile_error`、`verified=False` |
| D27（低）`record` 的 `checker` 形参既不比也不记 | `test_d27_*` 两条 | `observations` 里没有 `checker_claimed`；声称 `Lean 3.0.0` 而现跑是 4.7.0 也照样 `recorded=True` |

## 为什么 D25 的判据在"派发层"而不是直接调 L

`_end_from_payload` 是 `Conductor.summon` 里唯一把"角色返回"翻成"任务终态"的地方
（`conductor.py` 的 `[6] 执行` 那一段）。D25 的两次折叠都发生在这一格：角色的
`status` 被当成任务终态、`error` 只从 `raw["error"]` 取。所以判据必须让返回值真的
穿过 `summon` —— 用替身喂一个与真 L 同形的读数，而不是直接调 `AgentL.formalize`。
替身的键集合对着 `agent_l/formalize.py::FAITHFULNESS_KEYS` 现核（少一格就红），
免得"替身随 L 的实现漂走、判据静默失效"。

## 真 Lean 与零模型

D26 的端到端与 D27 的两条要真跑检查器：本机那一版 Lean 用绝对路径给出来；不可用时
如实 skip 并写清原因（不伪装通过）。D25 的六条不需要检查器（替身只回读数），
所以它们在没装 Lean 的机器上照样跑。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

#: 本机那一版真 Lean（绝对路径，不依赖 PATH；与 `tests/test_l_action_dispatch.py` 同一处）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()

CLAIM = "forall n : Nat, n + 0 = n"
STMT_ID = "000001"
LABEL = "加零不改变自然数"
LEAN_REL = "code/formal/add_zero_probe.lean"
DECL_SHORT = "add_zero_probe"
DECL_FULL = "LProbe.add_zero_probe"
SID = "000001"

#: 检查器原话（D25 的 ① 要求它在失败那一档仍然读得到）。
CHECKER_WORDS = "error(1): unknown identifier 'Nat.zero_add'\nwarning: declaration uses 'sorry'"
#: L 写在 `detail` 里的那一句（它把检查器的原话压成一行，键名就叫 `detail`）。
FAILED_DETAIL = "检查器退出码 1 ⇒ 编译/精化失败：unknown identifier 'Nat.zero_add'"


# ============================================================ 夹具与小工具


def _lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """打开 Lean 这条路（L 的声明与 `formal.*` 工具只在开着时装配）。"""
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _skip_unless_usable(ws: pathlib.Path) -> None:
    """要真跑检查器的判据：不可用就如实 skip（不伪装通过）。"""
    from agentflow import leantoolchain as LT

    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条要真跑检查器，跳过（不伪装通过）")
    reading = LT.lean_selfcheck_reading(root=ws)
    if str(reading.get("state")) != "usable":
        pytest.skip(
            f"Lean 自检不是 usable（state={reading.get('state')}；"
            f"problems={reading.get('problems')}）⇒ 这一条要真跑检查器，跳过（不伪装通过）")


def _workspace(base: pathlib.Path) -> tuple[object, pathlib.Path]:
    """工作区 + 一条 12 步证明的命题（`record` 的绑定对象）。"""
    from agentflow.store import Store

    ws = base / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    proof = "\n\n".join(
        f"第 {k} 步：把第 {k - 1} 步的结论代入一次并化简。" for k in range(1, 13))
    with st.tx("statements", actor="agent-B") as tx:
        tx.upsert("statements", {
            "stmt_id": STMT_ID,
            "label": LABEL,
            "statement": CLAIM,
            "statement_full": CLAIM,
            "proof_text": proof,
            "evidence_kind": "heuristic",
            "status": "active",
            "origin": "own_result",
            "quote_reason": "自产命题（这一组判据不涉及外部原文）",
        }, note="probe:statement")
    return st, ws


def _source(*, steps: int = 12, two_declarations: bool = False) -> str:
    """Lean 源码：定理在 `namespace LProbe` 之内（D26 的关键形状）。"""
    lines = ["import Init.Data.Nat.Basic", "", "namespace LProbe", ""]
    if two_declarations:
        lines += ["theorem add_zero_probe (n : Nat) : n + 0 = n := by", "  rfl", ""]
        lines += ["theorem another_probe : True := trivial", ""]
    else:
        lines += ["/-- 加零不改变自然数。 -/",
                  "theorem add_zero_probe (n : Nat) : n + 0 = n := by", "  rfl"]
        for k in range(1, steps + 1):
            lines.append(f"-- step {k}")
        lines.append("")
    lines += ["end LProbe", ""]
    return "\n".join(lines)


def _l_reading(**override: Any) -> dict:
    """L 的 `formalize` 返回体：E 的九个键 + L 的四格 + 盘上五格 + 忠实复述那一族。

    忠实复述那一族的键从中性表现取（`_NEUTRAL_FAITHFULNESS` 与 `FAITHFULNESS_KEYS`
    在 `agent_l/formalize.py` 的导入期逐格相等），而不是在这里手抄一份：L 那一侧
    正在长（路径号那一批已经加了几格），替身手抄就会停在上一版，于是"判据打在真形状上"
    这件事静默失效 —— 而它的失效形态是绿。
    """
    from agentflow.agent_l import formalize as LF

    out: dict[str, Any] = {
        key: (value() if callable(value) else value)
        for key, value in LF._NEUTRAL_FAITHFULNESS.items()  # noqa: SLF001 - 判据要对着真身
    }
    out.update({
        # E 的九个
        "checked": True, "verified": False, "claim": CLAIM,
        "reason": "compile_error", "detail": FAILED_DETAIL,
        "verifier_output": CHECKER_WORDS, "missing_imports": [],
        "verifier_status": "compile_error", "exit_code": 1,
        # L 的四格
        "status": "failed", "problems": [FAILED_DETAIL],
        "lean": {"version": "4.7.0", "lean_path": str(LEAN)}, "lean_path": str(LEAN),
        # 盘上五格
        "path": LEAN_REL, "sha256": "0" * 64, "bytes": 321,
        "declaration_name": DECL_FULL, "written": True,
        # 忠实复述那一族的具体值（键由上面那张中性表兜住）
        "statement_id": STMT_ID, "statement_source": "explicit",
        "coverage": {"steps_total": 12, "steps_mapped": 12, "unmapped": [],
                     "sorry_lines": [], "statement_id": STMT_ID},
        "faithfulness": "complete", "steps_path": "code/formal/add_zero_probe.steps.jsonl",
        "refused": False, "checker_status": "failed", "checker_reason": "compile_error",
        "b_library": {"stmt_id": STMT_ID, "label": LABEL, "proof_chars": 120,
                      "dependency_steps": 12, "found": True},
    })
    out.update(override)
    return out


def _unknown_reading(**override: Any) -> dict:
    """`unknown`：检查器跑了，但综合结论是"没查成"（漏一步 / 自检不过 / 受控拒绝）。"""
    reading = _l_reading(
        status="unknown", checked=True, verified=False, reason="faithfulness_incomplete",
        checker_status="verified", checker_reason="verified",
        detail="faithfulness_incomplete：逐步对照只接上 11/12 步", problems=[],
        exit_code=0, verifier_output="'LProbe.add_zero_probe' does not depend on any axioms",
        faithfulness="incomplete",
        coverage={"steps_total": 12, "steps_mapped": 11, "unmapped": [12],
                  "sorry_lines": [], "statement_id": STMT_ID},
    )
    reading.update(override)
    return reading


def _refused_reading(**override: Any) -> dict:
    """受控拒绝：`refused=True` + L 自己的理由码（不在 `REFUSAL_REASONS` 里）+ 一个字节都没写。"""
    reading = _l_reading(
        status="unknown", checked=False, verified=None, reason="statement_not_found",
        detail="`statements` 里没有 999999 ⇒ 要形式化的那一行不存在。先请 B 登记，再来形式化",
        verifier_output="", verifier_status="", exit_code=None, problems=[],
        refused=True, written=False, path="", sha256="", bytes=0, checker_status="",
        checker_reason="", coverage={}, faithfulness="unknown", steps_path="",
    )
    reading.update(override)
    return reading


class _FakeL:
    """L 的替身：`formalize` 返回预设读数（键与真 L 同一套）。"""

    def __init__(self, reading: dict) -> None:
        self.reading = dict(reading)
        self.calls = 0

    def formalize(self, **params: Any) -> dict:
        """真 L 的 `formalize` 形状（参数不参与：读数由夹具钉住）。"""
        self.calls += 1
        return dict(self.reading)


def _dispatch(st: object, reading: dict, *, key: str) -> tuple[object, dict]:
    """把替身的读数穿过一次真的 `Conductor.summon`，返回 `(SummonResult, tasks 行)`。"""
    from agentflow.conductor import Conductor

    fake = _FakeL(reading)
    cond = Conductor(st, registry={"L": ("object", fake)})
    res = cond.summon("L", "formalize",
                      {"claim": CLAIM, "source": "theorem add_zero_probe : True := trivial",
                       "declaration_name": DECL_FULL, "statement_id": STMT_ID},
                      by="B", input_key=key)
    assert fake.calls == 1, "替身没有被调到 —— 这条判据什么都没测"
    row = next((dict(r) for r in st.rows("tasks")
                if str(r.get("task_id")) == str(res.task_id)), None)
    assert row is not None, f"派发没有落 tasks 行：{res.task_id}"
    return res, row


def _digest(ws: pathlib.Path, task_id: str) -> dict:
    """动作日志：`out/tasks/<task_id>.json`（这一份就是"动作日志"）。"""
    path = ws / "out" / "tasks" / f"{task_id}.json"
    assert path.is_file(), f"派发没有落动作日志：{path}"
    raw = path.read_bytes()
    assert raw, f"{path} 是空文件"
    return json.loads(raw.decode("utf-8"))


# ============================================================ 1. D25 第一面：failed


def test_d25_failed_keeps_the_checker_words_and_the_payload(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """① `failed` 那一档：步结果里仍读得到检查器原话 + .lean 路径 + coverage。

    改前红（原文）：`L.formalize 执行中异常（ValueError: status=failed 时必须写 error`
    `（失败的原因不能是空白））`、`payload=None` —— 一次有证据的"命题没核过"被记成
    "框架崩了"，而那三样证据全丢。

    这条判据的三段各咬一处：
    - payload 不丢 ⇒ `_end_from_payload` 没有在 `_end` 之前抛；
    - `error` 从 `detail` 兜底 ⇒ `schema.Task.validate` 过了（否则整行写不下去）；
    - 动作日志（`out/tasks/<id>.json`）里那三格仍在 ⇒ 事后复核得到。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    res, row = _dispatch(st, _l_reading(), key="d25:failed")

    # ---- 任务终态：failed 是"这一趟没干成"，但它是有证据的没干成
    assert str(res.status) == "failed", (res.status, res.outcome, res.detail)
    assert str(res.outcome) == "failed", (res.status, res.outcome)
    assert str(row["status"]) == "failed" and str(row["outcome"]) == "failed", row
    assert "执行中异常" not in str(row["detail"]), row["detail"]

    # ---- payload 不许丢：检查器原话 / .lean 路径 / coverage 三格都读得到
    payload = res.payload
    assert isinstance(payload, dict), type(payload)
    assert str(payload["verifier_output"]) == CHECKER_WORDS, payload["verifier_output"]
    assert str(payload["path"]) == LEAN_REL, payload["path"]
    assert dict(payload["coverage"])["steps_mapped"] == 12, payload["coverage"]
    assert str(payload["checker_status"]) == "failed", payload["checker_status"]

    # ---- error 必须非空（`Task.validate` 逐字要求），且它来自 L 的 `detail`
    assert str(row["error"]).strip(), row["error"]
    assert "unknown identifier" in str(row["error"]), row["error"]

    # ---- 动作日志里那三格也在（事后复核不依赖内存）
    digest = _digest(ws, str(res.task_id))
    assert str(digest["outcome"]) == "failed", digest
    for key in ("verifier_output", "path", "coverage"):
        assert key in (digest["payload_keys"] or []), (key, digest["payload_keys"])
    assert "unknown identifier" in str(digest["payload_preview"]), digest["payload_preview"]


# ============================================================ 2. D25 第二面：三档


def test_d25_unknown_is_not_checked_not_ok(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """② `unknown`（漏一步 / 自检不过）在动作日志上是"没查成"，不是 ok。

    改前红：这一档落 `done/ok`，与"查过、没问题"在台账上同形（实测三条：
    `UNKNOWN | status=done outcome=ok`）。

    为什么落 `no_result` 而不是新造一个 `tasks.outcome` 取值：`TASK_OUTCOMES` 是
    `schema.py` 里的受控词表（且 `cycles.outcome` / `audits.outcome` 复用它），
    为一次映射放宽它是把整张词表改宽。`no_result` 说的是"跑完了、没给出结论"，
    而"没查成"这件事由 `detail` 的 `[handler_not_checked …]` 与 payload 里的
    `checked` / `status` / `reason` 承担 —— 不是只靠一句自然语言。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    res, row = _dispatch(st, _unknown_reading(), key="d25:unknown")

    assert str(row["outcome"]) != "ok", row
    assert str(res.outcome) != "ok", (res.status, res.outcome)
    assert str(row["status"]) == "done", row["status"]
    assert str(row["outcome"]) == "no_result", row["outcome"]
    assert "[handler_not_checked" in str(row["detail"]), row["detail"]
    assert "没查成" in str(row["detail"]), row["detail"]
    assert "faithfulness_incomplete" in str(row["detail"]), "角色自己的理由码要可读"

    # 检查器原话仍然在（unknown 不是"什么都没跑"）
    assert isinstance(res.payload, dict), type(res.payload)
    assert "does not depend on any axioms" in str(res.payload["verifier_output"])
    digest = _digest(ws, str(res.task_id))
    assert str(digest["outcome"]) == "no_result", digest
    assert "[handler_not_checked" in str(digest["detail"]), digest["detail"]


def test_d25_refused_carries_a_controlled_reason_and_the_handlers_own_code(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③ `refused=None` 的旧世界：受控拒绝被折成 ok；现在必须落 `refused` + 受控理由。

    改前红：`REFUSED | status=done outcome=ok row.detail=台账里没有 999999`
    —— 一次"框架正确地说了不"在台账上写着成功。

    L 拒绝时给的是 `refused=True` + 它自己的理由码（`statement_not_found`），而那个码
    不在 `REFUSAL_REASONS` 里：框架不替它再造一套词表 —— 行上落 `invalid_params`
    （词表定义："参数/前置条件不满足：这次调用本身不成立"），L 的原话进 `detail`。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    res, row = _dispatch(st, _refused_reading(), key="d25:refused")

    assert str(res.status) == "done", (res.status, res.outcome)
    assert str(res.outcome) == "refused", (res.status, res.outcome, res.detail)
    assert str(row["outcome"]) == "refused", row
    assert str(row["refusal_reason"]) == "invalid_params", row["refusal_reason"]
    assert "[handler_refused" in str(row["detail"]), row["detail"]
    assert "statement_not_found" in str(row["detail"]), "角色自己的理由码必须还在"
    # 拒绝不是 ok（`SummonResult.ok` 既有的判据）
    assert res.ok is False, (res.status, res.outcome)
    # payload 不丢：拒绝那一支的读数（refused / written / reason）照样读得到
    assert isinstance(res.payload, dict), type(res.payload)
    assert res.payload["refused"] is True and res.payload["written"] is False
    digest = _digest(ws, str(res.task_id))
    assert str(digest["outcome"]) == "refused", digest


def test_d25_verified_is_still_ok(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（反真空的另一半）：`verified` 仍然落 `done/ok`。

    没有这一条，上面三条可以靠"凡三态都不记 ok"满足 —— 那会把每一次真的核过都
    记成"没查成"，比原来的折叠更糟。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reading = _l_reading(
        status="verified", verified=True, reason="verified", checker_status="verified",
        checker_reason="verified", detail="检查器退出码 0、公理在内",
        exit_code=0, problems=[], faithfulness="complete",
        verifier_output=f"'{DECL_FULL}' does not depend on any axioms")
    res, row = _dispatch(st, reading, key="d25:verified")

    assert str(res.status) == "done" and str(res.outcome) == "ok", (res.status, res.outcome)
    assert str(row["status"]) == "done" and str(row["outcome"]) == "ok", row
    assert row["error"] in (None, ""), row["error"]
    assert "[handler_not_checked" not in str(row["detail"]), row["detail"]
    assert isinstance(res.payload, dict) and res.payload["status"] == "verified"


def test_d25_the_three_grades_are_distinguishable_in_the_log(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """三档在动作日志上不同形：`ok` / `refused` / `not_checked(no_result)`。

    改前红：三种返回在 `tasks.outcome` 上都是 `ok`（`row.detail` 各不相同，但机器可读的
    那一格只有一个值）—— 于是"拒绝 / 没查成 / 成功"只能靠读散文分开。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    verified = _l_reading(status="verified", verified=True, reason="verified",
                          checker_status="verified", checker_reason="verified",
                          exit_code=0, detail="检查器退出码 0", problems=[])
    rows: dict[str, dict] = {}
    for grade, reading in (("ok", verified), ("refused", _refused_reading()),
                           ("not_checked", _unknown_reading())):
        res, row = _dispatch(st, reading, key=f"d25:grades:{grade}")
        digest = _digest(ws, str(res.task_id))
        rows[grade] = {"outcome": str(row["outcome"]), "digest": str(digest["outcome"])}

    assert rows["ok"]["outcome"] == "ok", rows
    assert rows["refused"]["outcome"] == "refused", rows
    assert rows["not_checked"]["outcome"] == "no_result", rows
    assert len({r["outcome"] for r in rows.values()}) == 3, rows
    # 台账与动作日志两个落点给的是同一个读数（不是只在其中一处改了口径）
    for grade, got in rows.items():
        assert got["digest"] == got["outcome"], (grade, got)


# ============================================================ 3. D25 反真空


def _revert_to_status_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """把映射退回"status 即终态"那一版（D25 改前逐字，只留与本判据相关的路径）。

    为什么要这样写反真空：判据"payload 不丢 / unknown 不是 ok"如果对任何实现都
    成立，那它就是真空的。这里把改前那一版装回去，断言两条判据当场变红 ——
    于是"这次修的是它"是机器读数，而不是一句自述。
    """
    from agentflow.conductor import TERMINAL_STATUSES, Conductor

    def _before(self, tid, raw):  # noqa: ANN001 - 与真方法同签名
        if isinstance(raw, dict):
            status = str(raw.get("status") or "done")
            if status not in TERMINAL_STATUSES:
                status = "done"
            outcome = raw.get("outcome")
            detail = str(raw.get("detail") or raw.get("summary") or "")
            # 改前逐字：`error` 只从 `raw["error"]` 取（L 的键叫 `detail`）
            error = str(raw["error"]) if raw.get("error") else None
            if status == "done" and outcome is None:
                outcome = "ok"
                detail = detail or "执行完成（handler 未声明 outcome，按有产出处理）"
            if status == "failed":
                outcome = "failed"
            return self._end(tid, status=status, outcome=outcome,
                             detail=detail or "执行完成", error=error,
                             payload=raw.get("payload", raw.get("data", raw)))
        return self._end(tid, status="done", outcome="no_result",
                         detail="执行完成，本动作没有产出（no_result）")

    monkeypatch.setattr(Conductor, "_end_from_payload", _before)


def test_d25_anti_vacuum_failed_loses_the_payload_under_the_old_mapping(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（①）：退回"status 即终态" ⇒ failed 那一档的 payload 必丢。

    这条读到的原文就是真机那一条：整步落 `failed` + `执行中异常（ValueError: …）`，
    `payload=None`。
    """
    _lean_on(monkeypatch)
    _revert_to_status_is_terminal(monkeypatch)
    st, _ws = _workspace(tmp_path)
    res, row = _dispatch(st, _l_reading(), key="d25:anti:failed")

    assert str(res.status) == "failed", (res.status, res.outcome)
    assert res.payload is None, "改前那一版应当把 payload 丢了（否则这条判据没有咬住任何东西）"
    assert "执行中异常" in str(res.detail), res.detail
    assert "status=failed 时必须写 error" in str(res.detail), res.detail
    # 台账行上留下的是那条 ValueError 本身（真机那一条的原文）
    assert "status=failed 时必须写 error" in str(row["error"]), row["error"]


def test_d25_anti_vacuum_unknown_and_refused_become_ok_under_the_old_mapping(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（②③）：退回那一版 ⇒ `unknown` 与 `refused` 都落 `done/ok`。

    这一条证明"三档在日志上不同形"不是天然成立的：改前它们同形。
    """
    _lean_on(monkeypatch)
    _revert_to_status_is_terminal(monkeypatch)
    st, _ws = _workspace(tmp_path)
    for grade, reading in (("unknown", _unknown_reading()), ("refused", _refused_reading())):
        res, row = _dispatch(st, reading, key=f"d25:anti:{grade}")
        assert str(row["outcome"]) == "ok", (grade, row)
        assert str(res.status) == "done" and str(res.outcome) == "ok", (grade, row)


# ============================================================ 4. D26：命名空间前缀


def test_d26_sole_declaration_name_resolves_the_namespace() -> None:
    """D26 本体：源码里唯一那条声明的限定名（命名空间栈拼出来的）。

    改前红：`sole_declaration_name` 只取源码里的短名 ⇒ 返回 `add_zero_probe`，
    而 `#print axioms add_zero_probe` 在文件作用域里是一条未知常量。
    """
    from agentflow import formalgw as FG

    src = _source()
    assert FG.declaration_names(src) == [DECL_SHORT], FG.declaration_names(src)
    assert FG.sole_declaration_name(src) == DECL_FULL, FG.sole_declaration_name(src)


def test_d26_two_declarations_are_still_refused_not_guessed() -> None:
    """不许猜：两份具名声明 ⇒ 受控拒绝，且候选名列的是限定名。

    改前红：拒绝这件事本来就成立（0/多条都抛），但候选名列的是短名
    （`['add_zero_probe', 'another_probe']`）—— 调用方照着那个名字去点名，
    下一趟仍旧撞 `unknown constant`。重命名空间之后，候选名必须是能直接用的。
    """
    from agentflow import formalgw as FG

    src = _source(two_declarations=True)
    with pytest.raises(FG.DeclarationNameError) as err:
        FG.sole_declaration_name(src)
    message = str(err.value)
    assert f"{DECL_FULL}" in message, message
    assert "LProbe.another_probe" in message, message
    assert "显式给出声明名" in message, message


def test_d26_nested_and_multi_part_namespaces_keep_their_prefix() -> None:
    """嵌套 / 多段命名空间：前缀按"一条 `namespace` 行 = 一层"拼与弹。

    为什么值得单独一条：L 自己那份实现（`declaration_name_in`）按名字段压栈，
    于是 `namespace A.B` 之后一条 `end A.B` 只弹掉一段、`A` 留在栈里 —— 后面那条
    声明的前缀就拼错了。桥接层这一份按层压，所以：

    - `namespace Outer` → `section S` → 定理 ⇒ `Outer.t1`（`section` 不改名字空间）；
    - `namespace A.B` → 定理 ⇒ `A.B.t`；`end A.B` 之后那条 ⇒ 回到文件作用域，`u`。
    """
    from agentflow import formalgw as FG

    nested = (
        "namespace Outer\n\nsection S\n\n"
        "theorem t1 : True := trivial\n\nend S\n\n"
        "namespace Inner\n\ntheorem t2 : True := trivial\n\nend Inner\n\nend Outer\n"
    )
    assert FG.qualified_declaration_names(nested) == ["Outer.t1", "Outer.Inner.t2"], \
        FG.qualified_declaration_names(nested)

    multipart = (
        "namespace A.B\n\ntheorem t : True := trivial\n\nend A.B\n\n"
        "theorem u : True := trivial\n"
    )
    assert FG.qualified_declaration_names(multipart) == ["A.B.t", "u"], \
        FG.qualified_declaration_names(multipart)


def test_d26_check_formal_without_a_name_verifies_a_namespaced_theorem(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D26 端到端：带 namespace 的源码不给 `declaration_name` ⇒ `verified=True`。

    走的是真那条链：`formal.check_formal`（L 的工具）→ `verify.check_formal`（桥接层）
    → `formalgw.check_lean`（`name=""`）→ `sole_declaration_name` → 真 Lean。
    改前红：`verified=False`、`status="compile_error"`、检查器原话里是
    `unknown constant 'add_zero_probe'`。
    """
    from agentflow.agent_l import install_l_tools

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    target = ws / LEAN_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_source(), encoding="utf-8")

    reg = install_l_tools(st, workspace_root=ws)
    # 刻意不给 declaration_name：这一条判的就是"不给也能拼出全名"
    res = reg.call("formal.check_formal", claim=CLAIM, script_path=LEAN_REL)
    assert res.ok is True, (res.ok, res.error, res.meta)
    data = dict(res.data or {})
    assert data.get("verified") is True, (data.get("verified"), data.get("reason"),
                                          data.get("detail"))
    assert str(data.get("status")) == "verified", (data.get("status"), data.get("detail"))
    assert int(data.get("exit_code") or 0) == 0, data.get("exit_code")
    out = str(data.get("verifier_output") or "")
    assert DECL_FULL in out or DECL_SHORT in out, out


def test_d26_check_formal_refuses_to_guess_between_two_declarations(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D26 端到端（负控）：两份具名声明 ⇒ 受控拒绝（`param_error`），不起检查器去猜。

    判据打在桥接层（`verify_tools.check_formal`）上：`sole_declaration_name` 是它的
    判据，受控拒绝的形态该由它给（`checked=False` + `kind=param_error` + 候选名）。

    另记一条在 L 那一侧读到的相邻缺陷（不归 D26，本用例只如实断言"拒绝"这件事）：
    `formal.check_formal` 当时把这次拒绝折成 `kind="unexpected"`
    （`AttributeError: 'AgentL' object has no attribute '_formal_refusal'`）——
    L 的 `check_formal` 继承了 E 的实现，而 E 那条失败分支调的是 `self._formal_refusal`，
    L 自己只定义了 `_refusal`。于是"受控拒绝"在 L 的工具面上变成一次崩溃。

    2026-10-23（D29/D30）：那条相邻缺陷已修（`agent_l/core.py` 的 `_formal_refusal`
    是转发到 `_refusal` 的受控拒绝口，形状是 D25 的第三档）。下面是旧断言
    （`assert lres.ok is False`）—— 它记录的是改前缺陷形态，不是契约：`ok=False`
    只来自那次崩溃。修好之后 L 的工具层按 `tools/formal_tools.py` 的口径回
    "调用成功、结论是被拒"（`ok=True` + `data.refused=True`），与 `formal.record`
    的受控拒绝同形。反真空见
    :func:`test_d29_anti_vacuum_without_the_alias_the_tool_face_is_unexpected_again`。
    """
    from agentflow.agent_l import install_l_tools
    from agentflow.tools import verify_tools as VT

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    target = ws / LEAN_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_source(two_declarations=True), encoding="utf-8")

    res = VT.check_formal(CLAIM, script_path=LEAN_REL, root=ws)
    assert res.ok is False, (res.ok, res.data)
    assert str(res.meta.get("kind")) == "param_error", res.meta
    message = str(res.error)
    assert "LProbe.add_zero_probe" in message and "LProbe.another_probe" in message, message
    # 受控拒绝必须是"没查成"，不是"查了没通过"（`decl_mismatch` 是另一档）
    assert res.data is None or str((res.data or {}).get("status") or "") != "compile_error"

    # L 的工具层同样不许把这一趟说成通过 —— 但"说成通过"的判据是 `data` 里的三态位，
    # 不是 `ok`：`ok=False` 只该出现在崩溃那一支（D29 改前正是如此）。
    reg = install_l_tools(st, workspace_root=ws)
    lres = reg.call("formal.check_formal", claim=CLAIM, script_path=LEAN_REL)
    assert lres.ok is True, (lres.ok, lres.error, lres.meta)
    assert str(lres.meta.get("kind") or "") != "unexpected", lres.meta
    refused = dict(lres.data or {})
    assert refused.get("refused") is True, refused
    assert str(refused.get("refusal_reason")) == "invalid_params", refused
    assert str(refused.get("status")) == "unknown", refused
    # 拒绝理由可读：L 自己的码与工具层那句话都还在
    assert str(refused.get("reason")) == "tool_failed", refused
    assert "param_error" in str(refused.get("detail") or ""), refused


# ============================================================ 5. D27：checker 形参


def _write_lean(ws: pathlib.Path, source: str | None = None) -> pathlib.Path:
    """把一份 `.lean` 写进工作区。

    刻意不经过 `formalize`：D27 要考的是 `record` 自己（它读盘上这一份、现跑一次
    检查器、再落一行），而 `formalize` 那一侧归另一路在改 —— 判据不把别人的
    在飞改动当成自己的前提。
    """
    target = ws / LEAN_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source if source is not None else _source(), encoding="utf-8")
    return target


def test_d27_the_claimed_checker_is_recorded_in_observations(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D27：`checker` 形参要么记下来、要么删掉 —— 这里选"记下来并对账"。

    改前红：`observations` 里没有 `checker_claimed` ⇒ 调用方口述的那台检查器既没被比、
    也没被记，于是 `record` 的模块 docstring 说"四格都用于对账"而实际只有三格。
    """
    from agentflow.agent_l import install_l_tools

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    _write_lean(ws)
    reg = install_l_tools(st, workspace_root=ws)

    res = reg.call("formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                   declaration_name=DECL_FULL, checker="Lean 4.7.0")
    assert res.ok is True, (res.error, res.meta)
    data = dict(res.data or {})
    assert data.get("recorded") is True, (data.get("reason"), data.get("detail"))

    rows = [dict(r) for r in st.rows("experiments")]
    assert len(rows) == 1, rows
    obs = dict(rows[0].get("observations") or {})
    assert str(obs.get("checker") or "").startswith("lean "), obs
    assert str(obs.get("checker_claimed")) == "Lean 4.7.0", obs


def test_d27_a_contradicted_checker_version_is_a_controlled_refusal(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D27 对账：口述的版本与现跑那一台不一致 ⇒ 受控拒绝 `reading_mismatch`，一行都不写。

    改前红：`checker="Lean 3.0.0"` 与现跑的 4.7.0 摆在一起也照样 `recorded=True`
    —— 那一行写进去的会是"另一台机器"的读数（`params["checker"]` 与调用方口述分家，
    而台账上看不出来）。

    比版本号不比写法（`lean 4.7.0` 与 `Lean 4.7.0` 是同一台）：与 `_readings_mismatch`
    的单向判据同一条纪律 —— 只拒"更强的声称"，不拒"另一种写法"。
    """
    from agentflow.agent_l import install_l_tools

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    _write_lean(ws)
    reg = install_l_tools(st, workspace_root=ws)

    refused = reg.call("formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                       declaration_name=DECL_FULL, checker="Lean 3.0.0")
    assert refused.ok is True, (refused.error, refused.meta)
    data = dict(refused.data or {})
    assert data.get("recorded") is False, data
    assert str(data.get("reason")) == "reading_mismatch", (data.get("reason"), data.get("detail"))
    assert "3.0.0" in str(data.get("detail")), data.get("detail")
    assert st.rows("experiments") == [], "被拒时一行都不许写"
    # 受控拒绝的形态：`refused=True` + 受控理由（派发层据此落 refused，不是"没查成"）
    assert data.get("refused") is True, data
    assert str(data.get("refusal_reason")) == "invalid_params", data


# ============================================================ 6. D29 反真空


def test_d29_anti_vacuum_without_the_alias_the_tool_face_is_unexpected_again(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（D29，2026-10-23）：把 `_formal_refusal` 从 L 的 MRO 上摘掉 ⇒ 判据必红。

    为什么必须有这一条：D26 那条用例的最后一段现在断言"L 的工具层回
    `ok=True` + `refused=True`、`kind` 不是 `unexpected`"。若没有负控，那几条可以
    只是照着实现抄下来的（尺子随实现漂）。这里把 `agent_l/core.py` 那处修复退回去
    —— 也就是 D29 改前那一版：L 只有 `_refusal`，E 那条 `not res.ok` 分支调
    `self._formal_refusal` 就抛 `AttributeError`，被 `ToolRegistry.call` 兜成
    `kind="unexpected"`。读数必须与判据里那几条逐条相反（`ok=False`、
    `kind="unexpected"`、`data=None`），于是那条判据读的是修复本身。

    为什么这里打桩而不真跑检查器：D29 的落点在 L 这一层（受控拒绝口），与检查器是否
    装了无关。自检闸钉成 usable、桥接层换成一次受控失败（`param_error`），于是
    `check_formal` 一定走进 E 那条失败分支 —— 也就是真机那次的两步。
    """
    from agentflow.agent_l import AgentL, install_l_tools
    from agentflow.tools import base as TB
    from agentflow.tools import verify_tools as VT

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    monkeypatch.setattr(AgentL, "_lean_selfcheck", lambda self: ("usable", ""))
    monkeypatch.setattr(
        VT, "check_formal",
        lambda *a, **k: TB.fail("（反真空）桥接层受控失败 param_error", kind="param_error"))

    owner = next(cls for cls in AgentL.__mro__ if "_formal_refusal" in vars(cls))
    monkeypatch.delattr(owner, "_formal_refusal")

    reg = install_l_tools(st, workspace_root=ws)
    lres = reg.call("formal.check_formal", claim=CLAIM,
                    source="theorem add_zero_probe (n : Nat) : n + 0 = n := by rfl")
    assert lres.ok is False, (lres.ok, lres.data)
    assert str(lres.meta.get("kind")) == "unexpected", lres.meta
    assert "AttributeError" in str(lres.error), lres.error
    # 受控拒绝那一档的读数整个不见了 —— 这就是改前缺陷形态
    assert lres.data is None, lres.data
