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
| a | 命题带证明正文而依赖面没建起来 ⇒ 结果里有 `deps_missing`（三档：`missing` / `not_applicable` / `present`，外加两条受控拒） | 改前返回值里没有这个键（KeyError），0 行是静默的 |
| b | 验证台账一处真身：文件是正本、同名表不存在（`rows=None` 不是 0）、派生副本分家能被抓；读数面读得到"已签 N 份" | 改前没有 `verifications.ledger_reading`（AttributeError），收工门读数里也没有这一格 |
| c | 一条命题交 3 份证明 ⇒ `proof_no=1..3`、三条 `path_group`、三份各签；后补的第 4 份也落 `#p4` | 改前只有 #p1 的正文进引用扫描 ⇒ 依赖表只有一条 `used_by="stmt:<号>"`、`path_group=1`，`#p2` 起的依赖面一条都没有 |
| d | 反真空：把 a 的护栏打桩成空 ⇒ a 必红；把 b 的"两面一致"打桩成恒相等 ⇒ b 必红 | 判据若没接在这两根线上，打桩不会让它变 |
| e | 用 sylow3 的三条命题做只读夹具复算：① 与 ③ 的读数在改后各自怎么出现 | 无（它是 a/b/c 的真机读数面） |

## 2026-11-04（业主裁定：`missing` 钉在只读预览层，不退役）

`missing`（作者没写依赖段）与 `not_applicable`（这份证明本来就自足）是两件事。
B 那一侧对"正文引了在册命题、而稿里没有 `## 依赖` 段"整笔拒
`dependency_section_missing`（没有那一段就没有依赖边可落）—— 那是对的；但读数层
不该跟着把这一档删掉，否则再也说不清"这份稿为什么进不来"。所以判据 a 的 `missing`
读的是只读预览层（`depsection.deps_missing_reading` 的直调，该函数 docstring 写明
这一档"留给只读预览与别的调用方"），`_a_holds` 原样套在它返回的 dict 上；
B 那一侧同一形态另有一条独立的拒收判据。三档一档不少，每档带反真空。

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

from agentflow import depsection as DS
from agentflow import evidencebits as EB
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

from conftest import seed_statement_row

#: 真机夹具（只读）。用例在这一棵树不存在时 skip，不去凭空造一份"像 sylow3"的东西。
SYLOW3 = pathlib.Path(__file__).resolve().parents[1] / "projects" / "sylow3"

_OK = {"verdict": "成立", "findings": []}


def _proof_manuscript(rows) -> str:
    """F 的证明手稿（`## 依赖` 四列表）：2026-10-26 起 B 登记引用在册命题的证明时要拿到它。

    业主当天的口径（逐字）：「依赖面登记是否是F在其手稿中写好，D的研究手稿引用F的证明
    手稿给B入库时，B侧读到F手稿处的依赖面，按此入库的？」→「是通过D传吗」。
    于是"正文引了在册命题、却没有任何一份手稿"这一档改成整笔拒收
    `dependency_section_missing`（不许静默地靠正文扫描落依赖）。下面两条用例原本正是
    那一档写法，现在把 F 那份稿按同一格式递进来 —— 它们断言的东西（依赖落成 / 三份
    证明三面）一个字都不改。

    `rows` 是 `[(命题号, F 的原话, 路径号)]`。
    """
    lines = ["## 证明", ""]
    for sid, _quote, _group in rows:
        lines.append(f"1. 由 stmt:{sid} 直接推出。")
    lines += ["", "## 依赖", "",
              "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |",
              "|---|---|---|---|"]
    for sid, quote, group in rows:
        lines.append(f"| {quote} | stmt:{sid} | 第 1 步 | {int(group)} |")
    return "\n".join(lines) + "\n"


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


def _seed(store: Store, *, full: str, proof_text: str,
          proofs: tuple = ()) -> dict:
    """造一条在册命题（历史形态：直接铺行）。

    2026-11-02 准入闸 strict 之后，无签的证明正文经 `register_statement` 写不进去
    （`proof_without_v_sign`）；新建命题时无签的 `#p2` 及以后更没有号可挂签。
    这一组 b/c 要的是"盘上有一条带 N 份证明的行"，现场因此按真机行同形铺行
    （`bits` 由 `bits_of` 现算、证明清单带 `created_at`）。判据一个字都没改。
    """
    payload = own(full)
    numbers = [1] + [int(p.get("proof_no") or 0) for p in proofs]
    seeded = seed_statement_row(
        store, proof_text=proof_text,
        statement_full=str(payload["statement_full"]),
        statement_text=str(payload["statement_text"]), kind="conjecture",
        label=str(payload["statement_text"]), origin="own_result",
        doc_id=S.format_id(0), quote_reason=str(payload["quote_reason"]),
        proofs=[{**dict(p), "created_at": S.now_iso()} for p in proofs],
        bits=EB.with_optimized_defaults(
            EB.bits_of(origin="own_result", proof=True, proof_process=proof_text,
                       kind="conjecture"), numbers))
    return {"ok": True, "stmt_id": str(seeded["stmt_id"]), "new_row": True}


def _promote_to_proof_review(store: Store, stmt_id: str, proof_text: str) -> None:
    """把一条在册命题抬到 `proof_review`（先落 V 的签，再改档位 —— 顺序不许反）。

    为什么这两条用例需要它：手稿的依赖段有一条引用门槛（业主 2026-10-24，逐字
    「proof_review级及以上才可引用」）。改前这两条用例走的是"正文扫描"的老路，不经过
    那道门；现在它们按新口径交稿，被引命题就必须真的够格 —— 否则红的是档位门，
    而这两条用例要证明的不是档位门。

    2026-10-29 口径：`proof_review` 那一档的准入是"同一份正文连续 `SIGN_STREAK_NEED`
    次「成立」"（第 1、2 次只落台账、不翻位）⇒ 这里连签够次数再改档位。
    """
    need = int(VR.SIGN_STREAK_NEED)
    for i in range(1, need + 1):
        signed = VR.record_verification(
            store.root, statement_id=stmt_id, proof_text=proof_text, verdict=_OK,
            verifier="agent-V", store=store, proof_no=1, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
        assert signed.get("checked") is True, signed
        wrote = bool((signed.get("statement_writeback") or {}).get("written"))
        assert wrote is (i == need), (
            f"第 {i} 次「成立」的翻位读数是 written={wrote!r} —— 2026-10-29 口径："
            f"连续 {need} 次才发签（第 1、2 次只落台账）", signed)
    row = _row(store, stmt_id)
    row["evidence_kind"] = "proof_review"
    with store.tx("statements", actor="test", note="fixture:evidence_kind") as tx:
        tx.upsert("statements", row)


def _deps_of(store: Store, stmt_id: str) -> list[dict]:
    """这一条命题的依赖行（按 `used_by` 的前缀认，`#pN` 尾巴也算同一条命题）。"""
    head = f"stmt:{stmt_id}"
    return [dict(d) for d in store.rows("dependencies")
            if str(d.get("used_by") or "") == head
            or str(d.get("used_by") or "").startswith(head + "#")]


def _sign(store: Store, *, stmt_id: str, proof_text: str, proof_no: int) -> dict:
    """V 的签名写入口（`verify.verify_proof` 走的就是它；这里不经模型）。

    2026-10-29 口径：同一份正文连续 `SIGN_STREAK_NEED` 次「成立」且秘书判定通过才发签
    （第 1、2 次只落台账）⇒ 夹具连签够次数、返回签发的那一签；这条正控在下面钉住。
    """
    need = int(VR.SIGN_STREAK_NEED)
    signed: dict = {}
    for i in range(1, need + 1):
        signed = VR.record_verification(
            store.root, statement_id=str(stmt_id), proof_text=proof_text,
            verdict=dict(_OK), verifier="agent-V", store=store, proof_no=int(proof_no), secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
        wrote = bool((signed.get("statement_writeback") or {}).get("written"))
        assert wrote is (i == need), (
            f"第 {i} 次「成立」的翻位读数是 written={wrote!r} —— 2026-10-29 口径："
            f"连续 {need} 次才发签（第 1、2 次只落台账）", signed)
    return signed


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


#: 手稿正文（夹具）：三节里只有「命题」「证明」，没有 `## 依赖` 那一节。
#: 这是"作者没写依赖段"的形状本身 —— B 对它是整笔拒（`dependency_section_missing`），
#: 而读数层必须能把这件事说出来（`missing`）。
def _manuscript_missing_dependency_section(body: str) -> str:
    return ("# F 的证明手稿（夹具）\n\n- 命题号：stmt:（待登记）\n\n"
            "## 命题\n\n（夹具命题）\n\n"
            f"## 证明\n\n{body}\n\n")


#: 手稿正文（夹具）：`## 依赖` 是空表（表头在、0 行）—— 这是合法的"自足"声明。
def _manuscript_empty_dependency_table(body: str) -> str:
    return ("# F 的证明手稿（夹具）\n\n- 命题号：stmt:（待登记）\n\n"
            "## 命题\n\n（夹具命题）\n\n"
            f"## 证明\n\n{body}\n\n"
            "## 依赖\n\n"
            "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
            "|---|---|---|---|\n\n"
            "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")


def _read_only_deps_reading(body: str, *, manuscript: str = "",
                            deps_written: int = 0) -> dict:
    """只读预览层的依赖面读数（`depsection.deps_missing_reading` 的直调）。

    2026-11-04（业主裁定：`missing` 钉在只读预览层，不退役）：
    B 那一侧对"正文引了在册命题、而稿里没有 `## 依赖` 段"整笔拒
    `dependency_section_missing` —— 那一侧必须拒（没有依赖段就没有依赖边可落）。
    但读数层不该跟着把这一档删掉：删了就再也说不清"这份稿为什么进不来"。
    该函数自己的 docstring 写的正是"这一档读数留给只读预览与别的调用方"，
    所以这一档在这里读（`section` 就是那份稿的 `## 依赖` 段 `parse_dependency_section`
    的原始形状；`deps_written` 由调用方给 —— 预览时是 0）。
    """
    text = manuscript or _manuscript_missing_dependency_section(body)
    section = DS.parse_dependency_section(text)
    refs = DS.stmt_refs(body)
    return DS.deps_missing_reading(
        proof_text=body, deps_written=int(deps_written), derived_from=refs,
        refs=len(refs), section=section)



@pytest.mark.usefixtures("signed_v_handoffs")
def test_a_a_proof_without_any_dependency_line_is_named_not_silent(tmp_path):
    """判据 a：带证明正文而依赖面没建起来 ⇒ 读数要按三档说出来，拒绝也要被解释。

    真机读数（sylow3）：七条命题各带 2700 到 6300 字证明，`dependencies` 全表 0 行，
    而返回值里只有 `deps_written=0` —— 没有任何一格因为这件事变红。

    2026-11-04（业主裁定：`missing` 钉在只读预览层，不退役；B 那一侧照旧整笔拒）。
    三档 + 一条拒 + 一条不拒，逐档钉，每档旁边带反真空（把形态换一格，读数必须换）：
    - `missing`：正文引了在册命题，而稿里没有 `## 依赖` 段（"作者没写依赖段"）——
      在只读预览层读（`_read_only_deps_reading`）；`_a_holds` 原样套在那份 dict 上；
    - `missing`（第二形态）：同一段正文 + 稿里是一张空表（说辞与表打架）——预览层
      同样读 `missing`，`derived_from` 点名被引的那一条；
    - `not_applicable`：稿的 `## 依赖` 是空表 + 正文零引用（自足，不是"缺依赖"）；
    - `present`：正文引了、稿里也登记了 ⇒ 依赖落成；
    - 拒 ①：missing 的同一形态交 B ⇒ `dependency_section_missing`（零写入）；
    - 拒 ②（2026-11-06 业主口径的纠正）：稿的表点名一条不在册的号 ⇒ 整笔受控拒
      `dependency_source_not_registered`、点名那个号（「F 读不到它」）——
      它不是待接的悬空边，而是这一笔写错了。
    """
    st = _ws(tmp_path, "a")
    b = _agent(st)

    # ① 自足（空表 + 零引用）⇒ not_applicable；"扫了、确实是空"看 deps_state
    lone_body = "证明：由定义与假设直接计算，不引用任何在册命题。"
    lone = b.register_statement(
        **own("孤命题：证明里一条在册引用都没有。"),
        proof_text=lone_body,
        proof_manuscript=_manuscript_empty_dependency_table(lone_body))
    assert lone.get("ok") is True, lone
    lone_reading = dict(lone.get("deps_missing") or {})
    assert lone_reading.get("state") == SEC.DEPS_MISSING_NOT_APPLICABLE, lone
    assert lone_reading.get("derived_from") == [], lone_reading
    # "扫了、确实是空"与"没扫"必须分开：扫描的三态还在（`none_in_proof`）。
    assert lone.get("deps_state") == "none_in_proof", lone
    assert int(lone.get("deps_written") or 0) == 0, lone

    # 上下文引理 C（在册）
    ctx = b.register_statement(**own("上下文引理 C：用来被引用的那一条。"),
                               proof_text="证明：略。")
    assert ctx.get("ok") is True, ctx
    cid = str(ctx["stmt_id"])

    # ② 只读预览层：正文引在册 C + 稿缺 `## 依赖` 段 ⇒ missing（why / next_step 都在）
    missing_body = f"证明：由 stmt:{cid} 直接推出。"
    missing = _read_only_deps_reading(missing_body)
    assert missing.get("state") == SEC.DEPS_MISSING_ABSENT, missing
    assert _a_holds({"deps_missing": missing, "deps_written": 0}), missing
    assert int(missing.get("proof_chars") or 0) > 0, missing
    assert str(missing.get("why") or "").strip(), missing
    assert str(missing.get("next_step") or "").strip(), missing
    # 反真空：同一段正文、稿里补上一张空表（段在）且依赖真落了 ⇒ present（不是恒 missing）
    wrote = _read_only_deps_reading(
        missing_body, manuscript=_manuscript_empty_dependency_table(missing_body),
        deps_written=1)
    assert wrote.get("state") == SEC.DEPS_MISSING_PRESENT, wrote
    # 反真空：正文零引用 ⇒ 自足档（not_applicable），不是 missing
    quiet = _read_only_deps_reading("证明：由定义直接得到，不引用任何在册命题。")
    assert quiet.get("state") == SEC.DEPS_MISSING_NOT_APPLICABLE, quiet
    # 反真空：`_a_holds` 的每一格都真的被读（逐格拧掉 ⇒ 必红）
    for knob, value in (("why", ""), ("next_step", ""), ("proof_chars", 0)):
        broken = dict(missing, **{knob: value})
        assert not _a_holds({"deps_missing": broken, "deps_written": 0}), (knob, broken)
    assert not _a_holds({"deps_missing": missing, "deps_written": 1}), missing

    # ③ missing 的第二形态（说辞与表打架）：同一段正文 + 空表、预览时 deps_written=0
    #    ⇒ 同一档 missing，`derived_from` 原样交回（旧 `:254-256` 那两条断言落在这里）。
    #    注意：真交给 B 时秘书的正文扫描会把那条边写进去（deps_written=1）⇒ B 读成
    #    `present`（见 ④）—— 这正是"读数层解释拒绝、写库层不许静默"的分工。
    conflicts = _read_only_deps_reading(
        missing_body, manuscript=_manuscript_empty_dependency_table(missing_body))
    assert conflicts.get("state") == SEC.DEPS_MISSING_ABSENT, conflicts
    assert _a_holds({"deps_missing": conflicts, "deps_written": 0}), conflicts
    assert conflicts.get("derived_from") == [cid], conflicts
    assert "derived_from" in str(conflicts.get("why") or ""), conflicts
    # 反真空：同一张空表 + 正文换成零引用 ⇒ 这一档变成 not_applicable（不是 missing）
    conflicts_quiet = _read_only_deps_reading(
        "证明：由定义直接得到，不引用任何在册命题。",
        manuscript=_manuscript_empty_dependency_table(
            "证明：由定义直接得到，不引用任何在册命题。"))
    assert conflicts_quiet.get("state") == SEC.DEPS_MISSING_NOT_APPLICABLE, conflicts_quiet

    # ④ 同一形态交给 B ⇒ 整笔拒 `dependency_section_missing`（拒信要指回缺的那一节）
    before_statements = len(st.rows("statements"))
    before_deps = [dict(r) for r in st.rows("dependencies")]
    refused = b.register_statement(
        **own("命题 D：引了在册命题，而手稿里没有依赖段。"),
        proof_text=missing_body,
        proof_manuscript=_manuscript_missing_dependency_section(missing_body))
    assert refused.get("ok") is False, refused
    assert refused.get("kind") == DS.REFUSED_SECTION_MISSING, refused
    err = str(refused.get("error") or "")
    assert f"stmt:{cid}" in err and "依赖" in err, err
    assert len(st.rows("statements")) == before_statements, st.rows("statements")
    assert [dict(r) for r in st.rows("dependencies")] == before_deps
    # 反真空（拒 ↔ 收）：同一份"没有依赖段"的稿、正文换成零引用 ⇒ 照常入库
    accepted = b.register_statement(
        **own("命题 D2：稿里没有依赖段，但正文也零引用。"),
        proof_text="证明：由定义直接得到，不引用任何在册命题。",
        proof_manuscript=_manuscript_missing_dependency_section(
            "证明：由定义直接得到，不引用任何在册命题。"))
    assert accepted.get("ok") is True, accepted
    assert (accepted.get("deps_missing") or {}).get("state") == (
        SEC.DEPS_MISSING_NOT_APPLICABLE), accepted

    # ⑤ 正控：真引用了在册的号、稿里也登记 ⇒ 依赖落成，`state=present`
    _promote_to_proof_review(st, cid, "证明：略。")
    cited = b.register_statement(
        **own("命题 E：证明里引用了上下文引理 C。"),
        proof_text=f"证明：由 stmt:{cid} 直接推出。",
        # 2026-10-26：引了在册命题的证明必须交稿（参数 / D 携带 / 盘上兜底三处之一），
        # 否则整笔拒收 —— 这里按 F 的手稿格式把那一节递进来。
        proof_manuscript=_proof_manuscript([(cid, "由上下文引理 C，结论直接得到", 1)]))
    assert cited.get("ok") is True, cited
    cited_reading = dict(cited.get("deps_missing") or {})
    assert cited_reading.get("state") == SEC.DEPS_MISSING_PRESENT, cited
    assert int(cited.get("deps_written") or 0) >= 1, cited
    assert cited_reading.get("derived_from") == [cid], cited_reading

    # ⑥ 不在册的号（2026-11-06 业主口径的纠正）：稿的依赖表点名一条不在册的号
    #    ⇒ 整笔受控拒、点名那个号，而不是落 dangling 之后照写。业主逐字：
    #    「F 应该无法读到尚未在册的命题」⇒ 这种正文只可能是这一笔写错了（F 读不到它，
    #    不可能在引用它）。`dependency_source_not_registered` 因此在收方这条路上重新
    #    成为门（`53ec0477` 让"不在册 ⇒ dangling + 照写"是错的，这一处翻回来）。
    #    反真空：同一份稿里那条号换成在册且够格的 C ⇒ 落成 closed 边（见 ⑤）。
    unknown = "000098"
    before_ghost = len(st.rows("statements"))
    before_ghost_deps = [dict(r) for r in st.rows("dependencies")]
    ghost = b.register_statement(
        **own("命题 G：稿的依赖表点名了一条不在册的命题。"),
        proof_text=f"证明：由 stmt:{unknown} 直接推出。",
        proof_manuscript=_proof_manuscript([(unknown, "某条不存在的引理", 1)]))
    assert ghost.get("ok") is False, ghost
    assert ghost.get("kind") == DS.REFUSED_UNKNOWN_SOURCE, ghost
    err = str(ghost.get("error") or "")
    assert f"stmt:{unknown}" in err, err
    assert "不在册" in err and "F 读不到它" in err, err
    assert len(st.rows("statements")) == before_ghost, "受控拒：那一行不许落下去"
    assert [dict(r) for r in st.rows("dependencies")] == before_ghost_deps

    # ⑦ 还没有证明正文 ⇒ not_applicable（不是"缺依赖"，也不是"零依赖"）
    pending = b.register_statement(**own("命题 F：证明还没写。"))
    assert pending.get("ok") is True, pending
    pending_reading = dict(pending.get("deps_missing") or {})
    assert pending_reading.get("state") == SEC.DEPS_MISSING_NOT_APPLICABLE, pending
    assert pending_reading.get("proof_chars") == 0, pending

    # 三档不许折平（missing 取自只读预览层那一份 —— 同一份正文的读数）
    states = {lone_reading["state"], missing["state"], cited_reading["state"]}
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
    # 三份证明各签满门槛（2026-10-29 口径：同一份正文连续 `SIGN_STREAK_NEED` 次「成立」
    # 且秘书判定通过才发签，第 1、2 次只落台账）⇒ 这一条夹具要"签过三份"就得先有三份
    # 在册证明，再各签够次数。读数面的断言（`signed >= 3`）一个字都没放宽。
    proof_texts = ("证明：由定义直接得到。", "证明：换一条路线。", "证明：再换一条路线。")
    out = _seed(st, full="命题 B1：被签三次的那一条。", proof_text=proof_texts[0],
                proofs=tuple({"proof_no": i, "text": t}
                             for i, t in enumerate(proof_texts[1:], 2)))
    assert out.get("ok") is True, out
    sid = str(out["stmt_id"])
    for no in (1, 2, 3):
        _sign(st, stmt_id=sid, proof_text=VR.proof_text_of(_row(st, sid), no),
              proof_no=no)

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
    x = _seed(st, full="引理 X：任意有限群 G 有 Sylow p-子群。",
              proof_text="证明：由轨道计数得。")
    y = _seed(st, full="引理 Y：p-群作用的轨道长是 p 的幂。",
              proof_text="证明：由群作用公理得。")
    assert x.get("ok") and y.get("ok"), (x, y)
    xid, yid = str(x["stmt_id"]), str(y["stmt_id"])
    # 手稿依赖段的引用门槛：被引的两条都要够 `proof_review`（业主 2026-10-24 加码裁定）
    _promote_to_proof_review(st, xid, "证明：由轨道计数得。")
    _promote_to_proof_review(st, yid, "证明：由群作用公理得。")

    p1 = f"路线一：由 stmt:{xid} 直接推出。"
    p2 = f"路线二：由 stmt:{yid} 与双陪集计数推出。"
    p3 = f"路线三：由 stmt:{xid} 与 stmt:{yid} 一起推出。"
    out = _seed(st, full="主命题 P：同一条 Sylow 定理的三条独立证法。",
                proof_text=p1,
                proofs=({"proof_no": 2, "text": p2}, {"proof_no": 3, "text": p3}))
    assert out.get("ok") is True, out
    pid = str(out["stmt_id"])
    # 三份证明的依赖面仍走生产写口（秘书的 `record_proof_deps`，`_attach_proofs`
    # 补写 #p2 及以后时用的正是它）：直接铺行只替掉被准入闸拦下的登记那一笔。
    deps_written = dict(b._statement_secretary().record_proof_deps(
        pid, [{"proof_no": 1, "text": p1}, {"proof_no": 2, "text": p2},
              {"proof_no": 3, "text": p3}]))
    assert deps_written.get("checked") is True, deps_written
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

    # 三份各签：第 3 位逐条证明分开，任一份成立不借光给别的。
    # 2026-11-11（业主裁定「签跟着正文走」）：`proof_no` 在 V 签侧退役 —— canonical
    # （#p1）的新行**不写**这一格；一份证明的身份由「正文 sha + statement_id + 路径」
    # 站住（路径那一维是上面已经钉住的 `path_group` 1 / 2 / 3）。显式 `proof_no>1`
    # 是旧多证明写口的兼容（读侧按号分组），所以 #p2 / #p3 照写。下面按号各钉一次：
    # sha 错、命题串了、或把 `proof_no=1` 又写回 canonical，每一条都会红。
    for no, text in ((1, p1), (2, p2), (3, p3)):
        signed = _sign(st, stmt_id=pid, proof_text=text, proof_no=no)
        assert str(signed.get("statement_id") or "") == pid, signed
        assert str(signed.get("proof_sha256") or "") == VR.text_sha(text), signed
        assert ("proof_no" in signed) is (no > 1), signed
        assert VR.proof_no_of(signed) == no, signed
    assert EB.reviewed_by_proof(_row(st, pid)) == {1: True, 2: True, 3: True}, \
        _row(st, pid)["bits"]
    assert _c_holds(st, pid), (VR.proof_list(_row(st, pid)), _deps_of(st, pid))

    # 后补的第 4 份证明：挂上清单的同时也要落成 `#p4` 那一面（不许静默丢）。
    # 补 #pN 那一笔同样经正路不可达（无签的新正文）⇒ 清单直接铺行，依赖面仍走
    # 生产写口 `record_proof_deps`。
    p4 = f"路线四：由 stmt:{yid} 的反向计数推出。"
    row = _row(st, pid)
    row[VR.PROOFS_KEY] = [*[dict(p) for p in (row.get(VR.PROOFS_KEY) or [])],
                          {"proof_no": 4, "text": p4, "created_at": S.now_iso()}]
    row["bits"] = EB.with_optimized_flag(row.get("bits") or {}, 4, False)
    with st.tx("statements", actor="test", note="append_p4") as tx:
        tx.upsert("statements", row, note="append_p4")
    more = {"ok": True, "proof_deps": dict(
        b._statement_secretary().record_proof_deps(pid, [{"proof_no": 4, "text": p4}]))}
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
    # ---- 正控（a）：真读数下，`missing` 那一档是"说出来了"的
    #
    # 2026-11-04（业主裁定：`missing` 钉在只读预览层）：这一档的形态是"正文引了在册
    # 命题、而稿里没有 `## 依赖` 段"。B 那一侧同一形态整笔拒（见判据 a 的 ④），
    # 所以正控读的是只读预览层那一份 dict —— 判据函数 `_a_holds` 原样套上去。
    miss_body = "证明：由 stmt:000098 直接推出。"
    missing = _read_only_deps_reading(miss_body)
    assert _a_holds({"deps_missing": missing, "deps_written": 0}), missing

    # 打桩：把读数函数换成空字典（= 改前那一格根本不存在）
    monkeypatch.setattr(SEC, "_deps_missing_reading", lambda **kw: {})
    stubbed = _read_only_deps_reading(miss_body)
    assert not _a_holds({"deps_missing": stubbed, "deps_written": 0}), (
        "把 `deps_missing` 的读数打桩成空之后判据 a 还是绿的 ⇒ a 没接在那根线上")

    # ---- 正控（b）：真口径下，文件 6 行 vs 派生副本 0 行是"分家"
    st_b = _ws(tmp_path, "db")
    d_texts = ("证明：由定义直接得到。", "证明：换一条路线。")
    out = _seed(st_b, full="命题 D1：被签两次的那一条。", proof_text=d_texts[0],
                proofs=({"proof_no": 2, "text": d_texts[1]},))
    sid = str(out["stmt_id"])
    # 2026-10-29 口径：两份证明各要连续 `SIGN_STREAK_NEED` 次「成立」（只落台账的那两次
    # 也算台账的行）⇒ 这里是 2×3 行
    for no in (1, 2):
        _sign(st_b, stmt_id=sid, proof_text=VR.proof_text_of(_row(st_b, sid), no),
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


def _top_up_a_copy_of_the_real_ledgers(root, source) -> pathlib.Path:
    """把真机那批 `verifications/*.jsonl` 拷进临时工作区，并把每一份证明补到发签门槛。

    为什么要补（业主 2026-10-29 的口径）：真机那批台账是"一次成立就签"那一版写下的
    （每份 1–2 行「成立」），新口径下它们读成 `holding` —— 于是"读数面能说签了几份"
    这件事在原件上读不出非零。补次数只补「副本」：`projects/` 一个字节都不动，
    `ledger_reading` 的读法一个字都没改。

    补法是追加同一份正文的「成立」行（同 `proof_sha256`），直到该命题该证明号的
    `consecutive_holds` 说 `streak_ok` —— 用的是公开读口，不手算票数。
    """
    win = pathlib.Path(root) / "verifications"
    win.mkdir(parents=True, exist_ok=True)
    need = int(VR.SIGN_STREAK_NEED)
    for src in sorted((pathlib.Path(source) / VR.VERIFICATIONS_DIR).glob("*.jsonl")):
        rows = [json.loads(line) for line in
                src.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert rows, src
        last = dict(rows[-1])
        assert str(last.get("verdict")) == "成立", (src.name, last.get("verdict"))
        no = VR.proof_no_of(last)
        sid = src.stem
        dst = win / src.name

        def _flush() -> None:
            dst.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                           encoding="utf-8")

        _flush()
        n = len(rows)
        for _ in range(need):
            holds = VR.consecutive_holds(root, sid, proof_no=no)
            if holds.get("streak_ok"):
                break
            n += 1
            rows.append(dict(last, verification_id=f"v-9{n:04d}", round=n))
            _flush()
        holds = VR.consecutive_holds(root, sid, proof_no=no)
        assert holds.get("streak_ok") is True, (src.name, holds)
    return pathlib.Path(root)


@pytest.mark.usefixtures("signed_v_handoffs")
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
    assert ledger["table"]["is_store_table"] is False, ledger["table"]
    assert ledger["table"]["rows"] is None, ledger["table"]
    assert ledger["mirror"]["present"] is False, ledger["mirror"]
    assert ledger["agrees"] is None, ledger
    # 缺口二改后不会"消失"，但它变成一个能被读到的数（而不是一页空白）
    assert f"{VR.VERIFICATIONS_DIR}/*.jsonl" == ledger["source"], ledger
    assert ledger["rows"] >= 14, ledger
    # 2026-10-29 口径（连续 3 次「成立」才发签）落在真机老台账上的读数：那批行是旧口径
    # 写的（每份 1–2 行「成立」）⇒ 现在一份都不到门槛，`signed` 是 0（而 `rows` 仍是 14：
    # 文件面照读）。"读数面能说签了几份"由下面那份补够次数的副本证明：
    assert ledger["signed"] == 0 and ledger["signed_statements"] == [], ledger
    topped = _top_up_a_copy_of_the_real_ledgers(tmp_path / "sylow3_ledger", SYLOW3)
    signed_copy = VR.ledger_reading(topped)
    assert signed_copy["files"] == 7 and signed_copy["rows"] == ledger["rows"] + 7 * (
        int(VR.SIGN_STREAK_NEED) - 1), signed_copy
    assert signed_copy["signed"] == 7, signed_copy
    assert len(signed_copy["signed_statements"]) == 7, signed_copy

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


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
