# -*- coding: utf-8 -*-
"""彩排判据 C3 · 数值链：M → D → E（数值 / 穷举两次实验）→ V（签 `## 证明`）→ B（收编）。

## 这条链要走通的那一段

```text
AgentE.run_experiment(..., method="numeric")            # 普通数值：reports/e-num-<稿号>.md
AgentE.run_experiment(..., method="exhaustive_search")  # 穷举证明：reports/e-proof-<稿号>.md（有 ## 证明）
AgentV.verify_proof(proof_manuscript=<e-proof>)         # 三转 clean ⇒ vsigns + 收方秘书落签块
AgentB.ingest_manuscript(mode="register", <e-num>)      # 数值通道：放行 + 数值证据位
AgentB.ingest_manuscript(mode="register", <e-proof>)    # 按稿收编：证明正文 + 第 1 条路径
```

真入口：真 `Store` / 真事务 / 真 `AgentE.run_experiment`（真起子进程、真解析
`REPRO_RESULT`、真落台账与两份手稿）/ 真 `AgentV.verify_proof`（穷举会审 + 三转）/ 真
`Secretary`（E 的形态闸、B 的切稿与登记）。只有"模型这一轮说什么"是假缝。

## 形态闸归谁（业主 2026-11-13 裁决「甲」，本文件按它写）

「B 侧只对 B 自己登记的命题审注册名，E 和 F 手稿侧录入放行」⇒ 形态闸的持有者是
产出侧（E 的 `agent_e/proposition_form.py::_proposition_form_gate`，在写 experiments
行 / e-proof 稿之前判一次）。

这条放行只覆盖「指针收录」（E / F / D 递一份稿、`own.ingest_manuscript(mode=register)`）：
`e-num` / `e-proof` / `f-proof` 三族在 B 这一路不判、零次模型调用、不写形态台账
（回执里 `judged=False / released=True / model_calls=0 / ledger_appended=False`），
也不因此多落一份 b-稿。「引文侧不是这一档」：`origin="external_lit"` + 无稿 + 未在册
仍要过 B 的形态闸，判过先落 `reports/b-proof-<B稿号>.md` 再登记、判不过受控拒
（带 `fix` / `next_step`、零字节、号不发）。那一档不在这条数值链上，本文件不测它，
但也不断言"B 侧不判形态 / 不落稿" —— 只断言本链这两笔指针收录的放行读数。

## 这条链的"走通"按盘上读数认（不是看回执里的 ok=True）

| # | 终态读数（盘上 / 台账上） |
|---|---|
| 1 | `experiments` 两行：`method` / `result=supports` / `evidence_kind` 分别是 `cross_check` 与 `proof` |
| 2 | `reports/e-num-<稿号>.md` 在盘上，有 `## 命题` 与 `## 数值结果`、没有 `## 证明` |
| 3 | `reports/e-proof-<稿号>.md` 在盘上，`## 证明` 那一节非空（V 签的就是它） |
| 4 | 签：`out/vsigns/<证明正文 sha>.json`、稿上签块 `state="signed"`、`verifications` 三行 `path_group=1` |
| 5 | 数值通道的 `statements` 一行：`kind="conjecture"`、`bits.numeric="verified"`、`proof_text` 空 |
| 6 | 穷举那一条的 `statements` 一行：`kind="theorem"`、`evidence_kind="proof"`、`proof_list=[1]`、`path_reading.count=1` |

## 反真空（打坏产出侧的形态闸）

把 E 的 `_proposition_form_gate` 打桩成「形态不合规」⇒ 穷举那一趟在写盘之前受控拒
（`ExperimentError`，拒信里带 `proposition_form_refused` 与 E 自己的改法句），
experiments 行 / e-proof 稿 / statements 一个字节都不落 ⇒ 第 1 / 3 / 6 条必须红。
它证明这条链的绿来自"产出侧那道闸真的判过并放行"，不是恒真。

另一条判据钉「甲」的放行面：E 这两族走指针收录时回执 `judged=False / released=True /
model_calls=0 / ledger_appended=False`，B 的秘书缝一次都没被问过 `proposition_form`，
形态台账一行没多，而且这一路「没有」多落一份 b-稿（落 b-稿是引文侧的动作，不是
指针收录的）—— 防止以后有人把闸又搬回 B，或把"放行"读成"B 什么都不写了"。

零真实模型调用；`tmp_path` 工作区，不碰 `projects/` / `demo/`。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import depsection as DS
from agentflow import manuscriptsubmission as MSUB
from agentflow import proofregistry as PR
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_e import AgentE
from agentflow.agent_v import AgentV
from agentflow.store import Store

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
    """秘书那一格的假模型缝：按 `note` 末段回预置 JSON。"""

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
    """V 自己的审阅缝（穷举那一支走机械会审，这一格只给散文支备用）。"""

    wired = True

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)

    def ask(self, prompt: str = "", **_kw) -> _Call:
        call = _Call()
        call.text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return call


def _axis(answer: str) -> dict:
    return {"checked": True, "decision": answer, "reason": "夹具：照规则判",
            "basis": ["夹具"]}


CLEAN = json.dumps({"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。",
                    "findings": []}, ensure_ascii=False)
FORM_OK = {"checked": True, "well_formed": True, "conditions": "n 为偶数",
           "conclusion": "n^2 + 2 不是 3 的倍数", "problems": [],
           "decision": "形态合规", "refused": "", "reason": "夹具：形态合规"}
IDENTITY_DIFFERENT = {"checked": True, "decision": "different",
                      "canonical_name": "另一条命题", "same_as": "", "route": "",
                      "condition": "夹具", "conclusion": "夹具",
                      "reason": "夹具：与在册各条都不同", "basis": ["夹具"]}


def _forms(n: int = 4) -> list[dict]:
    return [dict(FORM_OK) for _ in range(n)]


# --------------------------------------------------------------------------- 装配


def _workspace(base: pathlib.Path) -> Store:
    """真工作区 + 两个真脚本（E 会真起子进程跑它们）。"""
    st = Store(base / "ws")
    st.init()
    code = pathlib.Path(st.root) / "code"
    code.mkdir(parents=True, exist_ok=True)
    (code / "num_scan.py").write_text(NUM_SCRIPT, encoding="utf-8")
    (code / "enum_ramsey.py").write_text(EXH_SCRIPT, encoding="utf-8")
    return st


def _run_chain(base: pathlib.Path, *, trace: dict | None = None) -> dict:
    """把 C3 那条链整条跑一遍，返回盘上的读数（反真空拿同一份读数打红）。

    `trace` 给一个 dict 时，工作区在建好那一刻就挂进去 —— 反真空那一条要在
    `run_experiment` 抛出来之后仍然读得到盘（"一个字节都没写"是判据）。
    """
    st = _workspace(base)
    if trace is not None:
        trace["store"] = st
    e_seam = _Seam({"proposition_form": _forms()})
    e = AgentE(st, config={}, workspace_root=st.root,
               secretary=SEC.Secretary("E", root=st.root, store=st, seam=e_seam,
                                       enable_model=True))
    numeric = e.run_experiment(NUM_CLAIM, "num-scan", "code/num_scan.py",
                               method="numeric")
    exhaustive = e.run_experiment(PROOF_CLAIM, "ramsey34", "code/enum_ramsey.py",
                                  method="exhaustive_search", exhaustive=True,
                                  certificate={"kind": "enumeration_bound",
                                               "detail": "n<=9 全枚举"},
                                  search_bound={"n": 9})

    rel = str(exhaustive.get("proof_manuscript") or "")
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") if rel else ""

    v = AgentV(st, workspace_root=st.root, llm=_Review(CLEAN),
               secretary=SEC.Secretary(
                   "V", root=st.root, store=st,
                   seam=_Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                               "sign_issuance": [_axis(SEC.SIGN_ISSUE)]}),
                   enable_model=True))
    # E 派 V：收方秘书 = `secretary:E`（签块落回 E 那一份稿）。
    from agentflow import conductor as CND

    with CND.calling_as("t-v-000001", "V", parent_task_id="t-e-000001",
                        parent_role="E"):
        reviewed = v.verify_proof(statement_id="", proof_manuscript=rel)

    b_seam = _Seam({"proposition_form": _forms(),
                    "statement_keywords": [{"keywords": ["偶数", "倍数"],
                                            "why": "夹具：这两个词能把同一条命题捞出来"}],
                    "statement_same": [dict(IDENTITY_DIFFERENT)],
                    "proof_kind": [{"checked": True, "decision": "different",
                                    "same_path": 0, "reason": "夹具：另一条路径"}]})
    b = AgentB(st, extractor=None, extract_text=None, config={},
               secretary=SEC.Secretary("B", root=st.root, store=st, seam=b_seam,
                                       enable_model=True))
    numeric_ms = str(numeric.get("numeric_manuscript") or "")
    form_rows_before = [dict(r) for r in SEC.proposition_form_rows(st.root)]
    filed_numeric = b.ingest_manuscript(manuscript=numeric_ms, mode="register")
    filed_proof = b.ingest_manuscript(manuscript=rel, mode="register")
    form_rows_after = [dict(r) for r in SEC.proposition_form_rows(st.root)]

    return {
        "store": st,
        "numeric": dict(numeric),
        "exhaustive": dict(exhaustive),
        "reviewed": dict(reviewed),
        "filed_numeric": dict(filed_numeric),
        "filed_proof": dict(filed_proof),
        "b_seam": b_seam,
        "form_rows_before": form_rows_before,
        "form_rows_after": form_rows_after,
        "rel": rel,
        "text": text,
        "numeric_rel": numeric_ms,
        "numeric_text": (pathlib.Path(st.root) / numeric_ms).read_text(encoding="utf-8")
                        if numeric_ms else "",
        "experiments": [dict(r) for r in st.rows("experiments")],
        "statements": [dict(r) for r in st.rows("statements")],
        "sid_numeric": str((filed_numeric.get("target") or {}).get("stmt_id") or ""),
        "sid_proof": str((filed_proof.get("target") or {}).get("stmt_id") or ""),
    }


# --------------------------------------------------------------------------- 判据本体


def _banked(reading: dict) -> dict:
    """盘上/台账上那几条承重读数（正控与反真空共用同一份量法）。

    稿上的字一律「重读盘上那一份」：签块是 V 的签发那一笔落上去的，而 `_run_chain`
    里那份 `text` 是 E 刚落完稿时的快照（签在那之后才落）。
    """
    st: Store = reading["store"]
    sid_numeric = reading["sid_numeric"]
    sid_proof = reading["sid_proof"]
    rel = str(reading["rel"])
    text = ((pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
            if rel and (pathlib.Path(st.root) / rel).is_file() else "")
    numeric_row = next((r for r in reading["statements"]
                        if str(r.get("stmt_id")) == sid_numeric), {})
    proof_row = next((r for r in reading["statements"]
                      if str(r.get("stmt_id")) == sid_proof), {})
    body = DS.proof_body(text).strip("\n") if text else ""
    reading = dict(reading)
    reading.update({
        "text": text,
        "numeric_row": numeric_row,
        "proof_row": proof_row,
        "proof_body": body,
        "proof_sha": PR.proof_sha(body) if body else "",
        "proof_groups": ([int(r.get("path_group") or 0)
                          for r in VR.list_verifications(st.root, statement_id=sid_proof,
                                                        limit=None)[0]] if sid_proof else []),
        "path": (MSUB.path_reading(st, st.root, statement_id=sid_proof)
                 if sid_proof else {}),
    })
    return reading


def _chain_problems(reading: dict) -> list[str]:
    """C3 的六条终态读数（空 = 通）。每条都读盘，不看回执里的 ok。"""
    reading = _banked(reading)
    st: Store = reading["store"]
    problems: list[str] = []

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
            problems.append(f"experiments 的两行不是「数值 cross_check + 穷举 proof」：{got}")

    # 2. 普通数值手稿：有 `## 命题` / `## 数值结果`，没有 `## 证明`。
    numeric_text = str(reading["numeric_text"])
    if not reading["numeric_rel"].startswith("reports/e-num-"):
        problems.append(f"普通数值手稿不在 e-num 族：{reading['numeric_rel']!r}")
    if "## 命题" not in numeric_text or "## 数值结果" not in numeric_text:
        problems.append("普通数值手稿缺 `## 命题` 或 `## 数值结果` 那一节")
    if "## 证明" in numeric_text:
        problems.append("普通数值手稿不该有 `## 证明`（它不过 V，见业主口径）")

    # 3. 穷举手稿：`## 证明` 那一节非空（V 的签就盖在它上面）。
    if not reading["rel"].startswith("reports/e-proof-"):
        problems.append(f"穷举手稿不在 e-proof 族：{reading['rel']!r}")
    if not reading["proof_body"].strip():
        problems.append("穷举手稿的 `## 证明` 是空的（没有可签的正文）")

    # 4. 签：信封 + 稿上签块 + 三行台账都是第 1 条路径。
    sha = str(reading["proof_sha"])
    if sha:
        if not VS.sign_path(st.root, sha).is_file():
            problems.append(f"签信封不在盘上：out/vsigns/{sha}.json")
        standing = VS.manuscript_sign_standing(reading["text"], proof_sha=sha)
        if str(standing.get("state") or "") != "signed":
            problems.append(f"稿上的签块不是 signed：{standing.get('state')!r} "
                            f"({standing.get('why') or standing.get('reason') or ''})")
        groups = [int(x or 0) for x in reading["proof_groups"]]
        if len(groups) != int(VR.SIGN_STREAK_NEED):
            problems.append(f"verifications 应恰好 {VR.SIGN_STREAK_NEED} 行，实得 {len(groups)} 行")
        if set(groups) != {1}:
            problems.append(f"verifications 的 path_group 不是 [1]：{groups}")

    # 5. 数值通道：conjecture + 数值位 verified + 证明栏空着。
    numeric_row = dict(reading["numeric_row"])
    if not numeric_row:
        problems.append(f"数值通道没有落 statements 行（号 {reading['sid_numeric']!r}）："
                        f"{reading['filed_numeric'].get('refused')!r} "
                        f"{str(reading['filed_numeric'].get('reason') or '')[:160]}")
    else:
        if str(numeric_row.get("kind") or "") != "conjecture":
            problems.append(f"数值通道的 kind 不是 conjecture：{numeric_row.get('kind')!r}")
        if str(numeric_row.get("evidence_kind") or "") != "cross_check":
            problems.append(f"数值通道的 evidence_kind 不是 cross_check："
                            f"{numeric_row.get('evidence_kind')!r}")
        if str(numeric_row.get("proof_text") or "").strip():
            problems.append("普通数值档的 proof_text 该留空（业主口径），实得非空")
        if dict(numeric_row.get("bits") or {}).get("numeric") != "verified":
            problems.append(f"数值通道的 bits.numeric 不是 verified："
                            f"{dict(numeric_row.get('bits') or {}).get('numeric')!r}")

    # 6. 穷举那一条：theorem / proof / 第 1 条路径。
    proof_row = dict(reading["proof_row"])
    if not proof_row:
        problems.append(f"按稿收编没有落 statements 行（号 {reading['sid_proof']!r}）："
                        f"{reading['filed_proof'].get('refused')!r} "
                        f"{str(reading['filed_proof'].get('reason') or '')[:160]}")
    else:
        if str(proof_row.get("kind") or "") != "theorem":
            problems.append(f"穷举那一条的 kind 不是 theorem：{proof_row.get('kind')!r}")
        if str(proof_row.get("evidence_kind") or "") != "proof":
            problems.append(f"穷举那一条的 evidence_kind 不是 proof："
                            f"{proof_row.get('evidence_kind')!r}")
        if PR.proof_sha(str(proof_row.get("proof_text") or "")) != reading["proof_sha"]:
            problems.append("命题行上的正文与稿里 `## 证明` 不是同一份")
        nos = [int(no) for no, _t in VR.proof_list(proof_row)]
        if nos != [1]:
            problems.append(f"proof_list 不是 [1]：{nos}")
        path = dict(reading["path"])
        if path.get("checked") is not True or int(path.get("count") or 0) != 1:
            problems.append(f"路径读数不是 1 条：{path}")
        elif int((path.get("paths") or [{}])[0].get("path_group") or 0) != 1:
            problems.append(f"第 1 条路径的 path_group 不是 1：{path.get('paths')}")
    return problems


# ============================================================ ① 正控：链走通


def test_the_numeric_chain_runs_end_to_end(tmp_path):
    """正控：E 两次实验 → V 签穷举稿 → B 收编两条，六条终态读数全对。"""
    reading = _run_chain(tmp_path)
    problems = _chain_problems(reading)
    assert problems == [], problems

    # 回执与盘上对得上（回执只作交叉核对，判据以盘上为准）。
    assert reading["numeric"]["evidence_kind"] == "cross_check", reading["numeric"]
    assert reading["exhaustive"]["evidence_kind"] == "proof", reading["exhaustive"]
    assert reading["filed_numeric"].get("ok") is True, reading["filed_numeric"]
    assert reading["filed_proof"].get("ok") is True, reading["filed_proof"]
    # 两次收编各落一行，且不是同一行（数值与证明是两条命题）。
    assert len({reading["sid_numeric"], reading["sid_proof"]}) == 2, (
        reading["sid_numeric"], reading["sid_proof"])
    assert len(reading["statements"]) == 2, reading["statements"]
    # V 的三转是一次送审里自己转三次。
    assert len(reading["reviewed"].get("review_passes") or []) == int(VR.SIGN_STREAK_NEED)
    assert reading["reviewed"].get("kind") == "proof_unregistered_signed", reading["reviewed"]


# ============================================================ ② 反真空：产出侧形态闸坏


def test_a_broken_producer_form_gate_turns_the_chain_red(tmp_path, monkeypatch):
    """反真空（产出侧形态闸）：E 的 `_proposition_form_gate` 判「形态不合规」⇒ 链必须红。

    2026-11-13 业主裁决之后，形态闸的持有者是产出侧（E 的数值证明路线），B 侧对
    `e-num` / `e-proof` 放行。所以这一条打的是 E 的那一格：`run_experiment` 在写
    experiments 行 / e-proof 稿之前受控拒（`ExperimentError`），一个字节都不写。
    它证明第 3 / 6 条不是"跑过 E 就算数"，而是"产出侧那道闸真的判过并放行"。
    """
    from agentflow.agent_e import ExperimentError
    from agentflow.agent_e import proposition_form as EFORM

    def _refuse(self, **_kw):
        return {"checked": True, "well_formed": False, "submittable": False,
                "refused": "proposition_form_refused",
                "reason": "打桩：这一条没有写清条件与结论",
                "problems": ["没有写出「从什么条件导出什么结论」"],
                "decision": "形态不合规"}

    monkeypatch.setattr(EFORM._NumericProofFormGate, "_proposition_form_gate", _refuse)

    trace: dict = {}
    with pytest.raises(ExperimentError) as excinfo:
        _run_chain(tmp_path, trace=trace)
    message = str(excinfo.value)
    # 受控码与 E 自己的改法句都在拒信里（E 侧没有 B 那对 fix / next_step 键）。
    assert "proposition_form_refused" in message, message
    assert "设…则…" in message, message

    # 零写入（指被拒的那一趟）：普通数值那一行照旧在（它不过这道闸）；
    # 穷举那一趟的实验行 / e-proof 稿 / statements 一个都没有（闸在写盘之前）。
    st: Store = trace["store"]
    experiments = [dict(r) for r in st.rows("experiments")]
    assert [str(r.get("method") or "") for r in experiments] == ["numeric"], experiments
    reports = pathlib.Path(st.root) / "reports"
    leftovers = ([p.name for p in reports.glob("e-proof-*.md")]
                 if reports.is_dir() else [])
    assert leftovers == [], leftovers
    assert st.rows("statements") == [], st.rows("statements")


# ============================================================ ③ 新裁决：B 侧放行


def test_pointer_intake_releases_the_e_families_without_a_second_form_judgement(tmp_path):
    """裁决「甲」（2026-11-13）：E 的两族走「指针收录」时 B 不判形态、零次模型调用。

    读数按收编回执里那一格认（`proposition_form`：`judged=False` / `released=True` /
    `model_calls=0` / `ledger_appended=False`），并核三处旁证：
    ① B 的秘书缝一次都没被问过 `proposition_form`；
    ② 形态台账在两次收编前后一行没多；
    ③ 指针收录这条路「没有」多落一份 b-稿 —— 「甲」里落 b-稿的是引文侧（
    `origin="external_lit"` + 无稿 + 未在册：判过先落 `reports/b-proof-<B稿号>.md`
    再登记），不是这一档。这一条「不」断言"B 侧不判形态/不落稿"，只断言本链这两笔
    指针收录的放行读数与其边界。
    """
    reading = _run_chain(tmp_path)
    assert _chain_problems(reading) == [], _chain_problems(reading)

    # 回执里的放行读数：两族各一条。
    for got, family in ((reading["filed_numeric"], "e-num"),
                        (reading["filed_proof"], "e-proof")):
        form = dict(got.get("proposition_form") or {})
        assert form.get("released") is True, (family, form)
        assert form.get("judged") is False, (family, form)
        assert int(form.get("model_calls") or 0) == 0, (family, form)
        assert form.get("ledger_appended") is False, (family, form)
        assert str(form.get("family") or "") == family, (family, form)
        assert "放行" in str(form.get("reason") or ""), (family, form)

    # 旁证①：B 的秘书缝没被问过形态（问过的只有同一命题检索那一族）。
    assert reading["b_seam"].asked("proposition_form") == 0, reading["b_seam"].seen
    # 旁证②：形态台账一行没多（E 那一次仍在；B 一次都没写）。
    before = {str(r.get("statement_sha256") or "") for r in reading["form_rows_before"]}
    after = {str(r.get("statement_sha256") or "") for r in reading["form_rows_after"]}
    assert after == before, (reading["form_rows_before"], reading["form_rows_after"])
    b_rows = [r for r in reading["form_rows_after"]
              if str(r.get("role") or "") == "B"]
    assert b_rows == [], b_rows
    # 旁证③：指针收录不多落 b-稿（落 b-稿是引文侧那一档的动作）。
    reports = pathlib.Path(reading["store"].root) / "reports"
    b_copies = ([p.name for p in reports.glob("b-proof-*.md")]
                if reports.is_dir() else [])
    assert b_copies == [], b_copies


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
