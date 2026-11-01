# -*- coding: utf-8 -*-
"""判据（D6）：「在飞」页的进程面不许把宿主进程 pid 印成每一行自己的 pid。

## 改前是什么样

`ui/src/pages/Live.tsx` 的进程面那一张表有一列叫 `pid`，每一行印的是
`live_pids()` 给出的登记文件里的 `pid` —— 那是宿主进程的 pid
（`stopctl.register_pid` 写的是"父进程自己"）。

三件事叠起来让"每行一个 pid"这个读法变成假的：

1. `data/tasks.json` 里根本没有 pid 列（`schema.Task` 的 26 个字段里没有它）——
   所以那一格不可能来自"这一行的角色"的台账；
2. 同一趟 run 里所有角色共用同一个宿主进程（一次 `run-agent` 里主控与它召唤的子角色
   都在同一个进程里跑）⇒ 多行会印出同一个号，读的人会以为"这几行是同一个被召唤者"；
3. 真正定位"这一行是谁"的键是 `sid` + `role`（名册里的 `task_id` 在另一张卡上）。

## 这一份守什么

| 判据 | 落点 |
|---|---|
| ① 列名写清它是什么 | `Live.tsx` 里那一列的表头逐字是 `宿主进程 pid`，且有一句说明 |
| ② 说明里写出"共用"这件事 | 表头上方那句必须同时出现"宿主进程"与"共用"（否则"宿主进程"三个字也是黑话） |
| ③ 反真空：改回旧文案 ⇒ 红 | 把列名换回 `pid` / 把说明删掉，同一个检查函数必须报出来 |
| ④ 那一格真印出这一行的 pid | 把那一列的 render 真跑一遍（node 里喂两行不同 pid + 三行没有 pid）：两行印出两个不同的号；缺 pid 时印 `unknown` / `—`（三态），不是字面量 `undefined` |
| ⑤ 反真空：渲染坏了 ⇒ 红 | 把 render 换成固定字面量 ⇒ ④ 的检查必须报；换回 `String(r.pid)` ⇒ 缺值档变 `undefined` ⇒ 必须报 |
| ⑥ 后端互证 | 同一进程登记两个角色 ⇒ `live_face` 两行的 pid 逐字相等（所以"每行 pid"没有分辨力） |

⑥是"这条判据为什么成立"的证据，①–⑤是"页面照做了"的证据：缺 ⑥ 的话，
文案可以随便写；缺 ①–⑤ 的话，后端读数对而页面照旧印"pid"。

## 2026-11-01：④ 原先是「源码里有 `String(r.pid)`」，这一笔把它改成「真跑那一列」

改前那条写法是 `if "String(r.pid)" not in source: …` —— 它断言的是源码文本。
上一轮把 `Live.tsx:106` 的 `String(r.pid)` 换成了 `cell(r.pid)`（可读性修法；有值时
输出逐字不变），两条判据当场红，而实现是对的。更要紧的是：这条判据与
`tests/test_webui_cells_never_print_undefined_or_unknown.py` 的 R1 互斥 ——
后者把单元格里裸 `String(r.x)` 判为缺陷，且文件头逐字列着 `Live.tsx:106` 是
"已修掉的 8 处之一"。两条判据不可能同时绿，而互斥是静默的（不同文件、不同时间红）。

为什么改成行为不是放宽：断言从"源码里有某段文本"变成"真跑出来是这一行的 pid、
缺了就三态"。改掉的那段文本对应的实现变了（缺 pid 时 `undefined` → `unknown`），
而那正是本页 `Live.tsx:13-15` 写死的三态承诺与 `components/Table.tsx` 的 `cell()`
契约 —— 是修法，不是回归。

## `node` 不在盘上时

④ 走 `tests/nodejs.py` 那一份共用帮手（与 `test_webui_three_state_reading.py` /
`test_the_root_is_named_m.py` / `test_roster_tree_renders_all_nodes.py` 同一份）：
没装 node / 没装 typescript ⇒ `skip` 并写明"记 unknown（不记 pass）"，汇总行里
读得出来；转译或跑不起来 ⇒ 断言红（那是装置坏了，不是环境）。

## 改前红在哪

①的列名是 `pid`（判据里那条"逐字等于 `宿主进程 pid`"直接红），②的说明整句不存在。
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib

import nodejs as NODE

from agentflow import schema as S
from agentflow import stopctl as SC
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE_TSX = REPO / "ui" / "src" / "pages" / "Live.tsx"
TABLE_TSX = REPO / "ui" / "src" / "components" / "Table.tsx"

#: 那一列的表头（改前是 `pid`）。
PID_TITLE = "宿主进程 pid"

#: 真跑那一列时喂的几行：前两行 pid 不同（证明印的是这一行的号），后三行没有 pid
#: （`{}` / `null` / 空串 —— 三态里"这一格没有"的三种来法）。
PID_ROWS: tuple[dict[str, object], ...] = (
    {"pid": 4321},
    {"pid": 9999},
    {},
    {"pid": None},
    {"pid": ""},
)

#: 缺 pid 时允许的两种显示：`cell()` 的 `unknown`（没读到）/ `blank()` 的 `—`（没有正文）。
#: 都表示"这一格没有"，不接受字面量 `undefined`（那正是 R1 要挡的形态）。
MISSING_WORDS = ("unknown", "—")


# ====================================================================== ①② 列名与说明
def _pid_label_problems(source: str) -> list[str]:
    """进程面那一列"叫什么、说明白了没有"（纯函数：给负控喂人造源码用）。

    只看 `Live.tsx` 里那几个关于 pid 的字符串，不做全文匹配：
    `running` 那张表也印 `sid`，全文匹配会让"表头改了、说明没改"照样绿。

    渲染那一半不在这里判：那是"真跑出来是什么"（④），由
    :func:`_render_problems` 判 —— 在这里再断言一段源码文本，就是 2026-11-01
    那次"把改进判成回归"的形态。
    """
    problems: list[str] = []
    if f'title: "{PID_TITLE}"' not in source:
        problems.append(
            f"进程面那一列的表头不是逐字的 `{PID_TITLE}`：读的人会把宿主进程的 pid "
            "当成这一行自己的 pid（同一趟 run 里多行会印出同一个号）")
    if f'title: "{PID_TITLE}"' in source and 'title: "pid"' in source:
        problems.append("进程面里还留着一列只叫 `pid` 的表头（两个口径并存）")
    # 说明那一句：必须同时写出"宿主进程"与"共用"（只写"宿主进程"仍是黑话）。
    notes = [ln for ln in source.splitlines()
             if "宿主进程" in ln and "共用" in ln and not ln.lstrip().startswith("*")]
    if not notes:
        problems.append(
            "进程面表头上方没有一句人话说明：它必须同时写出『宿主进程』与『共用』"
            "（同一趟 run 里所有角色共用一个宿主进程 ⇒ 多行会印同一个号）")
    return problems


def _live_source() -> str:
    return LIVE_TSX.read_text(encoding="utf-8")


# ====================================================================== ④ 真跑那一列
def _balanced(text: str, start: int) -> str:
    """从 `start`（一个 `(` / `[` / `{`）取到配对的闭合括号，含闭合那个（跳过字符串）。"""
    depth = 0
    out: list[str] = []
    quote = ""
    for ch in text[start:]:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        out.append(ch)
        if depth == 0 and len(out) > 1 and out[0] in "([{" and ch in ")]}":
            break
    return "".join(out)


def _column_body(source: str, key: str = "pid") -> str:
    """`key: "pid"` 那一列的对象正文（含花括号）。

    找不到就是判据自己过期了 —— 明确报出来，别静默退化成"扫不到 ⇒ 恒绿"。
    """
    at = source.find(f'key: "{key}"')
    assert at >= 0, f"`Live.tsx` 里找不到 `key: \"{key}\"` 那一列（判据自己过期了）"
    begin = source.rfind("{", 0, at)
    assert begin >= 0, f"`key: \"{key}\"` 前面没有对象起始的 `{{`（判据自己过期了）"
    chunk = _balanced(source, begin)
    assert chunk.startswith("{") and chunk.endswith("}"), (
        f"`key: \"{key}\"` 那一列的对象没有取平衡：{chunk[:120]!r}")
    return chunk


def _render_expr(column: str) -> str:
    """那一列 `render:` 的整段（含 `(r) =>`）；没有 `render:` ⇒ 空串。

    空串的意思是"走 `Table` 的缺省读法 `cell(row[key])`"——那也是这一格的实现，
    判据照跑，不把"没写 render"当成缺陷（写法与行为分开判）。
    """
    at = column.find("render:")
    if at < 0:
        return ""
    start = at + len("render:")
    expr: list[str] = []
    depth = 0
    quote = ""
    for ch in column[start:]:
        if quote:
            expr.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'`":
            quote = ch
            expr.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        expr.append(ch)
    return "".join(expr).strip()


#: 把那一列的 render 喂几行读数 → 读回每一格上屏的文字。
#:
#: `h` 是判据自己注入的（`{type, props, children}` 的极简 vnode），`cell` 来自
#: `components/Table.tsx` 转出来的真那一份 —— 不引 preact、不碰 DOM。
_RUNNER_JS = r"""
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const [renderPath, payloadPath] = process.argv.slice(2);
const mod = await import(pathToFileURL(renderPath).href);
const payload = JSON.parse(readFileSync(payloadPath, "utf8"));

function text(v) {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.map(text).join("");
  if (typeof v === "object") return text(v.children);
  return String(v);
}

const out = { cells: [], error: "" };
try {
  for (const row of payload.rows) out.cells.push(text(mod.render(row)));
} catch (e) {
  out.error = String(e && e.stack ? e.stack : e);
}
process.stdout.write(JSON.stringify(out));
"""


def _render_pid_cells(source: str, tmp: pathlib.Path) -> list[str]:
    """把 `key: "pid"` 那一列真跑一遍，返回 :data:`PID_ROWS` 每一格上屏的文字。"""
    tmp.mkdir(parents=True, exist_ok=True)
    expr = _render_expr(_column_body(source)) or "(r) => cell(r.pid)"
    NODE.transpile(TABLE_TSX, tmp / "table.mjs", jsx_factory="h")
    (tmp / "h.mjs").write_text(
        "export const h = (type, props, ...children) => ({ type, props, children });\n"
        "export const Fragment = (props) => props.children;\n", encoding="utf-8")
    render_tsx = tmp / "pid-column.tsx"
    render_tsx.write_text(
        "import { h } from './h.mjs';\n"
        "import { cell } from './table.mjs';\n"
        f"export const render = {expr};\n", encoding="utf-8")
    render_mjs = NODE.transpile(render_tsx, tmp / "pid-column.mjs", jsx_factory="h")
    payload = tmp / "pid-rows.json"
    payload.write_text(json.dumps({"rows": list(PID_ROWS)}, ensure_ascii=False),
                       encoding="utf-8")
    runner = tmp / "pid-runner.mjs"
    runner.write_text(_RUNNER_JS, encoding="utf-8")
    got = NODE.run_json(runner, str(render_mjs), str(payload),
                        what="把 pid 那一列真跑一遍失败")
    assert got["error"] == "", got["error"]
    return [str(x) for x in got["cells"]]


def _render_problems(cells: list[str]) -> list[str]:
    """④ 的判据本体（纯函数：给负控喂人造输出用）。

    三件事，缺一件就能被"看起来对"的形状蒙过去：
    - 第一行印出 4321；
    - 第二行印出 9999 —— 两行不同值才证得明"印的是这一行的 pid"（固定字面量、
      或误印成别的字段，都会在两行上给出同一个值）；
    - 三行没有 pid 的都落在三态词里（`unknown` / `—`）；`undefined` / 空串都不算。
    """
    problems: list[str] = []
    if len(cells) != len(PID_ROWS):
        return [f"那一列只跑出 {len(cells)} 格（应当 {len(PID_ROWS)} 格）"]
    if cells[0] != "4321":
        problems.append(f"pid=4321 那一格渲染成 {cells[0]!r} ⇒ 这一列没有印这一行的 pid")
    if cells[1] != "9999":
        problems.append(
            f"pid=9999 那一格渲染成 {cells[1]!r} ⇒ 这一列印的不是这一行的 pid"
            "（两行不同的 pid 必须印出两个不同的号；固定字面量在这里必红）")
    for row, got in zip(PID_ROWS[2:], cells[2:], strict=True):
        if got not in MISSING_WORDS:
            problems.append(
                f"{row} 那一格渲染成 {got!r} ⇒ 缺 pid 时没有走三态"
                f"（只接受 {' / '.join(MISSING_WORDS)}，不接受字面量 undefined）")
    return problems


# ====================================================================== ① ② 列名与说明
def test_the_process_table_names_the_host_process_pid_and_says_so() -> None:
    """判据 ① + ②：列名逐字是 `宿主进程 pid`，且有一句"共用"的说明。"""
    source = _live_source()
    problems = _pid_label_problems(source)
    assert problems == [], "\n".join(problems)
    # 那一列真的还在（不是"把整列删了、顺手把表头也删了"混过去）。
    assert 'key: "pid"' in source, "进程面少了 pid 那一格（判断要不要叫停要看它）"


# ====================================================================== ③ 反真空（文案）
def test_negative_control_the_old_title_and_a_missing_note_are_both_reported() -> None:
    """判据 ③（反真空）：把列名改回旧文案、把说明删掉 ⇒ 检查函数必须报出来。

    没有这一条，①② 可能是"读了源码、但读的那几行与 pid 无关" —— 一个永远绿的断言
    与一条被删掉的判据在输出上没有区别。
    """
    source = _live_source()
    assert _pid_label_problems(source) == [], "前提：真源码本身是绿的"

    old_title = source.replace(f'title: "{PID_TITLE}"', 'title: "pid"')
    assert old_title != source
    problems = _pid_label_problems(old_title)
    assert problems, "把表头改回 `pid` 之后判据没响"
    assert any("宿主进程 pid" in p for p in problems), problems

    no_note = "\n".join(ln for ln in source.splitlines()
                        if not ("宿主进程" in ln and "共用" in ln))
    problems = _pid_label_problems(no_note)
    assert problems, "把说明删掉之后判据没响"
    assert any("说明" in p for p in problems), problems


# ====================================================================== ④ 真跑那一列
def test_the_pid_column_prints_this_rows_pid_and_unknown_when_it_is_missing(
        tmp_path: pathlib.Path) -> None:
    """判据 ④：那一格真印出这一行的 pid；缺 pid 时走三态（`unknown` / `—`）。

    这一条取代了原先的 `if "String(r.pid)" not in source`（见模块头 2026-11-01 那节）：
    源码里有某段文本证明不了"这一格印的是这一行的号"，而它会把
    `String(…)` → `cell(…)` 这种有值时输出逐字不变的修法判成回归。
    """
    cells = _render_pid_cells(_live_source(), tmp_path)
    problems = _render_problems(cells)
    assert problems == [], "\n".join(problems)
    # 正控（读数是给人看的）：两行不同 pid 真的印出两个不同的号。
    assert cells[0] == "4321" and cells[1] == "9999", cells


# ====================================================================== ⑤ 反真空（渲染）
def test_negative_control_a_fixed_literal_and_the_old_string_pid_are_both_reported(
        tmp_path: pathlib.Path) -> None:
    """判据 ⑤（反真空）：渲染坏了，④ 那个检查必须报出来。

    两种坏法分别对应旧判据想守的两件事：
    - 固定字面量：两行印出同一个值 ⇒ "印的不是这一行的 pid"；
    - 改回 `String(r.pid)`：有值档仍对，但缺 pid 档变字面量 `undefined` ⇒ "没走三态"。
    这证明 ④ 不是恒绿的，也证明"改回旧写法"这条负控仍然会响（它是收紧：
    原先只要求源码里有那段文本，现在还要求缺值档必须落到三态词上）。
    """
    source = _live_source()
    column = _column_body(source)
    expr = _render_expr(column)
    assert expr, "`Live.tsx` 的 pid 列没有 render（判据自己过期了）"
    assert "cell(r.pid)" in source, "`Live.tsx` 的 pid 列不再走 `cell(r.pid)`（判据自己过期了）"

    fixed = source.replace(expr, '(r) => <span class="mono">{"固定值"}</span>')
    assert fixed != source
    problems = _render_problems(_render_pid_cells(fixed, tmp_path / "fixed"))
    assert problems, "把那一格换成固定字面量之后判据没响"
    assert any("这一行的 pid" in p for p in problems), problems

    old = source.replace("cell(r.pid)", "String(r.pid)")
    assert old != source
    problems = _render_problems(_render_pid_cells(old, tmp_path / "old"))
    assert problems, "把那一格改回 `String(r.pid)` 之后判据没响（缺值档变 undefined）"
    assert any("undefined" in p for p in problems), problems


# ====================================================================== ⑥ 后端互证
def test_the_live_reading_gives_one_pid_to_every_row_of_the_same_process(
        tmp_path: pathlib.Path) -> None:
    """判据 ⑥（为什么这一列必须叫"宿主进程"）：同一进程的两个角色，pid 逐字相同。

    `tasks` 表没有 pid 列（这条也在下面钉住）：那一格只能来自进程登记，
    而登记写的是"登记它的那个宿主进程"。
    """
    assert "pid" not in {f.name for f in dataclasses.fields(S.Task)}, (
        "tasks 表居然有 pid 列了 ⇒ 这一条的前提变了，重新想这一列该叫什么")

    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    # 同一个宿主进程（这个测试进程）登记两个角色 —— 这就是 `run-agent` 一趟里的形态。
    SC.register_pid(root, "M", "s1", pid=os.getpid())
    SC.register_pid(root, "D", "s1", pid=os.getpid())

    face = R.live_face(root)
    live = face["live"]
    assert len(live) == 2, live
    assert [r["role"] for r in live] == ["D", "M"], live
    pids = {r["pid"] for r in live}
    assert pids == {os.getpid()}, pids
    assert face["answer"] == "有", face
