# -*- coding: utf-8 -*-
"""判据：证明号从交付里读（稿头 / 携带单第四列），B 不许再猜。

## 缺口（2026-11-04 已核实的两个缺口之一）

E 的交付里没有"这是第几份证明"这一格：`exhaustionreport.compose_manuscript` 没有
`proof_no` 字段，`depsection.CARRIED_COLUMNS` 也没有这一列 ⇒ 一命题多证明时只能靠 B
在秘书那一支猜「canonical 空则 #p1 / 否则最大号 + 1」。猜错的形态是静默的：同一条
命题的第 2 份证明被记成 #p1，而 V 的签、依赖面的 `used_by`、论文对应表的
`proof_no` 全都跟着错位。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 稿头写 `- 证明号：2` ⇒ 收录后那一份落在 `#p2`（不是 `#p1`），`proof_no_source=crafted` | 交付里没有这一格可读；B 的落点只看"canonical 空不空" ⇒ 落在 `#p1`，返回值里也没有 `proof_no_source` |
| b | 稿头没写、携带单第四列写 2 ⇒ 同一结果，`proof_no_source=carried` | 携带单只有三列（列数不对就整节拒），没有第四列可读 |
| c | 两处都没写 ⇒ 回退（canonical 空则 `#p1` / 否则最大号 + 1），`proof_no_source=fallback`，且不覆盖已有 `#p1` | 返回值里没有 `proof_no_source`；这一档是"猜"还是"读了"，盘上分不开 |
| c2 | 两处都没写、且「没有模型缝」 ⇒ 判不了就不并：第二笔落新行 000001，`adjudication.fail_closed=True` + `why_not_merged` 点名在册那一条 | 2026-11-04（件1 76dd2971）之后的新口径：fail-closed 不并；这一条把"没查成会怎样"也钉住，test_c 的缝才有对照 |
| d | 反真空：把"读交付里的号"那一支打桩成恒缺席 ⇒ a 必须回落到 `#p1` | 没有那一支可打桩（`AttributeError`）⇒ 先红 |

## 口径

- 稿头那一行：`- 证明号：<N>`（`exhaustionreport.compose_manuscript` 写；
  `depsection.manuscript_proof_no` 读）。不知道就省略 = 第 1 份。
- 携带单第四列：`depsection.CARRIED_COLUMNS` 的最后一列；老行没有这一列 ⇒ 读成 `#p1`
  （老数据的读数与改前逐字不变）。
- B 优先用交付里的号（`crafted` 先于 `carried`）；都没有才回退。

全部用例在 `tmp_path` 里自建工作区；E 的穷举会审是机械七项 ⇒ 零模型调用。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import depsection as DS  # noqa: E402
from agentflow import propositionkey as PK  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402

from test_e_proof_is_carried_by_d import (  # noqa: E402
    FULL, _env, _file, _write_note,
)

P1 = ("1. 由定义直接得到。\n2. 对 n 作归纳，归纳步用假设两边同乘。\n"
      "3. 收尾：归纳完成，命题对一切 n 成立。")
P2 = ("反证法：假设存在反例 x。取最小者，由极小性可得邻域内每个点都满足条件；"
      "于是 x 的邻域是闭的，矛盾。故不存在反例。")


def _rows(env: dict) -> list[dict]:
    return [dict(r) for r in env["store"].rows("statements")]


def _add_proof_no_line(env: dict, no: int) -> None:
    """在 E 的稿头（`- 实验号：` 那一带）加一行 `- 证明号：<N>`。

    模拟"E 知道这是第几份"那一趟：只改稿头元信息，`## 证明` 那一节不动 ⇒
    V 的签块（盖的是 `## 证明` 正文的 sha）仍然有效。
    """
    rel = str(env["out"]["proof_manuscript"])
    target = pathlib.Path(env["store"].root) / rel
    lines = target.read_text(encoding="utf-8").split("\n")
    at = next(i for i, line in enumerate(lines) if line.startswith("- 实验号"))
    lines.insert(at + 1, f"- 证明号：{int(no)}")
    target.write_text("\n".join(lines), encoding="utf-8")


def _register_conjecture(env: dict) -> str:
    """先在册一条"证明还空着"的同一条命题（E 出稿时它可能还没号，这是真实次序）。"""
    first = env["b"].register_statement(
        origin="own_result", kind="conjecture", label="R(3,4)=9",
        statement_full=FULL, statement_text="R(3,4)=9", proof_text="",
        evidence_kind="cross_check", doc_id=S.format_id(0),
        line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    return str(first.get("stmt_id") or "")


def _sign_as(env: dict, sid: str, *, proof_no: int) -> None:
    """让 V 把这一份 e-proof 签成 `stmt:<sid>#p<proof_no>`（D268 批 2 的可复算凭据）。

    为什么夹具要自己造这一签（而不是让 `_env(sign=True)` 的 V 去签）：批 2 起签是
    `out/vsigns/<正文 sha>.json` 里一份按 (命题号, 证明号) 绑定的凭据 —— 而
    `_env` 的 V 是在命题还没在册时签的（`statement_id` 空、证明号缺省 #1）。本文件
    要量的正是"交付说第 N 份 ⇒ 这一份就是第 N 份"，所以签必须盖在第 N 份上：E 的稿
    头已经写了 `- 证明号：N`（V 真机也从稿头读号），这里按同一个号发签。
    签块仍盖在稿上（块只是视图，D 的携带单认它；认签看签文件）。

    `_credential_fixture.issue_credential` 是批 2 自己那份公共夹具（三票同源 +
    `vsigns.issue`），不新造第二套。改的是夹具，不是断言。
    """
    from agentflow import vsigns as VS
    from _credential_fixture import issue_credential

    column = str(env["column"])
    rel = str(env["out"]["proof_manuscript"])
    got = issue_credential(env["store"].root, proof_text=column, statement_id=sid,
                           manuscript=rel, proof_no=int(proof_no))
    ledger = str(dict(got.get("sign") or {}).get("ledger") or "")
    path = pathlib.Path(env["store"].root) / rel
    text = path.read_text(encoding="utf-8")
    path.write_text(VS.stamp_manuscript_sign(
        text, proof_sha=VR.text_sha(column), streak=VR.SIGN_STREAK_NEED,
        need=VR.SIGN_STREAK_NEED, verdict="成立",
        at="2026-11-05T12:00:00+08:00", ledger=ledger, statement_id=sid,
        manuscript_id=VS.manuscript_id_of(rel)), encoding="utf-8")


def _stub_model_says_same(monkeypatch: pytest.MonkeyPatch, *, target: str) -> None:
    """把"秘书判同一对正文"填成 `verdict=same / same_as=<target>`（判据入口那一处）。

    与 `tests/test_no_model_means_no_merge.py::_stub_model_says_same` 同形：打的是
    `Secretary.adjudicate_proposition`（判据入口），不是 `_same_proposition_candidate`
    （兜底那一档）。为什么 test_c 需要它（2026-11-04，件1 76dd2971 之后）：
    "第二份是同一套的改写 ⇒ 秘书判同一条 ⇒ 落成第 N 份证明"这条期望「以模型判得成
    为前提」；没有缝时秘书按 fail-closed 不并（那是新的、更严的读数，由同文件的
    `test_c2_...` 单独钉住）。不补这一道缝，test_c 测的就不再是"回退编号"，
    而是"没缝时不许并"—— 两件事混在一条用例里，改哪一端都说不清。
    """
    def _judge(self, stmt_like, **_kw):  # noqa: ANN001, ARG001 - 替身只用参数名对齐
        return {"checked": True, "verdict": PK.STATE_SAME, "same_as": str(target),
                "basis": "打桩：条件组与结论组一致", "canonical_name": "", "route": "",
                "condition": "打桩：条件未读", "conclusion": "打桩：结论未读",
                "reason": "打桩：模型判 same", "candidates": [], "cost": {},
                "reused": False, "cached": False, "statement_sha256": "",
                "attempted": True, "seam_source": "打桩"}

    monkeypatch.setattr(Secretary, "adjudicate_proposition", _judge)


# ============================================================ a 稿头那一行
def test_a_the_manuscript_header_number_lands_the_proof_on_that_number(
        tmp_path: pathlib.Path) -> None:
    """a：稿头写 `- 证明号：2` ⇒ 那一份落在 `#p2`，`proof_no_source=crafted`。

    2026-11-10（D268 批 2）：签改成"按号绑定"的可复算凭据 —— 这一份由 V 签成
    `stmt:<号>#p2`（见 `_sign_as`）。改的是夹具：`_env(sign=False)` 不再让 V 用
    "未在册 #1"的形态签，因为批 2 起那一签在册之后读到别的号上是 `borrowed`
    （借光不算签），这一笔会在准入闸上被拒 —— 而那与本文件要量的"B 读交付里的号"
    无关。被量对象一个字没变：`proof_no_source` / 落点 / 盘上那一份正文。
    """
    env = _env(tmp_path, sign=False)
    column = str(env["column"])
    _add_proof_no_line(env, 2)
    sid = _register_conjecture(env)
    _sign_as(env, sid, proof_no=2)

    rows, _note = AgentD(env["store"])._carried_manuscripts()
    _write_note(env, rows)
    filed = _file(env)
    assert filed.get("ok") is True, filed
    assert int(filed.get("proof_no") or 0) == 2, filed
    assert filed.get("proof_no_source") == "crafted", filed

    got = _rows(env)
    assert len(got) == 1, "同一份交付被登记成了第二行"
    row = got[0]
    assert VR.proof_text_of(row, 2) == column, (
        f"#p2 的正文不是这一份（读到 {VR.proof_text_of(row, 2)[:40]!r}）")
    assert VR.proof_text_of(row, 1) == "", (
        "这一份被同时写进了 #p1 —— 证明号只有一份权威，不许复制")
    assert VR.text_sha(VR.proof_text_of(row, 2)) == VR.text_sha(column)


# ============================================================ b 携带单第四列
def test_b_the_carried_sheet_column_lands_the_proof_on_that_number(
        tmp_path: pathlib.Path) -> None:
    """b：稿头没写、携带单第四列写 2 ⇒ 同样落在 `#p2`，`proof_no_source=carried`。

    2026-11-10（D268 批 2）：同 a —— 签是 `stmt:<号>#p2` 的可复算凭据（`_sign_as`）。
    """
    env = _env(tmp_path, sign=False)
    column = str(env["column"])
    sid = _register_conjecture(env)
    _sign_as(env, sid, proof_no=2)

    rows, _note = AgentD(env["store"])._carried_manuscripts()
    assert len(rows) == 1, rows
    # 稿头没写：D 生成的这一行按 #p1 读（空第四列）。这里只改携带单那一格，
    # 模拟"D 知道这一份是第 2 份并把号写在单上"。
    rows = [{**dict(r), "proof_no": 2} for r in rows]
    section = DS.render_carried_section(rows)
    assert "证明号" in section, section
    parsed = DS.carried_manuscripts(section)
    assert parsed["problems"] == [] and parsed["refused"] == "", parsed
    assert [r["proof_no"] for r in parsed["rows"]] == [2], parsed

    _write_note(env, rows)
    filed = _file(env)
    assert filed.get("ok") is True, filed
    assert int(filed.get("proof_no") or 0) == 2, filed
    assert filed.get("proof_no_source") == "carried", filed
    row = _rows(env)[0]
    assert VR.proof_text_of(row, 2) == column, row
    assert VR.proof_text_of(row, 1) == "", row


# ============================================================ c 回退
def test_c_without_a_number_the_fallback_does_not_overwrite_p1(
        store, signed_v_handoffs, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：两处都没有号 ⇒ 回退到最大号 + 1（`#p2`），已有 `#p1` 一个字不动。

    前提（2026-11-04，件1 76dd2971 之后）：第二份要并进同一条命题，「必须模型判
    `same`」（没有缝时秘书按 fail-closed 不并 —— 那一档由下面 `test_c2` 钉住）。
    所以这里按判据入口打一道"模型判 same"的缝，让"回退编号"这条被测的规则不变。
    """
    b = AgentB(store, extractor=None, extract_text=None, config={})
    first = b.register_statement(
        origin="own_result", kind="conjecture", label="L", statement_full=FULL,
        statement_text="R(3,4)=9", proof_text=P1, evidence_kind="heuristic",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    _stub_model_says_same(monkeypatch, target=str(first.get("stmt_id") or ""))
    # 第二份：命题表述是同一套的改写（模型判同一条 ⇒ 落成第 N 份证明那条路）。
    second = b.register_statement(
        origin="own_result", kind="conjecture", label="L",
        statement_full=FULL + "（同上）。",
        statement_text="R(3,4)=9", proof_text=P2, evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert second.get("ok") is True, second
    assert (second.get("adjudication") or {}).get("verdict") == PK.STATE_SAME, second
    assert second.get("proof_no_source") == "fallback", second
    assert int(second.get("proof_no") or 0) == 2, second

    row = dict(store.rows("statements")[0])
    assert VR.proof_text_of(row, 1) == P1, "回退那一笔覆盖了在册的 #p1"
    assert VR.proof_text_of(row, 2) == P2, row
    assert len(list(store.rows("statements"))) == 1


# ============================================================ c2 没缝 ⇒ fail-closed 落新行
def test_c2_without_a_model_the_second_proof_lands_a_new_row(
        store, signed_v_handoffs) -> None:
    """c2（反真空）：「没有」模型缝时不许并 ⇒ 落新行 000001，且读数说清"为什么没并"。

    件1（76dd2971）之后的硬口径：判不了就是不并，词面相似度只排序、不替模型表态。
    没有这一条，test_c 的那道缝就成了"唯一被看到的路径"——"没查成会怎样"只剩
    实现里的注释，没有任何判据钉住它。

    期望（改后的新行为，2026-11-04 8d4046f5 的同族读数）：
    `adjudication.checked=False`（没查成，不是"查过了、不同"）、`attempted=False`、
    `fail_closed=True`、`why_not_merged` 点名在册的 stmt:000000；第二笔落「新行」
    000001，编号回退到 `#p1`（新行没有 canonical 的 #1），旧行 `#p1` 一个字不动。
    """
    b = AgentB(store, extractor=None, extract_text=None, config={})
    first = b.register_statement(
        origin="own_result", kind="conjecture", label="L", statement_full=FULL,
        statement_text="R(3,4)=9", proof_text=P1, evidence_kind="heuristic",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    # 第二份：同一套表述的改写；没有模型缝 ⇒ 判不了 ⇒ 不并。
    second = b.register_statement(
        origin="own_result", kind="conjecture", label="L",
        statement_full=FULL + "（同上）。",
        statement_text="R(3,4)=9", proof_text=P2, evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert second.get("ok") is True, second
    adjudication = dict(second.get("adjudication") or {})
    assert adjudication.get("checked") is False, adjudication
    assert adjudication.get("attempted") is False, adjudication
    assert adjudication.get("fail_closed") is True, adjudication
    assert str(first.get("stmt_id") or "") in str(
        adjudication.get("why_not_merged") or ""), adjudication
    assert second.get("proof_no_source") == "fallback", second
    assert int(second.get("proof_no") or 0) == 1, second

    rows = {str(r.get("stmt_id")): dict(r) for r in store.rows("statements")}
    assert len(rows) == 2, f"没缝时两笔应当各落一行，实际 {len(rows)} 行：{sorted(rows)}"
    assert VR.proof_text_of(rows[str(first.get("stmt_id"))], 1) == P1
    new_row = rows[str(second.get("stmt_id"))]
    assert VR.proof_text_of(new_row, 1) == P2, new_row
    assert VR.proof_text_of(new_row, 2) == "", "新行不该多出 #p2"


# ============================================================ d 反真空
def test_d_stubbing_the_delivery_reading_falls_back_to_p1(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把"读交付里的号"那一支摘掉 ⇒ a 的那一笔不再成立（判据红）。

    打桩点就是那一支本身（`AgentB._proof_no_from_delivery`）：它同时管稿头与携带单
    —— 摘掉它之后，同一份夹具（稿头写着 2）只能走回退，落在 `#p1`。

    2026-11-10（D268 批 2，期望按新契约改写）：a 的签是 `stmt:<号>#p2` 的可复算
    凭据，而这一趟回退要写的 `#p1` 没有签 ⇒ 准入闸 `proof_without_v_sign` 整笔拒，
    盘上零新增。旧期望（"摘掉读数支之后照样落 #1、ok=True"）钉的是块时代那条
    与号无关的签（块在就算签，落哪一号都成立）；批 2 起签按 (命题号, 证明号) 绑定，
    那条期望不再等价 —— 新版更严：它同时要求"交付号读对了"与"那一份真的有
    覆盖它的签"，两者缺一整笔不写。反真空的强度没降：摘掉读数支之后 a 的结论
    （`ok=True` + 落在 #p2）当场不成立，而且拒信点名缺的是 `#1` 那一份的签。
    """
    env = _env(tmp_path, sign=False)
    column = str(env["column"])
    _add_proof_no_line(env, 2)
    sid = _register_conjecture(env)
    _sign_as(env, sid, proof_no=2)
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    _write_note(env, rows)

    monkeypatch.setattr(AgentB, "_proof_no_from_delivery",
                        staticmethod(lambda **kw: (0, "fallback")))
    filed = _file(env)
    assert filed.get("ok") is False, filed
    assert filed.get("kind") == "proof_without_v_sign", filed
    gate = dict(filed.get("proof_gate") or {})
    assert gate.get("missing") == [1], gate
    assert "#1" in str(gate.get("why") or ""), gate
    row = _rows(env)[0]
    assert VR.proof_text_of(row, 1) == "", (
        "摘掉读数支之后仍然把这一份写进了 #p1 —— 那一份没有签，闸没挡住")
    assert VR.proof_text_of(row, 2) == "", row


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
