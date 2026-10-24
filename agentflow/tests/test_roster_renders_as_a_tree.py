# -*- coding: utf-8 -*-
"""名册按树展开（业主 2026-10-24：「名册按树展开，不只是简单按层展开。」）。

## 改前是什么形态（截图 `draft/QQ截图20261024175641.png`）

`GET /api/roster` 的 `nodes` 是按层（BFS）排的：`d1 / d2 d2 d2 / d3 ... / d4 ...`，
前端拿 `depth` 现算左缩进就画成了"按层平铺的列表"。同一个名册名（F1 / B1 / V1）
在 d3 与 d4 各出现一次，而它们分属不同的父 —— 读的人看不出"谁是谁的子"。

盘上的事实一直是"一个父一份名册"：`out/roster/<父编号>.jsonl`，文件里每一行是
这个父名下的一个子。所以树不是"从层号推出来的"，它就是从那份文件里读出来的。

## 这一份守什么

| 判据 | 它守的是 | 改前红在哪 |
|---|---|---|
| ① `test_the_reader_returns_a_parent_to_children_tree_*` | reader 给出一份按父子分组的结构（键 = 父的绝对编号），父子与深度互相自洽 | 改前 `children_of` 不存在（只有按层的 `nodes`） |
| ② `test_the_children_keep_the_landing_order_*` | 同一个父的多个子 == 落盘行序，不是按名册名重排 | 改前 `_fold_roster` 按名字排序，C1 排在 F1 前面 |
| ③ `test_the_tree_is_collapsed_to_two_levels_by_default` | 前端默认展开到第 2 层，第 3 层节点默认折叠，且展开态在本次浏览内保持 | 改前前端没有折叠口径（整棵树一次铺开） |
| ④ `test_a_flat_stub_of_the_parent_child_relation_is_caught` | 反真空：把父子关系打桩成"全部挂根下" ⇒ ① 的判据必须红 | 改前 ① 本身就红（`children_of` 不存在），打桩前后都红 |

## 为什么③是源码判据

"默认展开几层"是纯前端的一件事：后端给的是整棵树（含深度），折叠与否是渲染时的
选择。Python 这一侧跑不起 Preact，所以这条判据钉前端源码里的那个常量与那条判据式
（`node.depth <= DEFAULT_OPEN_DEPTH`），并配三条负控：把 2 改成 3、把判据式换成
写死的数、把按 `children_of` 的递归渲染删掉 —— 三种形态都必须当场红。
本仓库对"只活在前端的事实"一直是这条口径（`tests/test_webui_roster_panel.py` 的判据④）。

## 夹具为什么故意让名字顺序与行序相反

`Secretary.roster_add` 给名字是按角色字母发的（F → F1、C → C1、V → V1、B → B1）。
夹具按"先 F 后 C"、"先 V 后 B"的顺序落盘，于是：

- 落盘行序 = `[F1, C1]`、`[V1, B1]`；
- 按名册名排序 = `[C1, F1]`、`[B1, V1]`。

两种口径给出的顺序正好相反，②才有区分力（都写成同序的话，重排过的实现也照样绿）。
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any, Mapping

import pytest

from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"

#: 夹具的根绝对编号（`t-000001` 是名册文件的主人，它不在任何人的名册里）。
ROOT_ID = "t-000001"

#: 期望的那棵树（父 → 它的直接子，按落盘行序）。
#: 根（t-000001）两子：先 F1（t-000003）后 C1（t-000002）；
#: F1（t-000003）两孙：先 V1（t-000004）后 B1（t-000005）。
EXPECTED_CHILDREN: dict[str, list[str]] = {
    ROOT_ID: ["t-000003", "t-000002"],
    "t-000003": ["t-000004", "t-000005"],
}

#: 前端那个"默认展开到第几层"的常量与取值（第 3 层节点默认折叠）。
OPEN_DEPTH = 2


# ====================================================================== 夹具
def _tree_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """造一棵三层树：1 个父、2 个子、其中一子 2 个孙。

    落点与行序都由写侧（`Secretary.roster_add`）决定 —— 手抄 JSONL 等于把盘上格式
    再定义一遍，两处迟早漂移（与 `tests/test_webui_roster_panel.py` 同一条理由）。
    """
    root = tmp / "ws"
    root.mkdir()
    Store(root).init()
    store = Store(root)
    sec = Secretary("M", root=root, store=store)
    adds = (
        # 根的两行：先 F 的（F1 = t-000003），后 C 的（C1 = t-000002）。
        (ROOT_ID, "F", "t-000003", "攻主命题的引理"),
        (ROOT_ID, "C", "t-000002", "梳理证明链"),
        # 其中一子（F1）的两行：先 V 的（V1 = t-000004），后 B 的（B1 = t-000005）。
        ("t-000003", "V", "t-000004", "核这一段的引文"),
        ("t-000003", "B", "t-000005", "把命题登记进台账"),
    )
    for owner, role, task_id, brief in adds:
        got = sec.roster_add(owner=owner, role=role, task_id=task_id, brief=brief)
        assert got["problem"] == "", got
        assert got["task_id"] == task_id, got
    return root


def _disk_children(root: pathlib.Path, owner: str) -> list[str]:
    """盘上 `<owner>.jsonl` 里那些子的绝对编号，按行序（去重保序）。

    这是"落盘行序"的唯一真身：判据 ② 拿它当期望值，而不是把顺序抄一份进测试。
    """
    path = root / "out" / "roster" / f"{owner}.jsonl"
    assert path.is_file(), f"夹具没有落出 {path}"
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        tid = str(row.get("task_id") or "")
        if tid and tid not in out:
            out.append(tid)
    return out


# ====================================================================== ① 的判据本身
def _tree_problems(face: Mapping[str, Any],
                   expected: Mapping[str, list[str]]) -> list[str]:
    """树形结构的判据：`children_of` 必须按父子分组，且与 `nodes` 互相自洽。

    逐条：
    1. `children_of` 在、是 `{父编号: [子编号...]}`（键是绝对编号，不是 `d1` 那样的层标签）；
    2. 每个父、每个子都在 `nodes` 里，且子的 `parent_task_id` 就是那个父、
       子的 `depth` = 父的 `depth` + 1（按层分组的口径在这里过不去）；
    3. 每个非根节点恰好作为某个父的子出现一次（既不许漏、也不许挂两处）；
    4. 与 `expected` 逐键逐项相等（父 → 子，按落盘行序）。
    """
    problems: list[str] = []
    by_id = {str(n.get("task_id") or ""): n for n in face.get("nodes") or []}
    children_of = face.get("children_of")
    if not isinstance(children_of, dict):
        problems.append(f"没有 children_of 这个形状（读数：{type(children_of).__name__}）")
        return problems
    if not children_of:
        problems.append("children_of 是空的 ⇒ 树形结构没有落脚点")
    seen_as_child: dict[str, int] = {}
    for parent, kids in children_of.items():
        if not isinstance(kids, list) or not kids:
            problems.append(f"{parent!r} 的子不是非空数组（{kids!r}）")
            continue
        if parent not in by_id:
            problems.append(f"children_of 的键 {parent!r} 不是任何一个节点的编号"
                            "（按层分组的形状会在这里露出来）")
            continue
        parent_node = by_id[parent]
        for kid in kids:
            kid = str(kid)
            if kid not in by_id:
                problems.append(f"{parent} 的子 {kid!r} 不在 nodes 里")
                continue
            if str(by_id[kid].get("parent_task_id") or "") != parent:
                problems.append(
                    f"{kid} 挂在 {parent} 名下，而它自己的 parent_task_id 是 "
                    f"{by_id[kid].get('parent_task_id')!r}")
            want = int(parent_node.get("depth") or 0) + 1
            if int(by_id[kid].get("depth") or 0) != want:
                problems.append(
                    f"{kid} 的 depth 是 {by_id[kid].get('depth')}，按父（{parent}，"
                    f"depth={parent_node.get('depth')}）应当是 {want}")
            seen_as_child[kid] = int(seen_as_child.get(kid) or 0) + 1
    for tid, k in sorted(seen_as_child.items()):
        if k > 1:
            problems.append(f"{tid} 同时挂在 {k} 个父名下（一个子只该有一个父）")
    roots = [str(x) for x in face.get("roots") or []]
    for tid in by_id:
        if tid in roots:
            if tid in seen_as_child:
                problems.append(f"根 {tid} 又是别人的子 ⇒ 根的口径与 children_of 打架")
            continue
        if tid not in seen_as_child:
            problems.append(f"{tid} 既不是根、也不在任何父名下 ⇒ 它从树上走不到")
    want_keys = {k for k, v in expected.items() if v}
    if set(children_of) != want_keys:
        problems.append(f"children_of 的键是 {sorted(children_of)}，应当是 {sorted(want_keys)}")
    for parent, kids in expected.items():
        got = [str(x) for x in (children_of.get(parent) or [])]
        if got and got != list(kids):
            problems.append(f"{parent} 的子是 {got}，按落盘行序应当是 {list(kids)}")
    return problems


def test_the_reader_returns_a_parent_to_children_tree(tmp_path: pathlib.Path) -> None:
    """判据①：reader 给出按父子分组的结构，父子与深度互相自洽（不是按层分组）。

    正控读的是 `roster_face` 的真读数（夹具三层树）；反面对照是把同一个读数里的
    `children_of` 换成"按层分组"的形状（`d1` / `d2` 当键）—— 同一个判据必须当场红。
    """
    face = R.roster_face(_tree_workspace(tmp_path))
    assert face["answer"] == "ok", face["reason"]
    problems = _tree_problems(face, EXPECTED_CHILDREN)
    assert problems == [], problems
    assert set(face["children_of"]) == {ROOT_ID, "t-000003"}, sorted(face["children_of"])
    assert all(k.startswith("t-") for k in face["children_of"]), sorted(face["children_of"])
    # 三层（根 = 1），五个节点 —— 与上面那棵树的形状对得上。
    assert (face["count"], face["max_depth"]) == (5, 3), (face["count"], face["max_depth"])
    assert face["roots"] == [ROOT_ID], face["roots"]

    # 反面对照：把父子关系改成"按层分组"（键是层标签）⇒ 同一个判据必红。
    by_layer = dict(face)
    by_layer["children_of"] = {"d1": ["t-000003", "t-000002"],
                               "d2": ["t-000004", "t-000005"]}
    assert _tree_problems(by_layer, EXPECTED_CHILDREN), (
        "按层分组的形状被当成了树 ⇒ ① 的判据分不出「谁是谁的子」")


# ====================================================================== ② 行序
def test_the_children_keep_the_landing_order_not_the_name_order(
        tmp_path: pathlib.Path) -> None:
    """判据②：同一个父的多个子按落盘行序排，不按名册名重排。

    期望值从盘上读（`<父>.jsonl` 的行序），不从实现里抄；再拿"按名册名排序"的
    结果对照一次，证明这两种口径在这份夹具上确实相反（否则这条判据没有区分力）。
    """
    root = _tree_workspace(tmp_path)
    face = R.roster_face(root)
    names = {str(n["task_id"]): str(n["name"]) for n in face["nodes"]}
    for owner, task_ids in (("t-000001", ["t-000003", "t-000002"]),
                            ("t-000003", ["t-000004", "t-000005"])):
        disk = _disk_children(root, owner)
        assert disk == task_ids, ("夹具前提变了：落盘行序不是预期的那个", disk)
        got = [str(x) for x in (face["children_of"].get(owner) or [])]
        assert got == disk, f"{owner} 的子 {got} 不是落盘行序 {disk}"
        # 同一份读数里的另一处（节点自己的 children）必须是同一个顺序。
        node = next(n for n in face["nodes"] if str(n["task_id"]) == owner)
        assert [str(k["task_id"]) for k in node["children"]] == disk, node["children"]
        # "按名册名重排"在这份夹具上是另一个顺序 ⇒ 上面那两条断言有区分力。
        by_name = sorted(disk, key=lambda tid: names[tid])
        assert by_name != disk, (
            f"{owner} 的名册名顺序与落盘行序相同 ⇒ 这条判据证明不了「没按名字重排」",
            names, disk)


# ====================================================================== ③ 折叠
def _tree_ui_problems(text: str) -> list[str]:
    """前端源码里"折叠到第 2 层 + 按 children_of 递归"的那几条标记。

    每一条都对得上一个具体的失败形态：
    - 没有 `DEFAULT_OPEN_DEPTH = 2` ⇒ 折叠口径没落地（整棵树一次铺开）；
    - 判据式不是 `depth <= DEFAULT_OPEN_DEPTH` ⇒ 写死了一个数，改层数时不会跟着动；
    - 没有 `openOverride` 这个模块级 Map ⇒ 展开态活不过一次数据刷新（流里每来一条
      事件面板就重取一次，挂在组件 state 上会被重置）；
    - 没有 `children_of` ⇒ 还在按 `nodes` 的顺序画（按层平铺）；
    - 还留着 `<NodeRow`（改前那一版"一行一个节点、按 `data.nodes` 顺序平铺"的组件）
      ⇒ 平铺渲染那一版没退场。
    """
    problems: list[str] = []
    if not re.search(rf"DEFAULT_OPEN_DEPTH\s*=\s*{OPEN_DEPTH}\b", text):
        problems.append(f"没有 DEFAULT_OPEN_DEPTH = {OPEN_DEPTH} 这个常量（默认展开几层没落地）")
    if not re.search(r"depth\s*<=\s*DEFAULT_OPEN_DEPTH", text):
        problems.append("默认展开的判据式不是 `depth <= DEFAULT_OPEN_DEPTH`"
                        "（写死了数字，改层数时不跟着动）")
    if not re.search(r"const\s+openOverride\s*:\s*Map<string,\s*boolean>\s*=\s*new\s+Map",
                     text):
        problems.append("没有模块级的 openOverride 表 ⇒ 展开态在数据刷新时会被重置")
    if "children_of" not in text:
        problems.append("没有按 children_of 递归渲染（父子关系没被用上）")
    if re.search(r"<NodeRow\b", text):
        problems.append("还留着 <NodeRow ⇒ 按层平铺那一版没退场")
    return problems


def test_the_tree_is_collapsed_to_two_levels_by_default() -> None:
    """判据③：默认展开到第 2 层（第 3 层节点默认折叠），展开态本次浏览内保持。

    源码判据 + 三条负控（改层数 / 换判据式 / 拆掉递归），每一条都必须当场红。
    """
    text = ROSTER_TSX.read_text(encoding="utf-8")
    assert _tree_ui_problems(text) == [], _tree_ui_problems(text)
    # 负控①：把默认展开的层数改成 3（第 3 层就不折了）
    assert _tree_ui_problems(text.replace(f"DEFAULT_OPEN_DEPTH = {OPEN_DEPTH}",
                                          "DEFAULT_OPEN_DEPTH = 3")), (
        "把默认展开层数改成 3，判据却一声不吭")
    # 负控②：判据式换成写死的数字
    assert _tree_ui_problems(text.replace("depth <= DEFAULT_OPEN_DEPTH", "depth <= 9")), (
        "把判据式换成写死的 9，判据却一声不吭")
    # 负控③：拆掉按 children_of 的递归渲染
    assert _tree_ui_problems(text.replace("children_of", "by_layer")), (
        "把 children_of 换掉，判据却一声不吭")


# ====================================================================== ④ 反真空
def test_a_flat_stub_of_the_parent_child_relation_is_caught(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据④（反真空）：把父子关系打桩成"全部挂根下" ⇒ ① 的判据必红。

    没有这一条，① 可能以"读到的那个形状恰好自洽"的形态绿着，而它守的那件事
    （谁是谁的子）其实没人核。打桩点是读出父子关系的那一处接缝
    （`readers._roster_children_of`）：它被换掉之后，`nodes` 与深度都照旧，
    只有父子关系变成平的一层 —— 这正是改前那张截图的形态。
    """
    root = _tree_workspace(tmp_path)
    assert _tree_problems(R.roster_face(root), EXPECTED_CHILDREN) == [], (
        "夹具前提变了：打桩之前 ① 就该是绿的")

    def _all_under_root(kids_of: Mapping[str, list[dict[str, Any]]],
                        roots: list[str]) -> dict[str, list[str]]:
        every: list[str] = []
        for rows in kids_of.values():
            for row in rows:
                tid = str(row.get("task_id") or "")
                if tid and tid not in every:
                    every.append(tid)
        parent = roots[0] if roots else ""
        return {parent: [tid for tid in every if tid != parent]}

    monkeypatch.setattr(R, "_roster_children_of", _all_under_root)
    stubbed = R.roster_face(root)
    problems = _tree_problems(stubbed, EXPECTED_CHILDREN)
    assert problems, ("把父子关系打桩成全部挂根下，① 的判据却一声不吭 ⇒ 那条判据是真空的")
    assert any("parent_task_id" in p or "depth" in p for p in problems), problems
