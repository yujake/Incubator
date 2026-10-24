"""判据（修法 1）：只读角色的产出必须有一条能落盘的登记通道。

修的是哪两条现场读数：`projects/mp3` 末节第 5 条：「`analysis_reports` = 0：C 的图读数没进登记表（它面外操作），只在手稿 000004 与我的报告里」；- 同族的 H
那一侧：`review_document` / `verify_fixes` 落的发现全部来自机械扫描（`scan_document`），H 自己读出来的那一条（例如"G8 回执没给退出码"）没有任何落点。根因（诊断，
不是猜测）：`(C, H)` 是 `READ_ONLY_ROLES`，两处过滤把它们的写工具剥掉：`tools/base.ToolRegistry._role_surface`（`for_role` 与
`call` 共用的唯一判据）：只读角色的工具面上，`SIDE_EFFECTS_WRITE` 与 `external == "exec"` 的工具一律剥除；2.
`agent_h._support.filter_readonly_h_surface`：H 的自由工具箱更窄（只留 none/read）。例外表 `tools/base.READONLY_CALL_EXCEPTIONS` 只登记了
H 的三件 `review.*`（它们落机械发现、报告文件），而 C 一件都没有 —— 于是 C 的写集（`capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]` 里的
`analysis_reports`）在工具层没有任何载体。真机现场（`projects/mp3/runs/C-20261018-201536-001.json`）里，C 第 4、5 步分别调 `gaps` 与 `handle`，
两次都拿到「没有名为 … 的工具」——它的动作只能由父代理 `summon` 唤起，从来不在它自己的工具面上。修法（业主裁定：优先复用既有表，不新增表）：复用两张既有表，各开一件只挂给那个角色的登记工具（不新增表、不改
`for_role` 的两条过滤）：`analysis.register_report`（roles = ("C",)）→ `analysis_reports`（落盘仍走
`agent_c._support.AnalysisReport.persist`，不重写第二份"怎么存报告"）；- `review.record_finding`（roles = ("H",)）→
`review_findings`（`tx.upsert("review_findings", …)`；不改 `documents.status`）。两件都登记进 `READONLY_CALL_EXCEPTIONS`（FC-27：
这一改动了权限面），并各在 `TOOL_WRITE_SETS` 里有逐工具写集。负控（"修好之前会红"的证据）：`test_removing_the_exception_entry_removes_the_channel`：
把例外表里那一条删掉 ⇒工具立刻从角色面上消失（这正是修法前的形态：`for_role("C")` 里 0 个写工具）；-
`test_the_channel_is_not_reachable_by_other_roles`：`call(..., role="D")` 被拒（登记通道只对那一个角色开）；-
`test_a_kind_outside_the_vocabulary_is_refused`：`kind` 表外 ⇒ 拒，且表里不新增行；- `test_an_empty_evidence_is_refused`：H 那条
`evidence` 空 ⇒ 拒（审校者的判断也要有依据）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import schema as S
from agentflow import tools as T
from agentflow.store import Store
from agentflow.tools import base as TB

from conftest import TS


def _store(tmp_path: Path) -> Store:
    root = tmp_path / "ws"
    (root / "reports").mkdir(parents=True)
    (root / "documents").mkdir(parents=True)
    return Store(root)


def _registry(store: Store):
    return T.build_registry(store=store, workspace_root=store.root).registry


def _writers(reg, role: str) -> list[str]:
    return [s.name for s in reg.for_role(role) if s.side_effect in T.SIDE_EFFECTS_WRITE]


def _universal_writers(role: str) -> set[str]:
    """登记在案的通用能力（2026-10-24 业主裁定：通用能力对所有人开放）。

    它们不是"只读角色的登记通道"，所以下面那些"各只一件"的断言要把它们剔掉 ——
    但剔掉之后必须正向核一遍它们真的在面上（见 `test_the_two_readonly_roles_...`），
    否则这条排除规则会把判据掏空。

    返回的是全部通用能力的名字（不是"只写表的那些"）：`clock.timer_cancel` 也据实是
    `write_local`，而它登记的写集是空集（只改 `out/clock` 的状态）——
    "有没有写表"与"是不是通用能力"是两件事，不能拿写集空不空来筛这一档。
    """
    from agentflow.tools import UNIVERSAL_TOOLS

    return set(UNIVERSAL_TOOLS)


def _counts(store: Store) -> dict[str, int]:
    return {t: len(store.rows(t)) for t in sorted(S.TABLES)}


def _seed_document(store: Store) -> None:
    """写一行 schema 合法的稿件（只为 `review.record_finding` 的 `doc_id` 存在性）。"""
    claim = {
        "claim_id": "claim-1", "kind": "定理", "text": "谱落在区间内。", "status": "证",
        "proof_location": "code/p1.py:12", "numeric_evidence": {},
        "counterexamples": [], "frozen": False, "freeze_reason": "", "allowed_use": "主结果",
        "scope_caveat": "", "revision_hash": "deadbeefdeadbeef", "errata_ids": [],
        "evidence_kind": "proof", "citations": ["rel:0000"], "is_negative": False,
        "negation_kind": None, "disclaimer": "", "section": "主要结果",
    }
    with store.tx("documents", actor="test", note="seed") as tx:
        row = S.Document(
            doc_id="0000", kind="paper", title="通道测试稿件", markdown_path=None,
            claims=[claim], status="draft", review_rounds=0, created_at=TS, updated_at=TS,
        )
        tx.upsert("documents", row.to_dict())


# ============================================================ 结构

def test_the_two_readonly_roles_each_have_one_registration_channel(tmp_path: Path) -> None:
    """正控：C 与 H 的工具面上各有一件自己的登记工具，且各只一件。

    通用能力（`clock.timer_start` 等，据实是 `write_local`）也在它们面上，但那不是
    "登记通道" —— 它们对所有人开放（2026-10-24 业主裁定），所以这里先剔掉再数。
    """
    store = _store(tmp_path)
    reg = _registry(store)
    universal = _universal_writers("C")
    # 只对"据实是写"的那些做正向核对：`clock.now` 这类通用能力本来就不该出现在写工具列表里。
    universal_write = {n for n in universal if reg.get(n).side_effect in T.SIDE_EFFECTS_WRITE}
    assert universal_write, "通用能力里一件写工具都没有 ⇒ 下面的排除会把判据掏空"
    assert universal_write <= set(_writers(reg, "C")), (
        f"通用写工具没有出现在 C 的面上：{sorted(universal_write - set(_writers(reg, 'C')))}"
    )
    assert [n for n in _writers(reg, "C") if n not in universal] == ["analysis.register_report"], (
        _writers(reg, "C")
    )
    h = [n for n in _writers(reg, "H") if n not in universal]
    assert "review.record_finding" in h, h
    # H 的另外三件是既有的落库代理（本修法不动它们）
    assert set(h) == {"review.review_document", "review.verify_fixes",
                      "review.report", "review.record_finding"}, h


def test_both_channels_are_registered_in_the_two_exception_tables() -> None:
    """两处登记必须成对：工具级例外表 ↔ 表级例外表 ↔ 逐工具写集（`[5c]` 那三条）。"""
    from agentflow import capabilities as C
    from agentflow.tools.base import READONLY_CALL_EXCEPTIONS as EXC

    assert {"analysis.register_report"} == {n for n, _ in EXC["C"]}
    assert "review.record_finding" in {n for n, _ in EXC["H"]}
    # 逐工具写集：C 只写 analysis_reports、H 只写 review_findings（都不碰知识表）
    assert C.TOOL_WRITE_SETS["analysis.register_report"] == frozenset({"analysis_reports"})
    assert C.TOOL_WRITE_SETS["review.record_finding"] == frozenset({"review_findings"})
    # 表级例外必须覆盖（否则 `[5c]` ③ 会红；这里正向钉住）
    assert "analysis_reports" in C.READ_ONLY_WRITE_EXCEPTIONS["C"]
    assert "review_findings" in C.READ_ONLY_WRITE_EXCEPTIONS["H"]
    for tool, role in (("analysis.register_report", "C"), ("review.record_finding", "H")):
        assert set(C.TOOL_WRITE_SETS[tool]) <= set(C.READ_ONLY_WRITE_EXCEPTIONS[role]), tool


# ============================================================ 行为（落盘读数）

def test_c_can_register_an_analysis_report_on_disk(tmp_path: Path) -> None:
    """行为：C 登记一条 `analysis_reports` ⇒ 0 → 1 行，且 markdown 文件真的在盘上。

    这一条就是修法验收要求的"前后读数"在测试里的形态。
    """
    store = _store(tmp_path)
    reg = _registry(store)
    before = _counts(store)
    res = reg.call("analysis.register_report", role="C",
                   kind="paths", summary="星形图读数：中心度 6、6 条边全为桥",
                   markdown="# 图读数\n\n- 中心 0000 度 6\n- 6 条边全是桥\n",
                   request="确定性关系分析", payload={"bridges": 6})
    assert res.ok is True, res.error
    after = _counts(store)
    assert before["analysis_reports"] == 0 and after["analysis_reports"] == 1, (before, after)
    row = store.rows("analysis_reports")[-1]
    assert row["created_by"] == "agent-C", row
    assert row["kind"] == "paths" and row["summary"]
    # 落盘实现仍是 `AnalysisReport.persist`：文件名规则与号段是同一份
    assert row["markdown_path"] == f"reports/{row['report_id']}-paths.md", row
    assert (Path(store.root) / row["markdown_path"]).is_file()
    assert json.loads(json.dumps(row["payload"])) == {"bridges": 6}
    # 只有这一张表动了（知识表零写入点）
    changed = {t for t in after if before[t] != after[t]}
    assert changed == {"analysis_reports"}, changed


def test_h_can_record_a_finding_of_its_own(tmp_path: Path) -> None:
    """行为：H 把自己读出来的发现落成 `review_findings` 一行（不改稿件状态）。"""
    store = _store(tmp_path)
    _seed_document(store)
    reg = _registry(store)
    before = _counts(store)
    res = reg.call("review.record_finding", role="H", doc_id="0000",
                   kind="unsupported_claim", target="claim-4",
                   message="数值断言缺本轮实跑回执的 exit_code ⇒ G8 判不了",
                   evidence="run_evidence.commands[*].exit_code 缺失（回执原样：\"     \"）",
                   axis="证据", level="warning",
                   line_unavailable_reason="版本未冻结，拿不到有意义的行号")
    assert res.ok is True, res.error
    after = _counts(store)
    assert after["review_findings"] == before["review_findings"] + 1, (before, after)
    row = store.rows("review_findings")[-1]
    assert row["created_by"] == "agent-H" and row["kind"] == "unsupported_claim"
    assert row["status"] == "open" and row["round"] >= 1
    # 只写这一张表：`documents` 的 status 一个字都没动（改状态是裁决那一档的事）
    assert after["documents"] == before["documents"]
    doc = next(r for r in store.rows("documents") if str(r.get("doc_id")) == "0000")
    assert doc["status"] == "draft", doc["status"]
    # 去重键仍是 `(kind, target, message)`：同一条再登记一次不产生新行
    again = reg.call("review.record_finding", role="H", doc_id="0000",
                     kind="unsupported_claim", target="claim-4",
                     message="数值断言缺本轮实跑回执的 exit_code ⇒ G8 判不了",
                     evidence="（重复）")
    assert again.ok is True and again.data["created"] is False, again.data
    assert len(store.rows("review_findings")) == after["review_findings"]


# ============================================================ 负控

def test_removing_the_exception_entry_removes_the_channel(monkeypatch, tmp_path: Path) -> None:
    """负控（核心）：把例外表里那一条删掉 ⇒ 工具立刻从角色面上消失。

    这就是修法前的形态：`READONLY_CALL_EXCEPTIONS` 里没有 C 的条目时，
    `for_role("C")` 里 0 个「非通用」写工具 —— C 的写集在工具层没有载体，
    图读数只能进回复。通用能力（`clock.timer_start` 等）不受这张表影响：
    它们走 `UNIVERSAL_TOOLS`（2026-10-24 业主裁定），所以这里先剔掉再判空。
    """
    store = _store(tmp_path)
    universal = _universal_writers("C")
    injected = dict(TB.READONLY_CALL_EXCEPTIONS)
    injected.pop("C")
    monkeypatch.setattr(TB, "READONLY_CALL_EXCEPTIONS", injected, raising=True)
    reg = _registry(store)
    remaining = [n for n in _writers(reg, "C") if n not in universal]
    assert remaining == [], _writers(reg, "C")
    # 差分：通用能力仍然在面上（否则上面那条判空可能只是"整个面都空了"）。
    assert universal & set(_writers(reg, "C")), _writers(reg, "C")
    res = reg.call("analysis.register_report", role="C", kind="paths",
                   summary="x", markdown="x")
    assert res.ok is False, res.data
    # 拒绝理由点名「只读角色的结构性过滤把它剥掉了」—— 这正是根因那一行
    # （`tools/base._role_surface`）在删掉例外条目之后会说的话。
    assert "结构性过滤" in str(res.error), res.error
    # 反向：删掉 H 那一条 ⇒ H 也拿不到（同一张表的两侧，不是只对 C 生效的补丁）
    injected2 = dict(TB.READONLY_CALL_EXCEPTIONS)
    injected2["H"] = tuple((n, w) for n, w in injected2["H"] if n != "review.record_finding")
    monkeypatch.setattr(TB, "READONLY_CALL_EXCEPTIONS", injected2, raising=True)
    reg2 = _registry(store)
    assert "review.record_finding" not in _writers(reg2, "H"), _writers(reg2, "H")


def test_the_channel_is_not_reachable_by_other_roles(tmp_path: Path) -> None:
    """负控：登记通道只对那一个角色开（C 的通道不能给别人用，反之亦然）。"""
    store = _store(tmp_path)
    _seed_document(store)
    reg = _registry(store)
    for role in ("A", "B", "D", "E", "F", "G", "H", "M", "V"):
        assert "analysis.register_report" not in _writers(reg, role), role
    for role in ("A", "B", "C", "D", "E", "F", "G", "M", "V"):
        assert "review.record_finding" not in _writers(reg, role), role
    res = reg.call("analysis.register_report", role="D", kind="paths",
                   summary="x", markdown="x")
    assert res.ok is False, res.data
    res2 = reg.call("review.record_finding", role="C", doc_id="0000", kind="overclaim",
                    target="claim-1", message="x", evidence="y")
    assert res2.ok is False, res2.data


def test_a_kind_outside_the_vocabulary_is_refused(tmp_path: Path) -> None:
    """负控：`kind` 不在受控词表 ⇒ 拒（表里不新增行）。

    为什么这一条重要：`analysis_reports` 的 `kind` 是 D 的分派键 —— 塞一个表外取值
    进去会让 D 的读取端出洞，而报告看起来完全正常。
    """
    store = _store(tmp_path)
    reg = _registry(store)
    res = reg.call("analysis.register_report", role="C", kind="随便一个",
                   summary="x", markdown="x")
    assert res.ok is False, res.data
    assert len(store.rows("analysis_reports")) == 0
    # 空 markdown / 空 summary 也拒（`persist()` 的两条前置条件）
    for kw in ({"summary": "", "markdown": "x"}, {"summary": "x", "markdown": " "}):
        r = reg.call("analysis.register_report", role="C", kind="paths", **kw)
        assert r.ok is False, (kw, r.data)
    assert len(store.rows("analysis_reports")) == 0


def test_an_empty_evidence_is_refused(tmp_path: Path) -> None:
    """负控：H 那条 `evidence` 空 ⇒ 拒（审校者的判断也要有依据，行数不变）。"""
    store = _store(tmp_path)
    _seed_document(store)
    reg = _registry(store)
    res = reg.call("review.record_finding", role="H", doc_id="0000", kind="overclaim",
                   target="claim-1", message="x", evidence="   ")
    assert res.ok is False, res.data
    assert len(store.rows("review_findings")) == 0
    # 稿件不存在也拒（不能给不存在的稿件落发现）
    res2 = reg.call("review.record_finding", role="H", doc_id="9999", kind="overclaim",
                    target="claim-1", message="x", evidence="y")
    assert res2.ok is False, res2.data
    assert len(store.rows("review_findings")) == 0


def test_the_two_briefs_name_their_channel() -> None:
    """提示词那一侧：两个角色的 brief 必须写清"你的产出用这一件登记"。

    只加工具不写提示词 ⇒ 模型不知道它存在（`tests/test_agent_prompts.py` 的摘要
    会随提示词变化换值，这条判据钉的是"写进去了"这件事本身）。
    """
    from agentflow.specs.c import SPEC as C_SPEC

    c_text = "\n".join(C_SPEC.brief.boundary) + "\n" + "\n".join(C_SPEC.brief.policy)
    assert "analysis.register_report" in c_text, "C 的 brief 里没写它的登记通道"
    assert "analysis_reports" in c_text
    from agentflow.specs.h import SPEC as H_SPEC

    h_text = "\n".join(H_SPEC.brief.boundary)
    assert "record_finding" in h_text, "H 的 brief 里没写它的登记通道"
