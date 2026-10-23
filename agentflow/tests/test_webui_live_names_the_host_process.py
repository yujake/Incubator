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
| ④ 后端互证 | 同一进程登记两个角色 ⇒ `live_face` 两行的 pid 逐字相等（所以"每行 pid"没有分辨力） |

④是"这条判据为什么成立"的证据，①②③是"页面照做了"的证据：缺 ④ 的话，
文案可以随便写；缺 ①–③ 的话，后端读数对而页面照旧印"pid"。

## 改前红在哪

①的列名是 `pid`（判据里那条"逐字等于 `宿主进程 pid`"直接红），②的说明整句不存在。
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

from agentflow import schema as S
from agentflow import stopctl as SC
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE_TSX = REPO / "ui" / "src" / "pages" / "Live.tsx"

#: 那一列的表头（改前是 `pid`）。
PID_TITLE = "宿主进程 pid"


def _pid_label_problems(source: str) -> list[str]:
    """进程面那一列"叫什么、说明白了没有"（纯函数：给负控喂人造源码用）。

    只看 `Live.tsx` 里那几个关于 pid 的字符串，不做全文匹配：
    `running` 那张表也印 `sid`，全文匹配会让"表头改了、说明没改"照样绿。
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
    if "String(r.pid)" not in source:
        problems.append("这一列不再渲染 `r.pid` ⇒ 说明与实现分家了")
    return problems


def _live_source() -> str:
    return LIVE_TSX.read_text(encoding="utf-8")


# ====================================================================== ① ② 列名与说明
def test_the_process_table_names_the_host_process_pid_and_says_so() -> None:
    """判据 ① + ②：列名逐字是 `宿主进程 pid`，且有一句"共用"的说明。"""
    source = _live_source()
    problems = _pid_label_problems(source)
    assert problems == [], "\n".join(problems)
    # 那一列真的还在（不是"把整列删了、顺手把表头也删了"混过去）。
    assert 'key: "pid"' in source, "进程面少了 pid 那一格（判断要不要叫停要看它）"


# ====================================================================== ③ 反真空
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


# ====================================================================== ④ 后端互证
def test_the_live_reading_gives_one_pid_to_every_row_of_the_same_process(
        tmp_path: pathlib.Path) -> None:
    """判据 ④（为什么这一列必须叫"宿主进程"）：同一进程的两个角色，pid 逐字相同。

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
