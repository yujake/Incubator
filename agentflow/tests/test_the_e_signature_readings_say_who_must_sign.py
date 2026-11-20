# -*- coding: utf-8 -*-
"""判据：`e_signature` 的读数必须说清"该由谁签"，并给出两格细分（2026-11-03，153-U-06 的丙+乙）。

## 背景（业主 2026-11-03 的调查结论：不是 bug，设计那一半要留）

`is_signed_exhaustion` 认的 `signed_by="V"` 是 E 在 `sign_experiment` 里代写的一格自述
（V 从来没在这条路径上盖过章）。业主 2026-10-27 的裁定是"先报不拦"，所以判定一个字节
都不改。但读数与措辞有两处说错/说不清：

1. `closing.py:4781` 那句写"签名者 E" —— 与字段语义相反（字段里写的是 V；E 是 ②③ 的作者）。
   `tests/test_t0_tier_and_exhaustion_proof.py:22` 的表头也写 `signed_by=E`。
2. 那条"只报不拦"的读数只有 `total` / `ids`，看不出：这一签应当由谁签、
   多少条靠 `e_signature` 背书、V 到底审没审过（审过而判了"有毛病"与"压根没签"
   是两件事，处置完全不同）。

## 这条判据钉住什么

1. `numericproof.suspect_self_signed` 的读数里出现 `signer_required="V"`（别名，不碰
   `schema.py` / `store.py` 的字段）；
2. 出现 `e_signature_backed`（本工作区多少条靠 e_signature 背书）与
   `third_party_verdicts`（那一签的分布：`已签·成立` / `已签·<判决>` / `没签` / `没查成`），
   它们的合计 == `e_signature_backed`；
3. `by_project` 给出本工作区的名字 → 读数（跨工作区要靠跨工作区的扫描，不在一个
   per-workspace 读数里编造）；
4. 收工读数（`rep.readings["suspect_self_signed"]`）把这些格透传出来；
5. 源码里不再出现"签名者 E"这句反话，且 `test_t0_tier_and_exhaustion_proof.py` 的表头
   写的是 `signed_by=V`。
6. 空工区（`Store.init()` 之后一行都没有）上，承重那一格记 `na`，而这两格的读数照旧产出
   （2026-11-20 EMPTYCELL 的 `na` 早退不许把读数一起吞掉；见本文件 a / b / c 三条）。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import closing as CL
from agentflow import numericproof as NP
from agentflow import schema as S
from agentflow.store import Store

REPO = pathlib.Path(__file__).resolve().parents[1]
CLOSING = REPO / "src" / "agentflow" / "closing.py"
T0_TEST = REPO / "tests" / "test_t0_tier_and_exhaustion_proof.py"

#: 一条"V 签下、E 写 ②③"的穷举证明行（与真机上那 7 条同形）。
ROW = {
    "experiment_id": "000001",
    "method": "numeric",
    "evidence_kind": "proof",
    "observations": {"e_signature": {
        "signed_by": "V", "proof_authors": ["E"], "proof_reason": "exhaustion",
        "proof_text": "程序：code/cert.py\n程序设计：把不等式化成一个多项式\n穷尽性：闭盒",
        "script_path": "code/cert.py", "script_sha256": "deadbeef",
    }},
}

#: 台账行的时间戳（schema 要求这一格；取值不影响本文件的判据）。
TS = "2026-11-20T00:00:00+08:00"


def _reading(tmp_path: pathlib.Path) -> dict[str, Any]:
    root = tmp_path / "ws"
    root.mkdir()
    return NP.suspect_self_signed([ROW], root=root, statements=[])


def _empty_reading_problems(rep: CL.ClosingReport) -> list[str]:
    """判据 a 的检查本体（c 要拿它证明"打桩掉写读数 ⇒ 必红"）。

    返回空表 = a 成立。它钉两件事：空工区上承重那一格记 `na`（没有可判对象），
    而承重那一格与 E 签那一格的读数都还在 —— `na` 不等于"不产出读数"。
    """
    problems: list[str] = []
    if rep.status.get("load_bearing") != "na":
        problems.append(
            f"空工区上 load_bearing 记的是 {rep.status.get('load_bearing')!r}，要 na")
    if not rep.readings.get("load_bearing"):
        problems.append("空工区上 readings.load_bearing 没有读数（na 不等于不产出读数）")
    got = rep.readings.get("suspect_self_signed")
    if not isinstance(got, dict) or not got:
        problems.append("空工区上 readings.suspect_self_signed 没有读数（na 不等于不产出读数）")
        return problems
    for key in ("signer_required", "e_signature_backed", "third_party_verdicts", "by_project"):
        if key not in got:
            problems.append(f"空工区上 suspect_self_signed 缺 {key}：{sorted(got)}")
    if got.get("signer_required") != "V":
        problems.append(f"空工区上 signer_required 是 {got.get('signer_required')!r}，要 V")
    if got.get("checked") is not True:
        problems.append(
            f"空工区上 suspect_self_signed.checked 是 {got.get('checked')!r}，要 True（表读得成）")
    if got.get("na") is not True:
        problems.append(
            "空工区上 suspect_self_signed 没标 na：一行都没有是「没有可判对象」，"
            "不是「查过且合格」")
    if "没有可判对象" not in str(got.get("reason") or ""):
        problems.append(
            f"空工区上 suspect_self_signed.reason 没说清为什么不适用：{got.get('reason')!r}")
    return problems


def test_the_reading_names_who_is_supposed_to_sign(tmp_path: pathlib.Path) -> None:
    """① `signer_required="V"`（别名，不动 schema/store）。"""
    got = _reading(tmp_path)
    assert got.get("signer_required") == "V", (
        f"读数里没有 `signer_required=\"V\"` ⇒ 读的人会以为签的就是 E：{sorted(got)}")


def test_the_reading_counts_what_e_signature_backs(tmp_path: pathlib.Path) -> None:
    """② `e_signature_backed` + `third_party_verdicts` 的分布（合计 == backed）。"""
    got = _reading(tmp_path)
    assert got.get("e_signature_backed") == 1, got.get("e_signature_backed")
    dist = got.get("third_party_verdicts")
    assert isinstance(dist, dict) and dist, f"没有那一签的 verdict 分布：{dist!r}"
    assert sum(int(v) for v in dist.values()) == 1, dist
    assert any("没签" in str(k) for k in dist), (
        f"这一条没有第三方签字行 ⇒ 分布里必须能看出『没签』：{dist}")


def test_the_reading_says_which_workspace(tmp_path: pathlib.Path) -> None:
    """③ `by_project` 给出本工作区的名字（跨工作区不在这个读数里编造）。"""
    got = _reading(tmp_path)
    by_project = got.get("by_project")
    assert isinstance(by_project, dict) and by_project, by_project
    assert "ws" in by_project, f"`by_project` 里没有本工作区的名字：{by_project}"


def test_the_closing_report_passes_the_two_cells_through(tmp_path: pathlib.Path) -> None:
    """④ 收工读数里透传这些格（只读，不改 status / 不进 blockers）。"""
    root = tmp_path / "proj"
    root.mkdir()
    st = Store(root)
    st.init()
    rep = CL.check_closing(st, checks=("load_bearing",), project_dir="", report_path="")
    got = rep.readings.get("suspect_self_signed") or {}
    for key in ("signer_required", "e_signature_backed", "third_party_verdicts", "by_project"):
        assert key in got, f"收工读数里没有 {key}：{sorted(got)}"
    assert rep.status.get("load_bearing") != "fail", (
        "这一格是读数：不许因为它把 `load_bearing` 判成 fail（业主 2026-10-27：先报不拦）")


def test_a_the_empty_workspace_still_gets_the_two_cells(tmp_path: pathlib.Path) -> None:
    """⑥ a（2026-11-20 EMPSUSPECT）：空 `Store.init()` 工区上两格读数照给。

    现场：EMPTYCELL 的 `na` 早退（`closing._no_judgeable_rows` 判"三张表一行都没有"）
    在写 `readings.suspect_self_signed` 之前就 return ⇒ 这一格是 `None`，而这条判据的
    ④ 还在老口径上要求它存在。`na` 说的是"这一格没有可判对象"，不是"不产出读数"：
    承重那一格记 `na`（不许折回 pass），E 签那一格的读数照旧给出（`signer_required="V"`、
    `e_signature_backed=0`、分布与逐条读数为空），并标 `na=True` 与理由 —— 三态不许折平。
    """
    root = tmp_path / "empty"
    root.mkdir()
    st = Store(root)
    st.init()
    rep = CL.check_closing(st, checks=("load_bearing",), project_dir="", report_path="")
    problems = _empty_reading_problems(rep)
    assert problems == [], problems


def test_b_a_workspace_with_rows_still_gets_the_two_cells(tmp_path: pathlib.Path) -> None:
    """⑥ b 正控：非空工区上两格照旧（a 不是把读数换成一份空壳）。

    有一行 `experiments` 可判 ⇒ 承重那格不是 `na`；E 签那一格的读数必须与直接调
    `numericproof.suspect_self_signed` 同形（同一份判据，不另写一份）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    row = S.Experiment(experiment_id="0001", claim="Theorem 1.5 的数值检查",
                       claim_key="thm:1.5", method="numeric", evidence_kind="cross_check",
                       result="supports", negation_kind="not_proved", code_path="code/exp.py",
                       code_hash="deadbeefdeadbeef", exit_code=0, created_at=TS)
    row.validate()
    with st.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())

    rep = CL.check_closing(st, checks=("load_bearing",), project_dir="", report_path="")
    got = rep.readings.get("suspect_self_signed") or {}
    for key in ("signer_required", "e_signature_backed", "third_party_verdicts", "by_project"):
        assert key in got, f"有行可判时收工读数里没有 {key}：{sorted(got)}"
    assert got.get("checked") is True, got
    assert not got.get("na"), f"有行可判却说「不适用」：{got}"
    assert rep.status.get("load_bearing") != "na", rep.status

    expected = NP.suspect_self_signed(st.rows("experiments"), root=st.root,
                                      statements=st.rows("statements"))
    assert got.get("e_signature_backed") == expected.get("e_signature_backed"), got
    assert got.get("third_party_verdicts") == expected.get("third_party_verdicts"), got
    assert got.get("by_project") == expected.get("by_project"), got


def test_c_stubbing_out_the_reading_before_the_early_return_makes_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥ c 反真空：把"早退前写读数"打桩掉 ⇒ a 的检查必红。

    打的是那个落点 `_record_suspect_self_signed`（不是整格函数）：换掉整格的话证明的是
    "夹具能红"，而不是"这一行改动是让读数在空工区上活下来的那一行"。
    """
    root = tmp_path / "empty"
    root.mkdir()
    st = Store(root)
    st.init()
    plain = CL.check_closing(st, checks=("load_bearing",), project_dir="", report_path="")
    assert _empty_reading_problems(plain) == [], _empty_reading_problems(plain)

    def _no_reading(rep: CL.ClosingReport, store: Any, *, na_reason: str = "") -> list:
        """改前：读数写在早退之后 ⇒ 空工区上这一格压根没落下。"""
        return []

    monkeypatch.setattr(CL, "_record_suspect_self_signed", _no_reading)
    stubbed = CL.check_closing(st, checks=("load_bearing",), project_dir="", report_path="")
    problems = _empty_reading_problems(stubbed)
    assert problems, "把早退前写读数打桩掉之后 a 的检查居然还是绿的 ⇒ a 没有接线到那个落点"
    assert any("suspect_self_signed" in p for p in problems), problems


def test_the_source_does_not_say_the_signer_is_e_any_more() -> None:
    """⑤ 源码里"签名者 E"这句反话必须消失，表格写的是 V。"""
    text = CLOSING.read_text(encoding="utf-8")
    assert "签名者 E" not in text, (
        "`closing.py` 里还写着" + "签名者 E" + "：字段语义是 `signed_by=\"V\"`（E 只是 ②③ 的作者）")
    t0 = T0_TEST.read_text(encoding="utf-8")
    #: 只核判据表里"①"那一行：同一个文件别处仍可以写 `signed_by=E`（那是"受控拒绝的
    #: 那个值"，判据 ⑦ 的正文就要提它）—— 所以这里不能对全文一刀切。
    row_one = [ln for ln in t0.splitlines() if ln.startswith("| ① |")]
    assert len(row_one) == 1, f"判据表里应有恰好一行 ①，实测 {len(row_one)} 行"
    assert "signed_by=V" in row_one[0] and "signed_by=E" not in row_one[0], (
        f"判据表 ① 那一行还写着 `signed_by=E`（该是 V）：{row_one[0]}")
