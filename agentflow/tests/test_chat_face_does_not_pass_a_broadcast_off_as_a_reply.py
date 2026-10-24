"""判据（D-62）：对话面不许把主控的公共频道广播当成"对用户说的话"。

## 病根（业主 2026-10-24：「看M对话public形式为什么也会直接让用户可见」）

对话页的档位此前只按"发信人是不是 M"分（`readers._chat_line` 的
`who = "conductor" if from == M else "team"`）。于是 M 的 `#public` 广播
（`agent_loop.PUBLIC`，语义是"发给树上的人"，见 `agent_loop.public_visibility` 逐条写的
可见面）与 M 对用户的私聊回答落进同一档，页面把一条广播印成"主控对你说的话"。
`channel` 只被拼进标题当装饰（`M → #public（public）`），读者从那一行看不出这条不是
说给他的。

## 分档判据（改后）

- `conductor`：只收"说给用户听"的那几条 —— 主控的私聊回答（`to` 是 `用户` / `user`）、
  `ask` 反问（`user_question`）、收工交付（`agent_run_end` 的 `final`）；
- `team`：其余全部，含主控的 `#public` 广播（收信人是全树，不是用户）、别的角色发给主控
  的私聊、别的角色的交付。这一档在页面上默认折起来（判据 6）。

为什么复用 `team` 而不新开一档：`team` 已经默认折叠，`CHAT_WHO` 只有三个名字；
新开第四档要同步 `CHAT_WHO` 与 `types.ts`，而"这些不是对你说的话"正是 `team` 的口径。

## 这一组钉六件事

1. a：主控的 `#public` 广播 ⇒ `who == "team"`（不在 conductor 档），且标题写出"全树"。
   改前红（改前是 conductor，标题是 `M → #public（public）`）。
2. b（负控）：主控的私聊回答（`to == 用户`）⇒ 仍是 `conductor`，别把主控的话全赶出对话。
3. c（负控）：主控的 `agent_run_end` 交付 ⇒ 仍是 `conductor`。
4. d（正控）：别的角色的 `#public` ⇒ `team`（原本就对，钉住别改坏）。
5. e（反真空）：把分档判据打桩成恒 `conductor` ⇒ 判据 a 必红；恒 `team` ⇒ 判据 b / c 必红。
   这一条不另写一套断言，而是复用 a / b / c 那三个判据函数 —— 打桩之后它们必须变成假。
6. f：`team` 那一档在页面上默认折叠（扫 `Home.tsx` 源码：开关初值 false，且 `team` 的线
   只有开关打开才进渲染列表）。广播因此不会顶到用户眼皮下。

改前红的实测读数（本轮）：判据 1 与判据 5 红（`who` 是 conductor、标题不含"全树"；
打桩函数在改前还不存在 ⇒ `AttributeError`）；判据 2 / 3 / 4 / 6 改前即绿，它们是负控与
正控，钉的是"这次修法别把对的东西改坏"。
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import Any

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import agent_loop as AL  # noqa: E402
from agentflow.webui import readers  # noqa: E402

#: 交付包根（`agentflow/`）。
REPO = SRC.parent

#: 对话页源码（判据 6 扫它）。
HOME_TSX = REPO / "ui" / "src" / "pages" / "Home.tsx"

#: 广播那一行标题必须写出的字（读的人据此知道这条是发给全树的）。
BROADCAST_TITLE_WORDS = ("广播", "全树", "public")


# ====================================================================== 夹具
def _broadcast(sender: str = "M") -> dict[str, Any]:
    """一条公共频道广播（`to` / `channel` 两个字段与 `send_message` 的落库形态一致）。"""
    return {"kind": "agent_message", "msg_id": "m000001", "from": sender,
            "to": AL.PUBLIC, "channel": "public",
            "body": "派活：研究方向一……（全树可见）"}


def _private_answer() -> dict[str, Any]:
    """主控对用户的私聊回答（`to` 是 `userio.USER`，`channel` 是 private）。"""
    return {"kind": "agent_message", "msg_id": "m000002", "from": "M", "to": "用户",
            "channel": "private", "body": "这一条才是说给你听的回答"}


def _delivery() -> dict[str, Any]:
    """主控这一趟的收工交付（`agent_run_end.final`，没有 `to` / `channel`）。"""
    return {"kind": "agent_run_end", "role": "M", "final": "这一趟的交付",
            "task_id": "t-000003"}


def _line(event: dict[str, Any]) -> dict[str, Any]:
    """一条事件 → 一条对话线（这条事件必须进对话，否则判据没有落脚点）。"""
    line = readers._chat_line(0, event)
    assert line is not None, f"这条事件应当进对话：{event}"
    return line


# ====================================================================== 判据本体
#: 这三条是 a / b / c 的判据本体，单独写出来是为了让判据 5（反真空）复用同一套断言 ——
#: 打桩之后它们必须变成假，否则那三条判据只是"看起来绿"。
def _a_holds() -> bool:
    return _line(_broadcast())["who"] == "team"


def _b_holds() -> bool:
    return _line(_private_answer())["who"] == "conductor"


def _c_holds() -> bool:
    return _line(_delivery())["who"] == "conductor"


# ====================================================================== 1 分档
def test_a_broadcast_from_the_conductor_is_not_a_line_to_the_user() -> None:
    """判据 1：主控的 `#public` 广播进 `team`，不进 `conductor`，且标题写出"全树"。

    改前那一版只按"发信人是不是 M"分档，于是这条广播落在 `conductor`，标题是
    `M → #public（public）` —— 两处都在对读者撒谎：档位说"这是主控对你说的话"，
    标题说"发给 #public"，而 #public 的语义是全树广播。
    """
    line = _line(_broadcast())
    assert line["who"] == "team", (
        f"主控的公共频道广播被当成对用户说的话：who={line['who']!r}，title={line['title']!r}")
    assert line["who"] != "conductor", "广播进了主控档（对话面会把它印在用户眼皮下）"
    for word in BROADCAST_TITLE_WORDS:
        assert word in line["title"], (
            f"广播标题没说清去向：缺「{word}」⇒ {line['title']!r}")


def test_the_conductor_still_answers_the_user_privately() -> None:
    """判据 2（负控）：主控的私聊回答（`to == 用户`）仍是 `conductor`。

    这一条守的是"别把主控的话全赶出对话"：把公共频道广播挪走之后，主控对用户说的话
    必须还在 `conductor` 那一档，否则对话页就只剩用户的独白。
    """
    line = _line(_private_answer())
    assert line["who"] == "conductor", (
        f"主控对用户的私聊回答没进主控档：who={line['who']!r}，title={line['title']!r}")


def test_the_conductor_delivery_is_still_a_conductor_line() -> None:
    """判据 3（负控）：主控 `agent_run_end` 的交付仍是 `conductor`。

    收工交付（`final`）是主控这一趟"交给用户的那段话"，判据按 `role` 取，不看有没有
    `to` —— 这一档不许因为这次修法被顺手挪走。
    """
    line = _line(_delivery())
    assert line["who"] == "conductor", (
        f"主控的交付没进主控档：who={line['who']!r}，title={line['title']!r}")


def test_another_roles_broadcast_is_still_team() -> None:
    """判据 4（正控）：别的角色的 `#public` 仍是 `team`（原本就对，钉住别改坏）。

    顺带钉住标题：别的角色的广播同样要写"全树"，不许回到 `D → #public（public）`。
    """
    line = _line(_broadcast("D"))
    assert line["who"] == "team", (
        f"别的角色的广播档位变了：who={line['who']!r}，title={line['title']!r}")
    for word in BROADCAST_TITLE_WORDS:
        assert word in line["title"], (
            f"别的角色的广播标题没说清去向：缺「{word}」⇒ {line['title']!r}")


# ====================================================================== 5 反真空
def test_a_vacuous_who_would_make_these_criteria_red(monkeypatch: Any) -> None:
    """判据 5：把分档判据打桩成常数 ⇒ a / b / c 必须红。

    "恒 conductor" 复现的正是改前那个病根（广播与回答同档）：a 必须变成假。
    "恒 team" 是另一种真空（把所有话都折进团队档）：b / c 必须变成假。
    两个方向都钉，才说明那三条判据真的在判"这一条属于哪一档"，而不是恒真。
    """
    monkeypatch.setattr(readers, "_chat_message_who",
                        lambda event, conductor: ("conductor", "打桩：恒主控"))
    monkeypatch.setattr(readers, "_chat_delivery_who",
                        lambda role, conductor: ("conductor", "打桩：恒主控"))
    assert not _a_holds(), "恒 conductor 时判据 a 还是绿的 ⇒ a 不是反真空的"

    monkeypatch.setattr(readers, "_chat_message_who",
                        lambda event, conductor: ("team", "打桩：恒团队"))
    monkeypatch.setattr(readers, "_chat_delivery_who",
                        lambda role, conductor: ("team", "打桩：恒团队"))
    assert not _b_holds(), "恒 team 时判据 b 还是绿的 ⇒ b 不是反真空的"
    assert not _c_holds(), "恒 team 时判据 c 还是绿的 ⇒ c 不是反真空的"


# ====================================================================== 6 前端
#: 块注释与整行注释（判据不许被注释里的 `team` 蒙过去）。
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)


def _home_source() -> str:
    """`Home.tsx` 的源码（剥掉注释：注释里出现 `team` 不算"页面折了它"）。"""
    assert HOME_TSX.is_file(), f"对话页不在盘上：{HOME_TSX}"
    text = HOME_TSX.read_text(encoding="utf-8")
    return _LINE_COMMENT.sub("", _COMMENT.sub("", text))


def test_the_team_tier_is_folded_by_default() -> None:
    """判据 6：`team` 那一档默认折叠（广播因此不会顶到用户眼皮下）。

    三处都要在（缺一处，`team` 的线就会默认露出来）：
    1. 开关的初值是 `false`；
    2. 渲染列表在开关没开时用 `l.who !== "team"` 过滤掉这一档；
    3. 勾选框真的驱动那个开关（读的人能自己把它打开，缺了它"折起来"就成了"删掉了"）。
    """
    text = _home_source()
    assert re.search(r"const\s*\[\s*team\s*,\s*setTeam\s*\]\s*=\s*useState\(false\)", text), (
        "team 那个开关的初值不是 false ⇒ 广播默认就会露出来")
    assert re.search(r"allLines\.filter\(\s*\(l\)\s*=>\s*l\.who\s*!==\s*\"team\"\s*\)", text), (
        "渲染列表没有在开关没开时滤掉 who === \"team\" 的线")
    assert "setTeam(ev.currentTarget.checked)" in text, (
        "勾选框没有驱动 team 开关 ⇒ 折起来的那一档读的人打不开（等于删掉了）")
