# -*- coding: utf-8 -*-
"""「只读角色」= 对其它智能体的产出只读（业主 2026-11-01 的口径）。

## 口径（业主原话）

> 可以观察到这三个"只读"角色的写工具都是产出自己侧的文件，不会更改其它智能体的产出，
> 所以"只读"的意思是对其它智能体的产出只读。

于是 C / H / V 现行的 `write_local` 件数（H 13 / C 10 / V 9）与这条口径不矛盾；
矛盾的是文案说得太绝对：`specs/c.py` 与 `specs/h.py` 都写着「工具面全量只读
（拿不到任何写工具）」，而 `tools_lines` 自己印着 13 / 10 行 `write_local`；
`STRUCTURE_NOT_PROMPT`（十一格共用）也写着「只读角色拿不到写工具」。

## 三条判据

1. 文案：C / H / V 的渲染提示词里不许再说「拿不到任何写工具」；必须说
   「对其它智能体的产出只读」，并点名**自己侧**的写工具（逐件）。
2. 读数：三家的 `write_local` 集合必须与登记的那一份逐件相同（多一件就是权限面漂了，
   而漂了不会有任何地方报错）。
3. 现场：H 去 ack 一条**别人的**板项 ⇒ 受控拒绝 `not_yours`，一条都不写
   （这就是"不改别人的产出"在板项那一侧的落点）。
"""
from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_prompts as AP                       # noqa: E402
from agentflow.conductor import Conductor, LocalBackend, calling_as  # noqa: E402
from agentflow.store import Store                                # noqa: E402
from agentflow.tools import (                                    # noqa: E402
    ROLES, SIDE_EFFECTS_WRITE, build_registry,
)
from agentflow.tools import conductor_tools as CT               # noqa: E402
from agentflow.tools.base import ToolRegistry                    # noqa: E402

#: 三家的 write_local 逐件（现算于 2026-11-01；H 13 / C 10 / V 9）。
_CLOCK7 = ("clock.alarm_start", "clock.periodic_start", "clock.periodic_stop",
           "clock.timer_cancel", "clock.timer_purpose", "clock.timer_start",
           "clock.wait_any")
_BOOK2 = ("conductor.ack", "conductor.post_task")
EXPECTED: dict[str, tuple[str, ...]] = {
    "C": tuple(sorted(_CLOCK7 + _BOOK2 + ("analysis.register_report",))),
    "H": tuple(sorted(_CLOCK7 + _BOOK2 + (
        "review.record_finding", "review.report", "review.review_document",
        "review.verify_fixes"))),
    "V": tuple(sorted(_CLOCK7 + _BOOK2)),
}
#: 本角色**自己侧**的业务写工具（文案里必须逐件点名）。
OWN_SIDE: dict[str, tuple[str, ...]] = {
    "C": ("analysis.register_report",),
    "H": ("review.review_document", "review.verify_fixes", "review.report",
          "review.record_finding"),
    "V": (),
}
#: 改前那句话（判据要能点名它）。
STALE = "拿不到任何写工具"
RIGHT = "对其它智能体的产出只读"


def _reg():
    return build_registry().registry


def test_the_wording_says_read_only_toward_other_agents() -> None:
    reg = _reg()
    bad: list[str] = []
    for role in ("C", "H", "V"):
        text = AP.system_prompt(role, registry=reg)
        if STALE in text:
            bad.append(f"{role} 还说「{STALE}」—— 它面上有 "
                       f"{len([s for s in reg.for_role(role) if s.side_effect in SIDE_EFFECTS_WRITE])} 件 write_local")
        if RIGHT not in text:
            bad.append(f"{role} 没有「{RIGHT}」这句口径")
        for name in OWN_SIDE[role]:
            if name not in text:
                bad.append(f"{role} 没点名自己侧的写工具 {name}")
    assert not bad, "只读口径没写对：\n  " + "\n  ".join(bad)


def test_the_structure_section_does_not_say_read_only_roles_have_no_write_tools() -> None:
    text = "\n".join(f"{name}：{body}" for name, body in AP.STRUCTURE_NOT_PROMPT)
    assert STALE not in text, f"STRUCTURE_NOT_PROMPT 还说「{STALE}」（十一格共用）"
    assert "自己侧" in text, "STRUCTURE_NOT_PROMPT 没写清「写工具只落在自己侧的产物上」"


def test_the_write_surface_is_exactly_the_registered_one() -> None:
    reg = _reg()
    got = {role: tuple(sorted(s.name for s in reg.for_role(role)
                              if s.side_effect in SIDE_EFFECTS_WRITE))
           for role in ("C", "H", "V")}
    assert got == {role: EXPECTED[role] for role in ("C", "H", "V")}, (
        "C/H/V 的 write_local 面与登记值不一致（权限面漂了）：\n"
        + "\n".join(f"{r}: {sorted(set(got[r]) ^ set(EXPECTED[r]))}" for r in ("C", "H", "V")))


# ---------------------------------------------------------------- 现场：别人的板项
TS = "2026-01-01T00:00:00+00:00"


def _workspace(tmp: pathlib.Path) -> dict:
    root = tmp / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    owner = str(cond.open_top_level_run("M", "夹具：只读角色不许动别人的板项"))
    child = cond._write_new_row({
        "role": "H", "action": "review", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": "fixture:H",
        "status": "running", "outcome": None, "refusal_reason": None,
        "instance": "", "detail": "夹具子代理", "error": None,
        "started_at": TS, "ended_at": None, "tokens": 0, "usd": 0.0,
        "artifacts": [], "inputs": [],
    }, note="fixture:child")
    return {"root": root, "store": store, "cond": cond, "owner": owner,
            "child": str(child)}


def _item(env: dict, to: str, summary: str) -> str:
    return env["cond"].open_item(kind="notice", role="M", expects="ack",
                                 action="notice", summary=summary, called_by="M",
                                 parent_task_id=to, depth=2,
                                 input_key=f"v-verdict@{summary}@v1")


def test_h_acking_somebody_elses_item_is_refused(tmp_path: pathlib.Path) -> None:
    env = _workspace(tmp_path)
    item = _item(env, env["owner"], "这条是给主控的")
    reg = ToolRegistry(name="readonly-scene")
    CT.register(reg, store=env["store"], conductor=env["cond"])
    with calling_as(env["child"], "H"):
        res = reg.call("conductor.ack", role="H", item_ids=[item], note="H 想替主控确认")
    assert res.ok, res.error
    data = res.data or {}
    assert data.get("state") == "refused", data
    assert data.get("acked") == [], data
    assert "not_yours" in (data.get("refusal_codes") or []), data
