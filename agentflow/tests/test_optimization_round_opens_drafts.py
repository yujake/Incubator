# -*- coding: utf-8 -*-
"""判据：优化轮按未优化清单批量开稿（一次调用），并附上按 kind 分派的提示词。

## 业主口径（2026-11-14，逐字）

> 「对于优化侧，系统取未优化的命题号及相关信息、命题类型、原证明稿，自动注册
>  B 侧稿号并给出初始稿（就是原证明稿的复制版），针对不同命题类型给 B 发送定制的
>  优化提示词（定理类、穷举证明类等可参考对应的 F、E 侧提示词并结合优化目标调整，
>  良定义类需再做设计）。」

## 这一份钉什么（每条都能单独红）

| # | 判据 | 反真空 |
|---|---|---|
| a | 正控：有原稿的定理（源稿没签）⇒ 批量开 1 份 B 号稿，`source_sign="unsigned"`、初始稿 = 原证明正文的复制 | 把 `_optimization_round_enabled` 打成假 ⇒ 一份都不开、盘上不新增 |
| b | 负控：没有原稿的概念 ⇒ 不开（`skipped_no_draft`），且 `next_step` 指向"先落 b-稿" | 给它塞一份正文 ⇒ 它立刻变成开得出来的那一条 |
| c | 幂等：同一轮跑两次 ⇒ 第二次 `opened=0`、`skipped_open` 点名已开的那一份，盘上不新增 | 摘掉来源记录 ⇒ 第二次又开一份（证明 `skipped_open` 量的是记录） |
| d | 提示词分派：theorem / exhaustive 两档 `status="ready"` 且有正文；`well_defined` 是 `draft_pending` 且 `prompt==""`（业主：良定义类需再做设计） | 把 well_defined 塞一句 F 侧的话 ⇒ 红 |
| e | 词表只有一处：`closing.OPTIMIZATION_PROMPT_CLASSES` 与注册表的 `PROMPT_CLASSES` 逐字相同 | — |

全部 tmp 工作区、零模型调用，不读写 `projects/` 与 `temp/realrun-*`。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest  # noqa: E402

from agentflow import closing as CL  # noqa: E402
from agentflow import conductor as CND  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.agent_b import optimize_prompts as OP  # noqa: E402
from agentflow.agent_b.open_polish_copy import opened_polish_sources  # noqa: E402
from agentflow.store import Store  # noqa: E402

TASK_ID = "t-000001"
P1 = "1. 由定义直接得到。\n2. 由 1 与假设 n ≥ 3 得结论。"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    """一条有原稿的定理（无签）+ 一条没有原稿的概念 + B 自己的任务行。"""
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    conftest.seed_statement_row(
        st, stmt_id="000000", kind="theorem", origin="own_result",
        statement_full="命题（夹具）：弦长函数不是常值。", proof_text=P1)
    conftest.seed_statement_row(
        st, stmt_id="000001", kind="concept", origin="own_result",
        statement_full="定义（夹具）：夹具概念的定义正文。")
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", S.Task(
            task_id=TASK_ID, role="B", action="run", called_by="user",
            status="running", input_key="B.run", detail="夹具：B 的优化轮任务行",
            started_at=conftest.TS).to_dict())
    return st


def _b(st: Store) -> AgentB:
    return conftest.b_form_gate_ok(AgentB(st, extractor=None, extract_text=None, config={}))


def _files(st: Store) -> list[str]:
    return sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("*.md"))


def _round(st: Store) -> dict:
    with CND.calling_as(TASK_ID, "B"):
        return _b(st).open_optimization_drafts()


# ================================================================ a 正控：未签也开

def test_a_the_round_opens_one_draft_from_an_unsigned_source(tmp_path) -> None:
    """a：有原稿的定理（源稿没签）⇒ 开 1 份 B 号稿，初始稿就是原证明正文，提示词是定理档。"""
    st = _ws(tmp_path)
    got = _round(st)
    assert got.get("checked") is True, got
    assert got.get("enabled") is True, got
    assert got.get("count") == 1, got
    assert got.get("refused") == [], got
    row = dict(got["opened"][0])
    assert row["stmt_id"] == "000000", row
    assert row["ok"] is True, row
    assert row["source_sign"] == "unsigned", row
    assert row["source_kind"] == "statement_proof_text", row
    assert row["prompt_class"] == "theorem", row
    assert dict(row.get("prompt") or {}).get("status") == "ready", row.get("prompt")
    assert str(dict(row.get("prompt") or {}).get("prompt") or "").strip(), row.get("prompt")

    cp = str(row["path"])
    assert cp == "reports/b-proof-000000.md", cp
    text = (pathlib.Path(st.root) / cp).read_text(encoding="utf-8")
    assert "## 证明" in text and P1 in text, text[:400]
    assert "- V 签：" not in text, text.split("\n")[:6]
    assert _files(st) == ["b-proof-000000.md"], _files(st)
    # 来源记录：源稿没有稿号 ⇒ `stmt:<命题号>`（幂等判据的同一枚记号）
    opened = opened_polish_sources(st)
    assert opened["checked"] is True and opened["count"] == 1, opened
    assert opened["by_source"] == {"stmt:000000": ["000000"]}, opened["by_source"]
    # 概念没有原稿 ⇒ 不开，但要给出下一步
    assert [x["stmt_id"] for x in got["skipped_no_draft"]] == ["000001"], got["skipped_no_draft"]
    assert "b-稿" in str(got["skipped_no_draft"][0].get("next_step") or ""), got["skipped_no_draft"]


def test_a_stubbing_the_round_off_opens_nothing(tmp_path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """a 反真空：把优化轮打桩成关掉 ⇒ 一份都不开、盘上不新增（"开了 1 份"不是恒真读数）。"""
    st = _ws(tmp_path)
    from agentflow.agent_b import open_polish_copy as OPC

    monkeypatch.setattr(OPC._OpenPolishCopy, "_optimization_round_enabled",
                        staticmethod(lambda: False))
    got = _round(st)
    assert got.get("checked") is True, got
    assert got.get("enabled") is False, got
    assert got.get("count") == 0, got
    assert _files(st) == [], _files(st)
    assert "反真空" in str(got.get("why") or ""), got


# ================================================================ b 负控：无原稿才不开

def test_b_a_concept_without_a_draft_is_not_opened_but_gets_a_next_step(tmp_path) -> None:
    """b：概念没有良定义论证 ⇒ 不开稿（不是受控拒，是"还轮不到开"），next_step 是可执行的。"""
    st = _ws(tmp_path)
    got = _round(st)
    skipped = {str(x["stmt_id"]): x for x in got["skipped_no_draft"]}
    assert set(skipped) == {"000001"}, skipped
    assert "没有可复制的原稿" in str(skipped["000001"].get("why") or ""), skipped
    assert "ingest_manuscript" in str(skipped["000001"].get("next_step") or ""), skipped
    assert all(str(x["stmt_id"]) != "000001" for x in got["opened"]), got["opened"]


def test_b_the_action_itself_refuses_only_when_there_is_no_source(tmp_path) -> None:
    """b 的第二半（无源稿才拒）：单条动作这一档是 `no_source_draft`，不是"没签"。"""
    st = _ws(tmp_path)
    with CND.calling_as(TASK_ID, "B"):
        got = _b(st).open_polish_copy(statement_id="000001")
    assert got.get("ok") is False, got
    assert got.get("refused") == "no_source_draft", got
    assert "没有可复制的原稿" in str(got.get("why") or ""), got
    assert got.get("path") == "", got


# ================================================================ c 幂等

def test_c_running_the_round_twice_does_not_open_a_second_copy(tmp_path) -> None:
    """c：同一轮跑两次 ⇒ 第二次不开新稿（来源记录在 `tasks.artifacts` 上认得出上一次）。"""
    st = _ws(tmp_path)
    first = _round(st)
    assert first["count"] == 1, first
    files_after_first = _files(st)
    second = _round(st)
    assert second["checked"] is True, second
    assert second["count"] == 0, second
    assert [x["stmt_id"] for x in second["skipped_open"]] == ["000000"], second["skipped_open"]
    assert second["skipped_open"][0]["copies"] == ["000000"], second["skipped_open"]
    assert _files(st) == files_after_first, (_files(st), files_after_first)


def test_c_without_the_record_the_second_round_opens_again(
        tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c 反真空：把来源记录读口打桩成"一条都没开过" ⇒ 第二次又开一份（证明幂等靠记录）。"""
    st = _ws(tmp_path)
    assert _round(st)["count"] == 1
    from agentflow.agent_b import open_polish_copy as OPC

    monkeypatch.setattr(OPC, "opened_polish_sources",
                        lambda store: {"checked": True, "by_source": {}, "count": 0, "why": ""})
    again = _round(st)
    assert again["count"] == 1, again
    assert len(_files(st)) == 2, _files(st)


# ================================================================ d 提示词分派

def test_d_the_two_ready_prompts_say_what_to_optimize() -> None:
    """d：theorem / exhaustive 两档是 `ready`，正文各自指向该档的优化目标。"""
    th = OP.optimization_prompt("theorem")
    ex = OP.optimization_prompt("exhaustive")
    assert th["status"] == "ready" and ex["status"] == "ready", (th["status"], ex["status"])
    assert "优化" in th["prompt"] and "命题" in th["goal"], th
    assert "搜索空间" in ex["prompt"] and "穷尽" in ex["prompt"], ex
    # 判"优化好了"的口径三档共用：正文改了 / V 签在新 sha 上 / 收录记成 optimized=true
    for one in (th, ex):
        assert "optimized=true" in one["done_when"], one["done_when"]
        assert "signed" in one["done_when"], one["done_when"]


def test_d_well_defined_is_still_a_draft_not_a_prompt() -> None:
    """d：良定义档不落（业主「良定义类需再做设计」）⇒ `draft_pending` 且正文为空。"""
    got = OP.optimization_prompt("well_defined")
    assert got["status"] == "draft_pending", got["status"]
    assert got["prompt"] == "", got["prompt"]
    assert "良定义" in got["goal"], got["goal"]


def test_d_stuffing_an_f_style_prompt_into_well_defined_turns_it_red() -> None:
    """d 反真空：给良定义档塞一句 F 侧的话（"把证明写清楚"）⇒ 上面那条判据当场红。"""
    stubbed = dict(OP.PROMPTS["well_defined"])
    stubbed.update(status="ready", prompt="把证明写清楚：每步给理由。")
    assert stubbed["prompt"] != "" and stubbed["status"] == "ready", stubbed
    # 同一把尺子（上面那条判据的三句）在桩上必须红
    problems = []
    if stubbed["status"] != "draft_pending":
        problems.append("status 不再是 draft_pending")
    if stubbed["prompt"]:
        problems.append("良定义档出现了提示词正文")
    assert problems, "塞回去之后判据没红 ⇒ 这条反真空失效"


def test_d_an_unknown_class_is_not_silently_a_theorem() -> None:
    """d 的边界：拼错的档名退回 theorem，但 `status` 标 `unregistered`（不静默）。"""
    got = OP.optimization_prompt("theroem")
    assert got["status"] == "unregistered", got
    assert got["key"] == "theroem", got
    assert "theroem" in str(got.get("why") or ""), got


# ================================================================ e 词表一处

def test_e_the_two_vocabularies_are_the_same_words() -> None:
    """e：档名词表只有两处，且逐字相同（多一档、少一档都红）。"""
    assert tuple(CL.OPTIMIZATION_PROMPT_CLASSES) == tuple(OP.PROMPT_CLASSES), (
        CL.OPTIMIZATION_PROMPT_CLASSES, OP.PROMPT_CLASSES)
    assert set(OP.PROMPTS) == set(OP.PROMPT_CLASSES), OP.PROMPTS.keys()
