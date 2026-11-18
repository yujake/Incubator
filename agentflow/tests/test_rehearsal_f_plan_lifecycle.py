# -*- coding: utf-8 -*-
"""彩排（真路径）F 线 · 计划生命周期：CLI 入口 → M→D→F（同一 F 名册实例接三件活）→ F 的步循环 + 真秘书。

## 这条链与真机差在哪（逐项）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条 |
| 派活 | `Conductor.summon`（`M→D`、`D→F` 都是 `ALLOWED_EDGES` 里的真边） | 同一条 |
| F 的步循环 | `AgentLoop.run` 里每一步由模型出形状 | 同一条：F 的 `attack.*` 是模型在循环里调到的 |
| 计划生命周期 | `attack.create_plan` / `attack.step` / `attack.abandon_plan` → `AgentF` 那一组动作 | 同一条：动作实现、预算、台账、`_write_plan` 全是产品原物 |
| 秘书判断 | `secretary.dispatch_fit`（D 派活的建议）＋ `secretary.judge_proposition_form`（F 交稿的形态闸） | 同一条：两处都是真 `Secretary` 走真 `LlmSeam`，只换模型那句话 |
| 收工门 | `_v_wait_gate_reading`（F 按签/放弃拦收工）＋ `_final_gate_reading`（M 整树销号） | 同一条：F1/F2 的 final 被真门拒，F3 过 |
| 模型缝 | 真 `LlmSeam`（`_agent_seam_factory` / `for_role` / `for_secretary`） | 同一条：构造点一个都没替换 |
| 记账 | 真 `TokenMeter` → `usage_ledger` | 同一条 |
| 出网 | `modelgw.urllib_transport`（HTTP POST） | 只换这一处：回预置的 OpenAI 兼容 JSON |

旧版（改写前登记在 `CHAIN_ONLY` 里）直调
`AgentF.create_plan/step/abandon_plan` 与 `Secretary.handoff_add`，打桩
`Secretary._judge_core` / `AgentF._write_plan` / `CP.PARALLEL_PLANS_LIMIT`；这一份一处都不换。

## 这条链覆盖什么（业主点名的 F 线）

```text
M --summon--> D --summon--> F1: create pA → step pA（交稿过形态闸）→ create pB → final（被收工门拒：两条计划未签未放弃）
D: attack.list_plans / attack.status 读计划 → 把建议写进下一次派活（真 summon 的 dispatch handoff 落 hands 台账）
D --summon--> 同一个 F1（reuse）: abandon pB「不再需要」（按 D 的建议）→ abandon pA「math_error」
                   → difficulty 那条（difficulty + salvaged）→ 两条在推时第三条被拒（业主原话）
                   → 「需要调整」在工具面被参数闸拒（行一个字节不改）→ 放弃 + 新开一条（组合操作）
                   → create pI（又一条在推）→ final（被真门拒：pI 未签未放弃）
D: attack.list_plans 读到 pI 仍 open → 建议写进第三次派活
D --summon--> 同一个 F1（reuse）: abandon pI「不再需要」→ final（过门）
D 销号那几个 F 名 → final；M 销号 D → final（整树销号）
```

### 为什么三件活复用同一个 F 名字（K3 起）

计划归实例（`attack_plans.created_by` = `agent-F-<名册名>`）：非属主 `step` /
`abandon_plan` 是受控拒（`plan_not_yours`）。所以「D 把建议发给下一个 F、下一个 F 照做」
这条链只有在「建议送到属主本人」时才走得通 —— 彩排因此用 `reuse=<名册名>` 派三件活
（三个台账号、同一个 F 实例），与真机里"同一个 F 跨趟接着攻"是同一条路。
"另一个实例想动这条计划会被拒"由 `tests/test_the_plan_belongs_to_one_instance.py` 的
a / b 两条单独钉（那里造的就是非属主）。

判据读盘（不是回执）：`attack_plans` 八行全部 `abandoned`；每行 `history` 的动作序列与
`abandon_kind` / `difficulty` / `salvaged` 逐条对得上；前两趟 F 的 `agent_run_end` 是
`final_refused` 且拒信点名未收口的那条计划；`out/secretary/proposition_form.jsonl` 有
`role=F` 一笔、`dispatch_fit.jsonl` 有 D 那一笔建议；`manuscripts/handoffs.jsonl` 里
D 的派活建议点名了 pB 与 pI；钱账逐分相等、无主 0、悬空 0。

## 反真空（同一个工作区里造红，不是另一份夹具）

- 收工门真的读台账：前两趟 F 发 final 时盘上各有一条「未签未放弃」的计划 ⇒
  final 被拒（`final_refused`、task `outcome=no_result`）。它证明正控里最后一趟的
  `final` 绿不是"final 恒放行"，而是"计划都收口了"。
- 并发上限真的来自那一格：第三条计划被拒时拒信逐字含业主那句提醒，且
  `attack_plans` 一行不多；随后把它前面的两条放弃之后，新的一条就建成了
  （同一个上限、同一条代码路径）。
- 「需要调整」不是理由值：工具面把它当参数错误拒掉（`reason` 的枚举里没有它），
  行一个字节不改；随后按口径做组合操作（放弃原计划 + 新开一条），两条都在盘上。

## 与旧彩排的一处刻意收窄（说清楚，不掩盖）

旧彩排直调 `AgentF.abandon_plan(reason="需要调整")`，断言产品那句
`plan_abandon_reason_not_allowed`。真机模型只能看到 `attack.abandon_plan` 这件工具，
它的 `reason` 是枚举（`math_error|difficulty|不再需要`）⇒ 那句话在真机上被
参数闸挡在动作实现之前。所以这一份断言的是参数闸的受控拒 + 行不变 + 组合操作，
不是 `plan_abandon_reason_not_allowed` 的原话 —— 后者的单点判据仍在
`tests/test_f_plan_abandon.py` 那一族（方法层）。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：计划生命周期与 Lean 无关（不产实验行、
不碰形式化工具面），两档的八条计划和收工门读数应当逐字相同；关档下名册里没有 L。
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

SID = "cc4-f-plan"
PROBLEM = "设 G 是有限群；则 |G| = p^2 时 G 是交换群。"
STEP1 = "由类方程，非中心共轭类的长度都被 p 整除。"
STEP2 = "于是 |Z(G)| 被 p 整除、非平凡。"
STEP3 = "G/Z(G) 循环 ⇒ G 交换。"
BUDGET = {"max_rounds": 3, "max_parallel_subgoals": 2,
          "max_persist_attempts": 2, "max_depth": 2}
SUBGOALS = [{"sid": "s1", "text": PROBLEM, "owner": "F", "testable": "写出三步论证"}]
#: 业主原话（逐字；并发上限那一格只在拒信里出现这一句）。
OWNER_TEXT = ("同时推进的plan个数已达上限2，请先推进已有plan，"
              "或将新plan的计划汇报父D，让父派其它F攻坚。")
#: 三条派活的任务文本（wire 按它选剧本 —— 与真机"派活文本就是给 F 的活"同一条路）。
TASK_F1 = "第一段：按这个方向先开两条计划，推进第一条并交一份稿，然后收工"
TASK_F2 = ("第二段：按 D 的建议处置已有计划，并继续走并发上限与放弃四档："
          "方向二（把同构类数出来）不再需要；方向一按 math_error 处置")
TASK_F3 = "第三段：按 D 的建议把方向九那条计划放弃成「不再需要」"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _find(prompt: str, pattern: str) -> str:
    m = re.search(pattern, prompt)
    return m.group(0) if m else ""


def _roster_names(prompt: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'"roster_name":\s*"([A-Z]\d*)"', prompt)]


def _my_task(prompt: str) -> str:
    return _find(prompt, r"这一趟派给你的活是 —— .+")


def _plan_id(prompt: str) -> str:
    """最近一次回执里的计划号（`attack.create_plan` 的 `data.plan_id`）。"""
    hits = re.findall(r'"data\.plan_id":\s*"(\d{6})"', prompt)
    return hits[-1] if hits else ""


def _open_plans(prompt: str) -> dict[str, str]:
    """从 `attack.list_plans` 的回执里读 `problem_key -> plan_id`（只读 open 的那些）。"""
    out: dict[str, str] = {}
    for m in re.finditer(r'"plan_id":\s*"(\d{6})",\s*"problem_key":\s*"([^"]+)"'
                         r'(?:,.*?)?"status":\s*"(\w+)"', prompt, re.S):
        if m.group(3) == "open":
            out[m.group(2)] = m.group(1)
    return out


def _all_plans(prompt: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r'"plan_id":\s*"(\d{6})",\s*"problem_key":\s*"([^"]+)"', prompt):
        out[m.group(2)] = m.group(1)
    return out


def _notified(prompt: str) -> str:
    """最近一次 `handoff` 回执里投递出去的那条板项号（`notified`）。"""
    hits = re.findall(r'"notified":\s*"(t-\d+)"', prompt)
    return hits[-1] if hits else ""


class _Wire:
    """预置的网络传输层替身（只回答"上游收到了什么、回了什么"）。"""

    def __init__(self) -> None:
        self.bodies: list[dict[str, str]] = []
        self.steps: dict[str, int] = {}
        self.retired: list[str] = []
        self.dispatch_fit = 0
        #: 这一趟从盘上读到的 `problem_key -> plan_id`（模型读一次、后面都按号说话）。
        self.ids: dict[str, str] = {}
        #: 两条建议投递出去之后各自落下的板项号（D 随后要撤销它们才能销号）。
        self.items: list[str] = []
        #: 刚发出去的那一条 `create_plan` 属于哪个 `problem_key`（下一拍从回执取号）。
        self.pending_key = ""
        #: 名册里那个 F 的名字（K3 起三件活复用同一个实例：`reuse` 它）。
        self.fname = ""

    def _note_ids(self, prompt: str) -> None:
        self.ids.update(_all_plans(prompt))
        made = _plan_id(prompt)
        if made and self.pending_key:
            self.ids[self.pending_key] = made
            self.pending_key = ""
        item = _notified(prompt)
        if item and item not in self.items:
            self.items.append(item)

    def _name_of(self, prompt: str, role: str, skip: int = -1) -> str:
        """名册里那个角色的实例名（缺省取最新那个 —— 派活是派给"下一个 F"）。"""
        names = [n for n in _roster_names(prompt) if n.startswith(role)
                 and n not in self.retired]
        if not names:
            return ""
        try:
            return names[skip]
        except IndexError:
            return ""

    def _fname(self, prompt: str) -> str:
        """名册里那个 F 的名字：K3 起计划归实例，非属主放弃会被受控拒 ⇒ 三件活必须复用
        同一个 F 名字（`reuse`），否则 D 的建议送到的是另一个实例、它动不了那条计划。

        名字从召唤回执的 `roster_name` 读（`_roster_names` 那一条正则就是读它）；
        读不到就返回空串 —— 那会让下一次召唤变成"新建一个实例"，本文件当场红（这是想要的：
        静默换一个实例等于把"归属"这件事从彩排里拿掉）。
        """
        names = [n for n in _roster_names(prompt) if n.startswith("F")
                 and n not in self.retired]
        if names:
            self.fname = names[-1]
        return self.fname

    # ------------------------------------------------------------ 剧本：M / D
    def _retire_then(self, prompt: str, role: str, nxt: str) -> str:
        todo = [n for n in _roster_names(prompt) if n not in self.retired]
        if todo:
            self.retired.append(todo[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": todo[0], "reason": "交完了"}})
        return nxt

    def _m(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"summon": {"role": "D",
                                     "task": "把这一方向交给 F 走计划生命周期"}})
        return self._retire_then(prompt, "M", _json({"final": "M 收工", "evidence": []}))

    def _advice(self) -> str:
        return (f"计划 {self.ids.get('pB')}（方向二）不再需要了：方向已改，"
                f"请把它放弃成「不再需要」；计划 {self.ids.get('pA')} 按 math_error 处置。")

    def _d(self, index: int, prompt: str) -> str:
        if index == 0:
            return _json({"summon": {"role": "F", "task": TASK_F1, "instance": "1"}})
        if index == 1:
            return _json({"tool": "attack.list_plans", "args": {}})
        if index == 2:
            return _json({"tool": "attack.status",
                          "args": {"plan_id": self.ids.get("pB") or ""}})
        if index == 3:
            # 反真空（真机上会踩到）：把计划号写进派活文本 ⇒ `dispatchpolicy` 受控拒。
            # K3 起同一个 F 名册实例接着干（`reuse`）：计划归实例，三件活必须是同一个实例。
            return _json({"summon": {"role": "F", "reuse": self._fname(prompt),
                                     "task": f"{TASK_F2}：{self._advice()}"}})
        if index == 4:
            # 建议走 handoff（不是派活文本）：计划号写在正文里不触发那条闸。
            return _json({"handoff": {
                "to": self._name_of(prompt, "F"),
                "summary": f"计划 {self.ids.get('pB')} 不再需要",
                "body": self._advice(),
                "refs": [f"plan:{self.ids.get('pB')}"]}})
        if index == 5:
            return _json({"summon": {"role": "F", "reuse": self._fname(prompt),
                                     "task": TASK_F2}})
        if index == 6:
            return _json({"tool": "conductor.void_items",
                          "args": {"item_ids": self.items[:1],
                                   "why": "建议已随派活转达给下一个 F，这条通知不再需要做"}})
        if index == 7:
            return _json({"tool": "attack.list_plans", "args": {}})
        if index == 8:
            advice = (f"计划 {self.ids.get('pI')}（方向九）也不再需要了：证据已够，"
                      "请把它放弃成「不再需要」。")
            return _json({"handoff": {
                "to": self._name_of(prompt, "F"),
                "summary": f"计划 {self.ids.get('pI')} 不再需要",
                "body": advice,
                "refs": [f"plan:{self.ids.get('pI')}"]}})
        if index == 9:
            return _json({"summon": {"role": "F", "reuse": self._fname(prompt),
                                     "task": TASK_F3}})
        if index == 10:
            return _json({"tool": "conductor.void_items",
                          "args": {"item_ids": self.items[-1:],
                                   "why": "建议已随派活转达给下一个 F，这条通知不再需要做"}})
        return self._retire_then(prompt, "D", _json({"final": "D 收工", "evidence": []}))

    # ------------------------------------------------------------ 剧本：F 的三个实例
    def _f_first(self, index: int, prompt: str) -> str:
        if index == 0:
            self.pending_key = "pA"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向一：" + PROBLEM, "problem_key": "pA",
                                   "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        if index == 1:
            return _json({"tool": "attack.step",
                          "args": {"plan_id": _plan_id(prompt),
                                   "product": {"kind": "proof", "label": "v1",
                                               "proposition": PROBLEM,
                                               "steps": [{"text": t, "assumption": True}
                                                         for t in (STEP1, STEP2, STEP3)]}}})
        if index == 2:
            self.pending_key = "pB"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向二：把同构类数出来",
                                   "problem_key": "pB", "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        return _json({"final": "F1 收工", "evidence": []})

    def _f_second(self, index: int, prompt: str) -> str:
        ids = self.ids
        if index == 0:
            return _json({"tool": "attack.list_plans", "args": {}})
        if index == 1:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pB") or "",
                                   "reason": "不再需要",
                                   "basis": "D 的建议：方向二不再需要"}})
        if index == 2:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pA") or "",
                                   "reason": "math_error",
                                   "basis": "第 3 步把 n=2 的情形当成了任意 n"}})
        if index == 3:
            self.pending_key = "pC"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向三：紧性估计卡住了",
                                   "problem_key": "pC", "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        if index == 4:
            return _json({"tool": "attack.step",
                          "args": {"plan_id": ids.get("pC") or _plan_id(prompt)}})
        if index == 5:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pC") or "", "reason": "difficulty",
                                   "basis": "卡在紧性估计：需要一条与主链独立的界",
                                   "difficulty": "紧性引理拿不到一致常数",
                                   "salvaged": [{"label": "部分紧性", "stmt_id": "000051"}]}})
        if index == 6:
            self.pending_key = "pD"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向四", "problem_key": "pD",
                                   "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        if index == 7:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pD") or _plan_id(prompt),
                                   "reason": "不再需要",
                                   "basis": "目标已改为另一条方向"}})
        if index == 8:
            self.pending_key = "pE"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向五", "problem_key": "pE",
                                   "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        if index == 9:
            self.pending_key = "pF"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向六", "problem_key": "pF",
                                   "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        if index == 10:
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向七", "problem_key": "pG",
                                   "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        if index == 11:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pE") or "", "reason": "math_error",
                                   "basis": "方向五的估计写错了"}})
        if index == 12:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pF") or "", "reason": "不再需要",
                                   "basis": "方向六与方向五重复"}})
        if index == 13:
            self.pending_key = "pH"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向八", "problem_key": "pH",
                                   "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        if index == 14:
            # 旧彩排的「需要调整」：真机工具面按枚举拒（参数闸），行一个字节不改。
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pH") or _plan_id(prompt),
                                   "reason": "需要调整"}})
        if index == 15:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pH") or "", "reason": "不再需要",
                                   "basis": "按新方向重排"}})
        if index == 16:
            self.pending_key = "pI"
            return _json({"tool": "attack.create_plan",
                          "args": {"problem": "方向九", "problem_key": "pI",
                                   "budget": BUDGET,
                                   "subgoals": [dict(s) for s in SUBGOALS]}})
        return _json({"final": "F2 收工", "evidence": []})

    def _f_third(self, index: int, prompt: str) -> str:
        ids = self.ids
        if index == 0:
            return _json({"tool": "attack.list_plans", "args": {}})
        if index == 1:
            return _json({"tool": "attack.abandon_plan",
                          "args": {"plan_id": ids.get("pI") or "", "reason": "不再需要",
                                   "basis": "D 的建议：方向九不再需要"}})
        return _json({"final": "F3 收工", "evidence": []})

    def _f(self, prompt: str) -> str:
        task = _my_task(prompt)
        if not task:
            # 被一条 message / notice 叫醒的续跑（同一个台账号、没有新派活）：
            # 它读一下板就收工。它不许消费 F1/F2/F3 剧本的下一拍 —— 那会让
            # "派活序列"与"唤醒"互相串位（2026-11-16 WF 修好执行侧之后实测）。
            return _json({"final": "被唤醒的 F 读完了板，收工", "evidence": []})
        stage = ("F1" if TASK_F1 in task else "F2" if TASK_F2 in task else "F3")
        index = self.steps.get(stage, 0)
        self.steps[stage] = index + 1
        if stage == "F1":
            return self._f_first(index, prompt)
        if stage == "F2":
            return self._f_second(index, prompt)
        return self._f_third(index, prompt)

    # ------------------------------------------------------------ 回复分派
    def reply(self, *, system: str, prompt: str) -> str:
        head = system.lstrip()
        m = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if m:
            kind = m.group(1)
            if kind == "proposition_form":
                return _json({"checked": True, "well_formed": True,
                              "conditions": "G 是有限群",
                              "conclusion": "|G| = p^2 时 G 是交换群",
                              "problems": [], "decision": "形态合规",
                              "refused": "", "reason": "彩排：形态合规"})
            if kind == "dispatch_fit":
                self.dispatch_fit += 1
                if self.dispatch_fit == 1:
                    return _json({"decision": "不是一个方向",
                                  "reason": "这条派活里捆了两个方向 ⇒ 建议拆成两条：各派一个 F",
                                  "basis": ["task 里同时出现两个方向"]})
                return _json({"decision": "是一个方向",
                              "reason": "只写了一个方向", "basis": ["夹具"]})
            return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["夹具"]})
        if "命题形态闸" in head:
            return _json({"checked": True, "well_formed": True, "decision": "形态合规",
                          "conditions": "G 是有限群", "conclusion": "|G| = p^2 时交换",
                          "problems": [], "refused": "", "reason": "彩排：形态合规"})
        m = re.match(r"你是 ([A-Z]) 号角色", head)
        if m:
            role = m.group(1)
            self._note_ids(prompt)
            index = self.steps.get(role, 0)
            if role == "M":
                self.steps["M"] = index + 1
                return self._m(index, prompt)
            if role == "D":
                self.steps["D"] = index + 1
                return self._d(index, prompt)
            if role == "F":
                return self._f(prompt)
        return _json({"decision": "可派", "reason": "彩排：兜底", "basis": ["夹具"]})

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
         lean: str = "0") -> dict[str, Any]:
    """真工作区 → 从 CLI 入口真跑一趟；只替换出网那一层。"""
    st = Store(base / "ws")
    st.init()
    wire = _Wire()
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root), "--sid", SID,
                "--subagents", "--task", "把这一方向交给 F 走计划生命周期", "--max-steps", "30",
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


def _tool_calls(events: list[dict], *, role: str, tool: str) -> list[dict]:
    return [e for e in events
            if e.get("kind") == "agent_step" and e.get("role") == role
            and e.get("shape") == "tool"
            and str((e.get("payload") or {}).get("name") or "") == tool]


def _result(call: dict) -> dict:
    got = call.get("result") or {}
    data = got.get("data")
    if hasattr(data, "to_dict"):
        data = dict(data.to_dict())
    return {"ok": bool(got.get("ok")), "data": data if isinstance(data, dict) else {},
            "error": str(got.get("error") or ""), "meta": dict(got.get("meta") or {})}


def _jsonl_rows(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _chain_reading(got: dict[str, Any]) -> dict[str, Any]:
    ws, st = got["ws"], got["store"]
    plans = [dict(r) for r in st.rows("attack_plans")]
    events = _events(ws)
    return {
        "store": st, "ws": ws, "events": events, "plans": plans,
        "tasks": [dict(r) for r in st.rows("tasks")],
        "by_key": {str(r.get("problem_key") or ""): r for r in plans},
        "form_rows": _jsonl_rows(ws / "out" / "secretary" / "proposition_form.jsonl"),
        "fit_rows": _jsonl_rows(ws / "out" / "secretary" / "dispatch_fit.jsonl"),
        "handoffs": _jsonl_rows(ws / "manuscripts" / "handoffs.jsonl"),
        "manuscripts": sorted(p.name for p in (ws / "reports").glob("*.md"))
        if (ws / "reports").is_dir() else [],
        "runs_end": [e for e in events if e.get("kind") == "agent_run_end"],
    }


def _history(plan: dict) -> list[dict]:
    return [dict(h) for h in (plan.get("history") or [])]


def _chain_problems(reading: dict[str, Any]) -> list[str]:
    """F 线的终态读数（空 = 通）。每一条都读盘/读会话，不看回执的 ok。"""
    problems: list[str] = []
    plans = {str(r.get("problem_key") or ""): r for r in reading["plans"]}

    # 1. 八条计划、全部终态；第三条并发的那一条一个字节都不落。
    if len(reading["plans"]) != 8:
        problems.append(f"attack_plans 应恰好 8 行，实得 {len(reading['plans'])} 行："
                        f"{sorted(plans)}")
    if "pG" in plans:
        problems.append("并发上限拒绝的那条计划竟然落库了（pG）")
    for key, row in sorted(plans.items()):
        if str(row.get("status") or "") != "abandoned":
            problems.append(f"计划 {key}（{row.get('plan_id')}）不是 abandoned："
                            f"{row.get('status')!r}")

    # 2. a：math_error 那一档 —— 推进一行 + 放弃一行，放弃行点名第 3 步。
    a = plans.get("pA") or {}
    hist = _history(a)
    if [str(h.get("action") or "") for h in hist] != ["proof", "abandon"]:
        problems.append(f"pA 的 history 不是 [proof, abandon]：{[h.get('action') for h in hist]}")
    else:
        if str(hist[1].get("abandon_kind") or "") != "math_error":
            problems.append(f"pA 的放弃档不是 math_error：{hist[1].get('abandon_kind')!r}")
        if "第 3 步" not in str(hist[1].get("detail") or ""):
            problems.append(f"pA 的放弃行没有点名第 3 步：{hist[1].get('detail')!r}")
        if int(a.get("rounds") or 0) != 1:
            problems.append(f"pA 的 rounds 不是 1：{a.get('rounds')!r}")

    # 3. b：difficulty 档的 difficulty / salvaged 都落行。
    c = plans.get("pC") or {}
    hist_c = _history(c)
    if [str(h.get("action") or "") for h in hist_c] != ["no_change", "abandon"]:
        problems.append(f"pC 的 history 不是 [no_change, abandon]："
                        f"{[h.get('action') for h in hist_c]}")
    else:
        last = hist_c[-1]
        if str(last.get("abandon_kind") or "") != "difficulty":
            problems.append(f"pC 的放弃档不是 difficulty：{last.get('abandon_kind')!r}")
        if "紧性" not in str(last.get("difficulty") or ""):
            problems.append(f"pC 的 difficulty 没落行：{last.get('difficulty')!r}")
        if list(last.get("salvaged") or []) != [{"label": "部分紧性", "stmt_id": "000051"}]:
            problems.append(f"pC 的 salvaged 没落行：{last.get('salvaged')!r}")

    # 4. e：D 的建议真的写进了派活，F 照建议放弃（两条）。
    for key in ("pB", "pI"):
        hist = _history(plans.get(key) or {})
        if not hist:
            problems.append(f"{key} 没有放弃行")
            continue
        last = hist[-1]
        if str(last.get("abandon_kind") or "") != "不再需要":
            problems.append(f"{key} 不是按 D 的建议放弃成「不再需要」："
                            f"{last.get('abandon_kind')!r}")
        if "D 的建议" not in str(last.get("detail") or ""):
            problems.append(f"{key} 的放弃行没有留下「D 的建议」：{last.get('detail')!r}")
    advice = [r for r in reading["handoffs"] if str(r.get("sender") or "") == "D"]
    if len(advice) != 2:
        problems.append(f"D 的建议应恰好 2 条（两次 handoff），实得 {len(advice)}")
    bodies = " ".join(str(r.get("body") or "") for r in advice)
    for key in ("pB", "pI"):
        pid = str((plans.get(key) or {}).get("plan_id") or "")
        if pid and pid not in bodies:
            problems.append(f"D 的建议里没有点名 {key}（{pid}）：{bodies[:200]!r}")

    # 5. 「需要调整」那一笔在工具面被参数闸拒，行不变（history 只有一条放弃行）。
    h = _history(plans.get("pH") or {})
    if [str(x.get("action") or "") for x in h] != ["abandon"]:
        problems.append(f"pH 的 history 不是恰好一条 abandon（「需要调整」写库了？）："
                        f"{[x.get('action') for x in h]}")
    elif str(h[0].get("abandon_kind") or "") != "不再需要":
        problems.append(f"pH 最后不是按组合操作放弃的：{h[0].get('abandon_kind')!r}")

    # 6. f：D 的秘书审派活只提醒不拦 —— 建议落行，派活照发。
    fits = [r for r in reading["fit_rows"] if str(r.get("verdict") or "") == "不是一个方向"]
    if not fits:
        problems.append(f"dispatch_fit 里没有「不是一个方向」那一笔：{reading['fit_rows']}")
    if not any(str(r.get("role") or "") == "D" for r in _plan_tasks(reading)):
        problems.append("D 那一行没有被落到 tasks 里（派活被秘书的建议拦掉了？）")
    if not [t for t in reading["tasks"] if str(t.get("role") or "") == "F"]:
        problems.append("F 一次都没被派出去（秘书的建议不该拦派活）")

    # 7. 形态闸：F 交稿那一笔真的判过（不是没判就算过）。
    if not [r for r in reading["form_rows"] if str(r.get("role") or "") == "F"]:
        problems.append(f"out/secretary/proposition_form.jsonl 没有 F 那一笔：{reading['form_rows']}")
    if not [n for n in reading["manuscripts"] if n.startswith("f-proof-")]:
        problems.append(f"F 的稿没落盘：{reading['manuscripts']}")

    # 8. 收工门：F1 / F2 的 final 被拒（计划未收口），F3 的过。
    for key, want in (("F1", "final_refused"), ("F2", "final_refused"), ("F3", "final")):
        ends = [e for e in reading["runs_end"] if str(e.get("stop_reason") or "") == want
                and str(e.get("role") or "") == "F"]
        if not ends:
            problems.append(f"{key} 的 agent_run_end 里没有 stop_reason={want}："
                            f"{[(e.get('role'), e.get('stop_reason')) for e in reading['runs_end']]}")
    f3_ok = [t for t in reading["tasks"]
             if str(t.get("role") or "") == "F" and str(t.get("outcome") or "") == "ok"
             and not str(t.get("action") or "")]
    if not f3_ok:
        problems.append(f"F3 那一趟 task 不是 ok：{[t for t in reading['tasks'] if t.get('role') == 'F']}")
    return problems


def _plan_tasks(reading: dict[str, Any]) -> list[dict]:
    return [t for t in reading["tasks"] if str(t.get("role") or "") == "D"]


# ============================================================ ① 正控


def test_the_plan_lifecycle_runs_in_fs_step_loop_with_the_real_secretary(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：M→D→F（三步实例）走完整条计划生命周期，全部经工具分发与真秘书。"""
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

    # ---- 计划生命周期是 F 在真循环里调的（事件里逐条查得到）
    for tool in ("attack.create_plan", "attack.step", "attack.abandon_plan"):
        assert _tool_calls(reading["events"], role="F", tool=tool), f"F 没调过 {tool}"
    # 并发上限那一笔：拒信逐字含业主原话；它是动作层的受控拒（外层 ok=True、
    # `data.created=False`），不是参数错 —— 两层受控拒在读数上分得开。
    creates = [_result(e) for e in _tool_calls(reading["events"], role="F",
                                               tool="attack.create_plan")]
    refused = [r for r in creates if r["data"].get("created") is False]
    assert len(refused) == 1, [(r["ok"], r["data"].get("created")) for r in creates]
    assert refused[0]["ok"] is True, (
        "并发上限是动作层的受控拒（外层 ok=True、data.created=False），"
        f"不该被参数闸拦：{refused[0]}")
    assert OWNER_TEXT in str(refused[0]["data"].get("error") or ""), refused[0]["data"]
    assert str(refused[0]["data"].get("refusal_reason") or "") == "invalid_params", refused[0]
    # 「需要调整」那一笔：工具面按参数闸拒，错误里点名 reason 的枚举。
    abandons = [_result(e) for e in _tool_calls(reading["events"], role="F",
                                                tool="attack.abandon_plan")]
    bad = [r for r in abandons if not r["ok"]]
    assert len(bad) == 1, [r["error"] for r in bad]
    assert "需要调整" in bad[0]["error"], bad[0]["error"]
    assert "参数" in bad[0]["error"], bad[0]["error"]

    # ---- 派活文本那一条闸真的判过：把计划号写进派活 ⇒ 受控拒；只说方向 ⇒ 放行。
    refused = [e for e in reading["events"]
               if e.get("kind") == "agent_step" and e.get("shape") == "summon"
               and str((e.get("result") or {}).get("refused") or "")
               == "dispatch_names_a_conjecture_id"]
    assert len(refused) == 1, (
        f"把计划号写进派活文本没有被 `dispatchpolicy` 拒："
        f"{[e.get('result') for e in reading['events'] if e.get('shape') == 'summon']}")
    landed = [e for e in reading["events"]
              if e.get("kind") == "agent_step" and e.get("shape") == "summon"
              and e.get("role") == "D" and (e.get("result") or {}).get("task_id")]
    assert len(landed) == 3, f"D 应该成功派出三个 F 实例：{len(landed)}"
    for one in landed:
        policy = dict((one.get("result") or {}).get("dispatch_policy") or {})
        assert policy.get("checked") is True and not policy.get("violations"), policy

    # ---- 钱：账本有行、无主为 0、悬空 0、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(reading["store"])
    assert money["ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money


# ============================================================ ② 反真空


def test_an_open_plan_refuses_fs_final_and_a_wider_cap_would_not(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：计划未收口时 F 的 final 必须被拒 —— 收工门读的是台账，不是回执。

    同一个工作区里三段读数各自造红/转绿：
    1. F1 发 final 时盘上有两条「未签未放弃」的计划 ⇒ `final_refused`、task `no_result`；
    2. 并发上限拒掉第三条时，拒信逐字含业主原话、`attack_plans` 一行不多；
    3. F2 把前面两条放弃之后，同类的新计划（pC…）就建成了 —— 同一格上限、同一条路径。
    """
    got = _run(tmp_path, monkeypatch, lean="0")
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    refusals = [e for e in reading["events"]
                if e.get("kind") == "agent_step" and e.get("shape") == "final"
                and (e.get("result") or {}).get("final_refused", {}).get("complete") is False]
    assert len(refusals) >= 2, (
        f"只有一个实例的 final 被拒 ⇒ 收工门没有真正读台账："
        f"{[(e.get('role'), e.get('payload')) for e in refusals]}")
    why = " ".join(str((e.get("result") or {}).get("final_refused", {}).get("why") or "")
                   for e in refusals)
    plans = reading["by_key"]
    assert str((plans.get("pA") or {}).get("plan_id") or "") in why, why[:600]
    assert str((plans.get("pI") or {}).get("plan_id") or "") in why, why[:600]
    # F1 那一趟的 task 结论是 no_result（拒收工不是"跑完了"）。
    f_tasks = [t for t in reading["tasks"] if str(t.get("role") or "") == "F"]
    assert [t for t in f_tasks if str(t.get("outcome") or "") == "no_result"], f_tasks
    # 上限那一条：没有落行（八条里没有 pG）。
    assert len(reading["plans"]) == 8, sorted(reading["by_key"])
    assert "pG" not in plans
    # F2 之后同类计划建成了（放弃前面两条 ⇒ 名额腾出来）。
    assert {"pC", "pD", "pE", "pF", "pH", "pI"} <= set(plans), sorted(plans)


# ============================================================ 判据①：一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。"""
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    reading = RC.ledger_identity(got["ws"], got["store"])
    print(f"[一行账] f-plan lean={lean} 真调用={reading['calls']} "
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
    print(f"[会话归口] f-plan lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert problems == [], "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_the_lifecycle_is_the_same_in_both_lean_modes(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档：同一条链照跑，八条计划的终态与收工门读数不变。"""
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
