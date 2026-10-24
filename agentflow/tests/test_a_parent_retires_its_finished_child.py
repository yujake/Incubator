# -*- coding: utf-8 -*-
"""D-59：父代理发起销号（子代理退场），秘书落实，名册与 UI 接线。

## 业主原话（唯一权威）

```
「父代理似乎没学会回收已用完不会再用的子代理（没见到名册销号），请检查相关代码逻辑和提示词口径，
  销号的发起在父代理，销号的实际动作在秘书侧，请检查接线情况」
「做，并做好和今天名册实现的接线，ui侧显示已销号子代理为画删除线的格式并不再显示收件箱情况」
「对已销号的，名册ui显示默认折叠，只有用户再点击展开再显示」
```

## 链断在哪（这一份守的就是那三处）

`Secretary.retire` 早就写好了（三分支、落 `<父>-retired.jsonl`），`Conductor.retire_ready`
也早就把"哪些子可以销号"算出来了 —— 断的是「发起」那一端：父代理没有任何工具/动作能叫它，
于是名册只增不减。这一份从"父发起"这一端往下钉到"名册读数 / UI"，一整条链：

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| ① `test_a_finished_child_is_retired_by_its_parent` | 子 done 且无未消板项 ⇒ 父调 `conductor.retire_child` ⇒ `-retired.jsonl` 多一行（带理由）、名册该节点 `retired=true` | 工具不存在 ⇒ `unknown_tool` |
| ② `test_a_child_still_in_flight_is_refused_by_name` | 子还在飞 ⇒ 受控拒绝并点名（「销号 ≠ 停止」） | 同上（工具不存在） |
| ③ `test_a_child_with_unread_board_items_is_refused` | 子名下还有 queued 板项 ⇒ 受控拒绝（不许把没读的东西销掉）；收口之后同一笔就能销 | 同上 |
| ④ `test_an_unreadable_ledger_or_roster_is_unknown` | 台账 / 名册读不出来 ⇒ `unknown`（不折成"不可销"） | 同上 |
| ⑤ `test_stubbing_the_secretary_retire_makes_one_red` | 反真空：把 `Secretary.retire` 打桩成空 ⇒ ① 必红 | 不适用（它守①不是真空的那一条） |
| ⑥ `test_the_roster_and_the_closing_reading_agree_after_retiring` | 销号后名册读数与秘书视图对同一个子只数一次（不重复计数） | 同上（工具不存在） |
| ⑦ `test_both_masters_and_researchers_prompts_say_retire_proactively` | M 与 D 的渲染提示词里都读得到"主动销号 + 销号 ≠ 停止"；删掉那条政策 ⇒ 该角色必红 | `specs/*.py` 里一个字都没有 |
| ⑧ `test_the_ui_strikes_through_retired_names_and_hides_the_inbox` | `Roster.tsx`：已销号节点的名字画删除线、行尾挂「已销号」、该分支不渲染收件箱 | 改前名字没删除线、收件箱照渲染 |
| ⑨ `test_a_retired_node_is_collapsed_by_default` | 已销号节点默认 `open=false`（哪怕 depth ≤ 2）；未销号且 depth ≤ 2 仍默认展开 | 改前只看层数 |
| ⑩ `test_a_clicked_open_survives_the_retired_default_collapse` | 用户点过（`openOverride` 置 true）⇒ 该节点仍展开 | 同⑨ |

⑨⑩ 用 `node` + `ui/node_modules/typescript` 把 `Roster.tsx` 里那一个纯函数（`isOpen`）
即时转成 ESM 真跑一遍（口径与 `tests/test_roster_tree_renders_all_nodes.py` 相同）：
Python 这一侧跑不起 Preact，但"默认开不开"本来就不该跟 Preact 绑在一起。

三档口径：没装 node / 依赖没装 ⇒ skip（记 unknown，不记 pass）；转译或跑不起来 ⇒ 红
（那是判据没查成，不是"查过了没问题"）。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from agentflow import agent_prompts as AP
from agentflow import schema as S
from agentflow import specs as SPECS
from agentflow.conductor import Conductor, LocalBackend, calling_as
from agentflow.secretary import Secretary, retired_path, roster_path
from agentflow.store import Store
from agentflow.tools import READ_ONLY_ROLES
from agentflow.tools import conductor_tools as CT
from agentflow.tools.base import ToolRegistry
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"
APP_CSS = UI_SRC / "theme" / "app.css"
TYPESCRIPT_LIB = REPO / "ui" / "node_modules" / "typescript" / "lib" / "typescript.js"

#: 工具名（父代理侧唯一的发起入口）。
TOOL = "conductor.retire_child"

TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具
def _workspace(tmp_path: pathlib.Path) -> dict[str, object]:
    """一个工作区 + 一个主控 + 父那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    # 生产里由 `AgentLoop._bind_roster_sink` 接上；这里显式接，是为了让"销号"与
    # "登记名册"落「同一份」名册文件（否则两条链各读一份名册，判据测的就不是生产形态）。
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：父这一趟"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, owner: str, *, role: str = "D",
           status: str = "done") -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": owner, "depth": 2, "input_key": f"fixture:{role}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理",
        "error": None, "started_at": TS,
        "ended_at": (TS if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _roster(env: dict[str, object], task_id: str, *, role: str = "D",
            brief: str = "写研究报告") -> str:
    """把它登记进父的名册（销号的指称是名册名，所以这一步是前提）。"""
    got = env["sec"].roster_add(owner=str(env["owner"]), role=role, task_id=task_id,
                                brief=brief)
    assert got.get("problem") == "", got
    return str(got["name"])


def _registry(store: Store, cond: Conductor) -> ToolRegistry:
    """只装主控那一组工具（本判据只问这一个工具，不必装配整张面）。"""
    reg = ToolRegistry(name="d59")
    CT.register(reg, store=store, conductor=cond)
    return reg


def _call(env: dict[str, object], task_id: str, *, reason: str = "它交差了我不再用它"):
    """以"父这一趟"的身份调一次销号（`calling_as` 挂上台账号，生产里由 `_do_tool` 挂）。"""
    reg = _registry(env["store"], env["cond"])
    with calling_as(str(env["owner"]), "M"):
        return reg.call(TOOL, role="M", task_id=task_id, reason=reason)


def _retired_rows(env: dict[str, object]) -> list[dict]:
    path = retired_path(str(env["root"]), str(env["owner"]))
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _node_of(face: dict, task_id: str) -> dict:
    return next(n for n in face["nodes"] if str(n["task_id"]) == task_id)


# ====================================================================== ① 可销
def test_a_finished_child_is_retired_by_its_parent(tmp_path: pathlib.Path) -> None:
    """① 子 done 且名下没有未消板项 ⇒ 父调 `conductor.retire_child` ⇒ 真的销掉了。

    四件事一起看，缺一件这条链就断着：
    1. 工具给出 `state=retired`（三态里"可销"那一档）；
    2. `<父>-retired.jsonl` 多一行，且「理由逐字」在里面（销号是父的决定，"为什么"只有父知道）；
    3. 名册读数（`readers.roster_face`）那一格 `retired=true`、`retired_branch` 也读得出来
       —— 这一条同时是 D-59 的第③件（名册读数接线）的判据；
    4. 名册事件流里落的是 `retire` 行（不是只写销号名单就完事）。
    """
    env = _workspace(tmp_path)
    child = _child(env["cond"], str(env["owner"]))
    name = _roster(env, child)
    assert name == "D1", name
    assert _retired_rows(env) == [], "夹具前提：改前一个销号行都没有"

    res = _call(env, child, reason="它交差了，我不再用它")
    assert res.ok, res.error
    data = res.data
    assert data["state"] == "retired", data
    assert data["retired"] is True, data
    assert data["name"] == "D1", data
    assert data["parent_task_id"] == str(env["owner"]), data
    assert data["roster_retired"] is True, data
    assert data["note"] == "它交差了，我不再用它", data

    rows = _retired_rows(env)
    assert len(rows) == 1, rows
    assert rows[0]["name"] == "D1" and rows[0]["task_id"] == child, rows
    assert rows[0]["reason"] == "它交差了，我不再用它", (
        f"销号理由没有逐字落进销号名单：{rows[0]}")
    assert rows[0]["branch"] == "waiting_no_children", rows

    # 名册事件流里那一行（D-59 第③件：与 today 的名册实现接线）
    roster_rows = [json.loads(x) for x in roster_path(
        str(env["root"]), str(env["owner"])).read_text(encoding="utf-8").splitlines() if x.strip()]
    retire_rows = [r for r in roster_rows if str(r.get("kind") or "") == "retire"]
    assert len(retire_rows) == 1, roster_rows
    assert retire_rows[0]["reason"] == "它交差了，我不再用它", retire_rows

    face = R.roster_face(env["root"])
    assert face["answer"] == "ok", face["reason"]
    node = _node_of(face, child)
    assert node["retired"] is True, node
    assert node["retired_branch"] == "waiting_no_children", node
    assert node["name"] == "D1", node


def test_the_tool_is_offered_to_every_role_that_can_be_a_parent() -> None:
    """① 附：可用角色 = 能当父的那些（边表有出边，减去只读角色）。

    ## 为什么这条要机器判
    "谁拿得到销号工具"就是权限面的一格：手写一份名单会在有人加边时静默漏掉那个角色，
    而漏掉的表现是"这个角色看不到工具" —— 不报错，只让那一支的名册越来越长。
    所以期望值从 `specs.edges()` 现算（`capabilities.ALLOWED_EDGES` 的同一份真身）。

    ## 两处排除写在这里，免得被读成遗漏
    `C` 没有出边（不召唤任何人 ⇒ 当不了父）；`H` / `V` 虽然边表里有出边，但它们是只读角色，
    `for_role` 会按 `SIDE_EFFECTS_WRITE` 把写工具结构性剥掉（本件真写名册与台账）。
    """
    edges = SPECS.edges()
    expected = {r for r, out in edges.items() if out} - set(READ_ONLY_ROLES)
    reg = ToolRegistry(name="d59-face")
    CT.register(reg)
    got = {r for r in (*S.ROLES, S.CONDUCTOR_ROLE) if TOOL in {s.name for s in reg.for_role(r)}}
    assert got == expected, f"销号工具的角色面是 {sorted(got)}，期望 {sorted(expected)}"
    # 反真空：业主点名的四个角色都要在里面（至少 M、D、F、G）
    assert {"M", "D", "F", "G"} <= got, got
    # 只读角色一个都不许拿到它（它们不是"忘了"，是结构上不许写）
    assert not (got & set(READ_ONLY_ROLES)), got


# ====================================================================== ② 还在飞
def test_a_child_still_in_flight_is_refused_by_name(tmp_path: pathlib.Path) -> None:
    """② 子还在飞 ⇒ 受控拒绝并点名；理由里写清「销号 ≠ 停止」。

    销号是"它交完了、名字永久不复用"，停止/叫停是"让它此刻停下来"。把两者混起来
    的代价：一个还在跑的子代理名字先被销掉，活还在跑（`member_retired` 之后再叫不醒它）。
    """
    env = _workspace(tmp_path)
    child = _child(env["cond"], str(env["owner"]), role="E", status="running")
    _roster(env, child, role="E", brief="跑实验")

    res = _call(env, child, reason="想销")
    assert res.ok, res.error
    data = res.data
    assert data["state"] == "refused", data
    assert data["retired"] is False, data
    assert data["branch"] == "active", data
    assert any(child in m and "还在跑" in m for m in data["missing"]), data
    assert "status=running" in data["reason"], data
    assert "销号 ≠ 停止" in data["reason"], data
    assert _retired_rows(env) == [], "被拒绝时一行都不许写销号名单"


# ====================================================================== ③ 未消板项
def test_a_child_with_unread_board_items_is_refused(tmp_path: pathlib.Path) -> None:
    """③ 子名下还有 queued 板项 ⇒ 受控拒绝（不许把没读的东西销掉）。

    负控的负控：把那条板项收口（`item_state=done`）之后，同一笔就能销 ——
    否则这条判据证明不了"是板项挡住了它"，只证明"它一律拒绝"。
    """
    env = _workspace(tmp_path)
    child = _child(env["cond"], str(env["owner"]), role="F", status="done")
    _roster(env, child, role="F", brief="攻坚")
    item = env["cond"].open_item(kind="notice", role="F", expects="ack", action="notice",
                                 summary="一条没消的通知", called_by="M",
                                 parent_task_id=child, depth=3)

    res = _call(env, child, reason="想销")
    assert res.ok, res.error
    data = res.data
    assert data["state"] == "refused", data
    assert data["retired"] is False, data
    assert data["branch"] == "waiting_no_children", data
    assert [x["task_id"] for x in data["open_items"]] == [item], data
    assert data["open_items"][0]["item_state"] == "queued", data
    assert any(item in m for m in data["missing"]), data
    assert "未消的板项" in data["reason"], data
    assert _retired_rows(env) == [], "被拒绝时一行都不许写销号名单"

    # 负控的负控：把它读进来并收口之后，同一笔能销
    # （`close_item(close="acked")` 对"从没被读过的项"是受控拒绝：空口 ack 不推进状态 ——
    #  所以这里照真实循环的次序走一遍：先 `mark_item_seen`，再 ack。）
    env["cond"].mark_item_seen(item, by_task_id=child, step=1)
    closed, why = env["cond"].close_item(item, close="acked", by_task_id=child)
    assert closed == "done" and why == "", (closed, why)
    again = _call(env, child, reason="那一条收口了，可以销了")
    assert again.ok, again.error
    assert again.data["state"] == "retired", again.data
    assert len(_retired_rows(env)) == 1, _retired_rows(env)


# ====================================================================== ④ 读不到
def test_an_unreadable_ledger_or_roster_is_unknown(tmp_path: pathlib.Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 台账 / 名册读不出来 ⇒ `unknown`（不折成"不可销"）。

    三态纪律：`refused` 说的是"查过了、现在不能销"（父该等/该收口），`unknown` 说的是
    "这一格没读成"（父该重读一次）。折成同一句话的代价：一次读盘故障会让父以为
    "它还不到时候"，于是它永远不销 —— 那正是 D-59 的原始症状换个理由再来一遍。
    """
    # 4a：台账读不出来
    env = _workspace(tmp_path / "a")
    child = _child(env["cond"], str(env["owner"]))
    _roster(env, child)

    def _boom(table: str, **kw: object):  # noqa: ANN001, ARG001
        raise RuntimeError("台账坏了")

    monkeypatch.setattr(env["store"], "rows", _boom, raising=True)
    res = _call(env, child, reason="想销")
    assert res.ok, res.error
    assert res.data["state"] == "unknown", res.data
    assert res.data["checked"] is False, res.data
    assert "台账读不成" in res.data["reason"], res.data
    assert _retired_rows(env) == [], "读不到台账时一行都不许写"
    monkeypatch.undo()

    # 4b：名册对照表读不出来（销号要按名册名指称，读不出来就是没查成）
    env2 = _workspace(tmp_path / "b")
    child2 = _child(env2["cond"], str(env2["owner"]))
    _roster(env2, child2)
    index = pathlib.Path(str(env2["root"])) / "out" / "roster" / f"{env2['owner']}-index.jsonl"
    with index.open("a", encoding="utf-8") as fh:
        fh.write("{这不是一行 json\n")
    res2 = _call(env2, child2, reason="想销")
    assert res2.ok, res2.error
    assert res2.data["state"] == "unknown", res2.data
    assert "名册" in res2.data["reason"], res2.data
    assert _retired_rows(env2) == [], "名册读不出来时一行都不许写"


# ====================================================================== ⑤ 反真空
def test_stubbing_the_secretary_retire_makes_one_red(tmp_path: pathlib.Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把 `Secretary.retire` 打桩成空 ⇒ ① 必红。

    这条守的是"父发起之后，落实真的发生在秘书那一侧"：如果这个工具自己拼了一份
    销号名单（而不是叫秘书），把秘书打桩掉它照样绿 —— 那正好是"两处各写一份名册"
    的形态（本项目的重复实现病）。打完桩之后 ① 的四件事一件都不许成立。
    """
    env = _workspace(tmp_path)
    child = _child(env["cond"], str(env["owner"]))
    _roster(env, child)
    real = Secretary.retire

    def _stub(self, **kw: object) -> dict:  # noqa: ANN001, ARG001
        return {}

    monkeypatch.setattr(Secretary, "retire", _stub)
    res = _call(env, child, reason="想销")
    assert res.ok, res.error
    assert res.data["state"] != "retired", res.data
    assert res.data["retired"] is False, res.data
    assert _retired_rows(env) == [], "秘书被打桩之后仍然写出了销号名单 ⇒ 工具自己拼了一份"
    assert _node_of(R.roster_face(env["root"]), child)["retired"] is False

    # 还原之后同一笔必须真的销掉（否则上面那条只能证明"从来没成功过"）
    monkeypatch.setattr(Secretary, "retire", real)
    again = _call(env, child, reason="想销")
    assert again.data["state"] == "retired", again.data
    assert len(_retired_rows(env)) == 1


# ====================================================================== ⑥ 不重复计数
def test_the_roster_and_the_closing_reading_agree_after_retiring(
        tmp_path: pathlib.Path) -> None:
    """⑥ 销号后"收工读数"与名册一致（同一个子只数一次，不重复计数）。

    销号会在三份台账里各落一行（名册 `retire` / 对照表 `retire` / 销号名单），
    读侧的口径是折叠成"一项一条"。重复计数的形态有两种，都在这里钉住：
    - 名册视图（`Secretary.roster_view`，收工时父看的那一份）里同一个名字出现两次；
    - 名册读数（`roster_face`）里同一个编号出现两次，或 `coverage` 与 `count` 对不上
      （那会让"名册上几人 / 台账里几个"这句收工读数自己打脸）。

    另一条要一起读的读数：销号之后 `retire_ready` 不再把它当候选 —— 否则"还能销几个"
    与"已经销了"会同时算它。
    """
    env = _workspace(tmp_path)
    child = _child(env["cond"], str(env["owner"]))
    _roster(env, child)
    before = env["cond"].retire_ready(str(env["owner"]))
    assert [r["task_id"] for r in before["ready"]] == [child], before

    res = _call(env, child, reason="交差了")
    assert res.data["state"] == "retired", res.data

    after = env["cond"].retire_ready(str(env["owner"]))
    assert after["checked"] is True, after
    assert child not in [r["task_id"] for r in after["ready"]], (
        f"销号之后它还在可销清单里 ⇒ 收工读数与名册各数一遍：{after}")

    view = env["sec"].roster_view(owner=str(env["owner"]))
    assert view["checked"] is True, view
    named = [r for r in view["rows"] if r["name"] == "D1"]
    assert len(named) == 1, f"名册视图里 D1 出现了 {len(named)} 次（重复计数）：{view['rows']}"
    assert named[0]["status"] == "retired", named[0]
    assert named[0]["retirable"] is False, named[0]

    face = R.roster_face(env["root"])
    ids = [str(n["task_id"]) for n in face["nodes"]]
    assert ids.count(child) == 1, f"名册读数里 {child} 出现了 {ids.count(child)} 次"
    assert face["count"] == len(face["nodes"]), face["count"]
    assert face["coverage"]["roster_nodes"] == face["count"], face["coverage"]
    assert face["coverage"]["unrostered"] == 0, face["coverage"]
    # 销号名单自己也只有一行（append-only，不重写）
    assert len(_retired_rows(env)) == 1


# ====================================================================== ⑦ 提示词口径
#: 这两句是判据要读到的两个语义（不是措辞洁癖）：①父要「主动」销；②销号不是停止。
_NEEDLES = ("主动销号", "销号 ≠ 停止")
_NEEDLE_CONTEXT = {
    "主动销号": "没写『主动销号』⇒ 父只会等别人来收，名册只增不减（D-59 的原始症状）",
    "销号 ≠ 停止": "没写『销号 ≠ 停止』⇒ 容易被读成『销号就是停掉它』，"
                "于是父会拿销号去停一个还在跑的子代理（名字先没了、活还在跑）",
}


def _prompt(role: str) -> str:
    """真渲染一遍这个角色的提示词（纯函数，零模型调用）。"""
    from agentflow.tools import build_registry

    return AP.system_prompt(role, registry=build_registry().registry,
                            task="夹具任务", workspace_root=str(REPO))


def _missing_needles(text: str) -> list[str]:
    return [n for n in _NEEDLES if n not in text]


def test_both_masters_and_researchers_prompts_say_retire_proactively(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑦ M 与 D 的渲染提示词里都读到"主动销号 + 销号 ≠ 停止"；删掉那条政策 ⇒ 该角色必红。

    为什么是这两个角色，而且「只」是它们：M 是所有支的根、D 是研究侧的主导者，
    它们的出边最多（`M→A/B/C/D/E/G/H`、`D→A/B/C/E/F`）—— 名册变长主要发生在它们名下。
    政策写在 `specs/m.py` / `specs/d.py` 的 `brief.policy`（渲染进 `ROLE_POLICY` 那一段），
    与工具名 `conductor.retire_child` 一起出现在提示词里。

    反真空（逐角色）：把那条政策从 `ROLE_BRIEFS` 里摘掉之后重新渲染，那个角色必须红。
    没有这一条，⑦ 可能只是因为"工具那一行里恰好有这两个词"而绿着。
    """
    from agentflow.tools import build_registry

    registry = build_registry().registry
    for role in ("M", "D"):
        text = AP.system_prompt(role, registry=registry, task="夹具任务",
                                workspace_root=str(REPO))
        assert _missing_needles(text) == [], (
            f"{role} 的提示词里读不到 {_missing_needles(text)}："
            + "；".join(_NEEDLE_CONTEXT[n] for n in _missing_needles(text)))
        assert TOOL in text, f"{role} 的提示词里没有点名 {TOOL} ⇒ 模型不知道怎么销号"

        # 反真空：把这一条政策从渲染源里摘掉 ⇒ 同一份判据必须红
        brief = AP.ROLE_BRIEFS[role]
        kept = tuple(x for x in brief.policy if "主动销号" not in x)
        assert len(kept) < len(brief.policy), (
            f"{role} 的 brief.policy 里找不到那条销号政策（夹具前提变了）")
        AP.ROLE_BRIEFS[role] = dataclasses.replace(brief, policy=kept)
        try:
            stripped = AP.system_prompt(role, registry=registry, task="夹具任务",
                                        workspace_root=str(REPO))
        finally:
            AP.ROLE_BRIEFS[role] = brief
        assert "主动销号" not in stripped, (
            f"摘掉政策之后 {role} 的提示词里还有『主动销号』⇒ 那句话来自别处，"
            "这条判据证明不了政策进了提示词")
        assert _missing_needles(stripped), (
            f"把销号政策从 {role} 的 brief 里摘掉，判据却仍然绿 ⇒ 这条判据是橡皮图章")


# ====================================================================== ⑧ UI 结构
def _flat(text: str) -> str:
    """把连续空白压成一个空格（缩进/换行怎么变都不影响源码判据）。

    为什么不是"去掉全部空白"：JSX 里 `class="roster-name roster-retired"` 那个空格是
    字符串内容的一部分，去掉它就成了另一个类名 —— 判据会变成看谁猜得中拼写。
    """
    return re.sub(r"\s+", " ", text).strip()


def _ui_problems(tsx: str, css: str) -> list[str]:
    """⑧ 的三件事：删除线、行尾「已销号」、该分支不渲染收件箱。

    每一条都对得上一个具体的失败形态：
    - 名字没有删除线 ⇒ 读的人分不出"已销号"与"还在职"（业主点名要删除线）；
    - 没有「已销号」标识 ⇒ 只能靠删除线猜（细线在暗色下几乎看不见）；
    - 已销号的行/明细还渲染收件箱 ⇒ 给一个已经退场的名字算未读（"销号即退场"没落地）。
    """
    flat = _flat(tsx)
    problems: list[str] = []
    if 'roster-name roster-retired' not in flat:
        problems.append("已销号节点的名字没有挂 `roster-retired` 这个类（名字没画删除线）")
    if 'text="已销号"' not in flat:
        problems.append("行尾没有「已销号」标识（`text=\"已销号\"`）")
    if not re.search(r"node\.retired \? null : inboxBadge\(node\.inbox\)", flat):
        problems.append("已销号的行仍然渲染收件箱那一格（`inboxBadge(node.inbox)` 没被 retired 挡住）")
    if not re.search(r"n\.retired \? \(.*?\) : \( <InboxBlock inbox=\{n\.inbox\} /> \)", flat):
        problems.append("已销号节点的明细里仍然渲染 `InboxBlock`（收件箱不该再显示）")
    if not re.search(r"\.roster-retired \{[^}]*text-decoration: line-through", _flat(css)):
        problems.append("`app.css` 里没有 `.roster-retired { text-decoration: line-through }`")
    return problems


def test_the_ui_strikes_through_retired_names_and_hides_the_inbox() -> None:
    """⑧ `Roster.tsx`：删除线 + 「已销号」标识 + 该分支不渲染收件箱（附 CSS 那一条）。

    四条负控逐条打在源码文本上（删掉那一处 ⇒ 判据必须红），否则这条判据只是
    "文件里有几个字"的橡皮图章。
    """
    tsx = ROSTER_TSX.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")
    assert _ui_problems(tsx, css) == [], _ui_problems(tsx, css)

    # 负控①：名字那一格不再区分 retired ⇒ 删除线没了
    assert _ui_problems(tsx.replace("roster-name roster-retired", "roster-name"), css), (
        "把删除线那个类去掉，判据却一声不吭")
    # 负控②：行尾标识没了
    assert _ui_problems(tsx.replace('text="已销号"', 'text="已退役"'), css), (
        "把「已销号」标识改回旧措辞，判据却一声不吭")
    # 负控③：收件箱那一格不再被 retired 挡住
    assert _ui_problems(tsx.replace("node.retired ? null : inboxBadge(node.inbox)",
                                    "inboxBadge(node.inbox)"), css), (
        "取消行里那条 retired 遮挡，判据却一声不吭")
    # 负控④：CSS 里那条删除线被删
    assert _ui_problems(tsx, css.replace("text-decoration: line-through;", "")), (
        "删掉 CSS 里的 line-through，判据却一声不吭")


# ====================================================================== ⑨⑩ 默认折叠
_TRANSPILE_JS = r"""
const ts = require(process.argv[1]);
const fs = require("node:fs");
const path = require("node:path");
const src = fs.readFileSync(process.argv[2], "utf8");
const out = ts.transpileModule(src, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
                     isolatedModules: true },
  fileName: path.basename(process.argv[2]),
}).outputText;
fs.writeFileSync(process.argv[3], out, "utf8");
"""

_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, payloadPath] = process.argv.slice(2);
const mod = await import(pathToFileURL(modulePath).href);
const payload = JSON.parse(readFileSync(payloadPath, "utf8"));
const out = [];
for (const c of payload.cases) {
  for (const [k, v] of Object.entries(c.override ?? {})) mod.openOverride.set(k, v);
  out.push(mod.isOpen({ task_id: c.task_id, depth: c.depth, retired: c.retired }));
  mod.openOverride.delete(c.task_id);
}
process.stdout.write(JSON.stringify({ open: out, default_depth: mod.DEFAULT_OPEN_DEPTH }));
"""


def _node_exe() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("没装 node ⇒ 前端默认折叠这一层记 unknown（不记 pass）")
    return node


def _extract_block(source: str, header: str) -> str:
    """从 TSX 源码里抠出一段（`header` 起到配对的 `}` 止）。

    括号配平是"数到深度归零"，不是"找下一个 }"：`isOpen` 里现在只有一个 if 块，
    但改成嵌套判断时后者会截出半段，而那半段在转译期就炸 —— 报错指向这一行，
    读的人立刻知道是抠取器坏了，而不是被误判成"默认折叠没实现"。
    """
    start = source.find(header)
    assert start >= 0, f"`Roster.tsx` 里找不到 `{header}`（实现改名了？这条判据的抠取点要跟着改）"
    brace = source.find("{", start)
    assert brace >= 0, f"`{header}` 后面没有函数体"
    depth = 0
    for i in range(brace, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"`{header}` 的括号没有配平（源码被截断了？）")


def _open_module(tmp_path: pathlib.Path) -> pathlib.Path:
    """把 `Roster.tsx` 里那一个纯函数（`isOpen`）转成 ESM。

    只抠三样东西：那个常量、那个模块级 `openOverride`、那个函数 —— 组件本体不进来
    （它 import preact 与一堆视图模块，判据跑不起也不该跑）。于是"默认开不开"
    这一层可以在真源码上被判据直接跑。
    """
    source = ROSTER_TSX.read_text(encoding="utf-8")
    depth_const = re.search(r"const DEFAULT_OPEN_DEPTH = \d+;", source)
    assert depth_const is not None, "`Roster.tsx` 里没有 `const DEFAULT_OPEN_DEPTH = N;`"
    fn = _extract_block(source, "function isOpen(")
    module = (
        "interface RosterNode { task_id: string; depth: number; retired: boolean }\n"
        "const openOverride: Map<string, boolean> = new Map();\n"
        f"{depth_const.group(0)}\n"
        f"{fn}\n"
        "export { isOpen, openOverride, DEFAULT_OPEN_DEPTH };\n"
    )
    ts_path = tmp_path / "rosterIsOpen.ts"
    ts_path.write_text(module, encoding="utf-8")
    out = tmp_path / "rosterIsOpen.mjs"
    node = _node_exe()
    if not TYPESCRIPT_LIB.is_file():
        pytest.skip("前端依赖没装（ui/node_modules/typescript 不在）⇒ 记 unknown（不记 pass）")
    proc = subprocess.run([node, "-e", _TRANSPILE_JS, str(TYPESCRIPT_LIB),
                           str(ts_path), str(out)],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, (
        "把 `Roster.tsx` 里的 `isOpen` 转成 ESM 失败（exit "
        f"{proc.returncode}）：{((proc.stderr or '') + (proc.stdout or ''))[:800]}")
    return out


def _run_is_open(cases: list[dict], tmp_path: pathlib.Path) -> dict:
    """把一组 `{task_id, depth, retired, override?}` 喂给真源码里那个函数。"""
    module = _open_module(tmp_path)
    payload = tmp_path / "isopen-cases.json"
    payload.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
    runner = tmp_path / "isopen-runner.mjs"
    runner.write_text(_RUNNER_JS, encoding="utf-8")
    proc = subprocess.run([_node_exe(), str(runner), str(module), str(payload)],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, (
        f"`isOpen` 在真源码上跑不起来（exit {proc.returncode}）："
        f"{((proc.stderr or '') + (proc.stdout or ''))[:1200]}")
    return json.loads(proc.stdout)


def test_a_retired_node_is_collapsed_by_default(tmp_path: pathlib.Path) -> None:
    """⑨ 已销号节点默认 `open=false`（哪怕 depth ≤ 2）；未销号且 depth ≤ 2 默认 `open=true`。

    业主原话：「对已销号的，名册 ui 显示默认折叠，只有用户再点击展开再显示」。
    "不论在第几层"这一条是刻意的：`DEFAULT_OPEN_DEPTH = 2` 是"当班那几行"的折叠口径，
    而销号节点代表的是"退场之前那一支" —— 它铺开会把当班那几行挤下去。

    负控：未销号且 depth ≤ 2 必须默认展开（别把"默认折叠"做成"默认全折"）。
    """
    out = _run_is_open([
        {"task_id": "t-r1", "depth": 1, "retired": True},
        {"task_id": "t-r2", "depth": 2, "retired": True},
        {"task_id": "t-r3", "depth": 3, "retired": True},
        {"task_id": "t-a1", "depth": 1, "retired": False},
        {"task_id": "t-a2", "depth": 2, "retired": False},
        {"task_id": "t-a3", "depth": 3, "retired": False},
    ], tmp_path)
    assert int(out["default_depth"]) == 2, out
    got = out["open"]
    assert got[:3] == [False, False, False], (
        f"已销号节点默认不是折叠的：{got[:3]}（第 1/2/3 层都该折）")
    assert got[3:5] == [True, True], (
        f"未销号且 depth ≤ 2 的节点默认该展开，实际 {got[3:5]}")
    assert got[5] is False, f"未销号 depth=3 仍应按层数折叠，实际 {got[5]}"


def test_a_clicked_open_survives_the_retired_default_collapse(tmp_path: pathlib.Path) -> None:
    """⑩ 用户点过之后（`openOverride` 置 true）⇒ 该节点仍展开。

    业主要的是"默认折叠 + 点了才展开"，不是"永远折着"。判定次序因此是
    先看 `openOverride`、再看 retired、最后才是层数 —— 反过来写会让"默认折叠"
    把用户刚点开的那个节点又折回去（每一次读数刷新都折一次）。
    """
    out = _run_is_open([
        {"task_id": "t-r1", "depth": 2, "retired": True, "override": {"t-r1": True}},
        {"task_id": "t-r2", "depth": 3, "retired": True, "override": {"t-r2": True}},
        {"task_id": "t-a3", "depth": 3, "retired": False, "override": {"t-a3": False}},
    ], tmp_path)
    got = out["open"]
    assert got[0] is True and got[1] is True, (
        f"用户点开过的已销号节点又被默认折叠吃掉了：{got}")
    assert got[2] is False, f"用户手动收起过的节点又被默认展开吃掉了：{got}"
