# -*- coding: utf-8 -*-
"""彩排（真路径）C9 · 概念图链：CLI 入口 → M→C（读数 + 登记报告）→ M→D（缺口立题）→ M→B（结构重复裁决）。

## 这条链钉的是什么

```text
C --own.gaps--> 缺口报告（自动登记进 analysis_reports）
C --own.structural_duplicates--> 结构重复候选
C --analysis.register_report(kind="paths", payload={"candidates": …})--> 候选进台账
D --table.list--> 读 analysis_reports 里那份 gaps 报告
D --own.ingest--> research_questions 一行（origin 指回 C 的报告号）
D --own.consider--> 状态机推进（或交缺口请求）
B --table.list--> 读 analysis_reports 里那份 paths 报告
B --own.decide_structural_duplicate--> 逐条裁决（merge / reject）
B --own.resolve_structural_duplicate--> 真合并：墓碑 + 关系改写（reject 那一条一个字节都不写）
```

## 与真机差在哪

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 / 执行体 / 缝 / 记账 / 出网 | CLI → `_exec_role` → `LlmBackend` → `AgentLoop.run`；真 `LlmSeam` / `TokenMeter` / `urllib_transport` | 同一条；只换出网那一处 |
| C 的读数 | `own.gaps` / `own.structural_duplicates` 由模型经工具分发调到 | 同一条（动作本体、图算法、登记通道全是产品原物） |
| C→D / C→B 的数据面 | `analysis_reports`（只读角色的唯一写入口） | 同一条：D 与 B 都用 `table.list` 读同一张表 |
| 立题 / 裁决 | `AgentD.ingest` / `AgentB.decide_structural_duplicate` | 同一条 |

旧版（改写前登记在 `CHAIN_ONLY` 里）直调
`AgentC.gaps` / `AgentD.ingest` / `AgentB.decide_structural_duplicate`，反真空还替换
`AgentC.gaps`；这一份一处都不换。

## 终态读数（全读盘）

- `analysis_reports`：`gaps` 一行（C 的动作自己登记）+ `paths` 一行（C 按读数登记）。
- `research_questions`：一行；`origin` 以 `C:gaps:<报告号>:` 开头、`related_concept_ids`
  是缺口那两个；`consider` 之后不再停在"什么都没发生"。
- 结构重复：0000/0001 判 `merge` 并执行 ⇒ `statements` 里被合并那一条
  `status=superseded` 且 `quote_reason` 点名 survivor、`relations` 不再指着被合并方；
  0008/0009（名字不同）判 `reject`、`applied=False`、概念表一个字节不动。
- 读数锚定：C 报告里的概念号 / 关系号都能在台账里查到。

## 反真空（同一个工作区里造红）

0008/0009 那一对「邻域相同但名字不同」必须被 B 拒（`reject` + `applied=False`），
且概念表逐字不变 —— 它证明 merge 那一条的墓碑不是"resolve 恒写"：结构等价 ≠ 同义，
合并决定权在 B，拒的那一档连墓碑都不落。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：这条链不碰 `formal.*`；关档下名册里没有 L。
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
from agentflow import conceptrows as CR
from agentflow import leanscope as LS
from agentflow import modelgw as MG
from agentflow.store import Store

from conftest import (add_concept, add_literature, add_relation, sync_counters)

SID = "cc4-c9"
TS = "2026-01-01T00:00:00+00:00"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _last_result(prompt: str) -> dict:
    """把 prompt 里那一行 `框架执行结果：{…}` 解析回对象（产品自己的数列化形态）。

    只取第一个 JSON 对象：那一行后面还接着"现在是第 N 步…"的协议说明。
    """
    idx = prompt.rfind("框架执行结果：")
    if idx < 0:
        return {}
    blob = prompt[idx + len("框架执行结果："):].lstrip()
    try:
        got, _end = json.JSONDecoder().raw_decode(blob)
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _rows_of(result: dict) -> list[dict]:
    """`table.list` 回执里的 `data.rows`（产品把行序列化成了一段 JSON 字符串）。"""
    rows = result.get("data.rows")
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except ValueError:
            return []
    if isinstance(rows, list):
        return [dict(x) for x in rows if isinstance(x, dict)]
    data = result.get("data")
    if isinstance(data, dict):
        inner = data.get("rows")
        if isinstance(inner, str):
            try:
                inner = json.loads(inner)
            except ValueError:
                return []
        if isinstance(inner, list):
            return [dict(x) for x in inner if isinstance(x, dict)]
    return []


def _row_of(result: dict) -> dict:
    """`table.get` 回执（行对象可能被摊平成 `data.<字段>` 的键）。"""
    data = result.get("data")
    if isinstance(data, dict) and str(data.get("report_id") or ""):
        return dict(data)
    row: dict[str, Any] = {}
    for key, value in result.items():
        if key.startswith("data."):
            row[key[len("data."):]] = value
    return row


def _first_gap(data: Any) -> dict:
    """从 C 的 `own.gaps` 回执里读出第一条候选（回执是 repr，且长回执会被观测层截断）。

    真机的模型读到的也是这一段：候选的 `key` / `concept_ids` / `kind` 在截断之前就
    露出来了，后面的长字段（reason / signals）被截掉不影响"把它立成机器可读的一份"。
    回执是 Python repr（单引号），两种引号都要认。
    """
    text = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    out: dict[str, Any] = {}
    for key in ("key", "kind", "confidence"):
        m = re.search(rf"""["']?{key}["']?\s*:\s*["']([^"']*)["']""", text)
        if m:
            out[key] = m.group(1)
    for key in ("concept_ids", "concept_names"):
        m = re.search(rf"""["']?{key}["']?\s*:\s*\[([^\]]*)\]""", text)
        if m:
            try:
                out[key] = json.loads("[" + m.group(1).replace("'", '"') + "]")
            except ValueError:
                pass
    return out if out.get("concept_ids") else {}


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self) -> None:
        self.bodies: list[dict[str, str]] = []
        self.steps: dict[str, int] = {}
        self.retired: list[str] = []
        #: 从 C 的回执里读到的候选（C 登记时写进报告 payload 的那一份）。
        self.candidates: list[dict] = []
        self.gaps_payload: dict = {}
        self.gaps_rid = ""

    def _roster(self, prompt: str) -> list[str]:
        return [n for n in re.findall(r'"roster_name":\s*"([A-Z]\d*)"', prompt)
                if n not in self.retired]

    def _retire_then(self, prompt: str, nxt: str) -> str:
        names = self._roster(prompt)
        if names:
            self.retired.append(names[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": names[0], "reason": "交完了"}})
        return nxt

    # ------------------------------------------------------------ 剧本
    def _m(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"summon": {"role": "C",
                                     "task": "读概念图：报缺口，并把结构重复候选登记成一份报告"}})
        if index == 1:
            return _json({"summon": {"role": "D",
                                     "task": "把 C 最近登记的那份缺口报告立成研究问题并推进"}})
        if index == 2:
            return _json({"summon": {"role": "B",
                                     "task": "读 C 登记的那份结构重复报告，逐条裁决并执行"}})
        return self._retire_then(prompt, _json({"final": "M 收工", "evidence": []}))

    def _c(self, index: int, prompt: str) -> str:
        result = _last_result(prompt)
        if index == 0:
            return _json({"tool": "own.gaps",
                          "args": {"limit": 1, "request": "C9 缺口"}})
        if index == 1:
            gap = _first_gap(result.get("data"))
            self.gaps_payload = {
                "verdict": "有" if gap else "无", "has_candidates": bool(gap),
                "candidate_gaps": [gap] if gap else [],
            }
            return _json({"tool": "own.structural_duplicates", "args": {"limit": 10}})
        if index == 2:
            cands = list(result.get("data.candidates")
                         or (result.get("data") or {}).get("candidates") or [])
            self.candidates = [dict(c) for c in cands if isinstance(c, dict)]
            compact = {
                "verdict": str(self.gaps_payload.get("verdict") or "有"),
                "has_candidates": True,
                "candidate_gaps": [
                    {key: dict(c).get(key) for key in
                     ("key", "kind", "concept_ids", "concept_names",
                      "related_relation_ids", "confidence", "reason")}
                    for c in (self.gaps_payload.get("candidate_gaps") or [])
                    if isinstance(c, dict)],
            }
            return _json({"tool": "analysis.register_report", "args": {
                "kind": "gaps",
                "summary": "缺口报告的机器可读版（D 的 ingest 直接吃这一份）",
                "markdown": "# 缺口\n\n- 结构洞候选见 payload\n",
                "request": "C9 缺口（机器可读）",
                "payload": compact}})
        if index == 3:
            return _json({"tool": "analysis.register_report", "args": {
                "kind": "paths",
                "summary": "结构重复候选两份：0000/0001（同名）与 0008/0009（异名）",
                "markdown": ("# 结构重复候选\n\n"
                             "- 0000/0001：邻域相同且同名 ⇒ 建议 merge\n"
                             "- 0008/0009：邻域相同但异名 ⇒ 交给 B 判\n"),
                "request": "C9 结构重复",
                "payload": {"candidates": self.candidates}}})
        return _json({"final": "C 读数完了", "evidence": ["analysis_reports"]})

    def _d(self, index: int, prompt: str) -> str:
        result = _last_result(prompt)
        if index == 0:
            return _json({"tool": "table.list", "args": {
                "table": "analysis_reports", "filter": {"kind": "gaps"},
                "fields": ["report_id", "kind"], "limit": 20}})
        if index == 1:
            rows = [r for r in _rows_of(result) if str(r.get("kind") or "") == "gaps"]
            if not rows:
                return _json({"final": "没有可消化的报告", "evidence": []})
            self.gaps_rid = str(rows[-1].get("report_id") or "")
            return _json({"tool": "table.get",
                          "args": {"table": "analysis_reports", "id": self.gaps_rid}})
        if index == 2:
            row = _row_of(result)
            if not row:
                return _json({"final": "读不到那份报告", "evidence": []})
            return _json({"tool": "own.ingest", "args": {"report": row}})
        if index == 3:
            created = result.get("data") if isinstance(result.get("data"), list) else []
            qid = str((created[0] if created else "") or "")
            if not qid:
                return _json({"final": "缺口没有立出题", "evidence": []})
            return _json({"tool": "own.consider", "args": {"qid": qid}})
        return _json({"final": "D 立题完了", "evidence": []})

    def _b(self, index: int, prompt: str) -> str:
        result = _last_result(prompt)
        if index == 0:
            return _json({"tool": "table.list", "args": {
                "table": "analysis_reports", "filter": {"kind": "paths"},
                "fields": ["report_id", "kind"], "limit": 20}})
        if index == 1:
            rows = [r for r in _rows_of(result) if str(r.get("kind") or "") == "paths"]
            if not rows:
                return _json({"final": "没有可裁决的候选", "evidence": []})
            return _json({"tool": "table.get",
                          "args": {"table": "analysis_reports",
                                   "id": str(rows[-1].get("report_id") or "")}})
        if index == 2:
            row = _row_of(result)
            payload = dict(row.get("payload") or {})
            self.candidates = [dict(c) for c in (payload.get("candidates") or [])
                               if isinstance(c, dict)]
            if not self.candidates:
                return _json({"final": "报告里没有候选", "evidence": []})
            return _json({"tool": "own.decide_structural_duplicate",
                          "args": {"candidate": self.candidates[0]}})
        if index == 3:
            return _json({"tool": "own.resolve_structural_duplicate",
                          "args": {"candidate": self.candidates[0]}})
        if index == 4:
            return _json({"tool": "own.decide_structural_duplicate",
                          "args": {"candidate": self.candidates[1]}})
        if index == 5:
            return _json({"tool": "own.resolve_structural_duplicate",
                          "args": {"candidate": self.candidates[1]}})
        return _json({"final": "B 裁决完了", "evidence": []})

    # ------------------------------------------------------------ 回复分派
    def reply(self, *, system: str, prompt: str) -> str:
        head = system.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            kind = m.group(1)
            if kind == "proposition_form":
                return _json({"checked": True, "well_formed": True, "decision": "形态合规",
                              "conditions": "夹具", "conclusion": "夹具", "problems": [],
                              "refused": "", "reason": "彩排：形态合规"})
            if kind == "statement_aesthetic":
                return _json({"checked": True, "decision": "T2", "nontriviality": 2,
                              "path_group": 1, "reason": "彩排：T2", "basis": ["彩排"],
                              "label": "T2", "applicable": True})
            if kind in ("proposition_identity", "statement_same"):
                return _json({"checked": True, "decision": "different",
                              "canonical_name": "夹具", "same_as": "", "route": "",
                              "condition": "夹具", "conclusion": "夹具",
                              "reason": "彩排：不同一条", "basis": ["彩排"]})
            if kind == "statement_keywords":
                return _json({"checked": True, "keywords": ["群", "子群"],
                              "why": "彩排"})
            if kind == "dispatch_fit":
                return _json({"decision": "是一个方向", "reason": "只写了一个方向",
                              "basis": ["彩排"]})
            return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["彩排"]})
        if head.startswith("你是「命题形态闸」"):
            return _json({"checked": True, "well_formed": True, "decision": "形态合规",
                          "conditions": "夹具", "conclusion": "夹具", "problems": [],
                          "refused": "", "reason": "彩排：形态合规"})
        if "你是「命题台账检索」" in head:
            return _json({"keywords": ["群", "子群"], "why": "彩排"})
        if "你是验证者（V）" in (head + prompt)[:400]:
            return _json({"verdict": "成立", "why": "彩排", "findings": []})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            role = m.group(1)
            index = self.steps.get(role, 0)
            self.steps[role] = index + 1
            if role == "M":
                return self._m(index, prompt)
            if role == "C":
                return self._c(index, prompt)
            if role == "D":
                return self._d(index, prompt)
            if role == "B":
                return self._b(index, prompt)
            return _json({"final": f"{role} 收工", "evidence": []})
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["彩排"]})

    def __call__(self, url: str, headers: Any, body: bytes,
                 timeout_sec: float) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages") or []
        system = next((str(x.get("content") or "") for x in messages
                       if x.get("role") == "system"), "")
        prompt = "\n".join(str(x.get("content") or "") for x in messages
                           if x.get("role") == "user")
        text = self.reply(system=system, prompt=prompt)
        self.bodies.append({"system": system, "prompt": prompt, "text": text})
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


# ============================================================ 夹具与读数


def _workspace(tmp_path: pathlib.Path) -> Store:
    """一张小图：一对结构重复（0000/0001 同名）＋一对邻域相同但异名（0008/0009）。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_concept(st, "0000", "群",
                definition="一个带有二元运算的集合，满足结合律、单位元与逆元。", sync=False)
    add_concept(st, "0001", "群", definition="带有二元运算的集合。", sync=False)
    add_concept(st, "0002", "子群", definition="群的非空子集，对运算封闭。", sync=False)
    add_concept(st, "0003", "正规子群", definition="对共轭作用封闭的子群。", sync=False)
    add_concept(st, "0006", "交换环", definition="乘法交换的环。", sync=False)
    add_concept(st, "0007", "整环", definition="无零因子的交换环。", sync=False)
    add_concept(st, "0008", "甲概念", definition="夹具概念甲。", sync=False)
    add_concept(st, "0009", "乙概念", definition="夹具概念乙。", sync=False)
    add_literature(st, "0000", title="夹具文献甲", processed=True, sync=False)
    add_literature(st, "0001", title="夹具文献乙", processed=True, sync=False)
    for rid, cids, lit in (("0000", ["0000", "0002"], "0000"),
                           ("0001", ["0000", "0003"], "0000"),
                           ("0002", ["0001", "0002"], "0001"),
                           ("0003", ["0001", "0003"], "0001"),
                           ("0006", ["0002", "0008"], "0000"),
                           ("0007", ["0003", "0008"], "0001"),
                           ("0008", ["0002", "0009"], "0000"),
                           ("0009", ["0003", "0009"], "0001")):
        add_relation(st, rid, cids, lit, description="子群是群的结构，正规子群是子群。",
                     quote="子群是群的结构。", quote_verified=True, sync=False)
    add_relation(st, "0004", ["0006", "0007"], "0000",
                 description="交换环是整环", quote="交换环是整环", quote_verified=True,
                 sync=False)
    add_relation(st, "0005", ["0006", "0007"], "0001",
                 description="交换环不是整环", quote="交换环不是整环", quote_verified=True,
                 sync=False)
    sync_counters(st)
    return st


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0") -> dict[str, Any]:
    base.mkdir(parents=True, exist_ok=True)
    st = _workspace(base)
    wire = _Wire()
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root), "--sid", SID,
                "--subagents", "--task", "读图、立题、裁决结构重复", "--max-steps", "10",
            ])
    except SystemExit as exc:
        rc = int(exc.code or 0)
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue()}


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
            and str((e.get("payload") or {}).get("name") or "") == tool]
    assert len(hits) > index, f"{role} 没有第 {index + 1} 次调过 {tool}"
    got = hits[index].get("result") or {}
    data = got.get("data")
    if hasattr(data, "to_dict"):
        data = dict(data.to_dict())
    return {"ok": bool(got.get("ok")),
            "data": data if isinstance(data, dict) else data,
            "error": str(got.get("error") or "")}


def _chain_reading(got: dict[str, Any]) -> dict[str, Any]:
    st = got["store"]
    events = _events(got["ws"])
    return {
        "store": st, "ws": got["ws"], "events": events,
        "reports": [dict(r) for r in st.rows("analysis_reports")],
        "questions": [dict(r) for r in st.rows("research_questions")],
        "statements": [dict(r) for r in st.rows("statements")],
        "relations": [dict(r) for r in st.rows("relations")],
        "concepts": {str(r.get("concept_id")): dict(r)
                     for r in CR.view(st, shape="legacy")["rows"]},
        "gaps": _tool_result(events, role="C", tool="own.gaps"),
        "dups": _tool_result(events, role="C", tool="own.structural_duplicates"),
        "registered": _tool_result(events, role="C", tool="analysis.register_report"),
        "ingest": _tool_result(events, role="D", tool="own.ingest"),
        "merge_decision": _tool_result(events, role="B",
                                       tool="own.decide_structural_duplicate", index=0),
        "merge_resolve": _tool_result(events, role="B",
                                      tool="own.resolve_structural_duplicate", index=0),
        "reject_decision": _tool_result(events, role="B",
                                        tool="own.decide_structural_duplicate", index=1),
        "reject_resolve": _tool_result(events, role="B",
                                       tool="own.resolve_structural_duplicate", index=1),
    }


def _chain_anchor_problems(reading: dict[str, Any]) -> list[str]:
    """C 的读数都落在台账上（概念号 / 关系号查得到，报告真的登记了）。"""
    problems: list[str] = []
    kinds = sorted(str(r.get("kind")) for r in reading["reports"])
    #: C 的 `own.gaps` 自动登记一份（面向人读），另外按 `analysis.register_report`
    #: 登记了机器可读的 gaps + paths 两份 —— 后者是 D / B 真正吃的那一份。
    if kinds != ["gaps", "gaps", "paths"]:
        problems.append(f"analysis_reports 的 kind 集合不是 [gaps, gaps, paths]：{kinds}")
    concept_ids = set(reading["concepts"])
    rel_ids = {str(r.get("relation_id")) for r in reading["relations"]}
    by_kind = {str(r.get("kind")): dict(r) for r in reading["reports"]}
    for kind in ("gaps", "paths"):
        payload = dict((by_kind.get(kind) or {}).get("payload") or {})
        if kind == "gaps":
            if str(payload.get("verdict") or "") not in ("有", "无"):
                problems.append(f"gaps 报告的 verdict 不在二值里：{payload.get('verdict')!r}")
        for cand in (payload.get("candidate_gaps") or payload.get("candidates") or []):
            if not isinstance(cand, dict):
                continue
            for cid in (cand.get("concept_ids") or []):
                if str(cid) not in concept_ids:
                    problems.append(f"{kind} 的候选概念号不在 concepts 里：{cid!r}")
            for rid in (cand.get("related_relation_ids") or []):
                if str(rid) not in rel_ids:
                    problems.append(f"{kind} 的关系号不在 relations 里：{rid!r}")
    if not str(reading["registered"]["data"].get("report_id") or ""):
        problems.append(f"C 的 paths 报告没有登记号：{reading['registered']}")
    if not reading["dups"]["ok"]:
        problems.append(f"C 的结构重复读数没查成：{reading['dups']}")
    return problems


def _question_problems(reading: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    rows = reading["questions"]
    if len(rows) != 1:
        return [f"research_questions 应恰好一行，实得 {len(rows)}"]
    q = rows[0]
    origin = str(q.get("origin") or "")
    if not origin.startswith("C:gaps:"):
        problems.append(f"问题的 origin 没有指回 C 的 gaps 报告：{origin!r}")
    related = [str(x) for x in (q.get("related_concept_ids") or [])]
    if len(related) < 2:
        problems.append(f"问题没有带上缺口的那两个概念：{q!r}")
    if not set(related) <= set(reading["concepts"]):
        problems.append(f"问题的概念号不在 concepts 里：{related!r}")
    created = reading["ingest"]["data"]
    if isinstance(created, dict):
        created = created.get("created") or []
    if str(q.get("status")) == "open" and not created:
        problems.append(f"问题还停在 open 且没有缺口请求：{q!r}")
    return problems


def _duplicate_problems(reading: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    before = dict(reading["concepts"])
    decision = reading["merge_decision"]["data"]
    resolved = reading["merge_resolve"]["data"]
    if str(decision.get("verdict") or "") != "merge":
        problems.append(f"0000/0001 没有判 merge：{decision!r}")
    if resolved.get("applied") is not True:
        problems.append(f"0000/0001 的合并没有执行：{resolved!r}")
    merged_id = str(decision.get("merged_id") or "")
    survivor_id = str(decision.get("survivor_id") or "")
    if merged_id and survivor_id:
        stmt = next((dict(r) for r in reading["statements"]
                     if str(r.get("stmt_id")) == merged_id), {})
        if str(stmt.get("status")) != "superseded":
            problems.append(f"被合并命题没有 superseded 墓碑：{stmt!r}")
        if survivor_id not in str(stmt.get("quote_reason") or ""):
            problems.append(f"墓碑没有点名并入哪一条（{survivor_id}）：{stmt!r}")
        if not str((before.get(merged_id) or {}).get("merged_into") or ""):
            problems.append(f"老表视图没有墓碑读数：{before.get(merged_id)!r}")
    for rel in reading["relations"]:
        if merged_id and merged_id in {str(x) for x in (rel.get("concept_ids") or ())}:
            problems.append(f"关系 {rel.get('relation_id')} 仍指着被合并方")
    if not (resolved.get("rewritten_relation_ids")
            or resolved.get("rejected_relation_ids")):
        problems.append(f"合并没有动任何关系：{resolved!r}")
    # 反真空：异名那一对必须被判 reject、一个字节不写。
    reject = reading["reject_decision"]["data"]
    reject_resolved = reading["reject_resolve"]["data"]
    if str(reject.get("verdict") or "") != "reject":
        problems.append(f"0008/0009 名字不同却判了 {reject.get('verdict')!r}")
    if reject_resolved.get("applied") is not False:
        problems.append(f"reject 却执行了合并：{reject_resolved!r}")
    after = dict(reading["concepts"])
    if after != before:
        problems.append("reject 那一档动了概念表（连墓碑都不许落）")
    return problems


# ============================================================ ① 正控


def test_the_concept_graph_chain_runs_through_tool_dispatch(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：C 读数登记 → D 缺口立题 → B 结构重复裁决（merge 落墓碑、异名 reject）。"""
    got = _run(tmp_path, monkeypatch, lean="0")
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」")
    assert [e for e in reading["events"] if e.get("kind") == "llm_call"], (
        "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam")

    problems = (_chain_anchor_problems(reading) + _question_problems(reading)
                + _duplicate_problems(reading))
    assert problems == [], problems

    # 三段的动作都是经工具分发调到的（事件里逐条查得到）。
    for role, tool in (("C", "own.gaps"), ("C", "own.structural_duplicates"),
                       ("C", "analysis.register_report"), ("D", "own.ingest"),
                       ("D", "own.consider"),
                       ("B", "own.decide_structural_duplicate"),
                       ("B", "own.resolve_structural_duplicate")):
        assert _tool_result(reading["events"], role=role, tool=tool), f"{role} 没调过 {tool}"

    # ---- 钱：账本有行、无主为 0、悬空 0、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ 判据①：一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    print(f"[一行账] c9 lean={lean} 真调用={reading['calls']} "
          f"出网={len(got['wire'].bodies)} 账本行={reading['rows']} "
          f"duplicate={len(reading['duplicates'])} 未配对={len(reading['unpaired'])} "
          f"未认领={len(reading['unclaimed'])}")
    assert reading["calls"] == len(got["wire"].bodies), (
        f"真调用与出网次数不等：事件 {reading['calls']} / 出网 {len(got['wire'].bodies)}")
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
    print(f"[会话归口] c9 lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_the_concept_graph_chain_is_the_same_in_both_lean_modes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档：同一条链照跑，三段读数不变。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    reading = LS.lean_reading()
    assert reading.verdict == verdict, reading.to_dict()
    assert LS.is_hidden("L") is hidden, (lean, reading.to_dict())
    problems = (_chain_anchor_problems(_chain_reading(got))
                + _question_problems(_chain_reading(got))
                + _duplicate_problems(_chain_reading(got)))
    assert problems == [], problems
    from agentflow import schema as S

    roles = set(LS.visible_roles(S.ROLES))
    assert ("L" in roles) is (not hidden), sorted(roles)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
