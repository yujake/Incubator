# -*- coding: utf-8 -*-
"""B 改稿后无 V 签就入库 ⇒ 拒信必须给「请重新拿 V 签」+ 可执行路径。

## 业主裁定（2026-11-01，逐字）

> 「要鼓励B的改写，即改后无V签就想入库时报告"请重新拿V签"，而非只说对不上。
>   同理，其它拒都最好要回复一句原因，一句建议」

## 这一份钉住的四件事

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | stale（签过旧版、改了一个字）⇒ 拒信含事实句 + `建议：请重新拿 V 签`，且建议落在前 400 字 | 改前只说「没有一份「成立」的签盖住这一份正文」+ 两条路，其中 ② 先送 V 是假出路 |
| b | 照建议真的走通：按 `kind="conjecture"` 重交（新正文上盘）→ `verify_proof`（不传 proof_text）→ 3 次 clean → 秘书发签 → `out/vsigns/<sha(P2)>.json` 在盘上 | 改前 ② 没写这一步，照它做会撞 `proof_text_mismatch`（新正文还没上盘） |
| c | 反真空：原样入库（sha 一致、签盖着它）⇒ 不出现「请重新拿 V 签」 | 只加文案的改法会对着没改的人也喊重签 |
| d | 三个分支不抹平：unsigned ⇒「请拿 V 签」（不是「重新」）；rejected ⇒「按 findings 改完再送」（不是「重签」） | 一句通用文案会把三种处置说成同一件事，尤其 rejected 会误导人原样重送 |

零模型调用：V 的审阅缝与秘书缝都是夹具（与 `test_v_reviews_three_times_before_signing`
同一套替身），一次真模型都不发。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from conftest import (reset_bit3_cache, seed_statement_row,  # noqa: E402
                      sign_for_the_gate)
from agentflow import depsection as DS             # noqa: E402
from agentflow import evidencebits as EB          # noqa: E402
from agentflow import schema as S                 # noqa: E402
from agentflow import secretary as SEC            # noqa: E402
from agentflow import verifications as VR          # noqa: E402
from agentflow import vsigns as VSP                # noqa: E402
from agentflow.agent_b import AgentB               # noqa: E402
from agentflow.agent_v import AgentV               # noqa: E402
from agentflow.store import Store                  # noqa: E402


def _judge_for(verdict: dict) -> dict:
    """夹具：按这一行的判词给秘书的轴（只给两态；「有毛病」⇒ fault）。

    2026-11-06 裁定 2 之后，台账的轴只能来自秘书。夹具写的是"这一行当年怎么判的"，
    所以轴跟着判词走：成立 ⇒ clean、有毛病 ⇒ fault、其余（看不出来一类）⇒ 空轴。
    这不是"按字面定轴"—— 这条断言在夹具里，是声明这一段是什么现场，不是判据。
    """
    word = str((verdict or {}).get("verdict") or "")
    if word == "成立":
        return {"checked": True, "axis": "clean", "decision": "没问题",
                "reason": "夹具：秘书判 clean"}
    if word == "有毛病":
        return {"checked": True, "axis": "fault", "decision": "有缺陷要指出",
                "reason": "夹具：秘书判 fault"}
    return {"checked": False, "axis": "", "decision": "",
            "reason": "夹具：判词不是两态，秘书没给轴"}

SID = "000000"
FULL = "设 G 是 3-正则群；则弦长函数不是常值（重签判据）。"
TEXT = "弦长函数不是常值（重签判据）"
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
P2 = P1 + "\n3. 补一步（改稿）。"
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
OWN = {"statement_full": FULL, "statement_text": TEXT, "origin": "own_result", "derived_from": ["999999"],
       "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}
OK = {"verdict": "成立", "findings": []}
BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
       "findings": [{"level": "error", "step": 2, "kind": "无依据的步骤",
                     "detail": "第 2 步直接用了结论"}]}
CLEAN_REPLY = json.dumps({"verdict": "成立", "why": "试了几种反例构造都失败，未发现问题。",
                          "findings": []}, ensure_ascii=False)


# ------------------------------------------------------------------ 夹具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None, config={})


def _row(st: Store) -> dict:
    hit = [dict(r) for r in st.rows("statements")]
    assert len(hit) == 1, hit
    return hit[0]


def _conjecture(st: Store, text: str) -> dict:
    """第一笔：直接铺行造"在册、有证明、还没签"的历史形态。

    2026-11-02 准入闸 strict 之后，无签的证明正文经 `register_statement` 写不进去
    （整笔拒 `proof_without_v_sign`）—— 而这一组测的是"改稿/重签"那几档的拒信。
    已在册时仍走真登记（改稿那一笔要量 `canonical_written`）。
    """
    if not st.rows("statements"):
        seeded = seed_statement_row(
            st, proof_text=text, statement_full=FULL, statement_text=TEXT,
            kind="conjecture", label=TEXT, quote_verified=None,
            quote_reason=OWN["quote_reason"],
            doc_id=S.format_id(0), line_range={"start": None, "end": None, "label": ""},
            # bits 按 B 真登记会落下的那一份现算（proof 位真、reviewed 假）——
            # 升档那一格（D-37）读的就是它。
            bits=EB.bits_of(origin="own_result", proof=True, proof_process=text,
                            kind="conjecture"))
        return {"ok": True, "stmt_id": str(seeded["stmt_id"]), "new_row": True}
    return _b(st).register_statement(**{**OWN, "kind": "conjecture"}, proof_text=text)


def _theorem(st: Store, text: str) -> dict:
    return _b(st).register_statement(**{**OWN, "kind": "theorem"}, proof_text=text)


def _sign(st: Store, text: str, *, verdict: dict | None = None, times: int = 1) -> None:
    """V 的签名写入口（`verify.verify_proof` 走同一个落点；这里不经模型）。"""
    for _ in range(int(times)):
        VR.record_verification(st.root, statement_id=SID, proof_text=text,
                               verdict=dict(verdict or OK), verifier="agent-V",
                               store=st, proof_no=1, secretary_judge=_judge_for(dict(verdict or OK)))


class _Call:
    """`llmseam.SeamCall` 的替身（`ask` / `judge` 只读这几个属性）。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _ReviewSeam:
    """V 自己的审阅缝：每次问都给一份干净的「成立」回复，并记次数。"""

    wired = True

    def __init__(self) -> None:
        self.n = 0

    def ask(self, prompt: str = "", **_kw) -> _Call:
        self.n += 1
        call = _Call()
        call.text = CLEAN_REPLY
        return call

    def asked(self) -> int:
        return self.n


class _Seam:
    """秘书的缝：`v_reply_defect` 判 clean，`sign_issuance` 判签发。"""

    wired = True

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, _Call]:
        kind = note.split(":", 1)[-1]
        if kind == "v_reply_defect":
            doc = {"checked": True, "decision": SEC.V_REPLY_CLEAN,
                   "reason": "夹具：照规则判", "basis": ["夹具"]}
        else:
            doc = {"checked": True, "decision": SEC.SIGN_ISSUE,
                   "reason": "夹具：三轮都干净", "basis": ["夹具"]}
        return doc, _Call()


def _agent_v(st: Store, review: _ReviewSeam, seam: _Seam) -> AgentV:
    return AgentV(st, workspace_root=st.root, llm=review,
                  secretary=SEC.Secretary("V", root=st.root, store=st, seam=seam,
                                          enable_model=True))


# ------------------------------------------------------------------ a：拒信

def test_a_changed_text_without_a_new_sign_is_refused_with_the_advice(
        tmp_path: pathlib.Path) -> None:
    """a：改一个字、拿旧签入库 ⇒ 受控拒绝 + 「建议：请重新拿 V 签」（前 400 字内）。"""
    st = _ws(tmp_path)
    assert _conjecture(st, P1)["ok"] is True
    _sign(st, P1, times=3)

    got = _theorem(st, P2)

    assert got["ok"] is False and got["kind"] == "self_authored_needs_v", got
    err = str(got.get("error") or "")
    assert "建议：" in err, f"拒信没有「建议：」那一句：{err}"
    assert "请重新拿 V 签" in err, f"业主点名的那句话不在：{err}"
    head = err[:400]
    assert "请重新拿 V 签" in head, (
        f"建议句被挤出模型能看到的 400 字窗口（前 400 字里没有它）：{head}")
    assert "改稿是正确动作" in head, f"前 400 字没鼓励改写：{head}"
    # 整笔不写：盘上仍是旧稿（否则「没签却写进去了」比拒信措辞更坏）。
    assert _row(st)["proof_text"] == P1, _row(st)["proof_text"]


# ------------------------------------------------------------------ b：可达性

def test_b_the_advice_is_walkable_end_to_end(tmp_path: pathlib.Path) -> None:
    """b：照 a 的建议走一遍，真的拿到新 sha 的 V 签（不是一句好看的话）。"""
    st = _ws(tmp_path)
    assert _conjecture(st, P1)["ok"] is True
    _sign(st, P1, times=3)
    refused = _theorem(st, P2)
    assert "请重新拿 V 签" in str(refused.get("error") or ""), refused

    # 期望反转（准入闸变严：无签不再可写）之后，可达的那条路是 「V 签先落手稿」
    # （业主 2026-11-02：「V 签不直接进台账，进手稿，随 B 侧收录时读到」）：
    # 把握要交的新正文写成一份稿 → V 走"手稿"那条审稿入口连判 3 转、签块落回稿
    # → 再把正文交 B（闸按手稿签块认那一份签）。
    man_rel = "reports/f-proof-000000.md"
    man_path = pathlib.Path(st.root) / man_rel
    man_path.parent.mkdir(parents=True, exist_ok=True)
    man_text = (f"# F 的证明手稿：{TEXT}\n\n"
                "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
                f"## 命题\n\n{FULL}\n\n## 证明\n\n{P2}\n\n"
                "## 依赖\n\n"
                "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
                "|---|---|---|---|\n\n"
                "（自足证明，空表就是声明。）\n")
    man_path.write_text(man_text, encoding="utf-8")

    review, seam = _ReviewSeam(), _Seam()
    # 2026-11-03 件一：未在册正判的块由收方秘书落 —— 先挂上"V 由 F 派出来"的身份。
    from agentflow import conductor as CND

    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        # 2026-11-05：没有命题号就没有可签的对象 ⇒ 这一走要带号（命题已在册）。
        got = _agent_v(st, review, seam).verify_proof(
            SID, proof_manuscript=man_rel)
    assert review.asked() == 3, (
        f"一次 verify_proof 只问了 {review.asked()} 次模型 ⇒ 「连续 3 次」还得靠人送三次")
    assert got.get("checked") is True, got
    assert "V 签" in man_path.read_text(encoding="utf-8"), (
        "签块没落回稿 —— 「重新拿 V 签」不可达")

    # 签到了再交正文：这一笔要量的是 `canonical_written`（旧正文进 proof_history）。
    # 交的正是稿里那一份正文（`proof_body` 会带上段尾换行 —— 签块盖的就是这一串字节）。
    signed_body = DS.proof_body(man_text)
    # 手稿签块 + 在册台账两处都签住这一份（准入闸认"覆盖它的签"：手稿签块或台账）。
    # 台账按连续 3 次「成立」签，且带 `store`（与 V 的现场发签同一个写口：签完
    # D-37 会把 kind 抬成 theorem —— 这一条要量的"改稿之后不再降档"就落在这上面）。
    for _i in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            st.root, statement_id=SID, proof_text=signed_body,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", store=st, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    rewrite = _b(st).register_statement(
        **{**OWN, "kind": "conjecture"}, proof_text=signed_body,
        proof_manuscript=man_text)
    assert rewrite["ok"] is True, rewrite
    assert rewrite.get("canonical_written") is True, rewrite
    assert _row(st)["proof_text"].strip("\n") == P2, _row(st)["proof_text"]
    assert _row(st)["kind"] == "theorem", _row(st)["kind"]
    assert _row(st)["bits"]["reviewed"] is True, _row(st)["bits"]

    # ③ 签完不必再交一次登记（再交只会得到 duplicate 读数，不是再一次欠签）。
    again = _theorem(st, signed_body)
    assert again.get("kind") == "duplicate_statement", again


# ------------------------------------------------------------------ c：反真空

def test_c_an_unchanged_signed_text_is_not_told_to_resign(
        tmp_path: pathlib.Path) -> None:
    """c：原样入库（sha 一致、签盖着它）⇒ 不说「请重新拿 V 签」。"""
    st = _ws(tmp_path)
    assert _conjecture(st, P1)["ok"] is True
    _sign(st, P1, times=3)

    got = _theorem(st, P1)   # 同一份正文、签就盖着它
    assert got.get("kind") != "self_authored_needs_v", (
        f"没改的人也被告知要重签：{got}")
    assert "请重新拿 V 签" not in str(got.get("error") or ""), got

    gap = VR.proof_review_gap(st.root, dict(_row(st), evidence_kind="proof_review"))
    assert gap["ok"] is True, gap
    assert "请重新拿 V 签" not in str(gap.get("why") or ""), gap["why"]


# ------------------------------------------------------------------ d：三档不抹平

def test_d_the_three_branches_are_not_flattened(tmp_path: pathlib.Path) -> None:
    """d：unsigned 说「请拿 V 签」不说「重新」；rejected 说「改完再送」不说「重签」。"""
    # ---- unsigned：一次都没签过
    st = _ws(tmp_path / "unsigned")
    assert _conjecture(st, P1)["ok"] is True
    unsigned = _theorem(st, P1)
    err = str(unsigned.get("error") or "")
    assert unsigned.get("kind") == "self_authored_needs_v", unsigned
    assert "请拿 V 签" in err, f"unsigned 没给首签的下一步：{err}"
    assert "请重新拿 V 签" not in err, f"一次都没签过却说「重新」：{err}"

    # ---- rejected：同一份正文被判过「有毛病」
    st2 = _ws(tmp_path / "rejected")
    assert _conjecture(st2, P1)["ok"] is True
    _sign(st2, P1, verdict=BAD, times=1)
    rejected = _theorem(st2, P1)
    err2 = str(rejected.get("error") or "")
    assert rejected.get("kind") == "self_authored_needs_v", rejected
    assert "按 findings 改完再送" in err2, f"rejected 没给「改哪」：{err2}"
    assert "请重新拿 V 签" not in err2, f"rejected 原样重送被说成「重签」：{err2}"
    assert "重签" not in err2, f"rejected 不该说「重签」（会误导原样重送）：{err2}"
