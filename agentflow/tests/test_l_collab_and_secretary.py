# -*- coding: utf-8 -*-
"""L 的协作面（无入边、唯一入口是用户指定单条执行）+ 秘书/名册/读写面 + 形式化实验行。

## 这一组判的是哪几条（业主 2026-10-22 的施工单，含 B-5 裁定）

业主 B-5 逐字：「L 的形式化验证成本极高 ⇒ 在全部研究和论文落定之后，用户指定有
形式化验证需求时，要一条才做一条」。于是本组的第一条判据是"没有任何角色能派 L"，
而"用户指定单条执行（`run-agent L`）跑得起来、跑得出 `.lean` 与一行 `experiments`"
是另一条。

| # | 判据 | 改前红（没有这一批改动时它怎么红） |
|---|---|---|
| 1 | 任何角色的出边里都没有 L；越权调用一律 `forbidden_edge` | 本批中途曾开过 `F → L`（业主 2026-10-22 上一条口径）⇒ 那条边一旦留下，`F→L` 那一条断言当场红。改前（更早那版）L 是 `summonable=False` + 空边集，但越权的理由串是"不可召唤"而不是可行动的那一句 |
| 2 | 用户指定单条执行跑完整条链：`run-agent L` 写 `.lean` + `.steps.jsonl` + 落一行 `experiments` | 改前动作表里没有 `record`、写集是空集 ⇒ `experiments` 一行都没有；没有 `formal.record` 这个工具 ⇒ 第二步的工具调用直接不可达 |
| 3 | `record` 只写 `experiments`，命题那一行的证据档一个字不动（V 签仍必需） | 改前 `statements` 那一格根本没有"L 会不会碰"的读数 |
| 4 | `record` 不信调用方口述：读得比现跑更强 ⇒ `reading_mismatch`，一行都不写 | 改前没有这一格；一个"直接信调用方"的版本会让 `1 = 2` 拿到 `evidence_kind="proof"` |
| 5 | `run-agent L` 有自己的秘书台账、名册行、读写面（与 E 被派活时的名册行同形态） | 改前单条执行时这三样一个都没有：台账要有秘书职责才落、名册行与读写面只有"被父派活"那条路才产生 |
| 6 | 反真空：把"单条执行时开自己的名册行"那一步钉成空操作 ⇒ 判据 5 必须红 | 判据 5 若读的是一个恒为空的 glob，它会在"什么都没做"上全绿 |

## 零模型

`run-agent` 那两条用 `ScriptedGateway`（与真模型同接口、发 0 次请求、花 0 元）。
真 Lean 用本机那一版的绝对路径；本机没有它时，需要检查器结论的断言改成
"结论是 unknown / 不是 proof"，而不是悄悄跳过。

## 临时文件

所有工作区都在 pytest 的 `tmp_path` 下，`.lean` / `.steps.jsonl` / `out/` 随 tmp 一起清掉。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import schema as S

#: 本机那一版真 Lean（绝对路径；PATH 上的 lean 可能是另一个东西）。
LEAN = pathlib.Path(r"D:\Incubator\_env\lean470\lean-4.7.0-windows\bin\lean.exe")
HAVE_LEAN = LEAN.is_file()

#: 被形式化的那条命题（B 登记的原文）。
CLAIM = "forall n : Nat, n + 0 = n"
#: `proof_text` 只有一步（空行分段 ⇒ 一步），配一条 `-- step 1` 就是 100% 覆盖的形态。
PROOF_TEXT = "对任意自然数 n，n + 0 与 n 是同一个项，故由 rfl 即得。"

GOOD_SOURCE = """import Init.Data.Nat.Basic

namespace LProbe

/-- 一条具体命题：对所有自然数 n，n + 0 = n。 -/
theorem add_zero_probe (n : Nat) : n + 0 = n := rfl
-- step 1

end LProbe
"""

BAD_SOURCE = """import Init.Data.Nat.Basic

namespace LProbe

/-- 反控用的假命题：1 = 2。 -/
theorem one_eq_two : 1 = 2 := rfl
-- step 1

end LProbe
"""

STMT_ID = "000001"
FORMAL_TOOLS = ("formal.formalize", "formal.check_formal", "formal.record")

#: 面向模型/用户的角色（判"谁的出边里都没有 L"时逐个数）。
ALL_ROLES = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)


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


# --------------------------------------------------------------------------- 夹具

def _lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _workspace(tmp_path: pathlib.Path, *, stmt: bool = True) -> tuple[object, pathlib.Path]:
    """建一个工作区 + 一条 B 登记的命题。"""
    from agentflow.store import Store

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    if stmt:
        with st.tx("statements", actor="agent-B") as tx:
            tx.upsert("statements", {
                "stmt_id": STMT_ID,
                "statement": CLAIM,
                "statement_full": CLAIM,
                "proof_text": PROOF_TEXT,
                "evidence_kind": "heuristic",
                "status": "active",
                "origin": "own_result",
                "quote_reason": "自产命题（这一组判据不涉及外部原文）",
            }, note="probe:statement")
    return st, ws


def _drive_run_agent(ws: pathlib.Path, script: dict[str, list[str]], task: str, role: str,
                     monkeypatch: pytest.MonkeyPatch, *, max_steps: int = 6) -> dict:
    """用 `run-agent <role>` 跑一趟（零模型）。"""
    from argparse import Namespace

    from agentflow import cli
    from agentflow import sessions as SS
    from agentflow.llmseam import LlmSeam
    from agentflow.tools.conductor_tools import reset_cache

    def factory(role_name: str, *, root: pathlib.Path, sid: str, usd_budget: float | None,
                store: object = None) -> LlmSeam:
        gw = ScriptedGateway(script.get(role_name, ['{"final": "（没有剧本）", "evidence": []}']))
        return LlmSeam(role=role_name, session_root=root, gateway=gw, price=(0.0, 0.0),
                       sid=sid, usd_budget=usd_budget)

    monkeypatch.setattr(cli, "_agent_seam_factory", factory)
    reset_cache()
    args = Namespace(root=str(ws), sid="t", json=False, budget_usd=None, dispatch=False,
                     role=role, task=task, drive=[], max_steps=max_steps, rounds=1,
                     report_every=1, resume=False, stop_file=None)
    rc = cli.cmd_run_agent(args)
    events, problems = SS.read_session(ws, sid="t")
    return {"rc": int(rc), "ws": ws, "events": events, "problems": problems,
            "steps": [e for e in events if e.get("kind") == "agent_step"],
            "ends": [e for e in events if e.get("kind") == "agent_run_end"]}


def _tool_results(run: dict, name: str) -> list[dict]:
    """那一趟里某件工具的每一次返回值（`data` 那份）。"""
    out: list[dict] = []
    for ev in run["steps"]:
        result = ev.get("result") or {}
        if str(result.get("tool") or "") == name:
            out.append(dict(result.get("data") or {}))
    return out


def _roster_add_rows(ws: pathlib.Path, owner: str) -> list[dict]:
    path = ws / "out" / "roster" / f"{owner}.jsonl"
    if not path.is_file():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if str(r.get("kind") or "") == "add"]


def _secretary_ledgers(ws: pathlib.Path, role: str) -> list[pathlib.Path]:
    folder = ws / "out" / "secretary"
    if not folder.is_dir():
        return []
    return sorted(folder.glob(f"{role}-*.jsonl"))


def _top_task_id(st: object, role: str) -> str:
    """这一趟自己的任务号（`run-agent` 开的那一条：role 对、`called_by` 不是角色）。"""
    for row in st.rows("tasks"):
        if (str(row.get("role")) == role and str(row.get("action")) == "run"
                and not str(row.get("parent_task_id") or "")):
            return str(row.get("task_id"))
    return ""


# ============================================================ 判据 1：入口只有 B
def test_only_b_has_an_edge_to_l_and_l_only_calls_c(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """协作面的形状：唯一入边是 `B → L`，L 唯一的出边是 `L → C`；其余角色一律 forbidden_edge。

    这一条随业主 2026-10-22 当天的几次改口径而变过，逐次记在这里（它守的正是
    "谁能让 L 干活"）：第一版空边集 + 不可召唤；第二版 `F → L`（"F 需要一个形式化
    下游"）；第三版撤 `F → L`（B-5「要一条才做一条」）；最终裁定（逐字记在
    `specs/l.py` 的模块 docstring）把唯一入口给了 B（B 登记命题、也最知道哪一条
    值得付形式化成本），并给 L 一条出边 `L → C`（梳理证明链）。

    改前红（任一方向）：前三版都真的落地过（空边集 / F→L），所以"边加错人或加多"
    这条路径是踩过的 —— 入边集合不是 {'B'}、或 L 的出边不是 {'C'}，下面当场红。

    反真空：先断言边表不是空的，并证明 F→E 这条无关的既有边仍然通。
    """
    from agentflow import policy as P
    from agentflow.agentspec import builtin_registry

    _lean_on(monkeypatch)
    edges = C.ALLOWED_EDGES
    assert sum(len(v) for v in edges.values()) >= 30, (
        f"边表几乎是空的 ⇒ 下面的断言会变成真空：{ {k: len(v) for k, v in edges.items()} }")
    inbound = sorted(role for role, targets in edges.items() if "L" in targets)
    assert inbound == ["B"], f"能召唤 L 的角色是 {inbound}（最终裁定：只有 B）"
    assert sorted(edges.get("L") or []) == ["C"], (
        f"L 的出边是 {sorted(edges.get('L') or [])}（最终裁定：只有 C）")
    assert "L" not in C.NON_SUMMONABLE, (
        f"L 在不可召唤名单里 ⇒ B 也派不动它（而裁定要 B 是唯一入口）：{sorted(C.NON_SUMMONABLE)}")
    reg = builtin_registry()
    assert "L" in reg.summonable_roles(), reg.summonable_roles()
    pol = P.Policy()
    assert P.check(pol, P.Decision(frm="F", to="E", action="", depth=2)) is None, \
        "F → E 这条既有边都不通了 ⇒ 这一条判据读的不是边表"
    # ---- 入口那一半：B → L 在策略层是通的
    assert P.check(pol, P.Decision(frm="B", to="L", action="", depth=2)) is None, \
        "B → L 不通 ⇒ 最终裁定的唯一入口没有接上"
    # ---- 越权：其余角色都被拒，且理由是 forbidden_edge
    for frm in ("M", "F", "D", "A", "E"):
        got = P.check(pol, P.Decision(frm=frm, to="L", action="", depth=2))
        assert got is not None, f"{frm} → L 居然通了（裁定里只有 B）"
        assert got.reason == "forbidden_edge", (frm, got.reason, got.detail)
        assert "L" in got.detail, (frm, got.detail)


def test_every_other_caller_is_refused_by_the_conductor(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """主控与父代理真的调用不动 L（不是"名单里有它没它"这么一句话）；B 那一条通。

    改前红：开过 `F → L` 的那一版里，下面 F 那一条会拿到 `outcome="ok"`。

    三态纪律在这里的落点：`status` 是"这次召唤跑完了没有"（被拒也是跑完了），
    "有没有做"看 `outcome` —— 两个格子刻意分开，判据不许折成一个。
    """
    from agentflow import secretary as SEC
    from agentflow.host import wired_conductor
    from agentflow.tools.conductor_tools import reset_cache

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path, stmt=False)
    reset_cache()
    cond = wired_conductor(st, workspace_root=str(ws))
    cond.secretary = SEC.Secretary("F", root=ws, store=st, registry=None, seam=None)
    parent = cond.open_item(kind="delegation", role="F", expects="work", action="step",
                            summary="F 的攻坚（判据用）", called_by="M", depth=1)
    for frm in ("M", "F", "D", "A"):
        res = cond.summon("L", "check_formal", {"claim": "1 = 1"}, by=frm,
                          parent_task_id=parent)
        assert str(res.outcome) == "refused", f"{frm} → L 居然被受理了：{res}"
        assert str(res.refusal_reason) == "forbidden_edge", (frm, res.refusal_reason, res.detail)
    l_rows = [r for r in st.rows("tasks") if str(r.get("role")) == "L"]
    assert l_rows, "越权那几次一次都没留痕 ⇒ 这一条判据没有东西可看"
    assert all(str(r.get("outcome")) == "refused" for r in l_rows), l_rows
    assert all(str(r.get("refusal_reason")) == "forbidden_edge" for r in l_rows), l_rows


# ============================================================ 判据 2：单条执行跑通
def test_run_agent_l_does_the_whole_job_in_one_specified_run(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """用户指定单条执行：`run-agent L` 写 `.lean` + `.steps.jsonl` + 落一行 `experiments`。

    改前红：动作表里没有 `record`、写集是空集 ⇒ `experiments` 一行都没有；
    工具面没有 `formal.record` ⇒ 第二步的工具调用直接不可达（`unknown tool`）；
    `formal.formalize` 的工具 schema 里没有 `statement_id` ⇒ 显式编号那一步被参数门拒。

    这是"要一条才做一条"的正控：一条命题、一次执行、一行实验。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    replies = [
        json.dumps({"tool": "formal.formalize",
                    "args": {"claim": CLAIM, "source": GOOD_SOURCE,
                             "declaration_name": "add_zero_probe",
                             "statement_id": STMT_ID}}, ensure_ascii=False),
        json.dumps({"tool": "formal.record",
                    "args": {"statement_id": STMT_ID,
                             "code_path": "code/formal/add_zero_probe.lean",
                             "declaration_name": "add_zero_probe"}}, ensure_ascii=False),
        json.dumps({"final": "形式化并登记完成", "evidence": []}, ensure_ascii=False),
    ]
    run = _drive_run_agent(ws, {"L": replies}, f"把 {CLAIM} 形式化并登记", "L", monkeypatch)
    assert run["rc"] == 0, (run["rc"], run["problems"])
    assert run["problems"] == [], run["problems"]
    ends = [e for e in run["ends"] if str(e.get("role")) == "L"]
    assert ends and str(ends[-1].get("stop_reason")) == "final", run["ends"]

    # ---- 1. `.lean` 真的落盘，`sha256` 与盘上字节一致
    formalize = _tool_results(run, "formal.formalize")
    assert formalize, f"这一趟没有调到 formal.formalize（步骤：{run['steps']}）"
    got = formalize[0]
    rel = str(got.get("path") or "")
    assert rel == "code/formal/add_zero_probe.lean", got
    target = ws / rel
    assert target.is_file(), f"返回值说有文件，盘上没有：{target}"
    raw = target.read_bytes()
    assert b"\r\n" not in raw, "落盘的行尾必须是 \\n"
    assert str(got.get("sha256")) == hashlib.sha256(raw).hexdigest(), got
    assert str(got.get("statement_id")) == STMT_ID, got

    # ---- 2. 逐步对照表在（C 路那一格的产物：12 步那种形态的最小版，一步一行）
    steps_path = str(got.get("steps_path") or "")
    assert steps_path.endswith(".steps.jsonl"), got
    steps_file = ws / steps_path
    assert steps_file.is_file(), f"逐步对照表没落盘：{steps_file}"
    rows = [json.loads(x) for x in steps_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows and set(rows[0]) == {"proof_step", "quote", "lean_lines", "how"}, rows[:1]
    coverage = dict(got.get("coverage") or {})
    assert coverage.get("steps_total") == len(rows), (coverage, rows)
    if HAVE_LEAN:
        assert coverage.get("steps_mapped") == coverage.get("steps_total"), coverage
        assert str(got.get("status")) == "verified", got.get("coverage")

    # ---- 3. 一行 experiments（method=formal），且形状与 E 那一套同源
    experiments = st.rows("experiments")
    assert len(experiments) == 1, experiments
    row = experiments[0]
    assert str(row.get("method")) == "formal", row
    assert str(row.get("claim_key")) == f"stmt:{STMT_ID}", row
    assert str(row.get("code_path")) == rel, row
    assert str(row.get("created_by")) in ("agent-L", "L"), row.get("created_by")
    record = _tool_results(run, "formal.record")
    assert record and record[0].get("recorded") is True, record
    if HAVE_LEAN:
        assert str(row.get("evidence_kind")) == "proof", row


# ============================================================ 判据 3：写集只到 experiments
def test_record_writes_only_experiments_and_never_upgrades_the_statement(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L 的写集只有 `experiments`；命题那一行的证据档写前写后逐字相同（V 签仍必需）。

    改前红：改前 L 的写集是空集（这一条会红在 `!= {"experiments"}` 上），而
    "L 会不会把命题升档"根本没有读数 —— 现在有两个方向：权限面（写集）与行为
    （写前写后现读）。

    本机没有真 Lean 时：这一行的证据档必须是 `heuristic`（不许标 proof）。
    """
    from agentflow.agent_l import AgentL

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    # ---- 权限面
    assert C.WRITE_SETS["L"] == frozenset({"experiments"}), sorted(C.WRITE_SETS["L"])
    assert "statements" not in C.write_set_of("L"), sorted(C.write_set_of("L"))
    assert C.write_set_of("L") and len(C.write_set_of("L")) < len(S.TABLES), (
        f"L 的写集读出来是 {sorted(C.write_set_of('L'))} ⇒ 上面两条断言在空集/全表上恒真")

    # ---- 行为
    agent = AgentL(st, workspace_root=ws)
    formalized = agent.formalize(CLAIM, source=GOOD_SOURCE,
                                 declaration_name="add_zero_probe", statement_id=STMT_ID)
    assert formalized.get("written") is True, formalized
    before = next(r for r in st.rows("statements") if str(r.get("stmt_id")) == STMT_ID)
    recorded = agent.record(STMT_ID, str(formalized["path"]),
                            declaration_name="add_zero_probe")
    assert recorded["recorded"] is True, recorded
    after = next(r for r in st.rows("statements") if str(r.get("stmt_id")) == STMT_ID)
    assert str(before.get("evidence_kind")) == str(after.get("evidence_kind")) == "heuristic", (
        before, after)
    assert recorded["statement_evidence_kind_before"] == "heuristic", recorded
    assert recorded["statement_evidence_kind_after"] == "heuristic", recorded
    assert bool(recorded["verification_required"]) is True, recorded
    # 没有 V 的签名：这一趟没碰 `verifications/`
    assert not (ws / "verifications").exists() or not list(
        (ws / "verifications").glob("*.jsonl")), "这一趟不该产生任何 V 的签名"
    # 那一行实验本身的两项证据形状
    row = st.rows("experiments")[0]
    if HAVE_LEAN:
        assert str(row.get("evidence_kind")) == "proof", row
        assert str(row.get("verifier_output") or "").strip(), row
        assert str(row.get("verifier_subject_key")) == f"stmt:{STMT_ID}", row
    else:
        assert str(row.get("evidence_kind")) != "proof", row
    assert dict(row.get("observations") or {}).get("output_sha256"), row


# ============================================================ 判据 4：读数不许被口述
def test_record_refuses_inflated_readings_and_writes_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """调用方口述"检查器说通过"而现跑不是 ⇒ `reading_mismatch`，`experiments` 一行都不写。

    改前红：改前没有 `record` 这一格；而一个"直接信调用方"的版本会让 `1 = 2` 拿到
    `evidence_kind="proof"`（这里用假命题 + 口述 verified 打它）。

    反真空：把对账钉成"永远一致" ⇒ 同一个调用写进去一行。它写进去了，才说明
    上面那个拒绝是对账产生的，而不是别处顺手拒的。注意写进去的那一行仍然不是 proof
    （"信不信调用方"与"这一行标不标 proof"是两件事，后者由现跑的三态决定）。
    """
    from agentflow.agent_l import AgentL
    from agentflow.agent_l import record as REC

    _lean_on(monkeypatch)
    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 假命题这一档没有检查器结论可对账")
    st, ws = _workspace(tmp_path)
    agent = AgentL(st, workspace_root=ws)
    formalized = agent.formalize(CLAIM, source=BAD_SOURCE, declaration_name="one_eq_two",
                                 statement_id=STMT_ID)
    assert formalized.get("written") is True, formalized
    assert str(formalized.get("status")) in ("failed", "unknown"), formalized

    inflated = agent.record(STMT_ID, str(formalized["path"]),
                            declaration_name="one_eq_two",
                            status="verified", verified=True)
    assert inflated["recorded"] is False, inflated
    assert str(inflated["reason"]) == "reading_mismatch", inflated
    assert st.rows("experiments") == [], f"被拒的那一次居然写了行：{st.rows('experiments')}"

    monkeypatch.setattr(REC, "_readings_mismatch", lambda **kw: "")
    bogus = agent.record(STMT_ID, str(formalized["path"]), declaration_name="one_eq_two",
                         status="verified", verified=True)
    assert bogus["recorded"] is True, bogus
    row = st.rows("experiments")[0]
    assert str(row.get("method")) == "formal", row
    assert str(row.get("evidence_kind")) != "proof", row
    assert str(row.get("result")) == "inconclusive", row


def test_record_refuses_a_statement_that_is_not_in_the_ledger(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`statement_id` 不在台账里 ⇒ `statement_not_found`，一行都不写。

    改前红：`record` 不存在（`AttributeError`）。
    """
    from agentflow.agent_l import AgentL

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    agent = AgentL(st, workspace_root=ws)
    formalized = agent.formalize(CLAIM, source=GOOD_SOURCE,
                                 declaration_name="add_zero_probe", statement_id=STMT_ID)
    got = agent.record("9999", str(formalized["path"]), declaration_name="add_zero_probe")
    assert got["recorded"] is False, got
    assert str(got["reason"]) == "statement_not_found", got
    assert st.rows("experiments") == [], st.rows("experiments")


# ============================================================ 判据 5：秘书/名册/读写面
def test_run_agent_l_has_a_ledger_roster_row_and_surface(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`run-agent L` 有自己的秘书台账、名册行与读写面目录（单条执行也要有这三样）。

    改前红：改前单条执行时一个都没有 —— 台账要有秘书职责才落，而名册行与读写面
    只有"被父派活"那条路（`Conductor._register_roster`）才产生，单条执行没有父。

    与 E 同形态的判法（不是"两个都非空"）：名册行的键集必须与 E 被派活时那一行
    逐字相同（同一份 `roster_add` 的输出形状），台账的键集必须与 E 自己那一份相同。
    """
    from agentflow import secretary as SEC
    from agentflow.host import wired_conductor
    from agentflow.store import Store
    from agentflow.tools.conductor_tools import reset_cache

    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path, stmt=False)
    run = _drive_run_agent(ws, {"L": [json.dumps({"final": "单条执行", "evidence": []},
                                                ensure_ascii=False)]},
                           "单条执行", "L", monkeypatch, max_steps=2)
    assert run["rc"] == 0, (run["rc"], run["problems"])
    top = _top_task_id(st, "L")
    assert top, f"这一趟没有顶行任务号：{st.rows('tasks')}"

    # ---- 1. 秘书台账（实例分片）
    ledgers = _secretary_ledgers(ws, "L")
    assert ledgers, "单条执行没有秘书台账（out/secretary/L-*.jsonl）"
    ledger = ledgers[0]
    assert ledger.name == f"L-{top}.jsonl", (ledger.name, top)
    rows = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows, f"台账是空文件：{ledger}"
    for row in rows:
        assert str(row.get("from")) == "secretary/L", row
        assert str(row.get("role")) == "L", row
        assert str(row.get("task_id")) == top, row

    # ---- 2. 名册行（owner 是这一趟自己的任务号）
    roster = _roster_add_rows(ws, top)
    assert len(roster) == 1, f"名册里 L 的行数是 {len(roster)}（{roster}）"
    entry = roster[0]
    assert str(entry.get("role")) == "L" and str(entry.get("task_id")) == top, entry
    assert str(entry.get("name") or "").startswith("L"), entry
    slot = str(entry.get("surface") or "")
    assert slot, f"名册行没有读写面槽位：{entry}"

    # ---- 3. 读写面目录真的建出来了
    face = ws / "out" / "surfaces" / top / slot
    assert face.is_dir(), f"名册写了槽位 {slot!r}，盘上没有那个读写面目录：{face}"
    pool = ws / "out" / "roster" / f"{top}-surfaces.jsonl"
    assert pool.is_file(), f"读写面池事件没落盘：{pool}"
    events = [json.loads(x) for x in pool.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert any(str(e.get("kind")) == "alloc" and str(e.get("slot")) == slot for e in events), events

    # ---- 4. 与 E 同形态：E 被 F 派活的那一条名册行，键集必须与 L 这行逐字相同
    st2 = Store(tmp_path / "ws2")
    st2.init()
    reset_cache()
    cond = wired_conductor(st2, workspace_root=str(tmp_path / "ws2"))
    cond.secretary = SEC.Secretary("F", root=tmp_path / "ws2", store=st2,
                                   registry=None, seam=None)
    parent = cond.open_item(kind="delegation", role="F", expects="work", action="step",
                            summary="F 的攻坚（判据用）", called_by="M", depth=1)
    res = cond.summon("E", "list_experiments", {"limit": 1}, by="F", parent_task_id=parent,
                      roster={"brief": "读一条实验行", "task": "读一条实验行"})
    assert str(res.outcome) == "ok", (res.outcome, res.refusal_reason, res.detail)
    e_rows = [r for r in _roster_add_rows(tmp_path / "ws2", parent)
              if str(r.get("role")) == "E"]
    assert len(e_rows) == 1, e_rows
    assert set(e_rows[0]) == set(entry), {
        "只在 L 那一行": sorted(set(entry) - set(e_rows[0])),
        "只在 E 那一行": sorted(set(e_rows[0]) - set(entry)),
    }


def test_the_solo_roster_step_is_not_vacuous(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把"单条执行时开自己的名册行"钉成空操作 ⇒ 判据 5 必须红。

    为什么必须有一条这样的负控：判据 5 读的是两个 glob（`L-*.jsonl` 与
    `out/roster/<id>.jsonl`）。写错一个字母的 glob 在空目录上恒返回空，而"空"
    在断言里看起来就像"这一趟本来就没有"。
    """
    from agentflow import secretary as SEC

    _lean_on(monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(SEC.Secretary, "open_solo_entry",
                        lambda self, **kw: {"name": "", "surface": "", "problem": ""})
    run = _drive_run_agent(ws, {"L": [json.dumps({"final": "单条执行", "evidence": []},
                                                ensure_ascii=False)]},
                           "单条执行", "L", monkeypatch, max_steps=2)
    assert run["rc"] == 0, (run["rc"], run["problems"])
    # 名册行与读写面必须没有出现（那正是判据 5 断言"要有"的两样）
    roster_dir = ws / "out" / "roster"
    assert not roster_dir.is_dir() or not list(roster_dir.glob("*.jsonl")), (
        "把 open_solo_entry 钉成空操作之后仍然有名册行 ⇒ 判据 5 读的不是那一步")
    surfaces = ws / "out" / "surfaces"
    assert not surfaces.is_dir() or not list(surfaces.glob("*/*")), (
        "把 open_solo_entry 钉成空操作之后仍然有读写面目录 ⇒ 判据 5 读的不是那一步")
