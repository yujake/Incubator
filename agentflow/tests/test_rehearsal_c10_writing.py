# -*- coding: utf-8 -*-
"""彩排（真路径）C10 · 成文/审校回路：G 成文 → H 审 → G 修订 → H 复审 + H 自行 close_as。

## 这条链与真机差在哪（逐项）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条 |
| 派活 | `Conductor.summon`（`M→G`、`M→H`；`G→H` 也是真边，本趟由 M 派两次 G、两次 H） | 同一条 |
| 成文 | `doc.compose_claim` / `doc.build_document` → `AgentG.*` | 同一条 |
| 审校 | `review.review_document` → `AgentH.review`（真 `scan_document`） | 同一条 |
| 修订 | `own.revise` → `AgentG.revise`（真改稿、真重渲染） | 同一条 |
| 复审 + 收尾 | `review.verify_fixes(close_as=…)` → 真三态判定 | 同一条：`close_as` 是 H 自己给的那一格 |
| 模型缝 | 真 `LlmSeam`（`_agent_seam_factory` / `for_role` / `for_secretary`） | 同一条：构造点一个都没替换 |
| 记账 | 真 `TokenMeter` → `usage_ledger` | 同一条 |
| 出网 | `modelgw.urllib_transport`（HTTP POST） | 只换这一处：回预置的 OpenAI 兼容 JSON |

旧 `test_rehearsal_c10_writing.py`（`CHAIN_ONLY` 里那份）直调 `AgentG.*` / `AgentH.*`，并
打桩 `review_tools.scan_document`；这一份两处都不换。

## 这条链覆盖什么（业主点名的 C10）

```text
M --summon--> G --doc.compose_claim--> 一条合规断言
                --doc.build_document--> documents 一行 + 渲染稿
                --doc.register_dependency(dangling)--> 一条拿不到的外部定理（留缺陷）
M --summon--> H --review.review_document--> review_findings 一行（dangling_dep / error）
M --summon--> G --own.revise--> 真修订（改的是 claims，不改依赖面）
M --summon--> H --review.verify_fixes(close_as="unresolved_review")--> H 自己收尾、交人复核
```

判据读盘：`documents` 一行且 `status="unresolved_review"`、`review_rounds=2`、
`review_findings` 一行 `kind="dangling_dep"`/`level="error"`/`status="open"`、
`dependencies` 一行 `status="dangling"`、G 的 `revise` 回执点名 `status="revised"`、
H 的 `verify_fixes` 回执 `verdict="unresolved_review"` 且逐条列出 `still_open`、钱账干净。

## 为什么 H 收尾而不是 accepted

这一趟 G 的修订真的跑了，但 H 的发现落在依赖面（引了一条拿不到的外部定理），
`G.revise` 只改断言、不改依赖 —— 所以 H 复审时那条 error 仍然复现。H 据此自己
给 `close_as="unresolved_review"` 交人复核。这不是"没修好"的意外：它正是业主
2026-11-15 裁定「收不收尾由 H 自己判，没有计数器替你收尾」要走的那一格。

## 反真空（把 close_as 拿掉）

同一条链、同一份盘，只把 H 复审时的 `close_as` 拿掉 ⇒ 判决必须落回 `revise_again`
（`blocking` 还在）、`documents.status` 停在 `in_review`、不许出现
`unresolved_review`。它证明"H 自行收尾"这件事真的压在 H 给的那一格上，不是轮数
到点或别的什么东西顺手带出来的。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：这条链不碰形式化，两档的盘上读数应当一致。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

import rehearsal_contract as RC

from agentflow import cli
from agentflow import leanscope as LS
from agentflow import modelgw as MG
from agentflow.store import Store

from conftest import (
    add_concept, add_literature, add_relation, sync_counters, write_paper,
)

SID = "cc3-c10"
CLAIM_TEXT = "数值抽样支持该结论。"
PAPER = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"\section{数值证据}",
    CLAIM_TEXT,
    r"\end{document}",
    "",
])
DISCLAIMER = "数值交叉验证，不构成证明"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _roster_names(prompt: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'"roster_name":\s*"([A-Z]\d*)"', prompt)]


def _doc_id_of(prompt: str) -> str:
    m = re.search(r'"doc_id":\s*"(\d+)"', prompt)
    return m.group(1) if m else ""


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self, *, close_as: bool = True) -> None:
        self.close_as = bool(close_as)
        self.bodies: list[dict[str, str]] = []
        self._steps: dict[Any, int] = {}
        self._done: list[str] = []
        #: M 已经跑过收工门没有（22B：有论文包的项目在 final 前必须先问一次门）。
        self._closed = False

    # ------------------------------------------------------------ 剧本
    def _m_step(self, prompt: str) -> str:
        index = self._steps.get("M", 0)
        self._steps["M"] = index + 1
        plan = [("G", "写一份稿：把数值证据成文"),
                ("H", "审这份稿"),
                ("G", "修订这份稿（按 H 的发现）"),
                ("H", "复核这份稿并决定收不收尾")]
        if index < len(plan):
            role, task = plan[index]
            return _json({"summon": {"role": role, "task": task}})
        todo = [n for n in _roster_names(prompt) if n not in self._done]
        if todo:
            self._done.append(todo[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": todo[0], "reason": "交完了"}})
        # 22B（2026-11-16）：这一趟盘上有论文包（`out/paper/main.tex`）⇒ 属"有门的
        # 项目"，M 在 final 之前必须先跑一次收工门。彩排照真机形态补这一拍。
        if not self._closed:
            self._closed = True
            return _json({"tool": "conductor.closing", "args": {
                "goal": "C10 成文 / 审校回路跑通（H 自行 close_as）",
                "goal_met": True,
                "basis": "documents 一行 unresolved_review、review_findings 一行 dangling_dep、"
                         "dependencies 一行 dangling、H 的 verify_fixes 已逐条列 still_open",
            }})
        return _json({"final": "M 收工", "evidence": []})

    def _step(self, role: str, prompt: str) -> str:
        doc = _doc_id_of(prompt) or "000000"
        if role == "M":
            return self._m_step(prompt)
        if role == "G":
            phase = "revise" if "修订" in prompt else "write"
            index = self._steps.get(("G", phase), 0)
            self._steps[("G", phase)] = index + 1
            if phase == "write":
                seq = [
                    _json({"tool": "doc.compose_claim",
                           "args": {"text": CLAIM_TEXT, "citations": ["lit:0000"],
                                    "evidence_kind": "cross_check", "section": "数值证据",
                                    "claim_id": "claim-1"}}),
                    _json({"tool": "doc.build_document",
                           "args": {"kind": "paper", "title": "C10 彩排稿",
                                    "claims": [{"text": CLAIM_TEXT,
                                                "citations": ["lit:0000"],
                                                "evidence_kind": "cross_check",
                                                "section": "数值证据",
                                                "disclaimer": DISCLAIMER,
                                                "claim_id": "claim-1"}],
                                    "open_problems": ["非交换环情形尚未处理"]}}),
                    _json({"tool": "doc.register_dependency",
                           "args": {"used_by": f"doc:{doc}", "kind": "theorem",
                                    "label": "外部定理：非交换环情形的定理",
                                    "status": "dangling",
                                    "status_reason": "彩排：引了一处我们拿不到的外部定理"}}),
                    _json({"final": "G 写完了", "evidence": []}),
                ]
            else:
                seq = [
                    _json({"tool": "own.revise",
                           "args": {"doc_id": doc, "note": "按 H 的发现修订"}}),
                    _json({"final": "G 改完了", "evidence": []}),
                ]
            return seq[min(index, len(seq) - 1)]
        if role == "H":
            phase = "verify" if "复核" in prompt else "review"
            index = self._steps.get(("H", phase), 0)
            self._steps[("H", phase)] = index + 1
            args: dict[str, Any] = {"doc_id": doc}
            if phase == "verify":
                args["round_no"] = 2
                if self.close_as:
                    args["close_as"] = "unresolved_review"
            tool = ("review.verify_fixes" if phase == "verify"
                    else "review.review_document")
            seq = [
                _json({"tool": "doc.list_documents", "args": {}}),
                _json({"tool": tool, "args": args}),
                _json({"final": "H 判完了", "evidence": []}),
            ]
            return seq[min(index, len(seq) - 1)]
        return _json({"final": f"{role} 收工", "evidence": []})

    def _reply(self, system: str, prompt: str) -> str:
        head = system.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            table = {
                "dispatch_fit": {"decision": "这一件能做", "reason": "彩排",
                                 "basis": ["夹具"]},
                "statement_aesthetic": {"decision": "T2", "reason": "彩排",
                                        "basis": ["夹具"]},
            }
            return _json(table.get(m.group(1), {"decision": "可派", "reason": "彩排",
                                                "basis": ["夹具"]}))
        if head.startswith("你是「命题形态闸」"):
            return _json({"well_formed": True, "conditions": "夹具", "conclusion": "夹具",
                          "problems": [], "decision": "形态合规", "refused": "",
                          "reason": "彩排"})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            return self._step(m.group(1), prompt)
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["夹具"]})

    def __call__(self, url: str, headers: Any, body: bytes,
                 timeout_sec: float) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages") or []
        system = next((str(x.get("content") or "") for x in messages
                       if x.get("role") == "system"), "")
        prompt = "\n".join(str(x.get("content") or "") for x in messages
                           if x.get("role") == "user")
        text = self._reply(system, prompt)
        self.bodies.append({"system": system, "prompt": prompt, "text": text})
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


# ============================================================ 夹具


def _workspace(base: pathlib.Path) -> Store:
    """一个最小可成文的工作区：一条文献 + 两条概念 + 一条关系 + 一份论文正文。"""
    st = Store(base / "ws")
    st.init()
    add_literature(st, "0000", title="夹具文献", processed=True, sync=False)
    add_concept(st, "0000", "谱", definition="d", sync=False)
    add_concept(st, "0001", "区间", definition="d", sync=False)
    add_relation(st, "0000", ["0000", "0001"], "0000",
                 quote="Spectrum lies in the interval.",
                 description="谱落在区间内", quote_verified=True, sync=False)
    sync_counters(st)
    write_paper(st, PAPER)
    return st


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0", close_as: bool = True) -> dict[str, Any]:
    st = _workspace(base)
    wire = _Wire(close_as=close_as)
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root), "--sid", SID,
                "--subagents", "--task", "把数值证据成文并审校", "--max-steps", "12",
            ])
    except SystemExit as exc:
        rc = int(exc.code or 0)
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "close_as": close_as}


def _events(ws: pathlib.Path) -> list[dict]:
    got: list[dict] = []
    for path in sorted((ws / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
    return got


def _tool_result(events: list[dict], *, role: str, tool: str, index: int = 0) -> dict:
    hits = [e for e in events
            if e.get("kind") == "agent_step" and e.get("role") == role
            and e.get("shape") == "tool"
            and str((e.get("payload") or {}).get("name") or "") == tool]
    assert len(hits) > index, f"{role} 没有第 {index + 1} 次调过工具 {tool}"
    got = hits[index].get("result") or {}
    data = got.get("data")
    if hasattr(data, "to_dict"):
        data = dict(data.to_dict())
    return {"ok": bool(got.get("ok")), "data": data if isinstance(data, dict) else {},
            "error": str(got.get("error") or "")}


def _rows(store: Store, table: str) -> list[dict]:
    return [dict(r) for r in store.rows(table)]


def _reading(got: dict[str, Any]) -> dict[str, Any]:
    st, ws = got["store"], got["ws"]
    events = _events(ws)
    documents = _rows(st, "documents")
    doc = dict(documents[0]) if documents else {}
    return {
        "store": st, "ws": ws, "events": events,
        "documents": documents, "doc": doc,
        "findings": _rows(st, "review_findings"),
        "dependencies": _rows(st, "dependencies"),
        "tasks": _rows(st, "tasks"),
        "reviewed": _tool_result(events, role="H", tool="review.review_document"),
        "revised": _tool_result(events, role="G", tool="own.revise"),
        "verified": _tool_result(events, role="H", tool="review.verify_fixes"),
    }


def _chain_problems(reading: dict[str, Any]) -> list[str]:
    """C10 的终态读数（空 = 通）。每个字都读盘，不看回执里的 ok。"""
    problems: list[str] = []
    st: Store = reading["store"]

    # 1. 成文：documents 一行、断言合规、稿在盘上。
    documents = reading["documents"]
    if len(documents) != 1:
        problems.append(f"documents 应恰好 1 行，实得 {len(documents)} 行")
    doc = dict(reading["doc"])
    claims = [dict(c) for c in (doc.get("claims") or [])]
    if len(claims) != 1 or str(claims[0].get("text") or "") != CLAIM_TEXT:
        problems.append(f"documents.claims 不是 G 给的那一条：{claims}")
    elif str(claims[0].get("disclaimer") or "") != DISCLAIMER:
        problems.append(f"cross_check 的受控声明丢了：{claims[0].get('disclaimer')!r}")
    rel = str(doc.get("markdown_path") or "")
    if not rel or not (pathlib.Path(st.root) / rel).is_file():
        problems.append(f"渲染稿没落盘：{rel!r}")

    # 2. H 审：dangling_dep / error 落成 findings 一行、仍 open。
    findings = reading["findings"]
    if len(findings) != 1:
        problems.append(f"review_findings 应恰好 1 行，实得 {len(findings)} 行：{findings}")
    else:
        f = findings[0]
        if str(f.get("kind") or "") != "dangling_dep":
            problems.append(f"finding 的 kind 不是 dangling_dep：{f.get('kind')!r}")
        if str(f.get("level") or "") != "error":
            problems.append(f"finding 的 level 不是 error：{f.get('level')!r}")
        if str(f.get("status") or "") != "open":
            problems.append(f"finding 该仍 open：{f.get('status')!r}")
    if str(reading["reviewed"]["data"].get("verdict") or "") != "rejected":
        problems.append(f"H 首审该 rejected：{reading['reviewed']['data'].get('verdict')!r}")

    # 3. 依赖面：那一行真的在盘上、状态是 dangling（缺陷是造出来的、不是编的）。
    deps = reading["dependencies"]
    if len(deps) != 1 or str(deps[0].get("status") or "") != "dangling":
        problems.append(f"dependencies 不是一行 dangling：{deps}")

    # 4. G 修订：真跑了、稿件进了下一版。
    revised = reading["revised"]
    if not revised["ok"]:
        problems.append(f"G 的 revise 回执不是 ok：{revised['error']!r}")
    if str(revised["data"].get("status") or "") not in ("revised", "draft", "in_review"):
        problems.append(f"G 修订后的 status 不对：{revised['data'].get('status')!r}")

    # 5. H 复审 + 收尾：三态词表里的 unresolved_review，且 still_open 逐条列出。
    verified = reading["verified"]
    if not verified["ok"]:
        problems.append(f"H 的 verify_fixes 回执不是 ok：{verified['error']!r}")
    data = verified["data"]
    if str(data.get("verdict") or "") != "unresolved_review":
        problems.append(f"H 复审该判 unresolved_review：{data.get('verdict')!r}")
    if not data.get("still_open"):
        problems.append("H 判了 unresolved_review，却没有逐条列出仍未解决的发现")
    if str(doc.get("status") or "") != "unresolved_review":
        problems.append(f"documents.status 该是 unresolved_review：{doc.get('status')!r}")
    if int(doc.get("review_rounds") or 0) != 2:
        problems.append(f"documents.review_rounds 该是 2：{doc.get('review_rounds')!r}")
    return problems


# ============================================================ ① 正控：链走通（H 自行收尾）


def test_the_writing_chain_runs_from_the_cli_and_h_closes_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：G 成文 → H 审出 dangling_dep → G 修订 → H 复审并自行 close_as（Lean 关）。"""
    got = _run(tmp_path, monkeypatch, lean="0", close_as=True)
    reading = _reading(got)

    # ---- 入口与"只换了网线"
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」")
    assert [e for e in reading["events"] if e.get("kind") == "llm_call"], (
        "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam")

    problems = _chain_problems(reading)
    assert problems == [], problems
    # H 的收尾判断落在账上（不是只在回执里）：`close_as` 是 H 自己给的那一格。
    assert "close_as" in str(reading["verified"]["data"].get("reason") or ""), (
        reading["verified"]["data"].get("reason"))
    # 四个角色任务都真的跑过（M + G×2 + H×2）。
    roles = [str(t.get("role")) for t in reading["tasks"] if not str(t.get("kind") or "")]
    assert roles.count("G") == 2 and roles.count("H") == 2, roles

    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空：拿掉 close_as


def test_without_close_as_h_does_not_close_the_document(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：同一份稿、同一条链，只把 H 复审时的 `close_as` 拿掉 ⇒ H 不许自行收尾。

    它证明"H 自己收尾"压在那一格上：拿掉它之后判决必须落回 `revise_again`、
    稿件停在 `in_review`，且盘上不许出现 `unresolved_review`。
    """
    got = _run(tmp_path, monkeypatch, lean="0", close_as=False)
    reading = _reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    data = reading["verified"]["data"]
    assert str(data.get("verdict") or "") == "revise_again", data.get("verdict")
    assert data.get("still_open"), "没修好的发现必须逐条列出（不许隐藏）"
    assert str(reading["doc"].get("status") or "") == "in_review", reading["doc"].get("status")
    assert str(reading["doc"].get("status") or "") != "unresolved_review"
    # 其它腿没有因此退化：H 审出发现、G 修订照跑。
    assert [f.get("kind") for f in reading["findings"]] == ["dangling_dep"], reading["findings"]
    assert reading["revised"]["ok"] is True, reading["revised"]


# ============================================================ 判据①：每笔真调用一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    print(f"[一行账] lean={lean} 真调用={reading['calls']} 出网={len(got['wire'].bodies)} "
          f"账本行={reading['rows']} duplicate={len(reading['duplicates'])} "
          f"未配对={len(reading['unpaired'])} 未认领={len(reading['unclaimed'])}")
    assert reading["calls"] == len(got["wire"].bodies), (
        "有真缝调用没有落 `llm_call` 事件（或反之）："
        f"事件 {reading['calls']} / 出网 {len(got['wire'].bodies)}")
    problems = RC.one_row_per_call_problems(reading)
    assert problems == [], "判据①红：\n- " + "\n- ".join(problems)


# ============================================================ 判据②：会话归口


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_llm_call_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据②：这一趟所有 `llm_call` 事件都落在本趟 `sid`，缺省会话 0 条。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    split = RC.session_split(got["ws"], SID)
    print(f"[会话归口] lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_the_chain_runs_in_both_lean_modes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档：同一条链照跑、H 照样自行收尾；关档下名册里没有 L。"""
    got = _run(tmp_path, monkeypatch, lean=lean, close_as=True)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    reading = LS.lean_reading()
    assert reading.verdict == verdict, reading.to_dict()
    assert LS.is_hidden("L") is hidden, (lean, reading.to_dict())
    problems = _chain_problems(_reading(got))
    assert problems == [], problems
    from agentflow import schema as S

    roles = set(LS.visible_roles(S.ROLES))
    assert ("L" in roles) is (not hidden), sorted(roles)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
