# -*- coding: utf-8 -*-
"""彩排（真路径）C3 · 数值链：CLI 入口 → E 数值/穷举两次实验 → V 签 → B 收编。

## 这条链与真机差在哪（逐项）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条 |
| 派活 | `Conductor.summon`（`M→E`、`E→V`、`E→B` 都是 `ALLOWED_EDGES` 里的真边） | 同一条 |
| 实验 | `verify.run_experiment` → `AgentE.run_experiment`（真起子进程、真解析 `REPRO_RESULT`） | 同一条：盘上两份真脚本被真跑 |
| 形态闸 | 产出侧 `secretary.judge_proposition_form`（E 的缝） | 同一条：判定内容是预置回复，闸本体与调用点一个都没换 |
| 送审 | `verify.verify_proof` → `AgentV.verify_proof`（穷举会审；E 的过审门槛是 1） | 同一条 |
| 收编 | `own.ingest_manuscript(mode="register")` → `AgentB.ingest_manuscript` | 同一条 |
| 模型缝 | 真 `LlmSeam`（`_agent_seam_factory` / `for_role` / `for_secretary`） | 同一条：构造点一个都没替换 |
| 记账 | 真 `TokenMeter` → `usage_ledger` | 同一条 |
| 出网 | `modelgw.urllib_transport`（HTTP POST） | 只换这一处：回预置的 OpenAI 兼容 JSON |

旧 `test_rehearsal_c3_numeric_chain.py`（`CHAIN_ONLY` 里那份）直调三个 Agent 的公开方法，
并替换私有类 `_NumericProofFormGate._proposition_form_gate`；这一份两处都不换。

## 这条链覆盖什么（业主点名的 C3）

```text
M --summon--> E --verify.run_experiment(numeric)-->  experiments 一行 + reports/e-num-*.md
                --verify.run_experiment(exhaustive)--> experiments 一行 + reports/e-proof-*.md
                --summon--> V --verify.verify_proof--> 一次机械过审 clean（E 的 need=1）⇒ 签 + 稿上签块
                --summon--> B --own.ingest_manuscript--> statements 两行（conjecture / theorem）
```

判据读盘：`experiments` 两行（`numeric/cross_check` + `exhaustive_search/proof`）、
`reports/e-num-*` 有 `## 数值结果` 与 `## 命题`、`reports/e-proof-*` 的 `## 证明` 非空、
`out/vsigns/<正文 sha>.json` 在盘上、`verifications` 一行 `path_group=1`、`statements`
两行（数值档 `kind=conjecture` + `bits.numeric=verified`；穷举档 `kind=theorem` +
`proof_list=[1]`）、钱账逐分相等且无主 0。

## 2026-11-15 EC 修：E 的收工门不再把两族同号读成 ambiguous

C3 彩排此前抓到一条真产品缺陷：E 的收工门（`agent_loop._v_wait_gate_reading` →
`manuscriptclosing.signed_candidates`）按 `manuscript_id` 单独分桶，而 E 的两族稿各有
独立号段（`e-proof` / `e-num` 都从 `000000` 起）⇒ 同一工作区里同时有
`reports/e-num-000000.md` 与 `reports/e-proof-000000.md` 时，两份候选共用同一个稿号
⇒ `state="ambiguous_path"` ⇒ E 的 final 被受控拒（"这一份 e-proof 没有现行的 V 签
（ambiguous_path）"），E 的 task outcome 落 `no_result`。

修法：稿的身份改成 `(family, manuscript_id)`（候选带 `family`、分桶/门内索引都按
这一对键；F/B 同形，不给 E 打特例）。本文件现在把 E 的 final 那一格也钉上：
E 的 final 必须记成 `stop_reason="final"`、task outcome 必须是 `ok`，且拒信里
不许再出现 `ambiguous_path`。修复前的读数见 `temp/cc3/REPORT-CC3.md` §三；
修后的读数见 EC 路交付。

## 反真空（产出侧形态闸）

预置回复把形态判定说成"形态不合规" ⇒ 真 `run_experiment` 的产出侧闸必须受控拒
（`ExperimentError`）⇒ experiments 行 / e-proof 稿 / statements 一个字节都不落。
它证明这条链的绿来自"产出侧那道闸真的判过并放行"，不是恒真。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍。关档尤其重要：E 的动作面在关档下不含
`formal`（`COMPUTATIONAL_METHODS`），两者都不该改变本链的数值/穷举两段。
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
from agentflow import depsection as DS
from agentflow import leanscope as LS
from agentflow import manuscriptsubmission as MSUB
from agentflow import modelgw as MG
from agentflow import proofregistry as PR
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

SID = "cc3-c3"

NUM_CLAIM = "对 n <= 40 的偶数 n，n^2 + 2 都不是 3 的倍数。"
PROOF_CLAIM = "R(3,4) = 9（K_9 的二染色穷举没有单色 K_3 / K_4）。"

#: 普通数值脚本：只报观察结果，不声称证明（`cross_check`）。
NUM_SCRIPT = """
import json
bad = [n for n in range(2, 41, 2) if (n * n + 2) % 3 == 0]
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "counterexample": None, "negation_kind": "not_proved",
    "observations": {"checked": len(range(2, 41, 2)), "bad": bad},
}))
"""

#: 穷举脚本：数字与"全部 / 无一遗漏"都写在代码里（V 的会审逐项核）。
#: 脚本名刻意不叫 `enum.py` —— 脚本目录会进子进程的 `sys.path`，叫 `enum` 会遮住
#: 标准库的 `enum`，连 `import json` 都会失败（探针里踩过一次）。
EXH_SCRIPT = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 = 68719476736 个二染色；先按顶点置换取 canonical form "
                        "去掉对称性重数，再按 3-子集/4-子集的对称性剪枝；每个染色都落在枚举里，"
                        "无一遗漏；边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9}, "strategy": "canonical form + symmetry breaking",
}))
"""

FORM_OK = {"checked": True, "well_formed": True, "conditions": "n 为偶数",
           "conclusion": "n^2 + 2 不是 3 的倍数", "problems": [],
           "decision": "形态合规", "refused": "", "reason": "彩排：形态合规"}
FORM_BAD = {"checked": True, "well_formed": False, "submittable": False,
            "refused": "proposition_form_refused",
            "reason": "彩排：这一条没有写清条件与结论",
            "problems": ["没有写出「从什么条件导出什么结论」"],
            "decision": "形态不合规"}
CLEAN = {"verdict": "成立", "why": "彩排：没发现反例。", "findings": []}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _find(prompt: str, pattern: str) -> str:
    m = re.search(pattern, prompt)
    return m.group(0) if m else ""


def _roster_names(prompt: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'"roster_name":\s*"([A-Z]\d*)"', prompt)]


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self, *, form_ok: bool = True) -> None:
        self.form_ok = bool(form_ok)
        self.bodies: list[dict[str, str]] = []
        self._steps: dict[str, int] = {}
        self._stage: dict[str, dict[str, Any]] = {}
        self._done: dict[str, list[str]] = {}

    # ------------------------------------------------------------ 剧本
    def _retire_then(self, prompt: str, role: str, nxt: str) -> str:
        """名册里还有没销号的 → 销一个；都销完了 → 走 `nxt`（由调用方给的下一步）。"""
        done = self._done.setdefault(role, [])
        todo = [n for n in _roster_names(prompt) if n not in done]
        if todo:
            done.append(todo[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": todo[0], "reason": "交完了"}})
        return nxt

    def _step(self, role: str, prompt: str) -> str:
        index = self._steps.get(role, 0)
        self._steps[role] = index + 1
        numeric = _find(prompt, r"reports/e-num-\d+\.md")
        proof = _find(prompt, r"reports/e-proof-\d+\.md")
        if role == "M":
            if index == 0:
                return _json({"summon": {"role": "E", "task": "做数值与穷举两次实验"}})
            return self._retire_then(prompt, "M", _json({"final": "M 收工",
                                                         "evidence": []}))
        if role == "E":
            if not self.form_ok:
                # 反真空：只做穷举那一趟（它要过产出侧形态闸）。
                if index == 0:
                    return _json({"tool": "verify.run_experiment",
                                  "args": {"claim": PROOF_CLAIM, "claim_key": "ramsey34",
                                           "script_path": "code/enum_ramsey.py",
                                           "method": "exhaustive_search",
                                           "exhaustive": True,
                                           "certificate": {"kind": "enumeration_bound",
                                                           "detail": "n<=9 全枚举"},
                                           "search_bound": {"n": 9}}})
                return _json({"final": "E 收工", "evidence": []})
            stage = self._stage.setdefault("E", {"at": 0, "done": []})
            if stage["at"] == 0:
                stage["at"] = 1
                return _json({"tool": "verify.run_experiment",
                              "args": {"claim": NUM_CLAIM, "claim_key": "num-scan",
                                       "script_path": "code/num_scan.py",
                                       "method": "numeric"}})
            if stage["at"] == 1:
                stage["at"] = 2
                return _json({"tool": "verify.run_experiment",
                              "args": {"claim": PROOF_CLAIM, "claim_key": "ramsey34",
                                       "script_path": "code/enum_ramsey.py",
                                       "method": "exhaustive_search", "exhaustive": True,
                                       "certificate": {"kind": "enumeration_bound",
                                                       "detail": "n<=9 全枚举"},
                                       "search_bound": {"n": 9}}})
            if stage["at"] == 2:
                stage["at"] = 3
                return _json({"summon": {"role": "V", "task": f"审这份证明 {proof}",
                                          "params": {"proof_manuscript": proof}}})
            if stage["at"] == 3:
                todo = [n for n in _roster_names(prompt) if n not in stage["done"]]
                if todo:
                    stage["done"].append(todo[0])
                    return _json({"tool": "conductor.retire_child",
                                  "args": {"child_name": todo[0], "reason": "V 签完了"}})
                stage["at"] = 4
                stage["summoned_b"] = True
                return _json({"summon": {"role": "B",
                                          "task": f"收编两份稿 {numeric} 与 {proof}"}})
            todo = [n for n in _roster_names(prompt) if n not in stage["done"]]
            if todo:
                stage["done"].append(todo[0])
                return _json({"tool": "conductor.retire_child",
                              "args": {"child_name": todo[0], "reason": "B 收编完了"}})
            return _json({"final": "E 收工", "evidence": []})
        if role == "V":
            if index == 0:
                return _json({"tool": "verify.verify_proof",
                              "args": {"proof_manuscript": proof}})
            return _json({"final": "V 签完了", "evidence": []})
        if role == "B":
            seq = [
                _json({"tool": "own.ingest_manuscript",
                       "args": {"manuscript": numeric, "mode": "register"}}),
                _json({"tool": "own.ingest_manuscript",
                       "args": {"manuscript": proof, "mode": "register"}}),
                _json({"final": "B 收编完了", "evidence": []}),
            ]
            return seq[min(index, len(seq) - 1)]
        return _json({"final": f"{role} 收工", "evidence": []})

    def _reply(self, system: str, prompt: str) -> str:
        head = system.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            kind = m.group(1)
            if kind == "proposition_form":
                return _json(FORM_OK if self.form_ok else FORM_BAD)
            table = {
                "statement_aesthetic": {"decision": "T2", "reason": "彩排", "basis": ["夹具"]},
                "proposition_identity": {"decision": "different", "reason": "彩排",
                                         "basis": ["夹具"], "canonical_name": "另一条命题",
                                         "same_as": "", "route": "", "condition": "夹具",
                                         "conclusion": "夹具"},
                "statement_same": {"decision": "different", "reason": "彩排",
                                   "basis": ["夹具"], "canonical_name": "另一条命题",
                                   "same_as": "", "route": "", "condition": "夹具",
                                   "conclusion": "夹具"},
                "proof_kind": {"decision": "different", "same_path": 0, "reason": "彩排"},
                "v_reply_defect": {"decision": "没问题", "reason": "彩排", "basis": ["夹具"],
                                   "defect_step": None, "defect_kind": "",
                                   "report_gap": ""},
                "sign_issuance": {"decision": "签发", "reason": "彩排", "basis": ["夹具"]},
                "dispatch_fit": {"decision": "这一件能做", "reason": "彩排",
                                 "basis": ["夹具"]},
            }
            return _json(table.get(kind, {"decision": "可派", "reason": "彩排",
                                          "basis": ["夹具"]}))
        if head.startswith("你是「命题形态闸」"):
            return _json(FORM_OK if self.form_ok else FORM_BAD)
        if head.startswith("你是「命题台账检索」"):
            return _json({"keywords": ["偶数", "倍数"], "why": "彩排：这两个词能捞到同一条"})
        if "你是验证者（V）" in (head + prompt)[:400]:
            return _json(CLEAN)
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
    """真工作区 + 两个真脚本（E 会真起子进程跑它们）。"""
    st = Store(base / "ws")
    st.init()
    code = pathlib.Path(st.root) / "code"
    code.mkdir(parents=True, exist_ok=True)
    (code / "num_scan.py").write_text(NUM_SCRIPT, encoding="utf-8")
    (code / "enum_ramsey.py").write_text(EXH_SCRIPT, encoding="utf-8")
    return st


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0", form_ok: bool = True) -> dict[str, Any]:
    st = _workspace(base)
    wire = _Wire(form_ok=form_ok)
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root), "--sid", SID,
                "--subagents", "--task", "做数值与穷举两次实验并收编", "--max-steps", "10",
            ])
    except SystemExit as exc:
        rc = int(exc.code or 0)
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "form_ok": form_ok}


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


def _pending_rows(ws: pathlib.Path) -> list[dict]:
    base = VR.pending_dir(ws)
    if not base.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(base.glob("*.jsonl")):
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    return rows


def _chain_reading(got: dict[str, Any]) -> dict[str, Any]:
    ws, st = got["ws"], got["store"]
    events = _events(ws)
    experiments = _rows(st, "experiments")
    statements = _rows(st, "statements")
    reports = ws / "reports"
    return {
        "store": st, "ws": ws, "events": events,
        "experiments": experiments,
        "statements": statements,
        "tasks": _rows(st, "tasks"),
        "numeric": _tool_result(events, role="E", tool="verify.run_experiment", index=0),
        "exhaustive": _tool_result(events, role="E", tool="verify.run_experiment", index=1),
        "reviewed": _tool_result(events, role="V", tool="verify.verify_proof"),
        "filed_numeric": _tool_result(events, role="B", tool="own.ingest_manuscript", index=0),
        "filed_proof": _tool_result(events, role="B", tool="own.ingest_manuscript", index=1),
        "reports": sorted(p.name for p in reports.glob("*.md")) if reports.is_dir() else [],
        "numeric_rel": str((_tool_result(events, role="E", tool="verify.run_experiment",
                                         index=0).get("data") or {}).get(
                                             "numeric_manuscript") or ""),
        "proof_rel": str((_tool_result(events, role="E", tool="verify.run_experiment",
                                       index=1).get("data") or {}).get(
                                           "proof_manuscript") or ""),
        "pending": _pending_rows(ws),
        "unsigned_review": str((_tool_result(events, role="V", tool="verify.verify_proof")
                                .get("data") or {}).get("verdict") or ""),
        "form_rows": [dict(r) for r in _form_rows(ws)],
    }


def _form_rows(ws: pathlib.Path) -> list[dict]:
    path = ws / "out" / "secretary" / "proposition_form.jsonl"
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


# ============================================================ 判据本体


def _chain_problems(reading: dict[str, Any]) -> list[str]:
    """C3 的六条终态读数（空 = 通）。每条都读盘，不看回执里的 ok。"""
    problems: list[str] = []
    st: Store = reading["store"]
    root = pathlib.Path(st.root)

    # 1. experiments 两行：方法与档位对得上。
    experiments = reading["experiments"]
    if len(experiments) != 2:
        problems.append(f"experiments 应恰好 2 行，实得 {len(experiments)} 行")
    else:
        got = {(str(r.get("method") or ""), str(r.get("result") or ""),
                str(r.get("evidence_kind") or "")) for r in experiments}
        want = {("numeric", "supports", "cross_check"),
                ("exhaustive_search", "supports", "proof")}
        if got != want:
            problems.append(f"experiments 两行不是「数值 cross_check + 穷举 proof」：{got}")

    # 2. 普通数值手稿：数值结果与命题两节都在，且没有 `## 证明`。
    numeric_rel = str(reading["numeric_rel"])
    numeric_path = root / numeric_rel if numeric_rel else None
    numeric_text = (numeric_path.read_text(encoding="utf-8")
                    if numeric_path is not None and numeric_path.is_file() else "")
    if not numeric_rel.startswith("reports/e-num-"):
        problems.append(f"普通数值手稿不在 e-num 族：{numeric_rel!r}")
    if "## 命题" not in numeric_text or "## 数值结果" not in numeric_text:
        problems.append("普通数值手稿缺 `## 命题` 或 `## 数值结果` 那一节")
    if "## 证明" in numeric_text:
        problems.append("普通数值手稿不该有 `## 证明`（它不过 V）")

    # 3. 穷举手稿：`## 证明` 非空（V 的签就盖在它上面）。
    proof_rel = str(reading["proof_rel"])
    proof_path = root / proof_rel if proof_rel else None
    proof_text = (proof_path.read_text(encoding="utf-8")
                  if proof_path is not None and proof_path.is_file() else "")
    if not proof_rel.startswith("reports/e-proof-"):
        problems.append(f"穷举手稿不在 e-proof 族：{proof_rel!r}")
    body = DS.proof_body(proof_text).strip("\n") if proof_text else ""
    if not body:
        problems.append("穷举手稿的 `## 证明` 是空的（没有可签的正文）")

    # 4. 签：信封 + 稿上签块 + 一行台账都是第 1 条路径（E 的过审门槛是 1）。
    sha = PR.proof_sha(body) if body else ""
    if sha:
        if not VS.sign_path(root, sha).is_file():
            problems.append(f"签信封不在盘上：out/vsigns/{sha}.json")
        standing = VS.manuscript_sign_standing(proof_text, proof_sha=sha)
        if str(standing.get("state") or "") != "signed":
            problems.append(f"稿上的签块不是 signed：{standing.get('state')!r} "
                            f"({standing.get('why') or standing.get('reason') or ''})")
        groups = [int(r.get("path_group") or 0) for r in reading["pending"]]
        if len(groups) != int(VR.EXHAUSTION_SIGN_STREAK_NEED):
            problems.append(
                f"pending 台账应恰好 {VR.EXHAUSTION_SIGN_STREAK_NEED} 行"
                f"（E 的过审门槛是 1，业主 2026-11-17），实得 {len(groups)} 行")
        if set(groups) != {1}:
            problems.append(f"pending 的 path_group 不是 [1]：{groups}")

    # 5. 数值通道：conjecture + 数值位 verified + 证明栏空着。
    statements = reading["statements"]
    numeric_rows = [r for r in statements if str(r.get("kind") or "") == "conjecture"]
    proof_rows = [r for r in statements if str(r.get("kind") or "") == "theorem"]
    if len(numeric_rows) != 1:
        problems.append(f"数值通道应有 1 行 conjecture，实得 {len(numeric_rows)} 行")
    else:
        row = numeric_rows[0]
        if str(row.get("evidence_kind") or "") != "cross_check":
            problems.append(f"数值通道的 evidence_kind 不是 cross_check："
                            f"{row.get('evidence_kind')!r}")
        if str(row.get("proof_text") or "").strip():
            problems.append("普通数值档的 proof_text 该留空（业主口径），实得非空")
        if dict(row.get("bits") or {}).get("numeric") != "verified":
            problems.append(f"数值通道的 bits.numeric 不是 verified："
                            f"{dict(row.get('bits') or {}).get('numeric')!r}")

    # 6. 穷举那一条：theorem / proof / 第 1 条路径。
    if len(proof_rows) != 1:
        problems.append(f"穷举档应有 1 行 theorem，实得 {len(proof_rows)} 行")
    else:
        row = proof_rows[0]
        if str(row.get("evidence_kind") or "") != "proof":
            problems.append(f"穷举那一条的 evidence_kind 不是 proof："
                            f"{row.get('evidence_kind')!r}")
        if PR.proof_sha(str(row.get("proof_text") or "")) != sha:
            problems.append("命题行上的正文与稿里 `## 证明` 不是同一份")
        nos = [int(no) for no, _t in VR.proof_list(row)]
        if nos != [1]:
            problems.append(f"proof_list 不是 [1]：{nos}")
        path = MSUB.path_reading(st, root, statement_id=str(row.get("stmt_id") or ""))
        if path.get("checked") is not True or int(path.get("count") or 0) != 1:
            problems.append(f"路径读数不是 1 条：{path}")
        elif int((path.get("paths") or [{}])[0].get("path_group") or 0) != 1:
            problems.append(f"第 1 条路径的 path_group 不是 1：{path.get('paths')}")

    # 7. 回执也要对得上（交叉核对，不作为主判据）。
    if not reading["reviewed"].get("ok"):
        problems.append(f"V 的 verify_proof 回执不是 ok：{reading['reviewed'].get('error')!r}")
    return problems


# ============================================================ ① 正控：链走通


def test_the_numeric_chain_runs_from_the_cli_with_only_the_wire_replaced(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：E 两次实验 → V 签穷举稿 → B 收编两条，六条终态读数全对（Lean 关）。"""
    got = _run(tmp_path, monkeypatch, lean="0")
    reading = _chain_reading(got)

    # ---- 入口与"只换了网线"
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」")
    live = [e for e in reading["events"] if e.get("kind") == "llm_call"]
    assert live, "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam"

    # ---- 六条盘上读数
    problems = _chain_problems(reading)
    assert problems == [], problems
    # 两次实验各落一份稿；E 的形态台账里有产出侧那一笔（真闸判过）。
    assert "e-num-000000.md" in reading["reports"], reading["reports"]
    assert "e-proof-000000.md" in reading["reports"], reading["reports"]
    assert [r for r in reading["form_rows"] if str(r.get("role")) == "E"], reading["form_rows"]
    # E 的过审门槛是 1（业主 2026-11-17：实验侧报告不承重，承重的是程序）：
    # 一次机械过审就发签 —— 这一次送审里不该出现第 2、3 轮，也不是三次独立送审。
    assert len(reading["reviewed"]["data"].get("review_passes") or []) == int(
        VR.EXHAUSTION_SIGN_STREAK_NEED), reading["reviewed"]["data"].get("review_passes")
    assert str(reading["reviewed"]["data"].get("kind") or "") == "proof_unregistered_signed", (
        reading["reviewed"]["data"].get("kind"))

    # ---- E 的 final 必须过收工门（2026-11-15 EC）：两族同号不再读成 ambiguous。
    # `e-num-000000` 与 `e-proof-000000` 是两份稿；门若按单号分桶，E 的 final 会以
    # `final_refused` 收尾、task outcome 落 `no_result`（修前实测，见 CC3 报告 §三）。
    e_main = [t for t in reading["tasks"]
              if str(t.get("role")) == "E" and str(t.get("action") or "") == ""
              and str(t.get("called_by") or "") == "M"]
    assert len(e_main) == 1, e_main
    assert str(e_main[0].get("outcome") or "") == "ok", e_main[0]
    e_ends = [e for e in reading["events"]
              if e.get("kind") == "agent_run_end" and str(e.get("role")) == "E"]
    assert e_ends, "会话里没有 E 的 agent_run_end"
    finals = [e for e in e_ends if str(e.get("stop_reason") or "") == "final"]
    assert finals, [e.get("stop_reason") for e in e_ends]
    assert str(finals[-1].get("final") or "") == "E 收工", finals[-1].get("final")
    notes = " ".join(str(x) for e in e_ends for x in (e.get("notes") or []))
    assert "ambiguous_path" not in notes, notes[-800:]
    # E 收工前已经有一枚 `mss:` 记号指到 e-proof（签触发那一条路），不因同号串到 e-num。
    # 2026-11-16 EC3 起记号头写的是 `mss:<族>-<号>`（`agent_f/submission.py::submission_token`）：
    # e-proof / e-num 同号时正是族那一格把两份分开 ⇒ 这里钉「带族头 + 载体路径」。
    # 老形 `mss:<号>` 只在读侧兼容，不再是新写的形态 —— 判据跟着新形态走，不是放宽。
    heads = [str(a) for a in (e_main[0].get("artifacts") or [])]
    assert any(a.startswith("mss:e-proof-000000#")
               and "path=reports/e-proof-000000.md" in a
               for a in heads), heads

    # ---- 钱：账本有行、无主为 0、悬空 0、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空：产出侧形态闸坏


def test_a_broken_producer_form_gate_turns_the_chain_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：模型说"形态不合规" ⇒ E 的产出侧闸必须受控拒，链上一个字节都不落。

    闸不换：真 `_NumericProofFormGate` 调真秘书，只是它的判定内容是预置回复
    （这是"模型说了一句什么"那一层）。若这一条不红，第 3/6 条判据就只是"跑过 E
    就算数"，而不是"产出侧那道闸真的判过并放行"。
    """
    got = _run(tmp_path, monkeypatch, lean="0", form_ok=False)
    st, ws = got["store"], got["ws"]
    assert got["wire"].bodies, "反真空没真的问过模型"
    assert _rows(st, "experiments") == [], "形态闸判不合规，却落了 experiments 行"
    reports = ws / "reports"
    leftovers = sorted(p.name for p in reports.glob("e-proof-*.md")) if reports.is_dir() else []
    assert leftovers == [], f"形态闸判不合规，却落了 e-proof 稿：{leftovers}"
    assert _rows(st, "statements") == [], "形态闸判不合规，却收了命题"
    # 那一笔受控拒要如实回给模型（不是静默失败）：工具回执 ok=False，且拒信里带受控码。
    tool = _tool_result(_events(ws), role="E", tool="verify.run_experiment")
    assert tool["ok"] is False, tool
    assert ("proposition_form" in tool["error"] or "形态" in tool["error"]
            or "没有落库" in tool["error"]), tool["error"]
    # 形态台账要记下这一笔（`role=E` 的"没判成/判不过"读数）。
    assert [r for r in _form_rows(ws) if str(r.get("role")) == "E"], _form_rows(ws)


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
    """Lean 开/关两档：同一条链照跑，六条盘上读数不变；关档下名册里没有 L。"""
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
