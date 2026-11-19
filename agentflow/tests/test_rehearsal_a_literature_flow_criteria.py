# -*- coding: utf-8 -*-
"""判据（反真空 / 产品就绪）：A 侧文献全流程那几条闸各自承重吗？

这份不是彩排：它复用 `test_rehearsal_a_literature_flow.py` 的真入口 `_run`
（CLI + 真 `LlmSeam` + 真账本），只在旁边补四类判据：

| # | 判据 | 做法 | 打桩的是哪一格 |
|---|---|---|---|
| 就绪 | 产品侧必须先有 `qualified` 态 | 直接读 `schema.CANDIDATE_STATUSES` + `LitCandidate.validate` 的两条不变量 | 不打桩（这一条今天是红的，见下） |
| a | 无回读回执 ⇒ 不许改 status | 剧本里摘掉 `lit.stage_list` | 剧本（A 的动作），不是产品 |
| a′ | 无抽读回执 ⇒ 不许改 status | 剧本里摘掉 `text.extract`（连带 `fs.read`） | 剧本（A 的动作），不是产品 |
| b | 回填空 ⇒ 提交必红 | `litstage._decisions_from` 返回空 | 产品那一格（回填） |
| c | 去号处理打掉 ⇒ 提交被报告判据拦 | `litstage._rejected_entry` 里塞回 `cand:<槽位>` | 产品那一格（渲染） |
| d | 定稿缺号 ⇒ 清表被报告判据拦 | `litstage._numbered_entry` 不印 `lit:` | 产品那一格（渲染） |
| e | 清表打掉 ⇒ 收工门红 | 剧本里摘掉 `lit.admit_all` | 剧本（A 的动作），不是产品 |
| f | `judged_state` 打桩 ⇒ `undecided_candidates` 消失 | `litstage.judged_state` 恒返回 `rejected` | 产品那一格（收工门第八格读它） |

## 为什么这份文件允许打桩产品那一格

上面 b/c/d/f 打的是"被测的那一段"——它们要证的不是"链能跑"，而是"链上的某一条
判据真的长在那个格子上"。这与 `tests/rehearsal_contract.py` 的「打桩只许五类」
天然冲突，所以这份文件被登记进 `rehearsal_contract.FLOW_CRITERIA_FILES`
（与 `WF_CRITERIA_FILES` 同形：判据文件，不是彩排）。真机同路径的证据仍由那份彩排
提供（它仍在那张名单里、三格照跑）。

## 产品就绪那一条今天是红的（先红）

`schema.CANDIDATE_STATUSES` 还没有 `qualified`：Q1 的 schema 那一半在
`temp/Q1-fc27-schema-qualified.patch` 里，命中 FC-27 的 schema-migration /
eval-criteria，须人编写或人逐行走查 + 2 名 reviewer approve 后 apply。没有它，
`lit.admit` 判收写 `qualified` 会被 `LitCandidate.validate()` 拒 ⇒ ②–⑨ 全都到不了。
所以本文件的第一条判据今天红（红点就是那一格）—— 它不是环境问题，是产品缺口：
`tests/test_lit_submit_registers_only_at_submit.py` 的 6 条也是同一个红点。
补丁 apply 之后它自己变绿，不需要改这一条（另外 7 条反真空也会从 xfail 变成真跑）。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import closing as CL
from agentflow import litstage as L
from agentflow import schema as S

from test_rehearsal_a_literature_flow import (
    RID,
    SLOT_DROP,
    SLOT_KEEP,
    _blocked_reason,
    _events,
    _full_problems,
    _honest_failure_problems,
    _presubmit_problems,
    _report,
    _rows,
    _run,
    _tool_result,
)

#: 受控理由码（被拒那一条在定稿里的理由）。
REJECT_CODE = "rejected_off_topic"


def _assert_authoritative_fail(got: Any) -> None:
    """负控的诚实读数（业主 2026-11-19 裁定 ③）：`verdict=fail` + `rc==1` + 红格点名。

    改前这七条负控都写 `assert got["rc"] == 0` —— 那时收工门手里那一份不是权威结论
    （M 没给 `project_dir` / `report_path`），所以 `rc` 不参与。2026-11-19 之后彩排照
    真机形态带全两个参数 ⇒ 权威结论 = `fail`（这一趟的交付缺了它该有的东西）⇒ 运行
    退出码 1。这里只钉"权威门说 fail、rc 真的是 1、红的恰好是 `literature_pending`"
    —— 各条自己的 `_full_problems` / `_presubmit_problems` 已经逐格判过细节。
    """
    problems = _honest_failure_problems(got, red=["literature_pending"])
    if problems:
        raise AssertionError("负控读数不对：\n- " + "\n- ".join(problems))


def _ready_or_xfail() -> None:
    """产品缺 `qualified` 时，这一格还轮不到它红 —— 用已知卡点登记（不是豁免）。"""
    reason = _blocked_reason()
    if reason:
        pytest.xfail(reason)


def _by_slot(got: dict[str, Any]) -> dict[str, dict]:
    return {str(r.get("slot")): r for r in _rows(got["store"], "lit_candidates")}


def _codes(rep: Any) -> list[str]:
    return [str(f.code) for f in rep.blockers]


# ============================================================ 就绪（先红）


def test_the_product_carries_the_qualified_status() -> None:
    """就绪：`qualified` 必须在状态词表里，且两条不变量由 `validate()` 守。

    这一条今天红 —— 红点就是「产品侧还没完善好」：Q1 的 schema 那一半在
    `temp/Q1-fc27-schema-qualified.patch`（FC-27，需 2 名 reviewer）。它不是环境
    问题，也不是"这条链写错了"；补丁 apply 之后它自己绿。
    """
    assert "qualified" in S.CANDIDATE_STATUSES, (
        "产品缺口（A 侧流程在 HEAD 上不可用）：`schema.CANDIDATE_STATUSES` 还没有 "
        f"`qualified`（现值 {S.CANDIDATE_STATUSES}）⇒ `lit.admit` 判收写 `qualified` 会被 "
        "`LitCandidate.validate()` 拒。修复：人审并 apply "
        "`temp/Q1-fc27-schema-qualified.patch`（FC-27 · schema-migration / "
        "eval-criteria，须人编写或逐行走查 + 2 名 reviewer approve）。")
    base = dict(slot=SLOT_KEEP, batch=1, status="qualified", request_id=RID,
                title="彩排夹具：判收未注册", relevance="为什么与本次检索相关")
    S.LitCandidate(**base).validate()                       # 正控：合格形态不炸
    with pytest.raises(ValueError):
        S.LitCandidate(**{**base, "relevance": ""}).validate()   # 判过的证据必须有
    with pytest.raises(ValueError):
        S.LitCandidate(**{**base, "lit_id": SLOT_DROP}).validate()  # 判收不注册


# ============================================================ a 无回读回执


def test_without_the_readback_the_judge_refuses_to_change_status(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a：摘掉 `lit.stage_list`（回读回执）⇒ `lit.admit` 整笔拒 `no_readback`。

    这就是"无回执不许改 status"那条闸：A 没回读过自己刚写的清单就判收，整笔拒、
    一条都不改；候选行仍是 `pending`。链判据必须因此红 —— 若这一条不红，① 的
    `qualified` 读数就可能是"没回读也判过了"。
    """
    _ready_or_xfail()
    got = _run(tmp_path, monkeypatch, skip=("readback",))
    _assert_authoritative_fail(got)
    refused = _tool_result(_events(got["ws"]), role="A", tool="lit.admit")
    assert refused["ok"] is False, refused
    assert (refused.get("meta") or {}).get("kind") == "no_readback", refused.get("meta")
    row = _by_slot(got)[SLOT_KEEP]
    assert str(row.get("status") or "") == "pending", row
    assert str(row.get("lit_id") or "") == "", row
    assert _full_problems(got), "回读闸被摘掉，链判据却读成了通 ⇒ 判据是橡皮图章"


# ============================================================ a′ 无抽读回执


def test_without_the_read_receipt_the_judge_refuses_to_change_status(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a′：摘掉 `text.extract` + `fs.read` ⇒ `lit.admit` 整笔拒 `no_read_evidence`。

    报 `readable` 却没有抽读回执：整笔拒、逐槽点名、一行都不改。它证明
    `readable` 不是 A 的一句话（抽了不读也算没读）。
    """
    _ready_or_xfail()
    got = _run(tmp_path, monkeypatch, skip=("extract",))
    _assert_authoritative_fail(got)
    refused = _tool_result(_events(got["ws"]), role="A", tool="lit.admit")
    assert refused["ok"] is False, refused
    meta = dict(refused.get("meta") or {})
    assert meta.get("kind") == "no_read_evidence", meta
    assert any(str(p.get("slot")) == SLOT_KEEP for p in meta.get("read_problems") or []), meta
    row = _by_slot(got)[SLOT_KEEP]
    assert str(row.get("status") or "") == "pending", row
    assert _full_problems(got), "抽读闸被摘掉，链判据却读成了通 ⇒ 判据是橡皮图章"


# ============================================================ b 回填空


def test_an_empty_backfill_turns_the_submit_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b：把回填打桩成空（`_decisions_from` 返回 []）⇒ 提交必红（不能静默出定稿）。

    注册确实发生了（`literature` 多一行），但 `qualified` 行没有被结算成 `admitted`、
    `lit_id` 没回填 ⇒ 定稿写不出来（`not_registered`）、清表也没有发生。
    链判据必须因此红 —— 它证明 ④ 的"回填到同一行"不是装饰。
    """
    _ready_or_xfail()
    original = L._decisions_from
    try:
        L._decisions_from = lambda *a, **k: []
        got = _run(tmp_path, monkeypatch)
    finally:
        L._decisions_from = original
    _assert_authoritative_fail(got)
    refused = _tool_result(_events(got["ws"]), role="A", tool="lit.admit_all")
    assert refused["ok"] is False, refused
    assert (refused.get("meta") or {}).get("kind") in ("not_registered", "report_violations"), \
        refused.get("meta")
    row = _by_slot(got)[SLOT_KEEP]
    assert str(row.get("status") or "") == "qualified", row
    assert str(row.get("lit_id") or "") == "", row
    assert _rows(got["store"], "literature"), "注册那一步本该已经发生（红点在回填，不在注册）"
    assert not str(row.get("cleared_at") or ""), row
    archive = got["ws"] / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    assert not archive.is_file(), "回填没写成却清了表"
    assert _full_problems(got), "回填被打桩成空，链判据却读成了通 ⇒ ④ 没有对手方"


# ============================================================ c 去号处理


def test_a_dirty_submitted_report_blocks_the_registration(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：把 `cand:<槽位>` 塞回未入库条目 ⇒ 交报告那一刻的报告判据必红、注册被拦。

    打桩的是"渲染那一格"（`_rejected_entry`），判据是产品自己的
    `report_violations(phase="submitted")`：它拦住之后一条都不注册（literature 0 行）、
    也不会有定稿与归档。链判据必须因此红 —— 它证明"报告里不许出现临时号"是拦门档，
    不是写在文档里的一句话。
    """
    _ready_or_xfail()
    original = L._rejected_entry

    def _dirty(row, **kw: Any) -> list[str]:
        lines = original(row, **kw)
        return [lines[0].replace("- 《", f"- cand:{row.get('slot')} 《", 1)] + lines[1:]

    try:
        L._rejected_entry = _dirty
        got = _run(tmp_path, monkeypatch)
    finally:
        L._rejected_entry = original
    _assert_authoritative_fail(got)
    refused = _tool_result(_events(got["ws"]), role="A", tool="lit.admit_all")
    assert refused["ok"] is False, refused
    assert (refused.get("meta") or {}).get("kind") == "report_violations", refused.get("meta")
    snap = _report(got["ws"], f"lit-{RID}.submitted.md")
    assert "cand:" in snap, "打桩没落到原件上（夹具没改到那一行）"
    assert L.report_violations(snap, phase="submitted"), "元件带临时号却没红 ⇒ 去号判据没有牙"
    assert _rows(got["store"], "literature") == [], "报告判据已经拦了，却还是注册了"
    assert "报告状态：**定稿**" not in _report(got["ws"], f"lit-{RID}.md"), (
        "报告判据已经拦了，却还是出了定稿")
    assert _full_problems(got), "去号处理被打掉，链判据却读成了通 ⇒ ⑤ 是橡皮图章"


# ============================================================ d 定稿缺号


def test_a_final_report_without_numbers_blocks_the_clearing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：定稿的入库条目不印 `lit:` ⇒ 第二个渲染时刻的报告判据红、清表被拦。

    注册与回填都发生了（候选行 `admitted`、`lit_id` 有值），但 `report_violations(
    phase="final", blocking=True)` 拦住了清表：没有归档、行上没有 `cleared_at`。
    它证明 ⑧ 的第二个渲染时刻真的在拦门（不是只跑一次）。
    """
    _ready_or_xfail()
    original = L._numbered_entry

    def _no_number(row, *, tiers: Any, reads: Any) -> list[str]:
        return [f"- 《{row.get('title')}》（彩排：故意不印号）",
                "  判定：批准入库",
                "  可得性：可读全文（readable）"]

    try:
        L._numbered_entry = _no_number
        got = _run(tmp_path, monkeypatch)
    finally:
        L._numbered_entry = original
    _assert_authoritative_fail(got)
    refused = _tool_result(_events(got["ws"]), role="A", tool="lit.admit_all")
    assert refused["ok"] is False, refused
    assert (refused.get("meta") or {}).get("kind") == "report_violations", refused.get("meta")
    row = _by_slot(got)[SLOT_KEEP]
    assert str(row.get("status") or "") == "admitted", row
    assert str(row.get("lit_id") or ""), row
    assert not str(row.get("cleared_at") or ""), "定稿判据拦住了，却还是清了表"
    archive = got["ws"] / "data" / "lit_candidates" / f"archive-{RID}.jsonl"
    assert not archive.is_file(), "定稿判据拦住了，却还是写了归档"
    assert _full_problems(got), "定稿缺号，链判据却读成了通 ⇒ ⑧ 第二个时刻没有对手方"


# ============================================================ e 清表打掉


def test_skipping_the_submit_leaves_the_closing_gate_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：摘掉 `lit.admit_all`（判完不提交）⇒ 收工门红 + `delegation_not_cleared`。

    这是"清表打掉"那一条：同一个 CLI 路、同一个缝，只把提交从剧本里摘掉 ——
    全表已经判完（qualified + rejected），但行上没有 `cleared_at`、也没有归档，
    所以第八格必须拦（blocker 不是读数）。清表之后它变 pass（彩排的正控）。
    """
    _ready_or_xfail()
    got = _run(tmp_path, monkeypatch, skip=("submit",))
    _assert_authoritative_fail(got)
    rep = CL.check_closing(got["store"], checks=("literature_pending",))
    assert rep.status["literature_pending"] == "fail", rep.to_dict()
    assert "delegation_not_cleared" in _codes(rep), rep.to_dict()
    # 这一趟的"提交前状态判据"本身是通的（判完、没清表）—— 所以收工门那格的红
    # 只可能来自"清表没发生"，不是来自"还有没判的"（那会是另一条 blocker）。
    assert not _presubmit_problems(got), (
        "判完不提交这一趟的提交前读数不该有问题：\n- " + "\n- ".join(_presubmit_problems(got)))


# ============================================================ f judged_state


def test_stubbing_judged_state_makes_the_undecided_blocker_disappear(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f：`judged_state` 打桩成恒终态 ⇒ `undecided_candidates` 那条 blocker 必消失。

    判据长在 `litstage.judged_state` 上，不是长在"表里行数"上：把那一条打桩成
    "全是 rejected"，收工门就看不见还有没判的（这正是缺陷形态：读数永远绿）。
    所以这里的判据是反过来的——"必须点名没判的那一条"这条判据在打桩之后必须红。
    """
    _ready_or_xfail()
    got = _run(tmp_path, monkeypatch, skip=("submit",), pending_extra=True)
    _assert_authoritative_fail(got)
    before = CL.check_closing(got["store"], checks=("literature_pending",))
    assert before.status["literature_pending"] == "fail", before.to_dict()
    assert "undecided_candidates" in _codes(before), before.to_dict()
    # 判据原话：全表还有没判的 ⇒ 收工门必须点名 undecided_candidates。
    criterion = lambda rep: "undecided_candidates" in _codes(rep)  # noqa: E731 - 判据本体
    assert criterion(before), "正控：还有一条没判，收工门却没点名"
    original = L.judged_state
    try:
        L.judged_state = lambda row: "rejected"
        after = CL.check_closing(got["store"], checks=("literature_pending",))
    finally:
        L.judged_state = original
    assert not criterion(after), (
        "打桩成恒终态之后仍然点名 undecided_candidates ⇒ 这一格的判据不是长在 "
        "`litstage.judged_state` 上（那它就不是在判'判过没有'）")
    assert _presubmit_problems(got), "还有没判的行，链判据却读成了通"


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
