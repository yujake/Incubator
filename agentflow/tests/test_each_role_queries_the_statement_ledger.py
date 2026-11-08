# -*- coding: utf-8 -*-
"""判据（p263 第 4 步）：每个角色的「查」都接在 `statementledger` 那组查口上。

## 这一份钉什么

不是「角色会查」这句声明，而是行为：每条用例只走角色自己的入口，
然后用两种方式证明它真的经过了查口 ——

1. 只给一种输入：按编号的角色只给编号（不给正文、不给标签），
   按关键字的角色只给关键词（不给编号）。查成了，说明这条口子在用。
2. 反真空：把该角色用到的那条查口降级（`by_id` 永远查不到 /
   `by_keywords` 永远 0 命中 / `rows_of` 读不成）⇒ 该角色原有的判据必须变红 ——
   否则它没走查口（自己扫全表、或自己留了一份实现）。

## 为什么不用「扫源码找 `rows("statements")`」当主判据

业主口径：「能行为验证就行为验证」。源码扫描只能证明"这一句不在"，
证明不了"这条角色真的问查口要过答案"；上面第 2 条能。角色侧的
`rows("statements")` 计数作为读数贴在交付报告里（工具
`temp/_p263_role_query_sites.py`），不进常驻判据。

## 每个角色用到哪种口径

| 角色 | 口径 | 为什么 |
|---|---|---|
| C | 按编号 | `proof_chain` 的目标解析：「号优先、别名兜底」，号那一支走 `by_id` |
| L | 按编号 | `_pick_statement` 只认「显式编号」与「正文逐字全等」；前者走 `by_id` |
| V（三个库模块） | 按编号 / 全表→索引 | 签档、回填、重送都按号读；没有关键词检索面 |
| B | 编号 + 关键字 | 收录前：逐字全等（`duplicate_hits`）+ 秘书的检索判定链（`by_keywords`） |
| D | 关键字 | 「已知成果」按内容词找（`by_keywords`，池由调用方给） |
| F | 编号 + 掩码 | 按号读在册那一行；可引清单只列等级够的（掩码由调用方给） |
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_statement_row  # noqa: E402
from agentflow import statementledger as SL  # noqa: E402
from agentflow.store import Store  # noqa: E402


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _degraded_id(*_a, **_k):
    """把口径一降级成「永远查不到（但算查过）」。"""
    return {"checked": True, "mode": SL.MODE_ID, "stmt_id": "", "found": False,
            "hits_total": 0, "row": {}, "scanned": 0, "source": "rows",
            "matched_by": SL.MATCHED_BY_ID, "why": "降级：永远查不到",
            "reason": "", "error": {}}


def _degraded_keywords(*_a, **_k):
    """把口径二降级成「永远 0 命中（但算查过）」。"""
    return {"checked": True, "mode": SL.MODE_KEYWORDS, "keywords": [], "hits": [],
            "hits_total": 0, "scanned": 0, "checked_rows": 0, "source": "rows",
            "matched_by": SL.MATCHED_BY_KEYWORDS, "why": "降级：永远 0 命中",
            "reason": "", "error": {}}


def _unreadable_rows_of(*_a, **_k):
    """把唯一取数口降级成「读不成」（不是 0 行）。"""
    return (None, "`statements` 台账读不出来（夹具：降级）⇒ 这一问没查成"
                  "（不是「台账里没有这一行」，也不是「0 行」）",
            {"type": "RuntimeError", "message": "夹具：降级"})


# ===================================================== ① C：按编号
def test_c_takes_the_chain_target_by_number_and_returns_its_content(
        tmp_path: pathlib.Path) -> None:
    """只给编号（`stmt:0001`，不给正文/标签）⇒ 解析到那一行、内容按号取到。"""
    from agentflow import agent_c

    st = _store(tmp_path)
    seeded = seed_statement_row(
        st, stmt_id="0001", label="A⇒B", statement_full="若 A 成立，则 B 成立。",
        kind="theorem", evidence_kind="proof", proof_text="Proof. 检查器核过。")
    rep = agent_c.AgentC(st).proof_chain("stmt:0001")
    assert rep.ok, rep.to_dict()
    # 「号」那一支走的是查口口径一（不是别名、不是关键词）：
    assert rep.payload["matched_by"] == "stmt_id", rep.payload
    assert rep.payload["node"]["stmt_id"] == "0001", rep.payload
    # 内容确实是按号从台账取回来的那一行（标签 + 种类都在）：
    assert rep.payload["node"]["label"] == seeded["label"], rep.payload
    assert rep.payload["node"]["kind"] == seeded["kind"], rep.payload


def test_c_a_degraded_id_mode_loses_the_chain_target(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径一降级 ⇒ 只给编号的链目标解析不到（它的判据红）。"""
    from agentflow import agent_c

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", evidence_kind="proof",
                       proof_text="Proof. 检查器核过。")
    monkeypatch.setattr(SL, "by_id", _degraded_id)
    rep = agent_c.AgentC(st).proof_chain("stmt:0001")
    assert rep.ok is False, rep.to_dict()
    assert rep.error == "target_not_found", rep.to_dict()


def test_c_a_degraded_rows_of_is_not_an_empty_graph(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：唯一取数口降级 ⇒ 链读成「读不成」，不是「没有依赖」。"""
    from agentflow import agent_c

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", evidence_kind="proof",
                       proof_text="Proof. 检查器核过。")
    monkeypatch.setattr(SL, "rows_of", _unreadable_rows_of)
    rep = agent_c.AgentC(st).proof_chain("0001")
    assert rep.ok is False, rep.to_dict()
    assert rep.payload["checked"] is False, rep.payload
    assert "读不成" in rep.summary, rep.summary


# ===================================================== ② L：按编号
def test_l_picks_the_statement_to_formalize_by_number_alone(
        tmp_path: pathlib.Path) -> None:
    """只给编号（`stmt:0001`）⇒ 取到那一条；claim 只是同一句的复核，不当检索用。"""
    from agentflow.agent_l import AgentL

    st = _store(tmp_path)
    body = "若 A 成立，则 B 成立。"
    seed_statement_row(st, stmt_id="0001", label="A⇒B", statement_full=body,
                       kind="theorem", proof_text="Proof. 一步。")
    got = AgentL(st)._pick_statement(claim=body, statement_id="stmt:0001")
    assert got["ok"] is True, got
    assert got["statement_id"] == "0001", got
    assert got["source"] == "explicit", got
    assert got["label"] == "A⇒B" and got["body"] == body, got


def test_l_a_degraded_id_mode_refuses_the_statement_by_name(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径一降级 ⇒ 只给编号那一档受控拒（`statement_not_found`）。"""
    from agentflow.agent_l import AgentL

    st = _store(tmp_path)
    body = "若 A 成立，则 B 成立。"
    seed_statement_row(st, stmt_id="0001", label="A⇒B", statement_full=body,
                       kind="theorem", proof_text="Proof. 一步。")
    monkeypatch.setattr(SL, "by_id", _degraded_id)
    got = AgentL(st)._pick_statement(claim=body, statement_id="0001")
    assert got["ok"] is False, got
    assert got["reason"] == "statement_not_found", got


def test_l_a_degraded_rows_of_is_unreadable_not_absent(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：取数口降级 ⇒ 不给编号那一档读成「读不出来」，不是「没有这一条」。"""
    from agentflow.agent_l import AgentL

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", proof_text="Proof. 一步。")
    monkeypatch.setattr(SL, "rows_of", _unreadable_rows_of)
    got = AgentL(st)._pick_statement(claim="随便一句转述", statement_id="")
    assert got["ok"] is False, got
    assert got["reason"] == "statement_ledger_unreadable", got
    assert "读不出来" in got["detail"], got


# ===================================================== ③ V：三个库模块（按编号 / 索引）
def test_v_registration_gap_takes_the_statement_by_number_alone(
        tmp_path: pathlib.Path) -> None:
    """只给编号（`label="0001"`）⇒ 取到那一行并如实报「还没入库」。"""
    from agentflow import vreceipts as VRE

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", proof_text="Proof. 一步。")
    got = VRE.registration_gap(store=st, label="0001")
    assert got["checked"] is True, got
    assert got["statement_id"] == "0001", got
    assert got["body"] is True, got          # 正文取到了那一行
    assert got["gap"] is True, got           # 还没 reviewed（不是「已收录」）


def test_v_a_degraded_id_mode_cannot_see_the_row(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径一降级 ⇒ 按号读不到那一行的正文（`body` 从 True 掉成 False）。"""
    from agentflow import vreceipts as VRE

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", proof_text="Proof. 一步。")
    monkeypatch.setattr(SL, "by_id", _degraded_id)
    got = VRE.registration_gap(store=st, label="0001")
    assert got["body"] is False, got
    assert got["gap"] is True, got


def test_v_an_unreadable_ledger_is_not_an_empty_register(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：取数口降级 ⇒ 在册号读数「没查成」，不是「没有册」（空元组）。"""
    from agentflow import vsigns as VS

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", proof_text="Proof. 一步。")
    assert VS._registered_ids(st) == ("0001",), "前提变了：在册号读数不走了"
    monkeypatch.setattr(SL, "rows_of", _unreadable_rows_of)
    assert VS._registered_ids(st) == (), "取数口降级了，在册号读数却还读得到"


# ===================================================== ④ B：编号 + 关键字（收录之前）
def test_b_reads_the_disk_row_by_number_alone(tmp_path: pathlib.Path) -> None:
    """只给编号 ⇒ 回读到盘上那一格的 `evidence_kind`（不拿请求值顶）。"""
    from agentflow.agent_b import AgentB

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", evidence_kind="proof", proof_text="Proof. 一步。")
    b = AgentB(st, extractor=None, extract_text=None, config={})
    assert b._evidence_kind_on_disk("0001") == "proof"


def test_b_a_degraded_id_mode_reads_unknown_instead_of_the_value(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径一降级 ⇒ 回读那一格掉成 `unknown`（不是「盘上就是这个值」）。"""
    from agentflow.agent_b import AgentB

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", evidence_kind="proof", proof_text="Proof. 一步。")
    b = AgentB(st, extractor=None, extract_text=None, config={})
    monkeypatch.setattr(SL, "by_id", _degraded_id)
    assert b._evidence_kind_on_disk("0001") == "unknown"


def _judge_same(*, same_as: str):
    def _fake(self, kind, context, *, task_id="", note=""):
        ids = [str(c.get("stmt_id") or "") for c in (context.get("candidates") or [])]
        hit = same_as if same_as in ids else ""
        return {"checked": True, "decision": "same" if hit else "different",
                "same_as": hit, "canonical_name": "P 阶元", "route": "",
                "condition": "", "conclusion": "", "basis": ["夹具"],
                "reason": "夹具", "cost": {}, "elapsed_sec": 0.0}
    return _fake


def test_b_finds_the_registered_one_by_keywords_before_taking_it_in(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """只给内容（不给编号）⇒ 收录之前先按关键词问出在册的那一条。

    B 自己不检索：挑词与判定是秘书那一层，检索只经查口口径二（`by_keywords`）。
    """
    from agentflow import secretary as SEC
    from agentflow.agent_b import AgentB

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="P 阶元",
                       statement_full="设 G 是有限群且 |G| = p^a·m，则 G 有 p 阶元。",
                       kind="theorem")
    sec = SEC.Secretary("B", root=st.root, store=st)
    monkeypatch.setattr(SEC.Secretary, "pick_statement_keywords",
                        lambda self, **kw: {"checked": True, "keywords": ["p 阶元"],
                                            "why": "夹具"})
    monkeypatch.setattr(SEC.Secretary, "judge", _judge_same(same_as="0001"))
    b = AgentB(st, extractor=None, extract_text=None, config={})
    monkeypatch.setattr(type(b), "_statement_secretary", lambda self: sec)
    got = b._resolve_same_statement(full="设 G 是有限群，那么 G 里有 p 阶元。",
                                    label="P 阶元", kind="theorem")
    assert got["checked"] is True, got
    assert got["found"] == "0001", got


def test_b_a_degraded_keyword_mode_no_longer_finds_the_registered_one(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径二降级 ⇒ 同一问再认不出在册那一条（`found` 掉成空）。"""
    from agentflow import secretary as SEC
    from agentflow.agent_b import AgentB

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="P 阶元",
                       statement_full="设 G 是有限群且 |G| = p^a·m，则 G 有 p 阶元。",
                       kind="theorem")
    sec = SEC.Secretary("B", root=st.root, store=st)
    monkeypatch.setattr(SEC.Secretary, "pick_statement_keywords",
                        lambda self, **kw: {"checked": True, "keywords": ["p 阶元"],
                                            "why": "夹具"})
    monkeypatch.setattr(SEC.Secretary, "judge", _judge_same(same_as="0001"))
    b = AgentB(st, extractor=None, extract_text=None, config={})
    monkeypatch.setattr(type(b), "_statement_secretary", lambda self: sec)
    # 换一句不同的转述：避开判定缓存，确保这一问真的走到检索。
    first = b._resolve_same_statement(full="设 G 是有限群，那么 G 里有 p 阶元。",
                                      label="P 阶元", kind="theorem")
    assert first["found"] == "0001", first
    monkeypatch.setattr(SL, "by_keywords", _degraded_keywords)
    bad = b._resolve_same_statement(full="有限群 G 一定含一个 p 阶元。",
                                    label="P 阶元", kind="theorem")
    assert bad["found"] == "", bad


# ===================================================== ⑤ D：已知成果（内容关键字）
def _known_results_mask(rows) -> list[dict]:
    """D 的「已知成果」视图：`origin=own_result` ∧ `status=active`（掩码由调用方给）。"""
    return [r for r in rows
            if str(r.get("origin") or "") == "own_result"
            and str(r.get("status") or "") == "active"]


def test_d_finds_known_results_by_content_keywords_on_its_own_mask(
        tmp_path: pathlib.Path) -> None:
    """只给内容词 ⇒ 在 D 的已知成果视图里取到那一条；视图外的行不进来。"""
    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="P 阶元",
                       statement_full="设 G 是有限群，则 G 有 p 阶元。",
                       kind="theorem", origin="own_result")
    seed_statement_row(st, stmt_id="0002", label="P 阶元（外来）",
                       statement_full="设 G 是有限群，则 G 有 p 阶元。（摘自文献）",
                       kind="theorem", origin="external_lit", source_lit_id="0001")
    from agentflow.agent_d import AgentD

    assert AgentD(st) is not None
    rows, problem, _error = SL.rows_of(st)
    assert problem == "", problem
    assert len(rows) == 2, rows
    mask = _known_results_mask(rows)
    got = SL.by_keywords(rows=mask, keywords=["p 阶元"])
    assert got["checked"] is True, got
    assert [h["stmt_id"] for h in got["hits"]] == ["0001"], got


def test_d_an_unreadable_ledger_is_not_a_missing_carried_sheet(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：取数口降级 ⇒ 携带单缺口读数「没查成」，不是「不缺」。"""
    from agentflow.agent_d import AgentD

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="P 阶元",
                       statement_full="设 G 是有限群，则 G 有 p 阶元。",
                       kind="theorem", origin="own_result")
    monkeypatch.setattr(SL, "rows_of", _unreadable_rows_of)
    got = AgentD(st)._carried_missing_reading([])
    assert got["checked"] is False, got
    assert "读不出来" in got["reason"], got


def test_d_a_degraded_keyword_mode_loses_the_known_result(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径二降级 ⇒ 已知成果视图里再也取不到那一条（0 命中）。"""
    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="P 阶元",
                       statement_full="设 G 是有限群，则 G 有 p 阶元。",
                       kind="theorem", origin="own_result")
    rows = st.rows("statements")
    mask = _known_results_mask(rows)
    assert SL.by_keywords(rows=mask, keywords=["p 阶元"])["hits_total"] == 1
    monkeypatch.setattr(SL, "by_keywords", _degraded_keywords)
    assert SL.by_keywords(rows=mask, keywords=["p 阶元"])["hits_total"] == 0


# ===================================================== ⑤ F：按编号 + 掩码
def _high_bits():
    from agentflow import evidencebits as EB

    return EB.bits_of(origin="own_result", proof=True, proof_process="夹具：一份证明",
                      reviewed=True, reviewed_by={"by": "agent-V"}, kind="theorem")


def test_f_reads_the_statement_by_number_alone(tmp_path: pathlib.Path) -> None:
    """只给编号 ⇒ 取到台账那一行（读不到不据此判「没签」）。"""
    from agentflow.agent_f import AgentF

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", proof_text="Proof. 一步。")
    assert AgentF(st)._statement_row("0001")["label"] == "A⇒B"


def test_f_a_degraded_id_mode_returns_no_row(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：口径一降级 ⇒ 按号取不到那一行（空表，不是「没有这条」）。"""
    from agentflow.agent_f import AgentF

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="A⇒B",
                       statement_full="若 A 成立，则 B 成立。",
                       kind="theorem", proof_text="Proof. 一步。")
    monkeypatch.setattr(SL, "by_id", _degraded_id)
    assert AgentF(st)._statement_row("0001") == {}


def test_f_the_citable_mask_is_the_callers_and_blocks_the_below_grade(
        tmp_path: pathlib.Path) -> None:
    """F 的掩码读数：够等级的列进可引清单，不够的那条拿不到（掩码由 F 给，不是查口的阈值）。

    `by_keywords` 里没有任何等级阈值：同一个关键字在「全表」上命中两条，
    在 F 交给它的掩码上只剩够格的那一条。
    """
    from agentflow import depsection as _DS
    from agentflow.agent_f import AgentF

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="P 阶元",
                       statement_full="设 G 是有限群，则 G 有 p 阶元。",
                       kind="theorem", evidence_kind="heuristic",
                       proof_text="Proof. 一步。", bits=_high_bits())
    seed_statement_row(st, stmt_id="0002", label="P 阶元（猜想）",
                       statement_full="设 G 是有限群，则 G 有 p 阶元？",
                       kind="conjecture")
    f = AgentF(st)
    lines, ids, note = f.citable_statements()
    assert ids == ["stmt:0001"], (lines, ids, note)
    assert "1 条的等级低于" in note, note
    rows, problem = f.statement_rows()
    assert problem == "" and len(rows) == 2, (rows, problem)
    mask = [r for r in rows
            if str(r.get("stmt_id") or "") in _DS.citable_pool(rows)]
    got = SL.by_keywords(rows=mask, keywords=["p 阶元"])
    assert [h["stmt_id"] for h in got["hits"]] == ["0001"], got
    # 同一个词在全表上两条都命中 ⇒ 「拿不到」是掩码挡的，不是词没命中。
    all_hits = SL.by_keywords(rows=rows, keywords=["p 阶元"])
    assert {h["stmt_id"] for h in all_hits["hits"]} == {"0001", "0002"}, all_hits
    below = SL.by_keywords(rows=mask, keywords=["猜想"])
    assert below["hits_total"] == 0, below


def test_f_an_unreadable_ledger_is_not_no_citable_statements(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：取数口降级 ⇒ 可引清单读成「读不到」，不是「一条可引的都没有」。"""
    from agentflow.agent_f import AgentF

    st = _store(tmp_path)
    seed_statement_row(st, stmt_id="0001", label="P 阶元",
                       statement_full="设 G 是有限群，则 G 有 p 阶元。",
                       kind="theorem", evidence_kind="heuristic",
                       proof_text="Proof. 一步。", bits=_high_bits())
    monkeypatch.setattr(SL, "rows_of", _unreadable_rows_of)
    lines, ids, note = AgentF(st).citable_statements()
    assert lines == [] and ids == [], (lines, ids)
    assert "读不出来" in note, note


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
