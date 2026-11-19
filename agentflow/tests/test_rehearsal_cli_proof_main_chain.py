# -*- coding: utf-8 -*-
"""彩排（真路径）：证明主链 —— 从 CLI 入口进，只把网络传输层换成预置 JSON。

## 这条彩排与真机差在哪（逐项，不许含糊）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条（一次都没绕开） |
| 派活 | `Conductor.summon` → `tasks` 行 → 真秘书 | 同一条 |
| 模型缝 | 真 `LlmSeam`（`_agent_seam_factory` / `for_role` / `for_secretary`） | 同一条：构造点一个都没替换 |
| 记账 | 真 `TokenMeter` → `usage_ledger` | 同一条 |
| 出网 | `modelgw.urllib_transport`（HTTP POST） | 只换这一处：回预置的 OpenAI 兼容 JSON |
| 模型 key | 机器上那把 | env `AGENTFLOW_MODEL_API_KEY` 给一个假值（模拟"配了 key"） |

也就是说：除了网线，全是产品那一套。 `temp/sp/REPORT-SP.md` §1.8 说的替换点就是这一层
（"彩排替换点应是 gateway/transport"）。

## 这条链覆盖什么（业主点名的主链 a）

```text
M(summon B) → B → V.verify_proof 三转（每转一次 V 判 + 一次秘书判）
            → 收方秘书把签块落回 reports/f-proof-000002.md（三签 3/3）
            → B.register_statement（判非平凡度 T2 → 收录 statements 1 行 → 依赖面读数）
            → M 销号 B、收工
```

判据读盘（不看回执的 ok=True）：`statements` 1 行、`nontriviality.jsonl` 1 行 T2、
`verifications/pending/<正文 sha>.jsonl` 3 行、稿上有 `- V 签：…连续=3/3`、
B 的回执说依赖面 `deps_state="none_in_proof"`（空表 = 声明自足）、
账本 `unattributed=0 / dangling=[] / equal=True`。

## 反真空（第二条）

把 V 的审阅回复换成「有毛病」⇒ 三签不成立 ⇒ 稿上没有签块、`statements` 0 行。
它证明上面那些绿是门在承重，不是橡皮图章。

## Lean 两档

`test_the_same_chain_runs_with_lean_off`：`AGENTFLOW_LEAN_ENABLED=0` 下同一条链照跑，
且名册里没有 L。关档此前的链级覆盖是 0（`temp/sp/REPORT-SP.md` §五）。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

from agentflow import cli
from agentflow import modelgw as MG
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.store import Store

import rehearsal_contract as RC

SID = "rc2-main-chain"

#: 判据①/②的本体只有一份：`rehearsal_contract` 的读数函数（CC3 的四条链也用同一份）。
#: RC2 时它们写在本文件里；CC3 搬进契约文件，避免两处各写一份「什么叫不对」。
#: `LLM_ROW_PREFIX`（模型调用级账本行的机器标记）也在那里。
LLM_ROW_PREFIX = RC.LLM_ROW_PREFIX
_ledger_identity = RC.ledger_identity
_one_row_per_call_problems = RC.one_row_per_call_problems
_session_calls = RC.session_calls
_session_problems = RC.session_problems


def _session_split(ws: pathlib.Path) -> dict[str, Any]:
    """本趟的会话归口读数（`sid` 由本文件钉死 = `SID`）。"""
    return RC.session_split(ws, SID)


MANUSCRIPT = "reports/f-proof-000002.md"
PROPOSITION = ("设 a = 1/√2、O_a = {(x,y,z) : |x|+|y|+|z| ≤ a}；则对任意单位向量 n 与"
               "任意实数 t，截面面积 A_n(t) ≤ 2a²，且等号成立当且仅当 n 平行于某坐标轴"
               "且 t = 0。")
PROOF = ("1. 口径与齐次缩放：O_a = a·O_1，area(a·K) = a²·area(K)，故只需证 a=1 时 ≤ 2。\n"
         "2. 由 Brunn 凹性与 O_1 的中心对称得 A_n(t) ≤ A_n(0)：最大值在中心截面。\n"
         "3. 中心截面为六边形，面积闭式 2s/D ≤ 2，等号当且仅当 n=±e_i。")
MANUSCRIPT_TEXT = (
    "# F 的证明手稿：彩排主链\n\n- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
    "## 命题\n\n" + PROPOSITION + "\n\n## 证明\n\n" + PROOF + "\n\n## 依赖\n\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n\n（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _judge_reply(kind: str) -> str:
    """秘书判断面的预置结论（按 `_judge_system` 的类别头分派）。"""
    table: dict[str, dict[str, Any]] = {
        "statement_aesthetic": {"decision": "T2", "reason": "彩排：有一段真正的推理",
                                "basis": ["证明有三步", "用到了 Brunn 凹性"]},
        "proposition_identity": {"decision": "same", "reason": "彩排：同一条",
                                 "basis": ["夹具"], "canonical_name": "截面面积上界",
                                 "same_as": "", "route": "", "condition": "夹具",
                                 "conclusion": "夹具"},
        "proof_kind": {"decision": "same", "reason": "彩排", "basis": ["夹具"], "same_path": 1},
        "v_reply_defect": {"decision": "没问题", "reason": "彩排：三步都对", "basis": ["夹具"],
                           "defect_step": None, "defect_kind": "", "report_gap": ""},
        "sign_issuance": {"decision": "签发", "reason": "彩排", "basis": ["夹具"]},
        "dispatch_fit": {"decision": "这一件能做", "reason": "彩排", "basis": ["夹具"]},
    }
    return _json(table.get(kind, {"decision": "可派", "reason": "彩排", "basis": ["夹具"]}))


class _Wire:
    """预置的网络传输层替身（与 `modelgw.urllib_transport` 同签名）。

    它不是缝：预算闸 / 账本 / `llm_call` 事件 / ambient 解析全在真 `LlmSeam` 上；
    这里只回答"上游那一端收到了什么、回了什么"。
    """

    def __init__(self, *, verdict: str = "成立",
                 via: str = "register_statement") -> None:
        self.verdict = str(verdict)
        self.via = str(via)
        self.bodies: list[dict[str, Any]] = []
        self.replies: list[str] = []
        self._steps: dict[str, int] = {}

    # ------------------------------------------------------------ 剧本
    def _step(self, role: str) -> str:
        index = self._steps.get(role, 0)
        self._steps[role] = index + 1
        if role == "M":
            seq = [_json({"summon": {"role": "B", "task": f"收录手稿 {MANUSCRIPT}"}}),
                   _json({"tool": "conductor.retire_child",
                          "args": {"child_name": "B1", "reason": "B 交完了"}}),
                   _json({"final": "交付：B 已收录", "evidence": []})]
        elif role == "B":
            if self.via == "ingest_manuscript":
                record = _json({"tool": "own.ingest_manuscript",
                                "args": {"manuscript": MANUSCRIPT, "mode": "register"},
                                "why": "V 已经签了，走手稿收录那一路"})
            else:
                record = _json({"tool": "own.register_statement",
                                "args": {"proof_manuscript": MANUSCRIPT,
                                         "label": "F 攻坚 0002 子目标 S4"},
                                "why": "V 已经签了，按稿收录"})
            seq = [_json({"summon": {"role": "V", "task": f"审这份证明 {MANUSCRIPT}",
                                     "params": {"proof_manuscript": MANUSCRIPT}}}),
                   _json({"tool": "conductor.retire_child",
                          "args": {"child_name": "V1", "reason": "V 签完了"}}),
                   record,
                   _json({"final": "B 的结论：已收录", "evidence": []})]
        elif role == "V":
            seq = [_json({"tool": "verify.verify_proof",
                          "args": {"proof_manuscript": MANUSCRIPT}, "why": "按稿三转"}),
                   _json({"final": "V 的结论：已签" if self.verdict == "成立"
                          else "V 的结论：打回", "evidence": []})]
        else:
            seq = [_json({"final": f"{role}：彩排收工", "evidence": []})]
        return seq[min(index, len(seq) - 1)]

    def _reply(self, system: str, prompt: str) -> str:
        head = system.lstrip()
        body = prompt.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            return _judge_reply(m.group(1))
        if head.startswith("你是「命题形态闸」"):
            return _json({"well_formed": True, "conditions": "a = 1/√2、n 为单位向量",
                          "conclusion": "则 A_n(t) ≤ 2a²",
                          "problems": [], "decision": "前提与结论都写清了"})
        if body.startswith("你是验证者（V）"):
            if self.verdict == "成立":
                return _json({"verdict": "成立", "findings": [],
                              "reason": "彩排：三步都对"})
            return _json({"verdict": "有毛病",
                          "findings": [{"level": "error", "step": 2,
                                        "kind": "math",
                                        "quote": "第 2 步的界不对"}],
                          "reason": "彩排：第 2 步不成立"})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            return self._step(m.group(1))
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["夹具"]})

    # ------------------------------------------------------------ 传输
    def __call__(self, url: str, headers: Any, body: bytes,
                 timeout_sec: float) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages") or []
        system = next((str(x.get("content") or "") for x in messages
                       if x.get("role") == "system"), "")
        prompt = "\n".join(str(x.get("content") or "") for x in messages
                           if x.get("role") == "user")
        text = self._reply(system, prompt)
        self.bodies.append({"url": url, "system": system, "prompt": prompt})
        self.replies.append(text)
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


# ============================================================ 夹具


def _workspace(tmp_path: pathlib.Path) -> Store:
    """真工作区 + 一份 F 的证明手稿（稿号 000002 是签的载体）。"""
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / MANUSCRIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MANUSCRIPT_TEXT, encoding="utf-8")
    return st


def _run(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         verdict: str = "成立", lean: str = "0",
         via: str = "register_statement") -> dict[str, Any]:
    """从 CLI 入口真跑一趟；只替换出网那一层（+ 一个假 key）。"""
    st = _workspace(tmp_path)
    wire = _Wire(verdict=verdict, via=via)
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    # 这一组彩排钉的是"注册缺口 ⇒ final_refused"的旧现场：把 R9FIX-D5 的收工前
    # 自动收尾关掉，否则静默子代理会在 final 那一拍被框架销掉、rc 变 0。
    from agentflow.agent_loop import AgentLoop
    _auto = AgentLoop.auto_retire_before_final
    AgentLoop.auto_retire_before_final = False
    try:
        try:
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli.main(["start", "--mode", "research", "--root", str(st.root),
                               "--sid", "rc2-main-chain", "--task",
                               f"把 {MANUSCRIPT} 收录进命题台账", "--max-steps", "6",
                               "--subagents"])
        except SystemExit as exc:                 # `cli.main` 正常是 return，不是 raise
            rc = int(exc.code or 0)
    finally:
        AgentLoop.auto_retire_before_final = _auto
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue()}


def _events(ws: pathlib.Path) -> list[dict]:
    """这一趟的会话事件（不按 sid 过滤：V 的工具路径那一支用自己的缝）。"""
    got: list[dict] = []
    for path in sorted((ws / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
    return got


def _tool_result(events: list[dict], *, role: str, tool: str) -> dict:
    for e in events:
        if (e.get("kind") == "agent_step" and e.get("role") == role
                and e.get("shape") == "tool"
                and str((e.get("payload") or {}).get("name") or "") == tool):
            return dict(e.get("result") or {})
    raise AssertionError(f"{role} 没有调过工具 {tool}（会话事件里找不到）")


def _rows(store: Store, table: str) -> list[dict]:
    return [dict(r) for r in store.rows(table)]


def _pending_rows(ws: pathlib.Path) -> list[dict]:
    """三签的 pending 台账（按正文 sha 分文件；空 = 一签都没落）。"""
    base = VR.pending_dir(ws)
    if not base.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(base.glob("*.jsonl")):
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    return rows


def _nontriviality_rows(ws: pathlib.Path) -> list[dict]:
    path = SEC.nontriviality_path(ws)
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


# ============================================================ 正控：主链走通


def test_the_proof_main_chain_runs_from_the_cli_with_only_the_wire_replaced(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：M 派 B → B 送 V → V 三签 → 收方秘书落块 → B 判档 T2 + 收录 + 依赖读数。

    读盘（不看回执 ok）：statements 1 行、pending 三行、稿上有 `- V 签：…连续=3/3`、
    `nontriviality.jsonl` 一行 T2、依赖面 `none_in_proof`、账本 `unattributed=0`。
    """
    got = _run(tmp_path, monkeypatch, lean="0")
    ws, st = got["ws"], got["store"]

    # ---- 入口与"只换了网线"（两步都不能省）
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」，不是「换掉造缝的那一层」")
    # 真 LlmSeam 落下的审计记录（不是替身缝：替身缝不落 llm_call 事件）
    calls = [e for e in _events(ws) if e.get("kind") == "llm_call"]
    assert calls, "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam"
    assert all(str(c.get("ledger", {}).get("reason") or "") in
               {"charged", "duplicate", "no_meter"} for c in calls), calls[:2]

    # ---- 派活：M → B → V（tasks 三行都是产品落的）
    tasks = {str(r.get("task_id")): r for r in _rows(st, "tasks")}
    by_role = {str(r.get("role")): r for r in tasks.values() if not str(r.get("kind") or "")}
    assert set(by_role) == {"M", "B", "V"}, sorted(by_role)
    assert str(by_role["B"].get("called_by")) == "M" and str(by_role["B"].get("outcome")) == "ok"
    assert str(by_role["V"].get("called_by")) == "B" and str(by_role["V"].get("outcome")) == "ok"

    # ---- 送审 + 三签：V 的 verify.verify_proof 三转全 clean，签块落回稿
    verdict = _tool_result(_events(ws), role="V", tool="verify.verify_proof")
    data = dict(verdict.get("data") or {})
    assert data.get("checked") is True, data
    passes = list(data.get("review_passes") or [])
    assert len(passes) == 3, f"签的门槛是 3 转（SIGN_STREAK_NEED=3），实得 {len(passes)} 转"
    assert [p.get("pass") for p in passes] == [1, 2, 3], passes
    assert all(str(p.get("axis")) == "clean" for p in passes), passes
    assert str(passes[-1].get("terminal") or "") == "signed", passes[-1]
    assert all(str(p.get("verification_id") or "") for p in passes), passes
    pending = _pending_rows(ws)
    assert len(pending) == 3, f"pending 台账应三行（一行一转），实得 {len(pending)}"
    text = (ws / MANUSCRIPT).read_text(encoding="utf-8")
    assert "- V 签：已签=true" in text and "连续=3/3" in text, text[-500:]
    assert any(p.suffix == ".json" for p in (ws / "out" / "vsigns").glob("*.json")), \
        "签的信封文件没落盘"

    # ---- 判非平凡度：先判、后落行（业主 2026-11-15 的次序）
    tiers = _nontriviality_rows(ws)
    assert len(tiers) == 1, f"档位台账应恰好一行，实得 {len(tiers)}"
    assert str(tiers[0].get("label") or "") == "T2", tiers[0]
    assert int(tiers[0].get("nontriviality") or -1) == 2, tiers[0]
    assert int(tiers[0].get("path_group") or 0) == 1, tiers[0]
    assert str(tiers[0].get("stmt_id") or ""), "档位行没挂命题号"
    assert str(tiers[0].get("role") or "") == "B", tiers[0]

    # ---- 收录 + 依赖：statements 一行、依赖面如实报「空表=声明自足」
    statements = _rows(st, "statements")
    assert len(statements) == 1, statements
    row = statements[0]
    assert str(row.get("statement_text") or "") == PROPOSITION, row
    assert str(row.get("proof_text") or "") == PROOF, row
    register = dict(_tool_result(_events(ws), role="B", tool="own.register_statement").get("data") or {})
    assert register.get("ok") is True and str(register.get("refused") or "") == "", register
    assert register.get("deps_state") == "none_in_proof", register.get("deps_state")
    assert int(register.get("deps_written") or 0) == 0, register.get("deps_written")
    assert (register.get("nontriviality_record") or {}).get("label") == "T2", \
        register.get("nontriviality_record")
    assert register.get("proposition_form", {}).get("released") is True, \
        "F 手稿的形态闸应在产出侧判过（B 侧放行）"

    # ---- 钱：账本有行、无主为 0、没有悬空号
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(st)
    assert money["ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ 判据①「每笔一行账」


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行。

    读数是逐笔的，不是汇总的：

    - `llm_call` 事件数 = 出网层真的被调到的次数（`wire.bodies`）；
    - `usage_ledger` 里模型调用级的行数（`note` 以 `source=llmseam;` 开头）与它相等；
    - 每一笔 `charged` 的 `usage_id` 指到一行，且行上的 `(role, task_id, call_index)`
      与事件的 `(role, task_id)`、会话号逐字对上；
    - `duplicate` 数 = 0（那一档的语义是"这次真调用被判成已经记过了 ⇒ 静默不记"）。

    为什么单独成判据：三格只要求"账本有行、无主 0、悬空 0"，一笔被 `duplicate`
    吞掉的钱不会让那条绿变红 —— 它只是让账本少一行，而少掉的那一行正好是
    "这次真调用"的审计面。这条判据把"少"变成红。

    Lean 开/关两档都跑：记账与开关无关，但"两档的读数都干净"必须自己说出来，
    不能靠"另一档没跑所以没红"。
    """
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = _ledger_identity(got["ws"], got["store"])
    print(f"[一行账] lean={lean} 真调用={reading['calls']} 出网={len(got['wire'].bodies)} "
          f"账本行={reading['rows']} duplicate={len(reading['duplicates'])} "
          f"未配对={len(reading['unpaired'])} 未认领={len(reading['unclaimed'])}")
    assert reading["calls"] == len(got["wire"].bodies), (
        "有真调用没有落 `llm_call` 事件（或反之）："
        f"事件 {reading['calls']} / 出网 {len(got['wire'].bodies)}")
    problems = _one_row_per_call_problems(reading)
    assert problems == [], "判据①红：\n- " + "\n- ".join(problems)


# ============================================================ 判据②「会话归口」


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_llm_call_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据②：这一趟所有 `llm_call` 事件都落在本趟 `sid`，缺省会话 0 条。

    三格不红的原因不是它守住了这一格：账本按 ambient task 归口，
    一条没有 `sid` 的缝（工具路径按 env 现造的第二条）照样记对账、照样让三格绿，
    而它的审计事件全落在 `sessions/<当天日期>.jsonl` 上。所以会话归口必须
    单独判，且判据的对象是会话文件，不是账本。

    顺带把装配读数钉住：`llmseam.role_seam("V")` 必须是这一趟装配的那一条
    （`sid` = 本趟、`budget_of` 与 `meter` 都在），而不是"登记过、没人用"的摆设。
    """
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    split = _session_split(got["ws"])
    print(f"[会话归口] lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} "
          f"会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = _session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)
    assert len(split["in_run"]) == len(got["wire"].bodies), (
        f"本趟会话 {len(split['in_run'])} 条 / 出网 {len(got['wire'].bodies)} 次")
    from agentflow import llmseam as LS

    seam = LS.role_seam("V")
    assert isinstance(seam, LS.LlmSeam), (
        "装配期没有给 V 登记按角色缝 ⇒ 工具路径会按 env 现造第二条（无 sid / 无 budget_of）")
    assert str(seam.sid or "") == SID, (
        f"登记的 V 缝不是这一趟的会话（sid={seam.sid!r}）：工具路径照样落缺省会话")
    assert seam.meter is not None, "登记的 V 缝没有接账本 ⇒ 工具路径的调用不会进 usage_ledger"
    assert callable(seam.budget_of), "登记的 V 缝没有 budget_of ⇒ 预算轴与本体那条缝不是同一个数"
    assert seam.spend.calls > 0, (
        "登记的 V 缝一次都没被用过 ⇒ 它只是躺在注册表里，工具路径仍然走别的缝")


# ============================================================ 反真空：V 不签


def test_a_rejected_proof_means_no_signature_no_ledger_row_for_the_statement(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：V 判「有毛病」⇒ 三签不成立 ⇒ 稿上无签块、`statements` 0 行。

    它证明正控里那些绿是门在承重：同一条 CLI 路、同一个缝、同一份稿，只把
    "模型怎么判"换掉，链就红。若这一条也绿，正控就是橡皮图章。
    """
    got = _run(tmp_path, monkeypatch, verdict="有毛病", lean="0")
    ws, st = got["ws"], got["store"]
    assert got["wire"].bodies, "反真空没真的问过模型"
    verdict = _tool_result(_events(ws), role="V", tool="verify.verify_proof")
    data = dict(verdict.get("data") or {})
    assert data.get("checked") is True, data
    assert str(data.get("verdict") or "") == "有毛病", data.get("verdict")
    passes = list(data.get("review_passes") or [])
    assert len(passes) == 1, (
        "判出毛病就该立刻停（不进第二转）", passes)
    assert str(passes[0].get("terminal") or "") == "rejected", passes[0]
    assert int(passes[0].get("unresolved_errors") or 0) >= 1, passes[0]
    text = (ws / MANUSCRIPT).read_text(encoding="utf-8")
    assert "- V 签：已签=true" not in text, "判了有毛病却把签块盖上了"
    # 负判的判词照落 pending（那是"V 看过、结论是不成立"，不是签）：一行、判词有毛病。
    negative = _pending_rows(ws)
    assert len(negative) == 1, negative
    assert str(negative[0].get("verdict") or "") == "有毛病", negative[0]
    assert _rows(st, "statements") == [], "没有签却把命题收进了台账"
    # B 的收录口要如实拒（受控拒读数，不是静默失败）
    register = dict(_tool_result(_events(ws), role="B", tool="own.register_statement").get("data") or {})
    assert register.get("ok") is False, register
    assert "签" in str(register.get("reason") or ""), register.get("reason")


# ============================================================ 链 b：ingest_manuscript 线


def test_the_pointer_ingest_line_also_judges_the_tier_before_landing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：同一份稿改成走 `B.ingest_manuscript(mode="register")` ⇒ 也判档、也收录。

    这条线是「指针式登记」的另一半（`register_statement` 那条已在正控里走过）：
    业主 2026-11-15 说「两种录入线都真带稿」。判据读盘与正控同一批：statements 1 行、
    档位一行 T2、`deps_state="none_in_proof"`，且回执的 `mode` 是 `register`。
    """
    got = _run(tmp_path, monkeypatch, lean="0", via="ingest_manuscript")
    ws, st = got["ws"], got["store"]
    assert got["rc"] == 0, (got["rc"], got["stderr"][-1500:])
    register = dict(_tool_result(_events(ws), role="B",
                                 tool="own.ingest_manuscript").get("data") or {})
    assert register.get("ok") is True, register
    assert str(register.get("mode") or "") == "register", register.get("mode")
    assert str((register.get("target") or {}).get("stmt_id") or ""), register.get("target")
    statements = _rows(st, "statements")
    assert len(statements) == 1, statements
    assert str(statements[0].get("statement_text") or "") == PROPOSITION, statements[0]
    tiers = _nontriviality_rows(ws)
    assert len(tiers) == 1 and str(tiers[0].get("label") or "") == "T2", tiers
    assert str(tiers[0].get("stmt_id") or "") == str(statements[0].get("stmt_id")), tiers[0]
    # 签名仍然生效（同一份稿只认领一次，签块在稿上）
    assert "- V 签：已签=true" in (ws / MANUSCRIPT).read_text(encoding="utf-8")


# ============================================================ Lean 关档


def test_the_same_chain_runs_with_lean_off_and_no_l_in_the_roster(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lean 关档（`AGENTFLOW_LEAN_ENABLED=0`）同一条链照跑，且名册里没有 L。

    关档此前的链级覆盖 = 0（`temp/sp/REPORT-SP.md` §五：14 份彩排全跑在开档，
    off 档只有单点判据）。这一条把"关档下主链仍然从 CLI 走到收录"钉住。
    """
    got = _run(tmp_path, monkeypatch, lean="0")
    ws, st = got["ws"], got["store"]
    assert got["rc"] == 0, (got["rc"], got["stderr"][-1500:])
    # 开关的读数（现读，不是猜）
    from agentflow import leanscope as LS

    reading = LS.lean_reading()
    assert reading.verdict == "off", reading.to_dict()
    assert LS.is_hidden("L") is True, "关档下 L 应当不存在"
    # 链照跑：签 + 收录都在
    assert "- V 签：已签=true" in (ws / MANUSCRIPT).read_text(encoding="utf-8")
    assert len(_rows(st, "statements")) == 1, _rows(st, "statements")
    # 名册/任务里没有 L（关档的"隔绝"在链级也成立）
    roles = {str(r.get("role")) for r in _rows(st, "tasks")}
    assert "L" not in roles, sorted(roles)
    events = _events(ws)
    assert not [e for e in events if str(e.get("role") or "") == "L"], \
        "关档下 L 不该有任何一步"


# ============================================================ Lean 开档


def test_the_same_chain_runs_with_lean_on(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lean 开档（`AGENTFLOW_LEAN_ENABLED=1`）同一条链：签、收录、两组新读数都在。

    关档那条（上一条）与这一条合起来才是"两档都跑过"：只跑一档时，另一档的绿
    没有判据看着。这一条刻意重复正控的盘上读数（签块 / statements 1 行），
    因为"开档下这条链仍然走到收录"本身就是要钉住的那一格 —— 形式化开着时
    名册里多一个 L，不能改变主链的终态。
    """
    got = _run(tmp_path, monkeypatch, lean="1")
    ws, st = got["ws"], got["store"]
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    from agentflow import leanscope as LS

    reading = LS.lean_reading()
    assert reading.verdict == "on", reading.to_dict()
    assert LS.is_hidden("L") is False, "开档下 L 应当存在"
    # 链照跑：签 + 收录都在（与关档同一批盘上读数）
    assert "- V 签：已签=true" in (ws / MANUSCRIPT).read_text(encoding="utf-8")
    assert len(_rows(st, "statements")) == 1, _rows(st, "statements")
    # 两组新判据在开档下也干净（判据本体与正控/反真空是同一份）
    assert _session_problems(_session_split(ws)) == [], _session_split(ws)["elsewhere"]
    assert _one_row_per_call_problems(_ledger_identity(ws, st)) == [], (
        _ledger_identity(ws, st))
