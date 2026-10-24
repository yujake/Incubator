# -*- coding: utf-8 -*-
"""D-63：寻址按名册名或绝对编号，角色代号降级为兼容写法。

业主 2026-10-24 逐字：「现在怎么还有to谁的写法？已经是名册机制了！」

诊断（改前实测，不是推测）：名册机制已经落地（每行有名册名 `D1` 与绝对编号
`t-000003`），但寻址面还留着角色级的口径 —— 政策文案逐字教 `to=A–H`（`specs/m.py`
里那一句「交接工作前先写一份手稿」），而名册解析从不把"这一条是写给哪个实例的"
写进读数：`addressing` 里没有 `addressed_by` 这一格，于是"按名册名发"与"按角色代号
发"在回执上长得一样，读的人分不出这一次到底用的是哪一档。

这一份钉六件事（每条都真跑；改前红的地方逐条写在各自的 docstring 里）：

a) 角色代号在册多个 ⇒ 受控拒绝，拒信点名那几个名册名并给出改写法
   （改前红在"在册几个 / 请写名册名或绝对编号"这两句上：改前只说"要发给谁：B1 还是 B2"）；
b) 名册名 ⇒ 解析到那一个成员，读数 `addressed_by=roster_name`；
c) 绝对编号 ⇒ 解析到那个实例，读数 `addressed_by=task_id`；
d) 角色代号在册恰好一个 ⇒ 兼容解析到那一个，读数 `addressed_by=role_fallback`；
e) `to=#public` 仍走频道语义，读数 `addressed_by=channel`；
f) 政策文案不再教 `to=<角色代号>` 这种写法（反真空：塞回一句就红）；
附) 政策现在教的那种写法（名册名 / 绝对编号）解码器真的收 —— 提示词教什么就得收什么。

边界：这一份只用一条四层链（M → A → B（我）→ D1/D2）与真名册文件，不碰
`secretary.py` / `webui/*` / `tests/golden/*`；`_do_message` 是寻址与投递的同一条实现，
所以断言打在它与它的回执上，而不是另造一份判据。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import sessions as SS
from agentflow.agent_loop import AgentLoop
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "d63"

#: 我这一岗：`B`。选它是因为 `B → D` 是一条真协作边（准入不会先拒），
#: 于是量到的只是寻址判据本身，而不是 `message_admission` 那一档。
ME = "B"


class _Gate:
    """最小的模型接缝（这一份判据不跑循环，只用 `AgentLoop` 的装配）。"""

    spec = type("Spec", (), {"model": "stub", "api_key": "x"})()

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        return type("Reply", (), {"ok": True, "text": json.dumps(
            {"final": "收工", "evidence": []}, ensure_ascii=False),
            "tool_calls": (), "tokens_in": 1, "tokens_out": 1,
            "error_detail": "", "error_kind": ""})()


def _row(cond: Conductor, parent: str, role: str, *, key: str) -> str:
    """在台账里造一行（`depth` 按父的深度 + 1，与 `test_addressing_goes_through_the_roster` 同一口径）。"""
    prow = cond._task(parent) or {}
    return cond._write_new_row({
        "task_id": "", "role": role, "action": "run_once", "called_by": "M",
        "parent_task_id": parent, "depth": int(prow.get("depth") or 1) + 1,
        "input_key": key, "status": "done",
        "outcome": "ok", "refusal_reason": None, "instance": "",
        "detail": f"一个 {role} 实例", "error": None,
        "started_at": "2026-10-24T10:00:00+08:00",
        "ended_at": "2026-10-24T10:05:00+08:00",
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }, note=f"start:{role}.run_once")


def _env(root: pathlib.Path, *, same_role_children: int = 2) -> dict[str, Any]:
    """一条四层链 + 我名下的名册（`D1` … `Dn`，每行的角色都是 `D`）。"""
    ws = root / "ws"
    st = Store(ws)
    st.init()
    cond = Conductor(st, policy=None, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond).registry
    top = cond.open_top_level_run("M", "顶层这一趟")
    gp = _row(cond, top, "A", key=f"d63@gp:{root}")
    me = _row(cond, gp, ME, key=f"d63@me:{root}")
    kids = [_row(cond, me, "D", key=f"d63@d{i}:{root}")
            for i in range(same_role_children)]
    loop = AgentLoop(role=ME, session_root=ws, registry=reg, conductor=cond,
                     seam=LlmSeam(role=ME, session_root=ws, gateway=_Gate(),
                                  price=(0.0, 0.0), sid=SID),
                     store=st, sid=SID, max_steps=2)
    loop.my_task_id = me
    loop.parent_task_id = gp
    assert loop.secretary is not None, "这一组判据要的是'名册在手上'那一档"
    names: list[str] = []
    for kid in kids:
        got = loop.secretary.roster_add(owner=me, role="D", task_id=kid, brief="一条路")
        assert got["problem"] == "", got
        names.append(str(got["name"]))
    return {"ws": ws, "st": st, "cond": cond, "loop": loop,
            "top": top, "gp": gp, "me": me, "kids": kids, "names": names}


def _messages(ws: pathlib.Path) -> list[dict[str, Any]]:
    events, _ = SS.read_session(ws, sid=SID)
    return [e for e in events if e.get("kind") == "agent_message"]


def _board(cond: Conductor, task_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in cond.open_items_of(task_id)]


def _addressing(out: dict[str, Any]) -> dict[str, Any]:
    addr = out.get("addressing")
    assert isinstance(addr, dict), ("回执里没有寻址读数", out)
    return addr


# ---------------------------------------------------------------- a) 歧义 ⇒ 受控拒绝

def test_a_role_code_with_two_instances_is_refused_and_names_the_roster_names(
        tmp_path: pathlib.Path) -> None:
    """判据 a：角色代号 `D` 在册两个 ⇒ 受控拒绝，拒信点名 D1/D2 并给出改写法。

    改前红：改前的拒信是「角色名 D 在你的名册里匹配到 2 个（D1、D2）⇒ 受控拒绝：
    要发给谁：D1 还是 D2（写成名册名或绝对编号就只投那一个；不替你挑一个）」——
    它没有说「在册几个」，也没有把「请写名册名或绝对编号」写成一句可直接照办的话，
    而这一票要的正是那句改写法。拒绝本身改前就在（这一条不是"静默投第一个"）。
    """
    env = _env(tmp_path, same_role_children=2)
    loop, cond, keys = env["loop"], env["cond"], env["kids"]
    assert env["names"] == ["D1", "D2"], env["names"]

    got = loop._do_message({"to": "D", "subject": "题", "body": "文"})

    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "ambiguous_in_roster", got
    assert list(got.get("candidates") or []) == ["D1", "D2"], got
    text = str(got.get("error") or "")
    assert "在册 2 个" in text, ("拒信要说清在册几个", text)
    for name in ("D1", "D2"):
        assert name in text, ("拒信要点名那几个名册名", name, text)
    assert "请写名册名" in text and "绝对编号" in text, ("拒信要给改写法", text)
    # 受控拒绝不许留下半条：板项与收件箱都必须是空的
    for kid in keys:
        assert _board(cond, kid) == [], ("被拒的那一条不许投给谁", kid, _board(cond, kid))
    assert _messages(env["ws"]) == [], ("被拒的那一条不许落 agent_message", _messages(env["ws"]))


def test_a_role_code_with_no_instance_is_refused_and_points_at_the_callable_list(
        tmp_path: pathlib.Path) -> None:
    """判据 a 的第二档：角色代号在册 0 个 ⇒ 受控拒绝（`not_in_roster`），不许静默丢。

    这一档的受控码沿用既有取值（`not_in_roster` 说的就是"不在父∪子里"）——
    同一事实不新造第二个名字；拒信必须点名"你能通话的是"那几个。
    """
    env = _env(tmp_path, same_role_children=1)
    loop, cond, kid = env["loop"], env["cond"], env["kids"][0]

    got = loop._do_message({"to": "E", "subject": "题", "body": "文"})

    assert got.get("ok") is False, got
    assert str(got.get("refused") or "") == "not_in_roster", got
    text = str(got.get("error") or "")
    assert "E" in text and "你能通话的是" in text, text
    assert "D1" in text, ("可通话名单要点名名册名", text)
    assert _board(cond, kid) == [] and _messages(env["ws"]) == [], "被拒的那一条不许落"


# ---------------------------------------------------------------- b) 名册名 ⇒ 那一个

def test_b_a_roster_name_addresses_that_member_and_says_so(
        tmp_path: pathlib.Path) -> None:
    """判据 b：`to=D2` ⇒ 解析到 D2 那一个成员，读数 `addressed_by=roster_name`。

    改前红：投递本身改前就是对的（名册名解析早就落地），红的是读数 ——
    `addressing` 里没有 `addressed_by` 这一格，"按名册名发"与"按角色代号发"分不开。
    """
    env = _env(tmp_path, same_role_children=2)
    loop, cond = env["loop"], env["cond"]
    d1, d2 = env["kids"]

    got = loop._do_message({"to": "D2", "subject": "题", "body": "文"})

    assert got.get("ok") is True, got
    assert str(got.get("to_task_id") or "") == d2, got
    addr = _addressing(got)
    assert str(addr.get("addressed_by") or "") == "roster_name", addr
    assert str(addr.get("name") or "") == "D2" and str(addr.get("task_id") or "") == d2, addr
    assert len(_board(cond, d2)) == 1, _board(cond, d2)
    assert _board(cond, d1) == [], ("只投给那一个：另一个同名实例的板必须是空的", _board(cond, d1))


# ---------------------------------------------------------------- c) 绝对编号 ⇒ 那个实例

def test_c_an_absolute_task_id_addresses_that_instance(tmp_path: pathlib.Path) -> None:
    """判据 c：`to=<D1 的绝对编号>` ⇒ 解析到那个实例，读数 `addressed_by=task_id`。

    改前红：同判据 b —— 红在读数那一格（投递改前就对）。
    """
    env = _env(tmp_path, same_role_children=2)
    loop, cond = env["loop"], env["cond"]
    d1, d2 = env["kids"]

    got = loop._do_message({"to": d1, "subject": "题", "body": "文"})

    assert got.get("ok") is True, got
    assert str(got.get("to_task_id") or "") == d1, got
    addr = _addressing(got)
    assert str(addr.get("addressed_by") or "") == "task_id", addr
    assert str(addr.get("name") or "") == "D1", addr
    assert len(_board(cond, d1)) == 1, _board(cond, d1)
    assert _board(cond, d2) == [], ("只投给那个实例", _board(cond, d2))


# ---------------------------------------------------------------- d) 唯一 ⇒ 兼容解析

def test_d_a_lone_role_code_still_works_and_is_marked_as_a_fallback(
        tmp_path: pathlib.Path) -> None:
    """判据 d（负控：别把兼容一刀切断）：`to=D` 而 D 在册恰好一个 ⇒ 解析到那一个。

    改前红：解析改前就对，红在读数 —— `addressed_by` 这一格不存在，
    于是"这一条是靠角色代号兜到的"在回执上看不出来。
    """
    env = _env(tmp_path, same_role_children=1)
    loop, cond = env["loop"], env["cond"]
    (only,) = env["kids"]
    assert env["names"] == ["D1"], env["names"]

    got = loop._do_message({"to": "D", "subject": "题", "body": "文"})

    assert got.get("ok") is True, got
    assert str(got.get("to_task_id") or "") == only, got
    addr = _addressing(got)
    assert str(addr.get("addressed_by") or "") == "role_fallback", addr
    assert str(addr.get("how") or "") in ("child", "parent"), addr
    assert len(_board(cond, only)) == 1, _board(cond, only)


# ---------------------------------------------------------------- e) 频道语义不动

def test_e_the_public_channel_is_still_a_channel_not_a_person(
        tmp_path: pathlib.Path) -> None:
    """判据 e（负控）：`to=#public` 仍走频道语义，读数 `addressed_by=channel`。

    改前红：红在读数那一格；改后的正控是"它仍然落 `agent_message`（公告栏），
    而不是被寻址判据拦下来或被当成某个代理的私聊"。
    """
    env = _env(tmp_path, same_role_children=2)
    loop, cond = env["loop"], env["cond"]

    got = loop._do_message({"to": "#public", "subject": "公告一句", "body": "正文"})

    assert got.get("ok") is True, got
    addr = _addressing(got)
    assert str(addr.get("addressed_by") or "") == "channel", addr
    assert str(addr.get("how") or "") == "outside_roster", addr
    events = _messages(env["ws"])
    assert len(events) == 1, events
    assert str(events[0].get("to")) == "#public", events[0]
    assert str(events[0].get("channel")) == "public", events[0]
    for kid in env["kids"]:
        assert _board(cond, kid) == [], ("公告栏不是私聊：不许给谁开板项", kid)


# ---------------------------------------------------------------- 附) 政策教的写法真收

def test_the_policy_now_teaches_roster_names_and_the_decoder_accepts_them() -> None:
    """附判据：政策现在教的是名册名 / 绝对编号，解码器对两条通道都真的收。

    改前红：`_decode_shape` 的 `handoff` 那一支只认 `_known_recipient`（角色 / M /
    ALL）⇒ 模型照改后的政策写 `to=D2` 会被判非法。这条判据守的正是"提示词教了什么，
    解码器就得收什么"（同族判据在 `tests/test_agent_prompts.py`）。
    """
    roster = {"D2": {"checked": True, "how": "child", "kind": "child", "name": "D2",
                     "task_id": "t-000002", "role": "D", "brief": "", "candidates": [],
                     "callable": "子 D1（t-000003）", "refused": "", "error": "",
                     "addressed_by": "roster_name", "why": ""}}

    def resolve(to: str) -> dict[str, Any]:
        return dict(roster.get(str(to)) or {"checked": True, "how": "not_in_roster",
                                            "refused": "not_in_roster",
                                            "candidates": [], "callable": "",
                                            "error": f"名册上没有 {to}", "role": "",
                                            "name": "", "task_id": "", "why": ""})

    _key, payload, problem = AL._decode_shape(
        {"handoff": {"to": "D2", "summary": "s", "body": "b"}}, roster=resolve)
    assert problem == "", ("政策教 handoff 写名册名，而解码器不收", problem)
    assert str(payload.get("to")) == "D", ("手稿台账的收件人面仍是角色", payload)
    marker = payload.get("roster_addressing") or {}
    assert marker.get("written") == "D2" and marker.get("task_id") == "t-000002", payload
    assert str(marker.get("addressed_by") or "") == "roster_name", payload

    _key2, payload2, problem2 = AL._decode_shape(
        {"message": {"to": "D2", "subject": "s", "body": "b"}}, roster=resolve)
    assert problem2 == "", problem2
    assert (payload2.get("roster_addressing") or {}).get("addressed_by") == "roster_name", \
        payload2

    # 反真空：名册上没有这个写法时，解码器仍然受控拒绝（不是"一律放行"）
    _k3, p3, problem3 = AL._decode_shape(
        {"message": {"to": "D9", "subject": "s", "body": "b"}}, roster=resolve)
    assert problem3 and p3.get("refused") == "unknown_roster_name", (problem3, p3)


# ---------------------------------------------------------------- f) 政策文案

#: 角色级寻址的三种写法（`to=A–H` / `to=A-H` / `to=<单个角色字母>`）。
#: 刻意的边界：`to=D1` 与 `to=t-000003` 不匹配（字母后面紧跟的是数字或短横接数字），
#: `to=ALL` / `to=M` / `to=#public` 也不匹配 —— 这四种不是"发给某个角色"。
_ROLE_LEVEL_TO = re.compile(r"to\s*=\s*`?([A-H](?:\s*[–\-]\s*[A-H])?)\b")

SPECS_DIR = pathlib.Path(AL.__file__).resolve().parent / "specs"


def test_f_no_policy_text_teaches_a_role_level_recipient() -> None:
    """判据 f：政策文案（`specs/*.py`）里不再出现 `to=A–H` 这类角色级写法。

    反真空：把改前那一句塞回同一份读法里，它必须被认出来（否则这一条抓不住任何东西）。
    """
    sample = "给一个人写 `to=A–H`（或 `M`）"
    assert [m.group(1) for m in _ROLE_LEVEL_TO.finditer(sample)] == ["A–H"], \
        "反真空失效：角色级写法没被认出来"

    offenders: list[str] = []
    for path in sorted(SPECS_DIR.glob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in _ROLE_LEVEL_TO.finditer(line):
                offenders.append(f"{path.name}:{i} to={m.group(1)}")
    assert offenders == [], ("政策里还在教角色级收件人：" + "\n".join(offenders))

    # 反真空第二半：新写法必须真的在政策里（删掉整句也算破 —— 那等于没教）
    text = (SPECS_DIR / "m.py").read_text(encoding="utf-8")
    handed = [ln for ln in text.splitlines() if "交接工作前先写一份手稿" in ln]
    assert len(handed) == 1, ("M 的 handoff 政策那一句找不到了", handed)
    assert "名册名" in handed[0], ("政策要用名册名教收件人", handed[0])
    assert "绝对编号" in handed[0], ("政策要给绝对编号那一种写法", handed[0])


# ---------------------------------------------------------------- 附二) 手稿通道全链

def test_a_handoff_written_to_a_roster_name_lands_on_that_instance(tmp_path: pathlib.Path
                                                                   ) -> None:
    """附二判据：政策教的那种写法在 `handoff` 上从头走到尾 —— 台账按角色、通知按实例。

    改前红：解码器收不下名册名（见上一条），所以这一条路径在改前根本到不了
    `_do_handoff`；改后它必须把"手稿那一行的收件人 = 角色"与"通知落到那个实例的板上"
    这两件事同时做对（实例是 `_handoff_address` 用原写法解析出来的，不是按角色猜的）。
    """
    env = _env(tmp_path, same_role_children=2)
    loop, cond = env["loop"], env["cond"]
    d1, d2 = env["kids"]

    out = loop._do_handoff({"to": "D",
                            "summary": "交给 D2 这一路",
                            "body": "正文",
                            "roster_addressing": {"written": "D2", "name": "D2",
                                                  "task_id": d2, "role": "D",
                                                  "how": "child",
                                                  "addressed_by": "roster_name"}})

    assert out.get("ok") is True, out
    addr = out.get("addressing") or {}
    assert str(addr.get("delivery") or "") == "roster", addr
    assert str(addr.get("to") or "") == "D2", ("寻址问的是原写法", addr)
    assert str(addr.get("name") or "") == "D2" and str(addr.get("task_id") or "") == d2, addr
    assert str(addr.get("addressed_by") or "") == "roster_name", addr
    assert str(addr.get("manuscript_to") or "") == "D", ("手稿台账的收件人面是角色", addr)
    assert len(_board(cond, d2)) == 1, ("通知落到写的那一个实例", _board(cond, d2))
    assert _board(cond, d1) == [], ("另一个同名实例不许收到", _board(cond, d1))


if __name__ == "__main__":                                        # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
