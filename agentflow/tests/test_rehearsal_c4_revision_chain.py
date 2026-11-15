# -*- coding: utf-8 -*-
"""WF 判据：C4 打回修订链的「秘书洗稿 → 转达 F」（正控 / 反真空 / 负控），2026-11-16。

## 它钉的是什么（CC4 缺陷 2 的修复判据）

| 编号 | 它要证明的事 | 它能怎么红 |
|---|---|---|
| c4-a | V 判 fault（未在册支）⇒ 秘书洗稿真的发生（出网层里出现洗稿那一问）、
pending 行 `washed_relay` 有值、洗过的文本进了 F 的下一轮输入（与 V 的 final 同时可见） | 洗稿调用被摘掉（c4-b）或只写 pending、不转达 ⇒ problems 非空 |
| c4-b | 反真空：只把未在册支的洗稿摘掉（已在册支保留）⇒ c4-a 必须绿转红：
pending 没有 `washed_relay`、F 的下一轮输入里只有 V 的 final/notice、板上没有
`v-wash@` 项；整条 C4 链（打回 → 重写 → 再签）仍然走通 | 如果摘掉洗稿之后 c4-a 仍然绿 ⇒
它量的不是洗稿转达 |
| c4-c | 负控：已在册那一支的行为逐字不变 —— 用既有验收判据
`test_v_opinion_chain_reaches_f.test_e1...` 原样跑一遍（它钉着洗稿调用、台账
`washed_relay.text`、读侧 `washed`、板项 detail 四格） | 已在册支被顺手改坏 ⇒ e1 红 |

## 与 CC4 旧彩排的关系

执行体、夹具与出网替身全部复用 `tests/test_rehearsal_c4_revision_loop.py` 的 `_run`
（CLI 真入口、真 `wired_llm_conductor`、真 `AgentV.verify_proof`、只换
`modelgw.urllib_transport`）。本文件只加"未在册支洗稿转达"的判据与两条控制。

## 两个"转达"落点各自是什么（别把它们混成一件事）

1. `verifications/pending/<正文 sha>.jsonl` 那一行的 `washed_relay`：V 自己的账，
   与在册那一支的 `record_verification` 同形（条件写入：只有 `washed=True` 才写）；
2. F 的下一轮输入：洗过的文本走既有 `conductor.open_item` + `set_item_detail` 通道
   投成一条普通 notice（`input_key` 以 `v-wash@` 开头、不是 `v-verdict@` 那种
   要回执的判决项），它出现在 F 下一拍的板摘要/新消息里。V 自己的 final 仍在同一条
   `框架执行结果` 里 —— 两条一起可见，才分得清"V 的原话"与"秘书洗过的转达"。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from test_rehearsal_c4_revision_loop import (
    DEFECT,
    REJECT_FINAL,
    _chain_problems,
    _chain_reading,
    _run,
)

from agentflow.agent_v import AgentV

#: 彩排里秘书洗出来的那一份转达（`_Wire` 的洗稿支逐字回这一段）。
WASH_TEXT = "请补第 2 步的记号说明"


def _fault_row(reading: dict) -> dict:
    """v1 那一份被判 fault 的 pending 行（按第一轮 attack.step 的正文 sha 认）。"""
    sha = str((reading["steps"][0]["data"] or {}).get("proof_sha256") or "")
    for row in reading["pending"]:
        if str(row.get("proof_sha256") or "") != sha:
            continue
        if int(row.get("defect_step") or 0) == 2:
            return dict(row)
    return {}


def _next_f_prompt(reading: dict) -> str:
    """V 的 final 第一次出现在 F 的哪一拍输入里（那一拍就是"下一轮输入"）。"""
    for prompt in reading["f_prompts"]:
        if REJECT_FINAL in prompt:
            return str(prompt)
    return ""


def _wash_calls(got: dict) -> list[dict]:
    """出网层里"洗稿那一问"（`secretary._wash_v_system` 的稳定头）。"""
    return [b for b in got["wire"].bodies
            if str(b.get("system") or "").lstrip().startswith("你是「秘书」的洗稿面")]


def _wash_board(reading: dict) -> list[dict]:
    return [dict(r) for r in reading["tasks"]
            if str(r.get("input_key") or "").startswith("v-wash@")]


def _wash_decisions(ws: pathlib.Path) -> list[dict]:
    """`out/secretary/V.jsonl` 里"已洗稿"的决定行（洗稿真的发生了的落痕）。"""
    path = ws / "out" / "secretary" / "V.jsonl"
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or str(row.get("kind") or "") != "secretary_decision":
            continue
        if bool((row.get("judge") or {}).get("washed")):
            rows.append(row)
    return rows


def _wash_problems(reading: dict, got: dict) -> list[str]:
    """c4-a 的判据集合（空 = 通）；c4-b 用它证明"摘掉洗稿必须红"。"""
    problems: list[str] = []
    row = _fault_row(reading)
    if not row:
        return ["v1 的 fault pending 行没找到（这一条链没有判词落点）"]
    judge = dict(row.get("secretary_judge") or {})
    if str(judge.get("axis") or "") != "fault":
        problems.append(f"v1 那一行的秘书轴不是 fault：{judge.get('axis')!r}")
    washed = dict(row.get("washed_relay") or {})
    if not str(washed.get("text") or "").strip():
        problems.append(f"未在册支没有把洗过的转达写进 pending 行：{washed!r}")
    elif WASH_TEXT not in str(washed.get("text") or ""):
        problems.append(f"pending 行上的洗稿文本不是彩排里那一份：{washed.get('text')!r}")
    if not _wash_calls(got):
        problems.append("出网层里没有洗稿那一问 ⇒ 秘书没有被叫去洗稿")
    if not _wash_decisions(reading["ws"]):
        problems.append("`out/secretary/V.jsonl` 里没有「已洗稿」的决定行")
    prompt = _next_f_prompt(reading)
    if not prompt:
        problems.append("F 的下一轮输入里没找到 V 的 final（这一条没有转达对象）")
    else:
        if REJECT_FINAL not in prompt:
            problems.append("F 的下一轮输入里没有 V 的 final（两条读数分不开）")
        if WASH_TEXT not in prompt:
            problems.append("F 的下一轮输入里没有洗过的内容（洗稿没有转达）")
    board = _wash_board(reading)
    if not board:
        problems.append("板上没有 v-wash@ 那一项（洗过的转达没有落点）")
    else:
        one = dict(board[0])
        if WASH_TEXT not in str(one.get("detail") or ""):
            problems.append(f"板项的正文里没有洗过的内容：{one.get('detail')!r}")
        if str(one.get("kind") or "") != "notice":
            problems.append(f"洗稿转达的板项不是 notice：{one.get('kind')!r}")
        if str(one.get("input_key") or "").startswith("v-verdict@"):
            problems.append("未在册的洗稿转达用了 v-verdict@ 那种要回执的判决项"
                            "（未在册命题没有可收口的登记项）")
    return problems


def _strip_unregistered_wash(monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：只在"未在册"那一档把 `_wash_v_reply` 摘掉（已在册那一档原样调用）。"""
    original = AgentV._wash_v_reply

    def fake(self, reply, verdict, no, *, statement_id="", **kw):
        if str(statement_id or ""):
            return original(self, reply, verdict, no, statement_id=statement_id, **kw)
        return {"checked": True, "washed": False, "text": "", "findings": [],
                "dropped": [], "refused": "rehearsal_no_wash",
                "reason": "反真空：未在册支不洗稿"}

    monkeypatch.setattr(AgentV, "_wash_v_reply", fake)


# ============================================================ c4-a 正控


def test_c4_a_the_unregistered_fault_is_washed_and_relayed_to_f(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控：V 判 fault（未在册）⇒ 洗稿发生、pending 有 washed_relay、F 下一拍看得到。"""
    got = _run(tmp_path, monkeypatch, lean="0")
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    problems = _wash_problems(reading, got)
    print(f"[c4-a] wash_calls={len(_wash_calls(got))} "
          f"decisions={len(_wash_decisions(reading['ws']))} "
          f"pending_wash={bool((_fault_row(reading).get('washed_relay') or {}).get('text'))} "
          f"board={[r.get('input_key') for r in _wash_board(reading)]} "
          f"f_prompt_len={len(_next_f_prompt(reading))}")
    assert problems == [], problems
    # 整条 C4 链（打回 → 只改第 2 步 → 再送 → 签住 → final）仍然走通。
    assert _chain_problems(reading) == [], _chain_problems(reading)


# ============================================================ c4-b 反真空


def test_c4_b_without_the_unregistered_wash_the_positive_control_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：只摘掉未在册支的洗稿 ⇒ c4-a 绿转红，F 只剩 V 的 final/notice。"""
    _strip_unregistered_wash(monkeypatch)
    got = _run(tmp_path, monkeypatch, lean="0")
    reading = _chain_reading(got)
    assert got["rc"] == 0, (got["rc"], got["stdout"][-2000:], got["stderr"][-2000:])
    row = _fault_row(reading)
    prompt = _next_f_prompt(reading)
    print(f"[c4-b] pending_keys={sorted(row.keys())} "
          f"wash_calls={len(_wash_calls(got))} board={_wash_board(reading)} "
          f"f_prompt_has_v_final={bool(prompt and REJECT_FINAL in prompt)} "
          f"f_prompt_has_wash={bool(prompt and WASH_TEXT in prompt)}")
    # 1. 未在册支确实没洗：pending 行没有那一格、出网层没有洗稿那一问、板上没有转达项。
    assert "washed_relay" not in row, row
    assert _wash_calls(got) == [], _wash_calls(got)
    assert _wash_board(reading) == [], _wash_board(reading)
    # 2. F 的下一轮输入里只剩 V 的 final（洗过的内容一个字都没有）。
    assert prompt, "F 的下一轮输入里没找到 V 的 final"
    assert REJECT_FINAL in prompt
    assert WASH_TEXT not in prompt, "摘掉洗稿之后 F 的输入里仍然有洗过的内容"
    # 3. 这一条链本身仍然走通（反真空只摘洗稿，不带走打回/重写/再签）。
    assert _chain_problems(reading) == [], _chain_problems(reading)
    # 4. 最要紧的一格：c4-a 的判据在这里必须非空（否则正控是真空的）。
    problems = _wash_problems(reading, got)
    print(f"[c4-b] c4-a problems={problems}")
    assert problems, "摘掉未在册支的洗稿之后 c4-a 的判据仍然是绿的 ⇒ 正控没有量到洗稿转达"
    assert any("洗过" in one or "washed_relay" in one for one in problems), problems


# ============================================================ c4-c 负控


def test_c4_c_the_registered_branch_is_byte_for_byte_unchanged(
        tmp_path: pathlib.Path) -> None:
    """负控：已在册那一支的既有验收判据 e1 原样跑（它红了 = 已在册支被改了）。

    e1 的断言逐字钉着：秘书判 fault ⇒ 洗稿调用一次、洗出来的文本、台账那一行的
    `washed_relay.text`、读侧 `washed`、板项 detail 里逐字带着 V 指出的问题。
    它不看本文件新增的任何一格，所以"跑绿"就是"已在册支没有被我改坏"。
    """
    from test_v_opinion_chain_reaches_f import (
        test_e1_fault_washes_and_the_washed_opinion_is_what_f_gets as e1,
    )

    e1(tmp_path)


if __name__ == "__main__":  # pragma: no cover - 手工复跑用
    raise SystemExit(pytest.main([__file__, "-q"]))
