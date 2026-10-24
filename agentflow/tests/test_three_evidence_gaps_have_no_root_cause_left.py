# -*- coding: utf-8 -*-
"""三个证据层缺口的根因判据（代码侧）：依赖面、验证台账的真身、多证明的依赖面。

真机 sylow3（run 已结束，只读）上的三条现场读数：

1. `data/dependencies.json` 0 行 —— 依赖面从来没有建起来；
2. `verifications/*.jsonl` 有 7 份台账、14 行签，而按数据表那一面看是 0 行（同名表不存在）
   —— 两处口径没有被任何一格对起来过；
3. 三条路仍是三条独立命题（`proof_no` 全 1、`path_group` 只有一组）—— 多证明的依赖面
   从来没有按证明号分开过。

## 判据与各自的改前红

| 判据 | 它钉住的事 | 改前红在哪 |
|---|---|---|
| a | 命题带证明正文而零依赖 ⇒ 结果里有 `deps_missing`（三态） | 改前返回值里没有这个键（KeyError），0 行是静默的 |
| b | 验证台账一处真身：文件是正本、同名表不存在（`rows=None` 不是 0）、派生副本分家能被抓；读数面读得到"已签 N 份" | 改前没有 `verifications.ledger_reading`（AttributeError），收工门读数里也没有这一格 |
| c | 一条命题交 3 份证明 ⇒ `proof_no=1..3`、三条 `path_group`、三份各签；后补的第 4 份也落 `#p4` | 改前只有 #p1 的正文进引用扫描 ⇒ 依赖表只有一条 `used_by="stmt:<号>"`、`path_group=1`，`#p2` 起的依赖面一条都没有 |
| d | 反真空：把 a 的护栏打桩成空 ⇒ a 必红；把 b 的"两面一致"打桩成恒相等 ⇒ b 必红 | 判据若没接在这两根线上，打桩不会让它变 |
| e | 用 sylow3 的三条命题做只读夹具复算：① 与 ③ 的读数在改后各自怎么出现 | 无（它是 a/b/c 的真机读数面） |

e 只读 `projects/sylow3`（工作区已结束）：不写、不删、不改它的任何字节，
读不到就 skip（"没查成"不是"没有缺口"）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

#: 真机夹具（只读）。用例在这一棵树不存在时 skip，不去凭空造一份"像 sylow3"的东西。
SYLOW3 = pathlib.Path(__file__).resolve().parents[1] / "projects" / "sylow3"

_OK = {"verdict": "成立", "findings": []}


# ---------------------------------------------------------------- 小工具

def _ws(tmp_path: pathlib.Path, name: str = "ws") -> Store:
    st = Store(tmp_path / name)
    st.init()
    return st


def _agent(store: Store) -> AgentB:
    """B 的真实现（零模型调用：这条路只碰秘书与 store）。"""
    return AgentB(store, extractor=None, extract_text=None, config={})


def own(full: str, **kw) -> dict:
    """自产命题的两件式载荷（B 只交"定理内容 + 证明过程"）。"""
    payload = {
        "statement_full": full,
        "statement_text": full[:20],
        "origin": "own_result",
        # 自产、无出处、quote_verified 不是 True ⇒ 按硬规则从"猜想"进门
        # （升档由证据位现算，不在这里硬写 theorem）。
        "kind": "conjecture",
        "doc_id": S.format_id(0),
        "quote_reason": "我方自产命题，没有外部引文要比对",
    }
    payload.update(kw)
    return payload


def _row(store: Store, stmt_id: str) -> dict:
    return next(dict(r) for r in store.rows("statements")
                if str(r.get("stmt_id") or "") == str(stmt_id))


def _deps_of(store: Store, stmt_id: str) -> list[dict]:
    """这一条命题的依赖行（按 `used_by` 的前缀认，`#pN` 尾巴也算同一条命题）。"""
    head = f"stmt:{stmt_id}"
    return [dict(d) for d in store.rows("dependencies")
            if str(d.get("used_by") or "") == head
            or str(d.get("used_by") or "").startswith(head + "#")]


def _sign(store: Store, *, stmt_id: str, proof_text: str, proof_no: int) -> dict:
    """V 的签名写入口（`verify.verify_proof` 走的就是它；这里不经模型）。"""
    return VR.record_verification(
        store.root, statement_id=str(stmt_id), proof_text=proof_text,
        verdict=dict(_OK), verifier="agent-V", store=store, proof_no=int(proof_no))


def _plant_mirror(store: Store, rows: list[dict]) -> pathlib.Path:
    """在盘上造一个派生副本 `data/verifications.json`（真实工作区里没有这一份）。"""
    path = store.data / f"{VR.VERIFICATIONS_DIR}.json"
    path.write_text(json.dumps({"schema_version": 1, "rows": rows}, ensure_ascii=False),
                    encoding="utf-8")
    return path


# ============================================================ 判据 a：deps_missing
#: a 的判据体（供判据 d 的反真空复用同一套断言）。
def _a_holds(out: dict) -> bool:
    """这一笔的读数里，"带证明正文而零依赖"这件事被说出来了没有。"""
    got = out.get("deps_missing") or {}
    return (got.get("state") == SEC.DEPS_MISSING_ABSENT
            and int(out.get("deps_written") or 0) == 0
            and int(got.get("proof_chars") or 0) > 0
            and bool(str(got.get("why") or "").strip())
            and bool(str(got.get("next_step") or "").strip()))


def test_a_a_proof_without_any_dependency_line_is_named_not_silent(tmp_path):
    """判据 a：带证明正文而依赖 0 行 ⇒ 结果里出现 `deps_missing`（三态，逐档分开）。

    真机读数（sylow3）：七条命题各带 2700 到 6300 字证明，`dependencies` 全表 0 行，
    而返回值里只有 `deps_written=0` —— 没有任何一格因为这件事变红。

    这里三档一起钉：
    - 自足证明（扫了、确实是空）⇒ `state=missing`；
    - 依赖信息在 `derived_from` 上而无依赖行 ⇒ 同一档，但 `derived_from` 原样交回；
    - 真落了依赖 ⇒ `state=present`；
    - 没有证明正文（概念行）⇒ `state=not_applicable`（三档不许折平）。
    """
    st = _ws(tmp_path, "a")
    b = _agent(st)

    lone = b.register_statement(**own("孤命题：证明里一条在册引用都没有。"),
                                proof_text="证明：由定义与假设直接计算，不引用任何在册命题。")
    assert lone.get("ok") is True, lone
    assert _a_holds(lone), lone
    got = dict(lone["deps_missing"])
    assert got["derived_from"] == [], got
    # "扫了、确实是空"与"没扫"必须分开：扫描的三态还在（`none_in_proof`）。
    assert lone.get("deps_state") == "none_in_proof", lone

    # 依赖信息其实在盘上的另一处（命题行的 `derived_from`）⇒ 这一档要点名它去了哪儿
    ctx = b.register_statement(**own("上下文引理 C：用来被引用的那一条。"),
                               proof_text="证明：略。")
    assert ctx.get("ok") is True, ctx
    cid = str(ctx["stmt_id"])
    with_ctx = b.register_statement(
        **own("命题 D：证明里点名了上下文引理 C，而正文没有任何带前缀的引用。"),
        proof_text="证明：由上述上下文引理直接推出（正文里没有写 stmt: 前缀）。",
        derived_from=[cid])
    assert with_ctx.get("ok") is True, with_ctx
    missed = dict(with_ctx["deps_missing"])
    assert missed["state"] == SEC.DEPS_MISSING_ABSENT, with_ctx
    assert missed["derived_from"] == [cid], missed
    assert "derived_from" in missed["why"], missed

    # 正控：真引用了在册的号 ⇒ 依赖落成，`state=present`（护栏不是"凡带证明就报缺"）
    cited = b.register_statement(
        **own("命题 E：证明里引用了上下文引理 C。"),
        proof_text=f"证明：由 stmt:{cid} 直接推出。")
    assert cited.get("ok") is True, cited
    assert (cited["deps_missing"] or {}).get("state") == SEC.DEPS_MISSING_PRESENT, cited
    assert int(cited.get("deps_written") or 0) >= 1, cited

    # 三态不许折平：还没有证明正文的那一笔 ⇒ 不适用（不是"缺依赖"，也不是"零依赖"）
    pending = b.register_statement(**own("命题 F：证明还没写。"))
    assert pending.get("ok") is True, pending
    missing_state = (pending.get("deps_missing") or {})
    assert missing_state.get("state") == SEC.DEPS_MISSING_NOT_APPLICABLE, pending
    assert missing_state.get("proof_chars") == 0, pending
    states = {(lone["deps_missing"])["state"], (pending["deps_missing"])["state"],
              (cited["deps_missing"])["state"]}
    assert len(states) == 3, f"三档被折平了：{sorted(states)}"


# ============================================================ 判据 b：一处真身
def _b_holds(root: pathlib.Path, store: Store) -> bool:
    """b 的判据体：文件是正本、同名表不存在、派生副本分家能被抓。"""
    reading = VR.ledger_reading(root, store=store)
    mirror = dict(reading.get("mirror") or {})
    table = dict(reading.get("table") or {})
    return bool(
        reading.get("source") == f"{VR.VERIFICATIONS_DIR}/*.jsonl"
        and int(reading.get("files") or 0) >= 1
        and int(reading.get("rows") or 0) >= 1
        and table.get("is_store_table") is False
        # "这张表不存在"不许折成"表是空的"
        and table.get("rows") is None
        and mirror.get("present") is True
        and mirror.get("agrees") is False
        and bool(reading.get("problems")))


def test_b_the_ledger_has_one_body_and_the_readout_can_say_signed(tmp_path):
    """判据 b：验证台账只有一处真身（文件），且读数面读得到"已签 N 份"。

    真机现场：`verifications/` 七份、十四行签，而按数据表那一面看是 0 行
    （`data/verifications.json` 不存在，`store.rows("verifications")` 直接抛未知表）。
    改前没有任何一格把这两面对起来过 —— 于是"表 0 行"被当成"没有签"。
    """
    st = _ws(tmp_path, "b")
    b = _agent(st)
    out = b.register_statement(**own("命题 B1：被签三次的那一条。"),
                               proof_text="证明：由定义直接得到。")
    assert out.get("ok") is True, out
    sid = str(out["stmt_id"])
    for no in (1, 2, 3):
        _sign(st, stmt_id=sid, proof_text=VR.proof_text_of(_row(st, sid), no) if no > 1
              else "证明：由定义直接得到。", proof_no=no)

    reading = VR.ledger_reading(st.root, store=st)
    assert reading["checked"] is True, reading
    assert reading["files"] == 1 and reading["file_names"] == [f"{sid}.jsonl"], reading
    assert reading["rows"] >= 3, reading
    assert reading["signed"] >= 3, reading
    assert reading["signed_statements"] == [sid], reading
    # 表面那一格：这张表从来不存在（不是 0 行）
    assert reading["table"]["is_store_table"] is False, reading["table"]
    assert reading["table"]["rows"] is None, reading["table"]
    assert "不是一张 store 表" in reading["table"]["why"], reading["table"]
    # 没有派生副本 ⇒ 对账这一档是"没查"（None），不是"对上了"（True）
    assert reading["mirror"]["present"] is False, reading["mirror"]
    assert reading["agrees"] is None, reading

    # 派生副本与文件分家（文件 3 行、表 0 行）⇒ 必须被抓出来
    _plant_mirror(st, [])
    assert _b_holds(st.root, st), VR.ledger_reading(st.root, store=st)
    split = VR.ledger_reading(st.root, store=st)
    assert split["mirror"]["count"] == 0, split["mirror"]
    assert split["problems"], split
    assert any("分家" in p for p in split["problems"]), split["problems"]

    # 读数面（收工门）也要读得到"已签 N 份"，且分家要有一条可见的指认
    from agentflow import closing as C
    rep = C.check_closing(st, project_dir=str(st.root), report_path="")
    ledger_cell = dict(rep.readings.get("verification_ledger") or {})
    assert ledger_cell, sorted(rep.readings)
    assert int(ledger_cell.get("signed") or 0) >= 3, ledger_cell
    assert ledger_cell.get("agrees") is False, ledger_cell
    codes = [getattr(f, "code", "") for f in rep.findings]
    assert "verification_ledger_split" in codes, codes

    # 副本与文件逐条一致 ⇒ 对上了（正控：反真空不许靠"永远 False"成立）
    mirror_rows, _bad = VR.list_verifications(st.root, limit=None)
    _plant_mirror(st, [dict(r) for r in mirror_rows])
    ok = VR.ledger_reading(st.root, store=st)
    assert ok["agrees"] is True, ok["mirror"]
    assert not any("分家" in p for p in ok["problems"]), ok["problems"]


# ============================================================ 判据 c：三份证明
def _c_holds(store: Store, sid: str) -> bool:
    """c 的判据体：3 份证明 ⇒ 三个证明号、三条路径组、三份各签。"""
    row = _row(store, sid)
    nos = [int(no) for no, _text in VR.proof_list(row)]
    deps = _deps_of(store, sid)
    used_by = sorted({str(d.get("used_by") or "") for d in deps})
    groups = sorted({int(d.get("path_group") or 0) for d in deps})
    reviewed = EB.reviewed_by_proof(row)
    return bool(
        nos == [1, 2, 3]
        and used_by == [f"stmt:{sid}", f"stmt:{sid}#p2", f"stmt:{sid}#p3"]
        and groups == [1, 2, 3]
        and reviewed == {1: True, 2: True, 3: True})


def test_c_one_proposition_three_proofs_lands_three_dependency_surfaces(tmp_path):
    """判据 c：一条命题交 3 份证明 ⇒ `proof_no=1..3`＋三条 `path_group`＋三份各签。

    改前红（真机 sylow3 的同一形态，2026-10-24 探针）：三份证明交上去之后
    `proof_list` 是 [1,2,3]，而依赖表只有一条 `used_by="stmt:<号>"`（`path_group=1`）——
    `#p2`、`#p3` 的正文根本没进引用扫描，于是"这一份证明用到什么"在依赖面上不存在。
    """
    st = _ws(tmp_path, "c")
    b = _agent(st)
    x = b.register_statement(**own("引理 X：任意有限群 G 有 Sylow p-子群。"),
                             proof_text="证明：由轨道计数得。")
    y = b.register_statement(**own("引理 Y：p-群作用的轨道长是 p 的幂。"),
                             proof_text="证明：由群作用公理得。")
    assert x.get("ok") and y.get("ok"), (x, y)
    xid, yid = str(x["stmt_id"]), str(y["stmt_id"])

    p1 = f"路线一：由 stmt:{xid} 直接推出。"
    p2 = f"路线二：由 stmt:{yid} 与双陪集计数推出。"
    p3 = f"路线三：由 stmt:{xid} 与 stmt:{yid} 一起推出。"
    out = b.register_statement(
        **own("主命题 P：同一条 Sylow 定理的三条独立证法。"),
        proofs=[{"proof_no": 1, "text": p1}, {"proof_no": 2, "text": p2},
                {"proof_no": 3, "text": p3}])
    assert out.get("ok") is True, out
    pid = str(out["stmt_id"])
    # 号与正文：三个号、#p1 在 canonical 那一格、其余在清单里
    assert [int(no) for no, _t in VR.proof_list(_row(st, pid))] == [1, 2, 3], out
    assert VR.proof_text_of(_row(st, pid), 1) == p1
    assert VR.proof_text_of(_row(st, pid), 3) == p3

    # 依赖面：每份证明一条独立的 `used_by` 与一条独立的路径组
    deps = _deps_of(st, pid)
    assert deps, "三份证明一条依赖都没落 ⇒ #p2/#p3 的引用面不存在"
    by_used = {str(d.get("used_by")): d for d in deps}
    assert set(by_used) == {f"stmt:{pid}", f"stmt:{pid}#p2", f"stmt:{pid}#p3"}, sorted(by_used)
    assert int(by_used[f"stmt:{pid}"]["path_group"]) == 1
    assert int(by_used[f"stmt:{pid}#p2"]["path_group"]) == 2
    # #p3 引了两条在册命题 ⇒ 同一组里两行（组内 AND）
    assert int(by_used[f"stmt:{pid}#p3"]["path_group"]) == 3
    p3_rows = [d for d in deps if str(d.get("used_by")) == f"stmt:{pid}#p3"]
    assert {str(d.get("source_stmt_id")) for d in p3_rows} == {xid, yid}, p3_rows

    # 三份各签：第 3 位逐条证明分开，任一份成立不借光给别的
    for no, text in ((1, p1), (2, p2), (3, p3)):
        signed = _sign(st, stmt_id=pid, proof_text=text, proof_no=no)
        assert signed.get("proof_no") == no, signed
    assert EB.reviewed_by_proof(_row(st, pid)) == {1: True, 2: True, 3: True}, \
        _row(st, pid)["bits"]
    assert _c_holds(st, pid), (VR.proof_list(_row(st, pid)), _deps_of(st, pid))

    # 后补的第 4 份证明：挂上清单的同时也要落成 `#p4` 那一面（不许静默丢）
    p4 = f"路线四：由 stmt:{yid} 的反向计数推出。"
    more = b.register_statement(
        **own("主命题 P：同一条 Sylow 定理的三条独立证法。"),
        proofs=[{"proof_no": 1, "text": p1}, {"proof_no": 4, "text": p4}])
    assert more.get("ok") is True, more
    assert [int(no) for no, _t in VR.proof_list(_row(st, pid))] == [1, 2, 3, 4], more
    got = dict(more.get("proof_deps") or {})
    assert int(got.get("deps_written") or 0) >= 1, more
    assert got.get("proof_nos") == [4], got
    p4_used = {str(d.get("used_by")) for d in _deps_of(st, pid)}
    assert f"stmt:{pid}#p4" in p4_used, p4_used


# ============================================================ 判据 d：反真空
def test_d_anti_vacuum_both_guards_are_load_bearing(tmp_path, monkeypatch):
    """判据 d：把 a 的护栏打桩成空 ⇒ a 必红；把 b 的"两面一致"打桩成恒相等 ⇒ b 必红。

    两半都要先证明"正控是绿的"，再打桩；否则这一条测的是桩本身。
    """
    # ---- 正控（a）：真护栏下，孤命题这一笔是"说出来了"的
    st_a = _ws(tmp_path, "da")
    lone = _agent(st_a).register_statement(
        **own("孤命题：证明里一条在册引用都没有。"),
        proof_text="证明：由定义与假设直接计算，不引用任何在册命题。")
    assert _a_holds(lone), lone

    # 打桩：把读数函数换成空字典（= 改前那一格根本不存在）
    monkeypatch.setattr(SEC, "_deps_missing_reading", lambda **kw: {})
    st_a2 = _ws(tmp_path, "da2")
    stubbed = _agent(st_a2).register_statement(
        **own("孤命题：证明里一条在册引用都没有。"),
        proof_text="证明：由定义与假设直接计算，不引用任何在册命题。")
    assert not _a_holds(stubbed), (
        "把 `deps_missing` 的读数打桩成空之后判据 a 还是绿的 ⇒ a 没接在那根线上")

    # ---- 正控（b）：真口径下，文件 3 行 vs 派生副本 0 行是"分家"
    st_b = _ws(tmp_path, "db")
    b = _agent(st_b)
    out = b.register_statement(**own("命题 D1：被签两次的那一条。"),
                               proof_text="证明：由定义直接得到。")
    sid = str(out["stmt_id"])
    for no in (1, 2):
        _sign(st_b, stmt_id=sid,
              proof_text="证明：由定义直接得到。" if no == 1 else "证明：换一条路线。",
              proof_no=no)
    _plant_mirror(st_b, [])
    assert _b_holds(st_b.root, st_b), VR.ledger_reading(st_b.root, store=st_b)

    # 打桩：把派生副本那一面读成"与文件逐条相同"（恒相等）⇒ 分家抓不到了
    real_rows, _bad = VR.list_verifications(st_b.root, limit=None)

    def _always_same(root_p):
        return [dict(r) for r in real_rows], True

    monkeypatch.setattr(VR, "_ledger_mirror_rows", _always_same)
    assert not _b_holds(st_b.root, st_b), (
        "把两面一致判定打桩成恒相等之后判据 b 还是绿的 ⇒ b 没接在那根线上")


# ============================================================ 判据 e：sylow3 只读复算
def _sylow3_statements() -> list[dict]:
    path = SYLOW3 / "data" / "statements.json"
    if not path.is_file():
        pytest.skip(f"没有真机夹具（{path} 不在盘上）—— 这一条只读它，不造替身")
    return [dict(r) for r in json.loads(path.read_text(encoding="utf-8")).get("rows") or []]


def test_e_sylow3_recompute_says_which_gap_would_still_show(tmp_path):
    """判据 e：用 sylow3 的三条命题做只读夹具，复算"改后这三条缺口各读成什么"。

    只读：`projects/sylow3` 一个字节都不写（临时工作区在 `tmp_path` 下）。
    三条读数各自贴进断言消息里，失败时能直接看到现场。
    """
    rows = {str(r.get("stmt_id") or ""): r for r in _sylow3_statements()}
    if not {"000000", "000003", "000006"} <= set(rows):
        pytest.skip("真机夹具的命题号不是 000000 / 000003 / 000006 —— 这一条不对旧夹具判")

    # ---- 缺口二：这一趟到底"签了几份"（改前：文件 7 份、按表看是 0 行）
    ledger = VR.ledger_reading(SYLOW3)
    assert ledger["files"] == 7, ledger
    assert ledger["signed"] == 7, ledger
    assert ledger["table"]["is_store_table"] is False, ledger["table"]
    assert ledger["table"]["rows"] is None, ledger["table"]
    assert ledger["mirror"]["present"] is False, ledger["mirror"]
    assert ledger["agrees"] is None, ledger
    # 缺口二改后不会"消失"，但它变成一个能被读到的数（而不是一页空白）
    assert f"{VR.VERIFICATIONS_DIR}/*.jsonl" == ledger["source"], ledger
    assert ledger["rows"] >= 14, ledger

    # ---- 缺口一：把 000000 那一笔原样（定理内容 + 证明过程）重放一遍
    st = _ws(tmp_path, "e1")
    b = _agent(st)
    src = rows["000000"]
    replayed = b.register_statement(
        **own(str(src.get("statement_full") or ""),
              label=str(src.get("label") or "")[:80]),
        proof_text=str(src.get("proof_text") or ""))
    assert replayed.get("ok") is True, replayed
    assert (replayed.get("deps_missing") or {}).get("state") == SEC.DEPS_MISSING_ABSENT, \
        replayed.get("deps_missing")
    # 改前的现场就是这两格：依赖 0 行、扫描说"扫了、确实是空"
    assert int(replayed.get("deps_written") or 0) == 0, replayed
    assert replayed.get("deps_state") == "none_in_proof", replayed

    # ---- 缺口三：把三条路当成同一条命题的三份证明再交一次
    st3 = _ws(tmp_path, "e3")
    b3 = _agent(st3)
    texts = [str(rows[no].get("proof_text") or "") for no in ("000000", "000003", "000006")]
    assert all(t.strip() for t in texts), "真机夹具的三份证明正文读不全"
    merged = b3.register_statement(
        **own("Sylow 三定理：正规化子路线 / Wielandt 路线 / 归纳 S3 路线，三条独立证法。"),
        proofs=[{"proof_no": i, "text": t} for i, t in enumerate(texts, 1)])
    assert merged.get("ok") is True, merged
    mid = str(merged["stmt_id"])
    assert [int(no) for no, _t in VR.proof_list(_row(st3, mid))] == [1, 2, 3], merged
    for i, text in enumerate(texts, 1):
        signed = _sign(st3, stmt_id=mid, proof_text=text, proof_no=i)
        assert signed.get("proof_no") == i, signed
    assert EB.reviewed_by_proof(_row(st3, mid)) == {1: True, 2: True, 3: True}, \
        _row(st3, mid)["bits"]
    # 这三份真机证明正文都是中文散文（没有 stmt: 前缀）⇒ 依赖面仍然 0 行，
    # 但改后它有话说了：`deps_missing` 点名"扫了、确实是空"，不再是一页空白。
    assert (merged.get("deps_missing") or {}).get("state") == SEC.DEPS_MISSING_ABSENT, \
        merged.get("deps_missing")
    assert int(merged.get("deps_written") or 0) == 0, merged
    # 一条命题三份证明这条机制本身是通的（缺口三的代码侧不再是"落不成"）
    assert _row(st3, mid)["proof_text"] == texts[0], "canonical 那一格应当是 #p1"
    assert VR.proof_text_of(_row(st3, mid), 3) == texts[2]

    # 只读：真机工作区一个字没动（依赖表仍然是历史上那 0 行）
    assert len(list(Store(SYLOW3).rows("dependencies"))) == 0
