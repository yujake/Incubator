# -*- coding: utf-8 -*-
"""交接手稿的「发 / 收」两栏要显示绝对编码（Q2，业主 2026-10-26）。

## 诊断（真机 `projects/mp3-r3/manuscripts/handoffs.jsonl`，机器读）

行键 14 个：`body` / `bytes` / `created_at` / `format` / `id` / `note` / `path` /
`refs` / `sender` / `sha256` / `sid` / `summary` / `task_id` / `to`。
`000000 sender=M to=ALL task_id=t-000001`、`000001 sender=A to=M task_id=t-000002`
—— 发信人的绝对编码本来就在（`task_id` 就是发信人的台账号），收件人没有编号格；
页面上「发 / 收」两列于是只剩 `M` / `ALL` / `A` 这种角色名（`ui/src/pages/Artifacts.tsx`
那两列直接印 `sender` / `to`）。

## 判据（六条；改前红写在每一条的 docstring 里）

| 判据 | 查什么 |
|---|---|
| a | 新发一条（具体收件人）⇒ 行里有 `to_task_id` 且等于那个收件人的台账号；读侧渲染 `F（t-…）` |
| b | `to=ALL` ⇒ `to_task_ids` 非空，且就是发信人此刻的直接子代理；空列表 ⇒ `ALL（广播；无直接子代理）` |
| c | 旧行（两格都没有）⇒ 读侧写「旧账无号」/「广播；旧账无编号」，不报错、不编号 |
| d | 反真空①：把写侧「记编号」那一步打桩掉 ⇒ 判据 a 必红 |
| e | 同一父下两个同角色子代理 ⇒ 收件人是被点名的那一个实例（不是"唯一实例"、也不是空） |
| f | 反真空②：把「传编号」那一步（`handoff_add` 的转发形参）打桩掉 ⇒ a 与 e 必红，且读数是「旧账无号」 |

## 纪律

零模型钱：网关是桩（`_Gate`），`Store` / 名册 / 台账全在 `tmp_path` 里，不碰真工作区。
名册走 `Secretary.roster_add`（写侧唯一实现），台账行走 `Conductor._write_new_row`
（既有夹具的同一套造法，见 `tests/test_addressing_goes_through_the_roster.py`）。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from agentflow import manuscripts as MS
from agentflow import secretary as SEC
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.webui import readers as R

SID = "q2"

#: 发信人（我）与它的直接子代理；父是 `D`（名册的"父"那一格要读得到）。
ME_ROLE, PARENT_ROLE = "B", "D"


class _Gate:
    """零模型钱的网关桩（与既有判据同一个写法）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": "{}",
                                  "tool_calls": (), "tokens_in": 1, "tokens_out": 1,
                                  "error_detail": "", "error_kind": ""})()


def _row(cond: Conductor, parent: str, role: str, *, key: str) -> str:
    """在台账里造一行代理行（父/子都由它造；`depth` 按父的深度 + 1）。"""
    prow = cond._task(parent) or {}
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": key, "status": "done", "outcome": "ok",
        "refusal_reason": None, "instance": "", "detail": f"一个 {role} 实例",
        "error": None, "started_at": "2026-10-26T10:00:00+08:00",
        "ended_at": "2026-10-26T10:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _env(tmp_path: pathlib.Path, *, second_role: str = "A") -> dict[str, Any]:
    """四层台账 + 名册（父的名册名记在祖父那一侧）+ 我的两个子代理。

    `second_role` 决定第二个子代理的角色：默认 `A`（判据 b 要的"不止一个"），
    判据 e 传 `"F"`（同一父下两个同角色子代理）。
    """
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "Q2 顶层这一趟")
    pa = _row(cond, top, PARENT_ROLE, key="q2@pa")
    me = _row(cond, pa, ME_ROLE, key="q2@me")
    f1 = _row(cond, me, "F", key="q2@f1")
    f2 = _row(cond, me, second_role, key="q2@f2")
    loop = AgentLoop(role=ME_ROLE, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ME_ROLE, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = me
    loop.parent_task_id = pa
    sec = loop.secretary
    assert sec is not None, "这一组判据要的是「名册在手上」那一档"
    # 父的名册名记在祖父那一侧（名册的"父"那一格靠 `name_of(owner=祖父, task_id=父)` 换算）。
    assert sec.roster_add(owner=top, role=PARENT_ROLE, task_id=pa,
                          brief="我那一层的父")["name"] == "D1"
    assert sec.roster_add(owner=me, role="F", task_id=f1, brief="检索那一件")["name"] == "F1"
    name2 = sec.roster_add(owner=me, role=second_role, task_id=f2, brief="另一件")["name"]
    # 名字由秘书发号（同角色第二个实例 ⇒ `<角色>2`；判据 e 要的正是"两个同角色实例"）
    assert name2.startswith(second_role) and name2, name2
    return {"ws": ws, "st": st, "cond": cond, "loop": loop, "sec": sec,
            "top": top, "pa": pa, "me": me, "f1": f1, "f2": f2}


def _hand_off(env: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """走真机那条写路（`_do_handoff` ⇒ `Secretary.handoff_add` ⇒ `manuscripts.write`）。"""
    body = {"summary": "Q2 的一条交接", "body": "## 做了什么\n一行。\n"}
    return env["loop"]._do_handoff({**body, **payload})


def _last_row(ws: pathlib.Path) -> dict[str, Any]:
    rows = MS.rows(ws)
    assert rows, "这一趟一条手稿都没写"
    return rows[-1]


def _label(ws: pathlib.Path, index: int = -1) -> dict[str, Any]:
    return R.artifacts_face(ws)["handoffs"][index]


# ====================================================================== a) 具体收件人
def test_a_a_concrete_recipient_carries_its_task_id(tmp_path: pathlib.Path) -> None:
    """判据 a：新发一条给具体收件人 ⇒ 行里有 `to_task_id`，且读侧渲染成 `F（t-…）`。

    改前红：这一行只有 `to="F"`；`to_task_id` 这一格根本不存在，读模型里也没有任何一格
    装收件人的编号（`by_task_id` 对交接行恒 `not_applicable`），页面上只剩一个 `F`。
    """
    env = _env(tmp_path)
    res = _hand_off(env, {"to": "F"})
    assert res.get("ok") is True, res
    row = _last_row(env["ws"])
    assert row["to"] == "F" and row["sender"] == ME_ROLE, row
    # 收件人的绝对编码落在行里，且就是那个子代理的台账号（不是猜的）
    assert row.get("to_task_id") == env["f1"], row.get("to_task_id")
    # 发信人的台账号仍在原格（`task_id`），角色名 `sender` 一个字没被覆盖
    assert row["task_id"] == env["me"], row["task_id"]
    hand = _label(env["ws"])
    assert hand["sender_label"] == f"{ME_ROLE}（{env['me']}）", hand["sender_label"]
    assert hand["to_label"] == f"F（{env['f1']}）", hand["to_label"]
    # 各留一格：角色名与编号不许互相顶替
    assert hand["sender"] == ME_ROLE and hand["to"] == "F", hand
    assert hand["to_task_id"] == env["f1"], hand["to_task_id"]


# ====================================================================== b) 广播
def test_b_broadcast_records_the_senders_direct_children(tmp_path: pathlib.Path) -> None:
    """判据 b（正控）：`to=ALL` ⇒ `to_task_ids` 非空，且就是发信人此刻的直接子代理编号。

    为什么记编号列表而不是 `*`：`*` 是一句盘上对不了账的话（"广播面"到底是谁，没有一个字
    能核）；编号列表可以逐条在名册上对上，而"谁是直接子代理"本来就是名册答得出的那一问。
    """
    env = _env(tmp_path)
    res = _hand_off(env, {"to": "ALL"})
    assert res.get("ok") is True, res
    row = _last_row(env["ws"])
    assert row["to"] == "ALL", row
    codes = row.get("to_task_ids")
    assert isinstance(codes, list) and codes, codes
    # 名册上发信人此刻的直接子代理（非退役）：唯一一份名册读数，判据照它比
    kids = sorted(str(r.get("task_id") or "")
                  for r in env["sec"].roster_view(owner=env["me"])["rows"]
                  if str(r.get("task_id") or "") and str(r.get("status") or "") != "retired")
    assert codes == kids, (codes, kids)
    assert set(codes) == {env["f1"], env["f2"]}, codes
    # 具体收件人那一格不该被广播顶替（两种形状不许混）
    assert "to_task_id" not in row, row.get("to_task_id")
    hand = _label(env["ws"])
    assert hand["to_label"] == "ALL（" + "、".join(kids) + "）", hand["to_label"]
    assert hand["to_task_ids"] == kids, hand["to_task_ids"]


def test_b2_a_broadcast_with_no_children_is_recorded_as_empty(
        tmp_path: pathlib.Path) -> None:
    """判据 b（第二档）：一个子代理都没有的广播 ⇒ 记空列表，读侧写「广播；无直接子代理」。

    为什么空列表也要落盘：空列表是结论（查过了、名下真没有子代理），而缺键是
    "这一格没记"。两者在页面上必须分开 —— 折平之后"新行没查"会冒充"确实没有"。
    """
    env = _env(tmp_path)
    env["loop"].my_task_id = env["f1"]        # 叶子：它名下没有子代理
    res = _hand_off(env, {"to": "ALL"})
    assert res.get("ok") is True, res
    row = _last_row(env["ws"])
    assert row["to"] == "ALL" and row.get("to_task_ids") == [], row
    assert _label(env["ws"])["to_label"] == "ALL（广播；无直接子代理）", _label(env["ws"])


# ====================================================================== c) 旧行
def test_c_an_old_row_without_the_fields_says_so(tmp_path: pathlib.Path) -> None:
    """判据 c（正控）：旧行（两格都没有）⇒ 读侧写「旧账无号」，不报错、不编号。

    这一条守三态：没有编号与有一个编号必须分得开，而"没有"不许补一个看起来像
    编号的东西（补出来的那个数字看起来像证据，其实是猜）。广播那一档另有一句措辞
    （它还说了"这是广播"）。
    """
    env = _env(tmp_path)
    legacy = [
        {"id": "000000", "sender": ME_ROLE, "to": "F", "summary": "改前落的一条",
         "body": "# B → F｜改前落的一条\n", "refs": [],
         "created_at": "2026-10-25T09:00:00+08:00", "task_id": "t-legacy", "sid": SID,
         "note": "", "sha256": "0" * 64, "bytes": 1, "format": "jsonl",
         "path": "manuscripts/handoffs.jsonl#000000"},
        {"id": "000001", "sender": ME_ROLE, "to": "ALL", "summary": "改前落的广播",
         "body": "# B → ALL｜改前落的广播\n", "refs": [],
         "created_at": "2026-10-25T09:01:00+08:00", "task_id": "t-legacy", "sid": SID,
         "note": "", "sha256": "1" * 64, "bytes": 1, "format": "jsonl",
         "path": "manuscripts/handoffs.jsonl#000001"},
    ]
    p = MS.handoffs_path(env["ws"])
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        for one in legacy:
            fh.write(json.dumps(one, ensure_ascii=False, sort_keys=True) + "\n")
    face = R.artifacts_face(env["ws"])
    assert face["handoffs_tri"] == R.TRI_COMPUTED, face["reason"]
    first, second = face["handoffs"][0], face["handoffs"][1]
    # 编号格归一成"有值但为空"（键在、结论是"没有"），渲染写「旧账无号」
    assert first["to"] == "F" and first["to_task_id"] == "", first
    assert first["to_label"] == f"F（{R.HANDOFF_NO_CODE_WORD}）", first["to_label"]
    assert first["to_label"] == "F（旧账无号）", first["to_label"]
    # 发件人那一行的编号是有的（`task_id` 本来就在）⇒ 照旧显示，不许跟着"旧账无号"
    assert first["sender_label"] == f"{ME_ROLE}（t-legacy）", first["sender_label"]
    # 广播那一档另有一句（说清它不但是"没编号"，还是"广播"）
    assert second["to"] == "ALL" and second["to_task_ids"] == [], second
    assert second["to_label"] == f"ALL（{R.HANDOFF_NO_BROADCAST_WORD}）", second["to_label"]
    assert second["to_label"] == "ALL（广播；旧账无编号）", second["to_label"]


# ====================================================================== e) 同角色两实例
def test_e_the_named_instance_wins_over_the_role(tmp_path: pathlib.Path) -> None:
    """判据 e：同一父下两个同角色子代理 ⇒ 收件人是被点名的那一个实例。

    改前红（两个方向都红）：行里没有收件人编号；而"按角色猜"这条路在这一档要么落到
    `ambiguous_in_roster`（干脆没有号），要么落到另一个实例上 —— 两种都不是"点名的那一个"。
    """
    env = _env(tmp_path, second_role="F")
    f1, f2 = env["f1"], env["f2"]
    res = _hand_off(env, {"to": "F",
                          "roster_addressing": {"written": "F2", "name": "F2",
                                                "task_id": f2, "role": "F",
                                                "how": "child",
                                                "addressed_by": "roster_name"}})
    assert res.get("ok") is True, res
    assert str((res.get("addressing") or {}).get("task_id") or "") == f2, res["addressing"]
    row = _last_row(env["ws"])
    # 台账的收件人面仍是角色（`to` 是键），实例编号落在它自己那一格
    assert row["to"] == "F", row
    assert row.get("to_task_id") == f2, row.get("to_task_id")
    assert row.get("to_task_id") != f1, ("落到了另一个同角色实例上", row)
    assert _label(env["ws"])["to_label"] == f"F（{f2}）", _label(env["ws"])["to_label"]


# ====================================================================== d / f) 反真空
def test_d_stubbing_the_write_side_makes_a_red(tmp_path: pathlib.Path,
                                              monkeypatch) -> None:
    """判据 d（反真空①）：把写侧「记编号」那一步打桩掉 ⇒ 判据 a 必红。

    打桩打在 `manuscripts.write` 的收编号那一处（把两个形参按"没给"喂进去）：它一空，
    行里就不该再有那一格 —— 判据 a 的 `row.get("to_task_id") == 那个台账号` 于是不成立，
    读侧也不许从 `to="F"` 拼出一个编号来。
    """
    env = _env(tmp_path)
    real = MS.write

    def _dropped(*a: Any, **kw: Any) -> dict[str, Any]:
        kw["to_task_id"] = ""
        kw["to_task_ids"] = None
        return real(*a, **kw)

    monkeypatch.setattr(MS, "write", _dropped)
    res = _hand_off(env, {"to": "F"})
    assert res.get("ok") is True, res
    row = _last_row(env["ws"])
    assert row["to"] == "F", row
    assert "to_task_id" not in row, row.get("to_task_id")
    assert _label(env["ws"])["to_label"] == f"F（{R.HANDOFF_NO_CODE_WORD}）", _label(env["ws"])


def test_f_stubbing_the_forwarding_param_makes_a_and_e_red(tmp_path: pathlib.Path,
                                                          monkeypatch) -> None:
    """判据 f（反真空②）：把 `handoff_add` 的转发形参打桩掉 ⇒ a 与 e 都必红。

    这一条防的是"编号只活在回执里、没进行里"那种假绿：判据 a/e 读的是盘上那一行，
    转发断在秘书这一层，盘上就真的没有编号 —— 于是两条断言都不成立，读数是「旧账无号」，
    而不是一个编出来的数字。
    """
    env = _env(tmp_path, second_role="F")
    f2 = env["f2"]
    real = SEC.Secretary.handoff_add

    def _dropped(self: Any, **kw: Any) -> dict[str, Any]:
        kw["to_task_id"] = ""
        kw["to_task_ids"] = None
        return real(self, **kw)

    monkeypatch.setattr(SEC.Secretary, "handoff_add", _dropped)
    # a) 具体收件人这一档
    assert _hand_off(env, {"to": "F"}).get("ok") is True
    first = _last_row(env["ws"])
    assert first["to"] == "F" and "to_task_id" not in first, first
    assert _label(env["ws"])["to_label"] == "F（旧账无号）", _label(env["ws"])["to_label"]
    # e) 点名实例这一档
    assert _hand_off(env, {"to": "F",
                           "roster_addressing": {"written": "F2", "name": "F2",
                                                 "task_id": f2, "role": "F",
                                                 "how": "child",
                                                 "addressed_by": "roster_name"}}
                     ).get("ok") is True
    second = _last_row(env["ws"])
    assert second["to"] == "F" and "to_task_id" not in second, second
    assert _label(env["ws"])["to_label"] == "F（旧账无号）", _label(env["ws"])["to_label"]
