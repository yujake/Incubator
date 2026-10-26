# -*- coding: utf-8 -*-
"""判据（D7）：改已在册命题的正文有合法写口，且别条命题的手稿不会被当成这条的依赖源。

## 真机读数（`projects/mp3-r2`，2026-10-26 13:17，台账 `draft/156` 的 D7）

B 拿到 stmt:000008 的完整证明（F 的手稿 7595 B / 54 行），要把登记时那份截断正文
（止于「故 ω^n/」）换掉。它试了四条路，四条都不收，于是只能 handoff 上报
「本面内无改行写口」。结果：`proof_no` 恒 0、`proofs` 恒空 —— 多份证明与引用核实两项
在真机上根本进不到场。

四条路的真实返回（本文件 a 判据钉的是第 1、3 条的落点）：

1. `own.register_statement`（同 statement_full + `proof_text`=全文）⇒
   `ok:true / new_row:false / received_manuscript:true /
    note:「收方读稿登记：命题行不动（这条命题已经在册）…」`，`proof_text` 仍 1490 字、
   `proof_history` 0 条；
2. 只给 `proofs=[{proof_no:1, text:全文}]` ⇒ 同上，`proofs_received:[]`；
3. `proof_manuscript`=全文 ⇒ 同上（`manuscript_source:"param"`）；
4. `table.update(statements, 000008)` ⇒ `routed_to_backstop.secretary_refused` /
   `direct_write_refused`。

## 根因（改前）

`agent_b/register_statement.py` 里那条 2026-10-26 为「D 到 B」加的早退支路
（`if manuscript_text.strip(): ... _receive_carried_manuscript(...)`）只按
`_existing_statement_for(full)` 认"同一条命题已在册"，于是任何一份被兜底读盘 / D 的
携带单找出来的手稿都会让这一笔提前返回"命题行不动" —— 哪怕这一笔自己带了 canonical
正文。而真机上被找出来的那份稿根本不是这条命题的（`reports/f-proof-000000.md`，头一行
`- 命题号：stmt:000000`），它只是被证明正文里的一句引用带出来的。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 带正文的那一笔真的落盘 | `proof_text` 换成全文、旧正文进 `proof_history`（`text`/`sha`/`replaced_by` 逐条对得上） | 改前 `ok:true` 而 `proof_text` 一个字没动、`proof_history` 空（上面路 1 的原话） |
| a2 旧签不再算数、但不删 | 覆盖之后 `review_standing.state=="stale"`、`bits.reviewed` 读成 False、签名台账里那一签还在 | 改前正文没变 ⇒ 旧签照样算数（挡签链因此永远进不到场） |
| b1 反真空（A 的排除项） | 把 `_carries_canonical_write` 打成恒 False ⇒ a 必红 | —— |
| b2 别条命题的稿不许当依赖源 | 只交别条命题的稿 ⇒ `manuscript_owner_mismatch`，拒信点名两个号；`dependencies` 一行不落 | 改前 `ok:true`、被当成这条命题的稿 |
| b3 带正文 + 别条命题的稿 | 正文照写、那份稿的依赖面一条不落，读数 `manuscript_owner` 点名它属于谁 | 改前正文写不进去 |
| c 非 B 调用 | 秘书那一笔受控拒绝 `not_statement_writer`（写者仍然只有 B） | ——（既有行为，钉住不回退） |
| d 通用写口的拒信指回正路 | `table.update(statements, patch={proof_text})` 的拒信必须点名 `own.register_statement` 与 `proof_history` | 改前那句写「证明正文变了就是另一条命题，不能就地替换已登记的那一份」—— 与框架的实际能力相反，真机上模型正是读了它才写"无改行写口" |

全部 tmp 工作区、零模型调用。
"""
from __future__ import annotations

import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.conductor import calling_as  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

TS = "2026-10-26T13:03:49+08:00"
#: 在册那一行（真机 `statements.json` 的 000008）：命题正文 112 字，证明是截断摘录。
STATEMENT = ("设 k 为任意域，g 为 k 上的 Lie 代数，A = U(g) 为其泛包络代数，"
             "ε: A → k 为增广同态（ε|_g = 0，ε(1) = 1），ω = ker ε。"
             "若 A 左诺特或右诺特，则 dim_k g < ∞。")
#: 登记时落盘的证明正文（截断：真机上止于「故 ω^n/」，缺结论步与依赖节）。
TRUNCATED = ("P1（PBW 与长度滤过）：取 g 的一组 k-基并排序，由 PBW 定理有序单项式构成 A 的 k-基。\n\n"
             "P2（增广理想）：令 ω = ker ε，则 ω 是 A 的双边理想。\n\n"
             "N2（ω^n/ω^{n+1} 的维数上界）：在 P4 下，dim_k(ω^n/ω^{n+1}) ≤ k^n。"
             "证明：ω^n 是左理想、ω^{n+1} ⊆ ω^n 是其子左理想，故 ω^n/")
#: 完整证明（B 要写进去的那一份）：结尾有结论步，正文里点了在册的 stmt:000000。
FULL = (TRUNCATED.replace("故 ω^n/", "") + "ω^{n+1} 是商，维数上界由生成元个数给出。∎\n\n"
        "右诺特：把左作用换成右作用、c_i a_i 换成 a_i c_i，同一论证逐字成立。\n\n"
        "结论：A = U(g) 左诺特且右诺特；该论证与在册 stmt:000000 合起来给出充要条件。\n")
#: 别条命题的稿（真机 `reports/f-proof-000000.md` 的形状）：头一行写明它是 stmt:000000 的，
#: 带洗稿元信息与一张空的依赖表。
FOREIGN_MANUSCRIPT = (
    "# F 的证明手稿：逆命题：dim_k g = n < ∞ ⇒ U(g) 左右诺特\r\n\r\n"
    "- 命题号：stmt:000000\r\n"
    "- 计划：000000 · 子目标：S2\r\n"
    "- 依赖面洗稿：已洗=true；执行者=secretary-F\r\n\r\n"
    "## 命题\r\n\r\n逆命题：dim_k g = n < ∞ ⇒ U(g) 左右诺特。\r\n\r\n"
    "## 证明\r\n\r\n1. 滤环引理逐条写清（P1–P3）。\r\n2. 左右两向各自成立。\r\n\r\n"
    "## 依赖\r\n\r\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\r\n"
    "|---|---|---|---|\r\n\r\n"
    "（这一份证明没有引用任何在册命题 —— 空表就是自足的证明）\r\n")


# ------------------------------------------------------------------ 小工具


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


#: 在册那一行的号（真机 `stmt:000008`）。别条命题的稿声明的是 `stmt:000000` ——
#: 两个号必须不同，否则"这份稿是别人的"这条判据在夹具上恒不成立。
SID = "000008"


def _own(st: Store, *, statement_full: str = STATEMENT, proof_text: str = TRUNCATED,
         kind: str = "conjecture", stmt_id: str = SID) -> str:
    """铺一行在册命题（走真正的 `store.tx`，它必须成功）。"""
    row = {
        "stmt_id": stmt_id, "origin": "own_result", "kind": kind,
        "label": "U(g) 左右诺特蕴含 dim_k g<∞", "statement_full": statement_full,
        "statement_text": statement_full, "proof_text": proof_text,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None,
        "quote_reason": ("自产结果，没有外部出处可逐字回验；手稿在 N2 中途被截断 ⇒ "
                         "proof_text 是逐字但未完成的摘录，不是全文"),
        "line_range": {"start": None, "end": None, "label": "派活 t-000020 交付的手稿"},
        "created_at": TS, "created_by": "secretary-B",
        "bits": EB.bits_of(proof=bool(proof_text.strip()),
                           proof_process=proof_text, kind=kind),
    }
    with st.tx("statements") as tx:
        tx.upsert("statements", row, note="seed:real-mp3r2-000008")
    return str(row["stmt_id"])


def _foreign_manuscript_on_disk(st: Store) -> None:
    """盘上那一份别条命题的稿：`reports/f-proof-000000.md`（真机同名同形状）。"""
    d = pathlib.Path(str(st.root)) / DS.MANUSCRIPT_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "f-proof-000000.md").write_text(FOREIGN_MANUSCRIPT, encoding="utf-8")


def _agent(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None, config={})


def _row(st: Store) -> dict:
    return dict(st.rows("statements")[0])


def _sign(st: Store, *, proof_text: str = TRUNCATED, stmt_id: str = "") -> dict:
    """V 的签名写入口（`verify.verify_proof` 走的就是它；这里不经模型）。"""
    return VR.record_verification(
        st.root, statement_id=stmt_id or SID, proof_text=proof_text,
        verdict={"verdict": "成立", "findings": []}, verifier="agent-V", store=st,
        proof_no=1)


def _deps_count(st: Store) -> int:
    return len(st.rows("dependencies"))


# ============================================================ a：正文真的被换掉


def test_a_a_superseding_proof_text_is_written_with_history(tmp_path: pathlib.Path) -> None:
    """a 判据：带正文的那一笔真的覆盖 canonical，旧正文整段进 `proof_history`。

    现场照真机铺：在册行是截断登记，盘上有别条命题的稿 `reports/f-proof-000000.md`
    （证明正文里那句 `stmt:000000` 会把它带出来）。改前这一笔的返回是
    `ok:true / new_row:false / received_manuscript:true / note:「命题行不动」`，
    而 `proof_text` 仍是那份截断正文、`proof_history` 是空的。
    """
    st = _ws(tmp_path)
    sid = _own(st)
    _foreign_manuscript_on_disk(st)

    out = _agent(st).register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        label="U(g) 左右诺特蕴含 dim_k g<∞", proof_text=FULL,
        line_range={"start": None, "end": None,
                    "label": "notes/f-proof-S1-stmt000008.md（B 逐字读过并核过 sha256）"},
        evidence_kind="heuristic", quote_verified=None,
        quote_reason=("自产结果，无外部出处可逐字回验；verifications/ 下没有 000000.jsonl 之外的签"
                      "⇒ evidence_kind 按现算落 heuristic（不自报强档）"))

    assert out["ok"] is True, out
    row = _row(st)
    assert row["stmt_id"] == sid, row
    assert row["proof_text"] == FULL, ("改在册正文没写进去", row["proof_text"][-40:])
    history = [dict(h) for h in (row.get("proof_history") or [])]
    assert len(history) == 1, history
    entry = history[0]
    assert sorted(entry) == ["at", "replaced_by", "sha", "text"], entry
    assert entry["text"] == TRUNCATED, ("旧正文没有逐字留痕", entry["text"][-40:])
    assert entry["sha"] == VR.proof_sha(TRUNCATED), entry
    assert entry["replaced_by"] == VR.proof_sha(FULL), entry
    assert str(entry["at"]).strip(), entry
    assert out.get("canonical_written") is True, out
    assert out.get("canonical_history"), out


def test_a2_the_old_signature_stops_counting_but_is_not_deleted(tmp_path: pathlib.Path) -> None:
    """a2 判据：换完正文之后 V 的旧签不再算数，而台账里那一签不删（审计可查）。

    "不再算数"由读侧现算（`review_standing` 的 stale）与位（`bits.reviewed=False`）
    各说一遍；"不删"由签名台账里那一行仍在、`verification_id` 仍是它来钉。
    """
    st = _ws(tmp_path)
    sid = _own(st)
    signed = _sign(st, proof_text=TRUNCATED, stmt_id=sid)
    assert str(signed.get("verification_id") or "").startswith("v-"), signed
    assert EB.bits_from_row(_row(st))["reviewed"] is True, "正控：签完之后这一位必须是 True"

    _foreign_manuscript_on_disk(st)
    out = _agent(st).register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        label="U(g) 左右诺特蕴含 dim_k g<∞", proof_text=FULL,
        line_range={"start": None, "end": None,
                    "label": "notes/f-proof-S1-stmt000008.md（B 逐字读过并核过 sha256）"},
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="自产结果，无外部出处可逐字回验；重签之前按 heuristic 读")
    assert out["ok"] is True and out.get("canonical_written") is True, out

    standing = VR.review_standing(st.root, statement_id=sid, proof_text=FULL, proof_no=1)
    assert standing["state"] == "stale", standing
    assert standing["ok"] is False and standing["in_sync"] is False, standing
    assert standing["verification_id"] == signed["verification_id"], standing
    assert EB.bits_from_row(_row(st))["reviewed"] is False, _row(st).get("bits")
    rows, problems = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert problems == [], problems
    assert [r["verification_id"] for r in rows] == [signed["verification_id"]], (
        "旧签被删了 —— 审计链断在这里")


# ============================================================ b1：反真空


def test_b1_stubbing_the_write_predicate_out_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """b1 判据（反真空）：把 `_carries_canonical_write` 打成恒 False ⇒ a 必红。

    打桩点就是那条判据本身（它决定"这一笔要不要走读稿登记早退支路"）：打成恒 False
    之后，带正文的这一笔又会被早退支路吞掉 —— 于是 a 的绿来自这条判据，而不是
    某个顺手写的分支。
    """
    monkeypatch.setattr(AgentB, "_carries_canonical_write",
                        staticmethod(lambda **kw: False))
    st = _ws(tmp_path)
    _own(st)
    _foreign_manuscript_on_disk(st)
    out = _agent(st).register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        label="U(g) 左右诺特蕴含 dim_k g<∞", proof_text=FULL,
        line_range={"start": None, "end": None,
                    "label": "notes/f-proof-S1-stmt000008.md（B 逐字读过并核过 sha256）"},
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="自产结果，无外部出处可逐字回验")
    row = _row(st)
    assert out.get("canonical_written") is not True, out
    assert row["proof_text"] == TRUNCATED, ("判据被打桩了，正文却还是写进去了", row["proof_text"])
    assert not (row.get("proof_history") or []), row.get("proof_history")


# ============================================================ b2 / b3：稿的归属


def test_b2_a_manuscript_of_another_statement_is_refused_by_name(
        tmp_path: pathlib.Path) -> None:
    """b2 判据：拿别条命题的稿来登记 ⇒ 拒、点名两个号、依赖面一行不落。

    真机形态：兜底读盘按正文里的 `stmt:000000` 找到 `reports/f-proof-000000.md`，
    而那一份稿头一行写着 `- 命题号：stmt:000000` —— 它是 000000 的稿。改前它被当成
    这条命题的稿（`ok:true / received_manuscript:true`），依赖面记到错误的号上。
    """
    st = _ws(tmp_path)
    sid = _own(st)
    _foreign_manuscript_on_disk(st)
    out = _agent(st).register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        label="U(g) 左右诺特蕴含 dim_k g<∞",
        line_range={"start": None, "end": None,
                    "label": "notes/f-proof-S1-stmt000008.md（B 逐字读过并核过 sha256）"},
        proof_manuscript=FOREIGN_MANUSCRIPT,
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="自产结果，无外部出处可逐字回验")
    assert out["ok"] is False, out
    assert out["kind"] == "manuscript_owner_mismatch", out
    msg = str(out["error"])
    assert "stmt:000000" in msg and f"stmt:{sid}" in msg, msg
    assert _deps_count(st) == 0, "拒了却把别条命题的依赖记到了这条头上"
    assert out.get("manuscript_owner") == "000000", out
    row = _row(st)
    assert row["proof_text"] == TRUNCATED, "拒了却改了正文"


def test_b3_a_foreign_manuscript_never_feeds_the_dependency_face(
        tmp_path: pathlib.Path) -> None:
    """b3 判据：带正文 + 别条命题的稿 ⇒ 正文照写，那份稿的依赖面一条不落。

    A 与 B 的分工在这一条上看得最清楚：正文优先（A），但依赖面绝不从别人的稿上落（B）。
    读数里 `manuscript_owner` 点名那份稿属于谁、`manuscript_owner_ok=False`。
    """
    st = _ws(tmp_path)
    _own(st)
    _foreign_manuscript_on_disk(st)
    out = _agent(st).register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        label="U(g) 左右诺特蕴含 dim_k g<∞", proof_text=FULL,
        line_range={"start": None, "end": None,
                    "label": "notes/f-proof-S1-stmt000008.md（B 逐字读过并核过 sha256）"},
        proof_manuscript=FOREIGN_MANUSCRIPT,
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="自产结果，无外部出处可逐字回验")
    assert out["ok"] is True, out
    assert out.get("canonical_written") is True, out
    assert _row(st)["proof_text"] == FULL, _row(st)["proof_text"][-40:]
    assert _deps_count(st) == 0, "别条命题的依赖面被记到这条头上了"
    deps = dict(out.get("deps_missing") or {})
    assert deps.get("manuscript_owner") == "000000", deps
    assert deps.get("manuscript_owner_ok") is False, deps


# ============================================================ c：写者仍然只有 B


def test_c_only_b_can_write_the_statement(tmp_path: pathlib.Path) -> None:
    """c 判据：非 B 交内容 ⇒ 秘书受控拒绝 `not_statement_writer`，一行都不落。

    这一件不新增动作，所以"B 专用"这件事仍然由秘书那一笔的写者判据把关
    （`secretary.record_statement(..., role=...)`）；这里把它钉住不回退。
    """
    st = _ws(tmp_path)
    sec = Secretary("F", root=st.root, store=st)
    out = sec.record_statement({"statement_full": STATEMENT, "kind": "conjecture",
                                "proof_text": FULL, "origin": "own_result"},
                               role="F")
    assert out["checked"] is False, out
    assert out["refused"] == "not_statement_writer", out
    assert st.rows("statements") == []


# ============================================================ d：拒信指回正路


def test_d_the_direct_write_refusal_points_at_the_real_road(tmp_path: pathlib.Path) -> None:
    """d 判据：`table.update(statements, patch={proof_text})` 的拒信指回正路。

    改前那句是「证明正文变了就是另一条命题，不能就地替换已登记的那一份」—— 与框架的
    实际能力相反（canonical 本来就是可覆盖的，旧正文还有 `proof_history` 留痕）。真机上
    模型正是读了那句话才在 handoff 里写"本面内无改行写口"。这条拒信必须点名
    `own.register_statement` 与 `proof_history`，否则它仍然把模型劝到墙角。
    """
    from agentflow.tools import build_registry

    st = _ws(tmp_path)
    sid = _own(st)
    reg = build_registry(store=st, workspace_root=st.root).registry
    with calling_as("t-probe", "B"):
        res = reg.call("table.update", role="B", table="statements", id=sid,
                       patch={"proof_text": FULL})
    assert res.ok is False, res
    assert res.meta.get("kind") == "direct_write_refused", res.meta
    msg = str(res.error or "")
    assert "own.register_statement" in msg, msg
    assert "proof_history" in msg, msg
    assert "不能就地替换" not in msg, msg
    assert _row(st)["proof_text"] == TRUNCATED, "拒了却改了正文"


def test_d2_the_conflict_message_says_one_authority(tmp_path: pathlib.Path) -> None:
    """d2（附带）：`proof_text` 与 `proofs[#p1]` 同时给 ⇒ 拒信必须说清"只写一处"。

    真机上 B 就是这么交的（两个字段各写一份全文），拿到的是
    `proof_text_conflict`。这条拒信本身已经写了"二选一"，这里把它钉住 ——
    同一份正文只许有一个权威，这句话在"改在册正文"的正路上必须一直说。
    """
    st = _ws(tmp_path)
    _own(st)
    out = _agent(st).register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        label="U(g) 左右诺特蕴含 dim_k g<∞", proof_text=FULL,
        line_range={"start": None, "end": None,
                    "label": "notes/f-proof-S1-stmt000008.md（B 逐字读过并核过 sha256）"},
        proofs=[{"proof_no": 1, "text": FULL + "\n（多一个字）"}],
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="自产结果，无外部出处可逐字回验")
    assert out["ok"] is False and out["kind"] == "proof_text_conflict", out
    assert "二选一" in str(out["error"]), out["error"]


# ============================================================ 读数（`json` 便于人核）


def test_the_readings_are_json_safe(tmp_path: pathlib.Path) -> None:
    """读数形状：返回值必须能整份 `json.dumps`（它要进台账与观测层）。"""
    st = _ws(tmp_path)
    _own(st)
    _foreign_manuscript_on_disk(st)
    out = _agent(st).register_statement(
        statement_full=STATEMENT, origin="own_result", kind="conjecture",
        label="U(g) 左右诺特蕴含 dim_k g<∞", proof_text=FULL,
        line_range={"start": None, "end": None,
                    "label": "notes/f-proof-S1-stmt000008.md（B 逐字读过并核过 sha256）"},
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="自产结果，无外部出处可逐字回验")
    blob = json.dumps(out, ensure_ascii=False, default=str)
    assert blob.strip().startswith("{"), blob[:80]
