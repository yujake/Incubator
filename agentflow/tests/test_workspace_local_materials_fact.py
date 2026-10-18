# -*- coding: utf-8 -*-
"""工作区里"未收编的本地材料"要**进模型看得见的地方**（业主 2026-10-16 的 T5 口径）。

## 为什么补这个文件

业主口径（逐字）：**"直接建工作区，把你亲自下好的几篇文献丢在工作区，然后在此工作区下启动系统，
看看一上来 M 会不会注意到它们并提醒 A 将这些收编入库。"**

而 `WORKSPACE_FACTS` 此前只报"根目录 / 表清单 / 提示词版本" —— **提示词里根本没有这件事**，
M 只能碰运气想起来 `fs.list source/`。这一格补上之后，事实就摆在它眼前。
与 `toolchain_facts` 是同一条既有裁定：**事实必须进模型看得见的地方**。

## 守三件事（含负控）

1. 有未收编材料 ⇒ **进提示词**（并且点名 `A.ingest_local` 与 `books_dir`）；
2. 收编之后 ⇒ **那一行消失**（负控：不许每趟都催着重收一遍）；
3. **读不到台账 ⇒ 不说话**，绝不编一个"0 份"（三态：没读成 ≠ 都收编了）。
"""

from __future__ import annotations

import pathlib
import shutil

from agentflow import agent_prompts as AP
from agentflow.store import Store
from agentflow.tools import build_registry

def _real_pdf(text: str = "probe") -> bytes:
    """造一份**有文本层**的真 PDF。

    为什么不用手写的 `%PDF-1.4` 头：`A.ingest_local` 只收"它认得的类型"（要有文本层的全文），
    所以拿假字节做夹具会把"收编没成功"误当成"事实没更新" —— 我第一版就栽在这里。
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _ws(tmp_path: pathlib.Path, *, n_files: int = 2) -> tuple[Store, pathlib.Path]:
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init()
    src = ws / "source"
    src.mkdir(parents=True, exist_ok=True)
    for i in range(n_files):
        (src / f"paper-{i}.pdf").write_bytes(_real_pdf(f"paper {i}"))
    return store, ws


def _line(role: str, ws: pathlib.Path) -> str:
    reg = build_registry(store=Store(ws), workspace_root=ws).registry
    prompt = AP.system_prompt(role, registry=reg, workspace_root=str(ws))
    for ln in prompt.splitlines():
        if "未收编的本地材料" in ln:
            return ln.strip()
    return ""


def test_unregistered_local_materials_are_visible_to_m(tmp_path: pathlib.Path) -> None:
    """正控：M 的提示词里出现"未收编的本地材料"，且点名了收编的动作与参数。"""
    _store, ws = _ws(tmp_path, n_files=2)
    line = _line("M", ws)
    assert line, "工作区里明明有两份没收编的 PDF，M 的提示词里却没有这件事"
    assert "2 份" in line, line
    assert "A.ingest_local" in line and "books_dir" in line, line


def test_one_more_file_shows_up_individually(tmp_path: pathlib.Path) -> None:
    """边界：**又丢一份进去**时要能单独看出来（不是"永远 2 份"）。"""
    _store, ws = _ws(tmp_path, n_files=1)
    (ws / "source" / "newcomer.pdf").write_bytes(_real_pdf("newcomer"))
    line = _line("M", ws)
    assert "2 份" in line and "newcomer.pdf" in line, line


def test_the_line_disappears_once_ingested(tmp_path: pathlib.Path) -> None:
    """负控：收编之后那一行**必须消失** —— 否则 M 每一趟都会重收一遍。"""
    store, ws = _ws(tmp_path, n_files=2)
    reg = build_registry(store=store, workspace_root=ws).registry
    res = reg.call("search.ingest_local", role="A", books_dir=str(ws / "source"))
    assert res.ok, res
    assert len(store.rows("literature")) == 2, store.rows("literature")
    assert _line("M", ws) == "", "收编完了却还挂着'未收编'那一行"


def test_an_unreadable_ledger_says_nothing_instead_of_zero(tmp_path: pathlib.Path) -> None:
    """负控（三态）：**读不到台账就不说话**，不编一个"0 份"。"""
    _store, ws = _ws(tmp_path, n_files=2)
    (ws / "data" / "literature.json").unlink()
    assert _line("M", ws) == "", "读不到台账却报了读数（把'没读成'写成了'都收编了'）"


def test_the_fact_reaches_more_than_one_role(tmp_path: pathlib.Path) -> None:
    """反真空：这一格是**工作区事实**（不是 M 专属）—— 至少再看一个角色也读得到。"""
    _store, ws = _ws(tmp_path, n_files=1)
    assert _line("M", ws), "M 读不到"
    assert _line("A", ws), "A 读不到（可它正是要动手收编的那个角色）"
