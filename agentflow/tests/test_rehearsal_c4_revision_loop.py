# -*- coding: utf-8 -*-
"""彩排判据 C4 · 打回修订环：V 点名缺陷 → F 定点重写 → 正文 sha 变 → 再送审 → 签。

## 这条链要走通的那一段

```text
AgentF.step                        # v1：reports/f-proof-<稿号>.md（三节稿）
AgentV.verify_proof                # 第 1 转 clean、第 2 转 fault ⇒ 立刻停（defect_step=2）
AgentF.step                        # 定点重写：只换第 2 步，正文 sha 变
AgentV.verify_proof                # 三转 clean ⇒ 新签指向新 sha
```

## 为什么"旧签仍在、只是与现行正文不等"不是这一条

业主/产品口径（2026-11-11「签是冻结」）：签过的稿只读 —— `AgentF._hand_proof` 对已签稿
受控拒 `manuscript_frozen`（要改只能开 B 的优化副本）；V 对已签正文短接
（`proof_manuscript_signed`，`review_passes=[]`）。所以"同一份 F 稿签完再改、旧签变
stale"在产品里造不出来（只在"违背只读纪律直接改盘"那种异常态出现）。这一份因此按
真链断三条：

| # | 判据 | 反真空 / 负控 |
|---|---|---|
| a | 打回是终局且点名步号：`proof_unregistered_rejected`、`defect_step=2`、洗过的转达落台账；v1 一份签都没有 | 把第 2 转判成 clean ⇒ 这一条红（fault 会被读成"没问题"） |
| b | F 只改那一步：重写后 sha 变、第 1 / 第 3 步逐字节不动、第 2 步变了；再送审三转 ⇒ 新签指向新 sha | 把重写做成"整份换掉" ⇒ 第 1 / 3 步的逐字断言红 |
| c | 冻结纪律：已签稿就地改 ⇒ `manuscript_frozen`；已签正文再送审 ⇒ `proof_manuscript_signed` 且零新行 | 放开冻结 / 放开短接 ⇒ 这两条红 |
| d | 旧 F 签不跟着优化副本走：`open_polish_copy` 复制出的 b 号稿已清签、源稿仍签着 | 复制件带着签 ⇒ 这一条红 |

读数：打回前后各收一次工（真 `auto_submit_signed`，挂一条 running 的 F 行）——
未签时进 `still_unsubmitted`（`state="unsigned"`、零提交），签后进 `auto_submitted`
（`body_sha` 是新 sha）+ 注 `mss:` 记号。

零真实模型调用；`tmp_path` 工作区，不碰 `projects/` / `demo/`。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import conductor as CND
from agentflow import depsection as DS
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.agent_f import autosubmit as _AS
from agentflow.agent_v import AgentV
from agentflow.store import Store

PROBLEM = "设 G 是有限群；则 |G| = p^2 时 G 是交换群。"
STEP1 = "由类方程，非中心共轭类的长度都被 p 整除。"
STEP2 = "于是 |Z(G)| 被 p 整除、非平凡。"
STEP2_FIX = "于是 |Z(G)| 被 p 整除、非平凡（p 是素数 ⇒ |Z(G)| 是 p 的正倍数）。"
STEP3 = "G/Z(G) 循环 ⇒ G 交换。"

#: V 报回来的负判原文（它的结论词仍是「成立」，缺陷由秘书语义判定读出来）。
FAULT_REPLY = json.dumps({"verdict": "成立", "why": "第 2 步的记号没有定义。",
                          "findings": []}, ensure_ascii=False)
CLEAN_REPLY = json.dumps({"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。",
                          "findings": []}, ensure_ascii=False)
#: 秘书洗过的那一份转达（要能引回 V 指出的那句）。
WASHED = "第 2 步的记号没有定义：请补上记号说明之后再送 V 重签。"


# --------------------------------------------------------------------------- 假缝


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """秘书那一格的假模型缝（只实现 `Secretary.judge` 用到的 `ask_json`）。"""

    wired = True

    def __init__(self, answers: dict[str, list] | None = None) -> None:
        self.answers = {k: list(v) for k, v in (answers or {}).items()}
        self.seen: list[str] = []

    def ask_json(self, prompt, *, system="", task_id="", note=""):
        self.seen.append(str(note))
        kind = str(note).split(":", 1)[-1]
        queue = self.answers.get(kind) or [{}]
        doc = queue.pop(0) if len(queue) > 1 else queue[0]
        return dict(doc), _Call()

    def asked(self, kind: str) -> int:
        return sum(1 for note in self.seen if note.endswith(f":{kind}"))


class _Review:
    """V 自己的审阅缝：按顺序交回复，并记下问过几次。"""

    wired = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.prompts.append(prompt)
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call

    def asked(self) -> int:
        return len(self.prompts)


class _FakeF:
    """F 那一轮的模型缝（`AgentF.llm.complete`）。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def _axis(answer: str, **extra) -> dict:
    out = {"checked": True, "decision": answer, "reason": "夹具：照规则判",
           "basis": ["夹具"]}
    out.update(extra)
    return out


FORM_OK = {"checked": True, "well_formed": True, "conditions": "设 G 是有限群",
           "conclusion": "则 |G| = p^2 时 G 交换", "problems": [],
           "decision": "形态合规", "refused": "", "reason": "夹具：形态合规"}


def _round(step2: str) -> str:
    """F 的 proof 一轮：三步（全声明成前提——这一份只量"改哪一步"）。"""
    return json.dumps({
        "strategy": "套用已知定理", "why_strategy": "中心非平凡则商群循环",
        "product": "proof", "kind": "theorem", "proposition": PROBLEM,
        "steps": [{"text": t, "assumption": True} for t in (STEP1, step2, STEP3)],
    }, ensure_ascii=False)


# --------------------------------------------------------------------------- 装配


def _workspace(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    return st


def _v(st: Store, *, replies: tuple[str, ...],
       answers: dict[str, list] | None = None) -> AgentV:
    seam = _Seam(answers or {})
    return AgentV(st, workspace_root=st.root, llm=_Review(*replies),
                  secretary=SEC.Secretary("V", root=st.root, store=st, seam=seam,
                                          enable_model=True))


def _body_of(st: Store, rel: str) -> str:
    return DS.proof_body((pathlib.Path(st.root) / rel).read_text(encoding="utf-8"))


def _sha_of(st: Store, rel: str) -> str:
    """这一份手稿的正文 sha（与 V 签的是同一把尺：`proof_sha(手稿)`）。"""
    if not rel:
        return ""
    return PR.proof_sha((pathlib.Path(st.root) / rel).read_text(encoding="utf-8"))


def _rewrite(f: AgentF, *, rel: str, mid: str, plan_id: str, body: str) -> dict:
    """F 的定点重写（F.step 内部那一支的写口）：同一稿号、只换 `## 证明`。"""
    return f._hand_proof(
        full=PROBLEM, text=PROBLEM, body=body, sid="s1", proposition=PROBLEM,
        plan={"plan_id": plan_id, "problem_key": "p2"},
        sg={"sid": "s1", "text": PROBLEM, "kind": "theorem"},
        manuscript_id=mid, manuscript_text="",
        manuscript_received={"source": "param", "chars": 0, "section_rows": 0,
                             "refs_in_proof": 0},
        cites=[], tier={"kind": "heuristic", "why": "夹具"},
        dependency_rows=[], existing_row={})


def _f_row(st: Store, *, task_id: str = "t-000001") -> None:
    """一条 running 的 F 台账行（收工自动提交的挂点；不是"提交"本身）。"""
    with st.tx("tasks", actor="夹具", note="C4 的 F 行") as tx:
        tx.upsert("tasks", S.Task(
            task_id=task_id, role="F", action="step", called_by="M",
            parent_task_id=None, depth=1, input_key="c4", status="running",
            outcome=None, refusal_reason=None, instance="", detail="在跑",
            error=None, started_at=S.now_iso(), ended_at=None, tokens=0, usd=0.0,
            artifacts=[], inputs=[]).to_dict())


def _close(st: Store, *, plan_id: str, task_id: str = "t-000001") -> dict:
    """在 F 那一行的上下文里叫一次收工自动提交（真入口）。"""
    with CND.calling_as(task_id, "F"):
        return _AS.auto_submit_signed(store=st, root=st.root, plan_id=plan_id,
                                      stamp=S.now_iso())


def _run_loop(base: pathlib.Path) -> dict:
    """把 C4 那条环整条跑一遍，返回盘上的读数（反真空拿同一份读数打红）。"""
    st = _workspace(base)
    f = AgentF(st, config={"workspace_root": str(st.root)},
               llm=_FakeF(_round(STEP2), _round(STEP2_FIX)))
    f.f_secretary = SEC.Secretary("F", root=st.root, store=st,
                                  seam=_Seam({"proposition_form": [dict(FORM_OK)]}),
                                  enable_model=True)
    plan_id = f.create_plan(PROBLEM, "p2", subgoals=[
        {"sid": "s1", "text": "证明 |G| = p^2 时 G 交换", "owner": "F",
         "testable": "找到非交换反例或给出论证"}])["plan_id"]

    # ---- v1：F 落稿 -----------------------------------------------------------
    first = f.step(plan_id)
    rel = str(first.get("manuscript_path") or "")
    mid = str(first.get("manuscript_id") or "")
    body1 = _body_of(st, rel) if rel else ""
    sha1 = _sha_of(st, rel)

    # ---- V 判 fault（第 1 转 clean、第 2 转 fault ⇒ 立刻停） --------------------
    faulted = _v(st, replies=(CLEAN_REPLY, FAULT_REPLY), answers={
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN),
                           _axis(SEC.V_REPLY_FAULT, defect_step=2)],
        "wash_v_reply": [{"text": WASHED, "step": 2,
                          "findings": [{"quote": "第 2 步的记号没有定义",
                                        "why": "记号没定义就没法核这一步"}]}],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)],
    })
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        rejected = faulted.verify_proof(statement_id="", proof_manuscript=rel)
    pending_after_fault, pending_bad = VR.pending_rows(st.root)

    # 打回之后、重写之前收一次工：这一份应该是"未签 ⇒ 不入提交单"。
    _f_row(st)
    before = _close(st, plan_id=plan_id)

    # ---- v2：F 定点重写（只改第 2 步） -----------------------------------------
    second = f.step(plan_id)
    body2 = _body_of(st, rel) if rel else ""
    sha2 = _sha_of(st, rel)

    # ---- 再送审：三转 clean ⇒ 签新 sha ---------------------------------------
    signed = _v(st, replies=(CLEAN_REPLY,), answers={
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)],
    })
    with CND.calling_as("t-v-000002", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        resigned = signed.verify_proof(statement_id="", proof_manuscript=rel)
    after = _close(st, plan_id=plan_id)

    text2 = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") if rel else ""
    return {
        "store": st,
        "f": f,
        "plan_id": plan_id,
        "rel": rel,
        "mid": mid,
        "body1": body1,
        "body2": body2,
        "sha1": sha1,
        "sha2": sha2,
        "first": dict(first),
        "second": dict(second),
        "rejected": dict(rejected),
        "resigned": dict(resigned),
        "pending": [dict(r) for r in pending_after_fault],
        "pending_bad": pending_bad,
        "before": dict(before),
        "after": dict(after),
        "text2": text2,
    }


# --------------------------------------------------------------------------- 判据本体


def _rejection_problems(reading: dict) -> list[str]:
    """a：打回是终局、点名步号、洗过的转达落台账、这一版没有签。"""
    problems: list[str] = []
    rej = reading["rejected"]
    if str(rej.get("kind") or "") != "proof_unregistered_rejected":
        problems.append(f"V 的负判种类不是 proof_unregistered_rejected：{rej.get('kind')!r}")
    if int(rej.get("defect_step") or 0) != 2:
        problems.append(f"负判没有点名 defect_step=2：{rej.get('defect_step')!r}")
    passes = [dict(p) for p in (rej.get("review_passes") or [])]
    if [str(p.get("axis") or "") for p in passes] != ["clean", "fault"]:
        problems.append(f"连判没有在 fault 那一转立刻停：{passes}")
    elif int(passes[-1].get("defect_step") or 0) != 2:
        problems.append(f"fault 那一转没指到第 2 步：{passes[-1]}")
    if passes and str(passes[-1].get("terminal") or "") != "rejected":
        problems.append(f"fault 那一转不是终局：{passes[-1]}")
    if reading["pending_bad"]:
        problems.append(f"pending 台账读不全：{reading['pending_bad']}")
    # 打回那一行要留下来（负判是"这一版被判过"的证据，不许随后续重写被抹掉）。
    named = [r for r in reading["pending"]
             if int(r.get("defect_step") or 0) == 2
             and str((r.get("secretary_judge") or {}).get("axis") or "") == "fault"]
    if not named:
        problems.append(f"pending 台账里没有点名第 2 步的那条负判：{reading['pending']}")
    elif "第 2 步的记号没有定义" not in str(named[-1].get("why") or ""):
        problems.append(f"负判那一行没有留下 V 指出的那句：{named[-1].get('why')!r}")
    if reading["sha1"] and VS.sign_path(reading["store"].root,
                                        reading["sha1"]).is_file():
        problems.append("被判「有毛病」的那一版居然有签文件（负判不是签）")
    return problems


def _revision_problems(reading: dict) -> list[str]:
    """b：只改那一步、sha 变了、再送审三转、新签指向新 sha。"""
    problems: list[str] = []
    body1 = reading["body1"]
    body2 = reading["body2"]
    if not body1 or not body2:
        return ["v1 / v2 有一版没读到正文（fault 或重写没落稿）"]
    if reading["sha1"] == reading["sha2"]:
        problems.append("重写之后正文 sha 没变（这不是一次修订）")
    one = body1.splitlines()
    two = body2.splitlines()
    if len(one) != len(two):
        problems.append(f"步数变了（{len(one)} → {len(two)}）：只许改那一步")
    else:
        changed = [i for i, (a, b) in enumerate(zip(one, two)) if a != b]
        if changed != [2]:
            problems.append(f"改动的步不是恰好第 2 步：{changed}（body={two}）")
    if str(reading["second"].get("proof_mode") or "") != "rewritten":
        problems.append(f"第二次不是「重写」那一档：{reading['second'].get('proof_mode')!r}")
    signed = reading["resigned"]
    if str(signed.get("kind") or "") != "proof_unregistered_signed":
        problems.append(f"重写后没有签上：{signed.get('kind')!r} / "
                        f"{str(signed.get('reason') or '')[:160]}")
    if len(signed.get("review_passes") or []) != int(VR.SIGN_STREAK_NEED):
        problems.append(f"重审没有三转：{len(signed.get('review_passes') or [])}")
    sha2 = reading["sha2"]
    if sha2:
        if not VS.sign_path(reading["store"].root, sha2).is_file():
            problems.append(f"新签文件不在盘上：out/vsigns/{sha2}.json")
        sign = VS.sign_of(reading["store"].root, sha2)
        if str(sign.get("artifact_sha") or "") != sha2:
            problems.append(f"新签指的不是新 sha：{sign.get('artifact_sha')!r} vs {sha2}")
        standing = VS.manuscript_sign_standing(reading["text2"], proof_sha=sha2)
        if str(standing.get("state") or "") != "signed":
            problems.append(f"稿上签块不是 signed：{standing.get('state')!r}")
    # 读数（真 auto_submit）：未签 ⇒ 不提交；签后 ⇒ 提交新 sha。
    before = reading["before"]
    if int(before.get("auto_submitted_count") or 0) != 0:
        problems.append(f"打回那一版（未签）被提交了：{before.get('auto_submitted')}")
    still = [dict(x) for x in (before.get("still_unsubmitted") or [])]
    if not still or str(still[0].get("state") or "") != "unsigned":
        problems.append(f"未签那一档没进 still_unsubmitted（state=unsigned）：{still}")
    after = dict(reading["after"])
    row = next((dict(r) for r in reading["store"].rows("tasks")
                if str(r.get("task_id") or "") == "t-000001"), {})
    mss = [str(a) for a in (row.get("artifacts") or []) if str(a).startswith("mss:")]
    if not mss:
        problems.append(f"签后没有提交记号：{after} / {row.get('artifacts')}")
    elif f"body_sha={sha2}" not in mss[0]:
        problems.append(f"提交记号里的正文 sha 不是新 sha：{mss[0]!r}")
    elif "via=sign_issued" not in mss[0]:
        problems.append(f"提交不是签发那一刻置的：{mss[0]!r}")
    # 签后那一次收工：要么这一趟真写了（auto_submitted），要么签时刻已经写过
    # （`already_submitted`）—— 两者都算"已提交"，但读数不许是"没提交"。
    if int(after.get("auto_submitted_count") or 0):
        one = dict((after.get("auto_submitted") or [])[0])
        if str(one.get("body_sha") or "") != sha2:
            problems.append(f"auto_submitted 里的正文 sha 不是新 sha：{one.get('body_sha')!r}")
    else:
        still_after = [dict(x) for x in (after.get("still_unsubmitted") or [])]
        state = str(still_after[0].get("state") or "") if still_after else ""
        if state != "already_submitted":
            problems.append(f"签后那一份既没提交也没读成 already_submitted：{after}")
    return problems


# ============================================================ ①② 正控（a + b）


def test_the_fault_names_a_step_and_f_rewrites_only_that_step(tmp_path):
    """正控：V 点名第 2 步 ⇒ F 只改第 2 步 ⇒ sha 变 ⇒ 再送审三转签新 sha。

    两条读数一起量：打回那一版「没有签」（负判不是签），重写那一版签上了，
    而且两次收工自动提交的读数分得开（未签 ⇒ still_unsubmitted；签后 ⇒ auto_submitted）。
    """
    reading = _run_loop(tmp_path)
    problems = _rejection_problems(reading) + _revision_problems(reading)
    assert problems == [], problems
    # 回执与盘上对得上（回执只作交叉核对）。
    assert reading["first"].get("proof_mode") == "registered", reading["first"]
    assert reading["second"].get("manuscript_id") == reading["mid"], reading["second"]


# ============================================================ ③ 冻结纪律


def test_a_signed_manuscript_is_frozen_and_a_signed_review_short_circuits(tmp_path):
    """冻结纪律：已签稿就地改 ⇒ `manuscript_frozen`；已签正文再送审 ⇒ 短接、零新行。

    这两条是产品设计（2026-11-11「签是冻结」），不是缺陷：签跟着正文走，改正文那一签
    就不算这一版。把它们写成断言，是为了防止以后有人"顺手允许就地改"。
    """
    reading = _run_loop(tmp_path)
    st: Store = reading["store"]
    rel = reading["rel"]
    mid = reading["mid"]
    sha2 = reading["sha2"]
    assert sha2, reading

    # ① 就地改：受控拒，盘上一个字节不动。
    frozen = _rewrite(reading["f"], rel=rel, mid=mid, plan_id=reading["plan_id"],
                      body="\n".join([f"1. {STEP1}", f"2. {STEP2_FIX}", f"3. {STEP3}"]))
    assert frozen.get("ok") is False, frozen
    assert str(frozen.get("kind") or "") == "manuscript_frozen", frozen
    assert "open_polish_copy" in str(frozen.get("error") or ""), frozen.get("error")
    assert _sha_of(st, rel) == sha2, "冻结那一拒之后正文被改了"

    # ② 已签正文再送审：短接成 proof_manuscript_signed，且 pending 台账不多行。
    def _pending_for(sha: str) -> int:
        rows, _bad = VR.pending_rows(st.root)
        return sum(1 for r in rows
                   if str(r.get("proof_sha256") or "") == str(sha))

    before_rows = _pending_for(sha2)
    again = _v(st, replies=(CLEAN_REPLY,), answers={
        "v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
        "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    with CND.calling_as("t-v-000003", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        short = again.verify_proof(statement_id="", proof_manuscript=rel)
    # 已签那一档：要么在册那一支的 proof_manuscript_signed，要么未在册那一支的
    # proof_unregistered_signed —— 两支的共同点是"一次都没重判"。
    assert str(short.get("kind") or "") in ("proof_manuscript_signed",
                                           "proof_unregistered_signed"), short
    assert short.get("review_passes") == [], short
    assert "不重复审" in str(short.get("reason") or ""), short.get("reason")
    assert _pending_for(sha2) == before_rows, "已签正文被重新审了一遍（pending 多了行）"


# ============================================================ ④ 优化副本


def test_the_old_f_sign_does_not_follow_the_polish_copy(tmp_path):
    """旧 F 签不跟着优化副本走：副本是新的 b 号稿、签块清掉、源稿仍签着。

    这条链是产品给"要改已签稿"的唯一出口（`B.open_polish_copy`）—— 它证明"旧签作废"
    的实现不是"把旧签删掉"，而是"新稿上没有它"：源稿那份签仍在盘上、仍盖着源稿。
    """
    reading = _run_loop(tmp_path)
    st: Store = reading["store"]
    rel = reading["rel"]
    sha2 = reading["sha2"]
    source_text = _body_of(st, rel)

    b = AgentB(st, extractor=None, extract_text=None, config={}, auto_secretary=False)
    copy = b.open_polish_copy(statement_id="000000", source_manuscript=rel)
    assert copy.get("ok") is True, copy
    path = str(copy.get("path") or "")
    assert path and path != rel, copy
    assert path.startswith("reports/b-proof-"), copy
    assert str(copy.get("copy_body_sha") or "") == str(copy.get("source_body_sha") or ""), copy
    copy_text = (pathlib.Path(st.root) / path).read_text(encoding="utf-8")
    # 复制件：签块被清掉（新稿未签）。
    assert "- V 签：" not in copy_text, copy_text[:800]
    assert copy.get("signed_before") is True and copy.get("signed_after") is False, copy
    assert int(copy.get("cleared") or 0) >= 1, copy
    standing_copy = VS.manuscript_sign_standing(copy_text, proof_sha=sha2,
                                                manuscript_path=path)
    assert str(standing_copy.get("state") or "") != "signed", standing_copy
    # 源稿：一个字节没动、签还在、盖的还是它。
    assert _body_of(st, rel) == source_text, "优化副本把源稿改了"
    assert VS.sign_path(st.root, sha2).is_file(), "源稿那一签被删了"
    standing_source = VS.manuscript_sign_standing(reading["text2"], proof_sha=sha2)
    assert str(standing_source.get("state") or "") == "signed", standing_source


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
