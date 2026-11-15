# -*- coding: utf-8 -*-
"""彩排（真路径）C4 · 打回修订环：CLI 入口 → M→D→F→V，V 点名缺陷 → F 定点重写 → 再送审 → 签。

## 这条链与真机差在哪（逐项）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条 |
| 派活 | `Conductor.summon`（`M→D`、`D→F`、`F→V` 都是 `ALLEGED_EDGES` 里的真边） | 同一条 |
| F 交稿 | `attack.step` + `product` → `reports/f-proof-<稿号>.md` | 同一条：稿是产品自己落的 |
| 送审 / 打回 | `verify.verify_proof` → `AgentV.verify_proof`（连判三转）＋ 每转由 `secretary:V` 判 `clean/fault` | 同一条：判词内容预置，判据与写口是产品原物 |
| 缺陷回到 F 下一步 | V 的结论落 `verifications/pending/<sha>.jsonl`（`defect_step` + `secretary_judge.axis=fault`），V 收工时把意见作为 notice 交给父 F；F 下一步在开场/步内读到它 | 同一条：F 的下一拍 prompt 里逐字带着那句意见（本文件用 wire 记下 prompt 断言） |
| 重写 | F 再 `attack.step`（`proof_mode=rewritten`、稿号不变） | 同一条 |
| 再送审 / 签 | 三转 clean ⇒ `secretary:F` 把签块落回稿、`out/vsigns/<新 sha>.json` | 同一条 |
| 收工门 | `_v_wait_gate_reading`（F 的稿有现行签才放行 final） | 同一条：F 的 final 过了门，M 的 final 过了整树销号门 |
| 模型缝 / 记账 / 出网 | 真 `LlmSeam` / 真 `TokenMeter` / `modelgw.urllib_transport` | 只换出网那一处 |

旧版（改写前登记在 `CHAIN_ONLY` 里）直调
`AgentF.step` 与私有 `AgentF._hand_proof`、`AgentV.verify_proof`，缝是自造
`_Seam(ask_json)` + `_Review(ask)`；这一份一处都不换。

## 这一条链钉的四段（每段都能单独读盘）

1. v1 被判「有缺陷要指出」：`verifications/pending/<sha1>.jsonl` 一行，
   `defect_step=2`、`secretary_judge.axis="fault"`、`why` 里留着 V 指出的那句话；
   v1 一枚签都没有（`out/vsigns/<sha1>.json` 不存在、稿上没有签块）。
2. 那句意见回到 F 的下一步：wire 记下 F 每一拍的 prompt，重写那一拍里逐字带着
   V 的意见（`框架执行结果` 那一行 = 上一拍 summon 回来的 V 结论）。
3. 只改第 2 步：重写后正文 sha 变、行数不变、只有第 2 行不同；
   `attack.step` 的 `proof_mode="rewritten"`（稿号仍是同一份）。
4. 再送审三转 clean ⇒ 签：`pending/<sha2>.jsonl` 三行、稿上签块
   `连续=3/3`、`签名者=secretary:F`、`out/vsigns/<sha2>.json` 在盘上、签里的
   `artifact_sha` 就是新正文 sha；F 的 final 过门。

## 反真空

`fault=False` 那一趟（同一个 wire、同一份夹具，只把 `secretary:V` 的判定换成
恒 `clean`）：第一份稿当场三转签住 —— 一次重写都没有（`proof_mode` 只有
`registered`）、v1 的 sha 上三行 pending、签文件在盘上、final 直接过门。
它证明主链的"先打回、再重写、再签"不是恒真：把那一格判成 clean，打回与重写
就一起消失（旧彩排的 `test_..._a` 把这条反真空写成"判成 clean ⇒ 这一条红"）。

## 2026-11-16 已修：未在册支的「秘书洗稿 → 转达 F」（CC4 缺陷 2）

改前：`AgentV._wash_v_reply` 只在已在册那一档（`record_verification`）里被调用；
F 的稿在收录前是未在册的，走 `record_pending_sign` —— 那两处调用都不接
`washed_relay`。于是这条主路上：「秘书洗稿 → 转达给 F」这一步并不发生：
F 拿到的是 V 自己的结论（本彩排里由 V 的模型写成一句人话，经 notice 投到 F 的
下一拍），`secretary:V` 的语义判定落在 `pending` 台账的 `secretary_judge` 里。

现在未在册那一支与在册那一支同一条件洗稿（fault 且 fault_kind 不是
procedural/style），`washed_relay` 随 pending 行落盘；洗过的文本还走既有的
`conductor.open_item` + `set_item_detail` 通道投给送审者（F）的板摘要 ——
本彩排里 F 的下一拍 prompt 逐字带着「请补第 2 步的记号说明：…」，而 V 自己的
final（「V 判有毛病：…」）仍在同一条 `框架执行结果` 里：两条一起可见，读的人
分得清"V 的原话"与"秘书洗过的转达"。已在册那一支一个字节没改
（`tests/test_rehearsal_c4_revision_chain.py::test_c4_c...` 用既有 e1 判据原样跑）。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：这条链不碰形式化工具面，两档的四段读数
应当逐字相同；关档下名册里没有 L。
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
from agentflow import modelgw as MG
from agentflow import proofregistry as PR
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

SID = "cc4-c4"
PROBLEM = "设 G 是有限群；则 |G| = p^2 时 G 是交换群。"
STEP1 = "由类方程，非中心共轭类的长度都被 p 整除。"
STEP2 = "于是 |Z(G)| 被 p 整除、非平凡。"
STEP2_FIX = "于是 |Z(G)| 被 p 整除、非平凡（p 是素数 ⇒ |Z(G)| 是 p 的正倍数）。"
STEP3 = "G/Z(G) 循环 ⇒ G 交换。"
BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
SUBGOALS = [{"sid": "s1", "text": PROBLEM, "owner": "F", "testable": "写出三步论证"}]
DEFECT = "第 2 步的记号没有定义"
#: V 收工时交给父 F 的那句人话（真机由 V 的模型写；这里是它的结论）。
REJECT_FINAL = f"V 判有毛病：{DEFECT}，请补上后再送"
SIGNED_FINAL = "V 签在稿上（连续 3/3 成立）"


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


def _root(prompt: str) -> pathlib.Path:
    m = re.search(r"工作区根目录：(.+?)。", prompt)
    return pathlib.Path(m.group(1)) if m else pathlib.Path(".")


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self, *, fault: bool = True) -> None:
        self.fault = bool(fault)
        self.bodies: list[dict[str, str]] = []
        self.prompts: list[dict[str, str]] = []
        self.steps: dict[str, int] = {}
        self.retired: list[str] = []
        self.vreview = 0
        self.vdefect = 0
        #: 两版稿的盘上全文快照（在"下一次 attack.step 之前"取：那时盘上还是上一版）。
        self.before_text = ""
        self.after_text = ""

    def _snap(self, prompt: str) -> str:
        path = _root(prompt) / "reports" / "f-proof-000000.md"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _name_of(self, prompt: str, role: str) -> str:
        names = [n for n in re.findall(r'"roster_name":\s*"([A-Z]\d*)"', prompt)
                 if n not in self.retired]
        return names[0] if names else ""

    def _retire_then(self, prompt: str, nxt: str) -> str:
        name = self._name_of(prompt, "")
        if name:
            self.retired.append(name)
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": name, "reason": "交完了"}})
        return nxt

    # ------------------------------------------------------------ 剧本
    def _m(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"summon": {"role": "D", "task": "派 F 证一条并送 V 审"}})
        return self._retire_then(prompt, _json({"final": "M 收工", "evidence": []}))

    def _d(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"summon": {"role": "F", "task": PROBLEM}})
        return self._retire_then(prompt, _json({"final": "D 收工", "evidence": []}))

    def _f(self, index: int, prompt: str) -> str:
        pid = _plan_id(prompt)
        ms = _manuscript(prompt) or "reports/f-proof-000000.md"
        v1 = {"kind": "proof", "label": "v1", "proposition": PROBLEM,
              "steps": [{"text": t, "assumption": True} for t in (STEP1, STEP2, STEP3)]}
        v2 = {"kind": "proof", "label": "v2", "proposition": PROBLEM,
              "steps": [{"text": t, "assumption": True}
                        for t in (STEP1, STEP2_FIX, STEP3)]}
        if index == 0:
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": PROBLEM, "problem_key": "p2",
                                   "budget": BUDGET, "subgoals": SUBGOALS}})
        if index == 1:
            return _json({"tool": "attack.step", "args": {"plan_id": pid, "product": v1}})
        if index == 2:
            return _json({"summon": {"role": "V", "task": f"审这一份证明稿：{ms}",
                                     "params": {"proof_manuscript": ms}}})
        if not self.fault:
            # 反真空那一趟：V 当场签住 ⇒ F 不需要重写，直接收工。
            return _json({"final": "F 收工", "evidence": []})
        if index == 3:
            # 盘上此刻还是 v1（下一步才写 v2）⇒ 这是 v1 那份稿的读数。
            self.before_text = self._snap(prompt)
            return _json({"tool": "attack.step", "args": {"plan_id": pid, "product": v2}})
        if index == 4:
            self.after_text = self._snap(prompt)
            return _json({"summon": {"role": "V",
                                     "task": f"再审这一份（已按上一轮意见改过）：{ms}",
                                     "params": {"proof_manuscript": ms}}})
        return _json({"final": "F 收工", "evidence": []})

    def _v(self, i: int, prompt: str) -> str:
        ms = _manuscript(prompt) or None
        if i == 0:
            return _json({"tool": "verify.verify_proof",
                          "args": {"proof_manuscript": ms}})
        if "再审" in _my_task(prompt):
            return _json({"final": SIGNED_FINAL})
        return _json({"final": REJECT_FINAL if self.fault else SIGNED_FINAL})

    # ------------------------------------------------------------ 回复分派
    def reply(self, *, system: str, prompt: str) -> str:
        head = system.lstrip()
        # 洗稿那一趟的稳定头是「你是「秘书」的洗稿面」（`secretary._wash_v_system`），
        # 与下面判断面的头不同：改前这里只按判断面的头分支 ⇒ 洗稿一问落到兜底
        # `{"decision": "可派"}`，`wash_v_reply` 拿不到 `text` 就落 `wash_empty_text`
        # （C4 未在册支的洗稿因此永远洗不出来）。这里补上它自己那一支。
        if head.startswith("你是「秘书」的洗稿面"):
            return _json({"text": f"请补第 2 步的记号说明：{DEFECT}。",
                          "step": 2,
                          "findings": [{"quote": DEFECT,
                                        "why": "记号没定义就没法核这一步"}]})
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            kind = m.group(1)
            if kind == "proposition_form":
                return _json({"checked": True, "well_formed": True,
                              "conditions": "G 是有限群",
                              "conclusion": "|G| = p^2 时 G 是交换群",
                              "problems": [], "decision": "形态合规",
                              "refused": "", "reason": "彩排：形态合规"})
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
            if kind == "wash_v_reply":
                return _json({"text": f"请补第 2 步的记号说明：{DEFECT}。",
                              "step": 2,
                              "findings": [{"quote": DEFECT,
                                            "why": "记号没定义就没法核这一步"}]})
            if kind == "sign_issuance":
                return _json({"decision": "签发", "reason": "三转干净",
                              "basis": ["彩排"]})
            return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["彩排"]})
        if "命题形态闸" in head:
            return _json({"checked": True, "well_formed": True, "decision": "形态合规",
                          "conditions": "G 是有限群", "conclusion": "|G| = p^2 时交换",
                          "problems": [], "refused": "", "reason": "彩排：形态合规"})
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
            if role == "V":
                stage = "V2" if "再审" in _my_task(prompt) else "V1"
                i = self.steps.get(stage, 0)
                self.steps[stage] = i + 1
                return self._v(i, prompt)
            self.steps[role] = index + 1
            if role == "M":
                return self._m(index, prompt)
            if role == "D":
                return self._d(index, prompt)
            return self._f(index, prompt)
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["彩排"]})

    def __call__(self, url: str, headers: Any, body: bytes,
                 timeout_sec: float) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        messages = payload.get("messages") or []
        system = next((str(x.get("content") or "") for x in messages
                       if x.get("role") == "system"), "")
        prompt = "\n".join(str(x.get("content") or "") for x in messages
                           if x.get("role") == "user")
        _role = re.match(r"你是 ([A-Z]) 号角色", system.lstrip())
        self.prompts.append({"role": _role.group(1) if _role else "",
                             "system": system, "prompt": prompt})
        text = self.reply(system=system, prompt=prompt)
        self.bodies.append({"system": system, "prompt": prompt, "text": text})
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


# ============================================================ 夹具与读数


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0", fault: bool = True) -> dict[str, Any]:
    """真工作区 → 从 CLI 入口真跑一趟；只替换出网那一层。"""
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
                "--subagents", "--task", "派 F 证一条并送 V 审", "--max-steps", "12",
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


def _pending_rows(ws: pathlib.Path) -> list[dict]:
    base = VR.pending_dir(ws)
    if not base.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(base.glob("*.jsonl")):
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
    return rows


def _body(text: str) -> str:
    return DS.proof_body(text)


def _step_results(events: list[dict], *, role: str, tool: str) -> list[dict]:
    out: list[dict] = []
    for e in events:
        if e.get("kind") != "agent_step" or e.get("role") != role:
            continue
        if str((e.get("payload") or {}).get("name") or "") != tool:
            continue
        got = e.get("result") or {}
        data = got.get("data")
        if hasattr(data, "to_dict"):
            data = dict(data.to_dict())
        out.append({"ok": bool(got.get("ok")),
                    "data": data if isinstance(data, dict) else {}})
    return out


def _chain_reading(got: dict[str, Any]) -> dict[str, Any]:
    ws, st = got["ws"], got["store"]
    rel = "reports/f-proof-000000.md"
    path = ws / rel
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    wire: _Wire = got["wire"]
    before, after = wire.before_text, wire.after_text
    return {
        "store": st, "ws": ws, "rel": rel, "text": text,
        "body": DS.proof_body(text) if text else "",
        "sha": PR.proof_sha(text) if text else "",
        "before_text": before, "after_text": after,
        "sha_before": PR.proof_sha(before) if before else "",
        "sha_after": PR.proof_sha(after) if after else "",
        "lines_before": _section_lines(before), "lines_after": _section_lines(after),
        "events": _events(ws), "pending": _pending_rows(ws),
        "steps": _step_results(_events(ws), role="F", tool="attack.step"),
        "v_calls": _step_results(_events(ws), role="V", tool="verify.verify_proof"),
        "plans": [dict(r) for r in st.rows("attack_plans")],
        "tasks": [dict(r) for r in st.rows("tasks")],
        "f_prompts": [p["prompt"] for p in wire.prompts if p["role"] == "F"],
    }


def _section_lines(manuscript: str) -> list[str]:
    """一份手稿的 `## 证明` 正文按行拆（空行剔掉；只用来比"改哪一步"）。"""
    if not manuscript:
        return []
    return [ln.strip() for ln in DS.proof_body(manuscript).splitlines() if ln.strip()]


def _sign_files(ws: pathlib.Path) -> list[str]:
    d = ws / "out" / "vsigns"
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


def _chain_problems(reading: dict[str, Any]) -> list[str]:
    """C4 的四段终态读数（空 = 通）。每一条都读盘/读会话，不看回执的 ok。"""
    problems: list[str] = []
    ws: pathlib.Path = reading["ws"]
    steps = reading["steps"]
    if len(steps) != 2:
        return [f"F 的 `attack.step` 应恰好两次（v1 + 重写），实得 {len(steps)}"]
    mode_before = str(steps[0]["data"].get("proof_mode") or "")
    mode_after = str(steps[1]["data"].get("proof_mode") or "")
    if mode_before != "registered":
        problems.append(f"v1 的 proof_mode 不是 registered：{mode_before!r}")
    if mode_after != "rewritten":
        problems.append(f"重写那一轮的 proof_mode 不是 rewritten：{mode_after!r}")
    sha1_old = reading["sha_before"]
    sha2_new = reading["sha_after"]
    if not sha1_old or not sha2_new or sha1_old == sha2_new:
        problems.append(f"重写前后正文 sha 没有变化：{sha1_old!r} → {sha2_new!r}")
    if sha1_old != str(steps[0]["data"].get("proof_sha256") or ""):
        problems.append(f"v1 的盘上 sha 与那一轮回执对不上："
                        f"{sha1_old!r} vs {steps[0]['data'].get('proof_sha256')!r}")
    if sha2_new != str(steps[1]["data"].get("proof_sha256") or ""):
        problems.append(f"v2 的盘上 sha 与那一轮回执对不上："
                        f"{sha2_new!r} vs {steps[1]['data'].get('proof_sha256')!r}")
    if sha2_new != reading["sha"]:
        problems.append(f"签完之后盘上正文 sha 变了：{reading['sha']!r} vs {sha2_new!r}")

    # 1. 打回是终局且点名步号：pending 一行、axis=fault、defect_step=2、v1 无签。
    first = [r for r in reading["pending"]
             if str(r.get("proof_sha256") or "") == sha1_old]
    if len(first) != 1:
        problems.append(f"v1 的 pending 应恰好 1 行，实得 {len(first)}")
    else:
        one = dict(first[0])
        judge = dict(one.get("secretary_judge") or {})
        if str(judge.get("axis") or "") != "fault":
            problems.append(f"v1 的秘书轴不是 fault：{judge.get('axis')!r}")
        if int(one.get("defect_step") or 0) != 2:
            problems.append(f"v1 的 defect_step 不是 2：{one.get('defect_step')!r}")
        if DEFECT not in str(one.get("why") or ""):
            problems.append(f"v1 的判词没留下 V 指出的那句：{one.get('why')!r}")
        if str(one.get("verdict") or "") != "成立":
            problems.append(f"v1 那一行不是 V 的结论（应为「成立」+ fault 轴）："
                            f"{one.get('verdict')!r}")
    if (ws / "out" / "vsigns" / f"{sha1_old}.json").is_file():
        problems.append("被判有缺陷的 v1 竟然有签文件（负判不是签）")
    # v1 的正文只存在于重写之前：这里从第一轮的稿面读数核它没有签块
    # （第二份稿的签块不会回写到第一份上 —— 同一路径、同一稿号，签块按现行正文算）。
    v1_sign = steps[0]["data"].get("v_sign")
    if isinstance(v1_sign, dict) and str(v1_sign.get("state") or "") not in ("", "unsigned"):
        problems.append(f"v1 的稿面竟然有签读数（state 不是 unsigned）：{v1_sign}")

    # 2. 那句意见回到 F 的下一步（重写那一拍的 prompt 逐字带着它）。
    if len(reading["f_prompts"]) < 4:
        problems.append(f"F 的 prompt 少于 4 拍：{len(reading['f_prompts'])}")
    else:
        if DEFECT not in reading["f_prompts"][3]:
            problems.append(
                "打回的意见没有回到 F 的下一步：重写那一拍的 prompt 里找不到 "
                f"「{DEFECT}」")

    # 3. 只改第 2 步：行数不变、只有第 2 行不同。
    one = list(reading["lines_before"])
    two = list(reading["lines_after"])
    if len(one) != 3 or len(two) != 3:
        problems.append(f"稿的证明步数不是 3：{one!r} / {two!r}")
    else:
        changed = [i for i, (a, b) in enumerate(zip(one, two)) if a != b]
        if changed != [1]:
            problems.append(f"改动的步不是恰好第 2 步：{changed}")
        if STEP2_FIX not in two[1]:
            problems.append(f"第 2 步不是按 V 的意见改的那一版：{two[1]!r}")

    # 4. 再送审三转 clean ⇒ 签在新 sha 上。
    second = [r for r in reading["pending"]
              if str(r.get("proof_sha256") or "") == sha2_new]
    if len(second) != int(VR.SIGN_STREAK_NEED):
        problems.append(f"新 sha 的 pending 应恰好 {VR.SIGN_STREAK_NEED} 行，"
                        f"实得 {len(second)}")
    if any(str(dict(r.get("secretary_judge") or {}).get("axis") or "") == "fault"
           for r in second):
        problems.append("新 sha 的三转里混进了 fault")
    if not (ws / "out" / "vsigns" / f"{sha2_new}.json").is_file():
        problems.append(f"新签文件不在盘上：out/vsigns/{sha2_new}.json")
    else:
        sign = VS.sign_of(ws, sha2_new)
        if str(sign.get("artifact_sha") or "") != sha2_new:
            problems.append(f"签里的 artifact_sha 不是新 sha：{sign.get('artifact_sha')!r}")
    standing = VS.manuscript_sign_standing(reading["text"], proof_sha=sha2_new)
    if str(standing.get("state") or "") != "signed":
        problems.append(f"稿上的签块不是 signed：{standing.get('state')!r} "
                        f"({standing.get('why') or standing.get('reason') or ''})")
    signed_calls = [c for c in reading["v_calls"]
                    if str(c["data"].get("kind") or "") == "proof_unregistered_signed"]
    if not signed_calls:
        problems.append(f"V 没有一次签住：{[c['data'].get('kind') for c in reading['v_calls']]}")
    elif len(signed_calls[-1]["data"].get("review_passes") or []) != int(
            VR.SIGN_STREAK_NEED):
        problems.append(f"签住那一趟不是三转："
                        f"{len(signed_calls[-1]['data'].get('review_passes') or [])}")
    rejected_calls = [c for c in reading["v_calls"]
                      if str(c["data"].get("kind") or "") == "proof_unregistered_rejected"]
    if not rejected_calls:
        problems.append("V 一次都没有走「打回」那一档")
    elif int(rejected_calls[0]["data"].get("defect_step") or 0) != 2:
        problems.append(f"打回那一趟的 defect_step 不是 2："
                        f"{rejected_calls[0]['data'].get('defect_step')!r}")

    # 5. 收工：F 的 final 过门（稿有现行签）、M 的 final 过整树销号门。
    ends = [e for e in reading["events"] if e.get("kind") == "agent_run_end"]
    f_ends = [e for e in ends if str(e.get("role") or "") == "F"]
    if not [e for e in f_ends if str(e.get("stop_reason") or "") == "final"]:
        problems.append(f"F 没有以 final 收工：{[e.get('stop_reason') for e in f_ends]}")
    f_tasks = [t for t in reading["tasks"]
               if str(t.get("role") or "") == "F" and not str(t.get("action") or "")]
    if not [t for t in f_tasks if str(t.get("outcome") or "") == "ok"]:
        problems.append(f"F 的 task 结论不是 ok：{f_tasks}")
    return problems


def _lines(step: dict) -> list[str]:
    """某一轮稿的证明步骤（`attack.step` 回执里的 `proof_statements`，逐行文本）。"""
    return [str(x) for x in (step["data"].get("proof_statements") or [])]


# ============================================================ ① 正控


def test_the_rejection_rewrite_and_resign_run_from_the_cli(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：V 点名第 2 步 → F 的下一步带着那句意见 → 只改第 2 步 → 再送审签住。"""
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

    # ---- V 的两次调用都在真循环里（事件逐条查得到），且第一次是"打回"。
    assert len(reading["v_calls"]) == 2, reading["v_calls"]
    assert str(reading["v_calls"][0]["data"].get("kind") or "") == (
        "proof_unregistered_rejected")
    assert str(reading["v_calls"][1]["data"].get("kind") or "") == (
        "proof_unregistered_signed")
    # 稿上签块的三个读数（连续次数 / 签名者 / 正文 sha）。
    assert "连续=3/3" in reading["text"], reading["text"][:600]
    assert "签名者=secretary:F" in reading["text"], reading["text"][:600]
    assert reading["sha"] in reading["text"], reading["text"][:600]

    # ---- 钱：账本有行、无主为 0、悬空 0、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空


def test_a_clean_second_pass_skips_the_rejection_and_the_rewrite(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 `secretary:V` 的判定换成恒 clean ⇒ 打回与重写一起消失。

    同一份 wire、同一份夹具，只改秘书那一格：第一份稿三转干净、当场签住，
    F 一次都没重写（`proof_mode` 只有 `registered`）。它证明主链的
    "打回 → 重写 → 再签"不是恒真，而是压在那一条语义判定上。
    """
    got = _run(tmp_path, monkeypatch, lean="0", fault=False)
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert len(reading["steps"]) == 1, (
        f"判定换成 clean 之后 F 还重写了：{[s['data'].get('proof_mode') for s in reading['steps']]}")
    assert str(reading["steps"][0]["data"].get("proof_mode") or "") == "registered"
    assert not [r for r in reading["pending"]
                if str(dict(r.get("secretary_judge") or {}).get("axis") or "") == "fault"], (
        "判定换成 clean 之后 pending 里还有 fault")
    sha = str(reading["steps"][0]["data"].get("proof_sha256") or "")
    assert (reading["ws"] / "out" / "vsigns" / f"{sha}.json").is_file(), _sign_files(reading["ws"])
    assert len([r for r in reading["pending"]
                if str(r.get("proof_sha256") or "") == sha]) == int(VR.SIGN_STREAK_NEED)
    assert str(VS.manuscript_sign_standing(
        reading["text"], proof_sha=sha).get("state") or "") == "signed"
    assert [e for e in reading["events"] if e.get("kind") == "agent_run_end"
            and str(e.get("role") or "") == "F"
            and str(e.get("stop_reason") or "") == "final"], "F 没有以 final 收工"


# ============================================================ 判据①：一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    print(f"[一行账] c4 lean={lean} 真调用={reading['calls']} "
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
    print(f"[会话归口] c4 lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_the_revision_loop_is_the_same_in_both_lean_modes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档：同一条链照跑，四段读数不变。"""
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
