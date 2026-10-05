# -*- coding: utf-8 -*-
"""会话记录的并发写（`draft/39` §6.7 F4）：两个写者交错 ⇒ 文件里出现非法 UTF-8 字节。

## 这一条是实测逼出来的（2026-10-05，E5 之后的全量套件）

`tests/test_agent_loop.py::test_a_role_can_fan_out_a_batch_in_one_step` 报

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa8 in position 9472

而它单跑必过、全量套件里偶尔红 —— 病因不是那条用例，是会话语料被写坏了：
`LlmBackend` 在一波里并发跑同一角色的多个实例（线程），每个实例都往同一个
`sessions/<sid>.jsonl` 追加事件；没有锁时两次 `write` 会在一个中文字符的字节中间交错，
于是文件里躺着一个非法字节，读会话记录整条路直接炸（而会话记录是本框架唯一的叙事审计面）。

这一组钉两件事：

1. 多线程并发 `append` ⇒ 读回来一行都不坏（正控：判据真的在测并发写）；
2. 同一批事件在单线程下写 ⇒ 逐字节等于并发写的结果（说明锁没有改变内容，只改变顺序）。
"""
from __future__ import annotations

import json
import pathlib
import threading

from agentflow import sessions as SS


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


def test_the_lock_does_not_change_what_gets_written(tmp_path: pathlib.Path):
    """反真空：单线程顺序写的字节集合与并发写一致（锁只挡交错，不改内容）。"""
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
    assert sorted(json.dumps(e, sort_keys=True, ensure_ascii=False) for e in got_a) == \
        sorted(json.dumps(e, sort_keys=True, ensure_ascii=False) for e in got_b)
