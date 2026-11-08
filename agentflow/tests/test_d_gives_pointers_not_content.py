# -*- coding: utf-8 -*-
"""块甲：D 对命题台账只读 —— 交稿只递指针，正文由 B 从手稿里读。

业主原话（2026-11-08，逐字）：

> 「D对命题台账只有只读权限，D向B提交要登记的命题时都是有证明或数值实验的
>   （即E和F的成果）…B侧做好适配（应该在手稿里找命题和数值实验程序，不录入其它内容）」

## 判据（先红后绿）

| # | 判据 | 改前为什么红 |
|---|---|---|
| a1 | D 在 `calling_as(role="D")` 下只给 `proof_manuscript=<路径>` ⇒ B 收下；落盘那一行的 `statement_full` / `proof_text` 与手稿 `## 命题` / `## 证明` 逐字相同，且只落一行 | 改前 D 把正文抄进参数；没有"按手稿路径收录"这条形态（`statement_full` 是必填，B 不会自己从稿里读） |
| a2 | 同一形态下 D 再传 `statement_full` / `proof_text` / `kind` / `evidence_kind` ⇒ 受控拒 `d_gives_manuscript_pointers_only`，拒信逐字点名「只递指针」，且 `statements` 一行都不落 | 改前 D 就是这样交的，B 照收 |
| a3 | 反真空：把「调用方是 D」那一格摘掉 ⇒ a2 的同一笔被照收（证明 a2 的红真的来自那道闸，不是"恰好参数不对"） | 没有那道闸 |

全部用例在 `tmp_path` 里自建工作区；签是 `conftest.sign_before_registration` 落的真
pending 台账（改一个字就认不到）⇒ 零模型调用。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from conftest import sign_before_registration  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

MANUSCRIPT = "reports/f-proof-000000.md"
PROPOSITION = "对任意有限群 G，若 |G| = p^a·m 且 p∤m，则 G 有 p 阶元。"
PROOF = ("1. 取 G 的一个 Sylow p-子群 P（二阶 Sylow 定理）。\n"
         "2. |P| = p^a > 1 ⇒ 取 1 ≠ x ∈ P，由拉格朗日定理 ord(x) 是 p 的幂。\n"
         "3. 结论：x 的某个幂就是 p 阶元。")


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
    return {"store": st, "b": AgentB(st, extractor=None, extract_text=None, config={}),
            "text": text}


def _as_d(task_id: str = "t-d-000001"):
    return CND.calling_as(task_id, "D", parent_task_id="t-m-000001", parent_role="M")


def _rows(env: dict) -> list[dict]:
    return [dict(r) for r in env["store"].rows("statements")]


# ============================================================ a1 只递指针 ⇒ 收成一行
def test_a1_d_hands_only_a_pointer_and_b_reads_the_manuscript(
        tmp_path: pathlib.Path) -> None:
    """a1：D 只给路径 ⇒ B 从稿里读命题 / 证明；落盘那一行与稿逐字相同。"""
    env = _workspace(tmp_path)
    with _as_d():
        got = env["b"].register_statement(proof_manuscript=MANUSCRIPT)
    assert got.get("ok") is True, got
    rows = _rows(env)
    assert len(rows) == 1, f"应当只落一行，读到 {len(rows)}：{rows}"
    row = rows[0]
    assert row["statement_full"] == PROPOSITION, (
        "B 落盘的 statement_full 与手稿 `## 命题` 不是逐字相同：\n"
        f"盘上 {row['statement_full']!r}\n稿里 {PROPOSITION!r}")
    assert row["proof_text"] == PROOF, (
        "B 落盘的 proof_text 与手稿 `## 证明` 不是逐字相同：\n"
        f"盘上 {row['proof_text']!r}\n稿里 {PROOF!r}")
    pointer = dict(got.get("pointer") or {})
    assert pointer.get("d_gave_only_pointers") is True, pointer
    assert pointer.get("path") == MANUSCRIPT, pointer
    assert pointer.get("proposition_source") == "manuscript", pointer


# ============================================================ a2 D 传正文 ⇒ 受控拒
def test_a2_d_passing_content_is_refused_with_a_named_reason(
        tmp_path: pathlib.Path) -> None:
    """a2：D 传正文 ⇒ 受控拒；拒信逐字点名「只递指针」；一个字节都不写。"""
    env = _workspace(tmp_path)
    before = _rows(env)
    with _as_d():
        got = env["b"].register_statement(
            proof_manuscript=MANUSCRIPT,
            statement_full=PROPOSITION,
            proof_text=PROOF,
            kind="theorem",
            evidence_kind="proof",
        )
    assert got.get("ok") is False, got
    assert got.get("refusal_reason") == "invalid_params", got
    assert got.get("kind") == "d_gives_manuscript_pointers_only", got
    error = str(got.get("error") or "")
    assert "只递指针" in error, error
    assert "命题正文" in error and "证明正文" in error, error
    assert "B 从手稿里读" in error, error
    assert _rows(env) == before, "被拒的这一笔居然写了 statements"


# ============================================================ a3 反真空：摘掉那道闸
def test_a3_without_the_d_check_the_content_is_accepted(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a3：把「调用方是 D」那一格摘掉 ⇒ 同一笔正文照旧被收（a2 的绿真的来自它）。

    摘的是判据入口 `agent_b.register_statement._caller_is_d`（唯一一处"谁是 D"），
    摘掉之后这一笔退回改前的正文登记路 —— 参数本身是合法的，所以它会被收下。
    """
    import agentflow.agent_b.register_statement as RS

    env = _workspace(tmp_path)
    monkeypatch.setattr(RS, "_caller_is_d", lambda: False)
    with _as_d():
        got = env["b"].register_statement(
            proof_manuscript=MANUSCRIPT,
            statement_full=PROPOSITION,
            proof_text=PROOF,
            kind="conjecture",
            evidence_kind="heuristic",
            origin="own_result",
            quote_reason="夹具：我方自产命题，引文面不适用",
            line_range={"label": MANUSCRIPT},
        )
    assert got.get("ok") is True, got
    assert got.get("kind") != "d_gives_manuscript_pointers_only", got


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
