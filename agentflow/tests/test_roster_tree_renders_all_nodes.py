# -*- coding: utf-8 -*-
"""名册树：数据里有的节点一个都不许静默丢失（真机故障 D-51 之后那一版）。

## 现场

名册页整片不显示，只有抬头「节点 N 个 · 最深 M 层」还在。抬头的两个数取自
`count` / `max_depth`，正文那一段（`.roster-tree`）一行都没有。

## 成因（可执行的读数，不是猜）

真机上跑着的那个 `webui` 进程是 17:36:34 起的，而 D-51 在 18:15:10 才落盘；所以
浏览器拿到的是新前端 + 旧后端。旧后端那 15 个顶层键里没有 `children_of`：

    answer,count,coverage,diagnostics,dir,files,max_depth,nodes,reason,
    root,roots,tasks_reason,tasks_tri,tri,truncated

而改前的渲染在 `Roster.tsx` 里对它直取（第 245 行 `ctx.childrenOf[tid] ?? []`、
第 378 行 `data.children_of[tid] ?? []`），`ctx.childrenOf` 是 `undefined` 时
`?? []` 救不了它 —— 取属性这一步就抛了：

    TypeError: Cannot read properties of undefined (reading 't-000001')

第一个根（`t-000001`）就抛，于是 `.roster-tree` 那一段永远到不了 DOM；抬头那一行
已经提交出去了，所以「抬头在、树没有」正是这个形态。

## 这一份守什么

| 判据 | 它守的是 | 改前红在哪 |
|---|---|---|
| ① `test_the_tree_draws_every_node_of_the_reading` | 前端算出的"画出来的节点集合" == 读者给的 `nodes` 全集（一个不丢），两种读数形状（带 / 不带 `children_of`）都要成立 | 不带 `children_of` 那一份：改前抛 TypeError，画出 0 个（见 `test_the_pre_fix_path_draws_nothing_...`） |
| ② `test_a_truncated_reading_gets_a_row_for_every_missing_id` | `truncated=true` 时被父子关系点名、却不在 `nodes` 里的编号，逐个有一行可见说明（文字里带 `task_id`），且树顶上有一行汇总 | 改前连树都画不出来；说明行只在"递归已经跑起来"之后才可能出现在 `renderBranch` 里 |
| ③ `test_empty_roots_fall_back_to_parent_task_id` | `roots` 为空而 `nodes` 非空 ⇒ 按 `parent_task_id == ""` 退化找根，仍然全画出（不靠"平铺兜底"补数） | 改前是 `data.roots.map(...)` 直取，`roots=[]` ⇒ 一个分支都不产生，只能落到平铺兜底那一段 |
| ④ `test_stubbing_the_recursion_entry_makes_one_and_two_red` | 反真空：把递归入口打桩成返回空 ⇒ ①② 必红 | 不适用（它是守①②不是真空的那一条） |

## 为什么能跑起前端

名册树的"画哪些行"这件事被抽成了纯函数（`ui/src/rosterTree.ts`），不 import
`preact`。判据用 `node` + `ui/node_modules/typescript` 把它即时转成 ESM，再喂真
读者给的那一份 JSON，读出"画出来的集合"。Python 这一侧跑不起 Preact，但"画哪些
行"本来就不该跟 Preact 绑在一起 —— 这也是这次故障的教训之一：把取数与递归留在组件
里，它就只能靠肉眼看。

三档口径：没装 node / 依赖没装 ⇒ skip（记 unknown，不记 pass）；转译或跑不起来
⇒ 红（那是判据没查成，不是"查过了没问题"）。
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from typing import Any, Mapping

import pytest

from agentflow.secretary import Secretary
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI = REPO / "ui"
UI_SRC = UI / "src"
TREE_TS = UI_SRC / "rosterTree.ts"
ROSTER_TSX = UI_SRC / "components" / "Roster.tsx"
TYPESCRIPT_LIB = UI / "node_modules" / "typescript" / "lib" / "typescript.js"

#: 真机工作区（只读）。不在盘上就 skip 那一条判据，别的判据照旧跑夹具。
REAL_WORKSPACE = REPO / "projects" / "sylow3"

#: 夹具的根（它不在任何人的名册里）。
ROOT_ID = "t-000001"

#: 夹具的三层树（父 -> 直接子，按落盘行序）：
#: 根两子（先 F1 后 C1）、F1 两子（先 V1 后 B1）、C1 一子、V1 一子。
EXPECTED_CHILDREN: dict[str, list[str]] = {
    ROOT_ID: ["t-000003", "t-000002"],
    "t-000003": ["t-000004", "t-000005"],
    "t-000002": ["t-000006"],
    "t-000004": ["t-000007"],
}


# ====================================================================== 夹具
def _tree_workspace(tmp: pathlib.Path) -> pathlib.Path:
    """造一棵四层树（7 个节点）：写侧仍然是 `Secretary.roster_add`。

    手抄 JSONL 等于把盘上格式再定义一遍，两处迟早漂移（与
    `tests/test_roster_renders_as_a_tree.py` 同一条理由）。
    """
    root = tmp / "ws"
    root.mkdir()
    Store(root).init()
    sec = Secretary("M", root=root, store=Store(root))
    adds = (
        (ROOT_ID, "F", "t-000003", "攻主命题的引理"),
        (ROOT_ID, "C", "t-000002", "梳理证明链"),
        ("t-000003", "V", "t-000004", "核这一段的引文"),
        ("t-000003", "B", "t-000005", "把命题登记进台账"),
        ("t-000002", "E", "t-000006", "搜外部文献"),
        ("t-000004", "D", "t-000007", "起草证明正文"),
    )
    for owner, role, task_id, brief in adds:
        got = sec.roster_add(owner=owner, role=role, task_id=task_id, brief=brief)
        assert got["problem"] == "", got
        assert got["task_id"] == task_id, got
    return root


def _reading(tmp: pathlib.Path) -> dict[str, Any]:
    """读者给的那一份读数（判据的输入真身：不从实现里抄形状）。"""
    face = R.roster_face(_tree_workspace(tmp))
    assert face["answer"] == "ok", face["reason"]
    return dict(face)


def _without_children_of(face: Mapping[str, Any]) -> dict[str, Any]:
    """真机那一份读数：旧后端不发 `children_of` 这一格（其余 15 个键照旧）。"""
    out = dict(face)
    out.pop("children_of", None)
    return out


def _truncated(face: Mapping[str, Any], *, keep_depth: int = 2) -> dict[str, Any]:
    """`truncated=true` 的那一档：只留前两层节点，父子关系仍有完整编号。

    读者那一侧的口径是"截断只截 `nodes`，`children_of` 仍是完整的父子关系"
    （`readers.roster_face` 的 docstring 逐字写了），所以这里照那个形状造：
    被截掉的编号仍出现在父的子列表里 —— 那正是"点到不在 nodes 里的编号"。
    """
    out = dict(face)
    nodes = [n for n in face.get("nodes") or [] if int(n.get("depth") or 0) <= keep_depth]
    out["nodes"] = nodes
    out["count"] = len(nodes)
    out["truncated"] = True
    return out


# ====================================================================== 期望值
def _expected_ids(face: Mapping[str, Any]) -> set[str]:
    """这次读数里"有的那些节点"：树必须把它们的每一个都画出来。"""
    return {str(n.get("task_id") or "") for n in face.get("nodes") or []}


def _referenced_but_absent(face: Mapping[str, Any]) -> set[str]:
    """父子关系点名了、可这次读数里没有那些编号（截断的可见后果）。

    期望值从读数本身算（不在前端实现里抄一遍）：只有"能被走到的父"的子才算 ——
    父自己都被截掉了，它的子就没人点名，自然也不该要求一行说明。
    """
    present = _expected_ids(face)
    children_of = face.get("children_of")
    edges: dict[str, list[str]] = {}
    if isinstance(children_of, dict):
        for parent, kids in children_of.items():
            edges[str(parent)] = [str(k) for k in kids or []]
    else:
        # 旧后端不发 children_of 那一格：父子关系只能从节点自己的 children 读。
        for node in face.get("nodes") or []:
            tid = str(node.get("task_id") or "")
            edges[tid] = [str(c.get("task_id") or "") for c in node.get("children") or []]
    out: set[str] = set()
    for parent in present:
        for kid in edges.get(parent) or []:
            if kid and kid not in present:
                out.add(kid)
    return out


# ====================================================================== 跑前端
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

const [modulePath, payloadPath, mode] = process.argv.slice(2);
const mod = await import(pathToFileURL(modulePath).href);
const payload = JSON.parse(readFileSync(payloadPath, "utf8"));

// 改前那一条路径（Roster.tsx 改前第 350-366 行 + 第 245 行）：
// byId 建好之后 `ctx.childrenOf[tid]` 直取，没有"这一格在不在"的判断。
function preFixDrawn(p) {
  const byId = new Map();
  for (const n of p.nodes) byId.set(n.task_id, n);
  const visited = new Set();
  const out = [];
  const walk = (tid) => {
    if (visited.has(tid)) return;
    const node = byId.get(tid);
    if (node === undefined) return;
    visited.add(tid);
    out.push(tid);
    for (const kid of p.children_of[tid] ?? []) walk(kid);
  };
  for (const root of p.roots) walk(root);
  return out;
}

const result = {
  mode,
  drawn: [],
  missing_rows: [],
  notes: [],
  missing: [],
  unreached: [],
  error: "",
  missing_text_sample: "",
};

try {
  result.missing_text_sample = mod.missingText("t-999999");
} catch (e) {
  result.error = String(e && e.message ? e.message : e);
}

if (mode === "pre_fix") {
  try {
    result.drawn = preFixDrawn(payload);
  } catch (e) {
    result.error = `${e.name}: ${e.message}`;
  }
} else if (mode === "stub") {
  // 反真空：把组件要调的那一个递归入口打桩成返回空树。
  const flat = mod.flattenRows([]);
  result.drawn = flat.filter((r) => r.kind === "node").map((r) => r.task_id);
} else {
  const tree = mod.buildRosterTree(payload);
  const flat = mod.flattenRows(tree.rows);
  result.drawn = flat.filter((r) => r.kind === "node").map((r) => r.task_id);
  result.missing_rows = flat
    .filter((r) => r.kind !== "node")
    .map((r) => ({ task_id: r.task_id, text: r.text }));
  result.notes = tree.notes;
  result.missing = tree.missing;
  result.unreached = tree.unreached.map((n) => n.task_id);
}
process.stdout.write(JSON.stringify(result));
"""


def _node_exe() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("没装 node ⇒ 前端渲染函数这一层记 unknown（不记 pass）")
    return node


#: 同一个临时目录里的那一次转译只做一遍（判据里会拿它跑好几份读数）。
_TRANSPILED: dict[str, pathlib.Path] = {}


def _module_js(tmp: pathlib.Path) -> pathlib.Path:
    """把纯函数那一份（`ui/src/rosterTree.ts`）转成 ESM（同一份 tmp 只转一次）。"""
    cached = _TRANSPILED.get(str(tmp))
    if cached is not None and cached.is_file():
        return cached
    node = _node_exe()
    if not TYPESCRIPT_LIB.is_file():
        pytest.skip("前端依赖没装（ui/node_modules/typescript 不在）⇒ 记 unknown（不记 pass）")
    assert TREE_TS.is_file(), (
        f"{TREE_TS.relative_to(REPO)} 不在盘上：名册树「画哪些行」没有可判的纯函数")
    out = tmp / "rosterTree.mjs"
    # `encoding="utf-8"` 不是装饰：node 按 UTF-8 往 stdout 写，而 `text=True` 不给编码时
    # Python 用本机 locale（中文 Windows = GBK）去解它 ⇒ 读线程抛 UnicodeDecodeError、
    # `proc.stdout` 变成空串，于是这一整个文件在那种机器上 6 条全红，红的却与被测代码
    # 毫无关系（判据自己的环境脆弱）。同 `tests/test_webui_three_state_reading.py` 的口径。
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


def _run(face: Mapping[str, Any], tmp: pathlib.Path, *, mode: str = "tree") -> dict[str, Any]:
    """把一份读数喂给前端那一个纯函数，读回"它画了哪些行"。"""
    node = _node_exe()
    module = _module_js(tmp)
    payload = tmp / f"payload-{mode}.json"
    payload.write_text(json.dumps(face, ensure_ascii=False), encoding="utf-8")
    runner = tmp / "runner.mjs"
    runner.write_text(_RUNNER_JS, encoding="utf-8")
    proc = subprocess.run([node, str(runner), str(module), str(payload), mode],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        f"前端那个纯函数在真读数上跑不起来（exit {proc.returncode}）："
        f"{((proc.stderr or '') + (proc.stdout or ''))[:1200]}")
    return json.loads(proc.stdout)


# ====================================================================== 判据本身
def _criterion_one_problems(tree: Mapping[str, Any],
                            face: Mapping[str, Any]) -> list[str]:
    """① 判据本身：画出来的节点集合 == 这次读数里有的节点集合（一个不丢、不重）。"""
    problems: list[str] = []
    if str(tree.get("error") or ""):
        problems.append(f"前端那一层抛了异常 ⇒ 一行都画不出来：{tree['error']}")
    want = _expected_ids(face)
    got = [str(x) for x in tree.get("drawn") or []]
    if len(got) != len(set(got)):
        dup = sorted({x for x in got if got.count(x) > 1})
        problems.append(f"有节点被画了不止一次：{dup}")
    lost = sorted(want - set(got))
    if lost:
        problems.append(f"数据里有、树上没有的节点：{lost}")
    extra = sorted(set(got) - want)
    if extra:
        problems.append(f"树上多出读数里没有的编号：{extra}")
    return problems


def _criterion_two_problems(tree: Mapping[str, Any],
                            face: Mapping[str, Any]) -> list[str]:
    """② 判据本身：被父子关系点名、可这次读数里没有的编号，逐个有可见说明行。

    三处一起看，缺一处就等于"静默丢"：
    - 每一行说明的文字里有那个 `task_id`（读的人认得出是哪一条）；
    - 文字里说了"这次读数里没有"（不是一句无从对号的空话）；
    - 树顶上那行汇总里也列了它（汇总不受折叠影响，展开态变了也还看得见）。
    """
    problems: list[str] = []
    want = _referenced_but_absent(face)
    rows = {str(r.get("task_id") or ""): str(r.get("text") or "")
            for r in tree.get("missing_rows") or []}
    for tid in sorted(want):
        text = rows.get(tid, "")
        if text == "":
            problems.append(f"{tid} 被父子关系点名、这次读数里又没有它，却没有任何一行说明")
            continue
        if tid not in text:
            problems.append(f"{tid} 的说明行里没有它自己的编号（文字：{text!r}）")
        if "这次读数里没有" not in text:
            problems.append(f"{tid} 的说明行没说清「这次读数里没有它」（文字：{text!r}）")
    listed = {str(x) for x in tree.get("missing") or []}
    unlisted = sorted(want - listed)
    if unlisted:
        problems.append(f"树顶那行汇总没列这些缺号：{unlisted}（折叠起来就再也看不见了）")
    return problems


def _panel_source_problems(text: str) -> list[str]:
    """面板源码真的把那张树（含说明行与汇总）画到 DOM 上。

    为什么还要一条源码判据：② 在"模型这一层"绿，不等于"页面上看得见" ——
    上一版就是模型与递归都在组件里、于是整棵树可以静默地一行不画。
    """
    problems: list[str] = []
    if "buildRosterTree(" not in text:
        problems.append("Roster.tsx 没有调 buildRosterTree(（树又不是从读数建的）")
    if "row.text" not in text:
        problems.append("Roster.tsx 没画说明行那一格（row.text）⇒ 缺号在页面上看不见")
    if "tree.notes.map" not in text:
        problems.append("Roster.tsx 没画降级说明（tree.notes）⇒ 读不到那一格时仍然静默")
    if "tree.missing" not in text:
        problems.append("Roster.tsx 没画缺号汇总（tree.missing）⇒ 折叠之后说明行就看不见了")
    return problems


# ====================================================================== ① 一个不丢
def test_the_tree_draws_every_node_of_the_reading(tmp_path: pathlib.Path) -> None:
    """判据①：真读者数据算出的节点集合，与前端纯函数算出的集合相等。

    两种读数形状都要成立：
    - 新后端那一份（带 `children_of`）；
    - 真机那一份（旧后端不发 `children_of`，其余键照旧）—— 名册页整片不显示的
      那次就是这个形状。
    """
    face = _reading(tmp_path)

    full = _run(face, tmp_path)
    assert (full["mode"], full["error"]) == ("tree", ""), full
    assert _criterion_one_problems(full, face) == [], _criterion_one_problems(full, face)
    assert sorted(full["drawn"]) == sorted(_expected_ids(face)), (
        "画出来的集合与 readers 给的 nodes 不是同一个集合", full["drawn"])
    # 7 个节点、最深 4 层 —— 与夹具那棵树对得上（前提真的立住了）。
    assert (face["count"], face["max_depth"]) == (7, 4), (face["count"], face["max_depth"])
    # 这一份读数没有可降级的地方 ⇒ 不该有说明行（说明行不是装饰）。
    assert full["notes"] == [], full["notes"]
    assert full["missing_rows"] == [], full["missing_rows"]
    assert full["unreached"] == [], full["unreached"]

    stale = _without_children_of(face)
    assert "children_of" not in stale
    fell = _run(stale, tmp_path)
    assert _criterion_one_problems(fell, stale) == [], _criterion_one_problems(fell, stale)
    assert sorted(fell["drawn"]) == sorted(_expected_ids(stale)), fell["drawn"]
    # 降级是有话说的：没有 children_of 就得明说"改按每个节点自己的 children"。
    assert any("children_of" in n for n in fell["notes"]), fell["notes"]


def test_the_pre_fix_path_draws_nothing_on_the_same_reading(
        tmp_path: pathlib.Path) -> None:
    """改前红（本次故障的复现）：同一份真读数上，改前那一条访问抛异常 ⇒ 画 0 个。

    这不是"另一份实现"，是把改前那两行（`ctx.childrenOf[tid]` 直取）按原样摆出来
    跑一遍 —— 证据与根因在同一处：`?? []` 救不了"表本身是 undefined"。
    """
    face = _without_children_of(_reading(tmp_path))
    broke = _run(face, tmp_path, mode="pre_fix")
    assert "TypeError" in broke["error"], (
        "改前那条路径居然没抛异常 ⇒ 上面写的根因不成立，别照这个修", broke)
    assert broke["drawn"] == [], broke["drawn"]
    assert _criterion_one_problems(broke, face), (
        "改前那条路径在真读数上居然判绿 ⇒ ① 的判据分不出「整片不显示」")


# ====================================================================== ② 截断
def test_a_truncated_reading_gets_a_row_for_every_missing_id(
        tmp_path: pathlib.Path) -> None:
    """判据②：`truncated=true` 时，缺的节点逐个有可见说明行，且说明里带 task_id。

    两种形状都跑：带 `children_of` 的那一份（截断只截 nodes），以及旧后端那种
    没有 `children_of`、只能从节点自己的 children 看出被截掉的编号的那一份。
    """
    face = _reading(tmp_path)
    cut = _truncated(face)
    want = _referenced_but_absent(cut)
    assert want, ("夹具前提没立住：截断之后居然没有任何「被点名却不在读数里」的编号",
                  sorted(want))

    trimmed = _run(cut, tmp_path)
    assert _criterion_two_problems(trimmed, cut) == [], _criterion_two_problems(trimmed, cut)
    # 说明行的措辞就是业主那一句：这次读数里没有 t-XXXX（可能被截断）。
    assert trimmed["missing_text_sample"] == "这次读数里没有 t-999999（可能被截断）", (
        trimmed["missing_text_sample"])
    assert sorted(trimmed["missing"]) == sorted(want), (trimmed["missing"], sorted(want))
    # 而这些说明行不是替代品：还在读数里的节点照样一个不少地画出来。
    assert _criterion_one_problems(trimmed, cut) == [], _criterion_one_problems(trimmed, cut)
    assert trimmed["unreached"] == [], trimmed["unreached"]

    # 没有 children_of 的那一份：缺号要从节点自己的 children 看出来。
    cut_stale = _truncated(_without_children_of(face))
    want_stale = _referenced_but_absent(cut_stale)
    assert want_stale, "夹具前提没立住：这一份上没有可说的缺号"
    stale = _run(cut_stale, tmp_path)
    assert _criterion_two_problems(stale, cut_stale) == [], (
        _criterion_two_problems(stale, cut_stale))
    assert sorted(stale["missing"]) == sorted(want_stale), (stale["missing"], sorted(want_stale))

    # 面板真的把这一格画出来了（模型绿 != 页面上看得见）。
    problems = _panel_source_problems(ROSTER_TSX.read_text(encoding="utf-8"))
    assert problems == [], problems


# ====================================================================== ③ 退化找根
def test_empty_roots_fall_back_to_parent_task_id(tmp_path: pathlib.Path) -> None:
    """判据③：`roots` 为空而 `nodes` 非空 ⇒ 按 `parent_task_id == ""` 找根，仍然全画。

    三处一起看：
    - 画出来的集合仍然是全集（一个不丢）；
    - 没有一个节点落到"从根上走不到"那一段（退化的根就是根，不是兜底平铺）；
    - 说明里点了这次退化的口径（读的人知道这一份读数的根是自己找出来的）。
    """
    face = _reading(tmp_path)
    for label, payload in (
        ("带 children_of", {**_without_roots(face)}),
        ("没有 children_of", _without_roots(_without_children_of(face))),
    ):
        tree = _run(payload, tmp_path)
        assert _criterion_one_problems(tree, payload) == [], (
            label, _criterion_one_problems(tree, payload))
        assert sorted(tree["drawn"]) == sorted(_expected_ids(payload)), (label, tree["drawn"])
        assert tree["unreached"] == [], (
            f"{label}：roots 为空时这些节点没被当成树的一部分：{tree['unreached']}")
        assert any("roots" in n or "根" in n for n in tree["notes"]), (label, tree["notes"])
    # 反向前提：这些读数上"根"确实一个都不剩，否则这条判据是空转。
    assert _without_roots(face)["roots"] == []


def _without_roots(face: Mapping[str, Any]) -> dict[str, Any]:
    """`roots` 那一格是空的（读侧没给根 / 给了空数组）。"""
    out = dict(face)
    out["roots"] = []
    return out


# ====================================================================== ④ 反真空
def test_stubbing_the_recursion_entry_makes_one_and_two_red(
        tmp_path: pathlib.Path) -> None:
    """判据④（反真空）：把递归入口打桩成返回空树 ⇒ ①② 必红。

    没有这一条，① 可能以"读数恰好只有根、根被画一次"的形态绿着，② 可能以"本来就
    没有缺号"的形态绿着，而它们守的那两件事（一个不丢、缺号有话说）其实没人核。
    """
    face = _reading(tmp_path)
    cut = _truncated(face)
    # 正控：打桩之前 ①② 都该是绿的。
    assert _criterion_one_problems(_run(face, tmp_path), face) == []
    assert _criterion_two_problems(_run(cut, tmp_path), cut) == []

    stub = _run(face, tmp_path, mode="stub")
    assert stub["drawn"] == [], "打桩没生效（递归入口还画出了节点）"
    assert _criterion_one_problems(stub, face), (
        "把递归入口打桩成返回空树，① 的判据却一声不吭 ⇒ 那条判据是真空的")
    assert _criterion_two_problems(stub, cut), (
        "把递归入口打桩成返回空树，② 的判据却一声不吭 ⇒ 那条判据是真空的")


# ====================================================================== 真机读数
def test_the_real_workspace_reading_draws_every_node(
        tmp_path: pathlib.Path) -> None:
    """真机那一份读数（sylow3，只读）也要一个不丢 —— 两个形状都看。

    不在盘上就 skip：CI 里没有 `projects/`，那一条是 unknown，不是 pass。
    """
    if not (REAL_WORKSPACE / "out" / "roster").is_dir():
        pytest.skip(f"真机工作区不在盘上（{REAL_WORKSPACE.relative_to(REPO)}）⇒ 记 unknown")
    face = dict(R.roster_face(REAL_WORKSPACE))
    assert face["answer"] == "ok", face["reason"]
    assert _expected_ids(face), "真机读数里一个节点都没有 ⇒ 这条判据没有落脚点"

    full = _run(face, tmp_path)
    assert _criterion_one_problems(full, face) == [], _criterion_one_problems(full, face)

    stale = _without_children_of(face)
    fell = _run(stale, tmp_path)
    assert _criterion_one_problems(fell, stale) == [], _criterion_one_problems(fell, stale)

    # 真机这一份现在也是"没有缺号"的（truncated=false）：说明行不许凭空冒出来。
    assert full["missing"] == [], full["missing"]
    assert full["unreached"] == [], full["unreached"]
