# -*- coding: utf-8 -*-
"""判据：V 会审穷举型证据（三态），以及 E -> V 那条边（业主 2026-10-23 晚）。

业主原话（逐字）：「E 写的报告要能落下来，且 V 也要会审这种东西，加 E 派 V 的边」，
随后更正：「签字仍由 V 签（不是 E）。E 只是 ②③（程序设计 / 穷举论证）的原作者。」

## 这一组守六条

1. 穷举型证据（证明栏第 ① 段是数值实验程序）走 V 的会审：七项检查逐项给读数，
   全部通过 ⇒ `成立`、签第 3 位、台账落一行；
2. 把 ③ 的穷尽说明改坏（说成抽样、代码里也有抽样构造）⇒ `有毛病` 并点名那一项
   （不是一句"看起来不太行"）；
3. 搜索空间与代码对不上（③ 报了一个代码里没有的数）⇒ `有毛病`，点名那一项；
4. 报告没落地（缺材料）⇒ `看不出来`，点名缺什么，且不许判 `成立`；
5. `E -> V` 的边是真的：`conductor.summon("V", ..., by="E")` 被受理；
   其它角色到 V 的边一条都没多（负控：by="G" 仍被拒 `forbidden_edge`）；
6. 边表逐角色清单与总数钉住（多开一条边 ⇒ 这一条红）。

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发（会审是机械判据）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import add_literature, e_form_gate_ok, sign_before_registration  # noqa: E402
from agentflow import capabilities as C  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-10-23T00:00:00+08:00"
SCRIPT_REL = "code/enum_ramsey34.py"

#: 一个真的穷举脚本（数字在代码里出现、剪枝在报告里解释）。
EXHAUSTIVE_PROBE = """
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

#: 一个"抽样"脚本：它自己报了 exhaustive=true（E 的判据拿它签了 proof），
#: 但代码里是随机抽样、③ 也写着抽样 —— V 必须判"有毛病"。
SAMPLING_PROBE = """
import json, random
N = 9
TOTAL = 100000
picks = [random.randrange(2 ** 36) for _ in range(TOTAL)]
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "在 K_9 的二染色空间里抽查",
        "enumeration": "随机抽取 100000 个二染色逐点检查，覆盖率很高；边界 n=9",
        "search_space": {"graph": "K_9", "colourings": 100000},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9},
}))
"""

#: 一个"搜索空间报大了"的脚本：③ 说 2^40，而代码里只有 2^36（V 必须点名这个数）。
OVERCLAIM_SPACE_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 归约成二染色穷举",
        "enumeration": "枚举全部 2^40 = 1099511627776 个二染色，无一遗漏；边界 n=9",
        "search_space": {"graph": "K_9", "colourings": 1099511627776},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9},
}))
"""


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _chain(tmp_path: pathlib.Path, body: str = EXHAUSTIVE_PROBE,
           rel: str = SCRIPT_REL) -> dict:
    """整条链真跑一次：E 跑穷举实验（并落 ②③）→ B 原样登记命题 → 交给 V 会审的原料。

    B 这一笔按 `kind="conjecture"` 登记（而不是直接 `evidence_kind="proof"`）：
    2026-10-23 晚的第三方签字闸（`numericproof.filing_problems`）要求 proof 那一档必须
    有 V 的会审签名，而 V 只审在册的命题 ⇒ 正路的顺序是"先按猜想落库（这一步不受阻）、
    交给 V 会审、签完之后再升成定理级"。这条链在 V 会审之前就停下，所以只能是猜想那一档。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    _write(store, rel, body)
    out = e_form_gate_ok(AgentE(store, config={}, workspace_root=store.root)).run_experiment(
        "R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", rel, method="numeric")
    row = store.rows("experiments")[-1]
    column = NP.proof_column(row)
    # 准入闸（2026-11-02 默认 strict）：这一笔要写进台账的证明正文先要有 V 签；
    # 命题还没在册 ⇒ 先落 pending 那一签（V 在册前审的），登记时按正文 sha 认领。
    sign_before_registration(store.root, proof_text=column)
    # 2026-11-04（甲）：B 的入库面也要那份按号手稿（E 的 e-proof 稿就是它）。
    manuscript_text = (pathlib.Path(store.root) / str(out["proof_manuscript"])).read_text(
        encoding="utf-8")
    filed = AgentB(store, extractor=None, extract_text=None).register_statement(
        origin="own_result", kind="conjecture", label="R(3,4)=9",
        statement_full="对任意正整数 n，R(3,4)=9。", statement_text="R(3,4)=9",
        proof_text=column, proof_manuscript=manuscript_text,
        evidence_kind="cross_check", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert filed.get("ok") is True, filed
    statement = store.rows("statements")[-1]
    return {"store": store, "out": out, "row": row, "column": column,
            # 2026-11-04（甲）：在册穷举送审也要带 E 的按号手稿。
            "manuscript": str(out.get("proof_manuscript") or ""),
            "statement": statement, "v": AgentV(store, workspace_root=store.root,
                                                secretary=_v_secretary(store))}


def _v_secretary(store: Store):
    """V 的秘书替身：判 clean、判签发（业主 2026-10-29：发签权在秘书手上）。

    离线缝的答案与 `test_v_sign_gate_streak` 同源（不抄第二份夹具）。
    """
    from agentflow import secretary as SEC

    from test_v_sign_gate_streak import _Seam as _GateSeam
    from test_v_sign_gate_streak import _axis

    seam = _GateSeam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    return SEC.Secretary("V", root=store.root, store=store, seam=seam,
                         enable_model=True)


def _three(agent: AgentV, sid: str, column: str, *, manuscript: str = "") -> dict:
    """连审 `SIGN_STREAK_NEED` 次、返回最后一次的返回值（第 3 次才落签块）。

    2026-11-08：签只落在稿上，落块要收方秘书 ⇒ 造真实送审的挂点（parent=E）。
    """
    got: dict = {}
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-e-000001",
                        parent_role="E"):
        for _i in range(VR.SIGN_STREAK_NEED):
            got = agent.verify_proof(sid, proof_text=column, proof_manuscript=manuscript)
    return got


# ------------------------------------------------------------------ ③ 三态


def test_4a_an_exhaustive_evidence_that_holds_is_signed_by_v(tmp_path: pathlib.Path) -> None:
    """③-1 成立：七项检查全过 ⇒ `成立`、签第 3 位、台账落一行；②③ 的作者仍是 E。

    2026-10-29 之后"签第 3 位"要连续 `SIGN_STREAK_NEED` 次「成立」、且翻位由 V 的秘书做
    ⇒ 三次会审之后取最后一次（`_three`），台账因此有三行（改前一行）。
    """
    env = _chain(tmp_path)
    got = _three(env["v"], env["statement"]["stmt_id"], env["column"],
                 manuscript=env["manuscript"])
    assert got["checked"] is True, got
    assert got["kind"] == "numeric_evidence", got
    assert got["verdict"] == ER.VERDICT_OK, (got["verdict"], got.get("findings"))
    assert got["signed_bit3"] is False, got
    assert got["review_write"].get("manuscript_signed") is True, got["review_write"]
    checks = {str(c["name"]): c["ok"] for c in got["checks"]}
    for name in (ER.CHECK_PROGRAM, ER.CHECK_REPORT, ER.CHECK_SPACE, ER.CHECK_SYMMETRY,
                 ER.CHECK_BOUNDARY, ER.CHECK_EXHAUSTIVE, ER.CHECK_SLOT):
        assert checks.get(name) is True, (name, got["checks"])
    assert got["report_path"] == ER.report_relpath(env["out"]["experiment_id"])
    assert got["proof_authors"] == ["E"], got
    ledger = env["v"].list_verifications(env["statement"]["stmt_id"])["items"]
    # 三次会审各落一行（连续 3 次「成立」才发签）—— 改前一次就够。
    #
    # 2026-11-10（读侧并入，`verifications._claimed_pending_rows` / 2527e727）：这条
    # 命题的台账现在还会带上「命题还没在册时 V 审的那一签」—— 就是本文件 `_chain`
    # 里 `sign_before_registration` 落的那一份（`u-` 前缀、同一份正文的 sha）。
    # 它既不是这三次会审中的任何一次、也不顶一张会审票（`_gap_from_pending` 的理由），
    # 所以会审行（`v-`）与前提签（`u-`）必须分开数，不能混成一个"行数"。
    # 改前这里断言台账恰好 `SIGN_STREAK_NEED` 行；改后拆成"`v-` 恰好三行" +
    # "`u-` 恰好一行（且是这一份正文）" + "两者之和 == 台账全长"，强度没有降：
    # 少一次会审、多一条前提签、或把前提签借来顶一次会审，都在下面三行里立刻红。
    reviews = [r for r in ledger
               if not str(r.get("verification_id") or "").startswith(VR.PENDING_PREFIX)]
    premises = [r for r in ledger
                if str(r.get("verification_id") or "").startswith(VR.PENDING_PREFIX)]
    assert [r["verdict"] for r in reviews] == [ER.VERDICT_OK] * VR.SIGN_STREAK_NEED, ledger
    assert len(premises) == 1 and premises[0]["verdict"] == ER.VERDICT_OK, ledger
    assert str(premises[0].get("proof_sha256") or "") == VR.text_sha(env["column"]), premises
    assert len(ledger) == len(reviews) + len(premises) == VR.SIGN_STREAK_NEED + 1, ledger


def test_4b_a_broken_exhaustive_note_is_faulty_and_named(tmp_path: pathlib.Path) -> None:
    """③-2 把穷尽说明改坏（说成抽样、代码里也有抽样）⇒ `有毛病`，点名那一项。"""
    env = _chain(tmp_path, SAMPLING_PROBE, "code/sample_ramsey34.py")
    got = env["v"].verify_proof(env["statement"]["stmt_id"], proof_text=env["column"],
                                         proof_manuscript=env["manuscript"])
    assert got["checked"] is True, got
    assert got["verdict"] == ER.VERDICT_BAD, (got["verdict"], got.get("findings"))
    assert got["defect_step"] == 6, got["defect_step"]
    kinds = [str(f.get("kind")) for f in got["findings"]]
    assert ER.CHECK_EXHAUSTIVE in kinds, kinds
    assert "抽样" in json.dumps(got["findings"], ensure_ascii=False)
    assert got["signed_bit3"] is False, "有毛病不许签第 3 位"


def test_4c_a_search_space_that_the_code_does_not_support_is_faulty(
        tmp_path: pathlib.Path) -> None:
    """③-3 搜索空间与代码对不上（③ 报 2^40，代码里只有 2^36）⇒ `有毛病`，点名那个数。"""
    env = _chain(tmp_path, OVERCLAIM_SPACE_PROBE, "code/overclaim_ramsey34.py")
    got = env["v"].verify_proof(env["statement"]["stmt_id"], proof_text=env["column"],
                                         proof_manuscript=env["manuscript"])
    assert got["verdict"] == ER.VERDICT_BAD, (got["verdict"], got.get("findings"))
    assert got["defect_step"] == 3, got["defect_step"]
    kinds = [str(f.get("kind")) for f in got["findings"]]
    assert ER.CHECK_SPACE in kinds, kinds
    assert "1099511627776" in json.dumps(got["findings"], ensure_ascii=False), got["findings"]


def test_4d_a_missing_report_is_not_checked_and_never_holds(tmp_path: pathlib.Path) -> None:
    """③-4 报告没落地（缺材料）⇒ 没查成，点名缺什么；台账里不留行。

    2026-11-01 业主裁定把「看不出来」这一档整个取消（「看不出错就是没毛病」），于是
    缺材料的落法改了：它既不是"找到了缺陷"（不许打回 F），也不是"没找到缺陷"
    （不许判成立），只有"没查成"这一格 —— `checked=False` + `reason="missing_material"`，
    台账不留行（留一行会把"没查成"冒充成"审过了"）。会审的七项读数仍在
    `exhaustion_review` 里（它是机械读数的正本）。

    2026-11-10 的读侧并入之后，这条命题的台账里本来就有一行「还没在册时 V 审的
    那一签」（`u-`，夹具的 `sign_before_registration`）⇒ "不留行"按"这一趟不增行"判
    （见末尾那一段），不按"台账是空的"判。
    """
    env = _chain(tmp_path)
    report = pathlib.Path(env["store"].root) / env["out"]["report_path"]
    assert report.is_file()
    report.unlink()
    # 会审之前先把台账照一张相（"没查成不落行"要判的是"这一趟有没有多出行"，
    # 不是"台账是不是空的"—— 见下面那段口径说明）。
    before = [str(r.get("verification_id") or "")
              for r in env["v"].list_verifications(env["statement"]["stmt_id"])["items"]]
    assert before and all(v.startswith(VR.PENDING_PREFIX) for v in before), before
    got = env["v"].verify_proof(env["statement"]["stmt_id"], proof_text=env["column"],
                                         proof_manuscript=env["manuscript"])
    assert got["checked"] is False, got
    assert got["reason"] == "missing_material", got["reason"]
    # 不许出现"成立"：这是这一档最容易糊过去的地方
    assert got.get("verdict") in (None, ""), got.get("verdict")
    assert got.get("verdict") != ER.VERDICT_OK
    assert got["signed_bit3"] is False
    reviewed = got["exhaustion_review"]
    text = json.dumps({"why": reviewed["why"], "findings": reviewed["findings"],
                       "missing": reviewed["missing"], "detail": got["detail"]},
                      ensure_ascii=False)
    assert "缺" in text and ("报告" in text or "落盘" in text), text
    # 台账里一行都没多出来（"没查成"不落行）。
    #
    # 2026-11-10（读侧并入，`verifications._claimed_pending_rows` / 2527e727）：这条
    # 命题的台账现在本来就带着「命题还没在册时 V 审的那一签」（本文件 `_chain` 的
    # `sign_before_registration`，`u-` 前缀）⇒ `ledger == []` 这个形状已经不成立，
    # 而且它判的是"台账空不空"、不是"这一次落没落行"。改成"会审前后逐行完全相同"：
    # 既不许这一趟落新行，也不许把已有的前提签读成这一次的读数。强度比改前高：
    # 改前只看"空/不空"，改后连"有没有换掉/删掉已有行"一起判住。
    ledger = env["v"].list_verifications(env["statement"]["stmt_id"])["items"]
    assert [str(r.get("verification_id") or "") for r in ledger] == before, ledger
    assert not any(not str(r.get("verification_id") or "").startswith(VR.PENDING_PREFIX)
                   for r in ledger), ledger


def test_4e_a_proof_column_without_any_experiment_is_unknown(tmp_path: pathlib.Path) -> None:
    """③-5 只有一份证明栏（③ 在、程序路径钉不到实验）、台账里没有对应的实验
    ⇒ `看不出来`（缺 ②③ 与程序）。"""
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    _write(store, SCRIPT_REL, EXHAUSTIVE_PROBE)
    statement = {
        "stmt_id": S.format_id(0), "claim_key": "ramsey34=9",
        "statement_full": "对任意正整数 n，R(3,4)=9。",
        "proof_text": NP.compose_proof_column(
            enumeration="枚举全部 2^36 个染色，无一遗漏"),
    }
    reviewed = ER.review(workspace_root=store.root, statement=statement, experiments=[])
    assert reviewed["verdict"] == ER.VERDICT_UNKNOWN, reviewed
    assert reviewed["missing"], reviewed
    assert any("实验" in str(m) for m in reviewed["missing"]), reviewed["missing"]
    # 缺材料时不许出现"成立"：这是这一档最容易糊过去的地方
    assert ER.verdict_of(reviewed)["verdict"] != ER.VERDICT_OK


# ------------------------------------------------------------------ ④ E -> V 的边


def test_4f_the_edge_from_e_to_v_is_real_and_the_others_are_unchanged(
        tmp_path: pathlib.Path) -> None:
    """④ 边：`E -> V` 在真表里；summon 被受理；其它角色到 V 的边一条都不多。"""
    # ---- 静态那一半：逐角色清单与总数（多开一条 ⇒ 这里红）
    assert C.ALLOWED_EDGES["E"] == frozenset({"B", "D", "V"}), C.ALLOWED_EDGES["E"]
    assert sorted(C.ALLOWED_EDGES["A"]) == ["B"]
    assert sorted(C.ALLOWED_EDGES["B"]) == ["C", "D", "H", "L", "V"]
    assert sorted(C.ALLOWED_EDGES["C"]) == []
    assert sorted(C.ALLOWED_EDGES["D"]) == ["A", "B", "C", "E", "F"]
    # 2026-11-07（业主最终裁定）：裁去 `F→B`（交稿不许向下派 B）、加回 `F→D`（向上交给
    # 父代理 D）—— 一减一加，边总数仍是 34。
    assert sorted(C.ALLOWED_EDGES["F"]) == ["A", "C", "D", "E", "V"]
    # 2026-11-11 业主裁定：「G 的出边集为 C,D,H」「H 为 G 的下级不召唤 G」。
    assert sorted(C.ALLOWED_EDGES["G"]) == ["C", "D", "H"]
    assert sorted(C.ALLOWED_EDGES["H"]) == ["A", "E"]
    # 2026-11-05（业主裁定「V 不应该有出边」）：V 不再能唤起任何人（入边见下一行）。
    assert sorted(C.ALLOWED_EDGES["V"]) == []
    assert sorted(C.ALLOWED_EDGES["L"]) == ["C"]
    assert sorted(C.ALLOWED_EDGES["M"]) == ["A", "B", "C", "D", "E", "G", "H"]
    inbound_v = sorted(role for role, tos in C.ALLOWED_EDGES.items() if "V" in tos)
    assert inbound_v == ["B", "E", "F"], inbound_v
    # 边总数：2026-11-11 的边集收缩（G: 4→3、H: 3→2）之后是 32。
    assert sum(len(tos) for tos in C.ALLOWED_EDGES.values()) == 32

    # ---- 动态那一半：真起一个主控，E 派 V 会审穷举证据，并且拿得到判决
    from agentflow.host import wired_conductor
    from agentflow.tools.conductor_tools import reset_cache

    reset_cache()
    env = _chain(tmp_path)
    sid = env["statement"]["stmt_id"]
    cond = wired_conductor(env["store"], workspace_root=str(env["store"].root))
    # 工具路径（`tools/verify_tools.py:_agent_v`）造不出 V 的秘书，而那一处是 FC-27
    # （禁改区）⇒ 这一条链上没有秘书。业主 2026-10-29 的追加口径是"发签权在秘书手上、
    # 秘书不在场就等于不能发签"（`draft/125` §三点名的装配缺口正是这里），所以这一条
    # 现在判的是诚实的读数：会审照做、台账照落，而第 3 位不翻、且 `sign_issuance`
    # 明写 `checked=False`。装配补齐之后（`AgentV._secretary` 现造 / 调用方传 `secretary=`）
    # 这一条应当改成"三次之后 signed_bit3 为真"，那是下一半的判据。
    got = cond.summon("V", "verify_proof",
                      {"statement_id": sid, "proof_text": env["column"],
                       "proof_manuscript": env["manuscript"]}, by="E")
    assert got.status == "done", (got.status, got.outcome, getattr(got, "detail", ""))
    assert str(got.outcome) != "refused", (got.outcome, getattr(got, "refusal_reason", ""))
    payload = dict(getattr(got, "payload", None) or {})
    assert payload.get("verdict") == ER.VERDICT_OK, payload
    assert payload.get("kind") == "numeric_evidence", payload
    assert payload.get("verification_id"), payload
    assert payload.get("signed_bit3") is False, (
        "工具路径上没有 V 的秘书，却把第 3 位翻了 ⇒ 发签逃过了秘书那一关：" + str(payload))
    issuance = dict(payload.get("sign_issuance") or {})
    assert issuance.get("issue") is False and issuance.get("issued") is False, issuance
    # 这一趟挡在两道闸上：
    # ① p247（2026-11-06）把穷举这一档的轴改由机械会审自己给
    #    （`source=exhaustion_report`：七项全过 ⇒ clean），所以台账那一行算一票 ——
    #    改前这一格问的是"没有秘书 ⇒ 没人判 ⇒ 没轴 ⇒ 0 票"，那是旧口径。现在
    #    `projected=1` / `streak=1`（need=3，仍不够），不算签；
    # ② 发签仍要秘书：工具路径（`tools/verify_tools.py:_agent_v`）造不出 V 的秘书，
    #    这一名自动装配的秘书没有判断面 ⇒ `checked=False`，第 3 位不翻。
    # 装配缺口那一档不算框架失败：V 的会审确实做完了（`checked` 仍为真、`verdict`
    # 与台账都在），缺的只是"谁能发这一签"。
    assert issuance.get("projected") == 1, issuance
    assert issuance.get("streak") == 1, issuance
    assert issuance.get("streak_ok") is False, issuance
    assert issuance.get("need") == VR.SIGN_STREAK_NEED, issuance
    judge = dict(payload.get("secretary_judge") or {})
    assert judge.get("axis") == "clean", judge
    assert judge.get("checked") is True, judge
    assert judge.get("source") == "exhaustion_report", judge
    # 负控：没这条边的角色派 V 仍然被拒（否则上面那条"受理"只是空转）
    bad = cond.summon("V", "list_verifications", {}, by="G")
    assert str(bad.outcome) == "refused", bad
    blob = json.dumps({k: str(v) for k, v in vars(bad).items()}, ensure_ascii=False)
    assert "forbidden_edge" in blob, blob
