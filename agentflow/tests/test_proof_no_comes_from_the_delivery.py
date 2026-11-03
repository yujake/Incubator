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
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_d import AgentD  # noqa: E402

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


# ============================================================ a 稿头那一行
def test_a_the_manuscript_header_number_lands_the_proof_on_that_number(
        tmp_path: pathlib.Path) -> None:
    """a：稿头写 `- 证明号：2` ⇒ 那一份落在 `#p2`，`proof_no_source=crafted`。"""
    env = _env(tmp_path)
    column = str(env["column"])
    _add_proof_no_line(env, 2)
    _register_conjecture(env)

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
    assert VR.proof_sha(VR.proof_text_of(row, 2)) == VR.proof_sha(column)


# ============================================================ b 携带单第四列
def test_b_the_carried_sheet_column_lands_the_proof_on_that_number(
        tmp_path: pathlib.Path) -> None:
    """b：稿头没写、携带单第四列写 2 ⇒ 同样落在 `#p2`，`proof_no_source=carried`。"""
    env = _env(tmp_path)
    column = str(env["column"])
    _register_conjecture(env)

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
        store, signed_v_handoffs) -> None:
    """c：两处都没有号 ⇒ 回退到最大号 + 1（`#p2`），已有 `#p1` 一个字不动。"""
    b = AgentB(store, extractor=None, extract_text=None, config={})
    first = b.register_statement(
        origin="own_result", kind="conjecture", label="L", statement_full=FULL,
        statement_text="R(3,4)=9", proof_text=P1, evidence_kind="heuristic",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert first.get("ok") is True, first
    # 第二份：命题表述是同一套的改写（秘书判同一条 ⇒ 落成第 N 份证明那条路）。
    second = b.register_statement(
        origin="own_result", kind="conjecture", label="L",
        statement_full=FULL + "（同上）。",
        statement_text="R(3,4)=9", proof_text=P2, evidence_kind="cross_check",
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导")
    assert second.get("ok") is True, second
    assert second.get("proof_no_source") == "fallback", second
    assert int(second.get("proof_no") or 0) == 2, second

    row = dict(store.rows("statements")[0])
    assert VR.proof_text_of(row, 1) == P1, "回退那一笔覆盖了在册的 #p1"
    assert VR.proof_text_of(row, 2) == P2, row
    assert len(list(store.rows("statements"))) == 1


# ============================================================ d 反真空
def test_d_stubbing_the_delivery_reading_falls_back_to_p1(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：把"读交付里的号"那一支摘掉 ⇒ a 必须回落到 `#p1`（判据红）。

    打桩点就是那一支本身（`AgentB._proof_no_from_delivery`）：它同时管稿头与携带单
    —— 摘掉它之后，同一份夹具（稿头写着 2）只能走回退，落在 `#p1`。于是 a 的绿
    真的来自"读了交付里的号"，不是"恰好盘上只有一份证明"。
    """
    env = _env(tmp_path)
    column = str(env["column"])
    _add_proof_no_line(env, 2)
    _register_conjecture(env)
    rows, _note = AgentD(env["store"])._carried_manuscripts()
    _write_note(env, rows)

    monkeypatch.setattr(AgentB, "_proof_no_from_delivery",
                        staticmethod(lambda **kw: (0, "fallback")))
    filed = _file(env)
    assert filed.get("ok") is True, filed
    assert int(filed.get("proof_no") or 0) == 1, filed
    assert filed.get("proof_no_source") == "fallback", filed
    row = _rows(env)[0]
    assert VR.proof_text_of(row, 1) == column, row
    assert VR.proof_text_of(row, 2) == "", (
        "摘掉读数支之后仍然落在 #p2 —— a 的绿不是那一支给的")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
