# -*- coding: utf-8 -*-
"""p247：V 的判词只是陈述；轴（clean / fault）只由 V 的秘书语义分析给出。

业主 2026-11-06 第三次收紧逐字：
「① 结论只有两态：成立 / 有毛病。不存在『判不了』这一档；② 不做折档：不许按词面把
判不了 / 看不出来 / 拿不准 / 我无法判断折成任何一态；③ V 的判词只是陈述：每一转的轴
（clean / fault）一律由 V 秘书做语义分析后给出 + 写清依据；streak / 签发只看秘书给出的轴，
不看 V 自己写的那两个字。判 fault 而 V 没给 defect_step ⇒ 秘书定出那一步。」

## 这一份的四条判据（h–k）

| # | 它守什么 | 反真空 |
|---|---|---|
| h | 同一份「V 说成立 + 零 finding」的回复，秘书打桩成必判 clean / 必判 fault ⇒ 读数跟着打桩变 | 轴若从 `verdict` 字面来，两次读数会一样 ⇒ 这条红 |
| i | 秘书调用抛异常 ⇒ 不回退成字面判（`checked=False` / `unjudged`，不签发） | 回退就会出现 clean 三转 / 签发 ⇒ 这条红 |
| j | 秘书判 fault 而 V 没给 `defect_step` ⇒ 秘书定出那一步并写进台账那一行 | 步号为空或抄 V 的 ⇒ 这条红 |
| k | 把任一「按字面定轴」的快路塞回去 ⇒ h 的读数不再成立（本条是 k 的反真空演示） | 快路存在而本条打不中 ⇒ 它不是反真空 |

零真模型调用（秘书缝是替身），零网络。
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import agent_skills as AL  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow import specs as SP  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

SID = "000007"
PROOF = "1. 由定义直接得到。\n2. 由第 1 步得到结论。"
#: h / k 用的同一份回复：V 说「成立」、零 finding。
REPLY_HOLDS = json.dumps({"verdict": "成立", "findings": []}, ensure_ascii=False)


class _Call:
    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _ReviewSeam:
    """V 自己的审阅缝：永远交同一份回复。"""

    wired = True

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.prompts.append(prompt)
        call = _Call()
        call.text = self.reply
        return call

    def asked(self) -> int:
        return len(self.prompts)


class _AxisSecretary:
    """V 的秘书替身：轴由一个数字开关决定（clean / fault / 抛异常）。

    这个替身故意不看 V 的 `verdict` —— 它模拟的是"秘书做语义分析后给轴"。
    """

    def __init__(self, axis: str = "clean", *, raise_: bool = False) -> None:
        self.axis = axis
        self.raise_ = raise_

    def judge_v_reply(self, *, reply: str = "", verdict: str = "",
                      defect_step=None, **_kw) -> dict:
        if self.raise_:
            raise RuntimeError("夹具：秘书这一问抛异常")
        return {"checked": True, "axis": self.axis,
                "decision": "没问题" if self.axis == "clean" else "有缺陷要指出",
                "reason": "夹具：秘书语义判定", "basis": ["夹具"],
                "defect_step": (3 if self.axis == "fault" else None)}

    def wash_v_reply(self, **_kw) -> dict:
        return {"checked": True, "washed": True, "text": "第 3 步需要补依据。",
                "findings": [], "dropped": [], "refused": ""}

    def decide_sign_issuance(self, *, within_call=None, **_kw) -> dict:
        ok = within_call is not None and int(within_call) >= int(VR.SIGN_STREAK_NEED)
        return {"checked": True, "issue": ok, "issued": False,
                "decision": SEC.SIGN_ISSUE if ok else SEC.SIGN_WITHHOLD,
                "streak": int(within_call or 0), "projected": int(within_call or 0),
                "need": int(VR.SIGN_STREAK_NEED), "streak_ok": ok,
                "reason": "夹具：够就签发", "basis": ["夹具"]}


def _run(tmp_path: pathlib.Path, secretary) -> dict:
    """跑一趟 `verify_proof`（storeless 路径：只落台账、不发真签）。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    agent = AgentV(None, workspace_root=root, llm=_ReviewSeam(REPLY_HOLDS),
                   secretary=secretary)
    got = agent.verify_proof(SID, proof_text=PROOF)
    rows, bad = VR.list_verifications(root, statement_id=SID, limit=None)
    assert not bad, bad
    return {"got": got, "row": (dict(rows[-1]) if rows else {}),
            "rows": [dict(r) for r in rows]}


def _passes(got: dict) -> list[tuple[str, int, str]]:
    return [(str(p.get("axis") or ""), int(p.get("streak") or 0),
             str(p.get("terminal") or ""))
            for p in (got.get("review_passes") or [])]


# ------------------------------------------------------------------ h

def test_h_the_axis_comes_from_the_secretary_not_from_the_two_letters(tmp_path):
    """h：同一份回复，秘书打桩 clean / fault ⇒ 轴、streak、签发读数跟着打桩变。

    两条都断：
    - clean：三转都 clean、streak 1/2/3、第三转 `issue=True`、台账行的轴是 clean；
    - fault：第一转就 fault、streak 0、`issue=False`、台账行的轴是 fault。
    并且两次的 `verdict` 陈述逐字相同（「成立」）—— 变的是秘书的轴，不是 V 的字。
    """
    clean = _run(tmp_path / "clean", _AxisSecretary("clean"))
    fault = _run(tmp_path / "fault", _AxisSecretary("fault"))

    assert [p[0] for p in _passes(clean["got"])] == ["clean"] * int(VR.SIGN_STREAK_NEED)
    assert [p[1] for p in _passes(clean["got"])] == list(
        range(1, int(VR.SIGN_STREAK_NEED) + 1))
    assert _passes(clean["got"])[-1][2] == "signed", _passes(clean["got"])
    assert (clean["got"].get("sign_issuance") or {}).get("issue") is True, clean["got"]
    assert VR.secretary_axis(clean["row"]) == "clean", clean["row"]

    assert _passes(fault["got"]) == [("fault", 0, "fault")], _passes(fault["got"])
    assert (fault["got"].get("sign_issuance") or {}).get("issue") is False, fault["got"]
    assert VR.secretary_axis(fault["row"]) == "fault", fault["row"]

    # 同一份回复：台账上的陈述逐字相同（「成立」），轴却相反。
    assert clean["row"]["verdict"] == fault["row"]["verdict"] == "成立"
    assert VR.read_verdict(clean["row"]) == VR.read_verdict(fault["row"]) == "成立"


# ------------------------------------------------------------------ i

def test_i_a_raising_secretary_never_falls_back_to_the_verdict(tmp_path):
    """i：秘书调用抛异常 ⇒ `checked=False` / `unjudged`，不按 V 的「成立」补判 clean。

    若回退成字面判，这份「成立 + 零 finding」会走满三转并签发 —— 下面的读数会变。
    这里要求：只判一转、轴为空、不发签、`sign_issuance.checked=False`。
    """
    got = _run(tmp_path, _AxisSecretary("clean", raise_=True))
    passes = _passes(got["got"])
    assert passes == [("", 0, "unjudged")], passes
    assert got["got"].get("checked") is False, got["got"]
    reason = str(got["got"].get("reason") or "")
    assert reason.startswith("secretary_unjudged"), reason
    assert "没查成" in reason, reason
    assert "抛异常" in str(got["got"].get("detail") or ""), got["got"].get("detail")
    assert VR.secretary_axis(got["row"]) == "", got["row"]
    assert "secretary_judge" in got["row"], (
        "新行没有秘书那一格 ⇒ 会落进历史兼容读（那一支才按 verdict 字面读）")
    assert VR.read_verdict(got["row"]) == "成立", "V 的陈述被改写了" + str(got["row"])
    assert got["got"].get("signed_bit3") is False, got["got"]
    assert not (got["got"].get("sign_issuance") or {}).get("issue"), got["got"]


# ------------------------------------------------------------------ j

class _JudgeSeam:
    """真 `Secretary` 的缝：v_reply_defect 回 fault + defect_step=3；发签那一问回不签发。"""

    wired = True

    def __init__(self) -> None:
        self.seen: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict | None, _Call]:
        self.seen.append(note)
        if note.endswith(":v_reply_defect"):
            return ({"decision": SEC.V_REPLY_FAULT, "reason": "回复指向第 3 步",
                     "basis": ["回复里说第 3 步没有依据"],
                     "defect_step": 3, "defect_step_basis": "回复原文点名第 3 步"}, _Call())
        return ({"decision": SEC.SIGN_WITHHOLD, "reason": "fault 不发签",
                 "basis": ["夹具"]}, _Call())


def test_j_a_secretary_fault_fills_the_step_when_v_omits_it(tmp_path):
    """j：秘书判 fault、V 没给 `defect_step` ⇒ 秘书定出那一步（第 3 步）并写进台账。

    V 的回复里 `findings` 的 step 写的是 4（干扰项）：台账那一行必须取秘书定的 3，
    并留下秘书的依据（`defect_step_basis`）；V 的陈述仍原样是「有毛病」。
    """
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    seam = _JudgeSeam()
    sec = SEC.Secretary("V", root=root, store=st, seam=seam, enable_model=True)
    reply = json.dumps({"verdict": "有毛病",
                        "findings": [{"level": "error", "step": 4, "kind": "无依据",
                                      "detail": "第 4 步没有依据"}]},
                       ensure_ascii=False)
    agent = AgentV(None, workspace_root=root, llm=_ReviewSeam(reply), secretary=sec)
    got = agent.verify_proof(SID, proof_text=PROOF)

    judge = dict(got.get("secretary_judge") or {})
    assert judge.get("checked") is True and judge.get("axis") == "fault", judge
    assert judge.get("defect_step") == 3, judge
    assert "第 3 步" in str(judge.get("defect_step_basis") or ""), judge
    assert got.get("defect_step") == 3, got
    assert _passes(got) == [("fault", 0, "fault")], _passes(got)
    rows = [dict(r) for r in VR.list_verifications(root, statement_id=SID, limit=None)[0]]
    assert rows and rows[-1]["defect_step"] == 3, rows[-1]
    assert rows[-1]["verdict"] == "有毛病", rows[-1]


# ------------------------------------------------------------------ k

def test_k_restoring_a_literal_fast_path_breaks_h(tmp_path, monkeypatch):
    """k：把「按 V 的 verdict 字面定轴」这条快路塞回去 ⇒ h 的读数不再成立。

    这是这条判据自己的反真空：h 之所以能证明"轴来自秘书"，前提是代码里没有一条
    `verdict == "成立" ⇒ clean` 的短路。这里真的塞回去，再跑 h 的 fault 那一半 ——
    读数必须从 fault 变成 clean（否则 h 什么也没守住）。
    """
    honest = _run(tmp_path / "honest", _AxisSecretary("fault"))
    assert _passes(honest["got"]) == [("fault", 0, "fault")], _passes(honest["got"])

    def _literal_axis(self, reply, verdict, no, *, statement_id=""):
        said = str(verdict.get("verdict") or "")
        axis = "clean" if said == "成立" else "fault"
        return {"checked": True, "axis": axis, "decision": "夹具：按字面",
                "reason": "夹具：字面快路", "basis": ["夹具"], "defect_step": None}

    monkeypatch.setattr(AgentV, "_judge_v_reply", _literal_axis)
    patched = _run(tmp_path / "patched", _AxisSecretary("fault"))
    assert [p[0] for p in _passes(patched["got"])] != ["fault"], (
        "把字面快路塞回去之后，读数仍然跟着秘书的 fault 变 ⇒ k 打不中，h 是假绿")
    assert [p[0] for p in _passes(patched["got"])] == ["clean"] * int(VR.SIGN_STREAK_NEED)
    assert (patched["got"].get("sign_issuance") or {}).get("issue") is True, patched["got"]


# ------------------------------------------------------------------ 题面：判词是陈述

def test_the_three_prompts_say_the_verdict_is_a_statement():
    """b/e：三处题面逐字写着「判词只是陈述，轴由秘书语义分析给出」。

    连同两处旧措辞一起判：① 不许再出现"按 `有毛病` 收（台账那一行..."那套字面折档；
    ② `specs/v.py` docstring 与 `agent_skills` 的引文句不再是"不许签「成立」"。
    """
    cold = VR.cold_start_prompt("对任意正整数 n，R(3,4)=9。", PROOF, readonly_facts="- 夹具")
    system = AP.system_prompt("V", registry=build_registry().registry)
    body = next(s.body for s in AL.CATALOG["V"]
                if s.slug == "复核-两态并指到那一步")
    doc = SP.builtin_specs()["V"].brief.policy
    policy_text = "\n".join(str(x) for x in doc)

    for name, text in (("cold_start_prompt", cold), ("system_prompt(V)", system),
                       ("V 手册", body), ("specs/v.py policy", policy_text)):
        assert "陈述" in text and "秘书" in text, name
        assert "按「有毛病」收" not in text, f"{name} 还留着字面折档的旧措辞"
    assert "你的 `verdict` 只是陈述，不是判据" in cold, cold[:2000]
    assert "不按字面折档" in cold or "不按字面折档" in policy_text, policy_text[:2000]
    assert "每一转的轴（clean / fault）由你的秘书" in policy_text, policy_text[:2000]
    assert "框架**不按字面折档**" in body, body[:2000]
    assert "判词只是陈述，不是判据" in system, system[:500]

    # 第 1/3 条：`verifications` 模块 docstring 合并成一段、旧句不再出现。
    vmod = str(VR.__doc__ or "")
    assert "连\"历史值按成立读并计票\"也取消了" in vmod, vmod[:2000]
    assert "一律按 `成立` 收" not in vmod, "模块 docstring 还留着旧折档句"

    # 第 2 条：护栏 docstring 改准（只改文档）——旧句不再出现、新句在。
    guard = pathlib.Path(__file__).resolve().parent / "test_v_checks_fs_citations.py"
    gtext = guard.read_text(encoding="utf-8")
    assert "结论仍是 `成立`（V 没有找到缺陷" not in gtext, "护栏 docstring 还留着旧句"
    assert "是「没查成」，不是「没问题」" in gtext, gtext[:2000]

    # 第 5 条：秘书题面把两个「判不了」分开写清。
    judge = SEC._judge_system("v_reply_defect")
    assert "两个「判不了」别混" in judge, judge[-800:]
    assert "你自己（秘书）不能拿「判不了」当结论" in judge, judge[-800:]

    # 第 6 条：两处旧句「不许签『成立』」不再出现，新句是"不签发"。
    import agentflow.specs.v as SV  # noqa: E402

    vdoc = str(SV.__doc__ or "")
    assert "不许签「成立」" not in vdoc, "specs/v.py docstring 还留着旧句"
    assert "这一份改判 `有毛病`、不签发" in vdoc, vdoc[:2000]
    assert "不许签「成立」" not in body, "agent_skills 的引文句还留着旧句"
    assert "这一份改判「有毛病」、不签发" in body, body[:2000]


def test_parse_verdict_does_not_fold_any_word(tmp_path):
    """第 1/2 条：机械解析不折档 —— 判不了 / 看不出来 / 拿不准 原样是陈述、不产轴。"""
    for word in ("判不了", "看不出来", "拿不准", "我无法判断", "成立", "有毛病"):
        got = VR.parse_verdict(json.dumps({"verdict": word, "findings": []},
                                          ensure_ascii=False))
        assert got["verdict"] == word, got
        assert VR.secretary_axis(got) == "", f"parse_verdict 自己产出了轴：{got}"
