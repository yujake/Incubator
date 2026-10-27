# -*- coding: utf-8 -*-
"""Q14：B 收录定理与证明时"消化"成自然语言 —— 不设机械闸，只钉住"改写过 ⇒ 旧签作废"。

业主口径（2026-10-26，逐字）：
「B 侧收录定理和证明时我说过要做"消化"，即改写成自然语言形式，不是照抄（不然我就不用让
B 是以智能体的形式实现了）。自然语言形式的定义是：语句连贯（不是一个字一个字蹦，有完整
的句子结构），步骤间有衔接词（不要滥用箭头），对于难懂的证明步骤适当展开」
「B 的"消化"全部不设机械阀。要在提示词上鼓励，机制上放开（不强求与来源逐字一致。但如果
改写了，V 签作废，要求 B 派 V 重新签）」

## 这一份守的五件事

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | B 的技能正文写着三条口径（完整句 / 衔接词与箭头克制 / 难懂步骤展开）＋ 正例反例，且自己声明"不设机械闸" | 改前正文一个字都没有（`proof_text` 只被描述成"逐字摘录"） |
| a2 | 负控：秘书侧没有"消化 / 箭头密度 / 散文与否"这类判据；扫描器对一行摆进去的判据有牙 | ——（今天确实没有，这一条钉住"不许长出来"） |
| b | 签过的命题被非逐字改写 ⇒ 返回里 `review_standing=stale` ＋ `resign_required` ＋ note 点名"派 V 重新签" | stale 那半是既有链（`review_standing` 读侧现算，见 `tests/test_b_supersedes_a_registered_statement.py` 的 a2）；红的是返回那一半：改前 note 只说"读侧转 stale（待复核）"，返回值里没有 `review_standing` / `resign_required` |
| c | 正控：逐字相同（没改写）⇒ 签不作废、返回不喊重签 | 钉住 b 的绿不是"任何一笔都喊重签" |
| d | 信息格：`proof_vs_source` 能读到"与来源是否逐字一致"，且它不当门（`same=false` 照写） | 改前返回值里没有这一格（全仓 `proof_vs_source` 0 命中） |
| e | 反真空：把"改写 ⇒ 旧签不算数"那一步（`_review_after_rewrite`）打桩成"已签" ⇒ b 必红 | —— |

## 为什么"改写过 ⇒ 旧签作废"不是新造判定

判据本体只有一处：`verifications.review_standing`（现行正文的 sha 与台账覆盖集比）。
`_review_after_rewrite` 只做两件事 —— 问它、把"要不要重签"翻出来。台账是追加式的，
旧签一行都不删（`verifications/<命题号>.jsonl` 仍然可查），作废是读侧现算的结论。
这一条读侧链改前就已经守着（见上表 b 那一格），本文件补的是"返回里的指路"。

全部 tmp 工作区、零模型调用（B 的真实现 + V 的写入口 `record_verification`，不花钱）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import capabilities as C  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 一条自产命题（B 从 F 的手稿登记进来的那一种）。
STATEMENT = "设 L 是椭圆上的弦长函数；则 L 不是常值函数。"
STATEMENT_TEXT = "弦长函数不是常值"

#: F 的手稿（来源）。证明正文一节里有「⇒」，正是要被消化的那一处。
#: 刻意不留尾随换行：首尾空白的差异也是一次"改写"（`_attach_proofs` 逐字比），
#: 那会让这一份判据测到别的东西（秘书落盘时会去掉尾随空白）。
SRC = ("## 证明\n\n"
       "由 P1，平行弦上的 L 同值；对调两条半轴之后同一条弦的长会变 ⇒ 矛盾 ⇒ L 非常值。")

#: B 消化后的那一份（非逐字：完整句、连接词、把「⇒」展开）。判据 b 的输入。
DIGEST = ("设 L 是弦长函数。若 L 恒为常数，则任取一组平行弦都得到同一个值；而把两条半轴"
          "对调之后，同一条弦的长度会变，这与「恒为常数」矛盾。因此 L 不是常值函数。")

_OK = {"verdict": "成立", "findings": []}


# ------------------------------------------------------------------ 小工具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _agent(st: Store) -> AgentB:
    """B 的真实现（零模型调用：这条路只碰秘书与 store）。"""
    return AgentB(st, extractor=None, extract_text=None, config={})


def _own() -> dict:
    """自产命题的两件式：`kind="conjecture"` 是这一批的入口档（B-2 的猜想放行），
    它让这一份判据只测"消化 + 签"，不测"自产定理级要不要 V 的签"那道闸。"""
    return dict(statement_full=STATEMENT, statement_text=STATEMENT_TEXT,
                origin="own_result", kind="conjecture",
                line_range={"label": "reports/attack-000000.md"},
                quote_verified=None,
                quote_reason="自产证明，没有第二份文本可比对",
                evidence_kind="heuristic")


def _row(st: Store) -> dict:
    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1, rows
    return rows[0]


def _sign(st: Store, *, proof_text: str) -> dict:
    """V 的签名写入口（`verify.verify_proof` 走的就是它；这里不经模型）。"""
    return VR.record_verification(
        st.root, statement_id=str(_row(st)["stmt_id"]), proof_text=proof_text,
        verdict=dict(_OK), verifier="agent-V", store=st, proof_no=1)


# ==================================================== a：提示词侧的三条口径与正反例

def _b_body(slug: str) -> str:
    from agentflow import agent_skills as AS

    return next(s for s in AS.CATALOG["B"] if s.slug == slug).body


def test_a_the_b_manual_says_how_to_digest_with_both_examples():
    """a：B 的技能正文给出三条口径 ＋ 正例反例，并自己声明"不设机械闸"。

    改前红：改前正文只把 `proof_text` 写成"逐字摘录"（`agent_skills.py:730-731`），
    一条叫"消化"的口径都没有 —— 于是"照抄"是唯一被写出来的做法。
    """
    body = _b_body("登记-三件式与证据三态")
    for needle in ("完整句", "衔接词", "箭头", "展开", "正例", "反例"):
        assert needle in body, f"技能正文里没有这一条口径：{needle}"
    # 三条口径各要点到"怎么算好"，不是只给一个词
    assert "不是把符号与" in body or "不是把符号" in body, "缺「不是一个字一个字蹦」那半句"
    assert "只留给" in body, "缺「箭头克制」那半句（箭头只留给一步推出）"
    assert "显然" in body and "为什么" in body, "缺「难懂步骤展开」那半句"
    # 机制侧：改写要重签，且点名真实动作
    assert "派 V 重新签" in body, "技能正文没有写「改写过 ⇒ 派 V 重新签」"
    assert "V.verify_proof" in body, "技能正文没有点名派 V 的那个动作"
    # 不设机械闸：口径不是判据，这句话必须在（它不是注释，是给模型读的边界）
    assert "不设机械闸" in body, "正文没有声明这三条是口径、不是判据"
    # 逐字只对文献引文要求（与 quote_verified 的分工）
    assert "逐字只对文献引文要求" in body, "正文没有写清逐字只对文献引文要求"
    # 目录本身仍然自洽（动作存在可达 / 工具在面上 / 落点在根表里）
    from agentflow import agent_skills as AS

    assert AS.validate() == [], AS.validate()
    # 旧的"逐字证明正文"那一条不再是指令（否则消化会被自家手册劝回去）
    taste = _b_body("审美-太平凡的不收")
    assert "把逐字证明正文交进" not in taste, "审美那一条还在要求交逐字正文"
    assert "消化的自然语言" in taste, taste[:200]


#: 秘书侧不许出现的"文案判据"词（出现即说明有人把"消化 / 箭头密度 / 散文与否"做成了
#: 可执行的判据 —— 业主 2026-10-26：「B 的消化全部不设机械阀」）。
PROSE_TOKENS: tuple[str, ...] = ("箭头", "箭头密度", "消化度", "消化程度", "散文与否",
                                 "散文占比", "完整句", "连贯", "衔接词", "句长")

#: "被写成了判据"的形状：与「消化」同现即判红。为什么单列这一条：业主原话里那个词
#: （「B 纯粹负责消化理解」）在 `secretary.py` 里出现过两次，裸 grep 会误伤它。
CRITERION_SHAPED: tuple[str, ...] = ("判据", "得分", "阈值", "密度", "打分", "评分",
                                     "score", "比例", "占比")


def _prose_criteria_problems(text: str) -> list[str]:
    """秘书侧出现的"文案判据"（空列表 = 没有）。纯函数，好给负控做牙。"""
    out: list[str] = []
    for no, line in enumerate(str(text or "").splitlines(), 1):
        for tok in PROSE_TOKENS:
            if tok in line:
                out.append(f"{no}: 秘书侧出现了文案判据的词 {tok!r}：{line.strip()[:120]}")
        if "消化" in line and any(k in line for k in CRITERION_SHAPED):
            out.append(f"{no}: 秘书侧把「消化」写成了判据形态：{line.strip()[:120]}")
    return out


def test_a2_the_negative_control_no_prose_criterion_on_the_secretary_side():
    """a2（负控）：秘书侧没有"消化 / 箭头密度 / 散文与否"这类判据。

    两半都要：
    ① 现在的 `secretary.py` 扫出来是空的（`箭头` 0 次、`连贯` 0 次、`完整句` 0 次；
       `散文` 两次都在委托解析的样例里，不判 `proof_text`；`消化` 两次都是业主原话的
       分工句 —— 所以这一条按"判据形态共现"判，不裸 grep）；
    ② 反真空：把一行判据摆进去，扫描器必须当场咬住（否则①的绿只是"没查"）。
    """
    path = _SRC / "agentflow" / "secretary.py"
    text = path.read_text(encoding="utf-8")
    assert _prose_criteria_problems(text) == [], _prose_criteria_problems(text)
    # 装置自控：被扫的确实是那个文件（不是一段空文本）
    assert "def record_statement" in text and len(text) > 100000

    planted = text + ("\n# 判据：消化度低于 0.6 ⇒ 拒收\n"
                      "# 箭头密度 > 2 判不通过\n")
    got = _prose_criteria_problems(planted)
    assert any("消化度" in p for p in got), got
    assert any("箭头密度" in p for p in got), got
    # 第二条牙：只用「消化」＋判据形态（不靠黑名单里的度量名）也必须咬住
    only_cooc = "# 判据：这一条证明消化得够不够（得分写进底座）\n"
    assert _prose_criteria_problems(only_cooc), only_cooc
    # 不咬业主原话那一句（豁免是判据的一部分：假阳性会让这条判据变成噪音）
    assert _prose_criteria_problems("依赖，实现用二维列表）、查工具，B纯粹负责消化理解。」") == []


# ==================================================== b：改写过 ⇒ 旧签不算数 + 派 V 重签

def _b_must_hold(got: dict, st: Store, sid: str) -> None:
    """判据 b 的全部断言（独立成函数，判据 e 要靠它证明"打桩之后这里必红"）。"""
    reading = dict(got.get("review_standing") or {})
    assert reading.get("state") == "stale", reading
    assert reading.get("checked") is True, reading
    assert reading.get("canonical_changed") is True, reading
    assert got.get("resign_required") is True, got
    note = str(got.get("note") or "")
    assert "正文被改写过" in note and "不算数" in note, note
    assert "派 V 重新签" in note, note
    # 真实动作名与形参（不是"命题号 + 第几条"这种自家话）
    assert "V.verify_proof" in note, note
    assert "statement_id" in note and "proof_no" in note, note
    # 读侧（唯一判定口）也是 stale —— 返回里的那一格不是另算的
    standing = VR.review_standing(st.root, statement_id=sid, proof_text=DIGEST, proof_no=1)
    assert standing["state"] == "stale", standing
    assert standing["ok"] is False and standing["in_sync"] is False, standing


def test_b_rewriting_the_proof_voids_the_old_signature_and_points_at_v(tmp_path):
    """b：签过的命题被非逐字改写 ⇒ `review_standing=stale` ＋ 返回点名"派 V 重新签"。

    改前红：写入成功、读侧也已经是 stale（既有链），但返回值里没有 `review_standing` /
    `resign_required`，note 只说"读侧转 stale（待复核）"—— 读的人不知道下一步该干什么。

    这一笔还钉住三件"没被破坏"的事：行上的正文真的换成了消化的那一份、旧正文进
    `proof_history`、台账那一签一行都没删（作废是读侧现算，不是框架删签）。
    """
    st = _ws(tmp_path)
    first = _agent(st).register_statement(**_own(), proof_text=SRC, proof_manuscript=SRC)
    assert first["ok"] is True, first
    sid = str(_row(st)["stmt_id"])

    signed = _sign(st, proof_text=SRC)
    assert str(signed.get("verification_id") or "").startswith("v-"), signed
    assert EB.bits_from_row(_row(st))["reviewed"] is True, "正控：签完之后第 3 位必须是 True"

    got = _agent(st).register_statement(**_own(), proof_text=DIGEST, proof_manuscript=SRC)
    assert got["ok"] is True, got
    assert got.get("canonical_written") is True, got
    _b_must_hold(got, st, sid)

    row = _row(st)
    assert row["proof_text"] == DIGEST, row["proof_text"]
    history = [dict(h) for h in (row.get("proof_history") or [])]
    assert history, "旧正文没有留痕"
    last = history[-1]
    assert last["text"] == SRC and last["sha"] == VR.proof_sha(SRC), last
    assert last["replaced_by"] == VR.proof_sha(DIGEST), last
    assert EB.bits_from_row(row)["reviewed"] is False, row.get("bits")
    rows, problems = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert problems == [], problems
    assert [r["verification_id"] for r in rows] == [signed["verification_id"]], (
        "旧签被删了 —— 作废是读数，不是删记录")


def test_b2_the_action_and_params_named_in_the_note_are_real(tmp_path):
    """b2：note 里点名的动作与形参逐个对工具声明核过（今晚被"不存在的形参"咬过一次）。

    `V.verify_proof`：`statement_id` 必填、`proof_no` 是它自己的形参、`additionalProperties`
    为假（所以只能给这几个名字）。这条判据让 note 里那句话不能自己编。
    """
    spec = C.find_action("V", "verify_proof")
    assert spec is not None, "capabilities 里没有 V.verify_proof"
    assert spec.role == "V" and spec.action == "verify_proof", spec
    params = dict(spec.params or {})
    props = dict(params.get("properties") or {})
    assert "statement_id" in props, sorted(props)
    assert "proof_no" in props, sorted(props)
    assert list(params.get("required") or []) == ["statement_id"], params.get("required")
    assert params.get("additionalProperties") is False, params
    # 与 B 的出边也一致：B 派得动 V（note 里让 B 去派它，不是一句做不到的指令）
    assert "V" in set(C.ALLOWED_EDGES.get("B", ())), sorted(C.ALLOWED_EDGES.get("B", ()))


# ==================================================== c：逐字相同 ⇒ 签不作废

def test_c_the_same_text_keeps_the_signature_alive(tmp_path):
    """c（正控）：原样再交一次（逐字相同）⇒ 签不作废、返回也不喊重签。

    这一条挡的是"任何一笔都说旧签作废"那种假绿：`canonical_changed` 为假 ⇒ 不进改写
    那一格 ⇒ 没有 `review_standing=stale`，行上的签照旧算数。
    """
    st = _ws(tmp_path)
    first = _agent(st).register_statement(**_own(), proof_text=SRC, proof_manuscript=SRC)
    assert first["ok"] is True, first
    sid = str(_row(st)["stmt_id"])
    signed = _sign(st, proof_text=SRC)

    again = _agent(st).register_statement(**_own(), proof_text=SRC, proof_manuscript=SRC)
    assert again.get("canonical_written") is not True, again
    assert again.get("resign_required") is not True, again
    note = str(again.get("note") or "")
    assert "派 V 重新签" not in note, note
    assert "不算数" not in note, note
    assert "review_standing" not in note, note

    row = _row(st)
    assert row["proof_text"] == SRC, row["proof_text"]
    assert not (row.get("proof_history") or []), row.get("proof_history")
    standing = VR.review_standing(st.root, statement_id=sid, proof_text=SRC, proof_no=1)
    assert standing["state"] == "signed", standing
    assert standing["verification_id"] == signed["verification_id"], standing
    assert EB.bits_from_row(row)["reviewed"] is True, row.get("bits")


# ==================================================== d：信息格，不当门

def test_d_verbatim_vs_source_is_an_information_grid_not_a_gate(tmp_path):
    """d：`proof_vs_source` 读得到"与来源是否逐字一致"，而且它不拦写入。

    改前红：返回值里没有这一格。这一条同时钉住它"不是门"：`same=false` 的那一笔
    照样落盘（消化本来就会让 same 为假）。
    """
    from agentflow.agent_b import register_statement as RS

    st = _ws(tmp_path)
    got = _agent(st).register_statement(**_own(), proof_text=DIGEST, proof_manuscript=SRC)
    assert got["ok"] is True, got
    grid = dict(got.get("proof_vs_source") or {})
    assert grid.get("checked") is True, grid
    assert grid.get("same") is False, grid
    assert grid.get("matched") == "", grid
    assert grid.get("source") == DS.SOURCE_PARAM, grid
    # 不当门：same=false 的正文照样写进了盘上那一行
    assert _row(st)["proof_text"] == DIGEST

    # 行上能读到：同一个函数吃在册那一行，结论一样（判据只这一处）
    off_row = RS.verbatim_vs_source(row=_row(st), source_text=SRC, source=DS.SOURCE_PARAM)
    assert off_row["checked"] is True and off_row["same"] is False, off_row
    # 反真空：把正文换成来源原样 ⇒ 这一格真的会说"逐字"（否则它恒假）
    same = RS.verbatim_vs_source(row={"proof_text": SRC}, source_text=SRC,
                                 source=DS.SOURCE_PARAM)
    assert same["same"] is True and same["matched"] == "manuscript", same
    # 没有来源正文时是"没有对象"，不是"不一致"
    none = RS.verbatim_vs_source(row={"proof_text": DIGEST})
    assert none["checked"] is False and none["same"] is None, none


# ==================================================== e：反真空

def test_e_stubbing_the_rewrite_reading_turns_b_red(tmp_path, monkeypatch):
    """e（反真空）：把"改写 ⇒ 旧签不算数"那一步打成"已签" ⇒ b 的断言必红。

    打桩点就是判定点（`AgentB._review_after_rewrite`）：它一变成恒"已签"，返回里那一格
    与 note 的指路同时消失 —— 于是 b 的绿确实来自这一步，不是来自别处顺手写的分支
    （读侧 `review_standing` 仍然是 stale：这一条打桩不碰既有链，正好说明 b 的返回
    那一格是新增的那一步给的）。
    """
    monkeypatch.setattr(
        AgentB, "_review_after_rewrite",
        staticmethod(lambda root, *, stmt_id, proof_text: {
            "checked": True, "state": "signed", "resign_required": False,
            "verification_id": "v-stub", "proof_sha256": "",
            "canonical_changed": True, "why": "夹具：打桩成已签"}),
        raising=True)

    st = _ws(tmp_path)
    _agent(st).register_statement(**_own(), proof_text=SRC, proof_manuscript=SRC)
    sid = str(_row(st)["stmt_id"])
    _sign(st, proof_text=SRC)

    got = _agent(st).register_statement(**_own(), proof_text=DIGEST, proof_manuscript=SRC)
    assert got["ok"] is True, got
    assert (got.get("review_standing") or {}).get("state") == "signed", got.get("review_standing")
    assert got.get("resign_required") is False, got
    assert "派 V 重新签" not in str(got.get("note") or ""), got.get("note")
    # b 必红：同一组断言在打桩之后必须失败
    with pytest.raises(AssertionError):
        _b_must_hold(got, st, sid)
    # 而既有链没被打桩：读侧仍然是 stale（b 的返回那一格才是这一步给的）
    assert VR.review_standing(st.root, statement_id=sid, proof_text=DIGEST,
                              proof_no=1)["state"] == "stale"
