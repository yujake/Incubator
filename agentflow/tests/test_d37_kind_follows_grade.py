# -*- coding: utf-8 -*-
"""D-37（2026-10-24 真机 cube 抓到）：命题的 `kind` 没跟着 `grade` 升。

## 现场（`D:\\Incubator\\cube-ws`，只读）

```
statements 000000: kind="conjecture", evidence_kind="proof_review"
bits: {proof: true, reviewed: true, formal: {"1": "verified"}, grade: "theorem"}
verifications/000000.jsonl: v-000001 verdict="成立"、proof_no=1、proof_sha256 与现行正文相符
experiments 000001: method="formal", evidence_kind="proof"（Lean 4.7.0 + Mathlib 真编译 exit 0）
```

⇒ 两条独立凭据都在盘上（V 的签 + 形式化通过），`bits.grade` 现算也是 `theorem`，
而行上的 `kind` 仍写着"猜想"。等级与名字分家：读的人（G 写稿 / H 审校 / 收工门）
读的是 `kind` 那一格。

## 判据（七条：六条主判据 + ③ 的反真空；每条都写明"改前红在哪"）

| # | 判据 | 改前红在哪 |
|---|---|---|
| ① | 猜想 + 无签 ⇒ `kind` 保持 `conjecture`，读数逐条写清"还差什么"（不许折成"已升"） | 没有"kind 该不该跟等级走"这条读数；`_upgrade_evidence_kind` 只改 `evidence_kind` |
| ② | 猜想 + V 签「成立」+ proof ⇒ `kind=theorem`（走真 register / 升档路径，不手搓行） | 签完之后再登记一次只把 `evidence_kind` 升上去，`kind` 一个字不动 |
| ③ | 猜想 + 只有形式化 verified（无 V 签）⇒ 答案见下（按 `evidencebits.derive_grade` 的现算口径） | 同上：第 4 位同步进 `bits` 之后 `kind` 仍是 `conjecture` |
| ③b | 反真空：L 的台账写着"检查器没通过" ⇒ ③ 那一格不许升（名字停在 `conjecture`） | 没有 ③，这条无从谈起；它挡的是"反正都会升"那种假绿 |
| ④ | 反真空：把 ② 那一签从台账里删掉 ⇒ ② 必红（读侧 `kind` 回到 `conjecture`） | 没有 ②，这条无从谈起（改前 ② 本身红） |
| ⑤ | 历史不追溯：证据齐全而 `kind` 仍写"猜想"的老行，读一次不会被静默改写（读侧不变量） | 没有读侧口径；`kind` 只由写侧的动作改 |
| ⑥ | 升档凭据必须指得出"这条命题的哪一签"：只有"命题还没在册时审的那一签"（pending）⇒ B 登记新行时 `kind` 仍是 `conjecture`；本条台账的签（正控）照样升 | 改前 `_attach_proofs` 统一调 `kind_following_grade`，pending 被默认认领 ⇒ 新行在同一笔里变成 `theorem` |

## D-69（2026-10-24，业主）：抬档的时刻提前到"V 那一签落盘时"

D-37 定的是"改名由写侧那一支（同一份内容再交一次）来做"。真机 sylow3 证明那条路不够：
V 的台账里判「成立」、`bits.evidence.reviewed_by_proof` 是 `{"1": true}`，而那一行的
`kind` 仍是 `conjecture`，论文却已经把它排成 lemma / theorem —— 因为"再交一次"这件事
没有人会回头做。D-69 于是把这一格提前：`verifications.sign_statement` 在同一个事务里
调 `evidencebits.kind_following_grade`（判据一个字没变），判的是同一件事。

于是本文件有三处随 D-69 改口径（改的都是"什么时候写"，不是"凭什么写"）：

- ② 签完之后盘上已经是 `theorem`（并在同一笔里留下升档痕迹）。改前那一句
  "签完之后、再登记之前盘上还是猜想"作废 —— 它正是 D-69 要堵的那个窗口；
- ④ 删掉台账那一签之后，读侧回到 `conjecture`（依据没了），但盘上的名字不撤销：
  全仓没有降档路径（降档要写清为什么降，那是另一个决定）。这一条因此量的是
  "下一次写不会再升"与"读侧的依据确实来自台账"，不是"名字自动回退"；
- ⑤ 的历史行形态（证据齐、名字旧）只存在于「老工作区」里了，所以夹具改成把那一行
  按历史形态写回盘上再读 —— 读侧不许改历史这一条不变。

## ③ 的取舍（写在这里备查，理由逐字进了 `evidencebits.kind_following_grade` 的 docstring）

改前的问题是"没有名字"，不是"名字不够强"。`evidencebits.derive_grade` 的现算口径是：
第 2 位 + 第 3 位 ⇒ `pre_theorem`；第 2 位 + 第 4 位任一路径 `verified` ⇒ `theorem`。
V 的签（第 3 位）与形式化通过（第 4 位）是两条并列的独立凭据，而名字只有一个 ⇒
两条都落到 `theorem`：

- ② 是"V 签 + 证明"⇒ `theorem`（等级现算 `pre_theorem`，但那一签就是"这份证明站得住"）；
- ③ 是"只有形式化 verified、没有 V 签"⇒ 也是 `theorem`，既不是 `lemma` 也不是仍停在
  `conjecture`：`derive_grade` 对"证明 + 任一路径形式化通过"本来就现算 `theorem`，把它
  降成 `lemma` 会造出第二个等级口径（同一个 `bits` 两处读出两个档）。V 的签不是"能不能
  叫定理"的必要条件，它是第 3 位那条独立凭据；一条 Lean 真编译过的证明已经是定理。

## 2026-11-08（缺陷③）：这一组的写侧负控为什么不再钉 `ok=false`

`c94a8e8f` 把「收录回执」从"第 2 位这次翻真"那一支里解耦出来：只要这一行真有一份
正文，`_attach_proofs` 就把这一笔落点的号与现算 sha 写到 `statements` 顶层
（`proof_no` / `proof_sha256`），并且它进写盘判据（`out["proof_receipt"]` 非空 ⇒
事务提交）。于是"同一条命题已在册、而这一行的回执还没写过"的那一笔不再整笔拒
`duplicate_statement`：它真写了一格 ⇒ `ok=true` + `new_row=false`。

这一组的四条负控要量的不是"这一笔写没写东西"，而是"这一笔有没有把 `kind` 抬上去
（以及盘上的升档留痕有没有再动一次）"。所以判据钉在后者：`new_row=false`、
`upgraded=false` + 拒码逐字、盘上 `kind` / `_kind_upgrade` / `_grade_recomputed` 逐字不变。
拿 `ok` 当代理比这弱两层：拒收可能发生在写了一半之后，而"写了新行"也可能报 `ok=false`。

## 真机工作区不许碰

本文件只碰 `tmp_path` 下的临时工作区。cube 那条老行按新口径读到什么是只读探针的
事（`kind_following_grade` 是纯读函数，一个字节都不写），不在这里读真机工作区。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

from _same_statement_stub import SameStatementStub  # noqa: E402
from _proof_manuscript_fixture import write_proof_manuscript  # noqa: E402
from conftest import seed_statement_row, sign_before_registration  # noqa: E402

#: 一条干净的自产命题（cube 那条的形体：立方和闭式）。
FULL = "对任意整数 n≥0：1^3 + 2^3 + … + n^3 = (n(n+1)/2)^2。"
LABEL = "sum-of-cubes-closed-form"

#: 证明正文：写成归纳那两步（cube 那条的证明栏的同形）。不含硬禁令短语。
PROOF = ("对 n 作归纳。基例 n = 0：左边为空和 0，右边为 (0·1/2)^2 = 0，成立。"
         "归纳步：设 Σ_{k=1}^{n} k^3 = (n(n+1)/2)^2，则 "
         "Σ_{k=1}^{n+1} k^3 = (n+1)^3 + (n(n+1)/2)^2 = "
         "(n+1)^2 · (4(n+1) + n^2)/4 = (n+1)^2(n+2)^2/4 = ((n+1)(n+2)/2)^2，成立。")


# ------------------------------------------------------------------ 夹具

def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None, config={})


def _own(**kw) -> dict:
    """一条 `origin="own_result"` 的登记参数（只含动作面声明过的键，且按猜想进门）。"""
    base = {
        "statement_full": FULL, "statement_text": LABEL, "label": LABEL,
# 2026-11-17（业主裁定 ②）：own_result 必须写清来路；这一份夹具不测承重链，用形状合法的占位号。
        "origin": "own_result", "derived_from": ["999999"], "kind": "conjecture", "doc_id": S.format_id(0),
        "line_range": {"start": 1},
        "quote_verified": False,
        "quote_reason": "own_result：我方推导，没有第二份文本可比对",
    }
    base.update(kw)
    return base


def _file(store: Store, **kw) -> dict:
    """造一条在册的"猜想 + 有证明、还没签"的命题（历史形态：直接铺行）。

    2026-11-02 准入闸默认 strict 之后，这个状态不能再经 `register_statement` 造出来
    （无签的证明正文整笔拒 `proof_without_v_sign`）—— 而 D-37 这一组测的正是
    "这一行现在叫不叫定理"。所以现场改成直接铺行（真机 3134 行 own_result 的形状：
    bits 按 `bits_of` 现算（proof 位真、reviewed 位假）、台账 0 行、没有签）。
    期望值与判据一个字都没改。
    """
    own = _own(proof_text=PROOF, **kw)
    kind = str(own.get("kind") or "conjecture")
    seeded = seed_statement_row(
        store, proof_text=str(own.get("proof_text") or ""),
        statement_full=str(own.get("statement_full") or ""),
        statement_text=str(own.get("statement_text") or ""), kind=kind,
        label=str(own.get("label") or ""), origin=str(own.get("origin") or "own_result"),
        quote_verified=own.get("quote_verified"),
        quote_reason=str(own.get("quote_reason") or ""),
        # 其余按"B 真登记会落下的那一行"补齐（同形历史行）：`evidence_kind` 的缺省、
        # 出处两栏、依赖/别名两张空表 —— 升档那一步要读它们。
        evidence_kind="cross_check", doc_id="000000",
        line_range={"start": 1, "end": None, "label": ""},
        page_range={"start": None, "end": None, "label": ""},
        derived_from=[], aliases=[], source_lit_id=None,
        quote_mode="", quote_span="", quote_call_sha256="",
        bits=EB.bits_of(origin="own_result", proof=True, proof_process=PROOF,
                        kind=kind))
    return {"ok": True, "stmt_id": str(seeded["stmt_id"]), "new_row": False,
            "row": dict(seeded)}


def _row(store: Store, sid: str) -> dict:
    hit = [dict(r) for r in store.rows("statements") if str(r.get("stmt_id") or "") == sid]
    assert hit, f"盘上读不到命题 {sid}"
    return hit[0]


def _sign(store: Store, sid: str) -> dict:
    """V 的签名写入口（`verifications.record_verification`，动作面那一件的真身）。

    ## 为什么这一条不经 `AgentV.verify_proof`
    `verify_proof` 对人写的证明要一次模型判定（本仓没有模型缝时它如实回
    `judge_not_wired`、`checked=False`，一个字节都不写）—— 那是"没查成"，不是"查过了"。
    穷举那一档（证明栏是程序路径）才走机械会审；这一条是散文证明，所以签名走 V 落
    台账的那个写入口：`verdict` 是 V 的三态结论，`store` 一给就同一次写把第 3 位翻上去
    （见 `record_verification` 的 docstring）。这与 `AgentV.verify_proof` 拿到结论之后
    调的是同一个函数，不是另一条路。

    ## 为什么这里连签 `SIGN_STREAK_NEED` 次（2026-10-29 口径）
    「一次成立就签」已经取消：同一份正文（同 `proof_sha256`）必须连续
    `SIGN_STREAK_NEED` 次「成立」且秘书判定通过，第 1、2 次只落台账、第 3 位不翻。
    返回最后那一签（签发的那一签）；台账里前两行照样在，判据的断言一条都没放宽。
    """
    need = int(VR.SIGN_STREAK_NEED)
    signed: dict = {}
    for i in range(1, need + 1):
        signed = VR.record_verification(
            store.root, statement_id=sid, proof_text=PROOF,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", store=store, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
        wrote = bool((signed.get("statement_writeback") or {}).get("written"))
        assert wrote is (i == need), (
            f"第 {i} 次「成立」的翻位读数是 written={wrote!r} —— 2026-10-29 口径："
            f"连续 {need} 次才发签（第 1、2 次只落台账），读到的理由："
            f"{(signed.get('statement_writeback') or {}).get('reason') or '（没有理由）'}")
    return signed


def _resubmit(store: Store, **kw) -> dict:
    """同一份内容再交一次（升档那一步的正路：内容一个字不动）。"""
    return _b(store).register_statement(**_own(proof_text=PROOF, **kw))


def _formal_ledger_row(store: Store, *, sid: str, proof_no: int = 1,
                       experiment_id: str = "000001", verified: bool = True) -> dict:
    """落一行 L 的形式化台账（与 `agent_l/record.py` 落的那一行同形）。

    ## 为什么这里可以造行，而命题那一行不许手搓
    第 4 位不是从 B 的入参算出来的，是从 L 的 `experiments` 台账同步进命题行的
    （`evidencebits.formal_ledger_reading` 是唯一派生点，写盘由 B 的登记完成）。
    所以"L 验过了"这一件事在判据里就得先有那一行 —— 它的形状与 Owner 那一侧落的
    逐字同形（`test_formal_bit_is_two_dimensional.py` 的 `_put_formal_experiment` 同源）。
    命题那一行、它的 `bits`、它的 `kind` 全部走真 register / 升档路径，不在这里拼。
    """
    obs = {
        "status": "verified" if verified else "unknown",
        "checker_status": "verified" if verified else "not_checked",
        "verified": verified, "checker_verified": verified,
        "checker": "lean 4.7.0", "statement_id": sid,
        "code_hash": "a" * 64, "recorded_by": "agent-L",
        "tri_state": "verified" if verified else "not_checked",
        "proof_no": proof_no, "path_id": "p%dg1" % proof_no,
        "proof_sha256": VR.text_sha(PROOF), "path_source": "L",
    }
    row = S.Experiment(
        experiment_id=experiment_id, claim=FULL, claim_key=f"stmt:{sid}",
        method="formal", evidence_kind="proof" if verified else "heuristic",
        result="supports" if verified else "inconclusive",
        negation_kind="not_proved",
        code_path="code/formal/sum_cubes_closed_form.lean", code_hash="a" * 64,
        exit_code=0 if verified else None,
        verifier_output="no goals" if verified else "",
        verifier_subject_key=f"stmt:{sid}", created_at=S.now_iso(), created_by="agent-L",
        observations=obs,
        params={"checker": "lean 4.7.0", "statement_id": sid, "proof_no": proof_no,
                "path_id": "p%dg1" % proof_no, "proof_sha256": obs["proof_sha256"],
                "path_source": "L"},
    )
    row.validate()
    with store.tx("experiments", actor="test", note="probe:formal") as tx:
        tx.upsert("experiments", row.to_dict(), note="probe:formal")
    return row.to_dict()


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _statements_file(root: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(root) / "data" / "statements.json"


# ------------------------------------------------------------------ ① 无签 ⇒ 仍是猜想

def test_criterion1_a_conjecture_without_a_signature_stays_a_conjecture(
        store: Store) -> None:
    """① 猜想 + 无签 ⇒ `kind=conjecture`，且读数逐条写清"还差什么"。

    三态纪律那一半：证据不够时不许折成"已经升了"。所以这里不只断言 `kind` 没变，
    还断言读数给出了两条缺项（V 的签 / 形式化 verified）—— "还差什么"是可行动的
    那一句，不是一句"证据不足"。
    """
    filed = _file(store)
    sid = str(filed["stmt_id"])
    row = _row(store, sid)
    assert row["kind"] == "conjecture", row

    reading = EB.kind_following_grade(row, root=store.root)
    assert reading["checked"] is True, reading
    assert reading["state"] == "held", reading
    assert reading["kind"] == "conjecture", reading
    assert reading["declared"] == "conjecture", reading
    assert "v-" not in reading["basis"] and "formal" not in reading["basis"], reading
    shortfall = str(reading["shortfall"])
    assert "V" in shortfall, f"缺项要点名 V 的那一签：{shortfall}"
    assert "formal_by_proof" in shortfall, f"缺项要点名形式化那一位：{shortfall}"

    # 写侧负控：同一份内容再交一次、自称 proof_review（而台账里一次都没签）
    # ⇒ 一行都不许升，kind 仍是猜想，而且读数里留着"V 那一签还差"的原话。
    #
    # 2026-11-08（缺陷③，`c94a8e8f`）之后这一笔不再整笔拒收：这一行的收录回执
    # （`proof_no` / `proof_sha256`）此前没写过，而回执是"只要这一行真有正文就写"
    # 的那一格，它进了写盘判据 ⇒ `ok=true` 只代表"回执真写了一格"（`new_row=false`，
    # 没有新行、没有升档）。判据因此钉在"升没升"上，不再拿 `ok` 当代理
    # （理由逐字见模块 docstring 那一节）。
    again = _resubmit(store, evidence_kind="proof_review")
    assert again.get("new_row") is False, again
    # 升档没发生：请求的那一档被写入期闸按"没有能签住这份正文的台账"挡下（拒码逐字）。
    assert again.get("upgraded") is False, again
    assert str((again.get("upgrade_refused") or {}).get("refused") or "") == \
        "proof_review_without_evidence", again
    # 回执里"还差什么"的原话仍在：秘书留下的"还差 V 那一签"不许折成一句"重复登记"。
    assert "V 的一签" in str(again.get("note") or ""), (
        "秘书/ B 的读数里没有说清'还差 V 那一签'：" + str(again.get("note")))
    assert _row(store, sid)["kind"] == "conjecture", _row(store, sid)


# ------------------------------------------------------------------ ② V 签 + proof ⇒ 定理

def test_criterion2_a_signed_proof_lifts_the_kind_to_theorem(store: Store) -> None:
    """② 猜想 + V 签「成立」+ proof ⇒ `kind=theorem`（真 register / 升档路径）。

    路径逐字是驳回信里那条正路：先按猜想落库（V 只审在册的命题）→ V 签 → 同一份内容
    再交一次。这一条量的是"V 签「成立」之后 `kind` 有没有跟着到 `theorem`" —— 而它不该
    要求提交方自己声明 `kind="theorem"`（证据在盘上，名字就该跟着证据走）。

    D-69 之后，签那一刻就已经抬上去了（同一个事务里）；2026-11-04（业主）之后
    `evidence_kind` 也在同一笔里按现行签回填（`_grade_recomputed_from_signature`），
    所以"再交一次"现在真的是空操作：秘书查重后不新建行（`duplicate_statement`），
    盘上那一行一个字不动。这一条把两段都量：签字那一笔同时留下"名字"与"档位"两份
    升档痕迹；再交一次不改盘、也不产生第二份回填。
    """
    filed = _file(store)
    sid = str(filed["stmt_id"])
    signed = _sign(store, sid)
    assert signed.get("checked") is True and signed.get("verdict") == "成立", signed

    # D-69：签完就在盘上了（不再有"签完之后、再登记之前还是猜想"那个窗口）。
    before = _row(store, sid)
    assert before["kind"] == "theorem", before
    trace0 = dict(before.get("_kind_upgrade") or {})
    assert trace0.get("from") == "conjecture" and trace0.get("to") == "theorem", trace0
    # 依据指向签发的那一签（2026-10-29：连续 3 次之后第 3 行才发签，不是第 1 行）
    sign_row = f"verifications/{sid}.jsonl#{signed['verification_id']}"
    assert sign_row in str(trace0.get("basis") or ""), (sign_row, trace0)
    # 2026-11-05：档位不再回填 —— 判定面读等级。签字那一笔只留等级回执；
    # 历史列仍是登记时那一档（它只是历史）。
    assert before["evidence_kind"] == "cross_check", before
    recomputed = dict(before.get("_grade_recomputed") or {})
    assert recomputed.get("from") == "strong_conjecture", recomputed
    assert recomputed.get("to") == "pre_theorem", recomputed
    assert recomputed.get("to_kind") == "proof_review", recomputed
    assert sign_row in str(recomputed.get("basis") or ""), (sign_row, recomputed)
    # 同一笔事务的读数（名字与等级两条）都是签名入口给的，不是"事后才补"的一句话。
    writeback = dict(signed.get("statement_writeback") or {})
    assert (writeback.get("kind_upgrade") or {}).get("to") == "theorem", writeback
    assert "conjecture→theorem" in str(writeback.get("upgrade_note") or ""), writeback
    assert (writeback.get("grade_recomputed") or {}).get("to") == "pre_theorem", writeback
    read = EB.kind_following_grade(before, root=store.root)
    assert read["state"] == "not_applicable" and read["kind"] == "theorem", read

    # 同一份内容再交一次：名字已经到位 ⇒ 没有新行、也没有第二次升档。
    # 2026-11-05 起不再借这一笔"补档位"：等级是五元位现算的，历史列与判定无关。
    # 2026-11-08（缺陷③）之后这一笔会写收录回执（回执不在盘上时它就是一次真写）
    # ⇒ 判据钉"盘上那几格有没有动"，不钉 `ok`：升档留痕逐字相比（含 `at` / `basis`）。
    again = _resubmit(store)
    assert again.get("new_row") is False, again
    assert str(again.get("stmt_id") or sid) == sid, again
    row = _row(store, sid)
    assert row["kind"] == "theorem", row
    assert row["evidence_kind"] == "cross_check", row
    trace = dict(row.get("_kind_upgrade") or {})
    assert trace == trace0, (trace, trace0)
    # 幂等：回执只发生过一次（时间戳与依据一起没变），不是"每写一次重算一遍"。
    assert dict(row.get("_grade_recomputed") or {}) == recomputed, row

    # 再读一次：现在读数与盘上一致（已经是 theorem，不是"再升一次"）。
    read2 = EB.kind_following_grade(row, root=store.root)
    assert read2["state"] == "not_applicable", read2
    assert read2["kind"] == "theorem", read2


# ------------------------------------------------------------------ ③ 只有形式化 verified

def test_criterion3_formal_verified_alone_makes_it_a_theorem(store: Store) -> None:
    """③ 猜想 + 只有形式化 verified（无 V 签）⇒ `theorem`（理由见模块 docstring）。

    走的是第 4 位的真写侧：L 落一行 `method="formal"` + `evidence_kind="proof"` 的实验行，
    B 再登记一次 ⇒ `evidencebits.formal_ledger_reading` 把它同步进命题行的
    `bits.evidence.formal_by_proof`（这是 D28 的写侧），而 `kind` 必须与它一起到位。

    选择不是 `lemma`、也不是仍停在 `conjecture`：`derive_grade` 对"证明 + 任一路径
    形式化通过"现算就是 `theorem`，名字跟着等级走（第二个等级口径不许出现）。
    """
    filed = _file(store)
    sid = str(filed["stmt_id"])
    _formal_ledger_row(store, sid=sid)

    synced = _resubmit(store)
    assert synced.get("ok") is True, synced
    row = _row(store, sid)
    assert str((row.get("bits") or {}).get("grade") or "") == "theorem", row
    assert str(row.get("kind") or "") == "theorem", row
    trace = dict(row.get("_kind_upgrade") or {})
    assert trace.get("from") == "conjecture" and trace.get("to") == "theorem", trace
    assert "formal_by_proof" in str(trace.get("basis") or ""), trace
    assert "verified" in str(trace.get("basis") or ""), trace
    # 升上之后读侧与盘上一致（不是"再升一次"）。
    read = EB.kind_following_grade(row, root=store.root)
    assert read["state"] == "not_applicable" and read["kind"] == "theorem", read


def test_criterion3b_a_failed_formal_does_not_lift_the_kind(store: Store) -> None:
    """③ 的反真空：L 的台账写着"检查器没通过"（`evidence_kind="heuristic"`）⇒ 不许升。

    这一条与 ③ 只差那一格：`formal_ledger_reading` 只认 `evidence_kind="proof"` 为
    `verified`，`heuristic` 那一档根本不进第 4 位。于是 `kind` 必须停在 `conjecture`，
    读数给出 `held` 与"还差形式化 verified"那句原话 —— 否则 ③ 的绿可能是"反正都会升"。
    """
    filed = _file(store)
    sid = str(filed["stmt_id"])
    _formal_ledger_row(store, sid=sid, verified=False)

    synced = _resubmit(store)
    # 第 4 位没有变化 ⇒ 这一笔不升档（回执那一格会写 —— 见模块 docstring：那不是"升了"）。
    assert synced.get("new_row") is False, synced
    assert synced.get("upgraded") is not True, synced
    assert "kind_upgrade" not in synced, synced
    row = _row(store, sid)
    assert not row.get("_kind_upgrade"), row
    assert str((row.get("bits") or {}).get("grade") or "") != "theorem", row
    assert str(row.get("kind") or "") == "conjecture", row
    read = EB.kind_following_grade(row, root=store.root)
    assert read["state"] == "held" and read["kind"] == "conjecture", read
    assert "formal_by_proof" in str(read["shortfall"]), read


# ------------------------------------------------------------------ ④ 反真空：删掉那一签

def test_criterion4_deleting_the_signature_returns_it_to_conjecture(store: Store) -> None:
    """④ 反真空：把 ② 那一签从台账里删掉 ⇒ 读侧退回 `conjecture`，下一次写也不再升。

    这一条同时钉住升档依据是"台账里那一行"，不是"`bits.reviewed` 这个布尔"：
    位还停在 `true`（V 签过），而台账里已经没有那一签 ⇒ 依据不成立、名字不许升。
    这正是 `verifications.proof_review_gap` 那句话（读侧按台账现算）在 D-37 上的用法。

    D-69 之后盘上的名字不自动撤销（全仓没有降档路径：降档要写清为什么降，那是另一个
    决定）。所以这一条量的是两件仍然成立的事：读侧的依据确实来自台账（`held` + "还差
    V 那一签"），以及此后的写不会再往上走一步。
    """
    filed = _file(store)
    sid = str(filed["stmt_id"])
    assert _sign(store, sid).get("verdict") == "成立"
    ledger = VR.verification_ledger_path(store.root, sid)
    assert ledger.is_file() and ledger.read_text(encoding="utf-8").strip(), ledger
    named = _row(store, sid)
    assert named["kind"] == "theorem", named
    trace_named = dict(named.get("_kind_upgrade") or {})
    assert trace_named.get("to") == "theorem", trace_named

    # 删掉那一签（只删台账那一行；`bits.reviewed` 不动 —— 它就是"位说签过"的现场）。
    ledger.write_text("", encoding="utf-8")
    row = _row(store, sid)
    assert bool((row.get("bits") or {}).get("reviewed")) is True, row

    # 读侧的问法是"按盘上现有的证据，这一行现在该叫什么" —— 所以喂它历史形态
    # （名字还是猜想、没有升档留痕），判据才落在"依据在不在"上，而不是"名字已经是什么"。
    probe = dict(row)
    probe["kind"] = "conjecture"
    probe.pop("_kind_upgrade", None)
    read = EB.kind_following_grade(probe, root=store.root)
    assert read["state"] == "held", read
    assert read["kind"] == "conjecture", read
    assert "V" in str(read["shortfall"]), read

    again = _resubmit(store, evidence_kind="proof_review")
    # 升档请求被写入期闸挡下（台账里已经没有那一签）：拒码逐字（回执那一格照写，
    # 见模块 docstring —— 那是"这一笔真写了一格"，不是"升了"）。
    assert str((again.get("upgrade_refused") or {}).get("refused") or "") == \
        "proof_review_without_evidence", again
    assert again.get("upgraded") is False, again
    # 名字不撤销（没有降档路径），但也不许再往上走一步：升档留痕逐字没变（含 at）。
    after = _row(store, sid)
    assert after["kind"] == "theorem", after
    assert dict(after.get("_kind_upgrade") or {}) == trace_named, (
        after.get("_kind_upgrade"), trace_named)


# ------------------------------------------------------------------ ⑤ 历史不追溯

def test_criterion5_a_historical_row_is_read_but_never_rewritten(store: Store) -> None:
    """⑤ 历史不追溯：证据齐全而 `kind` 仍写着"猜想"的老行，读一次不会被静默改写。

    夹具是「老工作区」里那种行的形状（D-69 之前写下的：V 签完之后、B 还没再登记）：
    `kind="conjecture"`、`bits.proof=true`、`bits.reviewed=true`、
    `verifications/<号>.jsonl#v-000003`（连续 3 次之后签发的那一签）判成立。D-69 之后
    签名那一笔自己就会抬档，所以这种形态只能按历史形态写回盘上（真机上它是 sylow3 那三行）。

    判据两件：
    1. 读侧按新口径读出 `theorem`（并给出依据）—— 不然缺陷没修；
    2. 读完之后盘上那一行逐字节不变（`kind` 仍 `conjecture`，文件 sha256 相同）——
       读不许改历史。
    """
    filed = _file(store)
    sid = str(filed["stmt_id"])
    assert _sign(store, sid).get("verdict") == "成立"

    # 把那一行按"历史形态"写回盘上（只改这两处：名字回猜想、撤掉升档留痕）。
    historical = _row(store, sid)
    historical["kind"] = "conjecture"
    historical.pop("_kind_upgrade", None)
    with store.tx("statements", actor="test", note="probe:historical") as tx:
        tx.upsert("statements", historical, note="probe:historical")

    path = _statements_file(store.root)
    before_bytes = path.read_bytes()
    before_sha = _digest(path)
    historical = _row(store, sid)
    assert historical["kind"] == "conjecture", historical

    read = EB.kind_following_grade(historical, root=store.root)
    assert read["kind"] == "theorem", read
    assert read["state"] == "upgraded", read

    # 读侧不变量：一个字节都不许动（内存里的行、盘上的文件、台账行数）。
    assert path.read_bytes() == before_bytes, "读了一次就把 statements.json 改了：读侧不许写"
    assert _digest(path) == before_sha
    after = _row(store, sid)
    assert after["kind"] == "conjecture", after
    assert json.dumps(after, ensure_ascii=False, sort_keys=True) == \
        json.dumps(historical, ensure_ascii=False, sort_keys=True)

    # 负控（反真空）：这条夹具真的"证据齐全"—— 把台账那一签删掉，读数必须退回猜想，
    # 否则上面那句"读侧读出 theorem"可能只是读侧随便说了个词。
    VR.verification_ledger_path(store.root, sid).write_text("", encoding="utf-8")
    gone = EB.kind_following_grade(_row(store, sid), root=store.root)
    assert gone["state"] == "held" and gone["kind"] == "conjecture", gone


# --------------------------------------------------- ⑥ pending 签不够升新行的 kind

def _b_with_a_secretary(store: Store) -> AgentB:
    """按生产同形接一名秘书（离线替身只答"挑词 + 判 different"）。

    为什么这一条需要它：登记一条新命题时 `_resolve_same_statement` 先问一次
    "是不是在册的同一条"；没接秘书时那一问 fail-closed，会把判据顶掉（与
    `test_b1_b2_b4_rulings._b` 同一个缝）。检索面与生产一致，只把判定缝换成替身。
    """
    return AgentB(store, extractor=None, extract_text=None, config={},
                  secretary=Secretary("B", root=store.root, store=store,
                                      seam=SameStatementStub(), enable_model=True))


def test_criterion6_a_pending_sign_alone_does_not_lift_a_new_row(
        store: Store) -> None:
    """⑥（2026-11-10 业主裁量）：命题还没在册时审的那一签 ⇒ B 登记新行时 kind 仍是猜。

    改前红（`ea6132d3` 现场）：`_attach_proofs` 在等级重算之后对"这一行有正文"统一调
    `kind_following_grade`，而它默认认 D-34 的 pending 签 ⇒ 新建的 conjecture 行在
    同一次登记写里变成 `theorem`，`_kind_upgrade.basis` 指向
    `verifications/pending/<正文 sha>.jsonl#u-…` —— 这一行连自己的台账
    （`verifications/<命题号>.jsonl`）都还没有。升档的凭据必须指得出"这条命题的
    哪一签"，否则那不是派生、是猜。

    两边都要钉：
    - 准入闸照常放行（pending 那一签是"先签后登记"的正路凭据：`ok=True`、
      第 3 位 `reviewed=True`、`_grade_recomputed` 按它算到 `pre_theorem`）；
    - `kind` 停在 `conjecture`、没有 `_kind_upgrade`；读侧 `allow_pending=False` 是
      `held`（查过了、不够，不是 `unreadable`）。
    正控（参数不是"永远不升"的开关）：同一份正文签在这一条命题自己的台账里 ⇒
    `allow_pending=False` 也照样 `upgraded` 到 `theorem`；且默认参数下 pending 那一签
    仍算"签过"（D-34 的认领面一个字没动）。
    """
    # ---- 现场一：只有 pending 签（命题还没在册时审的）⇒ 新行仍是 conjecture ----
    sign_before_registration(store.root, proof_text=PROOF)
    manuscript = write_proof_manuscript(store.root, "000000", PROOF,
                                        statement_full=FULL)
    filed = _b_with_a_secretary(store).register_statement(
        statement_full=FULL, statement_text=LABEL, label=LABEL,
        origin="own_result", derived_from=["999999"], kind="conjecture", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        proof_text=PROOF, proof_manuscript=manuscript)
    assert filed.get("ok") is True, filed                    # 准入闸照常放行
    row = _row(store, "000000")
    assert row["kind"] == "conjecture", row                   # 改前红：这里读成 theorem
    assert "_kind_upgrade" not in row, row
    assert bool(dict(row.get("bits") or {}).get("reviewed")) is True, row
    assert dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {}).get("to") == "pre_theorem", row
    held = EB.kind_following_grade(row, root=store.root, allow_pending=False)
    assert held["state"] == "held" and held["kind"] == "conjecture", held
    assert held["checked"] is True, held                     # 查过了、不够 ≠ 没查成
    assert "不够升 kind" in str(held["shortfall"]), held
    # D-34 的认领面没被拆掉：默认参数下那一签仍算"签过"（读侧口径不变）。
    default = EB.kind_following_grade(row, root=store.root)
    assert default["state"] == "upgraded" and default["kind"] == "theorem", default

    # ---- 现场二（正控）：同一份正文签在这一条命题自己的台账里 ⇒ 照样升 ----
    filed2 = _file(store)                                    # 新号 000001，历史形态
    sid2 = str(filed2["stmt_id"])
    assert _sign(store, sid2).get("verdict") == "成立"
    probe = dict(_row(store, sid2))
    probe["kind"] = "conjecture"                             # 按"名字还没跟上"的形态读
    probe.pop("_kind_upgrade", None)
    here = EB.kind_following_grade(probe, root=store.root, allow_pending=False)
    assert here["state"] == "upgraded" and here["kind"] == "theorem", here
    assert f"verifications/{sid2}.jsonl#v-" in str(here["basis"]), here
