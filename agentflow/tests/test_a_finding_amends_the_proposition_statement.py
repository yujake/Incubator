# -*- coding: utf-8 -*-
"""由 V 的 finding 触发的「命题表述改动」（业主 2026-11-16 裁定 6，MST1 路）。

裁定原文（逐字，这就是本文件的验收标准）：

> 「我之前以为你要对着V的finding追踪改证明内容，现在我理解了你是要根据finding改命题表述，
>   这是有道理的，但需要再过命题表述闸且不申请新稿号而是沿用稿号和稿并自动修改稿中命题描述
>   为过闸的描述，然后继续edit。若命题有大问题，建议走math_error放弃命题」

## 改前是什么形态（AH5 现场，缺陷本体）

`proofregistry.register_or_rewrite` 只要发现 `## 命题` 的规范化指纹变了就整笔受控拒
（`proposition_text_changed`）。AH5 那一笔：F 为修第 12 步顺手把 `[1,∞)` 改成 `[1,∞]`
一个字符 ⇒ 整笔拒 ⇒ 盘上一个字节没写（连改对的那一步也退回去了）。

## 判据一览

| # | 造什么 | 期望 |
|---|---|---|
| a1 | V 判过「有毛病」的稿，只改命题表述（正文不动） | 过闸 ⇒ `ok`、稿号不变、`## 命题` 被自动改写、`## 证明` 分节哈希逐字不变 |
| a2 | AH5 现场：同一次写入既改第 12 步、又改一个字符的表述 | 整笔落盘（改前：整笔拒、一个字节没写） |
| b | 表述改动、闸判不过 | 受控拒 `proposition_form_refused` + 逐条点名缺什么；盘上一个字节不动 |
| c | 不是 finding 触发的表述改动（三种造法） | 受控拒 `proposition_text_changed`，读数说 `triggered=False` |
| d | 反真空 | 闸打桩恒真 ⇒ b 必红；触发读数打桩恒真 ⇒ c 必红 |
| e | 稿号逐字相同 | 路径字符串、`entries_on_disk` 恰好 1 条、`reports/` 里没有第二份稿 |

## 零模型调用

形态闸用替身（只记调用次数 / 可切"判不过"），V 的 finding 走真写口
`verifications.record_pending_sign`（不是手写 JSONL），落稿与重写走真的 `proofregistry`。
"""
from __future__ import annotations

import json
import pathlib

import pytest
from agentflow import manuscriptform as MF
from agentflow import proofoutcomes as PO
from agentflow import proofregistry as R
from agentflow import statementamend as SA
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import AgentF
from agentflow.store import Store

PLAN = "0000"
SID = "s1"
MID = "000041"
LABEL = f"F 攻坚 {PLAN} 子目标 {SID}"
REL = f"reports/f-proof-{MID}.md"
#: 一个字符的表述改动（`[1,∞)` → `[1,∞]`）：AH5 现场就是这么一笔。
PROP_OLD = "设 f 在 [1,∞) 上连续且可积，则 f 在该区间上一致连续。"
PROP_NEW = "设 f 在 [1,∞] 上连续且可积，则 f 在该区间上一致连续。"
BODY = "第 1 步：取 δ=ε。\n第 2 步：逐点验证 |x-y|<δ ⇒ |f(x)-f(y)|<ε。"
BODY_FIXED = ("第 1 步：取 δ=ε。\n"
              "第 12 步：用紧性把逐点控制换成一致控制（按 V 的缺陷修这一条）。")


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _gate_ok(**kw):
    return {"checked": True, "well_formed": True, "submittable": True,
            "conditions": "设 f 在 [1,∞] 上连续且可积", "conclusion": "则 f 一致连续",
            "problems": [], "decision": "夹具：形态合规", "refused": "",
            "reason": "夹具：形态合规", "actor": "secretary-F"}


def _gate_bad(**kw):
    return {"checked": True, "well_formed": False, "submittable": False,
            "conditions": "", "conclusion": "",
            "problems": ["结论不是可判真假的断言：这一段写的是修订说明"],
            "decision": "夹具：形态不合规", "refused": "proposition_form_refused",
            "reason": "这一节写成了作业话，不是一个定理陈述", "actor": "secretary-F"}


class _Gate:
    """形态闸替身：记下每一次调用（判据 d 要数它到底跑没跑）。

    两种入口都要有，因为"过闸"在生产代码里有两个调用面：
    - `__call__(**kw)`：`proofregistry` 的 `gate` 回调（登记 / 改表述那一笔）；
    - `judge_proposition_form(**kw)`：F 的秘书那一问（`_proposition_form_gate` 在
      写盘之前先问一次）。
    两个面返回同一份判据读数 —— 这正是"判据只有一处"在夹具上的形态。
    """

    def __init__(self, *, ok: bool = True) -> None:
        self.ok = bool(ok)
        self.calls: list[dict] = []

    def __call__(self, **kw):
        self.calls.append(dict(kw))
        return _gate_ok(**kw) if self.ok else _gate_bad(**kw)

    def judge_proposition_form(self, **kw):
        return self(**kw)

    def wash_dependency_face(self, text: str, **_kw) -> dict:
        """依赖面洗稿那一问（F 的每一轮都要问；夹具：本来就合规、没动一个字）。"""
        return {"checked": True, "text": str(text), "actor": "secretary-F",
                "washed": False, "deps_refused": "", "deps_refused_findings": [],
                "deps_section_filled": "", "deps_washing": [],
                "reason": "夹具：依赖面本来就合规"}


def _register(st: Store, *, proposition: str = PROP_OLD, proof_text: str = BODY,
              gate=None) -> dict:
    return R.register_or_rewrite(
        st.root, family=MF.FAMILY_F, label=LABEL, proposition=proposition,
        proof_text=proof_text, manuscript_id=MID, kind="conjecture",
        title="夹具：命题表述改动", gate=gate or _Gate())


def _rewrite(st: Store, *, proposition: str = PROP_NEW, proof_text: str = BODY,
             gate=None) -> dict:
    return _register(st, proposition=proposition, proof_text=proof_text, gate=gate)


def _fault(st: Store, proof_text: str = BODY, *, axis: str = "fault",
           rel: str = REL) -> dict:
    """V 对「这一份正文」落一行（真写口 `record_pending_sign`，未在册那一支）。

    `axis` 由秘书给（`secretary_judge.axis`）—— 这正是读侧唯一的轴来源：
    V 的判词只是陈述，不是轴。
    """
    defect = axis == "fault"
    return VR.record_pending_sign(
        str(st.root), proof_text=proof_text,
        verdict={"verdict": "有毛病" if defect else "成立",
                 "defect_step": 12,
                 "findings": ([{"level": "error", "step": 12, "kind": "无依据的步骤",
                                "detail": "第 12 步直接用了结论"}]
                              if defect else [])},
        object_path=rel,
        secretary_judge={"checked": True, "axis": axis,
                         "decision": "夹具：秘书的语义判定",
                         "reason": "夹具：带步号的缺陷" if defect else "夹具：核过"})


def _text(st: Store) -> str:
    return (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")


def _proposition(st: Store, text: str | None = None) -> str:
    _head, sections = R.split_sections(_text(st) if text is None else text)
    return next((body for name, body in sections if name == "命题"), "").strip()


# ------------------------------------------------------------------ a1：finding 触发 + 过闸

def test_a1_a_finding_reasons_statement_change_lands_on_the_same_number(tmp_path):
    """a1：V 判过「有毛病」⇒ 表述改动过闸之后就位改 `## 命题`，正文分节哈希逐字不动。"""
    st = _ws(tmp_path)
    gate = _Gate()
    first = _register(st, gate=gate)
    assert first["ok"] is True, first
    assert first["mode"] == "registered", first
    text1 = _text(st)
    prop_hash1 = R.section_hashes(text1)["## 命题"]
    proof_hash1 = R.section_hashes(text1)["## 证明"]
    assert _proposition(st) == PROP_OLD.strip()

    _fault(st)  # V 对当前正文判「有毛病」（AH5 的那一行 u-000005）

    second = _rewrite(st, gate=gate)
    assert second["ok"] is True, second
    assert second["mode"] == "rewritten", second
    assert second["written"] is True, second

    amend = dict(second.get("proposition_amend") or {})
    assert amend.get("ok") is True, amend
    assert amend.get("triggered") is True, amend
    assert amend.get("trigger_axis") == "fault", amend
    assert amend.get("trigger_verification_id", "").startswith("u-"), amend
    assert amend.get("proposition_before") == PROP_OLD, amend
    assert amend.get("proposition_after") == PROP_NEW, amend
    assert amend.get("fingerprint_before") == R.proposition_fingerprint(PROP_OLD), amend
    assert amend.get("fingerprint_after") == R.proposition_fingerprint(PROP_NEW), amend
    # 过闸的读数要带回去：F 下一步看得见"这一段是过闸之后的表述"。
    gate_reading = dict(second.get("gate") or {})
    assert gate_reading.get("submittable") is True, gate_reading
    # 闸真的跑了第二次（这一次是"改表述"的那一道，不是登记那一道）
    assert len(gate.calls) == 2, gate.calls
    assert gate.calls[-1]["statement_full"] == PROP_NEW, gate.calls[-1]

    text2 = _text(st)
    hashes2 = R.section_hashes(text2)
    assert hashes2["## 证明"] == proof_hash1, "改表述不许动 `## 证明`（签盖的是那一段）"
    assert hashes2["## 命题"] != prop_hash1, "`## 命题` 必须被自动改写成过闸的那一版"
    assert _proposition(st) == PROP_NEW.strip()
    # 正文 sha 与登记条目里的指纹都跟着这一笔走（同一把尺：`proofregistry`）
    assert second["sha256"] == first["sha256"], (first["sha256"], second["sha256"])
    assert R.parse_entry(text2)["fingerprint"] == R.proposition_fingerprint(PROP_NEW)
    assert len(list(st.rows("statements"))) == 0, "F 这一侧不写 statements（登记仍是 B 的事）"


# ------------------------------------------------------------------ a2：AH5 现场

def test_a2_the_ah5_write_lands_instead_of_being_refused_whole(tmp_path):
    """a2：同一次写入既改第 12 步、又改一个字符的表述 ⇒ 整笔落盘。

    改前（AH5）：整笔受控拒 `proposition_text_changed`、盘上一个字节没写，
    于是下一版把改对的那一步退回原样 —— 这一条钉的就是"不许再整笔拒"。
    """
    st = _ws(tmp_path)
    first = _register(st)
    assert first["ok"] is True, first
    _fault(st)  # 针对的是盘上那一份正文（BODY）

    got = _rewrite(st, proof_text=BODY_FIXED)
    assert got["ok"] is True, got
    assert got["mode"] == "rewritten", got
    text = _text(st)
    assert _proposition(st) == PROP_NEW.strip(), "表述那一笔没落下"
    assert "第 12 步" in R.split_sections(text)[1][
        [n for n, _ in R.split_sections(text)[1]].index("证明")][1], text
    assert got["sha256"] == R.proof_sha(text) != first["sha256"]
    entry = R.parse_entry(text)
    assert entry["sha256"] == got["sha256"], entry
    assert len(entry["versions"]) == 1, entry


# ------------------------------------------------------------------ a3：生产路径（attack.step）

class _ProofSeam:
    """F 的那条缝：只喂一轮 proof 档的产出（不联网、不起模型）。"""

    def __init__(self, body: str, proposition: str) -> None:
        self.body = str(body)
        self.proposition = str(proposition)

    def complete(self, prompt: str) -> str:
        return json.dumps({"product": "proof", "proposition": self.proposition,
                           "strategy": "套用已知定理",
                           "why_strategy": "夹具：由在册定理逐条读出",
                           "steps": [{"n": 1, "text": self.body,
                                      "cites": [], "assumption": True}]},
                          ensure_ascii=False)


def test_a3_the_production_path_keeps_editing_after_the_amendment(tmp_path):
    """a3：走真的 `attack.step` 入口 —— finding 触发的那一笔落盘后，F 还能继续改。

    这一条盯的是"生产路径上没有第二道整笔拒"：直调 `register_or_rewrite` 通不代表
    `AgentF.step` 通（它前面还有写前闸、稿号沿用、冻结读数几格）。
    """
    st = _ws(tmp_path)
    stub = _Gate()
    f = AgentF(st, config={"workspace_root": str(st.root)},
               llm=_ProofSeam(BODY, PROP_OLD))
    f.f_secretary = stub
    plan = f.create_plan("引理：由定义推出目标结论", "PK-MST1", subgoals=[
        {"sid": "s1", "text": "由定义推出目标结论", "owner": "F",
         "testable": "同一命题的表述改动之后还能继续改证明"}])
    pid = str(plan["plan_id"])
    first = dict(f.step(pid))
    assert first.get("proof_mode") == "registered", first
    mid = str(first.get("manuscript_id") or "")
    assert mid, first
    rel = f"reports/f-proof-{mid}.md"
    body_on_disk = VS.manuscript_proof_body(
        (pathlib.Path(st.root) / rel).read_text(encoding="utf-8"))
    #: V 判过「有毛病」—— 行落在**盘上这一段正文**上（AH5 现场的那一行）。
    VR.record_pending_sign(
        str(st.root), proof_text=body_on_disk, object_path=rel,
        verdict={"verdict": "有毛病", "defect_step": 1,
                 "findings": [{"level": "error", "step": 1, "kind": "无依据的步骤",
                               "detail": "第 1 步直接用了结论"}]},
        secretary_judge={"checked": True, "axis": "fault", "reason": "夹具：秘书的语义判定"})

    f.llm = _ProofSeam(BODY_FIXED, PROP_NEW)
    second = dict(f.step(pid))
    assert second.get("proof_mode") == "rewritten", second
    assert str(second.get("manuscript_id")) == mid, second
    text = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    _head, sections = R.split_sections(text)
    assert next(b for n, b in sections if n == "命题").strip() == PROP_NEW.strip()
    assert "第 12 步" in next(b for n, b in sections if n == "证明")
    # 形态闸跑了两次：登记一次、改表述一次（第二次判的就是过闸之后写下去的那一段）
    assert len(stub.calls) == 2, stub.calls
    assert stub.calls[-1]["statement_full"] == PROP_NEW, stub.calls[-1]


# ------------------------------------------------------------------ b：过闸判据在承重

def test_b_a_statement_change_that_misses_the_gate_is_refused_and_named(tmp_path):
    """b：finding 触发了，而新表述过不了形态闸 ⇒ 受控拒并点名，盘上一个字节不动。"""
    st = _ws(tmp_path)
    first = _register(st)
    assert first["ok"] is True, first
    _fault(st)
    before = _text(st)

    got = _rewrite(st, gate=_Gate(ok=False))
    assert got["ok"] is False, got
    assert got["refused"] == "proposition_form_refused", got
    assert got["written"] is False and got["preserved"] is False, got
    why = str(got.get("why") or "")
    assert "形态闸没放行" in why, why
    assert "结论不是可判真假的断言" in why, why  # 点名缺什么
    assert _text(st) == before, "闸判不过却动了盘上的稿"
    amend = dict(got.get("proposition_amend") or {})
    assert amend.get("ok") is False, amend
    assert amend.get("triggered") is True, amend
    assert dict(amend.get("gate") or {}).get("well_formed") is False, amend


# ------------------------------------------------------------------ c：没有 finding ⇒ 照旧受控拒

def test_c1_without_a_finding_a_statement_change_is_still_refused(tmp_path):
    """c1：没有任何 V 的 finding ⇒ 照旧受控拒 `proposition_text_changed`。

    这是刻意保留的那条纪律（"不许用挂证明改命题正文"）：放行的只有
    "V 对这一份正文判过有毛病"这一档，不是"谁想改就改"。
    """
    st = _ws(tmp_path)
    gate = _Gate()
    first = _register(st, gate=gate)
    assert first["ok"] is True, first
    before = _text(st)

    got = _rewrite(st, gate=gate)
    assert got["ok"] is False, got
    assert got["refused"] == "proposition_text_changed", got
    why = str(got.get("why") or "")
    assert "命题正文与登记条目里那一条不一致" in why, why
    assert "放弃" in why and "换号" in why, why
    assert _text(st) == before, "受控拒却动了盘上的稿"
    amend = dict(got.get("proposition_amend") or {})
    assert amend.get("ok") is False and amend.get("triggered") is False, amend
    assert len(gate.calls) == 1, "没触发就不该白跑一次形态闸"


def test_c2_a_finding_that_was_superseded_by_a_clean_verdict_is_not_a_trigger(tmp_path):
    """c2：先「有毛病」、后「成立」（同一份正文）⇒ 最新那一行说了算，不算 finding 触发。"""
    st = _ws(tmp_path)
    _register(st)
    _fault(st)
    _fault(st, axis="clean")   # 同一份正文的更新一行（追加序在后）
    before = _text(st)

    got = _rewrite(st)
    assert got["ok"] is False, got
    assert got["refused"] == "proposition_text_changed", got
    assert _text(st) == before
    amend = dict(got.get("proposition_amend") or {})
    assert amend.get("triggered") is False, amend
    assert amend.get("trigger_axis") == "clean", amend


def test_c3_a_finding_on_another_body_is_not_a_trigger(tmp_path):
    """c3：finding 落在别的一段正文上 ⇒ 不是这一份的 finding，受控拒。"""
    st = _ws(tmp_path)
    _register(st)
    _fault(st, "另一段正文：这是别人家的证明。")
    before = _text(st)

    got = _rewrite(st)
    assert got["ok"] is False, got
    assert got["refused"] == "proposition_text_changed", got
    assert _text(st) == before
    assert dict(got.get("proposition_amend") or {}).get("triggered") is False, got


# ------------------------------------------------------------------ d：反真空

def test_d1_stubbing_the_gate_to_always_pass_makes_b_red(tmp_path, monkeypatch):
    """d①：把"过闸"判据打桩成恒真 ⇒ b 的"受控拒"当场不成立（闸在承重）。"""
    monkeypatch.setattr(PO, "form_gate_reading",
                        lambda _gate, **_kw: ({"checked": True, "well_formed": True,
                                               "submittable": True, "problems": []}, None))
    st = _ws(tmp_path)
    _register(st)
    _fault(st)
    got = _rewrite(st, gate=_Gate(ok=False))
    # 打桩生效：判不过的闸不再挡得住（盘上真的写了）
    assert got["ok"] is True, got
    with pytest.raises(AssertionError):
        assert got["ok"] is False, "闸打桩恒真之后 b 不再成立 ⇒ 过闸那一格在承重"
    # 反过来说明 b 不是同义反复：判据 b 断言的就是"闸判不过 ⇒ 不受控拒"的反面
    assert got["proposition_amend"]["gate"]["submittable"] is True


def test_d2_stubbing_the_trigger_to_always_fault_makes_c_red(tmp_path, monkeypatch):
    """d②：把"是不是 finding 触发"打桩成恒真 ⇒ c1 的受控拒当场不成立。"""
    monkeypatch.setattr(SA, "trigger_reading",
                        lambda *_a, **_kw: {"checked": True, "triggered": True,
                                            "axis": "fault", "rows": 1,
                                            "verification_id": "u-000001",
                                            "defect_step": 12, "at": "", "findings": [],
                                            "problems": [], "why": "打桩：恒有 finding"})
    st = _ws(tmp_path)
    _register(st)
    got = _rewrite(st)
    assert got["ok"] is True, got
    with pytest.raises(AssertionError):
        assert got["ok"] is False, "触发读数打桩恒真之后 c1 不再成立 ⇒ 触发布在承重"
    assert dict(got.get("proposition_amend") or {}).get("triggered") is True, got


# ------------------------------------------------------------------ e：稿号逐字相同

def test_e_the_manuscript_number_is_byte_identical_before_and_after(tmp_path):
    """e：改动前后稿号逐字相同（路径 / 落点 / 盘上份数三处一起钉住）。"""
    st = _ws(tmp_path)
    first = _register(st)
    assert first["ok"] is True, first
    path_before = str(first["manuscript_path"])
    entries_before = R.entries_on_disk(st.root)
    _fault(st)
    second = _rewrite(st)
    assert second["ok"] is True, second
    path_after = str(second["manuscript_path"])
    # 逐字相同（不是"解析后相等"）
    assert path_after.encode() == path_before.encode() == REL.encode()
    assert str(second["manuscript_id"]) == str(first["manuscript_id"]) == MID
    entries_after = R.entries_on_disk(st.root)
    assert len(entries_before) == len(entries_after) == 1, (entries_before, entries_after)
    assert entries_after[0]["path"] == entries_before[0]["path"], (entries_before, entries_after)
    files = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("f-proof*.md"))
    assert files == [f"f-proof-{MID}.md"], files
    assert not list((pathlib.Path(st.root) / "reports").glob("*-v*.md")), "不许新落一份稿"
