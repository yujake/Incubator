# -*- coding: utf-8 -*-
"""彩排判据 C2 · 证明链：M → D（立题）→ F（立项 + 写稿）→ V（三转签）→ B（按稿收编）。

## 这条链要走通的那一段

```text
Conductor.summon("D", "register_conjecture")      # 立题：conjectures 一行（真事务）
Conductor.summon("F", "create_plan", by="D")      # 立项：attack_plans 一行
Conductor.summon("F", "step", by="D")             # 写稿：reports/f-proof-<稿号>.md（真渲染）
AgentV.verify_proof(proof_manuscript=…)           # 三转 clean ⇒ vsigns 信封 + 收方秘书落签块
AgentB.ingest_manuscript(mode="register")         # 按稿收编 ⇒ statements 一行 + 第 1 条路径
```

真入口：真 `Store` / 真事务 / 真 `Conductor.summon`（派活与落 `tasks`）/ 真 F 渲染器 /
真 `Secretary`（F 的形态闸、V 的判词与发签、B 的切稿与登记）。只有两处是假缝：
F 那一轮「模型说什么」与 V 那一轮「模型说什么」——都用预置 JSON 缝给。

## 这条链的"走通"按盘上读数认（不是看回执里的 ok=True）

| # | 终态读数（盘上 / 台账上） |
|---|---|
| 1 | `conjectures` 一行：`statement` 逐字是 D 立的那一条 |
| 2 | `attack_plans` 一行：`problem_key` 是 D 给的方向、`problem` 逐字是那条命题 |
| 3 | 稿名 `reports/f-proof-<六位稿号>.md`：不带 `-pN`、不借计划号 / 命题号 |
| 4 | 稿头：没有 `- 证明号：` 那一行；`- 证据种类：theorem` 在 |
| 5 | 依赖段表头恰好三列（引用 / 命题号 / 步），没有「路径号」那一列 |
| 6 | `statements` 一行：`kind="theorem"`（按稿头那一格落）、正文 sha 与稿上一致 |
| 7 | 路径号：`verifications` 三行都回填 `path_group=1`、`proof_list` = `[1]`、`path_reading.count=1` |
| 8 | 签：`out/vsigns/<正文 sha>.json` 在盘上，稿上的签块 `state="signed"` |
| 9 | `mss:` 记号：F 那一行 `tasks.artifacts` 里有 `mss:<稿号>#…via=sign_issued` |

## 反真空（打坏 V 那一环）

把 `vsigns.issue` 打桩成「不签」（返回 `written=False`）⇒ 第 7 / 8 / 9 条必须红，
B 的收录必须被签闸拒。它证明这条链的绿来自「V 真的签了」，而不是「三转跑完就算数」。

零真实模型调用；`tmp_path` 工作区，不碰 `projects/` / `demo/`。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import conductor as CO
from agentflow import depsection as DS
from agentflow import manuscriptsubmission as MSUB
from agentflow import proofregistry as PR
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_d import AgentD
from agentflow.agent_f import AgentF
from agentflow.agent_v import AgentV
from agentflow.store import Store

PROBLEM = "设 G 是有限群；则 |G| = p^2 时 G 是交换群。"
PROOF = ("1. 由类方程 |G| = |Z(G)| + Σ[G:C_G(x_i)]：每个非中心共轭类的长度都被 p 整除。\n"
         "2. 于是 |Z(G)| 被 p 整除、非平凡；G/Z(G) 循环 ⇒ G 交换。")
PLAN_KEY = "p2-abelian"


# --------------------------------------------------------------------------- 假缝


class _Call:
    """`llmseam.SeamCall` 的替身：`judge()` 只读 ok / problem / detail / text。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _Seam:
    """秘书那一格的假模型缝（只实现 `Secretary.judge` 用到的 `ask_json`）。

    按 `note` 的末段回预置 JSON；没预置的那一问回空 dict —— 与既有夹具同一做法
    （空 dict 在洗稿那一档读成「不用洗」，在判定那一档读成「没判成」）。
    """

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
    """F 那一轮的模型缝：`AgentF` 的 `llm.complete` 约定。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


FORM_OK = {"checked": True, "well_formed": True, "conditions": "设 G 是有限群",
           "conclusion": "则 |G| = p^2 时 G 交换", "problems": [],
           "decision": "形态合规", "refused": "", "reason": "夹具：形态合规"}
CLEAN_REPLY = json.dumps({"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。",
                          "findings": []}, ensure_ascii=False)


def _axis(answer: str) -> dict:
    return {"checked": True, "decision": answer, "reason": "夹具：照规则判",
            "basis": ["夹具"]}


def _round() -> str:
    """F 的 proof 一轮：命题 / 两步 / 稿头要落的 kind。"""
    return json.dumps({
        "strategy": "套用已知定理", "why_strategy": "中心非平凡则商群循环",
        "product": "proof", "kind": "theorem", "proposition": PROBLEM,
        "steps": [{"text": "由类方程，中心非平凡。", "assumption": True},
                  {"text": "于是 G/Z(G) 循环，G 交换。", "assumption": True}],
    }, ensure_ascii=False)


# --------------------------------------------------------------------------- 装配


def _workspace(base: pathlib.Path) -> Store:
    st = Store(base / "ws")
    st.init()
    return st


def _run_chain(base: pathlib.Path) -> dict:
    """把 C2 那条链整条跑一遍，返回盘上的读数（反真空拿同一份读数打红）。"""
    st = _workspace(base)
    f_seam = _Seam({"proposition_form": [dict(FORM_OK)]})
    f_sec = SEC.Secretary("F", root=st.root, store=st, seam=f_seam, enable_model=True)
    f = AgentF(st, config={"workspace_root": str(st.root)}, llm=_FakeF(_round()))
    f.f_secretary = f_sec

    def factory_d(*, store):
        return AgentD(store)

    def factory_f(*, store):
        return f

    cond = CO.Conductor(st, registry={"D": ("factory", factory_d),
                                      "F": ("factory", factory_f)})
    # ---- M → D：立题 ------------------------------------------------------------
    d_task = cond.summon("D", "register_conjecture", {
        "statement": PROBLEM, "origin": "doc:0000#thm-1", "form": "universal",
        "testable": {"parameters": {"p": "素数"},
                     "criterion": "G/Z(G) 循环 ⇒ G 交换",
                     "falsified_by": "找到 |G| = p^2 的非交换群"},
    })
    # ---- D → F：立项 ------------------------------------------------------------
    plan_task = cond.summon("F", "create_plan", {
        "problem": PROBLEM, "problem_key": PLAN_KEY,
        "subgoals": [{"sid": "s1", "text": "证明 |G| = p^2 时 G 交换", "owner": "F",
                      "testable": "找到非交换反例或给出完整论证"}],
    }, by="D", parent_task_id=str(d_task.task_id or ""))
    plan_id = str((plan_task.payload or {}).get("plan_id") or "")
    # ---- D → F：写稿 ------------------------------------------------------------
    step_task = cond.summon("F", "step", {"plan_id": plan_id},
                            by="D", parent_task_id=str(d_task.task_id or ""))
    step = dict(step_task.payload or {}) if isinstance(step_task.payload, dict) else {}
    rel = str(step.get("manuscript_path") or "")
    text = ((pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
            if rel else "")

    v_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                    "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    v = AgentV(st, workspace_root=st.root, llm=_Review(CLEAN_REPLY),
               secretary=SEC.Secretary("V", root=st.root, store=st, seam=v_seam,
                                       enable_model=True))
    # ---- F → V：送审（收方 = F 那一行；签块与 mss 记号都落回它） -------------------
    with CO.calling_as("t-v-000001", "V", parent_task_id=str(step_task.task_id or ""),
                       parent_role="F"):
        reviewed = v.verify_proof(statement_id="", proof_manuscript=rel)

    b_seam = _Seam({"proposition_form": [dict(FORM_OK)],
                    "statement_keywords": [{"keywords": ["交换群", "中心", "类方程"],
                                            "why": "夹具：同一条命题的关键词"}],
                    "proof_kind": [{"checked": True, "decision": "different",
                                    "same_path": 0, "reason": "夹具：第 1 条路径"}]})
    b = AgentB(st, extractor=None, extract_text=None, config={},
               secretary=SEC.Secretary("B", root=st.root, store=st, seam=b_seam,
                                       enable_model=True))
    # ---- V 签之后 → B：按稿收编 ------------------------------------------------
    filed = b.ingest_manuscript(manuscript=rel, mode="register")

    body = DS.proof_body(text).strip("\n") if text else ""
    sid = str((filed.get("target") or {}).get("stmt_id") or "")
    return {
        "store": st,
        "d_task": d_task.to_dict(),
        "plan_task": plan_task.to_dict(),
        "step_task": step_task.to_dict(),
        "step": step,
        "rel": rel,
        "text": text,
        "body": body,
        "reviewed": dict(reviewed),
        "filed": dict(filed),
        "conjectures": [dict(r) for r in st.rows("conjectures")],
        "plans": [dict(r) for r in st.rows("attack_plans")],
        "statements": [dict(r) for r in st.rows("statements")],
        "tasks": [dict(r) for r in st.rows("tasks")],
        "sid": sid,
    }


# --------------------------------------------------------------------------- 判据本体


def _chain_problems(reading: dict) -> list[str]:
    """C2 的九条终态读数（空 = 通）。每条都读盘，不看回执里的 ok。"""
    problems: list[str] = []
    st: Store = reading["store"]
    text = str(reading["text"])
    rel = str(reading["rel"])
    sid = str(reading["sid"])

    # 1. D 立的题。
    conjectures = reading["conjectures"]
    if len(conjectures) != 1 or str(conjectures[0].get("statement") or "") != PROBLEM:
        problems.append(f"conjectures 不是 D 立的那一条：{conjectures}")

    # 2. F 的立项（方向来自 D）。
    plans = reading["plans"]
    if len(plans) != 1:
        problems.append(f"attack_plans 应恰好 1 行，实得 {len(plans)} 行")
    else:
        plan = plans[0]
        if str(plan.get("problem_key") or "") != PLAN_KEY:
            problems.append(f"计划的 problem_key 不是 D 给的方向：{plan.get('problem_key')!r}")
        if str(plan.get("problem") or "") != PROBLEM:
            problems.append(f"计划的 problem 与立题不一致：{plan.get('problem')!r}")

    # 3. 稿名：一个稿号 = 一份文件，不带 -pN。
    if not rel:
        problems.append("F 这一轮没有落稿（manuscript_path 为空）")
    else:
        name = pathlib.PurePosixPath(rel).name
        if not rel.startswith("reports/f-proof-"):
            problems.append(f"稿名不在 f-proof 族里：{rel!r}")
        if re.search(r"-p\d+\.md$", name):
            problems.append(f"稿名带 `-pN`（一个稿号一份文件，不该有它）：{name!r}")
        if not (pathlib.Path(st.root) / rel).is_file():
            problems.append(f"稿不在盘上：{rel!r}")

    # 4. 稿头：没有「证明号」，证据种类在。
    #    稿上的字读「收编之后」那一份：V 的签块与 B 的落签都在这一份上。
    text = ((pathlib.Path(st.root) / rel).read_text(encoding="utf-8") if rel else "")
    if text:
        if "- 证明号：" in text:
            problems.append("稿头还有 `- 证明号：` 那一行（产出侧已退役）")
        if "- 证据种类：theorem" not in text:
            problems.append("稿头没有 `- 证据种类：theorem`（kind 无处可落）")

    # 5. 依赖段表头恰好三列。
    deps_section = text.split("## 依赖", 1)[1] if "## 依赖" in text else ""
    header = next((ln.strip() for ln in deps_section.splitlines() if ln.strip()),
                  "")
    want_cols = "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |"
    if header != want_cols:
        problems.append(f"依赖段表头不是三列：{header!r}")
    if "路径号" in deps_section:
        problems.append("依赖段还带着「路径号」那一列")

    # 6. statements：按稿头落 kind，正文 sha 与稿上一致。
    statements = reading["statements"]
    if len(statements) != 1:
        problems.append(f"statements 应恰好 1 行，实得 {len(statements)} 行")
    else:
        row = statements[0]
        if str(row.get("kind") or "") != "theorem":
            problems.append(f"statements.kind 不是稿头声明的 theorem：{row.get('kind')!r}")
        if str(row.get("stmt_id") or "") != sid or not sid:
            problems.append(f"回执里的命题号与盘上不一致：{sid!r} / {row.get('stmt_id')!r}")
        if reading["body"] and (
                PR.proof_sha(str(row.get("proof_text") or ""))
                != PR.proof_sha(reading["body"])):
            problems.append("命题行上的正文与稿里 `## 证明` 不是同一份")

    # 7. 路径号：verifications / proof_list / path_reading 三处都是第 1 条。
    if sid:
        rows, bad = VR.list_verifications(st.root, statement_id=sid, limit=None)
        groups = [int(r.get("path_group") or 0) for r in rows]
        if bad:
            problems.append(f"verifications 台账读不全：{bad}")
        if len(rows) != int(VR.SIGN_STREAK_NEED):
            problems.append(f"verifications 应恰好 {VR.SIGN_STREAK_NEED} 行（三转），"
                            f"实得 {len(rows)} 行")
        if set(groups) != {1}:
            problems.append(f"verifications 的 path_group 不是 [1]：{groups}")
        proof_nos = [int(no) for no, _t in VR.proof_list(
            next(r for r in statements if str(r.get("stmt_id")) == sid))]
        if proof_nos != [1]:
            problems.append(f"proof_list 不是 [1]：{proof_nos}")
        path = MSUB.path_reading(st, st.root, statement_id=sid)
        if path.get("checked") is not True or int(path.get("count") or 0) != 1:
            problems.append(f"路径读数不是 1 条：{path}")
        elif int((path.get("paths") or [{}])[0].get("path_group") or 0) != 1:
            problems.append(f"第 1 条路径的 path_group 不是 1：{path.get('paths')}")

    # 8. 签：信封在盘上、稿上签块 signed（签块由 V 的签发那一笔落在稿上）。
    if reading["body"]:
        sha = PR.proof_sha(reading["body"])
        if not VS.sign_path(st.root, sha).is_file():
            problems.append(f"签信封不在盘上：out/vsigns/{sha}.json")
        standing = VS.manuscript_sign_standing(text, proof_sha=sha)
        if str(standing.get("state") or "") != "signed":
            problems.append(f"稿上的签块不是 signed：{standing.get('state')!r} "
                            f"({standing.get('why') or standing.get('reason') or ''})")

    # 9. mss 记号：F 那一行 artifacts 里有它，且是签发那一刻置的。
    #    读「盘上现在那一行」（召唤回执是派活那一刻的快照，签在那之后才落）。
    step_task_id = str(reading["step_task"].get("task_id") or "")
    now = next((dict(r) for r in st.rows("tasks")
                if str(r.get("task_id") or "") == step_task_id), {})
    artifacts = [str(x) for x in (now.get("artifacts") or [])]
    mss = [x for x in artifacts if x.startswith("mss:")]
    if not mss:
        problems.append(f"F 那一行 tasks.artifacts 里没有 mss: 记号：{artifacts}")
    else:
        wanted_mid = str(reading["step"].get("manuscript_id") or "")
        if not any(x.startswith(f"mss:{wanted_mid}#") for x in mss):
            problems.append(f"mss: 记号点不到这一份稿（稿号 {wanted_mid!r}）：{mss}")
        if "via=sign_issued" not in mss[0]:
            problems.append(f"mss: 记号不是签发那一刻置的：{mss[0]!r}")
    return problems


# ============================================================ ① 正控：链走通


def test_the_proof_chain_runs_end_to_end(tmp_path):
    """正控：D 立题 → F 立项写稿 → V 三转签 → B 按稿收编，九条终态读数全对。"""
    reading = _run_chain(tmp_path)
    problems = _chain_problems(reading)
    assert problems == [], problems

    # 派活这一侧也要对：M→D 与 D→F 三趟都真的跑完并落了终态。
    tasks = [(str(t.get("role") or ""), str(t.get("action") or ""),
              str(t.get("outcome") or "")) for t in reading["tasks"]]
    assert sorted(tasks) == sorted([("D", "register_conjecture", "ok"),
                                    ("F", "create_plan", "ok"),
                                    ("F", "step", "ok")]), tasks
    # V 的三转是「一次送审里自己转三次」（不是 F 交了三趟）。
    assert reading["reviewed"].get("kind") == "proof_unregistered_signed", reading["reviewed"]
    assert len(reading["reviewed"].get("review_passes") or []) == int(VR.SIGN_STREAK_NEED)
    # 路径号这一格是"读数"，另按三处一起核（三处缺一处都可能恒真）。
    sid = reading["sid"]
    assert int(MSUB.path_reading(reading["store"], reading["store"].root,
                                 statement_id=sid)["count"]) == 1
    assert [no for no, _t in VR.proof_list(
        next(r for r in reading["statements"] if str(r.get("stmt_id")) == sid))] == [1]


# ============================================================ ② 反真空：V 没签


def test_a_stubbed_v_sign_turns_the_chain_red(tmp_path, monkeypatch):
    """反真空（V 那一环）：`vsigns.issue` 打桩成「不签」⇒ 链必须红。

    打桩的是"V 的签有没有颁出去"（产品里唯一那处 `vsigns.issue`），不是判据：
    V 的三转照跑、`verifications` 照写，只是没有签信封与签块。若这一条不红，
    上面那些断言就只是"送审跑过一遍"，而不是"V 真的签了、B 才收得进来"。
    """
    from agentflow import vsigns as _VS

    monkeypatch.setattr(
        _VS, "issue",
        lambda *a, **k: {"written": False, "idempotent": False,
                         "reason": "打桩：这一趟不签", "path": ""})

    reading = _run_chain(tmp_path)
    problems = _chain_problems(reading)
    assert problems, "签被打桩成「不签」，链却读成了通 —— 这一组判据是橡皮图章"
    # 红在签与收编这两格上（不是"三转都没跑"那种早退）：
    assert any("签" in p or "vsigns" in p for p in problems), problems
    assert reading["filed"].get("ok") is not True, reading["filed"]
    # 三转仍然真的跑过（反真空只打坏签，不打坏审阅）。
    assert len(reading["reviewed"].get("review_passes") or []) == int(VR.SIGN_STREAK_NEED)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
