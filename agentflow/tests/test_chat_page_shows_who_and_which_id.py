"""判据：对话页必须把"谁在说话、哪个绝对编号"真的印出来（业主 2026-10-21「全面接入」第二步）。

## 这一组钉五件事

1. 文本级（防"后端给了、前端没接"）：`ui/src/pages/Home.tsx` 真的读了 `task_id` /
   `task_id_source` / `role` / `role_source`，并且把它们交给了渲染用的那两个函数
   （`idCell` / `roleCell`）—— 读了却只拿去算一个没人用的变量，与没读一样都看不见；
2. 三态显示：`missing` 那一支必须出现「（未记录编号）」（不许留空、不许编一个）；
   `inherited` 与 `event` 两支的渲染必须不同（`inherited` 带「（承自本趟起跑）」括注，
   `event` 不带 —— 两支在源码里是两个各自独立的 `return`）；
3. 读侧 role：`agent_message` 只记 `from`（谁发的）、不记 `role` ⇒ `readers._chat_line`
   用 `from` 填 `role`，并把 `role_source` 标成 `from`；
4. 负控：`agent_message` 连 `from` 都没有 ⇒ `role` 是空串、`role_source` 是
   `missing`（不许猜一个角色，也不许把"没记"写成空串蒙过去）；
5. 契约：`ChatLine` 的声明与 `ui/src/types.ts` 同步 —— 生成物逐字节等于
   `emit_types.render_types()`，且 `role_source` 在声明与生成物两边都在。

改前红（本轮实测，逐条见回报）：第 1、2 条在页面还没印编号时红；第 3、4 条在
`_chat_line` 还没读 `from` 时红（第 4 条是 `KeyError: 'role_source'`）；第 5 条在
声明加了键而 `types.ts` 没重新生成时红。

为什么这几条要一起存在：后端的 `ChatLine` 早就给全了（`task_id` / `task_id_source`），
而页面只印 `who` / `title` / `ts` / `text`。那种缺口没有任何一条既存判据看得见 ——
后端全绿、契约全绿、用户还是看不到"哪个编号的哪个角色在说话"。
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Sequence

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow.webui import readers  # noqa: E402

#: 交付包根（`agentflow/`）。
REPO = SRC.parent

#: 对话页源码。
HOME_TSX = REPO / "ui" / "src" / "pages" / "Home.tsx"

#: 生成物（唯一类型来源）。
TYPES_TS = REPO / "ui" / "src" / "types.ts"

#: 编号没记时页面必须写的字样（"不许留空"的落地形态）。
MISSING_ID_WORD = "（未记录编号）"

#: 编号是回填来的时候页面必须加的那个记号（与 `event` 那一档的差别就落在这里）。
INHERITED_WORD = "（承自本趟起跑）"


# ====================================================================== 读源码
#: 块注释与整行注释（判据不许被注释里的字段名蒙过去）。
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _home_source() -> str:
    """`Home.tsx` 的源码（剥掉注释：注释里出现 `task_id` 不算"页面读了它"）。"""
    assert HOME_TSX.is_file(), f"对话页不在盘上：{HOME_TSX}"
    text = HOME_TSX.read_text(encoding="utf-8")
    return _LINE_COMMENT.sub("", _COMMENT.sub("", text))


def _function_lines(lines: Sequence[str], name: str) -> list[str]:
    """某个 `function <name>(...)` 的整段源码（到顶格的那个 `}` 为止）。

    为什么按"函数"而不是按"整个文件"取：三态那几支必须落在同一个渲染函数里才算
    "同一个格子分了三档"；拿整个文件比，`event` 出现在别处也能让断言通过。
    """
    head = next((i for i, line in enumerate(lines)
                 if line.strip().startswith(f"function {name}(")), None)
    assert head is not None, f"Home.tsx 里没有 function {name}（判据没有落脚点）"
    out: list[str] = [lines[head]]
    for line in lines[head + 1:]:
        out.append(line)
        if line == "}":
            break
    return out


def _branch_lines(lines: Sequence[str], value: str) -> list[str]:
    """`source === "<value>"` 那一条分支的源码（含条件行与它自己的收尾 `}`）。"""
    head = next((i for i, line in enumerate(lines)
                 if "source ===" in line and f'"{value}"' in line), None)
    assert head is not None, f"没有 source === \"{value}\" 这一支（三档没画出来）"
    out: list[str] = [lines[head]]
    for line in lines[head + 1:]:
        out.append(line)
        if line.strip() == "}":
            break
    return out


def _tail_lines(lines: Sequence[str]) -> list[str]:
    """最后一个 `source === ...` 分支收尾之后剩下的那几行 = `missing` 那一档的落点。"""
    last = max((i for i, line in enumerate(lines) if "source ===" in line), default=-1)
    assert last >= 0, "这个函数里没有任何 source === 分支（三态没有落点）"
    out: list[str] = []
    closed = False
    for line in lines[last:]:
        if closed:
            out.append(line)
        elif line.strip() == "}":
            closed = True
    return out


def _watch_keys(text: str) -> set[str]:
    """源码里出现过的字段名（`x.key` / `x?.key` 两档都算）。"""
    return {m.group(1) for m in re.finditer(r"[.?]\s*([A-Za-z_][A-Za-z0-9_]*)", text)}


# ====================================================================== 1 文本级
def test_the_chat_page_really_reads_the_id_and_its_source() -> None:
    """判据 1：页面读了 `task_id` / `task_id_source`（以及角色的来源 `role_source`）。

    这一条问的是"后端给了、前端接没接"：`ChatLine` 那两个键从 2026-10-21 起就在
    `/api/chat` 的每一条线上，而 `Line` 组件只印 `who` / `title` / `ts` / `text`。
    只断言"读了"还不够 —— 读了却没有人用它渲染，屏幕上照样什么都没有，所以下一半
    断言的是 `idCell` / `roleCell` 真的被 `Line` 以那一格为参数调用了。
    """
    text = _home_source()
    reads = _watch_keys(text)
    for key in ("task_id", "task_id_source", "role", "role_source"):
        assert key in reads, f"Home.tsx 没有读 {key}（后端给了、页面没接）"
    assert re.search(r"idCell\(\s*l\.task_id\s*,\s*l\.task_id_source\s*\)", text), \
        "task_id / task_id_source 读了却没交给 idCell（读了不印 = 看不见）"
    assert re.search(r"roleCell\(\s*l\.role\s*,\s*l\.role_source\s*\)", text), \
        "role / role_source 读了却没交给 roleCell（读了不印 = 看不见）"


# ====================================================================== 2 三态显示
def test_a_missing_id_is_written_out_instead_of_left_blank() -> None:
    """判据 2-a：`missing` 那一支必须写「（未记录编号）」，不许留空。

    留空在页面上读起来像"这个代理没有编号"，而盘上的事实是"这条事件没记" ——
    两种不同的三态被折成同一个空字符串，正是这一格最贵的那种错。
    """
    body = _function_lines(_home_source().splitlines(), "idCell")
    tail = "\n".join(_tail_lines(body))
    assert MISSING_ID_WORD in tail, (
        f"missing 那一支没有写出「{MISSING_ID_WORD}」：{tail.strip()}")


def test_an_inherited_id_renders_differently_from_an_event_id() -> None:
    """判据 2-b：`inherited` 与 `event` 的渲染必须不同（两支各自独立）。

    两边都要判：`inherited` 那一支必须带上「（承自本趟起跑）」这个记号（读的人有权
    知道这一格的来路不是这条事件自己记的），而 `event` 那一支不许带 —— 后者带了记号
    等于把"事件里真有"也说成"回填的"，前者不带则两档在屏幕上长得一样。
    """
    body = _function_lines(_home_source().splitlines(), "idCell")
    event = "\n".join(_branch_lines(body, "event"))
    inherited = "\n".join(_branch_lines(body, "inherited"))
    assert event != inherited, "event 与 inherited 两支的源码一模一样（三档没有分档）"
    assert INHERITED_WORD in inherited, (
        f"inherited 那一支没有「{INHERITED_WORD}」这个记号：{inherited.strip()}")
    assert INHERITED_WORD not in event, (
        f"event 那一支也带了「{INHERITED_WORD}」⇒ 两档在屏幕上分不开：{event.strip()}")


def test_the_role_cell_also_says_where_it_came_from() -> None:
    """判据 2-c：角色那一格的三档同样分得开（`from` 与 `missing`）。

    `agent_message` 的 role 是读侧从 `from` 补的（判据 3），于是它必须能与"事件自带
    角色"那一档分开看；缺角色时同样不许留空。
    """
    body = _function_lines(_home_source().splitlines(), "roleCell")
    from_branch = "\n".join(_branch_lines(body, "from"))
    event_branch = "\n".join(_branch_lines(body, "event"))
    tail = "\n".join(_tail_lines(body))
    assert "（承自发件人）" in from_branch, f"from 那一支没有出处记号：{from_branch.strip()}"
    assert "（承自发件人）" not in event_branch, (
        f"event 那一支也带了出处记号 ⇒ 两档分不开：{event_branch.strip()}")
    assert "（未记录角色）" in tail, f"缺角色时没有写出「（未记录角色）」：{tail.strip()}"


# ====================================================================== 3 读侧 role
def test_an_agent_message_takes_its_role_from_the_sender() -> None:
    """判据 3：`agent_message` 的 `role` 由 `from` 补齐，且 `role_source == "from"`。

    改前那一格是空串（真机读数里 `E → D（private）` 那条线"哪个角色"是空的）：那种
    记录里只有 `from`，而 `from` 就是发信人的角色。读侧补它是可复核的，前端拿标题
    `E → D` 去解析则不是（标题是给人看的一句话，不是数据）。
    """
    line = readers._chat_line(0, {"kind": "agent_message", "msg_id": "m0001",
                                  "from": "E", "to": "D", "channel": "private",
                                  "body": "私信", "from_task_id": "t-000003"})
    assert line is not None, "agent_message 应该进对话"
    assert line["role"] == "E", line
    assert line["role_source"] == "from", line
    # 另一半（正控）：事件自带 role 的那一类，来源必须仍是 event。
    start = readers._chat_line(0, {"kind": "agent_run_start", "role": "M",
                                   "task": "干活", "task_id": "t-000001"})
    assert start is not None
    assert start["role"] == "M" and start["role_source"] == "event", start


def test_an_agent_message_without_a_sender_does_not_guess_a_role() -> None:
    """判据 4（负控）：`agent_message` 没有 `from` ⇒ 角色与来源都不许猜。

    两格都要判：`role` 空串单独看没有意义（"没记"与"记了个空"长得一样），所以
    "这一格到底有没有角色"由 `role_source` 说话；反过来把 `missing` 写成空串混过去
    （两格都留空）必须红。
    """
    line = readers._chat_line(0, {"kind": "agent_message", "msg_id": "m0002",
                                  "to": "D", "channel": "private", "body": "?"})
    assert line is not None
    assert line["role"] == "", line
    assert line["role_source"] == "missing", line


# ====================================================================== 5 契约
def _chat_line_fields(gen_text: str) -> list[str]:
    """生成物里 `ChatLine` 那个接口的字段名（`name?:` 去掉问号）。"""
    m = re.search(r"export interface ChatLine \{(.*?)\n\}", gen_text, re.S)
    assert m is not None, "types.ts 里没有 ChatLine 接口"
    return [f.group(1) for f in re.finditer(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*)\??\s*:",
                                            m.group(1), re.M)]


def test_the_chat_line_declaration_and_the_generated_types_agree() -> None:
    """判据 5：声明（`readers._TS_TYPES`）与生成物（`types.ts`）逐字节同步。

    这是 `tests/test_webui_contracts.py` 那两条（C 类型对齐 + M2 新鲜度）在本接口上的
    同一件事：加了一格字段却不重生成，前端拿到的类型就少一格，`tsc` 只会以为那是一个
    可选字段 —— 一声不吭。这里先把"生成物是不是最新的"钉住，再钉字段本身在两边都在。
    """
    from agentflow.web import emit_types

    fresh = emit_types.render_types()
    on_disk = TYPES_TS.read_text(encoding="utf-8")
    assert fresh == on_disk, (
        "ui/src/types.ts 不是最新的生成物：跑 `python -B -m agentflow.web.emit_types`")
    fields = _chat_line_fields(fresh)
    assert "role_source" in fields, f"生成物里的 ChatLine 没有 role_source：{fields}"
    decl = next(fields for name, _why, fields in readers._TS_TYPES if name == "ChatLine")
    declared = [name.rstrip("?") for name, _t in decl]
    assert "role_source" in declared, f"readers 的 ChatLine 声明没有 role_source：{declared}"
    assert sorted(fields) == sorted(declared), (
        "声明与生成物的键集合不一致", sorted(fields), sorted(declared))
