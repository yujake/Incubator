# -*- coding: utf-8 -*-
"""判据：B 的二阶段（逐个优化）是自驱的 —— 快录交回那一刻它自己就开稿洗，不等 M 派。

## 业主裁定（2026-11-21，逐字）

    B 应该自动做，而不是 M 派。

真机 `projects/lp-ball-15` 的现场（只读取证，2026-11-21 15:0x）：
B 的 `own.run_once` 19 次、`own.register_statement` 19 次，而 `own.open_polish_copy`
0 次 —— 每一趟 B 的委托都只写「第一阶段快录」，回执也以「快录完成」收尾；
在册的 3 条带证明命题（`stmt:000125/000127/000130`，`proof_source=citation`）
`optimized_by_proof` 全是 `{"1": false}`。写「主职是第二阶段」的那一句只是描述，
不是动作：B 没有在"本委托只做快录"之后跨过去。

## 这一份钉什么（a / b / c / d，每条都能单独红）

| # | 判据 | 反真空 / 改前读数 |
|---|---|---|
| a | 夹具：「B 刚快录完一批、其中 1 条带证明未优化、文献队列已空」⇒ `run_once` 自己开出一份 `reports/b-proof-*.md`，回执 `stage_two.unwashed` 点名 `stmt_id` | 反真空 c：把自驱打桩成关 ⇒ 一份都不开、盘上不新增；改前：真机 19 次 `run_once` 0 次 `open_polish_copy` |
| b | 正控：把洗过的正文（带覆盖它的一签）交回 ⇒ 该份 `optimized_by_proof[1]=true`、`proof_history` 里有旧正文 | —— |
| c | 反真空：`_stage_two_self_drive_enabled()` 打桩成 False ⇒ a 的"开了稿"必须红（欠账仍点名，证明"点名"不是"开稿"） | —— |
| d | B 的渲染产物里，「快录完接着洗」是动作：`stage_two.unwashed` / `own.open_polish_copy` / 「不必等 M 派」三个锚点齐 | d2：把那一句从渲染产物里抠掉 ⇒ 同一个读法必红（"主职"那种描述顶不上） |

零模型调用：不开稿以外的写盘只发生在夹具；洗稿那一步在 b 里由夹具直接给出正文
（真机上那一步是 B 的 `fs.edit`，本判据不量文本判断的质量）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest  # noqa: E402

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptform as MF  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_v import AgentV  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

from test_agent_v_exhaustion_review import _v_secretary  # noqa: E402
from test_v_reviews_three_times_before_signing import CLEAN_REPLY, _ReviewSeam  # noqa: E402

TASK_ID = "t-000001"
FULL = "命题（夹具）：对任意正整数 n≥3，弦长函数不是常值。"
OLD = "1. 原证明：由定义直接得到。\n2. 结论成立。"
WASHED = ("1. 先把假设写全：n≥3、G 是 3-正则群。\n"
          "2. 再走一步：由定义得弦长函数在 n≥3 时取至少两个值。\n"
          "3. 结论：弦长函数不是常值。")


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    """一条带证明的定理（`optimized` 记着 false）+ B 自己的任务行。

    文献队列故意为空：这一格量的是"这一批快录完了、证明已在册"之后 B 自己动不动手。
    """
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    row = conftest.seed_statement_row(
        st, stmt_id="000000", kind="theorem", origin="own_result",
        statement_full=FULL, proof_text=OLD)
    bits = dict(row.get("bits") or {})
    ev = dict(bits.get("evidence") or {})
    ev[EB.OPTIMIZED_BY_PROOF_KEY] = {"1": False}
    ev["proof_source"] = "own"
    bits["evidence"] = ev
    with st.tx("statements", actor="test") as tx:
        cur = dict(next(r for r in st.rows("statements")
                        if str(r.get("stmt_id")) == "000000"))
        cur["bits"] = EB.normalize_raw(bits, origin="own_result", kind="theorem")
        tx.upsert("statements", cur)
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", S.Task(
            task_id=TASK_ID, role="B", action="run_once", called_by="user",
            status="running", input_key="B.run_once",
            detail="夹具：B 自己的循环（快录完这一批）",
            started_at=conftest.TS).to_dict())
    return st


def _agent(st: Store) -> AgentB:
    return conftest.b_form_gate_ok(AgentB(st, extractor=None, extract_text=None, config={}))


def _once(st: Store):
    with CND.calling_as(TASK_ID, "B"):
        return _agent(st).run_once()


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _row(st: Store) -> dict:
    return next(r for r in _rows(st) if str(r.get("stmt_id")) == "000000")


def _copies(st: Store) -> list[str]:
    return sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("b-proof-*.md"))


# ============================================================ a 自驱开稿
def test_a_run_once_opens_the_polish_copy_without_being_told(tmp_path: pathlib.Path) -> None:
    """a：文献队列空、还有一条带证明未优化 ⇒ `run_once` 自己开一份 B 号优化稿。"""
    st = _ws(tmp_path)
    got = _once(st)

    stage_two = dict(got.stage_two or {})
    assert stage_two.get("checked") is True, stage_two
    assert stage_two.get("enabled") is True, stage_two
    # 回执点名「这批还有哪几条没洗」—— 不是"报给 M 等派"，是 B 自己每一拍都读得到的读数。
    assert int(stage_two.get("unwashed_count") or 0) == 1, stage_two
    assert [one["stmt_id"] for one in stage_two["unwashed"]] == ["000000"], stage_two
    assert stage_two["unwashed"][0]["unoptimized_proofs"] == [1], stage_two

    # 动作那一半：自己把稿开出来了（写盘只在 open_polish_copy 的四步里）。
    assert [one["stmt_id"] for one in (stage_two.get("opened") or [])
            if one.get("ok")] == ["000000"], stage_two
    files = _copies(st)
    assert len(files) == 1, (files, stage_two)
    text = (pathlib.Path(st.root) / "reports" / files[0]).read_text(encoding="utf-8")
    assert "## 证明" in text and OLD in text, text[:600]
    assert "- V 签：" not in text, text.splitlines()[:8]
    # 副本的来历记在 tasks.artifacts 上（幂等的唯一依据；下一拍不会重复开）。
    row = next(dict(r) for r in st.rows("tasks") if str(r.get("task_id")) == TASK_ID)
    assert any("kind=polish" in str(tok) for tok in (row.get("artifacts") or [])), (
        row.get("artifacts"))
    assert stage_two.get("next_action"), stage_two


def test_a_the_second_tick_does_not_open_a_second_copy(tmp_path: pathlib.Path) -> None:
    """a 的幂等那一半：同一批再跑一拍 ⇒ 不再开第二份（`skipped_open` 点名它）。"""
    st = _ws(tmp_path)
    first = _once(st)
    assert len(_copies(st)) == 1, _copies(st)
    second = _once(st)
    stage_two = dict(second.stage_two or {})
    assert stage_two.get("checked") is True, stage_two
    assert stage_two.get("opened") == [], stage_two
    # 开过的那一份由 `tasks.artifacts` 的来源记录认出来（幂等的唯一依据）。
    assert stage_two["unwashed"][0]["opened"] is True, stage_two
    assert len(_copies(st)) == 1, _copies(st)
    # 欠账照旧点名：开过稿不等于洗过。
    assert int(stage_two.get("unwashed_count") or 0) == 1, stage_two


# ============================================================ b 洗 → 替换 → optimized
def test_b_a_signed_washed_body_replaces_and_marks_optimized(
        tmp_path: pathlib.Path) -> None:
    """b 正控：洗过的正文（有覆盖它的一签）交回 ⇒ true + 旧正文进 `proof_history`。"""
    st = _ws(tmp_path)
    _once(st)
    assert _copies(st), "夹具前提：a 那一笔没开出优化稿，b 就没有可洗的副本"
    copy_rel = f"reports/{_copies(st)[0]}"

    # 夹具代替 B 的 `fs.edit`：把副本正文换成洗过的那一版（真机上这一步是模型的文本判断）。
    washed_text = MF.render_proof_manuscript(
        "B", proposition=FULL, proof_text=WASHED, label="弦长函数不是常值")
    (pathlib.Path(st.root) / copy_rel).write_text(washed_text, encoding="utf-8")

    # 洗完之后重拿 V 签（零模型：剧本回三转「成立」；签块由收方秘书落回副本）。
    seam = _ReviewSeam([CLEAN_REPLY])
    v = AgentV(st, workspace_root=st.root, llm=seam, secretary=_v_secretary(st))
    with CND.calling_as("t-v-000001", "V", parent_task_id=TASK_ID, parent_role="B"):
        signed = v.verify_proof(statement_id="000000", proof_manuscript=copy_rel)
    assert signed.get("checked") is True, signed
    assert seam.asked() == int(VR.SIGN_STREAK_NEED), seam.asked()
    signed_text = (pathlib.Path(st.root) / copy_rel).read_text(encoding="utf-8")
    block = VS.manuscript_sign_reading(signed_text, manuscript_path=copy_rel)
    assert block.get("signed") is True, block
    assert block.get("signer") == "secretary:B", block

    # 带这份已签副本交回 ⇒ 精准替换（旧正文进 proof_history、optimized 记 true）。
    filed = _agent(st).register_statement(
        origin="own_result", derived_from=["999999"], kind="theorem",
        statement_full=FULL, statement_text="弦长函数不是常值",
        proof_text=WASHED, proof_manuscript=copy_rel,
        doc_id=S.format_id(0), line_range={"start": 1},
        quote_verified=False, quote_reason="own_result：夹具代替洗稿")
    assert filed.get("ok") is True, filed

    row = _row(st)
    assert str(row.get("proof_text") or "") == WASHED, row.get("proof_text")
    assert EB.optimized_by_proof(row) == {1: True}, row.get("bits")
    assert EB.optimized_state(row, 1) == "true", row.get("bits")
    history = [dict(h) for h in (row.get("proof_history") or [])]
    assert history, "旧正文没有进 proof_history ⇒ 不是精准替换"
    assert str(history[-1].get("text") or "") == OLD, history[-1]
    # 反真空的前提：b 的 true 来自"这一版有签"，不是来自"交了一次正文"。
    bare = dict(row)
    bare_bits = dict(bare.get("bits") or {})
    ev = dict(bare_bits.get("evidence") or {})
    ev.pop(EB.REVIEWED_BY_PROOF_KEY, None)
    ev.pop(EB.REVIEWED_SHA_BY_PROOF_KEY, None)
    bare_bits["evidence"] = ev
    bare["bits"] = bare_bits
    assert EB.optimized_state(bare, 1) != "true", (
        "把覆盖这一版的签拆掉之后 optimized 仍读成 true ⇒ b 的 true 不是签给的")


# ============================================================ c 反真空
def test_c_stubbing_the_self_drive_out_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：把自驱那一步打桩成关 ⇒ 一份稿都不开（"自己开了稿"不是恒真读数）。"""
    from agentflow.agent_b.stage_two import _StageTwoSelfDrive

    st = _ws(tmp_path)
    monkeypatch.setattr(_StageTwoSelfDrive, "_stage_two_self_drive_enabled",
                        staticmethod(lambda: False))
    got = _once(st)
    stage_two = dict(got.stage_two or {})
    assert stage_two.get("checked") is True, stage_two
    assert stage_two.get("enabled") is False, stage_two
    # 关掉的是"动作"，不是"读数"：欠账照旧逐条点名 —— 两个读数必须分开。
    assert int(stage_two.get("unwashed_count") or 0) == 1, stage_two
    assert stage_two.get("opened") == [], stage_two
    assert _copies(st) == [], "自驱被打桩成关之后仍然开了稿 ⇒ a 的读数不是这条自驱给的"


# ============================================================ d 提示词面：动作，不是描述
#: 「快录完接着洗」必须是动作：三个锚点缺一不可（少一个都只是描述）。
SELF_DRIVE_NEEDLES: tuple[str, ...] = (
    "stage_two.unwashed",
    "own.open_polish_copy",
    "不必等 M 派",
)


def _prompt(role: str = "B") -> str:
    return AP.system_prompt(role, registry=build_registry().registry,
                            task="把这一批快录完，接着洗", workspace_root="D:/x")


def _self_drive_gaps(text: str) -> list[str]:
    """d 的读法：同一行里三个锚点齐不齐（空 = 齐）。

    为什么要求同一行：分开出现在三段里就是"描述"（职责一句、工具摘要一句、手册索引
    一句），而 B 停在快录的那一刻读到的正是这种分散的描述。动作必须是一句可照做的话。
    """
    for line in str(text).splitlines():
        if all(needle in line for needle in SELF_DRIVE_NEEDLES):
            return []
    return [f"没有一条同时含 {SELF_DRIVE_NEEDLES} 的自驱动作（分散的描述不算动作）"]


def test_d_the_prompt_carries_the_self_drive_as_an_action() -> None:
    """d：B 的渲染产物里有一句同时含自驱三个锚点的动作。"""
    text = _prompt()
    assert text, "B 的提示词渲染成空串 ⇒ 这一条没有落脚点"
    gaps = _self_drive_gaps(text)
    assert gaps == [], f"B 的渲染产物缺这几处自驱锚点：{gaps}"


def test_d2_a_description_without_the_action_is_not_enough() -> None:
    """d2 反真空：把自驱那一句从渲染产物里抠掉 ⇒ 同一个读法必红。

    抠掉的不是整段 policy，只是"动作"那一句：剩下的「主职是第二阶段（逐个优化）」
    仍然在（真机 lp-ball-15 的 B 读到的正是这种描述，然后停在快录）。
    """
    text = _prompt()
    kept = [line for line in text.splitlines()
            if not all(needle in line for needle in SELF_DRIVE_NEEDLES)]
    stubbed = "\n".join(kept)
    assert stubbed != text, "夹具前提不成立：渲染产物里没有可抠的那一句自驱动作"
    assert _self_drive_gaps(stubbed), "抠掉自驱那一句之后检查器仍判绿 ⇒ d 是橡皮图章"
    # 描述还在也不算够 —— 这一条量的就是"描述顶不上动作"。
    assert "主职是第二阶段" in stubbed or "二阶段（逐个优化）" in stubbed, (
        "夹具前提不成立：抠掉之后连描述都不在了，量的不是'描述顶不上'")
