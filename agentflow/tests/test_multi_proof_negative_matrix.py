# -*- coding: utf-8 -*-
"""判据（八条负控）：多证明模型不许在下面这八个方向上"看起来连上了"。

业主 2026-10-22：「把线路彻底接通，做全面的测试样例」。正控（`test_multi_proof_end_to_end.py`）
证明每一环能走通；这一份证明每一环在该拦的地方拦、在该放的地方放 ——
八条各自一小段，互不依赖，任何一条红都能单独说清是哪个方向破了。

| 条 | 负控的事 | 它的反面（正控，同一条判据里就核） |
|---|---|---|
| ① | 只签 `#1` ⇒ `#2` 不许借光（unsigned，不是 signed 也不是 stale） | `#1` 自己仍是 signed |
| ② | 签名 sha 与当前正文不符 ⇒ 写入成功（哈希不是门锁），读侧 stale | 改回原样又读 signed |
| ③ | 新增 `#3` 证明 ⇒ 允许写入、读侧 unreviewed（不是被拒） | 已签的 `#1`/`#2` 状态不被牵连 |
| ④ | 正文排版与 `proof_text` 逐字不同 ⇒ 不动 R10、不动对应表格 | 表与正文对不上时那一格必须红 |
| ⑤ | `used_by="stmt:000001#pabc"` ⇒ 不折成 `#p1`（`as_proof_no` 返回 0） | 干净的 `#p2` 照旧认 |
| ⑥ | `doc:0001#claim-3` ⇒ 不被当坏尾巴（`doc:` 分流） | 同一串字不经分流时确实会被判成坏尾巴 |
| ⑦ | 对应表里 `ledger_id` 解析不到 / `file` 不在包内 ⇒ fail 且是 blocker | 修好之后回到 pass |
| ⑧ | 有正文、包里没表 ⇒ fail（`mapping_package_missing`），不许降成 warning | 不适用那一档仍是 unknown |

全部 tmp 工作区、零模型调用（签名的写入口直接调 `verifications.record_verification`）。
"""
from __future__ import annotations

import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL
from agentflow import evidencebits as EB
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import proofloc as PL
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_c.proof_chain import _DepGraph, _split_used_by
from agentflow.agent_g import AgentG
from agentflow.agent_h import mapping_judge as MJ
from agentflow.store import Store

SID = S.format_id(0)
QID = S.format_id(1)
EID = S.format_id(0)
LIT_A = S.format_id(9)
LIT_B = S.format_id(8)

P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
P3 = "第三条路线：\n1. 取对偶。\n2. 收尾。"
_OK = {"verdict": "成立", "findings": []}

TS = "2026-10-22T00:00:00+08:00"


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _own(full: str = "设 G 是 3-正则群；则弦长函数不是常值。",
         short: str = "弦长函数不是常值") -> dict:
    return {"statement_full": full, "statement_text": short, "origin": "own_result",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对",
            "label": short}


def _register_two(st: Store, *, extra: list | None = None) -> dict:
    """登记一条有两份证明的命题（`#p1` 甲、`#p2` 乙），返回 B 的返回值。"""
    proofs = [{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}]
    proofs += list(extra or [])
    return AgentB(st, extractor=None, extract_text=None, config={}).register_statement(
        **_own(), proofs=proofs)


def _row(store: Store, stmt_id: str = SID) -> dict:
    hit = [r for r in store.rows("statements") if str(r.get("stmt_id")) == stmt_id]
    assert hit, f"盘上读不到命题 {stmt_id}"
    return dict(hit[0])


def _sign(store: Store, *, text: str, proof_no: int) -> dict:
    return VR.record_verification(store.root, statement_id=SID, proof_text=text,
                                  verdict=dict(_OK), verifier="agent-V", store=store,
                                  proof_no=proof_no)


def _edit(store: Store, *, proof_no: int, text: str) -> dict:
    """改某一份证明的正文（走正常的写入路径：它必须成功）。"""
    row = _row(store)
    entries = []
    for entry in (row.get(VR.PROOFS_KEY) or []):
        item = dict(entry)
        if int(VR.proof_no_of(item)) == int(proof_no):
            item["text"] = text
        entries.append(item)
    row[VR.PROOFS_KEY] = entries
    with store.tx("statements", actor="test", note="edit") as tx:
        tx.upsert("statements", row, note="edit")
    return _row(store)


def _reading(store: Store) -> dict:
    return VR.statement_review_reading(store.root, _row(store))


def _ledger_rows(store: Store) -> int:
    rows, problems = VR.list_verifications(store.root, statement_id=SID, limit=None)
    assert problems == [], problems
    return len(rows)


def _edit_proof_text(store: Store, text: str) -> dict:
    """改 canonical（`#p1`）那一份的正文：它落在行上的 `proof_text` 那一格。"""
    row = _row(store)
    row["proof_text"] = text
    with store.tx("statements", actor="test", note="edit_p1") as tx:
        tx.upsert("statements", row, note="edit_p1")
    return _row(store)


def _proof(reading: dict, proof_no: int) -> dict:
    hit = [p for p in reading["proofs"] if int(p["proof_no"]) == int(proof_no)]
    assert hit, (proof_no, reading["proofs"])
    return hit[0]


def _r10(store: Store) -> tuple[int, dict]:
    return CL._leg_reading(store, "reviewed_proof_rows", store.root)


def _put_lit(store: Store, lit_id: str) -> None:
    row = S.Literature(lit_id=lit_id, title=f"文献 {lit_id}", type="J", summary="夹具",
                       path=None, added_at=TS)
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())


def _put_experiment(store: Store, exp_id: str = EID) -> None:
    row = S.Experiment(experiment_id=exp_id, claim="网格收敛性检查", claim_key="grid",
                       method="numeric", evidence_kind="cross_check",
                       result="inconclusive", negation_kind="not_proved",
                       code_path="scripts/run.py", code_hash="0123456789abcdef",
                       created_at=TS, created_by="agent-E")
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())


def _paper(project: pathlib.Path, *, extra_env: tuple = (), reflow: bool = False) -> None:
    """写一份正文（2 个 theorem + 1 个 experiment）。

    `reflow=True` 时正文里那段文字的排版与台账 `proof_text` 逐字不同（换行与空格
    都重排过）—— 第 ④ 条要的就是"排版不同不影响读数"。
    """
    tex = PC.package_dir(project) / PC.TEX_NAME
    tex.parent.mkdir(parents=True, exist_ok=True)
    first = ("弦长函数\n     不是常值（这一段按正文排版重排过，与台账的 proof_text 逐字不同）"
             if reflow else "弦长函数不是常值。")
    lines = ["\\documentclass{article}", "\\begin{document}",
             "\\begin{theorem}\\label{thm:chord}" + first + "\\end{theorem}",
             "\\begin{theorem}\\label{thm:finite}有限群的阶有限。\\end{theorem}",
             "\\begin{experiment}\\label{exp:grid}网格收敛性检查。\\end{experiment}",
             "\\end{document}", ""]
    lines.extend(extra_env)
    tex.write_bytes(("\n".join(lines)).encode("utf-8"))
    pkg = PC.package_dir(project)
    (pkg / "proofs").mkdir(parents=True, exist_ok=True)
    for name in ("p1", "p2", "q", "e"):
        (pkg / "proofs" / f"{name}.md").write_bytes((f"{name} 的正文\n").encode("utf-8"))


def _rows(project: pathlib.Path, *, bad_ledger: bool = False,
          bad_file: bool = False) -> list[PM.Row]:
    return [
        PM.Row(kind="theorem", label="thm:chord", env_no=1, ledger_id=f"stmt:{SID}",
               proof_no=1, file="proofs/p1.md", citation_loc_reason="我方自产命题"),
        PM.Row(kind="theorem", label="thm:chord", env_no=1,
               ledger_id=(f"stmt:{SID}#p9" if bad_ledger else f"stmt:{SID}#p2"),
               proof_no=2, file=("proofs/nope.md" if bad_file else "proofs/p2.md"),
               citation_loc_reason="我方自产命题"),
        PM.Row(kind="theorem", label="thm:finite", env_no=2, ledger_id=f"stmt:{QID}",
               proof_no=1, file="proofs/q.md", citation_loc_reason="我方自产命题"),
        PM.Row(kind="experiment", label="exp:grid", env_no=1, ledger_id=f"exp:{EID}",
               proof_no=1, file="proofs/e.md", citation_loc_reason="我方实验"),
    ]


def _workspace_for_paper(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    """造一个"两份证明都签过 + 第二条命题 + 一条实验"的工作区，返回 (store, 项目根)。"""
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    q = AgentB(st, extractor=None, extract_text=None, config={}).register_statement(
        **_own("设 H 是有限群；则 H 的阶有限。", "有限群的阶有限"), proof_text="显然。")
    assert q["ok"] is True and q["stmt_id"] == QID, q
    _put_experiment(st)
    assert _sign(st, text=P1, proof_no=1)["statement_writeback"]["written"] is True
    assert _sign(st, text=P2, proof_no=2)["statement_writeback"]["written"] is True
    return st, st.root / "proj"


# ============================================================ ① 不许借光

def test_proof_two_does_not_borrow_proof_ones_signature(tmp_path: pathlib.Path) -> None:
    """① 只签 `#1` ⇒ `#2` 读 unsigned：不是 signed，也不是 stale。

    三态在这里必须分得开：`unsigned` 是"一次都没签"（处置是派 V），`stale` 是
    "签过、签的不是现在这一份"（处置是重签那一份）。把没签的读成 stale，等于
    让"派活"变成"催签"，而两件事的下一步完全不同。
    """
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    assert _sign(st, text=P1, proof_no=1)["statement_writeback"]["written"] is True

    second = _proof(_reading(st), 2)
    assert second["state"] == "unsigned", f"① #2 没签却读成了 {second['state']!r}（{second}）"
    assert second["state"] != "signed", "① #2 借了 #1 的签"
    assert second["state"] != "stale", "① 没签的 #2 被记成了「签过过期」"
    assert second["reviewed"] is False and second["in_sync"] is None, second
    assert second["grade"] == "conjecture", "① #2 自己的档位被 #1 的签抬到了 " + str(second["grade"])
    # 逐条表整表在（"没有这一格"与"有、值为 False"不许同形）。
    assert EB.reviewed_by_proof(_row(st)) == {1: True, 2: False}, _row(st)["bits"]["evidence"]
    reading = _reading(st)
    assert reading["proofs_unreviewed"] == [f"{SID}#p2"], reading
    assert reading["proofs_stale"] == [], reading
    # 正控：`#1` 自己仍是 signed（否则上面那些"没借光"可能只是因为谁都没签）。
    assert _proof(reading, 1)["state"] == "signed", _proof(reading, 1)


# ============================================================ ② 哈希不是门锁

def test_an_edited_proof_is_written_and_reads_stale_not_refused(tmp_path: pathlib.Path) -> None:
    """② 签名 sha 与当前正文不符 ⇒ 写入成功，读侧 stale。

    这一条钉的是"哈希的职责"：它回答"这份稿在你签完之后有没有被改过"，不是
    "允许不允许你改"。写入期那道闸（`verifications.proof_review_gaps`）只拦
    "没有凭据"，不拦"凭据过期" —— stale 是读数，不是拒收理由。

    两份证明各改一次：`#p2` 走逐条读数（`review_standing` 带证明号），`#p1`
    走 `proof_review_gap`（它判的是 canonical 那一份）。两处都必须"写入成功 +
    读侧 stale"，否则多证明模型里"改哪一份"会得到两种不同的处置。
    """
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    signed1 = _sign(st, text=P1, proof_no=1)
    signed2 = _sign(st, text=P2, proof_no=2)
    assert signed2["proof_sha256"] == VR.proof_sha(P2)

    edited2 = P2 + "\n3. 补一步（签完之后改的）。"
    now = _edit(st, proof_no=2, text=edited2)          # 必须成功，不许抛
    assert VR.proof_text_of(now, 2) == edited2, "② 改稿没落盘（写入被拒了）"
    assert VR.proof_sha(edited2) != signed2["proof_sha256"], "夹具不成立：改完 sha 居然没变"
    # 台账那一行留在签名当时那一份上（历史不许被改写）。
    rows, problems = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert problems == [] and rows[-1]["proof_sha256"] == signed2["proof_sha256"], rows[-1]
    # 写入期那道闸不许把 stale 当成"没有凭据"。
    assert VR.proof_review_gaps(st.root, [now]) == [], "② stale 被折成了「没有凭据」（写入被拦）"
    standing = VR.review_standing(st.root, statement_id=SID, proof_text=edited2, proof_no=2)
    assert standing["state"] == "stale" and standing["ok"] is False, standing
    assert standing["in_sync"] is False, standing

    # 同一件事在 canonical 那一份上（`proof_review_gap` 判的就是 #p1）。
    edited1 = P1 + "\n3. 也补一步。"
    now1 = _edit_proof_text(st, edited1)
    assert now1["proof_text"] == edited1, "② 改 canonical 正文没落盘（写入被拒了）"
    gap = VR.proof_review_gap(st.root, now1)
    assert gap["state"] == "stale" and gap["ok"] is False, gap
    assert VR.proof_review_gaps(st.root, [now1]) == [], "② canonical 的 stale 被当成了「没有凭据」"

    reading = _reading(st)
    assert _proof(reading, 2)["state"] == "stale", reading["proofs"]
    assert _proof(reading, 2)["in_sync"] is False, reading["proofs"]
    assert _proof(reading, 1)["state"] == "stale", reading["proofs"]
    assert reading["proofs_stale"] == [f"{SID}#p1", f"{SID}#p2"], reading
    assert _ledger_rows(st) == 2, "② 改稿不许往台账里补行（那不是「签过一次」）"
    # 正控：两份都改回签名时那一份 ⇒ 立刻又是 signed（不需要重签）。
    _edit(st, proof_no=2, text=P2)
    _edit_proof_text(st, P1)
    reading2 = _reading(st)
    assert _proof(reading2, 1)["state"] == "signed", reading2["proofs"]
    assert _proof(reading2, 2)["state"] == "signed", reading2["proofs"]
    assert reading2["proofs_stale"] == [], reading2
    assert _ledger_rows(st) == 2, "② 改回正文之后台账仍应当只有那两行"
    assert signed1["verification_id"] != signed2["verification_id"], "夹具不成立：两签同一编号"


# ============================================================ ③ 新增证明不是被拒

def test_a_third_proof_is_writable_and_reads_unreviewed(tmp_path: pathlib.Path) -> None:
    """③ 新增 `#3` ⇒ 允许写入、读侧 unreviewed（不是被拒，也不许牵连已签的两份）。"""
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    _sign(st, text=P1, proof_no=1)
    _sign(st, text=P2, proof_no=2)

    more = AgentB(st, extractor=None, extract_text=None, config={}).register_statement(
        **_own(), proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 3, "text": P3}])
    assert more.get("ok") is True, f"③ 新增 #3 被拒了：{more}"
    assert more.get("proofs") == [{"proof_no": 3}], more
    row = _row(st)
    assert [no for no, _ in VR.proof_list(row)] == [1, 2, 3], VR.proof_list(row)
    # 新增这一笔不许动已签的那两份的读数。
    reading = _reading(st)
    assert _proof(reading, 1)["state"] == "signed", reading["proofs"]
    assert _proof(reading, 2)["state"] == "signed", reading["proofs"]
    assert _proof(reading, 3)["state"] == "unsigned", "③ 没签的 #3 读成了 " + str(_proof(reading, 3))
    assert reading["proofs_unreviewed"] == [f"{SID}#p3"], reading
    # 定理级读数不因多一份没签的证明而变（按命题去重）。
    n, det = _r10(st)
    assert n == 1 and det["counted_total"] == 2, (n, det.get("counted"))


# ============================================================ ④ 排版不同不动读数

def test_a_differently_typeset_paper_does_not_touch_the_review_or_the_cell(
        tmp_path: pathlib.Path) -> None:
    """④ 正文排版与 `proof_text` 逐字不同 ⇒ 不动 R10、不动对应表格。

    正文与台账是两份表示：对应表要的是"这条定理在台账里有行、完整证明可查"，
    与 sha 无关。所以这里正文里的定理段是重排过的（换行、空格都不同）、
    `file` 里那份正文也不是 `proof_text` 的逐字副本 —— 两格都不许因此变红。
    反真空：表与正文真的对不上时那一格必须红（同一份判据里核）。
    """
    st, project = _workspace_for_paper(tmp_path)
    before, detail = _r10(st)
    assert before == 1, detail

    _paper(project, reflow=True)
    PM.write_package(project, _rows(project))
    mapping = PM.mapping_reading(project, workspace_root=st.root)
    assert mapping["state"] == "pass", f"④ 排版不同把对应表判红了：{mapping['problems']}"
    after, detail2 = _r10(st)
    assert after == before == 1, f"④ 排版不同动了 R10：{before} -> {after}"
    assert [(c["stmt_id"], c["proof_no"]) for c in detail2["counted"]] == \
        [(c["stmt_id"], c["proof_no"]) for c in detail["counted"]], detail2["counted"]

    closing = CL.ClosingReport()
    CL._check_mapping(closing, str(project), st)
    assert closing.readings["mapping"]["state"] == "pass", closing.readings["mapping"]
    # 反真空：把一行指到正文里没有的 label ⇒ 那一格必须红（否则上面两条是"什么都没查"）。
    bad = _rows(project)
    bad[2] = PM.Row(kind="theorem", label="thm:missing", env_no=2, ledger_id=f"stmt:{QID}",
                    proof_no=1, file="proofs/q.md", citation_loc_reason="我方自产命题")
    PM.write_package(project, bad)
    assert PM.mapping_reading(project, workspace_root=st.root)["state"] == "fail", \
        "④ 表里有一行在正文里找不到环境，对应表却没红"


# ============================================================ ⑤ 坏尾巴不是证明号

def test_a_bad_proof_tail_is_not_folded_into_p1(tmp_path: pathlib.Path) -> None:
    """⑤ `used_by="stmt:000001#pabc"` ⇒ `as_proof_no` 返回 0，分组不折成 `#p1`。

    "折成 `#p1`"与"读不了"是两件事：前者会让一条带坏尾巴的依赖悄悄当成
    canonical 的证据，后者会把坏尾巴原文交回调用方留痕。判据就是
    `as_proof_no` 的 0（"这不是一个证明号"）与 `_split_used_by` 的 `problem`。
    """
    bad = f"stmt:{SID}#pabc"
    assert VR.as_proof_no(bad) == 0, f"⑤ 坏尾巴被读成了证明号 {VR.as_proof_no(bad)}"
    assert VR.as_proof_no(bad) != 1, "⑤ 坏尾巴被折成了 #p1"
    head, no, problem = _split_used_by(bad)
    assert no == PL.DEFAULT_PROOF_NO, (head, no)
    assert problem, "⑤ 坏尾巴的 problem 是空串（读侧看不出这个尾巴是坏的）"
    # 正控：干净的尾巴照旧认（别为了拦坏尾巴把好尾巴也判死）。
    assert VR.as_proof_no(f"stmt:{SID}#p2") == 2, VR.as_proof_no(f"stmt:{SID}#p2")
    clean_head, clean_no, clean_problem = _split_used_by(f"stmt:{SID}#p2")
    assert (clean_head, clean_no, clean_problem) == (f"stmt:{SID}", 2, ""), (
        clean_head, clean_no, clean_problem)

    # 分组那一侧：坏尾巴的边不许被折成"第 1 条证明"，也不许凭空多出一个证明号。
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    _put_lit(st, LIT_A)
    AgentG(st).register_dependency(used_by=bad, kind="prior_art", label="坏尾巴那条边",
                                   source_lit_id=LIT_A, path_group=1, status="closed")
    deps = [dict(r) for r in st.rows("dependencies")]
    assert [str(r["used_by"]) for r in deps] == [bad], deps
    graph = _DepGraph(stmts=[_row(st)], deps=deps, exps=[], lits=[])
    two_d = graph.groups_of(SID)
    assert PL.DEFAULT_PROOF_NO not in two_d, (
        f"⑤ 坏尾巴被折成了 canonical #p1（分组键 {sorted(two_d)}）")
    # 那条边没有被删：它落在自己的原样键上（坏尾巴原文在 `_split_used_by` 的 problem 里）。
    assert graph.groups_of(bad), "⑤ 坏尾巴那条边被静默丢了（连原样键上都找不到）"


# ============================================================ ⑥ doc: 分流

def test_a_doc_reference_is_not_a_bad_proof_tail() -> None:
    """⑥ `doc:0001#claim-3` ⇒ 先按 `doc:` 分流，`problem` 必须为空。

    同一串字直接交给 `proofloc` 会被判成坏尾巴（`#claim-3` 不是 `#pN`）——
    那就是"分流之前就调解析器"的后果：一条正常的 claim 引用被记成坏尾巴，
    而坏尾巴的读法是"按 canonical 读"，于是读数看着没变、台账里已经多了一类假缺陷。
    """
    head, no, problem = _split_used_by("doc:0001#claim-3")
    assert (head, no, problem) == ("doc:0001#claim-3", PL.DEFAULT_PROOF_NO, ""), (head, no, problem)
    # 反真空：不分流时它确实会被判成坏尾巴（这条对照就是"分流为什么必要"）。
    assert PL.parse_used_by_checked("doc:0001#claim-3")[2] != "", "未分流的形态必须能被看见"
    # 图里那条边留在自己的键上：claim 号不许被当命题号索引。
    edge = {"dep_id": "000001", "used_by": "doc:0001#claim-3", "kind": "prior_art",
            "label": "手稿里的第 3 条断言", "status": "closed", "status_reason": "",
            "source_lit_id": None, "source_experiment_id": None,
            "source_stmt_id": None, "source_doc_id": "0001", "path_group": 1}
    graph = _DepGraph(stmts=[], deps=[edge], exps=[], lits=[])
    assert graph.groups_of("doc:0001#claim-3"), "⑥ doc: 那条边没进图"
    assert graph.groups_of("0001") == {}, "⑥ claim 号被当成了命题号"


# ============================================================ ⑦ 对应表两条轴

def test_an_unresolvable_ledger_or_a_missing_file_is_a_blocker(tmp_path: pathlib.Path) -> None:
    """⑦ `ledger_id` 解析不到 / `file` 不在包内 ⇒ mapping 格 fail，且是 blocker。

    两条轴互不遮蔽：一条坏不遮蔽另一条被报（这里分两次造，各自点名）。
    "是 blocker 而不是 warning"这一条要判到底：`Finding.level` 与
    `mapping_judge.level_of` 两处都得是拦门那一档。
    """
    st, project = _workspace_for_paper(tmp_path)
    _paper(project)

    PM.write_package(project, _rows(project, bad_ledger=True))
    got = PM.mapping_reading(project, workspace_root=st.root)
    assert got["state"] == "fail", got
    kinds = [p["kind"] for p in got["problems"]]
    assert "mapping_unresolvable" in kinds, kinds
    closing = CL.ClosingReport()
    CL._check_mapping(closing, str(project), st)
    assert closing.readings["mapping"]["state"] == "fail", closing.readings["mapping"]
    hits = [f for f in closing.findings if f.code == "mapping_unresolvable"]
    assert hits and all(f.level == MJ.LEVEL_BLOCKER for f in hits), [f.to_dict() for f in closing.findings]

    PM.write_package(project, _rows(project, bad_file=True))
    got2 = PM.mapping_reading(project, workspace_root=st.root)
    assert got2["state"] == "fail", got2
    kinds2 = [p["kind"] for p in got2["problems"]]
    assert "mapping_file_missing" in kinds2, kinds2
    closing2 = CL.ClosingReport()
    CL._check_mapping(closing2, str(project), st)
    hits2 = [f for f in closing2.findings if f.code == "mapping_file_missing"]
    assert hits2 and all(f.level == MJ.LEVEL_BLOCKER for f in hits2), \
        [f.to_dict() for f in closing2.findings]
    # 两处都是客观档（判出来就拦门）。
    assert MJ.level_of("mapping_unresolvable") == MJ.LEVEL_BLOCKER
    assert MJ.level_of("mapping_file_missing") == MJ.LEVEL_BLOCKER
    # 正控：修好之后回到 pass（否则"红"可能只是因为这一格永远是红的）。
    PM.write_package(project, _rows(project))
    assert PM.mapping_reading(project, workspace_root=st.root)["state"] == "pass"


# ============================================================ ⑧ 有正文没表

def test_a_paper_without_a_table_fails_and_is_never_downgraded(
        tmp_path: pathlib.Path) -> None:
    """⑧ 有正文、包里没表 ⇒ fail（`mapping_package_missing`），不许降成 warning。

    "没产出"与"没查成"是两件事：没有正文也没有表 ⇒ `unknown`（不适用）；
    有正文却没有表 ⇒ `fail`（G 没交表）。把后者降成 warning，等于让"漏交一整份
    交付物"在收工门上只留一句建议。
    """
    st, project = _workspace_for_paper(tmp_path)
    _paper(project)                       # 只写正文，不写对应表
    json_path, md_path = PM.mapping_paths(project)
    assert not json_path.exists() and not md_path.exists(), (json_path, md_path)

    got = PM.mapping_reading(project, workspace_root=st.root)
    assert got["state"] == "fail", f"⑧ 有正文没表却读成了 {got['state']!r}"
    kinds = [p["kind"] for p in got["problems"]]
    assert "mapping_package_missing" in kinds, kinds
    assert MJ.level_of("mapping_package_missing") == MJ.LEVEL_BLOCKER, "⑧ 这一档被降成了非 blocker"

    closing = CL.ClosingReport()
    CL._check_mapping(closing, str(project), st)
    cell = closing.readings["mapping"]
    assert cell["state"] == "fail", cell
    assert cell["blockers"] >= 1, cell
    hits = [f for f in closing.findings if f.code == "mapping_package_missing"]
    assert hits, [f.to_dict() for f in closing.findings]
    assert all(f.level == MJ.LEVEL_BLOCKER for f in hits), (
        "⑧ 没交表被降成了 " + repr([f.level for f in hits]))
    # 三态的另一档：没有正文也没有表 ⇒ unknown（不适用），不是 fail 也不是 pass。
    empty = _ws(tmp_path / "empty")
    plain = empty.root / "plain"
    PM.mapping_reading(plain)
    got_plain = PM.mapping_reading(plain, workspace_root=empty.root)
    assert got_plain["state"] == "unknown", got_plain
