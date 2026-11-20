# -*- coding: utf-8 -*-
"""受控拒的原文必须落在盘上（2026-11-17，AL2·#3 / AH1）。

## 改前是什么形态

真机现场（AH1）：这一趟 A 有 5 次"收录被拒"，而拒信原文不在盘上 —— 那些拒走的是
秘书那条缝（`Secretary.record_statement`：判定与落库都在秘书那一侧，模型判定发生
在这里），不是 agent 的工具调用，所以 B 的 `agent_step_call` 里 0 条、run 文件也还
没写到那一刻 ⇒ 审计时"为什么拒"只能猜，判据只能报"会话里 0 次"。

## 判据

| 判据 | 它要证明的事 |
|---|---|
| a 缝上的受控拒 | `out/secretary/refusals.jsonl` 多一行原文：`kind` / `why` / `at` / `role` / `task_id` / `where`；`why` 与返回值的 `reason` 逐字相同 |
| b 工具路径的拒 | 工具路径照旧有自己的读数（`routed_to_backstop` + `refused_by_backstop`），并且同一份原文也进台账（"无论来自哪条路"） |
| c 反真空 | 把落盘那一步打桩关掉 ⇒ a 的那一行必消失（于是 a 的绿来自那个写点，不是别的路径顺手记的） |

落点复用既有形态：`out/secretary/*.jsonl` 是秘书侧的轴台账目录
（`dispatch_fit.jsonl` / `nontriviality.jsonl` / `relay.jsonl` 都在这里），webui 的
目录 glob 也认它 —— 不新造目录、不新造形状。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import refusals as R
from agentflow.conductor import calling_as
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.tools import build_registry

#: AH1 那一类载荷：要写证明正文，而盘上没有在册行、也没有盖住正文的手稿签。
PAYLOAD = {
    "kind": "theorem",
    "statement_full": "设 x>0，则 x+1>0。",
    "proof_text": "由 x>0 直接相加得到。",
    "origin": "own_result",
}

#: 判据 a 要求的六格（逐字；多一格不算错，少一格就是"查不到为什么拒"）。
LINE_KEYS: tuple[str, ...] = ("at", "kind", "role", "task_id", "where", "why")


def _ws(path: pathlib.Path):
    root = path / "ws"
    store = Store(root)
    store.init()
    return root, store


def test_a_a_seam_refusal_leaves_the_original_text(tmp_path: pathlib.Path) -> None:
    """a：秘书缝上的受控拒 ⇒ 盘上有一行原文（含 kind/why/时刻/角色/委托）。"""
    root, store = _ws(tmp_path)
    sec = Secretary("B", root=root, store=store, seam=None, enable_model=False)
    # 绑实例只走 `bind_task`（`task_id` 是只读属性；裸赋值会 AttributeError）。
    # 这里要的是"这一笔的 task_id 落成 t-000054"，分片与存活标记一并落 —— 与本判据无关，
    # 但也不许为了一条夹具去绕开唯一绑定点。
    sec.bind_task("t-000054")

    out = sec.record_statement(PAYLOAD, role="B")
    assert out.get("checked") is False, out
    assert str(out.get("refused") or ""), "这一笔没有被受控拒 ⇒ 判据 a 的前提不成立"
    assert str(out.get("reason") or ""), "受控拒没有理由原话 ⇒ 这一条判据自己先不合格"

    rows = R.refusal_records(root)
    assert len(rows) == 1, f"拒了一次，台账却是 {len(rows)} 行：{rows}"
    line = rows[0]
    for key in LINE_KEYS:
        assert key in line, f"台账那一行缺 {key!r}：{sorted(line)}"
    assert line["kind"] == str(out.get("refused")), (line, out.get("refused"))
    assert line["why"] == str(out.get("reason")), (
        "台账里的 why 与返回值里的 reason 不是逐字同一句 —— 审计拿到的就不是原话",
        line["why"], out.get("reason"))
    assert line["role"] == "B", line
    assert line["task_id"] == "t-000054", line
    assert line["where"] == "secretary.record_statement", line
    assert str(line["at"]).strip(), "台账那一行没有时刻"
    # 落的是既有的秘书轴台账目录（不是新造目录）。
    assert R.refusal_ledger_path(root).parent == root / "out" / "secretary"


def test_b_a_tool_path_refusal_also_leaves_a_line(tmp_path: pathlib.Path) -> None:
    """b：走工具路径的那一条拒照旧有自己的读数，并且同一份原文也进台账。"""
    root, store = _ws(tmp_path)
    reg = build_registry(store=store, workspace_root=root).registry
    with calling_as("t-tool-refusal", "B"):
        res = reg.call("table.create", role="B", table="statements", row=dict(PAYLOAD))
    assert res.ok is False, ("直写 statements 应当被转交正路并受控拒", res)
    assert str(res.meta.get("kind") or "").startswith("routed_to_backstop"), res.meta
    assert res.meta.get("refused_by_backstop"), (
        "工具路径照旧要有兜底方的原话（refused_by_backstop）", res.meta)
    rows = R.refusal_records(root)
    assert len(rows) == 1, f"工具路径拒了一次，台账却是 {len(rows)} 行：{rows}"
    # 兜底方那句原话在 `refused_by_backstop`（`<码>：<理由>`）与 `res.error` 里都要读得到；
    # 台账那一行的 kind 就是那个码 —— 两处不许各说一套。
    said = str(res.meta.get("refused_by_backstop") or "")
    assert rows[0]["kind"] in said and rows[0]["kind"] in str(res.error or ""), (
        rows[0]["kind"], said, res.error)


def test_c_removing_the_write_point_turns_a_red(tmp_path: pathlib.Path,
                                                monkeypatch) -> None:
    """c（反真空）：把落盘那一步关掉 ⇒ a 的那一行必消失。

    打桩点就是唯一的写点（`refusals.record_refusal`）：它返回 None 之后，同一条路径
    仍然被受控拒（返回值一个字没变），而台账里一行都没有 —— 于是 a 的绿来自那个写点。
    """
    monkeypatch.setattr(R, "record_refusal", lambda *a, **kw: None)
    root, store = _ws(tmp_path)
    sec = Secretary("B", root=root, store=store, seam=None, enable_model=False)
    out = sec.record_statement(PAYLOAD, role="B")
    assert out.get("checked") is False and str(out.get("refused") or ""), (
        "打桩只该关掉留痕，不该改变受控拒本身", out)
    assert R.refusal_records(root) == [], (
        "写点已经打桩关掉了，台账里却还有行 ⇒ 这一行不是那个写点落的")
