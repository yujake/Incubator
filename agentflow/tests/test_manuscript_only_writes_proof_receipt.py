# -*- coding: utf-8 -*-
"""缺陷 ③：只给手稿时 `proof_no` / `proof_sha256` 必须真的落到 statements 顶层；
普通数值档（e-num）没有证明 ⇒ 不写 `proof_no`，并显式给 `has_proof=false`。

## 走查读数（改前红）

- 只给 `proof_manuscript`、`proof_text` 入参为空时：正文由 B 从稿里读，落进了
  `statements.proof_text`，而顶层 `proof_no` / `proof_sha256` 一个字节都没写
  （盘上 null）；返回值与 `_grade_recomputed` 却说"第 1 份证明"。
- `e-num` 通道：返回 `proof_no=1`，而这一行 `bits.proof=false`、`proof_text=""`
  ⇒ 没有证明却读出"第 1 份证明"。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 只递指针（`statement_full=""`）⇒ 盘上 `proof_no=1`、`proof_sha256` == 手稿 `## 证明` 正文的现算 sha；返回值同 | 顶层两格不写（null） |
| b | 只给 `proof_manuscript`（命题正文由参数给）⇒ 同样写顶层两格 | 同上；`_needs_proof` 为假时回执从不写 |
| c | e-num 普通数值档 ⇒ 盘上不写 `proof_no`、`proof_text=""`、`bits.proof=false`；返回值 `has_proof=false` / `proof_no=0` / `proof_sha256=""` | 改前返回 `proof_no=1`（没有证明却有"第 1 份"） |
| d | 反真空：把回执那一笔摘掉（打桩 `_attach_proofs` 抹掉 receipt 与两格）⇒ a 的盘上两格又变空（红） | 证明 a/b 的绿真的来自那一笔写入 |

零模型调用：签是 `conftest.sign_before_registration` 落的真 pending 台账（改一个字
就认不到）；e-num 走 E 的机器通道，不碰网络。
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import seed_proposition_form_ok, sign_before_registration  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402

MANUSCRIPT = "reports/f-proof-000000.md"
PROPOSITION = "对任意有限群 G，若 |G| = p^a·m 且 p∤m，则 G 有 p 阶元。"
PROOF = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
         "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。\n"
         "3. 结论：x 的某个幂就是 p 阶元。")
CLAIM = "设 n<=10，则 P(n) 对 n=1..10 都成立。"


def _workspace(tmp_path: pathlib.Path) -> dict:
    st = Store(tmp_path / "ws")
    st.init()
    deps = DS.render_dependency_section([])
    text = (
        "# F 的证明手稿：p 阶元\n\n"
        "- 依赖面洗稿：已洗=true；执行者=secretary:F\n\n"
        f"## 命题\n\n{PROPOSITION}\n\n"
        f"## 证明\n\n{PROOF}\n\n" + deps)
    target = pathlib.Path(st.root) / MANUSCRIPT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    sign_before_registration(st.root, proof_text=PROOF)
    return {"store": st,
            "b": AgentB(st, extractor=None, extract_text=None, config={})}


def _rows(env: dict) -> list[dict]:
    return [dict(r) for r in env["store"].rows("statements")]


# ============================================================ a 只递指针
def test_a_pointer_only_writes_the_proof_receipt_on_disk(tmp_path) -> None:
    """a：只给手稿 ⇒ 顶层 `proof_no` / `proof_sha256` 与真实正文一致。"""
    env = _workspace(tmp_path)
    got = env["b"].register_statement(statement_full="",
                                      proof_manuscript=MANUSCRIPT)
    assert got.get("ok") is True, got
    rows = _rows(env)
    assert len(rows) == 1, rows
    row = rows[0]
    want_sha = VR.proof_sha(PROOF)
    assert int(row.get("proof_no") or 0) == 1, row.get("proof_no")
    assert str(row.get("proof_sha256") or "") == want_sha, (
        "盘上 proof_sha256 与手稿 `## 证明` 正文的现算 sha 不一致："
        f"{row.get('proof_sha256')!r} != {want_sha!r}")
    assert got.get("has_proof") is True, got.get("has_proof")
    assert int(got.get("proof_no") or 0) == 1, got.get("proof_no")
    assert str(got.get("proof_sha256") or "") == want_sha, got.get("proof_sha256")


# ============================================================ b 正文由参数给
def test_b_manuscript_only_also_writes_the_receipt(tmp_path) -> None:
    """b：`proof_text` 入参为空、只给手稿路径 ⇒ 顶层两格照样写。"""
    env = _workspace(tmp_path)
    got = env["b"].register_statement(
        statement_full=PROPOSITION, proof_manuscript=MANUSCRIPT,
        kind="conjecture", origin="own_result", evidence_kind="heuristic",
        line_range={"label": MANUSCRIPT},
        quote_verified=False, quote_reason="own_result：F 的证明稿")
    assert got.get("ok") is True, got
    row = _rows(env)[0]
    assert int(row.get("proof_no") or 0) == 1, row.get("proof_no")
    assert str(row.get("proof_sha256") or "") == VR.proof_sha(PROOF), row


# ============================================================ c e-num 不谎报
def _numeric(store: Store, claim: str, key: str, script: str) -> dict:
    body = ("import json\nprint('REPRO_RESULT: ' + json.dumps({"
            "'result': 'supports', 'evidence_kind': 'cross_check', "
            "'observations': {'range': 'n<=10', 'points': 10}, "
            "'counterexample': None, 'negation_kind': 'not_proved'}))\n")
    path = pathlib.Path(store.root) / script
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return AgentE(store, config={}, workspace_root=store.root).run_experiment(
        claim, key, script, method="numeric")


def test_c_a_plain_numeric_row_has_no_proof_number(tmp_path) -> None:
    """c：e-num ⇒ 盘上不写 `proof_no`，并给 `has_proof=false` 的显式读数。"""
    st = Store(tmp_path / "num")
    st.init()
    out = _numeric(st, CLAIM, "k1", "code/scan.py")
    seed_proposition_form_ok(st.root, CLAIM, kind="conjecture", role="B")
    b = AgentB(st, extractor=None, extract_text=None, config={})
    got = b.register_statement(
        origin="own_result", kind="conjecture", label="scan",
        statement_full="", statement_text="", proof_text="",
        evidence_kind="cross_check", proof_manuscript=out["numeric_manuscript"],
        quote_verified=False, quote_reason="own_result：E 的实验读数")
    assert got.get("ok") is True, got
    row = [dict(r) for r in st.rows("statements")][0]
    assert row["proof_text"] == "", row["proof_text"]
    assert dict(row.get("bits") or {}).get("proof") is False, row.get("bits")
    assert not row.get("proof_no"), f"没有证明却写了 proof_no={row.get('proof_no')!r}"
    assert not row.get("proof_sha256"), row.get("proof_sha256")
    assert got.get("has_proof") is False, got.get("has_proof")
    assert int(got.get("proof_no") or 0) == 0, got.get("proof_no")
    assert str(got.get("proof_sha256") or "") == "", got.get("proof_sha256")


# ============================================================ d 反真空
def test_d_without_the_receipt_write_the_pointer_row_has_no_proof_number(
        tmp_path, monkeypatch) -> None:
    """d：把回执那一笔摘掉 ⇒ a 的盘上两格又变空（a/b 的绿依赖它）。

    打桩点取"写盘前那一格"（`Secretary.land_statement`）：它把 `transition` 交来的
    行原样写盘。这里把 `proof_no` / `proof_sha256` 从要写的那一行里拿掉 ——
    正是改前"顶层不写"的形态；若 a/b 仍然绿，说明那两格不是这一笔写的。
    """
    import agentflow.secretary as SEC

    real = SEC.Secretary.land_statement

    def _strip(self, stmt_id, transition, **kwargs):
        def _inner(row):
            got = transition(row)
            if isinstance(got, dict) and isinstance(got.get("row"), dict):
                stripped = dict(got["row"])
                stripped.pop("proof_no", None)
                stripped.pop("proof_sha256", None)
                got = dict(got)
                got["row"] = stripped
            return got

        return real(self, stmt_id, _inner, **kwargs)

    monkeypatch.setattr(SEC.Secretary, "land_statement", _strip)
    env = _workspace(tmp_path)
    got = env["b"].register_statement(statement_full="",
                                      proof_manuscript=MANUSCRIPT)
    assert got.get("ok") is True, got
    row = _rows(env)[0]
    assert not row.get("proof_no"), (
        "反真空失效：摘掉回执写入之后盘上仍有 proof_no", json.dumps(row))
    assert not row.get("proof_sha256"), row


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
