# -*- coding: utf-8 -*-
"""会话记录的并发写（`draft/39` §6.7 F4）：两个写者交错 ⇒ 文件里出现非法 UTF-8 字节。

这一条是实测逼出来的（2026-10-05，E5 之后的全量套件）：`tests/test_agent_loop.py::test_a_role_can_fan_out_a_batch_in_one_step` 报UnicodeDecodeError:
'utf-8' codec can't decode byte 0xa8 in position 9472而它单跑必过、全量套件里偶尔红 —— 病因不是那条用例，是会话语料被写坏了：`LlmBackend` 在一波里并发跑同一角色的多个实例（线程），
每个实例都往同一个`sessions/<sid>.jsonl` 追加事件；没有锁时两次 `write` 会在一个中文字符的字节中间交错，于是文件里躺着一个非法字节，读会话记录整条路直接炸（而会话记录是本框架唯一的叙事审计面）。这一组钉两件事：多线程并发
`append` ⇒ 读回来一行都不坏（正控：判据真的在测并发写）；2. 同一批事件在单线程下写 ⇒ 逐字节等于并发写的结果（说明锁没有改变内容，只改变顺序）。判据不许读时钟（`R0-A2`，2026-10-06 全量门）：第 2 条原先比的是逐字 JSON，
于是它在机器忙的时候随机红：B 的全量门里`test_the_lock_does_not_change_what_gets_written` 报的是同一批事件差一秒 ——`"ts": "2026-10-06T23:58:03+08:00"` vs
`"…23:58:04+08:00"`（同一条用例三次单跑2.55 s / 64.67 s / 0.83 s，红的就是被抢的那次）。这不是"偶尔不稳"，是判据问错了问题：它要问"锁有没有改内容"，却把 `append` 盖上去的时钟戳也算进了"内容"。
现算的读数（`_CLOCK_FIELDS` 的依据，实测脚本见交付说明）：`SS.append` 给事件只盖一个键 `ts`（`sessions.py:98``row.setdefault("ts", datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))`）
——输入事件 `['index','kind','payload','result']`、读回来 `['index','kind','payload','result','ts']`；跨秒追加时两次之间唯一不同的键就是 `ts`。于是：

| 字段 | 谁写的 | 为什么不算"写进去的内容" |
|---|---|---|
| `ts` | `sessions.append` 用 `setdefault` 盖的秒级时钟戳 | 调用方一个字节都没写它（写了就沿用）；两批跨一秒必然不同，而"跨秒"与"锁"无关 |

⇒ 归一化只剔 `ts`（换成占位符），其余字段一律逐字比；`_CLOCK_FIELDS` 与"`append` 真正盖了哪些键"由 `test_the_only_field_append_stamps_is_the_clock_one` 钉住（将来
`append` 多盖一个序号字段而这里没剔 ⇒ 判据会重新开始读时钟，那条守卫先红）。顺序无关（`sorted`）是刻意的：`root_b` 那一批是线程并发写进去的，交错顺序按定义不确定 ⇒ 这条判据能问的只有"事件的多重集合相等"；
"锁保住了追加顺序"不在这条判据里。
"""
from __future__ import annotations

import json
import pathlib
import threading

from agentflow import sessions as SS

#: `sessions.append` 会盖上的字段（实测：只有这一个）。它们由时钟给，不是内容。
_CLOCK_FIELDS: tuple[str, ...] = ("ts",)
#: 归一化时替换时钟字段的占位符（两批都替换成同一个值 ⇒ 只抹掉"什么时候写的"）。
_CLOCK_PLACEHOLDER = "<clock>"


def _events(n: int) -> list[dict]:
    """一批含多字节中文的大事件（交错最容易在多字节字符中间发生）。"""
    return [{"kind": "agent_step", "index": i,
             "payload": {"note": f"第 {i} 步：这是一段中文" + "很长" * 40},
             "result": {"text": "结论：" + "证据若干" * 30}} for i in range(n)]


def test_concurrent_appends_never_tear_a_line(tmp_path: pathlib.Path):
    """负控（真并发）：8 个线程各写 20 条 ⇒ 240 行全部读得出来、没有坏行、没有非法字节。"""
    root = tmp_path / "ws"
    root.mkdir()
    batch = _events(20)
    errors: list[str] = []

    def worker() -> None:
        for ev in batch:
            _path, problem = SS.append(root, ev, sid="t")
            if problem:
                errors.append(problem)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    # 1) 字节层：整份文件必须是合法 UTF-8（这一条就是那个 UnicodeDecodeError 的反面）
    raw = SS.session_path(root, "t").read_bytes()
    text = raw.decode("utf-8")            # 坏字节会在这里炸
    # 2) 行层：每一行都是合法 JSON 且条数对得上
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 8 * len(batch), len(lines)
    events, problems = SS.read_session(root, "t")
    assert not problems, problems
    assert len(events) == 8 * len(batch), len(events)
    assert all(json.loads(ln) for ln in lines)


def _canon(events: list[dict]) -> list[str]:
    """把时钟字段换成占位符之后，做与顺序无关的逐字归一（判据只在一处：负控也调它）。

    为什么只剔时钟字段、别的一律逐字比：这条判据的全部价值在于"锁没有改内容"，
    而"内容"就是调用方写进去的那些字节 —— 剔多了（例如把 `payload` 也放过）它就不再
    能红（负控 `test_the_lock_judge_still_goes_red_when_the_content_really_differs`
    把四个方向逐个钉住）。
    """
    out: list[str] = []
    for ev in events:
        row = {k: (_CLOCK_PLACEHOLDER if k in _CLOCK_FIELDS else v) for k, v in ev.items()}
        out.append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    return sorted(out)


def test_the_lock_does_not_change_what_gets_written(tmp_path: pathlib.Path):
    """反真空：单线程顺序写的字节集合与并发写一致（锁只挡交错，不改内容）。

    比的是 `_canon(...)`（剔掉 `append` 盖的秒级 `ts`），不是逐字 JSON ——
    逐字比会让这条判据在机器忙时读时钟（事故形态与现算读数见模块 docstring）。
    """
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    batch = _events(5)
    for ev in batch:
        SS.append(root_a, ev, sid="t")
    threads = [threading.Thread(target=SS.append, args=(root_b, ev), kwargs={"sid": "t"})
               for ev in batch]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got_a, bad_a = SS.read_session(root_a, "t")
    got_b, bad_b = SS.read_session(root_b, "t")
    assert not bad_a and not bad_b, (bad_a, bad_b)
    assert _canon(got_a) == _canon(got_b)


def test_the_only_field_append_stamps_is_the_clock_one(tmp_path: pathlib.Path):
    """机制守卫（`R0-A2`）：`_CLOCK_FIELDS` 必须逐字等于 `append` 真正盖上去的键。

    为什么这条必须有：归一化是"把某些字段剔掉再比"。剔错有两个方向都坏 ——
    少剔一个（将来 `append` 多盖一个序号/时钟字段）⇒ 判据重新开始读时钟，
    flake 复活而不会有任何判据变红；多剔一个 ⇒ 判据连内容都不比了。
    所以"盖了哪些键"这件事也要有判据，读的是现算结果，不是抄一份常量。
    """
    root = tmp_path / "ws"
    root.mkdir()
    ev = _events(1)[0]
    SS.append(root, dict(ev), sid="t")
    got, bad = SS.read_session(root, "t")
    assert not bad, bad
    stamped = sorted(set(got[0]) - set(ev))
    assert stamped == sorted(_CLOCK_FIELDS), (
        f"`append` 盖上去的键是 {stamped}，而判据只剔了 {list(_CLOCK_FIELDS)} —— "
        "少剔 ⇒ 判据又读时钟了（flake 复活）；多剔 ⇒ 判据连内容都不比了")


def test_the_lock_judge_still_goes_red_when_the_content_really_differs(
        tmp_path: pathlib.Path):
    """    负控（`R0-A2`）：归一化不许把"真的改坏"一起放过 —— 四个方向各给一次。判据的意图是"锁只挡交错、不改内容"，所以只要内容的集合变了就必须不等：

    | 改坏的方式 | 期望 | 为什么 |
    |---|---|---|
    | 丢一条 | 红 | 少写了一条事件（锁把某次追加吃掉了） |
    | 多一条 | 红 | 多出一次追加（同一批被写了两遍） |
    | 改一个 payload 字 | 红 | 交错把内容写坏了（正是那条 `UnicodeDecodeError` 的同族） |
    | 换顺序 | 不红 | 刻意的：并发写者那一批的交错顺序按定义不确定，这条判据问的是多重集合；"顺序被保住"不在这条判据的射程内（见 `_canon` 的 docstring） |

    前三条各自单独断言（不许三条挤在一个 `assert` 里 —— 那样只看得到第一条）。
    """
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    for ev in _events(5):
        SS.append(root_a, ev, sid="t")
    for ev in _events(5):
        SS.append(root_b, ev, sid="t")
    got_a, _ = SS.read_session(root_a, "t")
    got_b, _ = SS.read_session(root_b, "t")
    assert _canon(got_a) == _canon(got_b), "前置：没改坏时两边必须相等"

    dropped = got_b[:-1]
    assert _canon(got_a) != _canon(dropped), "丢一条没被认出来 ⇒ 判据对'少写'失去反应"

    extra = [*got_b, {**got_b[-1], "index": 999}]
    assert _canon(got_a) != _canon(extra), "多一条没被认出来 ⇒ 判据对'写重'失去反应"

    changed = [dict(got_b[0])] + got_b[1:]
    changed[0]["payload"] = {**changed[0]["payload"],
                             "note": changed[0]["payload"]["note"][:-1] + "改"}
    assert _canon(got_a) != _canon(changed), "改一个 payload 字没被认出来 ⇒ 判据不比内容了"

    # 第四条是"刻意不红"的那一侧：说清它为什么不在这条判据的射程内（不是漏了）。
    assert _canon(got_a) == _canon(list(reversed(got_b))), (
        "换顺序居然红了 —— 那说明这条判据开始对'交错顺序'下判断，"
        "而并发写者那一批的顺序按定义不确定（见 `_canon` 的 docstring）")
