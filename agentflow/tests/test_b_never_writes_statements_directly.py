# -*- coding: utf-8 -*-
"""B 本体对 `statements` 只读：每一笔台账写都由 B 的秘书落盘（业主 2026-11-08）。

业主逐字：「我应该定过B实际只有台账的只读权限，B的任何所谓写台账的路实际上都由B秘书洗过」
「为什么留了多种口径登记命题台账？」「不要给派的人直接钉死形状，叫他查清当前实现，尽可能
复用代码，只是收束口径」

## 判据

| # | 判据 | 它要的红 |
|---|---|---|
| a | 源码扫描：`src/agentflow/agent_b/**` 全部 .py 里"直接写 `statements`"的调用点 = 0 | 改前那两处：`_update_numeric_evidence`（`store.tx("statements")` + `tx.upsert`）与 `_attach_proofs`（同形） |
| a' | 反真空：同一台扫描器对"塞回一处直写"的样本必报 | 扫描器恒返回空 ⇒ a 的绿说明不了任何事 |
| b | 三条正控（新建行 / 追加证明 / 更新数值证据位）各跑一趟：行都落盘，且 `statements` 的每一次 upsert 事件 `actor` 都是 `secretary-B` | 改前那两笔的 `actor` 是 `agent-B` |
| c | 负控：把 `Secretary.land_statement` 关成"一个字都不写" ⇒ b 的两条写路必须不落盘 | 有"B 自己写"的后备路 ⇒ c 绿 |

扫描器只看调用形状（`X.tx("statements")` / `X.upsert("statements")` / `.update` / `.delete`），
不看上下文：`tables_for_concept_write("relations")` 那种"声明表名"的写法不是直接写（它的落盘在
`conceptrows → Secretary.write_concept_row` 里，已经经秘书）。
"""
from __future__ import annotations

import ast
import pathlib
import warnings
from typing import Any

import pytest

from conftest import add_literature, sign_before_registration, sign_for_the_gate
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import verifications as VR
from agentflow.agent_b import AgentB

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
AGENT_B = SRC / "agentflow" / "agent_b"

PROOF = ("证明（逐行走查的对象）：\n"
         "1. 由引理 1，弦长闭式 L²/4 = N/A²；\n"
         "2. N 的 Fourier 展开无 4φ 成分，而 A² 的 cos4φ 系数是 ν²/2；\n"
         "3. 若 L 恒为常数则 N = k·A² 逐次谐波系数相等 ⇒ 0 = kν²/2 ⇒ 与 k>0 矛盾。∎")
PROOF_2 = PROOF + "\n（第二份证明：同一结论的另一条路径，用于追加证明那一支。）"
STATEMENT = "设 a≠b 为半轴，椭圆 x²/a²+y²/b²=1 不存在等弦点（弦长函数非常值）。"


# ============================================================ a 扫描器
#: "直接写"的调用名（`X.<name>("statements", …)`）。`tx` 是开事务那一笔，其余是事务方法。
_WRITE_CALLS = frozenset({"tx", "upsert", "update", "delete", "patch"})


def _direct_statement_writes(source: str) -> list[tuple[int, str]]:
    """源码里直接写 `statements` 的调用点（行号, 调用名）。

    只解析、不 import（扫的是源码事实，不是运行时行为）；`ast.parse` 对老文件里的
    非法转义会发 `DeprecationWarning` —— 那与"谁写这张表"无关，这里静音掉。
    """
    out: list[tuple[int, str]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else "")
        if name not in _WRITE_CALLS or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == "statements":
            out.append((int(getattr(node, "lineno", 0)), name))
    return out


def test_a_no_agent_b_module_writes_statements_directly() -> None:
    """a：`agent_b/**` 全部 .py 里直接写 `statements` = 0（B 本体对台账只读）。"""
    files = sorted(AGENT_B.rglob("*.py"))
    assert files, f"扫描面是空的：{AGENT_B} 下一份 .py 都没找到（那时 0 命中说明不了任何事）"
    hits: list[tuple[str, int, str]] = []
    for path in files:
        for line, name in _direct_statement_writes(path.read_text(encoding="utf-8")):
            hits.append((str(path.relative_to(SRC)), line, name))
    assert hits == [], (
        "B 本体里还有直接写 `statements` 的地方（它必须经 B 的秘书落盘）：\n  "
        + "\n  ".join(f"{f}:{ln} {name}()" for f, ln, name in hits))


def test_a_negative_control_the_scanner_catches_a_direct_write_put_back() -> None:
    """a' 反真空：把一处直写塞回样本 ⇒ 同一台扫描器必须报（两种形状各一条）。"""
    sample = (
        "def _attach_proofs(self, sid):\n"
        "    with store.tx(\"statements\", actor=\"agent-B\") as tx:\n"
        "        row = tx.find(\"statements\", stmt_id=sid)\n"
        "        tx.upsert(\"statements\", row)\n"
    )
    found = _direct_statement_writes(sample)
    assert [name for _ln, name in found] == ["tx", "upsert"], found
    # 负控的负控：不相干的表名一个都不许报（否则上面那条"0 命中"是假的）
    assert _direct_statement_writes(
        "with store.tx(\"relations\") as tx:\n    tx.upsert(\"relations\", row)\n") == []


# ============================================================ b 三条正控
def _payload(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(
        origin="external_lit", kind="conjecture", label="椭圆无等弦点",
        statement_text="椭圆不存在等弦点", statement_full=STATEMENT,
        proof_text=PROOF, source_lit_id=S.format_id(0),
        page_range={"start": 7, "end": 7}, quote_verified=True,
        quote_reason="逐字比对通过（page 7）", evidence_kind="heuristic",
    )
    base.update(kw)
    return base


def _statement_upserts(store) -> list[dict[str, Any]]:
    return [dict(e) for e in store.read_events()
            if str(e.get("op") or "") == "upsert" and str(e.get("table") or "") == "statements"]


def _numeric_green() -> dict[str, Any]:
    """一条数值证据（`_update_numeric_evidence` 要的那份 green 读数）。"""
    return {
        "path": "reports/e-num-000001.md",
        "experiment_id": "000001",
        "code_path": "code/exp.py",
        "manuscript": {"sha256": "a" * 64},
        "experiment_row": {"code_hash": "deadbeefdeadbeef", "result": "supports"},
        "observations": {"points": 10, "range": "m<=5"},
        "params": {},
        "counterexample": False,
    }


def test_b1_a_new_row_lands_and_every_statement_upsert_is_the_secretarys(store) -> None:
    """b①：新建行 ⇒ 行落盘，`statements` 的每一次 upsert 都是 `secretary-B` 落的。"""
    add_literature(store, S.format_id(0))
    sign_before_registration(store.root, proof_text=PROOF)
    b = AgentB(store, extractor=None, extract_text=None)
    out = b.register_statement(**_payload())
    assert out.get("ok") is True, out
    sid = str(out.get("stmt_id") or "")
    assert sid, out
    row = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)
    assert row["created_by"] == "secretary-B", row.get("created_by")
    actors = {str(e.get("actor") or "") for e in _statement_upserts(store)}
    assert actors == {"secretary-B"}, (
        "有 statements 的 upsert 不是 B 的秘书落的："
        f"{actors}（B 本体对台账只读）")


def test_b2_appending_a_proof_lands_through_the_secretary(store) -> None:
    """b②：追加证明（`#p2`）⇒ 进 `proofs` 清单，那一笔 upsert 是 `secretary-B`。"""
    add_literature(store, S.format_id(0))
    sign_before_registration(store.root, proof_text=PROOF)
    b = AgentB(store, extractor=None, extract_text=None)
    out = b.register_statement(**_payload())
    assert out.get("ok") is True, out
    sid = str(out.get("stmt_id") or "")
    wrote = b._attach_proofs(sid, [{"proof_no": 2, "text": PROOF_2,
                                    "created_at": S.now_iso()}], canonical="")
    assert wrote.get("written") is True, wrote
    assert wrote.get("attached") == [2], wrote
    row = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)
    listed = [dict(p) for p in (row.get(VR.PROOFS_KEY) or [])]
    assert [int(p["proof_no"]) for p in listed] == [2], listed
    assert str(listed[0]["text"]) == PROOF_2, listed
    assert {str(e.get("actor") or "") for e in _statement_upserts(store)} == {"secretary-B"}


def test_b3_updating_the_numeric_evidence_bit_lands_through_the_secretary(store) -> None:
    """b③：更新数值证据位 ⇒ 第 1 位 `numeric=verified` + 等级现算，upsert 是 `secretary-B`。"""
    add_literature(store, S.format_id(0))
    # 起点照真机那一档：在册的普通数值猜想（自产、正文空）—— 更新的是它的第 1 位。
    sec = SEC.Secretary("B", root=store.root, store=store)
    seeded = sec.record_statement(
        dict(origin="own_result", kind="conjecture", label="椭圆无等弦点",
             statement_full=STATEMENT, statement_text="椭圆不存在等弦点", proof_text="",
             quote_verified=None, quote_reason="普通数值档还没有证明（夹具）",
             doc_id=S.format_id(0), evidence_kind="heuristic"), role="B")
    assert seeded.get("created") is True, seeded
    sid = str(seeded["stmt_id"])
    row = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)
    b = AgentB(store, extractor=None, extract_text=None)
    got = b._update_numeric_evidence(
        row=row, green=_numeric_green(), same={"why": "夹具：秘书判这一份就是在册的同一条"})
    assert got.get("ok") is True, got
    assert got.get("new_row") is False, got
    upd = dict(got.get("updated_statement") or {})
    assert upd.get("numeric") == "verified", upd
    assert upd.get("grade") == "strong_conjecture", upd
    assert upd.get("entries_after") == 1 and upd.get("entries_before") == 0, upd
    after = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)
    assert dict(after.get("bits") or {}).get("numeric") == "verified", after.get("bits")
    # 在册正文一个字都没改（这一支只更新证据位）
    assert str(after.get("statement_full") or "") == STATEMENT, after.get("statement_full")
    assert {str(e.get("actor") or "") for e in _statement_upserts(store)} == {"secretary-B"}


# ============================================================ c 负控
def test_c_without_the_secretarys_landing_nothing_is_written(store, monkeypatch) -> None:
    """c 负控：把 `land_statement` 关成"一个字都不写" ⇒ 两条写路必须不落盘。

    这一条问的是"b 的绿到底是谁给的"：如果 B 还留着一条自己写的后备路，关掉秘书之后
    那两笔照样会落盘 ⇒ 这里必红。替身与真方法同形（`(stmt_id, transition, *, op, note, role)`），
    并返回"没写"的三态；`transition` 一次都不许被它执行 —— 执行了就等于 B 自己写了。
    """
    add_literature(store, S.format_id(0))
    # 先落一条空正文的命题行（直接走秘书的登记口：这里要的是"行在、正文空"这个起点）。
    sec = SEC.Secretary("B", root=store.root, store=store)
    seeded = sec.record_statement(
        dict(origin="own_result", kind="conjecture", label="椭圆无等弦点",
             statement_full=STATEMENT, statement_text="椭圆不存在等弦点", proof_text="",
             quote_verified=None, quote_reason="证明还没做完（夹具）", doc_id=S.format_id(0),
             evidence_kind="heuristic"), role="B")
    assert seeded.get("created") is True, seeded
    sid = str(seeded["stmt_id"])
    sign_for_the_gate(store.root, statement_id=sid, proof_text=PROOF, store=store)

    called: list[str] = []

    def _no_write(self, stmt_id, transition, *, op, note="", role="B"):
        called.append(str(op))
        return {"checked": True, "written": False, "op": str(op),
                "refused": "probe_no_write",
                "reason": "探针：秘书的落盘被关掉了（这一笔不许落盘）",
                "result": {"refused": "probe_no_write",
                           "reason": "探针：秘书的落盘被关掉了"}}

    monkeypatch.setattr(SEC.Secretary, "land_statement", _no_write, raising=True)
    b = AgentB(store, extractor=None, extract_text=None)
    from agentflow import evidencebits as EB

    bits = EB.bits_of(origin="own_result", proof=True, proof_process=PROOF, kind="conjecture")
    wrote = b._attach_proofs(sid, [{"proof_no": 2, "text": PROOF_2,
                                    "created_at": S.now_iso()}],
                             canonical=PROOF, bits=bits)
    assert called and set(called) == {"attach_proofs"}, called
    assert wrote.get("written") is not True, wrote
    row = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)
    assert str(row.get("proof_text") or "") == "", (
        "秘书的落盘关掉了，B 还是把正文写进去了 —— 存在'B 自己写'的后备路")
    assert not list(row.get(VR.PROOFS_KEY) or []), row.get(VR.PROOFS_KEY)

    # 第二条写路（数值证据位）同一条判据：关掉之后五元位一个字节都不动。
    before_bits = dict(row.get("bits") or {})
    got = b._update_numeric_evidence(
        row=dict(row), green=_numeric_green(), same={"why": "夹具：同一条"})
    assert "numeric_evidence" in called, called
    assert got.get("ok") is not True, got
    after = next(dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid)
    assert dict(after.get("bits") or {}) == before_bits, (before_bits, after.get("bits"))


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
