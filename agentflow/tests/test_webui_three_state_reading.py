# -*- coding: utf-8 -*-
"""三态（在飞 / 待机 / 静默 / 未读到）在网页上的读数与措辞：数据级 + 源码级两类判据。

## 这一份补的是什么（上一份只到源码文本）

`tests/test_three_states_flying_standby_silent.py` 守的是后端三态，外加"前端用了那个
词表"。它能证明面板调了 `kidsStateText`，但证明不了"那一格读出来的数就是三态的数"：
把实现改成 `活 ${kids.length}` 而函数名与文案照旧，它仍然全绿（它只看函数体里有没有
`children.length`，从来不跑那个函数）。

所以这一份做两件事：

| 类 | 判据 | 它守的是 |
|---|---|---|
| 数据级 | 造 1 飞 1 待 1 静默的读数，喂给 `ui/src/rosterTree.ts` 的两个渲染函数（node 真跑），读回三档计数、`active` 与那一行字 | 三档计数与 `active = 在飞 + 待机` 对得上；「活 N」不是 `children.length`；读不到时显"未读到 + 原因"且一个数字都不出现（含 0） |
| 源码级 | `ui/src/**` 里每一处「在飞」都在白名单里（带判决理由），且没有一处把「在飞」当「活跃」用的写法 | 哪一句是页面名、哪一句是三态、哪一句是任务面 / 循环面 —— 逐处登记；塞一处旧写法必红 |

## 数据级为什么真跑前端函数

`rosterTree.ts` 是纯函数（不 import preact、不碰 DOM），`types.ts` 只在 `import type`
里出现 ⇒ 用 `ui/node_modules/typescript` 把它转成 ESM 就能被 node 直接跑（与
`tests/test_roster_tree_renders_all_nodes.py` 同一条做法，那一条已经证明这条路成立）。
没装 node / 没装 typescript ⇒ skip 并写明记 unknown，不记 pass。

## 源码级的白名单为什么逐行

「在飞」这个字在本仓库有三个正当用法：页面名（「在飞」页 = /live）、代理三态里
那一档、任务面 / 循环面的同一句话（台账行 status ∈ pending/running / 那一趟循环）。
三者混起来读正是业主点名要修的那个读数，所以每一处都必须有一句判决；白名单过期
（登记的那一行已经不在盘上）也算红 —— 否则它会长成"看起来还在挡着什么"。

## 业主原话（唯一权威，逐字）

```
「关于"在飞"的读数要随着时钟式待机进行适配，分三种：
 1.在工作叫"在飞"，2.在等待（计时器）为"待机"，3.已收工，无任务，无计时器，叫"静默"。
 更新"活跃子代理"的定义为非静默子代理。」
```
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from typing import Any, Mapping

import pytest

from agentflow import clock as CLK
from agentflow.conductor import Conductor, LocalBackend
from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI = REPO / "ui"
UI_SRC = UI / "src"
TREE_TS = UI_SRC / "rosterTree.ts"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"
APP_CSS = UI_SRC / "theme" / "app.css"
TYPESCRIPT_LIB = UI / "node_modules" / "typescript" / "lib" / "typescript.js"

#: 夹具里的时间戳（`schema.Task` 的"每个 start 有且仅有一个 end"要求它对得上）。
_TS = "2026-01-01T00:00:00+00:00"


# ====================================================================== 夹具（后端真读数）
def _workspace(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个工作区 + 一个主控 + 父那一趟的秘书（`roster_sink` 接上，与生产同一条取法）。"""
    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    cond = Conductor(store, registry={}, backend=LocalBackend({}))
    sec = Secretary("M", root=root, store=store)
    cond.roster_sink = sec
    owner = str(cond.open_top_level_run("M", "夹具：三态读数"))
    return {"root": root, "store": store, "cond": cond, "sec": sec, "owner": owner}


def _child(cond: Conductor, parent: str, *, role: str, status: str) -> str:
    """造一个子代理的台账行（`kind` 空 = 代理行；终态带 outcome 与 ended_at）。"""
    row = {
        "role": role, "action": "write_report", "called_by": "M",
        "parent_task_id": parent, "depth": 2, "input_key": f"三态读数:{role}:{status}",
        "status": status,
        "outcome": ("ok" if status == "done" else None),
        "refusal_reason": None, "instance": "", "detail": "夹具子代理",
        "error": None, "started_at": _TS,
        "ended_at": (_TS if status in ("done", "cancelled") else None),
        "tokens": 0, "usd": 0.0, "artifacts": [], "inputs": [],
    }
    return cond._write_new_row(row, note="fixture:child")


def _register(env: dict[str, Any], task_id: str, *, role: str) -> None:
    """登记进主控那一份名册（名册项的身份是 owner + name）。"""
    got = env["sec"].roster_add(owner=str(env["owner"]), role=role,
                                task_id=task_id, brief="夹具的活")
    assert got.get("problem") == "", got


def _three_way_view(tmp_path: pathlib.Path) -> dict[str, Any]:
    """1 在飞 + 1 待机 + 1 静默的三态读数（外加跑着的主控那一行）。

    待机那一个：`status=done` 但挂着一条没到点的一次性计时器 —— 这正是业主那句
    「在等待（计时器）为『待机』」的最小形态。
    """
    env = _workspace(tmp_path)
    owner = str(env["owner"])
    flying = _child(env["cond"], owner, role="D", status="running")
    standby = _child(env["cond"], owner, role="F", status="done")
    silent = _child(env["cond"], owner, role="B", status="done")
    for tid, role in ((flying, "D"), (standby, "F"), (silent, "B")):
        _register(env, tid, role=role)
    CLK.start_timer(str(env["root"]), reason="夹具：还没到点", after_sec=600.0,
                    task_id=standby, role="F")
    face = R.roster_face(str(env["root"]))
    assert face["answer"] == "ok", face["reason"]
    return dict(face)


def _pure_view(states: Mapping[str, Any]) -> dict[str, Any]:
    """一份手写的读数：树是 1 个父 + 3 个子（子各是 在飞 / 待机 / 静默）。

    `states` 单独给：它就是这一批要判的那一格，与树上画了几行是两件事
    （后端那一格数的是工作区里的代理，不是"这棵树有几行"）。
    """
    nodes = [
        {"task_id": "t-000100", "name": "", "role": "M", "depth": 1,
         "parent_task_id": "", "state": "flying",
         "children": [{"task_id": "t-000101"}, {"task_id": "t-000102"},
                      {"task_id": "t-000103"}]},
        {"task_id": "t-000101", "name": "D1", "role": "D", "depth": 2,
         "parent_task_id": "t-000100", "state": "flying", "children": []},
        {"task_id": "t-000102", "name": "F1", "role": "F", "depth": 2,
         "parent_task_id": "t-000100", "state": "standby", "children": []},
        {"task_id": "t-000103", "name": "B1", "role": "B", "depth": 2,
         "parent_task_id": "t-000100", "state": "silent", "children": []},
    ]
    return {
        "answer": "ok", "nodes": nodes, "roots": ["t-000100"],
        "children_of": {"t-000100": ["t-000101", "t-000102", "t-000103"]},
        "states": dict(states),
    }


def _one_each_states() -> dict[str, Any]:
    """三态合计：在飞 1 / 待机 1 / 静默 1（活跃 = 非静默 = 2）。"""
    return {"checked": True, "reason": "", "flying": 1, "standby": 1, "silent": 1,
            "unknown": 0, "active": 2, "total": 3,
            "labels": {"flying": "在飞", "standby": "待机", "silent": "静默",
                       "unknown": "未读到"}}


# ====================================================================== 跑前端那两个渲染函数
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
const payload = JSON.parse(readFileSync(payloadPath, "utf8"));

function stateOf(row) {
  return row.node === null ? "unknown" : mod.asAgentState(row.node.state);
}

const out = { cases: [], error: "" };
try {
  for (const one of payload.cases) {
    const view = one.view;
    const tree = mod.buildRosterTree(view);
    const root = tree.rows.find((r) => r.kind === "node") || null;
    const kids = root === null ? [] : root.kids;
    const states = kids.map(stateOf);
    out.cases.push({
      summary: mod.stateSummary(view, tree.rows, tree.unreached),
      kidsText: kids.length === 0 ? "" : mod.kidsStateText(kids),
      kidsLen: kids.length,
      kidsStates: states,
      kidsActive: mod.tallyStates(states).active,
      drawn: mod.flattenRows(tree.rows).filter((r) => r.kind === "node").map((r) => r.task_id),
      notes: tree.notes,
    });
  }
} catch (e) {
  out.error = String(e && e.stack ? e.stack : e);
}
process.stdout.write(JSON.stringify(out));
"""

#: 同一个临时目录里的那一次转译只做一遍。
_TRANSPILED: dict[str, pathlib.Path] = {}


def _node_exe() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("没装 node ⇒ 前端渲染函数这一层记 unknown（不记 pass）")
    return node


def _module_js(tmp: pathlib.Path) -> pathlib.Path:
    """把纯函数那一份（`ui/src/rosterTree.ts`）转成 ESM（同一份 tmp 只转一次）。"""
    cached = _TRANSPILED.get(str(tmp))
    if cached is not None and cached.is_file():
        return cached
    node = _node_exe()
    if not TYPESCRIPT_LIB.is_file():
        pytest.skip("前端依赖没装（ui/node_modules/typescript 不在）⇒ 记 unknown（不记 pass）")
    assert TREE_TS.is_file(), (
        f"{TREE_TS.relative_to(REPO)} 不在盘上：三态在页面上没有可判的纯函数")
    out = tmp / "rosterTree.mjs"
    proc = subprocess.run([node, "-e", _TRANSPILE_JS, str(TYPESCRIPT_LIB),
                           str(TREE_TS), str(out)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "把 rosterTree.ts 转成 ESM 失败（exit "
        f"{proc.returncode}）：{((proc.stderr or '') + (proc.stdout or ''))[:800]}")
    body = out.read_text(encoding="utf-8")
    assert '"./types"' not in body, (
        "rosterTree.ts 转出来还 import 了 ./types ⇒ 它不是纯函数，判据没法单独跑它")
    _TRANSPILED[str(tmp)] = out
    return out


def _render(views: list[dict[str, Any]], tmp: pathlib.Path) -> list[dict[str, Any]]:
    """把几份读数喂给前端那两个渲染函数，读回它们算出来的数。"""
    node = _node_exe()
    module = _module_js(tmp)
    payload = tmp / "three-state-payload.json"
    payload.write_text(json.dumps({"cases": [{"view": v} for v in views]},
                                  ensure_ascii=False), encoding="utf-8")
    runner = tmp / "three-state-runner.mjs"
    runner.write_text(_RUNNER_JS, encoding="utf-8")
    proc = subprocess.run([node, str(runner), str(module), str(payload)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        f"跑前端渲染函数失败（exit {proc.returncode}）："
        f"{((proc.stderr or '') + (proc.stdout or ''))[:800]}")
    got = json.loads(proc.stdout)
    assert got["error"] == "", got["error"]
    assert len(got["cases"]) == len(views)
    return list(got["cases"])


# ====================================================================== 数据级 ① 1 飞 1 待 1 静默
def test_one_each_renders_active_two_and_never_the_child_count(
        tmp_path: pathlib.Path) -> None:
    """1 飞 1 待 1 静默 ⇒ 渲染函数读出 在飞 1 / 待机 1 / 静默 1、活跃 2。

    三处一起看（少一处就能被"看起来对"的形状蒙过去）：
    - 顶部合计那一行逐字是 `在飞 1 · 待机 1 · 静默 1`，且 `active` 是 2、`total` 是 3；
    - 树根名下三个子 ⇒ 「活 2（飞 1 · 待 1）」：N = 非静默 = 在飞 + 待机；
    - 反真空：名下子行数是 3 而「活 N」是 2 —— 若那一格改用 `children.length`，
      它就会写成 3，而两个数相等正是"这一格没在读三态"的形态。
    """
    view = _pure_view(_one_each_states())
    got = _render([view], tmp_path)[0]

    summary = got["summary"]
    assert summary["text"] == "在飞 1 · 待机 1 · 静默 1", summary
    assert summary["active"] == 2, summary
    assert summary["total"] == 3, summary
    assert summary["unknown"] == 0, summary
    assert summary["reason"] == "", summary

    # 树根那一行的直接子就是 飞 / 待 / 静默 各一个
    assert got["kidsLen"] == 3, got
    assert sorted(got["kidsStates"]) == ["flying", "silent", "standby"], got["kidsStates"]
    assert got["kidsText"] == "活 2（飞 1 · 待 1）", got["kidsText"]
    assert got["kidsActive"] == 2, got
    assert got["kidsLen"] != got["kidsActive"], (
        "子行数与「活 N」相等 ⇒ 这一格可能在用 children.length 冒充非静默数")
    assert "活 3" not in got["kidsText"], got["kidsText"]

    # 树上画出来的节点：父 + 三个子（树本身没被三态读数影响）
    assert got["drawn"] == ["t-000100", "t-000101", "t-000102", "t-000103"], got["drawn"]
    assert got["notes"] == [], got["notes"]


def test_the_backend_roster_face_reaches_the_render_functions(
        tmp_path: pathlib.Path) -> None:
    """后端真读数（`readers.roster_face`）喂进渲染函数：三档与 `active` 同源。

    这一条防的是"前端与后端各算一遍"：夹具里 3 个子是 飞 / 待 / 静默，主控那一行
    自己在跑 ⇒ 后端合计是 在飞 2 / 待机 1 / 静默 1 / 活跃 3；渲染函数读出来的必须是
    同一批数字，而树根那一行名下的三个子仍然是「活 2（飞 1 · 待 1）」。
    """
    face = _three_way_view(tmp_path)
    states = face["states"]
    assert (states["flying"], states["standby"], states["silent"],
            states["unknown"]) == (2, 1, 1, 0), states
    assert states["active"] == 3 and states["total"] == 4, states

    got = _render([face], tmp_path)[0]
    summary = got["summary"]
    assert summary["text"] == "在飞 2 · 待机 1 · 静默 1", summary
    assert summary["active"] == 3, summary
    assert summary["total"] == 4, summary
    assert summary["unknown"] == 0, summary
    # 树根那一行名下：1 飞 1 待 1 静默 ⇒ 活 2（不是 3）
    assert got["kidsLen"] == 3, got
    assert got["kidsText"] == "活 2（飞 1 · 待 1）", got["kidsText"]
    assert got["kidsActive"] == 2, got
    # 后端那一格里逐节点的 state 也是这三档（同一份读数，不是页面另算的）
    by_name = {str(n.get("name") or ""): str(n.get("state") or "") for n in face["nodes"]}
    assert (by_name.get("D1"), by_name.get("F1"), by_name.get("B1")) == (
        "flying", "standby", "silent"), by_name
    # 待机那一格的理由里点名它挂在时钟上等（页面悬停显示的就是这一句）
    standby = next(n for n in face["nodes"] if str(n.get("name") or "") == "F1")
    assert "时钟" in str(standby.get("state_reason") or ""), standby


# ====================================================================== 数据级 ② 活跃不是后端某一格
def test_active_is_computed_from_the_definition_not_copied_from_a_lying_cell(
        tmp_path: pathlib.Path) -> None:
    """后端那一格 `active` 与定义对不上时：按定义显示，并把"对不上"写进原因。

    为什么要有这一条：`active` 那一格是另一份读数，抄它等于把矛盾静默地藏起来。
    两份读数互相矛盾时，页面必须两个都说（数按定义算、原因里点名那一格是几）。
    """
    view = _pure_view(_one_each_states())
    view["states"]["active"] = 99
    got = _render([view], tmp_path)[0]
    assert got["summary"]["active"] == 2, got["summary"]
    assert "99" in got["summary"]["reason"], got["summary"]
    assert "不等于在飞 + 待机" in got["summary"]["reason"], got["summary"]


# ====================================================================== 数据级 ③ 读不到
def _unread_states(*, checked: bool) -> dict[str, Any]:
    """合计"没读到"那一档：四格都是 null（后端声明的就是 `number | null`）。"""
    return {"checked": checked, "reason": "时钟读不成（夹具：out/clock/state.json 坏了）",
            "flying": None, "standby": None, "silent": None, "unknown": None,
            "active": None, "total": None,
            "labels": {"flying": "在飞", "standby": "待机", "silent": "静默",
                       "unknown": "未读到"}}


def test_an_unread_tally_says_unreadable_with_the_reason_and_never_a_zero(
        tmp_path: pathlib.Path) -> None:
    """`states.checked=false` 或四档有 null ⇒ "未读到 + 原因"，一个数字都不出现。

    两档一起钉：
    - `checked=false`（后端明说没查成）；
    - `checked=true` 而四格是 null —— 改前的实现写的是 `asNumber(...) ?? 0`，于是
      这一档会当场显示 `在飞 0 · 待机 0 · 静默 0`：把"没读到"折成"全都收工了"。
      这条判据就是那个折叠的负控。

    "不出现 0"按整行文字断言：那一行里连解释用的 0 都不许有（读者的第一眼只看数字）。
    """
    cases = [_pure_view(_unread_states(checked=False)),
             _pure_view(_unread_states(checked=True))]
    for got in _render(cases, tmp_path):
        summary = got["summary"]
        assert "未读到" in summary["text"], summary
        assert "时钟读不成" in summary["reason"], summary
        assert summary["unknown"] == -1, summary
        assert summary["active"] is None, summary
        assert summary["total"] is None, summary
        assert "0" not in summary["text"], (
            "读不到的那一行里出现了 0（会被读成'全都收工了'）", summary["text"])
        assert re.search(r"\d", summary["text"]) is None, (
            "读不到的那一行里出现了数字", summary["text"])
    # 改前那一档长这样：三个 0 并排（这就是负控要挡的形态）
    assert not any("在飞 0" in c["summary"]["text"] for c in _render(cases, tmp_path))


# ====================================================================== 源码级：白名单
#: 白名单：`(相对 ui/src 的路径, 去掉首尾空白后的整行)` -> 判决档。
#
#: 逐行而不是逐文件的理由写在模块头：同一个「在飞」有三种正当用法，混起来读正是
#: 这一批要修的那个读数，所以每一处都要有一句判决。白名单过期（那一行不在盘上）
#: 也红 —— 一张永不生效的豁免表会腐烂成"看起来还在挡着什么"。
#
#: 判决档只有五档，名字就是判决本身（理由见 `_REASONS`）：
#: - PAGE：页面名 / 面名（「在飞」页 = /live），不是读数；
#: - STATE：代理三态里 flying 那一档，或三态口径的说明；
#: - TASK：任务面的「在飞」（台账行 / `in_flight`），已逐字标明不是代理三态；
#: - LOOP：循环 / 进程面的「在飞」（那一趟循环），不是代理三态；
#: - NOTE：说明文，显式写"这里不说在飞 / 表里有它不等于它在飞"。
_ALLOWED: dict[tuple[str, str], str] = {
    ('components/Roster.tsx', '* 这张树的消费者是运行态监控：人在「在飞」页问"现在到底有谁在跑、谁是谁的子"。'): 'PAGE',
    ('components/Roster.tsx', '* （`draft/75 §1.4`），而"监控面"本来就在「在飞」页。所以它落在这里，与那一页的'): 'PAGE',
    ('components/Roster.tsx', '* 「在飞」「停机」「用量」几张卡片并排 —— 同一份读数，一处实现。'): 'PAGE',
    ('components/Roster.tsx', '* ## 每个代理那一格三态（在飞 / 待机 / 静默 / 未读到）'): 'STATE',
    ('components/Roster.tsx', '* 业主 2026-10-26：「『在飞』的读数要随着时钟式待机进行适配，分三种：1.在工作叫'): 'STATE',
    ('components/Roster.tsx', '* 『在飞』，2.在等待（计时器）为『待机』，3.已收工，无任务，无计时器，叫『静默』。'): 'STATE',
    ('components/Roster.tsx', '*   - 顶部合计「在飞 a · 待机 b · 静默 c」，读不到时显示"未读到 + 一句原因"，'): 'STATE',
    ('components/Roster.tsx', '* 「在飞 N 个」，也不能并进「活跃（非静默）」。页面把它逐字写成「未收口的活 N 件」，'): 'TASK',
    ('components/Roster.tsx', '/** 三态徽标（在飞 / 待机 / 静默 / 未读到）：文案与词表来自 `rosterTree.STATE_TEXT`，'): 'STATE',
    ('components/Roster.tsx', '* 在飞 = 强调色、待机 = 中性偏冷（次要标签色 + 层底色）、静默 = 灰（三级标签色）、'): 'STATE',
    ('components/Roster.tsx', '{/* 「▸ 活 N（飞 a · 待 b）」：N = 非静默（在飞 + 待机），不是 children.length'): 'STATE',
    ('components/Roster.tsx', 'title={`「活 N」的 N = ${ACTIVE_TEXT} = 在飞 + 待机，不是名下子节点的个数`'): 'STATE',
    ('components/Roster.tsx', '{/* 三态徽标：在飞 / 待机 / 静默 / 未读到（文案与颜色都跟着这一档走，悬停给原因）。 */}'): 'STATE',
    ('components/Roster.tsx', '它既不是「在飞 N 个」，也不能并进「活跃（非静默）」。 */}'): 'TASK',
    ('components/Roster.tsx', '* 名册面板（「在飞」页里的那一张卡）。'): 'PAGE',
    ('components/Roster.tsx', '{/* 顶部合计（业主 2026-10-26：「顶部合计：在飞 a · 待机 b · 静默 c」）。'): 'STATE',
    ('components/Roster.tsx', '活跃 = 非静默 = 在飞 + 待机；`未读到` 单独列，不混进活跃也不混进静默。'): 'STATE',
    ('components/Stop.tsx', '* 叫停按钮（`POST /api/stop`）—— 「一趟详情」与「在飞」两页用的是**同一套**。'): 'PAGE',
    ('components/Stop.tsx', '* （优雅停：落一个停机开关，在飞的循环在下一个检查点收工；强制停：连子孙进程一起杀，'): 'LOOP',
    ('components/Stop.tsx', '* 「一趟详情」里 —— 用户要叫停时待的却是「在飞」那一页。'): 'PAGE',
    ('main.tsx', '{ path: "/live", label: "在飞" },'): 'PAGE',
    ('pages/Help.tsx', 'why: "优雅停：落一个停机开关，在飞的那一趟在下一个检查点收工（「在飞」页能看到它）",'): 'LOOP',
    ('pages/Help.tsx', 'why: "写一份状态报告（落 STATUS-<时间>.md/.json，「在飞」页的「状态报告」那一栏就是它）",'): 'PAGE',
    ('pages/Help.tsx', 'page: "在飞（/live）",'): 'PAGE',
    ('pages/Help.tsx', '「在飞」页里那张卡读 <span class="mono">GET /api/roster</span>（只读：路由表里没有配对的 POST）。'): 'PAGE',
    ('pages/Help.tsx', '<b>每一行是一个代理的三态</b>（在飞 / 待机 / 静默 / 未读到）：'): 'STATE',
    ('pages/Help.tsx', '（鼠标停在徽标上就能看到）。判定只有后端一处：在工作叫在飞；时钟上还挂着等待'): 'STATE',
    ('pages/Help.tsx', '顶上那行「三态合计：在飞 a · 待机 b · 静默 c · 未读到 d」就是这几档各几个，'): 'STATE',
    ('pages/Help.tsx', '「活跃（非静默）」= 在飞 + 待机，行尾那格「活 N（飞 a · 待 b）」的 N 就是它'): 'STATE',
    ('pages/Help.tsx', '仍然是 <span class="mono">running</span>，所以它不能读成"在飞几个"，也不能并进'): 'TASK',
    ('pages/Help.tsx', '<Card title="容易读混的六格读数（未读 / 板项与在飞 / 待答 / 台账写入 / 会话事件条数 / 宿主进程 pid）">'): 'TASK',
    ('pages/Help.tsx', '<b>板项与在飞不能混算</b>：板项行是 <span class="mono">kind</span> 非空、'): 'TASK',
    ('pages/Help.tsx', '「在飞的活」看的是实例行（<span class="mono">kind</span> 为空、<span class="mono">status</span>'): 'TASK',
    ('pages/Help.tsx', '状态报告那一栏的「在飞」只数实例行：不分开数会把「板上有十几条要消的项」写成「在飞十几」。'): 'TASK',
    ('pages/Help.tsx', '这是「任务面」的「在飞」（一件活一行），不是名册卡那一格代理三态'): 'TASK',
    ('pages/Help.tsx', '（在飞 / 待机 / 静默）—— 两者同名不同口径，别拿一个去核另一个：'): 'STATE',
    ('pages/Help.tsx', '<b>进程面那一列是宿主进程的 pid</b>：「在飞」页进程面的列名逐字是'): 'PAGE',
    ('pages/Help.tsx', '—— 不是 0。「在飞」面同理：它的'): 'PAGE',
    ('pages/Help.tsx', '报错看三处：「在飞」的停机开关与用量；「产物」「证据链」每行的三态与理由；'): 'PAGE',
    ('pages/Home.tsx', '* 活着（进程在、只是这一拍不调模型），所以这一页不说「主控在飞」—— 那句话该由三态说。'): 'NOTE',
    ('pages/Live.tsx', '* 在飞（业主 2026-10-12：「特别照顾……对多智能体系统的监控能力」）。'): 'PAGE',
    ('pages/Live.tsx', '* 「在飞」那两张表里只有角色名、没有绝对编号的缺口，也把父→子那一层摆出来。'): 'PAGE',
    ('pages/Live.tsx', 'title="在飞"'): 'PAGE',
    ('pages/Live.tsx', 'liveFace.problem === "" ? null : <TriState tri="unreadable" reason={liveFace.problem} label="在飞面" />'): 'PAGE',
    ('pages/Live.tsx', '<TriState tri={l.tri} label="在飞面" reason={l.reason} />'): 'PAGE',
    ('pages/Live.tsx', '所以"表里有它"不等于"它在飞"。它此刻是哪一档，看下面名册树那一行的徽标。 */}'): 'NOTE',
    ('pages/Live.tsx', '挂机（待机）的那一趟循环仍然活着，所以「这张表里有它」不等于「它在飞」。'): 'LOOP',
    ('pages/Live.tsx', '一个代理此刻是「在飞 / 待机 / 静默 / 未读到」哪一档，看名册树那一行的徽标'): 'STATE',
    ('pages/Live.tsx', '紧挨着「在飞」那张卡，因为"谁在跑"与"它是谁的子"是同一个问题。 */}'): 'PAGE',
    ('pages/Live.tsx', '叫停的落点是工作区 <span class="mono">runs/</span> 下那一个跨进程开关：在飞的循环'): 'LOOP',
    ('pages/Machine.tsx', '* 现在 `GET /api/live`（在飞面）给了它，卡片改成指路「在飞」页 ——'): 'PAGE',
    ('pages/Machine.tsx', 'right={<Badge kind="badge-pass" text="已接线：见「在飞」页" />}'): 'PAGE',
    ('pages/Machine.tsx', '「在飞」'): 'PAGE',
    ('pages/Run.tsx', '* 后端 `GET /api/live`（在飞面）给停机开关与历史、`POST /api/stop` 给按钮，'): 'PAGE',
    ('pages/Run.tsx', '// 在飞面：这一页只用它的「停机开关」那一格（谁按的、按没按过）。'): 'PAGE',
    ('pages/Run.tsx', '叫停的落点是一个跨进程开关（工作区 runs/ 下那一份）：在飞的循环在下一个步检查点'): 'LOOP',
    ('pages/Run.tsx', '「在飞」页能看到开关是谁按的、以及最近几条停机历史，那里也有同一对按钮。'): 'PAGE',
    ('pages/Run.tsx', '{/* R93：这对按钮与「在飞」页共用同一份实现（`components/Stop.tsx`）——'): 'PAGE',
    ('rosterTree.ts', '// ====================================================================== 三态（在飞 / 待机 / 静默）'): 'STATE',
    ('rosterTree.ts', '// 业主 2026-10-26：「『在飞』的读数要随着时钟式待机进行适配，分三种……更新『活跃子代理』'): 'STATE',
    ('rosterTree.ts', '/** 一个代理的三态（业主 2026-10-26：「『在飞』的读数要随着时钟式待机进行适配」）。'): 'STATE',
    ('rosterTree.ts', '* - `flying` 在飞：正在工作；'): 'STATE',
    ('rosterTree.ts', 'flying: "在飞",'): 'STATE',
    ('rosterTree.ts', '/** 活跃 = 非静默 = 在飞 + 待机（业主：「更新『活跃子代理』的定义为非静默子代理」）。'): 'STATE',
    ('rosterTree.ts', '/** 四档各几个 + `active`（= 在飞 + 待机）+ `total`。 */'): 'STATE',
    ('rosterTree.ts', '/** 行尾那一格「活 N（飞 a · 待 b）」：N = 非静默 = 在飞 + 待机。'): 'STATE',
    ('rosterTree.ts', '* 页面每一处说"活跃"都从这里取：活跃 = 非静默 = 在飞 + 待机，`未读到` 不在里面。'): 'STATE',
    ('rosterTree.ts', '"在飞 / 待机 / 静默：未读到（这一份读数没给出合计，因此不显示任何数字）";'): 'STATE',
    ('rosterTree.ts', '/** 顶部合计那一行：`在飞 a · 待机 b · 静默 c`（读不到就说读不到 + 一句原因，不显示 0）。 */'): 'STATE',
    ('rosterTree.ts', '/** 活跃（非静默）= 在飞 + 待机；`null` = 没读到（不许折成 0）。 */'): 'STATE',
    ('rosterTree.ts', '* `active` = 在飞 + 待机、`total` = 四档之和都是**定义**；后端那两格只是同一件事的'): 'STATE',
    ('rosterTree.ts', 'notes.push(`合计里的 active（${activeRaw}）不等于在飞 + 待机（${active}）`'): 'STATE',
    ('rosterTree.ts', 'let text = `在飞 ${flying} · 待机 ${standby} · 静默 ${silent}`;'): 'STATE',
    ('rosterTree.ts', 'let text = `在飞 ${tally.flying} · 待机 ${tally.standby} · 静默 ${tally.silent}`;'): 'STATE',
    ('types.ts', '/** 出处：live_face() —— 在飞的循环 / 活进程 / 停机开关与历史（行逐字来自 stopctl）。 */'): 'LOOP',
}

#: 五个判决档的一句话理由（白名单里每一处都归其中一档）。
_REASONS: dict[str, str] = {
    "PAGE": "页面名 / 面名（「在飞」页 = /live，业主 2026-10-12 命名）：不是读数",
    "STATE": "代理三态里 flying 那一档（或三态口径的说明）：正是这一批要的那一档",
    "TASK": "任务面的「在飞」（台账行 status ∈ pending/running / in_flight）："
            "不是代理三态，页面已逐字标明口径",
    "LOOP": "循环 / 进程面的「在飞」（stopctl 的那一趟循环）：不是代理三态",
    "NOTE": "说明文：显式写「这里不说在飞 / 表里有它不等于它在飞」，留着正是为了防止读混",
}

#: 这些形态出现在一行含「在飞」的代码里就是缺陷（注释不算：注释在讲"不是它"）。
_BANNED: tuple[tuple[str, str], ...] = (
    ("children.length", "把子节点个数（children.length）当成「在飞 / 活跃」的计数"),
    ("kids.length", "把树上的子行数（kids.length）当成「在飞 / 活跃」的计数"),
    ("in_flight", "把任务面的 in_flight 印成「在飞」"),
    (".length", "用数组长度冒充「在飞 / 活跃」的计数"),
)

#: 旧写法的字面（改前那一枚徽标）。它出现即红，不管在哪一行。
_OLD_WORDINGS: tuple[str, ...] = ("件在跑",)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _strip_comments(text: str) -> str:
    """剥掉注释后的源码（块注释含 JSX 的 `{/* ... */}`；整行 `//` 也算注释）。"""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _source_texts() -> dict[str, str]:
    """`ui/src/**` 下每个 TS / TSX 文件的文本（相对路径 -> 文本）。"""
    out: dict[str, str] = {}
    for path in sorted(UI_SRC.rglob("*")):
        if path.suffix not in (".ts", ".tsx"):
            continue
        out[path.relative_to(UI_SRC).as_posix()] = path.read_text(encoding="utf-8")
    return out


def _audit_problems(sources: Mapping[str, str]) -> list[str]:
    """源码级判据本体：每一处「在飞」都有判决，且没有把「在飞」当「活跃」用的写法。

    三件事：
    1. 每一行含「在飞」的都必须登记在白名单里（逐行）；
    2. 白名单里每一条都必须还在盘上（过期即红）；
    3. 非注释代码里不许出现 `children.length` / `kids.length` / `in_flight` /
       `.length` 与「在飞」同行的计数写法，也不许出现旧字面「件在跑」。
    """
    problems: list[str] = []
    present: set[tuple[str, str]] = set()
    for rel, text in sources.items():
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "在飞" not in line:
                continue
            key = (rel, line.strip())
            present.add(key)
            if key not in _ALLOWED:
                problems.append(
                    f"{rel}:{lineno} 有一处「在飞」没登记判决（逐处白名单）：{line.strip()!r}")
    for key in _ALLOWED:
        if key not in present:
            problems.append(
                f"白名单过期：{key[0]} 里已经没有这一行 {key[1]!r}"
                "（改了就重新判一次，别让登记烂在表里）")
    for rel, text in sources.items():
        for lineno, line in enumerate(_strip_comments(text).splitlines(), start=1):
            if "在飞" in line:
                for needle, why in _BANNED:
                    if needle in line:
                        problems.append(f"{rel}:{lineno} {why}：{line.strip()!r}")
            for needle in _OLD_WORDINGS:
                if needle in line:
                    problems.append(f"{rel}:{lineno} 旧写法「{needle}」还在：{line.strip()!r}")
    return problems


def test_every_flying_word_in_the_ui_is_a_registered_decision() -> None:
    """正控：`ui/src/**` 里每一处「在飞」都在白名单里，且没有把「在飞」当「活跃」用。"""
    sources = _source_texts()
    assert sources, "ui/src 下一个 TS/TSX 都没读到 ⇒ 这条判据是空转"
    problems = _audit_problems(sources)
    assert problems == [], problems
    # 反真空：白名单不许退化成空壳；五档判决都要真的用上（有一档用不上 = 它写错了）。
    assert len(_ALLOWED) >= 60, len(_ALLOWED)
    assert {reason for reason in _ALLOWED.values()} == set(_REASONS), (
        "有判决档没被用上（或用了词表外的档）："
        f"{sorted({r for r in _ALLOWED.values()})}")
    # 三态那一档的文字（flying = 在飞）必须真的在词表里 —— 否则上面那些 STATE 都是空谈。
    assert 'flying: "在飞"' in sources["rosterTree.ts"]


def test_planting_the_old_style_turns_the_audit_red() -> None:
    """负控：塞一处旧写法 / 塞一处没判决的「在飞」/ 删一行白名单 ⇒ 都必须红。"""
    sources = dict(_source_texts())
    rel = "components/Roster.tsx"

    # 一 旧写法：把子节点个数印成「在飞 N 个」
    planted = dict(sources)
    planted[rel] = planted[rel] + '\nconst old = `在飞 ${node.children.length} 个`;\n'
    problems = _audit_problems(planted)
    assert any("children.length" in p for p in problems), problems
    assert any("没登记判决" in p for p in problems), problems

    # 二 只塞一句无害的「在飞」也红：白名单是穷尽的，不是"只挡已知写法"
    benign = dict(sources)
    benign[rel] = benign[rel] + '\nconst another = "在飞";\n'
    assert _audit_problems(benign), "新加一处「在飞」没人判，判据却一声不吭"

    # 三 旧徽标写法（任务面的 in_flight 印成「件在跑」）也红
    badge = dict(sources)
    badge[rel] = badge[rel] + '\nconst line = <span>{`活 ${node.in_flight} 件在跑`}</span>;\n'
    assert any("件在跑" in p for p in _audit_problems(badge)), _audit_problems(badge)

    # 四 白名单过期（那一行被删掉）也红
    victim_rel, victim_line = next(iter(_ALLOWED))
    dropped = dict(_source_texts())
    dropped[victim_rel] = "\n".join(
        line for line in dropped[victim_rel].splitlines() if line.strip() != victim_line)
    assert any("白名单过期" in p for p in _audit_problems(dropped)), (
        f"删掉白名单登记的那一行（{victim_rel}），判据却一声不吭")


# ====================================================================== 源码级：呈现落点
def test_the_state_badge_hovers_the_reason_and_the_css_has_four_buckets() -> None:
    """三态在页面上的落点：徽标悬停给 `state_reason`、四档各有自己的视觉档。

    - `stateBadge` 必须把 `state_reason` 绑到徽标的 `title` 上（三档文字说得清"哪一档"，
      说不清"凭什么"；待机与静默的差别就在理由里）；
    - 顶部合计必须把 `summary.active` 与 `summary.reason` 都摆出来（读不到时那一句
      原因上屏，正是"未读到 + 原因"）；
    - CSS 四档的类都在（在飞 = 强调色 / 待机 = 中性偏冷 / 静默 = 灰 / 未读到 = 警示）。
    """
    roster = ROSTER_TSX.read_text(encoding="utf-8")
    assert "stateTitle(" in roster and "state_reason" in roster, (
        "三态徽标没有把 state_reason 绑上去 ⇒ 悬停看不到'为什么是这一档'")
    assert "title={stateTitle(node)}" in roster, (
        "stateBadge 没有把 stateTitle 传给 Badge 的 title")
    assert "summary.reason" in roster, "顶部合计没把 reason 上屏（未读到那一档就说不清原因）"
    assert "summary.active" in roster, "顶部合计没摆出「活跃（非静默）」那一格"
    assert "summary.active === null" in roster, (
        "活跃那一格没有'未读到'分支（会折成 0）")

    tree = TREE_TS.read_text(encoding="utf-8")
    assert 'export const ACTIVE_TEXT = "活跃（非静默）";' in tree, (
        "「活跃」的措辞不是「活跃（非静默）」⇒ 读的人分不出这是哪一套口径")

    css = APP_CSS.read_text(encoding="utf-8")
    missing = [name for name in ("roster-state-flying", "roster-state-standby",
                                 "roster-state-silent", "roster-state-unknown")
               if f".{name}" not in css]
    assert not missing, f"三态徽标的视觉档缺了：{missing}（四档必须各有一个类）"
