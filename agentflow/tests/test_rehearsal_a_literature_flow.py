# -*- coding: utf-8 -*-
"""彩排（真路径）A 侧文献全流程：CLI → 真 `LlmSeam` → 真账本 → 判收/提交/清表/收工闸。

## 这条链与真机差在哪（逐项，不许含糊）

| 这一趟用的东西 | 真机 | 这份彩排 |
|---|---|---|
| 入口 | `agentflow start --mode research` | 同一行：`cli.main(["start", "--mode", "research", …])` |
| 执行体 | `_run_spec` → `_exec_role` → `host.wired_llm_conductor` → `LlmBackend` → `AgentLoop.run` | 同一条（一次都没绕开） |
| 派活 | `Conductor.summon`（`M→A` 是 `ALLOWED_EDGES` 里的真边） | 同一条 |
| 角色实现 | `AgentA` 的 `own.search_literature` + A 的工具面 | 同一条（`own.*` 由循环从 A 的动作表现造；`lit.*` / `text.extract` / `fs.read` 全是注册表里的真工具） |
| 判收 | `lit.admit` → `litstage.admit` → `apply_qualification` | 同一条（判收只写 `qualified`，不注册、不发号） |
| 提交 | `lit.admit_all` → `litstage.admit_all`（无号原件 → 批量注册 → 回填 → 带号定稿 → 清表） | 同一条 |
| 收工闸 | `conductor.closing` 工具 → `closing.check_closing` 第八格 | 同一条（M 在真循环里调） |
| 模型缝 | 真 `LlmSeam`（`_agent_seam_factory` / `for_role` / `for_secretary`） | 同一条：构造点一个都没替换 |
| 记账 | 真 `TokenMeter` → `usage_ledger` | 同一条 |
| 出网 | `modelgw.urllib_transport`（HTTP POST） | 只换这一处：回预置的 OpenAI 兼容 JSON |
| 模型 key | 机器上那把 | env `AGENTFLOW_MODEL_API_KEY` 给一个假值（只用来让"配置已就绪"成立） |

## 这条链覆盖的严格时序（Q1，业主口径逐条）

| # | 时序 | 这份彩排的判据（读盘，不看回执的 `ok=True`） |
|---|---|---|
| ① | `lit_candidates` 新增 `qualified` 态（判收=有资格、不注册、无号；`admitted` 仍=已注册必带 `lit_id`） | `_judge_problems`：literature 0 行；候选行 `status=qualified`、`lit_id` 空、`relevance` 非空；`judged_state` 读成"判过" |
| ② | `lit.admit` 判收不注册（`registered=0`，不建 literature 行） | 同上 + 回执 `registered=0` 且 `admitted[].lit_id` 全空；进度报告里 `## 待注册（1 篇）` 且无 `lit:` |
| ③ | 提交时落无号原件 `reports/lit-<rid>.submitted.md`（入库组不带号） | `_full_problems`：原件在盘上；全文没有 `lit:`、没有 `cand:`、没有「槽位 N」、带「有入库资格」 |
| ④ | `lit.admit_all` 只对 `qualified` 行批量注册、`lit_id` 回填同一行 ⇒ qualified→admitted | 回执 `registered=1`；候选行 `status=admitted` 且 `lit_id` 有值；`literature` 恰好 1 行且号相同 |
| ⑤ | 带号定稿 `reports/lit-<rid>.md`（入库组 `lit:NNNNNN`、拒组无号有理由、报告里不得出现 `cand:`） | 定稿的入库区带号、未入库区无号且有受控理由码；全文无 `cand:`；`report_violations(final)` 为空 |
| ⑥ | 清表：归档 `data/lit_candidates/archive-<rid>.jsonl` + 逐行 `cleared_at` / `clear_reason`（不物理删） | 归档在盘上且槽位→号成对；两行都带 `cleared_at` / `clear_reason`；表里无 `pending` |
| ⑦ | 收工闸：`closing` 第八格 `literature_pending`（blocker；读不到 ⇒ unknown） | 清表后 `pass`（`_full_problems`，走 M 的真工具回执 + `check_closing` 直读）；"清表前 `fail` + `delegation_not_cleared`"那一半由 `…_criteria.py` 的 e 守（它把退场补交打桩掉 —— 2026-11-21 ACLEAR2 之后，判完不提交这个状态要靠那个桩才可达） |
| ⑧ | `report_violations` 在两个渲染时刻各跑一次（拦门档） | 两个时刻的报告各自过同一份判据；"真的跑过"由 `…_criteria.py` 的两条负控证明（带槽位号 ⇒ 提交被拦；定稿缺号 ⇒ 清表被拦） |
| ⑨ | 报告过期：判定后自动重渲染；已清表再生成 ⇒ `already_settled` | 判定后那一份重渲染由 `…_criteria.py` 的 `_presubmit_problems`（清表前那一刻，带打桩）与 e 守；已清表的委托再 `write_report` ⇒ `LitStageError(kind="already_settled")` |

## 产品就绪（诚实登记：这条链今天在 HEAD 上跑不完）

本文件不替代产品那一格。Q1 的 `schema` 那一半在 `temp/Q1-fc27-schema-qualified.patch`
里（命中 FC-27 的 schema-migration / eval-criteria，须人编写或逐行走查 + 2 名 reviewer
approve 后 apply）。「没 apply 之前」，`lit.admit` 写 `qualified` 会被
`LitCandidate.validate()` 拒（回执 `kind=unexpected`，错误文本里含 `'qualified'`）⇒
②–⑨ 全都到不了。所以本文件的链判据在那种盘上不装绿：

- 每个判据都会先跑完整一趟（三格因此有对象），再判 `_blocked_reason()`；
- 产品缺 `qualified` 时：断言"这份读数必红"、"红点必须正是 schema 缺 `qualified`"，
  然后 `pytest.xfail(原因)` —— 它不是对缺陷的豁免，而是"已知卡点 + 精确红点"的机器登记；
- 产品补齐之后：`_blocked_reason()` 返回空串，同一批判据原样开始真跑（不需要改本文件）。

## 反真空（在哪、证明什么）

`tests/test_rehearsal_a_literature_flow_criteria.py`（判据文件，不是彩排）：跳过回读、
跳过抽读、打桩回填空、打桩去号、打桩定稿的号、打桩 `judged_state` —— 各自必须让
本文件链判据红。那份文件命中 `rehearsal_contract.FLOW_CRITERIA_FILES`，因为它必须
打桩产品那一格；本文件只替换网线。

## 收工门：走权威门（2026-11-19 业主裁定 ②/③）

M 调 `conductor.closing` 时带全 `project_dir` / `report_path`，所以那一份是权威结论
（`authoritative=True`）：full 链八格全 pass ⇒ `verdict=pass` / `rc=0`；两条负控
（判收-only / skip_submit）⇒ 第八格 `literature_pending` 红、`verdict=fail`、`rc=1`
（改前它们是 rc=0：非权威读数不参与退出码）。漏传这两个参数的交 final 会被受控拒
`closing_not_authoritative`（判据：`tests/test_a_non_authoritative_final_is_refused.py`）。

工作区为什么带一份前序交付物与体例声明：`closing.SUBSTANCE_TABLES` 那五张表本趟
一张都不写（A 的写集只有 `literature` / `lit_candidates`），空工作区永远过不了
`substance`；`_seed_prior_products` 里逐字登记了这件事（与
`tests/test_rehearsal_closing_eight_cells.py::_seed_tables` 同一做法）。验收表刻意不写：
一旦盘上有 `out/paper/ACCEPTANCE-CHECKS.json`，`acceptance` 就按整份研究交付的自动分支
判（`paper_mapping_rows` / `document_body_rows` / `reviewed_current_rows` / 交接模板 /
五条内容判据），那不是文献链的形态 —— 那份形态由 REH8 的十二行彩排覆盖。

## Lean 两档

`AGENTFLOW_LEAN_ENABLED` 开/关各跑一遍：文献链与形式化开关无关，但"两档都干净"必须
自己说出来（关档尤其重要：旧 14 份彩排里关档的链级覆盖是 0）。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Sequence

import pytest

import rehearsal_contract as RC

from agentflow import cli
from agentflow import closing as CL
from agentflow import leanscope as LS
from agentflow import litstage as L
from agentflow import modelgw as MG
from agentflow import schema as S
from agentflow.store import Store

SID = "cc3-a-lit"

#: 本趟委托号 / 两个槽位（新工作区的第一、二号；A 在提示词里读到的是同一对）。
RID = "r-000001"
SLOT_KEEP = "000000"
SLOT_DROP = "000001"

#: 盘上真的是一份 `.txt` 藏书（`extract.extract_text` 的原生分支；不装 PDF 后端）。
#:
#: 2026-11-20（ALITCONTENT）：判收要求「读到正文」，而 `litavail.content_read` 的
#: 判据是「摘要之外至少 500 字」（`MIN_BODY_BEYOND_ABSTRACT`）。所以这份藏书必须
#: 真是一篇"有正文"的稿子 —— 改前它只有两句定义（约 110 字），抽读与 `fs.read`
#: 都照跑，却在最后一步按 `abstract_only` 被拒，于是 ①②–⑨ 全链一起红。
#: 现在这一段把书里的定义、引理与证明都写出来（> 500 字），抽读件里除了摘要
#: 之外有可判的正文；判据本身一个字没松。
TEXT = (
    "An abelian group is a group in which the commutative law holds for every pair of "
    "elements. In additive notation this says a + b = b + a for all a and b; in "
    "multiplicative notation it says ab = ba. The identity element of an abelian group is "
    "unique, and every element has a unique inverse. A subgroup of an abelian group is a "
    "subset that is itself a group under the inherited operation. The first lemma of this "
    "note states that every subgroup of an abelian group is normal: for every element h of "
    "the subgroup and every element g of the group, the conjugate g h g^{-1} again lies in "
    "the subgroup. The proof is a one-line computation. Since the group is abelian we have "
    "g h g^{-1} = h g g^{-1} = h, and h belongs to the subgroup by assumption, so the "
    "conjugate belongs to the subgroup as well. Consequently the left cosets and the right "
    "cosets of the subgroup coincide, which is exactly the definition of a normal subgroup. "
    "The second lemma records the standard consequence for quotients: if the group is "
    "abelian then every quotient by a subgroup is again abelian, because the coset "
    "representatives can be commuted in the quotient operation. The third lemma observes "
    "that the centre of any group contains every element that commutes with all elements, "
    "and in the abelian case the centre is the whole group. Together these three lemmas "
    "give the structural picture used later in the survey: abelian groups have a very "
    "regular subgroup lattice, and the normal subgroups are precisely all subgroups. The "
    "remaining sections of the note work through examples, including the cyclic groups, "
    "the finite abelian groups, and the additive group of a ring, and they check each "
    "example against the lemmas above. The final section discusses why the abelian "
    "hypothesis cannot be dropped: in the symmetric group on three letters the subgroup "
    "generated by a transposition is not normal, so the first lemma fails without "
    "commutativity. That counterexample closes the note and explains the scope of the "
    "results stated here.")

#: 两条候选：一条判收（读过正文）、一条判拒（受控理由码）。`relevance` 是判过的证据。
ENTRIES = [
    {"title": "Abelian groups and their subgroups", "doi": "10.9/abelian-1",
     "provider": "fixture", "year": 2020, "type_code": "J",
     "relevance": "与本次检索相关：给出阿贝尔群子群正规性的标准结论",
     "url": "https://example.invalid/a1"},
    {"title": "A survey of unrelated topics", "doi": "10.9/unrelated-2",
     "provider": "fixture", "year": 2021, "type_code": "J",
     "relevance": "题录相关但内容与本次主题无关（彩排夹具）",
     "url": "https://example.invalid/a2"},
]

#: 多留一条没判的候选（`judged_state` 那一条负控要它：`undecided_candidates` 才有对象）。
EXTRA_ENTRY = {"title": "A third paper nobody judged", "doi": "10.9/unjudged-3",
               "provider": "fixture", "year": 2022, "type_code": "J",
               "relevance": "", "url": "https://example.invalid/a3"}

#: 权威门的两个参数（工具契约：相对工作区；业主 2026-11-19 裁定 ②）。
#:
#: 为什么 M 必须带这两个参数：不带 ⇒ `ClosingReport.authoritative=False`、
#: `report_shape` / `acceptance` / `artifact_ledger` 只能说「没查成」⇒ 那份读数不是
#: "这一趟能不能交"的结论 ⇒ 交 final 时会被受控拒（`closing_not_authoritative`，
#: 判据见 `tests/test_a_non_authoritative_final_is_refused.py`）。彩排照真机形态带全。
PROJECT_DIR = "."
REPORT_PATH = f"reports/lit-{RID}.md"

#: 工作区的前序交付物（`closing.SUBSTANCE_TABLES` 里 `documents` 的那一行）。
#:
#: 为什么要有它：`substance` 问的是"五张实质表里有没有非空的"。这条链本身只写
#: `literature` / `lit_candidates`（A 的写集），这五张表一张都不写 —— 空工作区
#: 永远过不了权威门，而彩排要判的是"权威门这条路"，不是"文献链产出全部实质表"。
#: 所以按 `tests/test_rehearsal_closing_eight_cells.py::_seed_tables` 的同一做法，
#: 把一份前序交付物放进工作区（它与 c9 的 `_workspace` 先种一张概念图同形），
#: 并在 docstring 里如实写明：`substance` 的 pass 来自前序产出，不是本趟产出。
PRIOR_DOC_TITLE = "阿贝尔群文献综述（本工作区的前序交付物）"

#: 验收表的机器可判行 —— 本工作区刻意不写这张表（理由见下面的长注记）。
#:
#: 为什么不留一张验收表（这条不是省事，是口径）：`out/paper/ACCEPTANCE-CHECKS.json`
#: 一旦在盘上，`closing._check_acceptance` 就按整份研究交付的自动分支判它 ——
#: `paper_mapping_rows` / `document_body_rows` / `reviewed_current_rows` /
#: `manuscript_rows`（"交接账本里 N 行全是框架派生的模板"）/ 五条 `content_leg_unmet`，
#: 每一档都要求这份工作区里有 D/E/F/G/H 的产物。这条彩排只跑 A 侧文献链（写集只有
#: `literature` / `lit_candidates`），塞一张验收表只会把 `acceptance` 判红，而红点
#: 与文献链无关 —— 那是 `tests/test_rehearsal_closing_eight_cells.py` 那份"八格全过"
#: 的彩排要覆盖的形态（它有十二行验收表与对应产物）。
#: 没有表时产品的口径是 `pass` + 读数"这个项目没有 ACCEPTANCE-CHECKS.json"（非研究型）。
STYLE_SECTIONS: tuple[str, ...] = ("已入库", "未入库", "待裁")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _rid_of(prompt: str) -> str:
    """从 A 的提示词里读这一次委托号（读不到就退回新工作区的第一号）。"""
    hit = re.search(r'"request_id":\s*"(r-\d{6})"', prompt)
    return hit.group(1) if hit else RID


class _Wire:
    """预置的网络传输层替身（与 `modelgw.urllib_transport` 同签名）。

    它不是缝：预算闸 / 账本 / `llm_call` 事件 / ambient 解析全在真 `LlmSeam` 上；
    这里只回答"上游那一端收到了什么、回了什么"。剧本按角色与提示词分派。
    """

    def __init__(self, *, skip: Sequence[str] = (), pending_extra: bool = False) -> None:
        self.skip = frozenset(skip)
        self.pending_extra = bool(pending_extra)
        self.bodies: list[dict[str, Any]] = []
        self._steps: dict[str, int] = {}
        self._done: list[str] = []

    # ------------------------------------------------------------ 剧本
    def _a_script(self, rid: str) -> list[str]:
        """A 这一趟的逐步动作（`skip` 里的那几步是负控要摘掉的那一格）。"""
        entries = list(ENTRIES) + ([EXTRA_ENTRY] if self.pending_extra else [])
        steps = {
            "search": _json({"tool": "own.search_literature",
                             "args": {"topic": "abelian group", "mode": "topical",
                                      "description": "abelian group 与文献入库资格"}}),
            "stage": _json({"tool": "lit.stage_add",
                            "args": {"request_id": rid, "entries": entries}}),
            "readback": _json({"tool": "lit.stage_list", "args": {"request_id": rid}}),
            "extract": _json({"tool": "text.extract",
                              "args": {"path": "books/notes.txt",
                                       "lit_id": f"cand:{SLOT_KEEP}"}}),
            "read": _json({"tool": "fs.read",
                           "args": {"path": f"out/texts/cand-{SLOT_KEEP}.txt"}}),
            "admit": _json({"tool": "lit.admit",
                            "args": {"request_id": rid,
                                     "items": [{"slot": SLOT_KEEP,
                                                "availability": "readable"}]}}),
            "reject": _json({"tool": "lit.stage_reject",
                             "args": {"slot": SLOT_DROP,
                                      "reason_code": "rejected_off_topic",
                                      "note": "与本次检索无关（彩排夹具）"}}),
            "submit": _json({"tool": "lit.admit_all", "args": {"request_id": rid}}),
        }
        order = ("search", "stage", "readback", "extract", "read", "admit",
                 "reject", "submit")
        skipped = set(self.skip) | ({"read"} if "extract" in self.skip else set())
        return [steps[name] for name in order if name not in skipped]

    def _m_script(self, prompt: str) -> str:
        """M：派 A → 等 A 回来 → 销号 → 调收工门 → final。"""
        index = self._steps.get("M", 0)
        self._steps["M"] = index + 1
        if index == 0:
            return _json({"summon": {"role": "A",
                                     "task": "检索并收编 abelian group 文献"}})
        todo = [n for n in re.findall(r'"roster_name":\s*"([A-Z]\d*)"', prompt)
                if n not in self._done]
        if todo:
            self._done.append(todo[0])
            return _json({"tool": "conductor.retire_child",
                          "args": {"child_name": todo[0], "reason": "收完了"}})
        if not self._steps.get("M:closing"):
            self._steps["M:closing"] = 1
            # 权威门的两个参数都带上（业主 2026-11-19 裁定 ②）：不带 ⇒ 这一份读数
            # 不是"这一趟能不能交"的结论 ⇒ 交 final 时会被受控拒。
            return _json({"tool": "conductor.closing",
                          "args": {"project_dir": PROJECT_DIR,
                                   "report_path": REPORT_PATH,
                                   "goal": "文献入库这一趟", "goal_met": True,
                                   "basis": "A 已提交（或停在该停的地方）",
                                   "task_list": [{"what": "文献链", "state": "done"}]}})
        return _json({"final": "M 收工", "evidence": []})

    def _a_step(self, index: int, prompt: str) -> str:
        script = self._a_script(_rid_of(prompt))
        if index < len(script):
            return script[index]
        return _json({"final": "A 的结论：逐条判完，按流程提交", "evidence": []})

    def _reply(self, system: str, prompt: str) -> str:
        head = system.lstrip()
        hit = re.match(r"你是「秘书」的判断面（类别：([a-z_]+)）", head)
        if hit:
            table = {
                "statement_aesthetic": {"decision": "T2", "reason": "彩排",
                                        "basis": ["夹具"]},
                "proposition_identity": {"decision": "same", "reason": "彩排",
                                         "basis": ["夹具"], "canonical_name": "群",
                                         "same_as": "", "route": "", "condition": "夹具",
                                         "conclusion": "夹具"},
                "proof_kind": {"decision": "same", "reason": "彩排", "basis": ["夹具"],
                               "same_path": 1},
                "dispatch_fit": {"decision": "这一件能做", "reason": "彩排",
                                 "basis": ["夹具"]},
            }
            return _json(table.get(hit.group(1),
                                   {"decision": "可派", "reason": "彩排", "basis": ["夹具"]}))
        if head.startswith("你是「命题形态闸」"):
            return _json({"well_formed": True, "conditions": "夹具", "conclusion": "夹具",
                          "problems": [], "decision": "形态合规", "refused": "",
                          "reason": "彩排"})
        hit = re.match(r"你是 ([A-Z]) 号角色", head)
        if hit:
            role = hit.group(1)
            if role == "M":
                return self._m_script(prompt)
            index = self._steps.get(role, 0)
            self._steps[role] = index + 1
            return self._a_step(index, prompt)
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
        self.bodies.append({"system": system[:200], "prompt": prompt, "text": text})
        return 200, json.dumps({"choices": [{"message": {"content": text},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 8, "completion_tokens": 8}},
                               ensure_ascii=False)


# ============================================================ 夹具


#: 前序交付物那一行的 `content_sha256`（`documents` 的必填格；值本身没有含义）。
PRIOR_DOC_SHA = "b" * 64


def _seed_prior_products(store: Store) -> None:
    """把前序交付物放进工作区（`substance` 那五张表里 `documents` 的一行）。

    如实登记（不许把它读成"本趟产出"）：这条链的写集只有 `literature` /
    `lit_candidates`，`closing.SUBSTANCE_TABLES` 的五张表它一张都不写。空工作区永远
    过不了权威门，所以这一趟像 `tests/test_rehearsal_closing_eight_cells.py` 一样带一份
    前序产出进来（那份彩排把八格的证据全部先种好，这条只种 `substance` 需要的那一格）。
    它是一条真的 `documents` 行（走产品写口 `store.tx` 落盘、`Document.validate()`
    过一遍），断言的是"这一类项目在文献链跑完时盘上该有什么形态"，不是"文献链产出了它"。
    """
    row = S.Document(
        doc_id="000000", kind="survey", title=PRIOR_DOC_TITLE,
        status="accepted", content_sha256=PRIOR_DOC_SHA,
        created_at="2026-11-19T12:00:00+00:00",
        updated_at="2026-11-19T12:00:00+00:00",
        review_verdict="成立", reviewed_at="2026-11-19T12:00:00+00:00",
        reviewed_by="agent-H",
        sections=[{"heading": "文献现状",
                   "body": "阿贝尔群子群正规性的标准结论见已入库文献。"}],
        claims=[{"claim_id": "c1", "section": "文献现状", "evidence_kind": "cross_check",
                 "text": "阿贝尔群的每个子群都是正规子群",
                 "citations": ["lit:000000"],
                 "disclaimer": "文献综述，不构成本项目的证明"}],
    )
    row.validate()
    with store.tx("documents", actor="rehearsal-a") as tx:
        tx.upsert("documents", row.to_dict())


def _seed_report_style(root: pathlib.Path) -> None:
    """M 的体例声明（`report_shape` 那格的"你说的和你写的一致"）。

    `out/review/REPORT-STYLE.json` 写的是 `STYLE_SECTIONS` —— 那三节正是
    `litstage.write_report` 真会写出来的小标题（`## 已入库` / `## 未入库` / `## 待裁`），
    门逐节核"声明的节有没有出现在报告的标题行里"，缺一节才红。不声明也能过（读数里
    如实写 `none`），写它是为了把这条判据也走一遍。
    """
    style = root / "out" / "review" / "REPORT-STYLE.json"
    style.parent.mkdir(parents=True, exist_ok=True)
    style.write_text(_json({"sections": list(STYLE_SECTIONS)}),
                     encoding="utf-8", newline="\n")


def _workspace(base: pathlib.Path) -> Store:
    """真工作区：`books/` 下一本真 `.txt` 藏书；`--provider fixture` 的候选表是空的。"""
    st = Store(base / "ws")
    st.init()
    root = pathlib.Path(st.root)
    (root / "books").mkdir(parents=True, exist_ok=True)
    (root / "books" / "notes.txt").write_text(TEXT, encoding="utf-8")
    (root / "demo" / "fixtures").mkdir(parents=True, exist_ok=True)
    (root / "demo" / "fixtures" / "candidates.json").write_text("[]", encoding="utf-8")
    # 权威门要的两类产物（见 `_seed_prior_products` / `_seed_report_style`）。
    _seed_prior_products(st)
    _seed_report_style(root)
    return st


def _run(base: pathlib.Path, monkeypatch: pytest.MonkeyPatch, *,
         lean: str = "0", skip: Sequence[str] = (), pending_extra: bool = False,
         sid: str = SID) -> dict[str, Any]:
    """从 CLI 入口真跑一趟；只替换出网那一层（+ 一个假 key）。"""
    st = _workspace(base)
    wire = _Wire(skip=skip, pending_extra=pending_extra)
    monkeypatch.setenv("AGENTFLOW_MODEL_API_KEY", "rehearsal-fake-key-never-used")
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", str(lean))
    monkeypatch.setattr(MG, "urllib_transport", wire)
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main([
                "start", "--mode", "research", "--root", str(st.root),
                "--sid", sid, "--provider", "fixture", "--subagents",
                "--task", "检索并收编 abelian group 文献（逐条判、提交清表）",
                "--max-steps", "16",
            ])
    except SystemExit as exc:                     # `cli.main` 正常是 return，不是 raise
        rc = int(exc.code or 0)
    return {"rc": int(rc), "ws": pathlib.Path(st.root), "store": Store(st.root),
            "wire": wire, "stdout": out.getvalue(), "stderr": err.getvalue(),
            "events": _events(pathlib.Path(st.root))}

def _events(ws: pathlib.Path) -> list[dict]:
    """这一趟的会话事件（不按 sid 过滤：任何一条都算这一趟的审计面）。"""
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


def _tool_data(events: list[dict], *, role: str, tool: str) -> dict:
    data = _tool_result(events, role=role, tool=tool).get("data")
    return dict(data) if isinstance(data, dict) else {}


def _rows(store: Store, table: str) -> list[dict]:
    return [dict(r) for r in store.rows(table)]


def _report(ws: pathlib.Path, name: str) -> str:
    path = ws / "reports" / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _blocked_reason() -> str:
    """产品侧就绪读数：空串 = 这条链该真跑；非空 = 已知卡点（逐字给出补丁与门）。"""
    if "qualified" in S.CANDIDATE_STATUSES:
        return ""
    return (
        "产品侧还没完善好（这条链今天在 HEAD 上跑不完）：`schema.CANDIDATE_STATUSES` "
        f"还没有 `qualified`（现值 {S.CANDIDATE_STATUSES}）⇒ `lit.admit` 判收写 "
        "`qualified` 会被 `LitCandidate.validate()` 拒（回执 kind=unexpected，错误文本含 "
        "'qualified'）⇒ ②–⑨ 全都到不了。修复不在本路："
        "`temp/Q1-fc27-schema-qualified.patch` 命中 FC-27（schema-migration / "
        "eval-criteria），须人编写或人逐行走查 + 2 名 reviewer approve 后 apply；"
        "apply 之后这份彩排自己开始真跑（不需要改它）。")


def _blockage_reading(got: dict[str, Any]) -> str:
    """已知卡点在会话里的原文（不是"红了就算"：红点必须正是 schema 缺 `qualified`）。"""
    try:
        admit = _tool_result(got["events"], role="A", tool="lit.admit")
    except AssertionError:
        return ""
    meta = dict(admit.get("meta") or {})
    error = str(admit.get("error") or "")
    if meta.get("kind") == "unexpected" and "'qualified'" in error:
        return error
    return ""


def _expect(problems: Sequence[str], got: dict[str, Any], *, label: str) -> None:
    """判据收尾：产品就绪 ⇒ 必须通；产品缺 `qualified` ⇒ 必须红、且红点可点名，再 xfail。"""
    reason = _blocked_reason()
    if not reason:
        assert not problems, f"{label}：\n- " + "\n- ".join(problems)
        return
    assert problems, (
        f"{label}：产品缺 `qualified`，这份读数却读成了通 —— 判据是橡皮图章")
    assert _blockage_reading(got), (
        f"{label}：红了，但红点不是已知的那一格（schema 缺 `qualified`）。"
        f"会话里 `lit.admit` 的回执：{_tool_result(got['events'], role='A', tool='lit.admit')}")
    pytest.xfail(reason)


# ============================================================ ① ② 判收


def _judge_problems(got: dict[str, Any]) -> list[str]:
    """①②：判收之后（本趟只判收、不提交）：有资格、不注册、没有号。"""
    problems: list[str] = []
    st, ws = got["store"], got["ws"]
    lit = _rows(st, "literature")
    if lit:
        problems.append(f"① 判收之后 `literature` 应 0 行，实得 {len(lit)} 行："
                        f"{[(r.get('lit_id'), r.get('title')) for r in lit]}")
    cands = _rows(st, "lit_candidates")
    if len(cands) != 2:
        problems.append(f"① 本趟应只有 2 条候选行（暂存两条、判收一条），实得 "
                        f"{len(cands)} 行：{[(r.get('slot'), r.get('status')) for r in cands]}")
        return problems
    by_slot = {str(r.get("slot")): r for r in cands}
    row = by_slot.get(SLOT_KEEP) or {}
    if str(row.get("status") or "") != "qualified":
        problems.append(f"① 判收后候选行的 status 应为 `qualified`，实得 "
                        f"{row.get('status')!r}（lit_id={row.get('lit_id')!r}）")
    if str(row.get("lit_id") or "").strip():
        problems.append(f"② 判收不注册 ⇒ `lit_id` 必须空，实得 {row.get('lit_id')!r}")
    if not str(row.get("relevance") or "").strip():
        problems.append("① `qualified` 行必须带 relevance（判过的证据），实得空串")
    if L.judged_state(row) != "admitted":
        problems.append(f"① `judged_state` 应把 qualified 读成「判过」，实得 "
                        f"{L.judged_state(row)!r}")
    other = by_slot.get(SLOT_DROP) or {}
    if str(other.get("status") or "") != "pending":
        problems.append(f"① 本趟没判的那一条应仍是 `pending`，实得 {other.get('status')!r}")
    admit = _tool_result(got["events"], role="A", tool="lit.admit")
    data = _tool_data(got["events"], role="A", tool="lit.admit")
    if not admit.get("ok"):
        problems.append(f"② `lit.admit` 回执不是 ok：{admit.get('error')!r}")
    if int(data.get("registered") or 0) != 0:
        problems.append(f"② 判收回执 `registered` 应为 0，实得 {data.get('registered')!r}")
    ids = [str(x.get("lit_id") or "") for x in (data.get("admitted") or [])]
    if ids and any(ids):
        problems.append(f"② 判收回执里不应有正式号，实得 {ids}")
    draft = _report(ws, f"lit-{RID}.md")
    if not draft:
        problems.append(f"② 判收后应有一份进度报告 `reports/lit-{RID}.md`，盘上没有")
    else:
        if "## 待注册（1 篇）" not in draft:
            problems.append("② 进度报告缺 `## 待注册（1 篇）`（判收未注册那一条）")
        if "`lit:" in draft:
            problems.append("② 进度报告里出现了正式号（判收这一刻还没有号）")
        bad = L.report_violations(draft, phase="draft")
        if bad:
            problems.append(f"② 进度报告没过报告判据：{bad}")
    return problems


def test_judging_is_qualified_not_registered(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """①+②：A 判收一条 ⇒ 候选行 `qualified`、`lit_id` 空、`literature` 0 行、回执 `registered=0`。

    这一步是 Q1 严格时序的分水岭：判收不是注册。它只改状态与证据，一个号都不发；
    号由提交那一刻的 `lit.admit_all` 批量发。若这一格变成"判收即入库"，③ 的无号原件
    就失去对象（`## 已入库` 里会直接出现号），回填也就没有可指的映射。

    ## 它是负控（2026-11-19 裁定 ③）

    只判收、不交 ⇒ 收工门第八格 `literature_pending` 红（`undecided_candidates`：
    暂存表里还有没判的那一条）⇒ 权威结论 `fail` ⇒ 运行退出码 1。改前这一趟是
    rc=0（非权威读数不参与退出码）—— 那正是本轮要钉掉的"静默 rc=0"。
    """
    got = _run(tmp_path, monkeypatch, lean="0", skip=("reject", "submit"))
    assert got["rc"] == 1, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    honest = _honest_failure_problems(got, red=["literature_pending"],
                                      codes=["undecided_candidates"])
    assert not honest, "负控读数不对：\n- " + "\n- ".join(honest)
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」")
    assert [e for e in _events(got["ws"]) if e.get("kind") == "llm_call"], (
        "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam")
    _expect(_judge_problems(got), got, label="①② 判收不注册")


# ============================================================ ③–⑧ 提交 + 清表


def _submitted_problems(got: dict[str, Any]) -> list[str]:
    """③：交报告那一刻的无号原件（入库组不带号、报告里没有临时号）。"""
    problems: list[str] = []
    snap = _report(got["ws"], f"lit-{RID}.submitted.md")
    if not snap:
        return [f"③ 无号原件 `reports/lit-{RID}.submitted.md` 不在盘上"]
    if "`lit:" in snap:
        problems.append("③ 交报告原件里出现了正式号（这一刻还没有号）")
    if "cand:" in snap:
        problems.append("③ 交报告原件里出现了 `cand:` 临时号（业主口径：写报告时不用临时号）")
    if re.search(r"槽位\s*\d{4,6}", snap):
        problems.append("③ 交报告原件里出现了「槽位 N」临时号")
    if "有入库资格" not in snap:
        problems.append("③ 交报告原件的入库组没有逐字写「有入库资格」")
    bad = L.report_violations(snap, phase="submitted")
    if bad:
        problems.append(f"③ 无号原件没过 `report_violations(phase=submitted)`：{bad}")
    return problems


def _final_problems(got: dict[str, Any]) -> list[str]:
    """⑤：带号定稿（入库组带号、拒组无号有理由、全文无临时号）。"""
    problems: list[str] = []
    final = _report(got["ws"], f"lit-{RID}.md")
    if not final:
        return [f"⑤ 定稿 `reports/lit-{RID}.md` 不在盘上"]
    cands = [r for r in _rows(got["store"], "lit_candidates")
             if str(r.get("slot")) == SLOT_KEEP]
    lit_ids = sorted({str(r.get("lit_id") or "") for r in _rows(got["store"], "literature")}
                     - {""})
    if len(lit_ids) != 1:
        problems.append(f"④ `literature` 应恰好 1 行带号，实得 {lit_ids}")
    elif f"`lit:{lit_ids[0]}`" not in final:
        problems.append(f"⑤ 定稿的入库区没有回填后的号 `lit:{lit_ids[0]}`")
    admitted = final.split("## 已入库", 1)[1].split("## 待注册", 1)[0] \
        if "## 已入库" in final else ""
    rejected = final.split("## 未入库", 1)[1].split("## 待裁", 1)[0] \
        if "## 未入库" in final else ""
    if "`lit:" not in admitted:
        problems.append("⑤ 定稿的入库区没有一条带 `lit:`")
    if "`lit:" in rejected:
        problems.append("⑤ 定稿的未入库区出现了正式号（被拒的没有号）")
    if "《A survey of unrelated topics》" not in rejected:
        problems.append("⑤ 定稿的未入库区没有那一条被拒的文献信息")
    if "理由：rejected_off_topic" not in rejected:
        problems.append("⑤ 定稿的未入库区没有受控理由码 `rejected_off_topic`")
    if "cand:" in final:
        problems.append("⑤ 定稿里出现了 `cand:` 临时号")
    bad = L.report_violations(final, phase="final", blocking=True)
    if bad:
        problems.append(f"⑤ 定稿没过 `report_violations(phase=final, blocking=True)`：{bad}")
    if cands and not str(cands[0].get("lit_id") or ""):
        problems.append("④ 候选行的 `lit_id` 没有回填")
    return problems


def _cleared_problems(got: dict[str, Any]) -> list[str]:
    """⑥：清表 = 归档 + 逐行标记（不物理删）⇒ qualified→admitted、无 pending。"""
    problems: list[str] = []
    st, ws = got["store"], got["ws"]
    cands = _rows(st, "lit_candidates")
    archive = ws / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    if not archive.is_file():
        problems.append(f"⑥ 归档 `data/lit_candidates/archive-{RID}.jsonl` 不在盘上")
    else:
        lines = [ln for ln in archive.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(lines) != 2:
            problems.append(f"⑥ 归档应有 2 行（一收一拒），实得 {len(lines)} 行")
        else:
            pairs = {str(json.loads(ln).get("slot")): str(json.loads(ln).get("lit_id") or "")
                     for ln in lines}
            if not pairs.get(SLOT_KEEP):
                problems.append(f"⑥ 归档里判收那一槽没有 `lit_id`：{pairs}")
            if pairs.get(SLOT_DROP):
                problems.append(f"⑥ 归档里判拒那一槽不该有号：{pairs}")
    live = _rows(st, "literature")
    if not live:
        problems.append("④ `literature` 应已注册 1 行，实得 0 行")
    admitted = [r for r in cands if str(r.get("slot")) == SLOT_KEEP]
    if admitted:
        row = admitted[0]
        if str(row.get("status") or "") != "admitted":
            problems.append(f"④ 判收那一行提交后应为 `admitted`，实得 {row.get('status')!r}")
        live_id = str(live[0].get("lit_id") or "") if live else ""
        if str(row.get("lit_id") or "") != live_id:
            problems.append(f"④ 候选行上的 `lit_id` 与 `literature` 行不一致："
                            f"{row.get('lit_id')!r} / {live_id!r}")
    for row in cands:
        if not str(row.get("cleared_at") or "").strip():
            problems.append(f"⑥ 槽位 {row.get('slot')} 没有 `cleared_at`（表没清）")
        if not str(row.get("clear_reason") or "").strip():
            problems.append(f"⑥ 槽位 {row.get('slot')} 没有 `clear_reason`")
        if L.judged_state(row) == "pending":
            problems.append(f"⑥ 槽位 {row.get('slot')} 清表后仍是 pending")
    if len(cands) != 2:
        problems.append(f"⑥ 清表不物理删 ⇒ 表里应仍有 2 行，实得 {len(cands)} 行")
    return problems


def _closing_problems(got: dict[str, Any], *, want: str) -> list[str]:
    """⑦：收工闸第八格（`want="pass"` 清表后 / `"fail"` 清表前）。"""
    problems: list[str] = []
    events = got["events"]
    try:
        data = _tool_data(events, role="M", tool="conductor.closing")
    except AssertionError as exc:
        return [f"⑦ {exc}"]
    status = dict(data.get("status") or {})
    got_status = str(status.get("literature_pending") or "")
    if got_status != want:
        problems.append(f"⑦ M 的 `conductor.closing` 里 `literature_pending` 应为 "
                        f"{want!r}，实得 {got_status!r}（findings="
                        f"{[(f.get('check'), f.get('code')) for f in data.get('findings') or []]}）")
    rep = CL.check_closing(got["store"], checks=("literature_pending",))
    if str(rep.status.get("literature_pending") or "") != want:
        problems.append(f"⑦ `closing.check_closing` 直读应为 {want!r}，实得 "
                        f"{rep.status.get('literature_pending')!r}")
    return problems


def closing_verdict_of(got: dict[str, Any]) -> dict[str, Any]:
    """M 那一次 `conductor.closing` 回执里的那一份权威结论（`readings.verdict`）。

    判据本体只有一份：`rehearsal_contract.closing_verdict`（c9 / c10 读同一份）。
    """
    return RC.closing_verdict(got["ws"])


def _authoritative_problems(got: dict[str, Any]) -> list[str]:
    """权威门（业主 2026-11-19 裁定 ②/③）：full 链必须真的过了权威门。

    四条逐字：`verdict == "pass"` / `authoritative is True` / `exit_code == 0` /
    八格逐格 `pass`（格子名单取自产品自己的 `DEFAULT_CHECKS`）。
    判据本体在 `rehearsal_contract.authoritative_problems`。
    """
    return RC.authoritative_problems(closing_verdict_of(got), allow_na=("acceptance",))


def _honest_failure_problems(got: dict[str, Any], *, red: Sequence[str],
                             codes: Sequence[str] = ()) -> list[str]:
    """负控（判收-only / skip_submit 等）：如实断言 `verdict=fail`、`rc==1`、红格点名。

    业主 2026-11-19 裁定 ③：「判收-only / skip_submit 等负控 ⇒ 如实断言 verdict=fail +
    rc==1 + 红格点名」。判据本体在 `rehearsal_contract.authoritative_failure_problems`。
    """
    return RC.authoritative_failure_problems(
        got.get("rc", -1), closing_verdict_of(got), red=red, codes=codes,
        na=("acceptance",))


def _full_problems(got: dict[str, Any]) -> list[str]:
    """③④⑤⑥⑦(pass)⑧：提交与清表这一段的盘上终态。"""
    problems: list[str] = []
    problems += _submitted_problems(got)
    problems += _final_problems(got)
    problems += _cleared_problems(got)
    problems += _closing_problems(got, want="pass")
    # ④ 回执读数：注册了几条、映射是不是同一条
    try:
        submit = _tool_data(got["events"], role="A", tool="lit.admit_all")
    except AssertionError as exc:
        problems.append(f"④ {exc}")
        return problems
    if int(submit.get("registered") or 0) != 1:
        problems.append(f"④ `lit.admit_all` 的 `registered` 应为 1，实得 "
                        f"{submit.get('registered')!r}")
    got_ids = [str(x.get("lit_id") or "") for x in (submit.get("admitted") or [])]
    live_ids = sorted({str(r.get("lit_id") or "") for r in _rows(got["store"], "literature")}
                      - {""})
    if got_ids != live_ids:
        problems.append(f"④ 回执里的映射 {got_ids} 与 `literature` 的号 {live_ids} 不一致")
    return problems


def test_the_full_a_flow_runs_from_the_cli_with_only_the_wire_replaced(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """③④⑤⑥⑦(pass)⑧：判收 → 无号原件 → 批量注册回填 → 带号定稿 → 清表 → 收工门 pass。

    判据全部读盘：原件里一个号都没有、定稿的入库组带号、拒组只留文献信息与受控理由码、
    归档里槽位↔号成对、每一行都有 `cleared_at`、表里没有 pending、第八格 pass。
    它同时钉住「报告里不许出现 `cand:`」这条去号处理（原件与定稿各查一次）。
    """
    got = _run(tmp_path, monkeypatch, lean="0")
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    assert got["wire"].bodies, "出网层一次都没被调到 ⇒ 这一趟没有真模型调用"
    assert MG.urllib_transport is got["wire"], "出网层没被替换（这一条会打真网络）"
    assert cli._agent_seam_factory.__module__ == "agentflow.cli", (
        "缝工厂被整体替换了 —— 这份彩排的承诺是「只换网线」，不是「换掉造缝的那一层」")
    live = [e for e in got["events"] if e.get("kind") == "llm_call"]
    assert live, "会话里一条 llm_call 都没有 ⇒ 走的不是真 LlmSeam"

    problems = _full_problems(got)
    _expect(problems, got, label="③–⑧ 提交 + 清表 + 收工闸")
    # ---- 权威门（2026-11-19 裁定 ②/③）：pass / authoritative / rc==0 / 八格逐格 pass
    gate_problems = _authoritative_problems(got)
    assert not gate_problems, "权威门读数不对：\n- " + "\n- ".join(gate_problems)

    # ---- 钱：账本有行、无主为 0、没有悬空号、逐分相等
    from agentflow.modelcost import reconcile_usage

    money = reconcile_usage(got["store"])
    assert money["usage_ledger_rows"] > 0, money
    assert money["unattributed"]["count"] == 0, money["unattributed"]
    assert money["dangling"] == [], money["dangling"]
    assert money["equal"] is True, money

    # ---- ⑨ 已清表再生成 ⇒ already_settled（清表之后报告是交付物，不再重渲染）
    if not _blocked_reason():
        with pytest.raises(L.LitStageError) as caught:
            L.write_report(got["store"], RID, phase="final")
        assert caught.value.kind == "already_settled", caught.value.kind


def test_a_script_that_skips_the_submit_is_cleared_by_the_framework_at_exit(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥⑦⑨(退场补交)：剧本里摘掉 `lit.admit_all` ⇒ 框架在 A 这一拍退场时自己提交。

    ## 2026-11-21（ACLEAR2）之前这条是负控，之后它是正控

    改前："判完不提交"是一个可达状态 —— 全表判完（qualified + rejected）、行上没有
    `cleared_at`、盘上没有归档，于是收工门第八格以 `delegation_not_cleared` 拦、rc=1。
    真机 `projects/lp-ball-15` 证明那个状态真的会发生：A 的 221 步里 `own.run_once`
    被调了 0 次，模型直接把判收做完就走，判完没清表的三个委托留到了收工门。

    修法（ACLEAR 的同一份自驱，接线补在 `agent_loop.run()` 的退场段）之后，这一形
    在产品里不再可达：只要这一拍退场，框架就自己 `lit.admit_all` 掉已判完的委托。
    所以这条彩排改为钉修法本身的读数：只摘掉剧本里的提交，行上照样有
    `cleared_at`、归档照样在盘上、收工门第八格 pass。

    那一条负控没有丢：它搬到了
    `test_rehearsal_a_literature_flow_criteria.py::test_skipping_the_submit_leaves_the_closing_gate_red`
    —— 同一个 CLI 路、同一个缝，先把退场自交的接线打桩掉，再断言"不提交 ⇒ 门红"。
    两份合起来才是完整的那一对：框架会补交；而没人补交时门照样拦。
    """
    got = _run(tmp_path, monkeypatch, lean="0", skip=("submit",))
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    st = got["store"]
    cands = _rows(st, "lit_candidates")
    states = {str(r.get("slot")): str(r.get("status") or "") for r in cands}
    assert states.get(SLOT_KEEP) == "admitted", states
    assert states.get(SLOT_DROP) == "rejected", states
    assert all(str(r.get("cleared_at") or "").strip() for r in cands), cands
    archive = got["ws"] / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    assert archive.is_file(), "退场补交了，归档却不在盘上"
    assert len([ln for ln in archive.read_text(encoding="utf-8").splitlines()
                if ln.strip()]) == len(cands), archive.read_text(encoding="utf-8")
    lit = _rows(st, "literature")
    assert len(lit) == 1, [(r.get("lit_id"), r.get("title")) for r in lit]
    rep = CL.check_closing(st, checks=("literature_pending",))
    assert rep.status["literature_pending"] == "pass", rep.to_dict()
    # ⑨ 的前半句仍然可读：报告是判定之后重渲染出来的那一份（待裁 0 / 未入库 1），
    # 且已入库那一条带着正式号（怎么渲染的由判据文件的 `_presubmit_problems` 守）。
    final = _report(got["ws"], f"lit-{RID}.md")
    assert final, f"⑨ 报告 `reports/lit-{RID}.md` 不在盘上"
    assert "## 待裁（0 条）" in final, final[:600]
    assert "## 未入库（1 篇）" in final, final[:600]
    assert "`lit:" in final, final[:600]
    assert "cand:" not in final, final[:600]


def _presubmit_problems(got: dict[str, Any]) -> list[str]:
    """⑥(未清表) + ⑦(fail) + ⑨(判定后重渲染)。"""
    problems: list[str] = []
    st = got["store"]
    cands = _rows(st, "lit_candidates")
    if _rows(st, "literature"):
        problems.append("⑥ 还没提交 ⇒ `literature` 应 0 行，实得 "
                        f"{[(r.get('lit_id'), r.get('title')) for r in _rows(st, 'literature')]}")
    archive = got["ws"] / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    if archive.is_file():
        problems.append("⑥ 还没提交 ⇒ 归档不该在盘上")
    if any(str(r.get("cleared_at") or "").strip() for r in cands):
        problems.append("⑥ 还没提交 ⇒ 行上不该有 `cleared_at`")
    states = {str(r.get("slot")): str(r.get("status") or "") for r in cands}
    if states.get(SLOT_KEEP) != "qualified":
        problems.append(f"① 判收那一行应为 qualified，实得 {states.get(SLOT_KEEP)!r}")
    if states.get(SLOT_DROP) != "rejected":
        problems.append(f"① 判拒那一行应为 rejected，实得 {states.get(SLOT_DROP)!r}")
    # ⑨：进度报告在判收之后写过，判拒之后必须被重渲染（待裁 0、未入库 1）
    draft = _report(got["ws"], f"lit-{RID}.md")
    if not draft:
        problems.append(f"⑨ 进度报告 `reports/lit-{RID}.md` 不在盘上（判定后应重渲染）")
    else:
        if "## 待裁（0 条）" not in draft:
            problems.append("⑨ 判拒之后进度报告没有重渲染：仍写着有待裁的行")
        if "## 未入库（1 篇）" not in draft:
            problems.append("⑨ 重渲染后的进度报告里未入库组不是 1 篇")
        if "## 待注册（1 篇）" not in draft:
            problems.append("⑨ 重渲染后的进度报告里待注册组不是 1 篇")
        if "`lit:" in draft:
            problems.append("⑨ 进度报告里出现了正式号（还没提交）")
        if "cand:" in draft:
            problems.append("⑨ 进度报告里出现了 `cand:`")
    problems += _closing_problems(got, want="fail")
    return problems


# ============================================================ 判据①：每笔真调用一行账


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_real_call_has_exactly_one_ledger_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据①：这一趟的每一次真调用，`usage_ledger` 里有且只有一行（Lean 开/关各一遍）。

    读数是逐笔的：`llm_call` 事件数 = 出网层真的被调到的次数 = 模型调用级的账本行数；
    每一笔 `charged` 的 `usage_id` 指到一行，行上的 `(role, task_id, call_index)` 与
    事件逐字对上；`duplicate` 为 0（那一档的语义是"这次真调用被判成记过了 ⇒ 静默不记"）。
    """
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
    assert not problems, "判据①红：\n- " + "\n- ".join(problems)


# ============================================================ 判据②：会话归口


@pytest.mark.parametrize("lean", ["1", "0"])
def test_every_llm_call_lands_in_this_runs_session(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, lean: str) -> None:
    """判据②：这一趟所有 `llm_call` 事件都落在本趟 `sid`，缺省会话 0 条。

    三格按 ambient task 归口（账本 `task_id`），不按会话文件归口 —— 一条没有 `sid`
    的缝照样记对账、照样让三格绿，而它的审计事件全落在缺省会话上。所以会话归口
    单独判，对象是会话文件，不是账本。
    """
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    split = RC.session_split(got["ws"], SID)
    print(f"[会话归口] lean={lean} 本趟={len(split['in_run'])} "
          f"别处={len(split['elsewhere'])} 会话={sorted(split['by_session'])}")
    assert split["calls"], "这一趟一次真调用都没有 ⇒ 判据没有对象（不是干净）"
    problems = RC.session_problems(split)
    assert not problems, "判据②红：\n- " + "\n- ".join(problems)


# ============================================================ Lean 两档


@pytest.mark.parametrize("lean,verdict,hidden", [("1", "on", False), ("0", "off", True)])
def test_the_chain_runs_in_both_lean_modes_and_l_is_isolated_when_off(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        lean: str, verdict: str, hidden: bool) -> None:
    """Lean 开/关两档：同一条链照跑，且关档下 L 在名册里不存在。

    文献链与形式化开关无关，但"两档都干净"必须自己说出来（旧 14 份彩排里关档的
    链级覆盖是 0 —— 只跑一档时，另一档的绿没有判据看着）。
    """
    got = _run(tmp_path, monkeypatch, lean=lean)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-1500:], got["stderr"][-1500:])
    reading = LS.lean_reading()
    assert reading.verdict == verdict, reading.to_dict()
    assert LS.is_hidden("L") is hidden, (lean, reading.to_dict())
    roles = set(LS.visible_roles(S.ROLES))
    assert ("L" in roles) is (not hidden), sorted(roles)
    _expect(_full_problems(got), got, label=f"Lean {verdict} 档的完整链")
    gate_problems = _authoritative_problems(got)
    assert not gate_problems, (f"Lean {verdict} 档的权威门读数不对：\n- "
                               + "\n- ".join(gate_problems))


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
