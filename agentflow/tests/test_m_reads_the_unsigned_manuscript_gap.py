# -*- coding: utf-8 -*-
"""INV7 第 ⑤ 条：M 的读数里必须有「已登记、V 签未到」的 F 稿这一格（判据 a–d）。

## 现场（`agentflow/temp/inv7/INV7-REPORT.md` §5.4，`projects/lp-ball-7`，只读取证）

M 在 09:31:58 的 `conductor.patrol` 里已经写明「立命题并派 F 落稿：派 D 立项，由 D 派 F
把候选族写成命题与证明」。可 09:59:41 的读数只有 `statements=1 / statements_unsigned=0 /
documents=0` —— 没有「已登记、还没送审的 F 稿」这一格。10:02:18 F 把
`reports/f-proof-000001.md` 登记进盘（正文 sha `ce0f72…`、`v_sign.state=unsigned`），
此后 M 再没 patrol，读数里也没有任何一格提醒它「该催签」。

## 这一份钉的判据

a. 盘上有「已登记（`proofregistry.parse_entry` 的 `checked`）、V 签还没到」的 F 稿 ⇒
   `researchpending.pending_reading` 的 `counts["manuscript_unsigned"]` 非零、
   `gaps` 里有 `manuscript_unsigned` 那一格，且逐份点名（稿路径 + 正文 sha + 等待
   时长）；同一份读数在 M 的两处可见面上都读得到：`conductor.patrol` 的异常清单与
   `_research_block` 那段提示词。
b. 负控：没有这样的稿 ⇒ 该格存在且为 0、不出 gap（不许把正常挂机堵死）。三档：
   b1 盘上根本没有 `reports/`；b2 只有草稿（没有登记元信息）；b3 已登记且已签。
   b1/b2 分开量的是「登记」这一刀，b3 量的是「未签」这一刀。
c. `next_action` 合法：只指向 D（`capabilities.ALLOWED_EDGES["M"]` 里没有 F / V 这条边），
   逐字口径是「转 D（由 D 派 F 把稿送 V）」；「派 F / 派 V」只许出现在「（由 D …）」那一
   句里 —— 那是 D 的动作，不是 M 的。
d. 反真空：把 ① 接的那一次共享扫描（`agent_f.pending.scan_registered`）打桩成空 ⇒
   a 的那组断言必红。它同时钉住「复用」：若这里自己抄了一份扫描，打桩共享扫描不会
   让 a 变红。

## 与 `statements_unsigned` 分开

两者量的是不同阶段：`statements_unsigned` 量命题台账行（在册、有正文、没签），
`manuscript_unsigned` 量盘上的稿（已登记、签还没到）。一份稿在 B 收录之前没有
`statements` 行，所以前者在那一刻是 0 —— 这正是 INV7 里 M 看不见「该催签」的原因。
判据见 `test_..._the_two_cells_are_separate`（两条各自独立触发、不互相顶替）。

边界：全部 tmp 工作区、假时钟，零真实模型调用、不碰 `projects/`。
"""
from __future__ import annotations

import re
from typing import Any, Mapping

import pytest

from _credential_fixture import issue_credential
from agentflow import capabilities as CAP
from agentflow import clock as CLK
from agentflow import proofregistry as PR
from agentflow import researchpending as RP
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

from conftest import seed_statement_row

AT = "2026-11-18T10:02:18+08:00"
#: 假时钟的"现在"：比 `AT` 晚 1800 秒（等待时长要能逐秒断言，不是"大于 0"）。
NOW = "2026-11-18T10:32:18+08:00"
WAIT_SEC = 1800
SID = "probe-m-manuscript-cell"
TASK = "M 的读数里要有「已登记、V 签未到」这一格"
BODY = "1. 取 ε>0，按定义逐点验证。（前提）"


# ---------------------------------------------------------------- 夹具


@pytest.fixture()
def bench():
    """假时钟：等待时长可逐秒断言；挂机那一拍不真睡。"""
    CLK.reset()
    CLK.reset_waits()
    CLK.reset_parked()
    CLK.reset_observed_events()
    CLK.reset_programs()
    fake = CLK.use(CLK.FakeClock(wall=NOW, monotonic=1000.0))
    try:
        yield fake
    finally:
        CLK.reset()
        CLK.reset_parked()


def _ws(tmp_path) -> tuple[Store, Conductor, Any]:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    return st, cond, ws


def _write_registered(ws, *, mid: str = "000001") -> tuple[str, str]:
    """在盘上落一份「已登记」的 F 证明稿（稿头有正文 sha / 命题指纹 / 版本行 ⇒ checked）。"""
    rel = f"reports/f-proof-{mid}.md"
    sha = PR.proof_sha(BODY)
    fp = PR.proposition_fingerprint(f"证明：中心化引理（夹具 {mid}）")
    text = (
        "# F 的证明手稿：夹具\n\n"
        "- 计划：0000 · 子目标：s1\n"
        f"- 正文sha：{sha}\n"
        f"- 命题指纹：{fp}\n"
        "- 命题类型：conjecture\n"
        f"- 登记时间：{AT}\n"
        f"- 标签：夹具 {mid}\n"
        f"- 版本：{AT}@{sha}\n\n"
        f"## 命题\n\n证明：中心化引理（夹具 {mid}）\n\n"
        f"## 证明\n\n{BODY}\n\n"
        "## 依赖\n\n（自足证明，空表就是声明。）\n"
    )
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return rel, sha


def _write_draft(ws, *, mid: str = "000009") -> str:
    """草稿：有 `## 命题` / `## 证明`，但没有登记元信息 ⇒ 不是「等签」。"""
    rel = f"reports/f-proof-{mid}.md"
    path = ws / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 草稿\n\n## 命题\n\n还没登记的一段话。\n\n"
        f"## 证明\n\n{BODY}\n\n## 依赖\n\n（空表）\n",
        encoding="utf-8")
    return rel


def _m_loop(st: Store, cond: Conductor, ws) -> AgentLoop:
    me = cond.open_top_level_run("M", TASK)
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    return AgentLoop(role="M", session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role="M", session_root=ws, gateway=None,
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=4, workspace_root=str(ws),
                     my_task_id=me)


def _cell_count(reading: Mapping[str, Any]) -> int:
    return int((reading.get("counts") or {}).get("manuscript_unsigned") or 0)


def _gap_codes(reading: Mapping[str, Any]) -> list[str]:
    return [str(g.get("code") or "") for g in (reading.get("gaps") or ())
            if isinstance(g, Mapping)]


def _assert_cell(reading: Mapping[str, Any], *, rel: str, sha: str,
                 waiting_sec: int) -> None:
    """判据 a 的那组断言（d 的反真空也走它）。"""
    assert reading.get("checked") is True, reading
    counts = dict(reading.get("counts") or {})
    assert "manuscript_unsigned" in counts, (
        "M 的读数里没有 manuscript_unsigned 这一格（改前正是这样）", counts)
    assert int(counts.get("manuscript_unsigned") or 0) == 1, counts
    gaps = {str(g.get("code") or ""): dict(g) for g in (reading.get("gaps") or ())
            if isinstance(g, Mapping)}
    assert "manuscript_unsigned" in gaps, (
        "M 的 gaps 里没有「已登记、V 签未到」这一档", reading.get("gaps"))
    gap = gaps["manuscript_unsigned"]
    assert int(gap.get("count") or 0) == 1, gap
    assert list(gap.get("ids") or []) == [rel], gap
    rows = [dict(r) for r in (gap.get("manuscripts") or ()) if isinstance(r, Mapping)]
    assert len(rows) == 1, gap
    row = rows[0]
    assert str(row.get("manuscript") or "") == rel, row
    assert str(row.get("sha") or "") == sha, row
    assert int(row.get("waiting_sec") or 0) == waiting_sec, row
    assert str(row.get("waiting_text") or ""), row
    why = str(gap.get("why") or "")
    assert rel in why, why
    assert sha[:12] in why, why
    assert str(row.get("waiting_text") or "") in why, why
    # 两格分开量：这一格不是从 statements_unsigned 借来的读数。
    assert "statements_unsigned" in counts, counts


def _assert_action_is_legal(reading: Mapping[str, Any]) -> None:
    """判据 c：处置建议只指向 D，且「派 F / 派 V」不是 M 的指令。"""
    action = dict(reading.get("next_action") or {})
    assert str(action.get("code") or "") == "manuscript_unsigned", action
    assert str(action.get("target") or "") == "D", action
    m_edges = set(CAP.ALLOWED_EDGES.get("M") or ())
    assert "D" in m_edges, sorted(m_edges)
    assert not ({"F", "V"} & m_edges), (
        "M 的边表里出现了 F / V 的直连边 —— 本判据的前提变了", sorted(m_edges))
    summary = str(action.get("summary") or "")
    assert summary.startswith("转 D（由 D 派 F 把稿送 V）"), summary
    # 括号里说的是 D 的动作；括号之外不许出现 M 的越界指令。
    outside = re.sub(r"（由 D[^）]*）", "", summary)
    assert "派 F" not in outside, summary
    assert "派 V" not in outside, summary
    assert "M 派" not in summary and "直接派" not in summary, summary


# ============================================================ a：逐份点名 + M 的两处可见面
def test_a_m_reading_names_each_registered_unsigned_manuscript(tmp_path, bench):
    """a：有 registered 未签稿 ⇒ `counts` 非零、gap 逐份点名（稿路径 + sha + 等待时长）。

    改前红：`counts` 里根本没有 `manuscript_unsigned`，`gaps` 里也没有这一档 ——
    M 只能看到 `statements_unsigned=0 / documents=0`。
    """
    st, cond, ws = _ws(tmp_path)
    rel, sha = _write_registered(ws)
    reading = RP.pending_reading(st)
    _assert_cell(reading, rel=rel, sha=sha, waiting_sec=WAIT_SEC)
    _assert_action_is_legal(reading)

    # 可见面 ①：巡查（`conductor.patrol` 的异常清单，同一份读数）。
    reg = build_registry(store=st, conductor=cond, workspace_root=ws).registry
    patrol = reg.call("conductor.patrol", role="M")
    assert patrol.ok, patrol.error
    lines = [str(x) for x in (patrol.data.get("anomalies") or ())]
    line = next((x for x in lines if "manuscript_unsigned" in x), "")
    assert line, lines
    assert "manuscript_unsigned×1" in line, line
    assert rel in line, line
    assert "转 D" in line, line

    # 可见面 ②：挂机判据与它念给模型的那一段（`_research_reading` / `_research_block`）。
    loop = _m_loop(st, cond, ws)
    assert _cell_count(loop._research_reading()) == 1, loop._research_reading()
    loop._research_cache = reading
    loop._tree_cache = {"checked": True, "busy": False,
                        "why_text": "夹具：整棵树闲着"}
    block = loop._research_block()
    assert "manuscript_unsigned" in block, block
    assert rel in block, block


# ============================================================ ②：与 statements_unsigned 分开
def test_the_two_cells_are_separate(tmp_path, bench):
    """②：两格各自独立触发、不互相顶替（量的是不同阶段）。

    现场：一条在册、有正文、没签的命题（`statements_unsigned=1`）＋ 一份已登记未签的
    F 稿（`manuscript_unsigned=1`）⇒ 两格同时非零、两个 gap 同时出现、各自点名自己的
    对象；把稿摘掉之后 `manuscript_unsigned=0` 而 `statements_unsigned` 仍是 1。
    """
    st, _cond, ws = _ws(tmp_path)
    seed_statement_row(st, proof_text="Proof. 夹具正文。",
                       statement_full="定理：夹具命题。",
                       statement_text="夹具命题", kind="theorem")
    rel, sha = _write_registered(ws)
    reading = RP.pending_reading(st)
    counts = dict(reading.get("counts") or {})
    assert int(counts.get("statements_unsigned") or 0) == 1, counts
    assert int(counts.get("manuscript_unsigned") or 0) == 1, counts
    codes = _gap_codes(reading)
    assert "statements_unsigned" in codes and "manuscript_unsigned" in codes, codes
    gaps = {str(g.get("code") or ""): dict(g) for g in (reading.get("gaps") or ())}
    assert rel in (gaps["manuscript_unsigned"].get("ids") or []), gaps
    # 取稿：`manuscript_unsigned` 归零，而命题那一格一条都不动（不互相顶替）。
    (ws / rel).unlink()
    after = dict(RP.pending_reading(st).get("counts") or {})
    assert int(after.get("manuscript_unsigned") or 0) == 0, after
    assert int(after.get("statements_unsigned") or 0) == 1, after
    assert "manuscript_unsigned" not in _gap_codes(RP.pending_reading(st))


# ============================================================ b：负控（该格为 0）
def test_b_without_a_reports_dir_the_cell_is_zero(tmp_path, bench):
    """b1：盘上根本没有 `reports/` ⇒ 该格存在且为 0，且不出 gap。"""
    st, _cond, _ws_ = _ws(tmp_path)
    reading = RP.pending_reading(st)
    assert reading.get("checked") is True, reading
    counts = dict(reading.get("counts") or {})
    assert "manuscript_unsigned" in counts, counts
    assert int(counts["manuscript_unsigned"]) == 0, counts
    assert "manuscript_unsigned" not in _gap_codes(reading), reading.get("gaps")
    assert reading.get("pending") is False, reading


def test_b2_a_draft_is_not_a_waiting_manuscript(tmp_path, bench):
    """b2：只有草稿（没有登记元信息）⇒ 该格为 0（「登记」这一刀真的在量）。"""
    st, _cond, ws = _ws(tmp_path)
    rel = _write_draft(ws)
    assert (ws / rel).is_file()
    reading = RP.pending_reading(st)
    counts = dict(reading.get("counts") or {})
    assert "manuscript_unsigned" in counts, counts
    assert int(counts.get("manuscript_unsigned") or 0) == 0, counts
    assert "manuscript_unsigned" not in _gap_codes(reading), reading.get("gaps")


def test_b3_a_signed_manuscript_is_not_counted(tmp_path, bench):
    """b3：已登记且已签 ⇒ 该格为 0（「未签」这一刀真的在量，不是数文件名）。"""
    st, _cond, ws = _ws(tmp_path)
    rel, sha = _write_registered(ws)
    issue_credential(ws, proof_text=BODY, manuscript=rel, artifact_path=rel)
    reading = RP.pending_reading(st)
    counts = dict(reading.get("counts") or {})
    assert "manuscript_unsigned" in counts, counts
    assert int(counts.get("manuscript_unsigned") or 0) == 0, counts
    assert "manuscript_unsigned" not in _gap_codes(reading), reading.get("gaps")


# ============================================================ c：处置建议合法
def test_c_the_action_points_only_at_d(tmp_path, bench):
    """c：`next_action` 只指向 D，逐字是「转 D（由 D 派 F 把稿送 V）」。

    断言「派 F / 派 V」只出现在「（由 D …）」那一句里：M 的边表没有 F / V 直连边
    （`capabilities._INDIRECT_FROM_M = {F, V}`），那两句是 D 的动作，不是 M 的指令。
    """
    st, _cond, ws = _ws(tmp_path)
    _write_registered(ws)
    reading = RP.pending_reading(st)
    _assert_action_is_legal(reading)
    summary = str((reading.get("next_action") or {}).get("summary") or "")
    assert "转 D（由 D 派 F 把稿送 V）" in summary, summary


# ============================================================ d：反真空（接线打桩）
def test_d_stubbing_the_shared_scan_turns_a_red(tmp_path, bench, monkeypatch):
    """d：把 ① 接的那一次共享扫描打桩成空 ⇒ a 必红。

    同时钉住「复用」：这里若自己抄了一份扫描逻辑，打桩 `agent_f.pending.scan_registered`
    不会让 a 变红 —— 而那时「M 看到的稿」与「F 看到的稿」就已经是两份口径了。
    """
    st, _cond, ws = _ws(tmp_path)
    rel, sha = _write_registered(ws)
    _assert_cell(RP.pending_reading(st), rel=rel, sha=sha, waiting_sec=WAIT_SEC)

    from agentflow.agent_f import pending as FP

    monkeypatch.setattr(FP, "scan_registered", lambda _root, **_kw: {
        "checked": True, "rows": [], "problems": [], "why": "打桩：扫不到登记稿"})
    stubbed = RP.pending_reading(st)
    assert _cell_count(stubbed) == 0, stubbed.get("counts")
    with pytest.raises(AssertionError):
        _assert_cell(stubbed, rel=rel, sha=sha, waiting_sec=WAIT_SEC)
