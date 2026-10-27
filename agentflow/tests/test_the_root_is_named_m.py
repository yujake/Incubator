# -*- coding: utf-8 -*-
"""名册树顶那一行：根的名字固定是主控（业主 2026-10-26：「顶层能不能标 M 啊，unknown 很怪」）。

## 现场（真机 `projects/mp3-r3`，改前）

`readers.roster_face` 的根节点读出来是 `role=""` / `name=""` —— 根不在任何人的名册里
（名册只记"某个父名下有哪些子"），于是页面（`Roster.tsx` 的 `nameText`）把它画成
「（顶层·无名册名）」，角色徽标画成一枚 `unknown`。那两格空串不是"没查到"，是"根没有
名册项"：页面把它当成"这一格读坏了"，读的人也就以为名册读坏了。

## 那一枚 `unknown` 是角色徽标，不是三态徽标

同一份读数里根的 `state` 是 `standby`（`state_reason` 说它挂在时钟上等），而三态徽标的
文案来自 `rosterTree.STATE_TEXT`，`unknown` 那一档写的是「未读到」—— 三态那一格从来不印
`unknown` 这个英文词。印出来的是角色那一格（`Roster.tsx` 的
`{node.role === "" ? "unknown" : node.role}`），它读的是 `nodes[].role`
（`readers.roster_face` 的 `role`），与 `nodes[].state` 是两个字段。所以这是渲染落点
问题，不是"某一刻读到了 unknown"：根的三态与别的节点走同一套判据
（`conductor.agent_state`，聚合在 `roster_face` 的 `most_active_state` 那一格）。

## 判据

| 判据 | 守的是 | 改前的样子 |
|---|---|---|
| a `test_the_root_of_a_roster_face_is_named_m` | 根 role/name 皆空的真名册面 ⇒ 根叫 M、role 是 M、三态是判出来的那一档 | 读到空串，页面画「（顶层·无名册名）」加一枚 `unknown` |
| a' `test_the_rendered_root_row_says_m` | 同一份读数喂给前端的渲染函数（`ui/src/rosterTree.ts` 真跑）⇒ 根那一行是 M，状态不是 unknown | 根那一行是空串 |
| b `test_the_real_workspace_root_is_m` | 真工作区（`projects/mp3-r3`，只读）⇒ 根 role=M、name=M | 两格都是空串 |
| c `test_stubbing_the_fill_turns_the_reading_red` | 反真空：把补名那一步打桩成不执行 ⇒ a 必红 | — |
| d `test_a_child_without_a_roster_name_is_not_renamed` | 正控：非根节点的空名照原样（不许被补成 M） | — |
| e `test_the_ui_no_longer_says_nameless` | `ui/src` 里不再出现「无名册名」，兜底逐字是 `M（顶层）`，且注明"正常路径不该走到" | 那一档就是页面上的样子 |
| f `test_the_unknown_on_that_row_was_the_role_badge` | 那一枚 `unknown` 出自角色徽标的字面量，三态徽标那一档写「未读到」 | 两者被读成一件事 |
| g `test_the_root_state_is_the_same_three_state_*` | 根的三态与别的节点同一套判据（自己跑 / 名下在飞 / 挂钟 / 收工） | 那一格被当成"另一类节点" |

## 为什么 c 与 d 必须一起在

只断言"根叫 M"的话，一个"把所有节点都叫 M"的实现也会绿（树就毁了）；只断言"子节点
没被改名"的话，改前那一版本来就绿（它谁也没补）。两条一起，才是"只补根、且根真被补"。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from typing import Any, Mapping

import pytest

from agentflow import clock as CLK
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"
TREE_TS = UI_SRC / "rosterTree.ts"
TYPESCRIPT_LIB = REPO / "ui" / "node_modules" / "typescript" / "lib" / "typescript.js"
#: 真机工作区（只读：这条判据不往它里面写一个字节）。
REAL_WORKSPACE = REPO / "projects" / "mp3-r3"

#: 夹具里的时间戳（`schema.Task` 的"每个 start 有且仅有一个 end"要求它对得上）。
_AT = "2026-10-26T00:00:00+08:00"


# ====================================================================== 夹具
def _row(task_id: str, *, role: str, parent: str | None, depth: int,
         status: str) -> dict[str, Any]:
    """一条实例行（`kind == ""`：一个 agent 一行，与 `schema.Task` 同形）。"""
    ended = None if status in ("pending", "running") else _AT
    outcome = None if status in ("pending", "running") else "ok"
    return {"task_id": task_id, "role": role, "action": "", "called_by": "parent",
            "parent_task_id": parent, "depth": depth, "input_key": f"k@{task_id}",
            "status": status, "outcome": outcome, "refusal_reason": None, "instance": "",
            "detail": "夹具：这一行是「根叫 M」那几条判据用的台账行", "error": None,
            "started_at": _AT, "ended_at": ended, "tokens": 0, "usd": 0.0,
            "artifacts": [], "inputs": [], "kind": "", "expects": "",
            "item_state": "", "item_close": "", "seen_by": "", "seen_step": None,
            "keep_alive": False}


def _roster_workspace(tmp: pathlib.Path, *, root_status: str = "done",
                      live_child: bool = True) -> pathlib.Path:
    """真名册的最小工作区：M（t-000001）派 D1，D1 再派 C1 与 F1。

    判据 a 的前提在盘上自然成立：根不在任何人的名册里，所以它的 `role` / `name`
    两格在名册那一侧根本不存在（`roster_face` 读到的是空串，与真机一致）。

    `root_status` / `live_child` 只给三态那一条判据用：根自己在跑、名下有在飞的子、
    还是全体收工，三档都由盘上这两行决定（口径仍是 `conductor.agent_state` 那一处）。
    """
    root = tmp / "ws"
    store = Store(root)
    store.init()
    sec = Secretary("M", root=root, store=store)
    assert sec.roster_add(owner="t-000001", role="D", task_id="t-000002",
                          brief="顶趟派出去的那一个")["problem"] == ""
    assert sec.roster_add(owner="t-000002", role="C", task_id="t-000003",
                          brief="D1 名下的第一个")["problem"] == ""
    assert sec.roster_add(owner="t-000002", role="F", task_id="t-000005",
                          brief="D1 名下的第二个")["problem"] == ""
    with store.tx("tasks", actor="test", note="root-named-m fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1,
                                status=root_status), note="顶趟")
        tx.upsert("tasks", _row("t-000002", role="D", parent="t-000001", depth=2,
                                status=("running" if live_child else "done")), note="第二层")
        tx.upsert("tasks", _row("t-000003", role="C", parent="t-000002", depth=3,
                                status="done"), note="收工")
        tx.upsert("tasks", _row("t-000005", role="F", parent="t-000002", depth=3,
                                status="done"), note="收工")
    return root


def _ledger_only_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """只有台账、没有 `out/roster/` 的工作区（`roster_face` 走台账兜底那一档）。

    这一档整棵树都没有名册名，所以它是判据 d 最干净的正控：根被补成 M 的同时，
    子节点的空名必须原样留着（那里没有"它是主控"这回事）。
    """
    root = tmp / "ledger-only"
    store = Store(root)
    store.init()
    with store.tx("tasks", actor="test", note="root-named-m fallback fixture") as tx:
        tx.upsert("tasks", _row("t-000001", role="M", parent=None, depth=1,
                                status="done"), note="顶趟")
        tx.upsert("tasks", _row("t-000002", role="D", parent="t-000001", depth=2,
                                status="done"), note="收工的那一个")
    return root


# ====================================================================== 判据本体
def _root_problems(face: Mapping[str, Any]) -> list[str]:
    """判据 a 的本体：根那一行的名字 / 角色 / 三态，以及"子节点没被改名"。

    写成"返回问题清单"而不是一串 assert，是为了让反真空那一条能拿同一个本体去
    证明"补名那一步不执行时它确实会红"—— 两条判据说的是同一件事，不许各写一份。
    """
    problems: list[str] = []
    if face.get("answer") != "ok":
        return [f"answer 不是 ok（{face.get('answer')!r}）：{face.get('reason')!r}"]
    nodes = {str(n.get("task_id") or ""): n for n in face.get("nodes") or []}
    roots = [str(x) for x in face.get("roots") or []]
    if len(roots) != 1:
        return [f"根不是一个（{roots}）⇒ 这条判据没有落脚点"]
    root = nodes.get(roots[0])
    if root is None:
        return [f"根 {roots[0]} 不在 nodes 里"]
    if str(root.get("parent_task_id") or "") != "":
        problems.append(f"根 {roots[0]} 的 parent_task_id 不是空串："
                        f"{root.get('parent_task_id')!r}")
    if root.get("depth") != 1:
        problems.append(f"根 {roots[0]} 的 depth 不是 1：{root.get('depth')!r}")
    if str(root.get("name") or "") != "M":
        problems.append(f"根 {roots[0]} 的 name 不是 M：{root.get('name')!r}"
                        "（根不在任何人的名册里，读侧要把它补成主控）")
    if str(root.get("role") or "") != "M":
        problems.append(f"根 {roots[0]} 的 role 不是 M：{root.get('role')!r}"
                        "（那一格空串会被页面画成一枚 unknown 角色徽标）")
    state = str(root.get("state") or "")
    if state not in ("flying", "standby", "silent"):
        problems.append(f"根 {roots[0]} 的三态不是判出来的那一档：{state!r}"
                        f"（reason={root.get('state_reason')!r}）——"
                        "它要与别的节点走同一套判据（跑着 / 挂钟 / 收工）")
    for tid, node in nodes.items():
        if tid == roots[0]:
            continue
        if str(node.get("name") or "") == "M":
            problems.append(f"非根节点 {tid} 的名字被补成了 M（它应当照原样："
                            f"{node.get('name')!r}）")
    return problems


# ====================================================================== a 读侧
def test_the_root_of_a_roster_face_is_named_m(tmp_path: pathlib.Path) -> None:
    """判据 a：根 role/name 皆空的真名册面 ⇒ 根叫 M，三态是判出来的那一档。

    改前红：根读出来是 `role=""` / `name=""`，页面把它画成「（顶层·无名册名）」，
    角色徽标画成 `unknown`。
    """
    face = R.roster_face(_roster_workspace(tmp_path))
    assert _root_problems(face) == [], _root_problems(face)
    # 正控（判据 d）：子节点仍然是名册给的那几个名字，一个都没被补成 M。
    names = {str(n["task_id"]): str(n["name"]) for n in face["nodes"]}
    assert names == {"t-000001": "M", "t-000002": "D1",
                     "t-000003": "C1", "t-000005": "F1"}, names
    roles = {str(n["task_id"]): str(n["role"]) for n in face["nodes"]}
    assert roles["t-000001"] == "M" and roles["t-000002"] == "D", roles
    # 父的名字是现算的：根叫 M，所以它那些子的 parent_name 也是 M。
    assert {str(n["parent_name"]) for n in face["nodes"] if n["depth"] == 2} == {"M"}, \
        [(n["task_id"], n["parent_name"]) for n in face["nodes"]]


# ====================================================================== a' 渲染
#: 把 `ui/src/rosterTree.ts`（纯函数）转成 ESM 再真跑一遍：页面读的就是它的产物。
_TRANSPILE_JS = r"""
const ts = require(process.argv[1]);
const fs = require("node:fs");
const path = require("node:path");
const src = fs.readFileSync(process.argv[2], "utf8");
const out = ts.transpileModule(src, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext,
    isolatedModules: true,
  },
  fileName: path.basename(process.argv[2]),
}).outputText;
fs.writeFileSync(process.argv[3], out, "utf8");
"""

_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [modulePath, payloadPath] = process.argv.slice(2);
const mod = await import(pathToFileURL(modulePath).href);
const view = JSON.parse(readFileSync(payloadPath, "utf8"));

const tree = mod.buildRosterTree(view);
const rows = mod.flattenRows(tree.rows).filter((r) => r.kind === "node");
const root = rows.length === 0 ? null : rows[0];
function nameOf(row) {
  return row === null || row.node === null ? "" : row.node.name;
}
function roleOf(row) {
  return row === null || row.node === null ? "" : row.node.role;
}
function stateOf(row) {
  return row === null || row.node === null ? "unknown" : mod.asAgentState(row.node.state);
}
process.stdout.write(JSON.stringify({
  drawn: rows.map((r) => r.task_id),
  names: rows.map(nameOf),
  root_id: root === null ? "" : root.task_id,
  root_name: nameOf(root),
  root_role: roleOf(root),
  root_state: stateOf(root),
  kid_names: root === null ? [] : root.kids.map(nameOf),
}));
"""


def _node_exe() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("没装 node ⇒ 前端渲染函数这一层记 unknown（不记 pass）")
    return node


def _render(face: Mapping[str, Any], tmp: pathlib.Path) -> dict[str, Any]:
    """把一份读数喂给前端的渲染函数，读回根那一行与画出来的节点集合。"""
    node = _node_exe()
    if not TYPESCRIPT_LIB.is_file():
        pytest.skip("前端依赖没装（ui/node_modules/typescript 不在）⇒ 记 unknown（不记 pass）")
    assert TREE_TS.is_file(), f"{TREE_TS.relative_to(REPO)} 不在盘上"
    module = tmp / "rosterTree.mjs"
    proc = subprocess.run([node, "-e", _TRANSPILE_JS, str(TYPESCRIPT_LIB),
                           str(TREE_TS), str(module)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "把 rosterTree.ts 转成 ESM 失败（exit "
        f"{proc.returncode}）：{((proc.stderr or '') + (proc.stdout or ''))[:800]}")
    assert '"./types"' not in module.read_text(encoding="utf-8"), (
        "rosterTree.ts 转出来还 import 了 ./types ⇒ 它不是纯函数，判据没法单独跑它")
    payload = tmp / "root-name-payload.json"
    payload.write_text(json.dumps(face, ensure_ascii=False), encoding="utf-8")
    runner = tmp / "root-name-runner.mjs"
    runner.write_text(_RUNNER_JS, encoding="utf-8")
    got = subprocess.run([node, str(runner), str(module), str(payload)],
                         capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert got.returncode == 0, (
        f"跑前端渲染函数失败（exit {got.returncode}）："
        f"{((got.stderr or '') + (got.stdout or ''))[:800]}")
    return dict(json.loads(got.stdout))


def test_the_rendered_root_row_says_m(tmp_path: pathlib.Path) -> None:
    """判据 a'：渲染函数读出来的根那一行是 M，三态是四档里的一档（不是 unknown）。

    这一层不是重复：页面印的是 `rosterTree.buildRosterTree` 的产物，读侧改名之后
    前端有没有真的把它读出来，只有真跑一遍它才说得清。
    """
    face = R.roster_face(_roster_workspace(tmp_path))
    got = _render(face, tmp_path)
    assert got["root_id"] == "t-000001", got
    assert got["root_name"] == "M", got
    assert got["root_role"] == "M", got
    assert got["root_state"] != "unknown", got
    # 正控：它名下那个子、以及再下一层的两个孙，名字照旧（渲染那一层也不许把它们补成 M）。
    assert got["kid_names"] == ["D1"], got
    assert got["names"] == ["M", "D1", "C1", "F1"], got
    assert "t-000001" in got["drawn"], got


# ====================================================================== g 三态同源
@pytest.mark.parametrize(("root_status", "live_child", "timed", "want"), [
    ("running", True, False, "flying"),
    ("done", True, False, "standby"),
    ("done", False, True, "standby"),
    ("done", False, False, "silent"),
])
def test_the_root_state_is_the_same_three_state_as_every_other_node(
        tmp_path: pathlib.Path, root_status: str, live_child: bool, timed: bool,
        want: str) -> None:
    """判据 g：根的三态与别的节点走同一套判据（自己跑 / 名下在飞 / 挂钟 / 收工）。

    四档的判定仍然只有 `conductor.agent_state` 一处；这一条钉的是"根没有另走一条路"：
    - 根自己在跑 ⇒ 在飞；
    - 根已收工、名下有在飞的直接子 ⇒ 待机（同一个"等"，台账那一面读得出来）；
    - 根已收工、挂在时钟上等 ⇒ 待机（机制那一面）；
    - 全体收工、没有钟 ⇒ 静默。
    """
    root = _roster_workspace(tmp_path, root_status=root_status, live_child=live_child)
    if timed:
        CLK.start_timer(str(root), reason="夹具：顶趟挂在时钟上等", after_sec=600.0,
                        task_id="t-000001", role="M")
    face = R.roster_face(root)
    node = next(n for n in face["nodes"] if n["task_id"] == "t-000001")
    assert node["state"] == want, (node, face["states"])
    assert str(node["state_reason"]), "判成某一档却不说凭什么（悬停就没有原因可看）"


# ====================================================================== b 真机
def test_the_real_workspace_root_is_m() -> None:
    """判据 b：真工作区（`projects/mp3-r3`，只读）⇒ 根 role=M、name=M。

    不在盘上就 skip：CI 里没有 `projects/`，那一条是 unknown，不是 pass。
    三态只断言"是判出来的那一档"：那一格跟着时钟走（挂着计时器是待机、到点收工是静默），
    钉死某个值等于把一条会随时间变的读数写进判据。
    """
    if not (REAL_WORKSPACE / "out" / "roster").is_dir():
        pytest.skip(f"真机工作区不在盘上（{REAL_WORKSPACE.relative_to(REPO)}）⇒ 记 unknown")
    face = R.roster_face(REAL_WORKSPACE)
    problems = _root_problems(face)
    assert problems == [], problems


# ====================================================================== c 反真空
def test_stubbing_the_fill_turns_the_reading_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 c：把补名那一步打桩成不执行 ⇒ 判据 a 必红。

    打桩点就是 `readers._roster_root_identity`（读侧补名的唯一落点）。它退成恒等函数
    以后，同一个夹具上 `_root_problems` 必须点名 name 与 role 两格 —— 否则判据 a 是
    一句空话（改前那一版本来就不补名，它必须在那条判据上红过）。
    """
    root = _roster_workspace(tmp_path)
    monkeypatch.setattr(R, "_roster_root_identity", lambda role, name: (role, name))
    face = R.roster_face(root)
    problems = _root_problems(face)
    assert problems, "补名那一步打桩成不执行，判据 a 却全绿 ⇒ 它是真空的"
    assert any("name 不是 M" in one for one in problems), problems
    assert any("role 不是 M" in one for one in problems), problems


# ====================================================================== d 正控
def test_a_child_without_a_roster_name_is_not_renamed(tmp_path: pathlib.Path) -> None:
    """判据 d：台账兜底那一档（谁都没有名册名）⇒ 只有根补名，子节点的空名照原样。

    这条防的是"把补名做成遍历全树"：那样整棵树会一起变成 M，而"根是顶趟那一股"
    这件事反而读不出来了。同时它也钉住兜底那一档的口径：补的只是根那一行。
    """
    face = R.roster_face(_ledger_only_workspace(tmp_path))
    assert face["answer"] == "unknown", face["reason"]
    nodes = {str(n["task_id"]): n for n in face["nodes"]}
    assert set(nodes) == {"t-000001", "t-000002"}, sorted(nodes)
    assert (str(nodes["t-000001"]["name"]), str(nodes["t-000001"]["role"])) == ("M", "M"), \
        nodes["t-000001"]
    assert nodes["t-000001"]["depth"] == 1, nodes["t-000001"]
    # 正控：子节点的空名原样留着（它确实没有名册名），父的名字是现算的 M。
    assert str(nodes["t-000002"]["name"]) == "", nodes["t-000002"]
    assert str(nodes["t-000002"]["role"]) == "D", nodes["t-000002"]
    assert str(nodes["t-000002"]["parent_name"]) == "M", nodes["t-000002"]


# ====================================================================== e UI 源码
def _ui_sources() -> dict[str, str]:
    """`ui/src/**` 下每个 TS / TSX 文件的文本（相对路径 -> 文本）。"""
    out: dict[str, str] = {}
    for path in sorted(UI_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx"):
            continue
        out[path.relative_to(UI_SRC).as_posix()] = path.read_text(encoding="utf-8")
    return out


def _nameless_top_problems(sources: Mapping[str, str]) -> list[str]:
    """判据 e 的本体：那一档「无名册名」在 `ui/src` 里不再出现，兜底逐字是 `M（顶层）`。

    为什么把"注明"也算一格：这一档只作为最后兜底（旧后端 / 缺那一格），正常路径上根
    的名字由读侧补好了 —— 不写明这一点，下一个读代码的人会以为根本来就没有名字。
    """
    problems: list[str] = []
    for rel, text in sources.items():
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "无名册名" in line:
                problems.append(f"{rel}:{lineno} 还有「无名册名」那一档：{line.strip()!r}")
    roster = str(sources.get("components/Roster.tsx") or "")
    if 'node.name === "" ? "M（顶层）" : node.name' not in roster:
        problems.append("Roster.tsx 的 nameText 兜底不是「M（顶层）」"
                        "（旧后端给的根还是会画成一格看不懂的名字）")
    if "正常路径不该走到" not in roster:
        problems.append("那一档兜底没注明「正常路径不该走到」⇒ 读的人以为根本来就没有名字")
    return problems


def test_the_ui_no_longer_says_nameless() -> None:
    """判据 e：`ui/src` 里不再出现「无名册名」，兜底逐字是 `M（顶层）` 并注明是兜底。"""
    sources = _ui_sources()
    assert sources, "ui/src 下一个 TS/TSX 都没读到 ⇒ 这条判据是空转"
    assert _nameless_top_problems(sources) == [], _nameless_top_problems(sources)
    # 负控：把那一档字面塞回去 ⇒ 必红（否则这条判据只是一句空话）。
    planted = dict(sources)
    planted["components/Roster.tsx"] = planted["components/Roster.tsx"].replace(
        'node.name === "" ? "M（顶层）" : node.name',
        'node.name === "" ? "（顶层·无名册名）" : node.name')
    assert _nameless_top_problems(planted), "把「无名册名」塞回去，判据却一声不吭"


# ====================================================================== f 诊断
def test_the_unknown_on_that_row_was_the_role_badge() -> None:
    """判据 f：页面上那一枚 `unknown` 出自角色徽标，不是三态徽标。

    诊断（改前真机 `projects/mp3-r3`）：根读数的 `state` 是 `standby`，页面却印着
    `unknown` —— 因为那是角色那一格（`{node.role === "" ? "unknown" : node.role}`，
    读的是 `nodes[].role`），而三态徽标那一档的文案是「未读到」（`STATE_TEXT.unknown`）。
    所以这里钉住两件事：英文词 `unknown` 只有一个落点（角色徽标），三态那一档的中文
    文案就是「未读到」—— 下次有人把两者混着读，这一条会指出它们不是同一格。
    """
    roster = ROSTER_TSX.read_text(encoding="utf-8")
    tree = TREE_TS.read_text(encoding="utf-8")
    assert '{node.role === "" ? "unknown" : node.role}' in roster, (
        "角色徽标那一格的字面量变了 ⇒ 这一条诊断要重新读（它指的就是那一行）")
    assert 'unknown: "未读到",' in tree, (
        "三态徽标的 unknown 那一档不是「未读到」⇒ 页面上的那个英文词更可能是它")
    assert "STATE_TEXT[state]" in roster, "三态徽标没走 STATE_TEXT（文案会各处各写一份）"
