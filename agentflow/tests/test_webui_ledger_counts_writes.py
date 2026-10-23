# -*- coding: utf-8 -*-
"""判据（D21）：「台账事件 N 条」数的不是 `events.jsonl` 的总行数。

## 改前是什么样

`webui/state.py::_read_ledger` 的 `events` 是 `len(store.read_events())` ——
`data/events.jsonl` 的总行数。而那份日志的写入口（`Store._append_events`）
每提交一次事务写 `rows + 1` 行：N 行事件，末尾再补一行 `op="commit"` 的标记。

于是"台账事件 12 条"与旁边那格"会话 5 段"并排读起来像同一个口径的两个数，
实际一个是"写入笔数的两倍（减一次）"，一个是"文件段数"。用户问"写了多少笔"
时，这个数会翻倍地回答，而页面上没有任何字提示这件事。

## 这一份守什么

| 判据 | 落点 |
|---|---|
| ① 拆分 | 一次写入 = 2 行 ⇒ `upserts == events == 2`、`commit_markers == 2` |
| ② 守恒 | `upserts + commit_markers == events.jsonl 的总行数`（任何一行都不许被悄悄丢掉） |
| ③ 口径有字 | `events_note` 必须写出"commit 标记"这件事（数字旁边不写，读的人照样会混） |
| ④ 反真空 | 把读数换回改前那份（`events` = 总行数、没有 `upserts`）⇒ 检查函数必须红 |

③不是形式主义：这一批改的正是"同一个数字两种口径并排放"，而口径的唯一载体
就是那一行字（`Home.tsx` 的文案与它同源）。
"""

from __future__ import annotations

import json
import pathlib

from agentflow import schema as S
from agentflow import webui as W
from agentflow.store import Store

TS = "2026-10-22T00:00:00+08:00"
#: 这一份夹具做几次写入（每次写入 = 一行事件 + 一行 commit 标记）。
WRITES = 2


def _write_n_times(st: Store, n: int) -> None:
    """走真写路径做 n 次写入（一次 `tx` = 一次提交 = 一批事件 + 一行提交标记）。

    行形状用 `Dependency`（`status="closed"` 必须指向一个来源 ⇒ 给一条命题号），
    这样"这次写入真的合法"不是靠骗过校验器得到的。
    """
    for i in range(n):
        row = S.Dependency(dep_id=S.format_id(i), used_by="stmt:000001", kind="theorem",
                           label="stmt:000002", status="closed", status_reason="",
                           source_stmt_id="000002", source_experiment_id=None,
                           source_lit_id=None, path_group=1, created_at=TS)
        row.validate()
        with st.tx("dependencies", actor="test") as tx:
            tx.upsert("dependencies", row.to_dict(), note="d21")


def _raw_lines(root: pathlib.Path) -> int:
    """`data/events.jsonl` 的总行数（空行不算 —— 它不是一行事件）。"""
    text = (root / "data" / "events.jsonl").read_text(encoding="utf-8")
    return len([ln for ln in text.splitlines() if ln.strip()])


def _ledger_problems(ledger: dict, raw_lines: int) -> list[str]:
    """台账那几格的自洽性（纯函数：负控喂改前那份读数用）。"""
    problems: list[str] = []
    upserts = ledger.get("upserts")
    markers = ledger.get("commit_markers")
    if upserts is None:
        problems.append("台账读数里没有 `upserts`（写入笔数）这一格")
    if markers is None:
        problems.append("台账读数里没有 `commit_markers` 这一格")
    if ledger.get("events") != upserts:
        problems.append(f"`events` 与 `upserts` 不是同一个口径：events={ledger.get('events')!r} / "
                        f"upserts={upserts!r}")
    if markers is not None and markers <= 0:
        problems.append(f"`commit_markers` 不该是 {markers!r}：每提交一次都会写一行")
    if upserts is not None and markers is not None and upserts + markers != raw_lines:
        problems.append(f"守恒不成立：upserts({upserts}) + commit_markers({markers}) "
                        f"!= events.jsonl 总行数({raw_lines})")
    if ledger.get("events") == raw_lines:
        problems.append(f"`events` 仍然等于总行数 {raw_lines}（改前那个口径：把 commit 标记"
                        "也数进去，于是同一个数翻倍地回答）")
    note = str(ledger.get("events_note") or "")
    if "commit" not in note:
        problems.append(f"`events_note` 没有写出 commit 标记这件事：{note!r}")
    return problems


# ====================================================================== ① ② ③
def test_the_ledger_reading_counts_writes_not_lines(tmp_path: pathlib.Path) -> None:
    """判据 ①②③：2 次写入 ⇒ 2 笔 + 2 行 commit 标记（总 4 行）。"""
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    _write_n_times(st, WRITES)

    raw = _raw_lines(root)
    assert raw == WRITES * 2, f"前提：{WRITES} 次写入应当落 {WRITES * 2} 行，实际 {raw} 行"

    ledger = W.snapshot(root)["ledger"]
    problems = _ledger_problems(ledger, raw)
    assert problems == [], "\n".join(problems)
    assert ledger["upserts"] == WRITES, ledger
    assert ledger["commit_markers"] == WRITES, ledger
    assert ledger["events"] == WRITES, ledger
    # 台账那一栏的另一个读数（tasks 行数）不受这一批影响。
    assert ledger["tables"] == 0, ledger


# ====================================================================== ④ 反真空
def test_negative_control_the_old_total_line_reading_is_reported(
        tmp_path: pathlib.Path) -> None:
    """判据 ④：把读数换回改前那份（`events` = 总行数、没有拆分）⇒ 必须红。

    改前红就是这一条：`_read_ledger` 那时返回的正是 `{"events": 4, "tables": ...}`
    （4 = 两笔写入的 4 行），今天的判据在它上面报 3 条。
    """
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    _write_n_times(st, WRITES)
    raw = _raw_lines(root)

    old_style = {"path": str(root / "data" / "events.jsonl"), "events": raw,
                 "tables": 0, "note": "", "tables_note": "含顶趟行；为 tasks 全量行数，非子任务条数"}
    problems = _ledger_problems(old_style, raw)
    assert problems, "改前那份读数居然通过了"
    assert any("upserts" in p for p in problems), problems
    assert any("仍然等于总行数" in p for p in problems), problems

    # 另一条负控：拆开了、但 `events` 忘了跟着改（两处口径并存的形态）。
    half = {"path": old_style["path"], "events": raw, "upserts": WRITES,
            "commit_markers": WRITES, "tables": 0, "note": "",
            "tables_note": "", "events_note": "每次写入占一行事件 + 一行 commit 标记"}
    problems = _ledger_problems(half, raw)
    assert problems and any("不是同一个口径" in p for p in problems), problems


def test_the_note_and_the_split_agree_with_what_is_really_on_disk(tmp_path: pathlib.Path) -> None:
    """判据 ②（守恒的另一半）：盘上那一行真是 `op=commit`，不是靠行数猜出来的。"""
    root = tmp_path / "ws"
    root.mkdir()
    st = Store(root)
    st.init()
    _write_n_times(st, WRITES)

    rows = [json.loads(ln) for ln in
            (root / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if ln.strip()]
    commits = [r for r in rows if str(r.get("op") or "") == "commit"]
    assert len(commits) == WRITES, rows
    assert all(int(r.get("rows") or 0) == 1 for r in commits), commits
    ledger = W.snapshot(root)["ledger"]
    assert ledger["commit_markers"] == len(commits)


#: 显示这一格台账读数的页面（`Home` 的「台账」卡与「一趟详情」的同名牌）。
LEDGER_PAGES = ("Home.tsx", "Run.tsx")


def test_every_page_that_shows_the_ledger_says_the_same_thing() -> None:
    """判据 ③（跨页）：两处显示同一个读数，就都得写出 commit 标记这件事。

    只改 `Home.tsx` 的话，「一趟详情」页会继续把"写入笔数"印成"事件 N 条" ——
    同一份读数在两个页面上两种说法，正是这一批要消掉的那种混读。
    """
    ui = pathlib.Path(__file__).resolve().parents[1] / "ui" / "src" / "pages"
    for name in LEDGER_PAGES:
        source = (ui / name).read_text(encoding="utf-8")
        problems = _page_problems(source)
        assert problems == [], f"{name}：" + "；".join(problems)


def _page_problems(source: str) -> list[str]:
    """一页里那三样（纯函数：给负控喂人造源码用）。"""
    problems: list[str] = []
    for token in ("upserts", "commit_markers", "commit 标记"):
        if token not in source:
            problems.append(f"页面上没有 `{token}`（口径没写到数字旁边）")
    if "台账事件" in source:
        problems.append("页面上还写着「台账事件 N 条」（那是改前那个数总行数的口径）")
    return problems


def test_negative_control_a_page_stuck_on_the_old_wording_is_reported() -> None:
    """判据 ③ 的反真空：把一页换回改前的写法 ⇒ 检查函数必须红。"""
    old = """
    <Card title="台账">
      <div class="readings">
        台账事件 <span class="mono">{snapshot.ledger.events === null ? "unknown" : snapshot.ledger.events}</span> 条 ·
        tasks 行数 <span class="mono">{snapshot.ledger.tables}</span> · 落点 {snapshot.ledger.path}
      </div>
      <div class="readings">{snapshot.ledger.tables_note}</div>
    </Card>
    """
    problems = _page_problems(old)
    assert problems, "改前那一段源码居然通过了"
    assert any("upserts" in p for p in problems), problems
    assert any("台账事件" in p for p in problems), problems

