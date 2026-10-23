# -*- coding: utf-8 -*-
"""判据：端到端矩阵查出来的三处"半断"与 L6 写侧那一半（工具层入口）。

上一路真机矩阵把多证明模型从头走到尾，量出四处"看起来连上了、其实半断"的地方。
这一份逐条钉住修法，每一条都带反真空（"修好了"与"判据没对象"必须分得开）：

| 条 | 半断在哪 | 修完之后要读到什么 |
|---|---|---|
| ① L4 | `_DepGraph` 把坏尾巴的 `problem` 丢掉 ⇒ 那条边挂在原样键上，`groups_of(命题号)` 查不到，链照样 `ok=True` 且没有 warning | 坏尾巴那条边的原串出现在 payload 的 `bad_used_by` 里，并且有一条 warning；好边读数不变；坏的没被折成 `#p1` |
| ② L3 | `bits.reviewed` 只核 `reviewed_by` 那一签（最近那一签）⇒ "签过 #p1、之后改了 #p2"读成没审过 | 任一条证明仍 signed ⇒ 汇总位 True；两条都 stale 之后才 False（逐条读数与它一致） |
| ③ L9 | `StatementRow.bits` 声明成 `("bits","number")` ⇒ 类型面读不出 `bits.reviewed` | 声明是对象，`ui/src/types.ts` 与 `emit_types.render_types()` 逐字节相同 |
| ④ L6 | `papermapping.write_package` 在 `src/` 下零调用方 ⇒ 对应表只能手抄，而判据要求与渲染器逐字相同 | `doc.write_mapping(rows=[…])` 一次写出 json / md / 附录，`mapping_reading` 判成 pass；同输入再调一次字节不变 |
| ⑤ 反真空 | ④ 可能是"什么都没查" | 把 `write_package` 换成"只写 json"（monkeypatch）⇒ ④ 的读数必须红 |

全部 tmp 工作区、零模型调用（签名直接调 `verifications.record_verification` 的写入口）。
"""
from __future__ import annotations

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import proofloc as PL
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_c import AgentC
from agentflow.agent_c.proof_chain import _DepGraph
from agentflow.agent_g import AgentG
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.web import emit_types as ET
from agentflow.webui import readers as RD

#: 命题 P（登记工作区里的第一条行，号由 store 发，实得 `000000`）。
SID = S.format_id(0)
#: 第二条命题（对应表里第二个 theorem 环境用它）。
QID = S.format_id(1)
#: 一条实验行（对应表里那个 experiment 环境用它）。
EID = S.format_id(0)
#: 两条文献（依赖的根）。
LIT_A = S.format_id(9)
LIT_B = S.format_id(8)

#: 证明 #p1（canonical，落 `proof_text`）。
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n >= 3 得结论。"
#: 证明 #p2（落同一行的证明清单）。
P2 = "另一条路线：\n1. 先证引理。\n2. 由引理得结论。"
#: 签完之后改出来的两版（stale 那一档用它；两份要互不相同）。
P1_EDITED = P1 + "\n3. 补一步（签完之后才改的）。"
P2_EDITED = P2 + "\n3. 补一步（签完之后才改的）。"

_OK = {"verdict": "成立", "findings": []}


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _own(full: str = "设 G 是 3-正则群；则弦长函数不是常值。",
         short: str = "弦长函数不是常值") -> dict:
    """自产命题的必填件：`doc_id` + `quote_reason`（`origin="own_result"` 那一档）。"""
    return {"statement_full": full, "statement_text": short, "origin": "own_result",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对",
            "label": short}


def _register_two(st: Store) -> dict:
    """登记一条有两份证明的命题（`#p1` 甲、`#p2` 乙）。

    B-2 闸（`must_start_as_conjecture`）之后的正路：这一笔还没有 V 的签 ⇒ 先按猜想登记
    （`kind="conjecture"` 是明文放行的那一档）。这一份里的判据读的是证明与五位，
    与 `kind` 无关；把首登改成 theorem 才是"绕开闸"，那件事本身会被 B-2 拒。
    """
    return AgentB(st, extractor=None, extract_text=None, config={}).register_statement(
        **_own(), kind="conjecture",
        proofs=[{"proof_no": 1, "text": P1}, {"proof_no": 2, "text": P2}])


def _register_one(st: Store, *, proof_text: str = P1,
                  full: str = "设 G 是 3-正则群；则弦长函数不是常值。",
                  short: str = "弦长函数不是常值") -> dict:
    """登记一条只有 canonical 证明的命题（`full` / `short` 必须与别的行不同）。

    同 `_register_two` 的登记路径：没有 V 的签 ⇒ 首登按猜想。
    """
    return AgentB(st, extractor=None, extract_text=None, config={}).register_statement(
        **_own(full, short), kind="conjecture", proof_text=proof_text)


def _row(store: Store, stmt_id: str = SID) -> dict:
    hit = [r for r in store.rows("statements") if str(r.get("stmt_id")) == stmt_id]
    assert hit, f"盘上读不到命题 {stmt_id}"
    return dict(hit[0])


def _sign(store: Store, *, text: str, proof_no: int) -> dict:
    return VR.record_verification(store.root, statement_id=SID, proof_text=text,
                                  verdict=dict(_OK), verifier="agent-V", store=store,
                                  proof_no=proof_no)


def _edit(store: Store, *, proof_no: int, text: str) -> dict:
    """改某一份证明的正文（改稿是正常写入：走 `store.tx`，不许被哈希拦下）。"""
    row = _row(store)
    if int(proof_no) == 1:
        row["proof_text"] = text
    else:
        entries = []
        found = False
        for entry in (row.get(VR.PROOFS_KEY) or []):
            item = dict(entry)
            if int(VR.proof_no_of(item)) == int(proof_no):
                item["text"] = text
                found = True
            entries.append(item)
        assert found, f"证明清单里没有 #{proof_no} 可改"
        row[VR.PROOFS_KEY] = entries
    with store.tx("statements", actor="test", note=f"edit:{proof_no}") as tx:
        tx.upsert("statements", row, note=f"edit:{proof_no}")
    return _row(store)


def _proof(reading: dict, proof_no: int) -> dict:
    hit = [p for p in (reading.get("proofs") or []) if int(p["proof_no"]) == int(proof_no)]
    assert hit, f"逐条读数里没有 #{proof_no}（读数：{reading.get('proofs')}）"
    return hit[0]


def _bad_tail_world(st: Store) -> tuple[list[dict], str]:
    """造一条好边 + 一条坏尾巴边（① L4 的夹具），返回 (依赖行, 坏尾巴原串)。"""
    assert _register_one(st)["ok"] is True
    _put_lit(st, LIT_A)
    _put_lit(st, LIT_B)
    bad_used = f"stmt:{SID}#pabc"
    good_used = f"stmt:{SID}"
    g = AgentG(st)
    for used, label, lit_id in ((good_used, "好那条边", LIT_A),
                                (bad_used, "坏尾巴那条边", LIT_B)):
        out = g.register_dependency(used_by=used, kind="prior_art", label=label,
                                    source_lit_id=lit_id, path_group=1, status="closed")
        assert out.get("ok") is not False, out
    deps = [dict(r) for r in st.rows("dependencies")]
    assert sorted(str(r["used_by"]) for r in deps) == sorted([good_used, bad_used]), deps
    return deps, bad_used


def _bad_tail_problems(graph: _DepGraph, rep: dict, bad_used: str) -> list[str]:
    """判据 ① 的读数：坏尾巴有没有被点名（图与 payload 两处 + 一条 warning）。

    收在一处是为了让反真空那一条拿同一组读数打红（判据不经两套口径）。
    """
    problems: list[str] = []
    if list(graph.bad_used_by) != [bad_used]:
        problems.append(f"图里没有留下坏尾巴原串（bad_used_by={graph.bad_used_by!r}）")
    payload = dict(getattr(rep, "payload", None) or {})
    if payload.get("bad_used_by") != [bad_used]:
        problems.append("payload 的 bad_used_by 没有点名坏尾巴"
                        f"（读数：{payload.get('bad_used_by')!r}）")
    warnings = [str(w) for w in (getattr(rep, "warnings", None) or [])]
    if not any("bad_used_by" in w or "尾巴" in w for w in warnings):
        problems.append(f"有坏尾巴却没有任何 warning（静默）：{warnings!r}")
    return problems


def _bits_decl_problems(decl: str) -> list[str]:
    """判据 ③ 的读数：`StatementRow.bits` 必须声明成对象（类型面读得出 bits.reviewed）。"""
    problems: list[str] = []
    if "export interface StatementRow {" not in decl:
        return ["type_decls() 里没有 StatementRow"]
    block = decl.split("export interface StatementRow {", 1)[1].split("\n}", 1)[0]
    lines = [line.strip() for line in block.splitlines() if line.strip().startswith("bits:")]
    if len(lines) != 1:
        problems.append(f"StatementRow 里 bits 的声明不是一条：{lines}")
        return problems
    if lines[0] != "bits: Record<string, unknown>;":
        problems.append(f"bits 的声明不是对象（类型面读不出 bits.reviewed）：{lines[0]!r}")
    if "number" in lines[0]:
        problems.append("bits 仍被声明成 number")
    return problems


def _put_lit(store: Store, lit_id: str) -> None:
    row = S.Literature(lit_id=lit_id, title=f"文献 {lit_id}", type="J", summary="夹具",
                       path=None, added_at=S.now_iso())
    row.validate()
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())


def _put_experiment(store: Store) -> None:
    row = S.Experiment(experiment_id=EID, claim="网格收敛性检查", claim_key="grid",
                       method="numeric", evidence_kind="cross_check",
                       result="inconclusive", negation_kind="not_proved",
                       code_path="scripts/run.py", code_hash="0123456789abcdef",
                       created_at=S.now_iso(), created_by="agent-E")
    row.validate()
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", row.to_dict())


# ------------------------------------------------------------------ 论文包夹具

def _paper(project: pathlib.Path) -> None:
    """写 2 个 theorem 环境 + 1 个 experiment 环境（正文里每个环境各要一行对应表）。"""
    tex = PC.package_dir(project) / PC.TEX_NAME
    tex.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join([
        "\\documentclass{article}",
        "\\begin{document}",
        "\\section{主结果}",
        "\\begin{theorem}\\label{thm:chord}弦长函数不是常值。\\end{theorem}",
        "\\begin{theorem}\\label{thm:finite}有限群的阶有限。\\end{theorem}",
        "\\begin{experiment}\\label{exp:grid}网格收敛性检查。\\end{experiment}",
        "\\end{document}",
        "",
    ])
    tex.write_bytes(body.encode("utf-8"))
    pkg = PC.package_dir(project)
    (pkg / "proofs").mkdir(parents=True, exist_ok=True)
    for name, text in (("p1", P1), ("p2", P2), ("q", "显然。"), ("e", "网格收敛性检查")):
        (pkg / "proofs" / f"{name}.md").write_bytes((text + "\n").encode("utf-8"))


def _mapping_rows() -> list[dict]:
    """对应表的四行（`file` 一律是论文包内的相对路径；行以工具入参的形状给出）。"""
    return [
        PM.Row(kind="theorem", label="thm:chord", env_no=1, ledger_id=f"stmt:{SID}",
               proof_no=1, file="proofs/p1.md",
               citation_loc_reason="我方自产命题，没有外部引文").to_dict(),
        PM.Row(kind="theorem", label="thm:chord", env_no=1, ledger_id=f"stmt:{SID}#p2",
               proof_no=2, file="proofs/p2.md",
               citation_loc_reason="我方自产命题，没有外部引文").to_dict(),
        PM.Row(kind="theorem", label="thm:finite", env_no=2, ledger_id=f"stmt:{QID}",
               proof_no=1, file="proofs/q.md",
               citation_loc_reason="我方自产命题，没有外部引文").to_dict(),
        PM.Row(kind="experiment", label="exp:grid", env_no=1, ledger_id=f"exp:{EID}",
               proof_no=1, file="proofs/e.md",
               citation_loc_reason="我方实验，没有引文位置").to_dict(),
    ]


def _three_files(project: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    json_path, md_path = PM.mapping_paths(project)
    return json_path, md_path, PM.appendix_path(project)


def _written_problems(project: pathlib.Path, workspace: pathlib.Path) -> list[str]:
    """④ 的读数：三份在不在 + `mapping_reading` 判成什么（正控与反真空共用这一份）。"""
    problems: list[str] = []
    for path in _three_files(project):
        if not path.is_file():
            problems.append(f"缺 {path.name}（{path}）")
    reading = PM.mapping_reading(project, workspace_root=workspace)
    if reading.get("state") != "pass":
        problems.append(f"mapping_reading 判成 {reading.get('state')!r}：{reading.get('reason')}")
    return problems


def _registry(st: Store):
    """G 的工具面（`doc.write_mapping` 就在它上面）。"""
    return build_registry(store=st, workspace_root=st.root, roles=("G",), strict=True).registry


def _tokens_of_a_paper_fixture(tmp_path: pathlib.Path) -> tuple[Store, pathlib.Path]:
    """造一个"两份证明都签过 + 第二条命题 + 一条实验"的工作区，返回 (store, 项目根)。"""
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    q = _register_one(st, proof_text="显然。", full="设 H 是有限群；则 H 的阶有限。",
                      short="有限群的阶有限")
    assert q["ok"] is True and q["stmt_id"] == QID, q
    _put_experiment(st)
    return st, st.root / "proj"


# ============================================================ ① L4：坏尾巴留痕

def test_a_bad_proof_tail_is_named_instead_of_disappearing(tmp_path: pathlib.Path) -> None:
    """① 坏尾巴那条边必须出现在 `bad_used_by` 里；好边读数不变；坏的没折成 `#p1`。

    断点原文：`head, proof_no, _problem = _split_used_by(used)` —— `problem` 被丢弃，
    于是坏尾巴的边挂在 `"000000#pabc"` 这个键上，`groups_of("000000")` 查不到它：
    那条承重边静默消失，链仍然 `ok=True`、没有一条 warning。
    """
    st = _ws(tmp_path)
    deps, bad_used = _bad_tail_world(st)
    good_used = f"stmt:{SID}"
    graph = _DepGraph(stmts=[_row(st)], deps=deps, exps=[], lits=[])

    # 索引口径不变：坏尾巴不折成任何证明号，好边照旧落在 canonical 的组 1 上。
    two_d = graph.groups_of(SID)
    assert sorted(two_d) == [PL.DEFAULT_PROOF_NO], (
        f"① 坏尾巴被折进了 `groups_of(命题号)`（读到的证明号 {sorted(two_d)}）")
    assert [d.get("label") for d in two_d[PL.DEFAULT_PROOF_NO][1]] == ["好那条边"], (
        f"① 好边的读数被坏尾巴改动了：{two_d[PL.DEFAULT_PROOF_NO][1]}")
    assert graph.groups_of(bad_used), "① 坏尾巴那条边被静默丢了（连原样键上都找不到）"
    assert graph.bad_used_by == [bad_used], (
        f"① 坏尾巴的原串没有留痕（bad_used_by={graph.bad_used_by!r}）")

    # 走完那条动作：payload 里看得见它，且有一条 warning（不许静默）。
    rep = AgentC(st).proof_chain(SID)
    payload = rep.payload
    assert payload.get("bad_used_by") == [bad_used], (
        f"① payload 的 `bad_used_by` 没有点名坏尾巴（读数：{payload.get('bad_used_by')!r}）")
    assert any("bad_used_by" in w or "尾巴" in w for w in (rep.warnings or [])), (
        f"① 有坏尾巴却没有任何 warning（静默）：{rep.warnings!r}")
    # 好边那条路径照旧走到根（反真空：上面那些"没折进去"不是因为一条边都没读到）。
    assert rep.ok is True, f"① 链读不成：{rep.error}"
    assert payload.get("groups_total") == 1, (
        f"① 好边那条路径不见了（groups_total={payload.get('groups_total')!r}）")
    assert [x["reached"] for x in payload["groups"]] == [True], payload["groups"]
    # 同一组读数收在一处（反真空那一条拿它打红，判据不经两套口径）。
    assert _bad_tail_problems(graph, rep, bad_used) == [], _bad_tail_problems(graph, rep, bad_used)


# ============================================================ ② L3：任一条 in-sync

def test_the_summary_bit_stays_true_while_any_proof_is_in_sync(tmp_path: pathlib.Path) -> None:
    """② 签 #p1、签 #p2、改 #p2 ⇒ 汇总位仍 True；再把 #p1 也改掉 ⇒ 才变 False。

    断点原文：`reviewed_by` 只有一格（最近那一签），`_stale_review_cleared` 只核它。
    "签 #p1、改 #p2"之后逐条读数 `[(1,'signed'),(2,'stale')]`、命题级读数
    `reviewed=True`，而 `bits_from_row(row)["reviewed"]` 读成 False。
    """
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    assert EB.bits_from_row(_row(st))["reviewed"] is False, "夹具前提：还没签就应当是 False"

    out1 = _sign(st, text=P1, proof_no=1)
    assert out1["statement_writeback"]["written"] is True, out1["statement_writeback"]
    assert EB.bits_from_row(_row(st))["reviewed"] is True, (
        "② 签了 #p1 之后汇总位不是 True")
    out2 = _sign(st, text=P2, proof_no=2)
    assert out2["statement_writeback"]["written"] is True, out2["statement_writeback"]
    assert EB.reviewed_by_proof(_row(st)) == {1: True, 2: True}, _row(st)["bits"]["evidence"]

    # 改 #p2（不动 #p1）：逐条读数里 #p2 stale、#p1 仍 signed ⇒ 汇总位必须仍为 True。
    edited2 = _edit(st, proof_no=2, text=P2_EDITED)
    assert VR.proof_text_of(edited2, 2) == P2_EDITED and edited2["proof_text"] == P1, edited2
    assert edited2["bits"]["reviewed"] is True, "夹具前提：改稿这一笔没有动位本身"
    reading = VR.statement_review_reading(st.root, edited2)
    assert _proof(reading, 2)["state"] == "stale", (
        f"② 改过正文的 #p2 没有读成 stale：{_proof(reading, 2)}")
    assert _proof(reading, 1)["state"] == "signed", (
        f"② 没被改过的 #p1 跟着 #p2 一起变成非 signed：{_proof(reading, 1)}")
    assert reading["reviewed"] is True, f"② 命题级读数不是「还有一条 in-sync」：{reading}"
    assert EB.bits_from_row(edited2)["reviewed"] is True, (
        "② 逐条读数说还有一条 in-sync，而汇总位读成 False（半断：只核了最近那一签）")

    # 再把 #p1 也改掉：两条都 stale ⇒ 汇总位才变 False（三态不许提前折平）。
    edited1 = _edit(st, proof_no=1, text=P1_EDITED)
    assert edited1["proof_text"] == P1_EDITED, edited1.get("proof_text")
    reading2 = VR.statement_review_reading(st.root, edited1)
    assert _proof(reading2, 1)["state"] == "stale", _proof(reading2, 1)
    assert _proof(reading2, 2)["state"] == "stale", _proof(reading2, 2)
    assert reading2["reviewed"] is False, f"② 两条都 stale 之后命题级读数仍是 True：{reading2}"
    assert EB.bits_from_row(edited1)["reviewed"] is False, (
        "② 两条都 stale 之后汇总位仍是 True（位过期了还在说审过）")

    # 改回签名时那一份 ⇒ 又读 True（不需要重签；哈希是读数，不是门锁）。
    _edit(st, proof_no=1, text=P1)
    _edit(st, proof_no=2, text=P2)
    assert EB.bits_from_row(_row(st))["reviewed"] is True, "② 改回去之后汇总位没有回到 True"


# ============================================================ ③ L9：类型声明

def test_the_statement_row_declares_bits_as_an_object() -> None:
    """③ `StatementRow.bits` 不是 number；生成物与声明逐字节一致。

    断点原文：`readers.StatementRow` 把 `bits` 声明成 `("bits","number")`（`ui/src/
    types.ts` 同），而它实际是 dict ⇒ 类型面读不出 `bits.reviewed`（运行时能读）。
    """
    decl = RD.type_decls()
    assert "export interface StatementRow {" in decl, "③ `type_decls()` 里没有 StatementRow"
    block = decl.split("export interface StatementRow {", 1)[1].split("\n}", 1)[0]
    lines = [line.strip() for line in block.splitlines() if line.strip().startswith("bits:")]
    assert len(lines) == 1, f"③ StatementRow 里 `bits` 的声明不是一条：{lines}"
    assert lines[0] == "bits: Record<string, unknown>;", (
        f"③ `bits` 的声明不是对象（类型面读不出 bits.reviewed）：{lines[0]!r}")
    assert "number" not in lines[0], "③ `bits` 仍被声明成 number"

    # 生成物：与 `emit_types.render_types()` 逐字节相同（手改生成物必红的那条判据同源）。
    types_ts = pathlib.Path(__file__).resolve().parents[1].joinpath(*ET.REPO_REL)
    on_disk = types_ts.read_text(encoding="utf-8")
    assert ET.TYPES_PATH_LABEL in on_disk, f"③ {types_ts} 不是 emit_types 的生成物"
    assert on_disk == ET.render_types(), (
        f"③ {types_ts} 与 `emit_types.render_types()` 不一致（重跑 "
        "`python -m agentflow.web.emit_types`）")
    assert "bits: Record<string, unknown>;" in on_disk, (
        "③ 生成物里 `bits` 不是对象（emit_types 没把这一格带出来）")
    # 同一组读数收在一处（反真空那一条拿它打红，判据不经两套口径）。
    assert _bits_decl_problems(decl) == [], _bits_decl_problems(decl)


# ============================================================ ④ L6：工具层写口

def test_the_tool_writes_the_three_mapping_files_and_is_idempotent(
        tmp_path: pathlib.Path) -> None:
    """④ `doc.write_mapping(rows=[…])` 一次写出三份，读成 pass，再调一次字节不变。

    断点原文：`papermapping.write_package` 在 `src/` 下零调用方 —— G 的工具面只有
    `doc.paper_compile`，而技能文档要求"先有对应表再写正文"。手抄的 md / 附录与渲染器
    逐字对不上（`md_drifted` / `mapping_paper_mismatch`），于是那条路根本不可达。
    """
    st, project = _tokens_of_a_paper_fixture(tmp_path)
    _paper(project)
    reg = _registry(st)
    assert "doc.write_mapping" in [s.name for s in reg.for_role("G")], (
        f"④ G 的工具面上没有 `doc.write_mapping`：{[s.name for s in reg.for_role('G')]}")
    rows = _mapping_rows()

    res = reg.call("doc.write_mapping", role="G", project="proj", rows=rows)
    assert res.ok is True, f"④ 写对应表没走成：{res.error}（meta={res.meta}）"
    assert res.data.get("state") == "pass", (
        f"④ 三份写出来了但现读判不过：{res.data.get('state')!r} / {res.data.get('problems')}")
    assert [p for p in _written_problems(project, st.root)] == [], (
        f"④ 写完之后三份/读数不对：{_written_problems(project, st.root)}")

    # 三份都由 json 渲染：md 与附录逐字等于盘上 json 的渲染结果（手抄必红）。
    json_path, md_path, frag = _three_files(project)
    rows_out = PM.parse_rows(json.loads(json_path.read_text(encoding="utf-8")))[0]
    assert md_path.read_text(encoding="utf-8") == PM.render_mapping_markdown(rows_out), (
        "④ MAPPING.md 不是由盘上 json 渲染出来的那一份")
    assert frag.read_text(encoding="utf-8").strip() == PM.render_appendix(rows_out).strip(), (
        "④ 正文附录不是由盘上 json 渲染出来的那一份")
    tex = (PC.package_dir(project) / PC.TEX_NAME).read_text(encoding="utf-8")
    assert PM.APPENDIX_INPUT in tex, "④ 正文里没有 `\\input{mapping-appendix}`"

    # 幂等：同一批行再写一次，三份逐字节不变。
    before = {p.name: p.read_bytes() for p in _three_files(project)}
    res2 = reg.call("doc.write_mapping", role="G", project="proj", rows=rows)
    assert res2.ok is True, f"④ 第二次写没走成：{res2.error}"
    after = {p.name: p.read_bytes() for p in _three_files(project)}
    assert after == before, (
        f"④ 同一批行写两次字节变了：{sorted(k for k in before if before[k] != after.get(k))}")


def test_the_positive_readings_go_red_when_the_writer_only_writes_json(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """⑤ 反真空：把 `write_package` 换成"只写 json"⇒ ④ 的读数必须红。

    没有这一条，④ 的绿可能只是"什么都没查"：三份都在、读数 pass 这两件事必须有对象。
    这里 monkeypatch 的正是工具内部调用的那一个函数（它不自己渲染，所以换掉它等于
    把"渲染 md 与附录"整段摘掉）。
    """
    st, project = _tokens_of_a_paper_fixture(tmp_path)
    _paper(project)
    reg = _registry(st)
    rows = _mapping_rows()

    def _json_only(root, items):
        json_path, md_path = PM.mapping_paths(root)
        payload = {"rows": [row.to_dict() for row in items]}
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_bytes(
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        md_path.unlink(missing_ok=True)
        PM.appendix_path(root).unlink(missing_ok=True)
        return json_path, md_path, PM.appendix_path(root)

    monkeypatch.setattr(PM, "write_package", _json_only)
    res = reg.call("doc.write_mapping", role="G", project="proj", rows=rows)
    assert res.ok is False, f"⑤ 只写了 json，工具却报成功：{res.data}"
    assert res.meta.get("kind") == "mapping_not_clean", res.meta
    problems = _written_problems(project, st.root)
    assert problems, "⑤ 只写了 json，而 ④ 的读数仍然全绿（那说明 ④ 是真空的）"
    assert any("MAPPING.md" in p for p in problems), problems
    assert any("mapping-appendix.tex" in p for p in problems), problems


# ============================================================ L6 工具层的形状

def test_the_tool_declares_a_write_and_refuses_a_bad_row(tmp_path: pathlib.Path) -> None:
    """附：`doc.write_mapping` 的声明与拒绝面（写盘那一档要如实声明）。

    - 声明 `write_local`：它真的写 `out/paper/` 下三份；
    - 不是 exec（不起子进程）—— 与 `doc.paper_compile` 的那根轴分开；
    - 一行读不懂 ⇒ ok=False 且一行都不写（半张表比没有表更坏）。
    """
    st, project = _tokens_of_a_paper_fixture(tmp_path)
    _paper(project)
    reg = _registry(st)
    spec = reg.get("doc.write_mapping")
    assert spec.side_effect == "write_local", spec.side_effect
    assert spec.declared_external == "none", spec.declared_external
    assert spec.roles == ("G",), spec.roles

    bad_rows = _mapping_rows()
    # 形状上合法（schema 会放行），读侧判据说读不懂（必填字段空）—— 走的是行校验那一支。
    bad_rows[0] = {**bad_rows[0], "label": ""}
    res = reg.call("doc.write_mapping", role="G", project="proj", rows=bad_rows)
    assert res.ok is False and res.meta.get("kind") == "mapping_unresolvable", res.meta
    assert res.meta.get("problems"), res.meta
    assert not any(p.is_file() for p in _three_files(project)), (
        "坏行被写掉了：一行读不懂时应当一行都不写")


# ============================================================ 反真空：三处半断各注入一次
#
# 上面 ①②③ 的绿必须"有对象"：把每一处修好的那一格还原成改前的形态（只在本进程里
# monkeypatch，不碰 src），对应的判据必须当场红。三处各一条，任何一条不红都说明那组
# 断言在对着空气。


def test_negative_control_the_dropped_bad_tail_problem_is_caught(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空（① L4）：把 `problem` 丢掉（改前那一行）⇒ ① 的读数必须红。

    注入点就是断点原文里那个 `_problem`：`_DepGraph` 拿到的 `problem` 一律为空 ⇒
    `bad_used_by` 留不下原串、`_bad_tail_warnings` 一条也说不出、payload 里那格是空的
    —— 那条承重边静默消失，链照样 `ok=True`。`_bad_tail_problems` 是正控用的同一份读数。
    """
    from agentflow.agent_c import proof_chain as PC

    st = _ws(tmp_path)
    deps, bad_used = _bad_tail_world(st)
    real = PC._split_used_by

    def _dropped(used: str) -> tuple[str, int, str]:
        head, no, _problem = real(used)
        return head, no, ""

    monkeypatch.setattr(PC, "_split_used_by", _dropped, raising=True)
    graph = _DepGraph(stmts=[_row(st)], deps=deps, exps=[], lits=[])
    rep = AgentC(st).proof_chain(SID)
    assert graph.bad_used_by == [], graph.bad_used_by        # 留痕消失（改前的形态）
    problems = _bad_tail_problems(graph, rep, bad_used)
    assert problems != [], "problem 丢掉之后判据 ① 仍然全绿 ⇒ 那条判据没有对象"
    assert any("bad_used_by" in p for p in problems), problems
    assert any("warning" in p for p in problems), problems


def test_negative_control_only_the_latest_signature_turns_the_summary_bit_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空（② L3）：把"逐条 sha 表"关掉、只核最近那一签 ⇒ ② 的读数必须红。

    注入点：`evidencebits.reviewed_sha_by_proof` 一律返回空 ⇒ `_stale_review_cleared`
    退回改前那条路（只看 `reviewed_by` 里那一次签名）。夹具就是 ② 的前半：签 #p1、
    签 #p2、只改 #p2。这时逐条读数说 #p1 仍 signed、命题级 `reviewed=True`，
    而汇总位被最近那一签（#p2）拖成 False —— 正是"签过 #p1、之后改了 #p2"读成没审过。
    """
    st = _ws(tmp_path)
    assert _register_two(st)["ok"] is True
    assert _sign(st, text=P1, proof_no=1)["statement_writeback"]["written"] is True
    assert _sign(st, text=P2, proof_no=2)["statement_writeback"]["written"] is True
    assert _edit(st, proof_no=2, text=P2_EDITED)["proof_text"] == P1
    assert EB.bits_from_row(_row(st))["reviewed"] is True, "夹具前提：改稿这一笔没有动位本身"

    monkeypatch.setattr(EB, "reviewed_sha_by_proof", lambda bits: {}, raising=True)
    row = _row(st)
    reading = VR.statement_review_reading(st.root, row)
    assert _proof(reading, 1)["state"] == "signed", reading["proofs"]
    assert reading["reviewed"] is True, reading
    assert EB.bits_from_row(row)["reviewed"] is False, (
        "只核最近那一签之后汇总位仍然是 True ⇒ ② 的判据没有对象（它本来就是真的）")


def test_negative_control_a_number_bits_declaration_turns_the_type_reading_red(
        monkeypatch) -> None:
    """反真空（③ L9）：把声明还原成 `bits: number` ⇒ ③ 的读数必须红。

    注入点：`readers.type_decls()` 返回改前那一份（`bits` 声明成 number）。正控用的
    `_bits_decl_problems` 在这里必须非空 —— 否则"生成物与声明逐字节相同"那几条
    对着的就不是"bits 是不是对象"。
    """
    decl = RD.type_decls()
    bad = decl.replace("bits: Record<string, unknown>;", "bits: number;", 1)
    assert bad != decl, "声明原文里找不到 bits 那一格 ⇒ 这一条负控没有对象"
    assert _bits_decl_problems(decl) == [], "夹具前提：注入之前 ③ 的读数应当是绿的"

    monkeypatch.setattr(RD, "type_decls", lambda: bad, raising=True)
    problems = _bits_decl_problems(RD.type_decls())
    assert problems != [], "bits 声明回 number 之后 ③ 仍然全绿 ⇒ 那条判据没有对象"
    assert any("number" in p for p in problems), problems
