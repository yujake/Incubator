# -*- coding: utf-8 -*-
"""彩排（真路径）D 线 · 只递指针：CLI 入口 → M→D→F（F 交稿并拿 V 签）→ D 写携带单 → B 按指针收录。

## 这条链钉的那一段（业主口径逐字见旧彩排的 docstring）

> 「D 对命题台账只有只读权限，D 向 B 提交要登记的命题时都是有证明或数值实验的
>   （即 E 和 F 的成果）…B 侧做好适配（应该在手稿里找命题和数值实验程序，不录入其它内容）。」

真机上它是这样发生的（本文件走的就是这条）：

```text
F --attack.step(product)--> reports/f-proof-<稿号>.md（洗过的三节稿）
F --summon V--> V 三转 clean ⇒ secretary:F 把签块落回稿；F 收工时框架写 `mss:<稿号>` 提交记号
D --own.write_report--> 报告里渲染「## 携带的证明手稿」一节（| mss:<稿号> | <路径> | <文件 sha> |）
      ⇒ 同一笔里 `_deliver_carried_to_b` 调 B 的登记口（B 是 D 构造期绑定的同一实例）
      ⇒ 这一笔发生在 D 的 `calling_as` 上下文里：B 的秘书判形态 / 档位 / 同一性，全在 D 那一步里
B --按稿收录--> statements 一行（statement_full 逐字等于稿的 `## 命题`）＋ 路径号
```

## 与真机差在哪

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 / 执行体 / 缝 / 记账 / 出网 | CLI → `_exec_role` → `LlmBackend` → `AgentLoop.run`；真 `LlmSeam` / `TokenMeter` / `urllib_transport` | 同一条；只换出网那一处 |
| F 拿签 | F 的循环里 `attack.step` → `summon V` → `secretary:F` 落签块 | 同一条（与 C4 同一套剧本，只是第一版就签住） |
| D 的携带 | `own.write_report`（D 的动作）→ `_carried_manuscripts` 读 F 的 `mss:` 提交记号 → 渲染 + 代递 | 同一条：携带单是产品自己渲染的那一节 |
| B 的收录 | B 的登记口（`register_statement`）在同一笔里被调；秘书判档 / 同一性 | 同一条：B 的秘书模型调用发生在 D 的 `calling_as` 里 |

旧版（改写前登记在 `CHAIN_ONLY` 里）直调
`depsection.read_carried_manuscript` + `AgentB.ingest_manuscript`，缝是自造
`_Seam(ask_json)`，还打桩 `conftest.b_form_gate_ok` 换掉秘书的形态判定；这一份三处都不换。

## 终态读数（全读盘）

`statements` 一行：`statement_full` 逐字等于稿的 `## 命题`（不是 D 抄来的）、
`manuscript_id` 等于 F 的稿号、`kind="theorem"`、`bits.proof` / `bits.reviewed` 都翻；
`manuscriptpaths.path_reading` 的 `paths[0].manuscript` 是这份稿（路径号由 B 的收录
事务分配，D 与稿都没写）；D 的报告里有「## 携带的证明手稿」一节（点名 `mss:<稿号>`
与文件 sha）且没有抄 `## 命题` 的正文，还有那一笔「B 收下 1 条」；B 的秘书台账
（`out/secretary/B.jsonl` / `nontriviality.jsonl` / `statement_same.jsonl`）各有一行；
钱账干净。

## 反真空（同一条链、只把 V 的判决换成"判有毛病"）

V 判错 ⇒ 稿拿不到签 ⇒ B 的收录闸受控拒：`statements` 零新增、D 的报告写
「B 收下 0 条」，V 的打回留在 `pending` 台账（`defect_step=2`），F 的 final 被
收工门拒。三态要分清：D 确实把那份稿列上了携带单（F 交稿时就登记了条目，
与签无关）、B 确实被叫到了（秘书判过档 / 同一性）—— 红的是"稿没有现行签"那一格。
它证明正控里那一行命题是"稿有签 + B 判过"之后才落的，不是收录口恒放行。

（旧彩排的另一条反真空「稿缺 `## 命题` ⇒ B 受控拒」在真机主路上也走不到 B：
D 那一侧预读就会把它记成"递不出去"、不调 B。两层闸的先后在报告里点名。）

## 与旧彩排的一处刻意收窄（说清楚，不掩盖）

旧彩排的依赖三列（引用 / 命题号 / 步）钉的是一条夹具预置的旧命题被引用之后
落进 `dependencies` 的那一行。真机主路上这一步走不通：V 会审这份稿，而它的引用闸
要求「被引的那条命题本身也有一份盘上手稿」（`reports/f-proof-<号>.md`），否则
`citation_level_unreadable` ⇒ 整份稿判「有毛病」、签不下来。旧夹具那条预置命题
没有手稿，所以它只适合"直调 B"那一条低一层的路。要让三列在真机上成立，得先有
第二份真拿签的手稿（E/F 的另一条交付），那是另一条链；本文件因此把这一格
缩成"空表声明自足"，并在报告里点名这件事。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：这条链不碰 `formal.*`；关档下名册里没有 L。
"""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import re
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

import pytest

import rehearsal_contract as RC

from agentflow import cli
from agentflow import depsection as DS
from agentflow import leanscope as LS
from agentflow import manuscriptpaths as MP
from agentflow import modelgw as MG
from agentflow import proofregistry as PR
from agentflow.store import Store

SID = "cc4-d-pointer"
PROBLEM = "设 n 是偶数；则 n^2 是 4 的倍数。"
STEP1 = "设 n = 2k（k 是整数）。"
STEP2 = "则 n^2 = 4k^2，被 4 整除。"
STEP3 = "所以 n^2 是 4 的倍数。"
BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
SUBGOALS = [{"sid": "s1", "text": PROBLEM, "owner": "F", "kind": "theorem",
            "testable": "写出两步论证"}]
DEFECT = "第 2 步的引理没有在册"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _my_task(prompt: str) -> str:
    m = re.search(r"这一趟派给你的活是 —— .+", prompt)
    return m.group(0) if m else ""


def _plan_id(prompt: str) -> str:
    hits = re.findall(r'"data\.plan_id":\s*"(\d{6})"', prompt)
    return hits[-1] if hits else ""


def _manuscript(prompt: str) -> str:
    hits = re.findall(r"reports/f-proof-\d{6}\.md", prompt)
    return hits[-1] if hits else ""


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self, *, fault: bool = False) -> None:
        self.fault = bool(fault)
        self.bodies: list[dict[str, str]] = []
        self.steps: dict[str, int] = {}
        self.retired: list[str] = []
        self.vreview = 0
        self.vdefect = 0

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
            return _json({"summon": {"role": "D",
                                     "task": "把这一条证下来、拿 V 的签、再把稿交给 B"}})
        return self._retire_then(prompt, _json({"final": "M 收工", "evidence": []}))

    def _d(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"summon": {"role": "F",
                                     "task": f"证明这一条并送 V 签：{PROBLEM}"}})
        if index == 1:
            return _json({"tool": "own.write_report", "args": {}})
        return self._retire_then(prompt, _json({"final": "D 收工", "evidence": []}))

    def _f(self, index: int, prompt: str) -> str:
        pid = _plan_id(prompt)
        ms = _manuscript(prompt) or "reports/f-proof-000000.md"
        if index == 0:
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": PROBLEM, "problem_key": "peven",
                                   "budget": BUDGET, "subgoals": SUBGOALS}})
        if index == 1:
            return _json({"tool": "attack.step", "args": {
                "plan_id": pid,
                "product": {"kind": "proof", "label": "v1", "proposition": PROBLEM,
                            "steps": [
                                {"text": STEP1, "assumption": True},
                                {"text": STEP2, "assumption": True},
                                {"text": STEP3, "assumption": True}]}}})
        if index == 2:
            return _json({"summon": {"role": "V", "task": f"审这一份证明稿：{ms}",
                                     "params": {"proof_manuscript": ms}}})
        return _json({"final": "F 收工", "evidence": []})

    def _v(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"tool": "verify.verify_proof",
                          "args": {"proof_manuscript": _manuscript(prompt) or None}})
        if self.fault:
            return _json({"final": f"V 判有毛病：{DEFECT}，请补上后再送"})
        return _json({"final": "V 签在稿上（连续 3/3 成立）"})

    # ------------------------------------------------------------ 回复分派
    def _form_ok(self) -> str:
        return _json({"checked": True, "well_formed": True,
                      "conditions": "n 是偶数", "conclusion": "n^2 是 4 的倍数",
                      "problems": [], "decision": "形态合规", "refused": "",
                      "reason": "彩排：形态合规"})

    def reply(self, *, system: str, prompt: str) -> str:
        head = system.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            kind = m.group(1)
            if kind == "proposition_form":
                return self._form_ok()
            if kind == "statement_aesthetic":
                return _json({"checked": True, "decision": "T2",
                              "nontriviality": 2, "path_group": 1,
                              "reason": "彩排：T2", "basis": ["彩排"],
                              "label": "T2", "applicable": True})
            if kind in ("proposition_identity", "statement_same"):
                return _json({"checked": True, "decision": "different",
                              "canonical_name": "n^2 是 4 的倍数",
                              "same_as": "", "route": "", "condition": "n 是偶数",
                              "conclusion": "n^2 是 4 的倍数",
                              "reason": "彩排：在册没有逐字同一条", "basis": ["彩排"]})
            if kind == "statement_keywords":
                return _json({"checked": True, "keywords": ["偶数", "平方", "整除"],
                              "why": "彩排：这几个词能捞到同一条"})
            if kind == "v_reply_defect":
                self.vdefect += 1
                if self.fault and self.vdefect == 2:
                    return _json({"checked": True, "decision": "有缺陷要指出",
                                  "reason": DEFECT + "。", "basis": ["彩排"],
                                  "defect_step": 2, "defect_kind": "math",
                                  "report_gap": ""})
                return _json({"checked": True, "decision": "没问题",
                              "reason": "没发现问题", "basis": ["彩排"],
                              "defect_step": None, "defect_kind": "",
                              "report_gap": ""})
            if kind == "sign_issuance":
                return _json({"decision": "签发", "reason": "三转干净", "basis": ["彩排"]})
            if kind == "dispatch_fit":
                return _json({"decision": "是一个方向", "reason": "只写了一个方向",
                              "basis": ["彩排"]})
            return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["彩排"]})
        if "命题形态闸" in head:
            return self._form_ok()
        if "你是「命题台账检索」" in head:
            return _json({"keywords": ["偶数", "平方", "整除"],
                          "why": "彩排：这几个词能捞到同一条"})
        if "你是验证者（V）" in (head + prompt)[:400]:
            self.vreview += 1
            if self.fault and self.vreview == 2:
                return _json({"verdict": "成立", "why": DEFECT + "。", "findings": []})
            return _json({"verdict": "成立",
                          "why": "试了几种反例构造都失败，未发现问题。", "findings": []})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            role = m.group(1)
            index = self.steps.get(role, 0)
            self.steps[role] = index + 1
            if role == "M":
                return self._m(index, prompt)
            if role == "D":
                return self._d(index, prompt)
            if role == "F":
                return self._f(index, prompt)
            if role == "V":
                return self._v(index, prompt)
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


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0", fault: bool = False) -> dict[str, Any]:
    base.mkdir(parents=True, exist_ok=True)
    st = Store(base / "ws")
    st.init()
    wire = _Wire(fault=fault)
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root), "--sid", SID,
                "--subagents", "--task", "把一条证下来并交给 B", "--max-steps", "10",
            ])
    except SystemExit as exc:
        rc = int(exc.code or 0)
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "fault": fault}


def _events(ws: pathlib.Path) -> list[dict]:
    got: list[dict] = []
    for path in sorted((ws / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                got.append(json.loads(line))
            except ValueError:
                continue
    return got


def _jsonl(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def _report_text(ws: pathlib.Path) -> tuple[pathlib.Path, str]:
    """D 写出来的那份研究报告（排除 F 的攻坚台账与各类证明稿）。"""
    skip = ("f-proof-", "b-proof-", "e-proof-", "attack-")
    hits = sorted(p for p in (ws / "reports").glob("*.md")
                  if not p.name.startswith(skip))
    if not hits:
        return ws / "reports" / "missing.md", ""
    return hits[-1], hits[-1].read_text(encoding="utf-8")


def _chain_reading(got: dict[str, Any]) -> dict[str, Any]:
    ws, st = got["ws"], got["store"]
    report_path, report = _report_text(ws)
    events = _events(ws)
    return {
        "store": st, "ws": ws, "report_path": report_path, "report": report,
        "events": events,
        "carried": DS.carried_manuscripts(report) if report else {},
        "statements": [dict(r) for r in st.rows("statements")],
        "deps": [dict(r) for r in st.rows("dependencies")],
        "tasks": [dict(r) for r in st.rows("tasks")],
        "b_decisions": _jsonl(ws / "out" / "secretary" / "B.jsonl"),
        "tiers": _jsonl(ws / "out" / "secretary" / "nontriviality.jsonl"),
        "write": _write_result(events),
    }


def _write_result(events: list[dict]) -> dict:
    for e in events:
        if e.get("kind") != "agent_step" or e.get("role") != "D":
            continue
        if str((e.get("payload") or {}).get("name") or "") != "own.write_report":
            continue
        got = e.get("result") or {}
        return {"ok": bool(got.get("ok")), "error": str(got.get("error") or "")}
    return {"ok": False, "error": "D 没有调过 own.write_report"}


def _chain_problems(reading: dict[str, Any]) -> list[str]:
    """D→B 这一段的终态读数（空 = 通）。"""
    problems: list[str] = []
    ws: pathlib.Path = reading["ws"]
    report = reading["report"]
    carried = dict(reading["carried"] or {})
    rows = [dict(r) for r in (carried.get("rows") or [])]
    mss = [r for r in rows if str(r.get("manuscript_id") or "")]
    if len(mss) != 1:
        return [f"D 报告的携带单应恰好 1 条 F 稿，实得 {len(mss)}：{rows}"]
    row = mss[0]
    mid = str(row.get("manuscript_id") or "")
    rel = str(row.get("path") or "")
    if not rel.startswith("reports/f-proof-"):
        problems.append(f"携带单上的路径不是 F 稿：{rel!r}")
    blob = (ws / rel).read_bytes() if rel and (ws / rel).is_file() else b""
    if blob and hashlib.sha256(blob).hexdigest() != str(row.get("sha256") or ""):
        problems.append("携带单上的文件 sha 与盘上那份不一致")
    # 指针：D 只递地址 —— 报告里没有命题正文，只有携带单那一行。
    if "## 携带的证明手稿" not in report:
        problems.append("D 的报告里没有「## 携带的证明手稿」那一节")
    if PROBLEM in report:
        problems.append("D 的报告里抄了 `## 命题` 的正文（应当只递指针）")
    # B 那一侧：statement_full 是稿里的命题（不是 D 抄过来的）。
    text = (ws / rel).read_text(encoding="utf-8") if blob else ""
    proposition = "\n".join(line for _no, line in
                            DS.section_lines(text, "## 命题")[0]).strip() if text else ""
    if proposition != PROBLEM:
        problems.append(f"稿里的 `## 命题` 不是夹具那句：{proposition!r}")
    rows_stmt = [dict(r) for r in reading["statements"]]
    if len(rows_stmt) != 1:
        return problems + [f"statements 应恰好一行，实得 {len(rows_stmt)}："
                           f"{[r.get('stmt_id') for r in rows_stmt]}"]
    one = rows_stmt[0]
    sid = str(one.get("stmt_id") or "")
    if str(one.get("statement_full") or "") != proposition:
        problems.append(f"落库命题不是稿里的那一句：{one.get('statement_full')!r}")
    if str(one.get("manuscript_id") or "") != mid:
        problems.append(f"行上的稿号不是 {mid}：{one.get('manuscript_id')!r}")
    if str(one.get("kind") or "") != "theorem":
        problems.append(f"kind 不是 theorem：{one.get('kind')!r}")
    # 证据档：F 的稿在"按稿收录"这一档里 `evidence_kind` 的缺省是 `heuristic`
    # （`register_statement.py:6573`：f-proof 族的声明档；E 的 e-proof 才是 proof）。
    # 真正"这份证明算不算证明"的读数是 `bits`：proof / reviewed 两位都翻了。
    if str(one.get("evidence_kind") or "") != "heuristic":
        problems.append(f"f-proof 族的缺省档不是 heuristic：{one.get('evidence_kind')!r}")
    bits = dict(one.get("bits") or {})
    if bits.get("proof") is not True:
        problems.append(f"bits.proof 没有翻（V 的签没认领）：{bits!r}")
    if bits.get("reviewed") is not True:
        problems.append(f"bits.reviewed 没有翻：{bits!r}")
    # 依赖：这份稿声明自足（`## 依赖` 是空表）⇒ 收录不写依赖行；
    # 这本身是一条读数（"没依赖"与"依赖没写进去"分得开）。
    deps = [r for r in reading["deps"]
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"]
    if deps:
        problems.append(f"稿声明自足却落了依赖行：{deps}")
    # 路径号：载体是这份 F 稿（号由 B 的收录事务分配，D 与稿都没写）。
    path = MP.path_reading(reading["store"], ws, statement_id=sid)
    if int(path.get("count") or 0) != 1:
        problems.append(f"path_reading.count 不是 1：{path.get('count')!r}")
    else:
        by_group = {int(p.get("path_group") or 0): dict(p)
                    for p in (path.get("paths") or [])}
        if str((by_group.get(1) or {}).get("manuscript") or "") != rel:
            problems.append(f"第 1 条路径的载体不是 {rel}：{by_group.get(1)!r}")
    # D 的报告里那一笔"交给 B"的回执：B 收下 1 条（D 自己渲染的读数，交叉核对）。
    if "B 收下 1 条" not in report:
        problems.append("D 的报告里没有「B 收下 1 条」那一笔")
    write = dict(reading["write"])
    if not write.get("ok"):
        problems.append(f"D 的 write_report 回执不是 ok：{write.get('error')!r}")
    return problems


# ============================================================ ① 正控


def test_d_hands_b_only_a_pointer_and_bs_secretary_judges_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：D 写携带单 → 同一笔里 B 按指针收录（B 的秘书在 D 的 calling_as 里判）。"""
    got = _run(tmp_path, monkeypatch, lean="0")
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」")
    assert [e for e in reading["events"] if e.get("kind") == "llm_call"], (
        "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam")

    problems = _chain_problems(reading)
    assert problems == [], problems

    # ---- B 的秘书真的被问过（D 的工具调用里那一笔，不在 B 自己的循环里）。
    assert reading["b_decisions"], reading["b_decisions"]
    assert reading["tiers"], reading["tiers"]

    # ---- 钱：账本有行、无主为 0、悬空 0、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["usage_ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空


def test_an_unsigned_manuscript_is_refused_by_the_ingest_gate(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：V 判有毛病 ⇒ 携带单上那份稿没签 ⇒ B 的收录闸受控拒、零新增。

    同一条链、同一份夹具，只把 V 的第二转判成 fault。读数三态分得清：

    - D 确实把那份稿列上了携带单（F 在交稿时就登记了这条目，与签无关）——
      所以「携带」不是这一格的闸；
    - B 被叫到了（它的秘书在同一笔里判过档 / 同一性），这一笔落 0 条；
    - `statements` 零新增、报告里写「B 收下 0 条」；V 的打回留在 `pending` 台账
      （`defect_step=2`），F 的 final 被收工门拒。

    它证明正控里那一行命题是"稿有现行签 + B 判过"之后才落的，不是收录口恒放行。
    """
    got = _run(tmp_path, monkeypatch, lean="0", fault=True)
    reading = _chain_reading(got)
    assert got["wire"].bodies, "反真空没真的问过模型"
    carried = dict(reading["carried"] or {})
    rows = [r for r in (carried.get("rows") or [])
            if str(r.get("manuscript_id") or "")]
    assert len(rows) == 1, carried
    assert reading["statements"] == [], f"未签的稿竟然收了命题：{reading['statements']}"
    assert reading["b_decisions"], "B 的秘书一次都没被叫到（这一格没有对象）"
    assert "B 收下 0 条" in reading["report"], reading["report"][-600:]
    pending = _jsonl_dir(reading["ws"] / "verifications" / "pending")
    assert [r for r in pending if int(r.get("defect_step") or 0) == 2], pending
    ends = [e for e in reading["events"] if e.get("kind") == "agent_run_end"
            and str(e.get("role") or "") == "F"]
    assert [e for e in ends if str(e.get("stop_reason") or "") == "final_refused"], (
        f"F 的 final 没被收工门拒：{[e.get('stop_reason') for e in ends]}")


def _jsonl_dir(path: pathlib.Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_dir():
        return rows
    for one in sorted(path.glob("*.jsonl")):
        rows += _jsonl(one)
    return rows


# ============================================================ 判据①：一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    print(f"[一行账] d-pointer lean={lean} 真调用={reading['calls']} "
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
    print(f"[会话归口] d-pointer lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_the_pointer_line_is_the_same_in_both_lean_modes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档：同一条链照跑，携带单 / 收录 / 路径号不变。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    reading = LS.lean_reading()
    assert reading.verdict == verdict, reading.to_dict()
    assert LS.is_hidden("L") is hidden, (lean, reading.to_dict())
    problems = _chain_problems(_chain_reading(got))
    assert problems == [], problems
    from agentflow import schema as S

    roles = set(LS.visible_roles(S.ROLES))
    assert ("L" in roles) is (not hidden), sorted(roles)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
