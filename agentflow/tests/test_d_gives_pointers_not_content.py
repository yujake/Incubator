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
| a4 | B 自己那一趟、父是 D 时登记自己的成果（`proof_manuscript` + 来路格）⇒ 收下，不再命中 D 闸 | `_caller_is_d()` 读了父角色 ⇒ B 自己的登记被判成「D 交稿」（真机 `projects/lp-ball-6` 的 `t-000064`，父 `t-000009` 是 D；6 次正面拒，见 `temp/inv2/REPORT.md` §2.2） |
| a5 | 负控：与 a4 同一笔调用、身份换成真 D（D 自己的 run，父是 M）⇒ 仍受控拒 `d_gives_manuscript_pointers_only`，零行 | 这一档改前就成立；它的作用是把"改后不许松"钉住（D 的直调在 `agent_d.write_report`） |
| a6 | 反真空：把「真调用方」那一格打回「父角色」（改前那一版判据）⇒ a4 的同一笔必被拒 | 同 a4（打回之后就是改前的形态） |

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

from conftest import b_form_gate_ok, sign_before_registration  # noqa: E402
# a1 / a4 / a5 / a6 会接一次"同一命题"那一问的离线替身（否则 fail-closed 会顶在
# 这道闸前面）：这一行是那四条的依赖，本路（INV2①）保留它。
from _same_statement_stub import wire_for_secretary  # noqa: E402
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
    return {"store": st,
            "b": b_form_gate_ok(AgentB(st, extractor=None, extract_text=None,
                                       config={})),
            "text": text}


def _as_d(task_id: str = "t-d-000001"):
    return CND.calling_as(task_id, "D", parent_task_id="t-m-000001", parent_role="M")


#: 真机 `projects/lp-ball-6` 的形态：B1 那一趟是 `t-000064`，它的父 `t-000009` 是 D。
B_TASK, D_PARENT = "t-b-000064", "t-d-000009"


def _as_b_summoned_by_d():
    """B 自己那一趟，父是 D（两个身份格各按现场写：我是 B，派我来的是 D）。"""
    return CND.calling_as(B_TASK, "B", parent_task_id=D_PARENT, parent_role="D")


def _own_result_kwargs(env: dict) -> dict:
    """B 登记"我自己从稿里读到的成果"这一笔的参数（形状逐字取 a3 那一笔）。

    刻意带着 `proof_manuscript` 与内容格（`statement_full` / `proof_text` /
    `kind` / `origin`）：真机上被误拒的就是这一形（闸 A 的
    `_POINTER_ONLY_BODY_FIELDS` 全在里面）。`derived_from` / `source_lit_id` 是可选
    信息（业主 2026-11-17：`origin` 只是状态），这一笔不测来路，所以不给。
    """
    return {"proof_manuscript": MANUSCRIPT,
            "statement_full": PROPOSITION,
            "proof_text": PROOF,
            "kind": "conjecture",
            "evidence_kind": "heuristic",
            "origin": "own_result",
            "quote_reason": "夹具：我方自产命题，引文面不适用",
            "line_range": {"label": MANUSCRIPT}}


def _caller_is_d_reading_the_parent_role_again() -> bool:
    """改前那一版判据（2026-11-17 INV2 钉死之前的实现，逐字：真调用方 ∪ 父角色）。

    只在本文件里存在：a6 用它把"看父不看自己"那一格重新装回去，证明 a4 的绿真的
    来自"只读真调用方"，而不是那一笔恰好参数合法。
    """
    import agentflow.agent_b.register_statement as RS

    roles = {str(CND.current_caller_role() or ""), str(RS._caller_role() or "")}
    return "D" in roles


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
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
            origin="own_result", derived_from=["999999"],
            quote_reason="夹具：我方自产命题，引文面不适用",
            line_range={"label": MANUSCRIPT},
        )
    assert got.get("ok") is True, got
    assert got.get("kind") != "d_gives_manuscript_pointers_only", got


# ============================================ a4 B 被 D 派来 ⇒ 不是"D 在交稿"（INV2 ①）
def test_a4_a_b_summoned_by_d_may_register_its_own_result(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a4：B 自己那一趟、父是 D ⇒ 它登记自己的成果不再命中 D 闸。

    改前红（真机 `projects/lp-ball-6` 19:43:44–19:50:42，`temp/inv2/REPORT.md` §2.2）：
    `_caller_is_d()` 读的是父角色 ⇒ B1（`t-000064`，父 `t-000009` 是 D）在自己的
    run 里带 `proof_manuscript` + 来路格登记，被判成「D 交稿」，6 次正面拒
    `d_gives_manuscript_pointers_only`，`statements` 一行没落。
    """
    wire_for_secretary(monkeypatch)
    env = _workspace(tmp_path)
    with _as_b_summoned_by_d():
        got = env["b"].register_statement(**_own_result_kwargs(env))
    assert got.get("ok") is True, got
    assert got.get("kind") != "d_gives_manuscript_pointers_only", got
    rows = _rows(env)
    assert len(rows) == 1, f"这一笔应当真落一行，读到 {len(rows)}：{rows}"


# ==================================== a5 负控：真 D 交同一笔仍拒（一个字都不许松）
def test_a5_the_real_d_is_still_refused_on_the_same_call(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a5：与 a4 逐字同一笔调用，身份换成真 D（D 自己的 run，父是 M）⇒ 仍拒。

    这是"不许放宽"那一半：`agent_d/write_report.py` 直调 `B.register_statement(...)`
    跑的就是这一档（`calling_as(role="D")`）。
    """
    wire_for_secretary(monkeypatch)
    env = _workspace(tmp_path)
    before = _rows(env)
    with _as_d():
        got = env["b"].register_statement(**_own_result_kwargs(env))
    assert got.get("ok") is False, got
    assert got.get("kind") == "d_gives_manuscript_pointers_only", got
    assert _rows(env) == before, "被 D 指针闸拒掉的这一笔居然写了 statements"


# ==================================== a6 反真空：把"真调用方"打回"父角色"⇒ a4 必红
def test_a6_reading_the_parent_role_again_makes_a4_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a6：把「真调用方」这一格打回「父角色」（改前那一版）⇒ a4 的同一笔必被拒。

    没有这一条时，a4 可能靠"这一笔恰好参数合法"变绿 —— 那测的就不是"判据读谁"。
    ① 不动判据 ⇒ 收下（证明这一笔本来能过，绿不是假的）；
    ② 装回父角色那一格 ⇒ 同一笔必红（与真机那 6 次拒逐字同一个码）。
    """
    wire_for_secretary(monkeypatch)
    import agentflow.agent_b.register_statement as RS

    green = _workspace(tmp_path / "green")
    with _as_b_summoned_by_d():
        ok_got = green["b"].register_statement(**_own_result_kwargs(green))
    assert ok_got.get("ok") is True, ("① 不动判据时这一笔必须被收下：", ok_got)

    monkeypatch.setattr(RS, "_caller_is_d",
                        _caller_is_d_reading_the_parent_role_again)
    red = _workspace(tmp_path / "red")
    before = _rows(red)
    with _as_b_summoned_by_d():
        refused = red["b"].register_statement(**_own_result_kwargs(red))
    assert refused.get("ok") is False, ("② 打回父角色之后必须被拒：", refused)
    assert refused.get("kind") == "d_gives_manuscript_pointers_only", refused
    assert _rows(red) == before, "被拒的这一笔居然写了 statements"


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))