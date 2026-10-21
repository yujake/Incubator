"""`usage_ledger` 的跨进程幂等：同一幂等键并发提交只落一条账。
## 为什么这一条必须真的开多个进程
原来的缺陷不是"算错了"，而是"两个进程各自都算对了"：两边都读到"没有这笔账"，于是各写一行，两行的 `usage_id` 本来就不同 ——`store.validate_table` 的"重复 ID"检查与主键 upsert
都不会响。进程内的并发（线程 / 同进程内交错）复现不出它，因为 `filelock` 是按进程持有的。所以本文件用 `subprocess` 起真进程，并让它们在同一个文件屏障上会合。
## 三条断言，各自防一种"假绿"
1. `test_negative_control_distinct_keys_write_n_rows`（负控）：
不同的键必须落 N 行。没有它，一次"进程根本没跑起来 / 写入被静默丢弃"也会让"只落一行"通过 —— 那是因为错误的原因变绿。
2. `test_same_idem_key_over_charge_reply_...`（正控，验收判据）：
同一个键的 N 个进程只落一行、只扣一次、其余拿到 `duplicate` 且不报错。
3. `test_race_window_is_actually_exercised_by_reply_mode`：
断言正控跑的确实是被放大过的竞态窗口（外层读账读到"没有"之后才在屏障上等齐），而不是"看起来像并发、其实被锁自然排队"。
## 修复前的实测（同一个装置）
`mode=reply, n=4` ⇒ 账本 4 行、总 token 6000，4 个进程全部`charged=true / reason="charged"`（应为 1 行、1500、1 个 charged + 3 个
duplicate）。修复后同一命令给出 1 行 —— 同一个装置跑出两种结局，才说明改的是那个窗口。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from agentflow.store import Store

#: 工作进程脚本（不在禁改区，也不是 pytest 收集目标）。
WORKER = Path(__file__).resolve().parent / "_mp_idem_worker.py"

#: 每个用例起几个进程。4 足以制造真实争用，又不至于让 CI 变慢。
N = 4

#: 与 worker 里的口径一致：一笔 1000 in + 500 out = 1500 token。
ONE_CHARGE_TOKENS = 1500


def _run_workers(
    base: Path,
    *,
    n: int = N,
    mode: str,
    task_id: str = "t-mp",
    call_index: int = 0,
    idem_key: str = "idem-unused",
    note: str = "mp",
    timeout: int = 240,
    ws: Path | None = None,
    tag: str = "",
) -> tuple[Store, list[dict]]:
    """起 `n` 个真进程跑同一个工作区，返回 (工作区, 各进程结果)。

    子进程的输出写文件而不是走管道：在本项目的受限执行环境里管道是明确的
    失败面，而文件正是 `Store` 自己一直在用的通道。结果也从文件读 ——
    读不到就说明那个进程崩了，此时把它的日志贴进断言消息。

    `ws` 可以指到同一个工作区上再跑一轮（"重放"用例就是这么做的）；
    `tag` 用来隔开两轮的 results/barrier 目录 —— 否则第二轮会看到第一轮
    遗留的屏障票，屏障立刻放行，"会合"就名存实亡。
    """
    ws = ws or (base / "ws")
    Store(ws).init()
    results = base / f"results{tag}"
    results.mkdir(parents=True, exist_ok=True)
    barrier = base / f"barrier{tag}"

    procs: list[subprocess.Popen] = []
    for i in range(n):
        cmd = [
            sys.executable, str(WORKER),
            "--mode", mode,
            "--root", str(ws),
            "--barrier-dir", str(barrier),
            "--result", str(results / f"r{i}.json"),
            "--n", str(n),
            "--task-id", task_id,
            "--call-index", str(call_index),
            "--idem-key", idem_key,
            "--note", note,
        ]
        with open(results / f"r{i}.log", "wb") as log:
            procs.append(subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT))

    for p in procs:
        p.wait(timeout=timeout)

    payloads: list[dict] = []
    for i in range(n):
        rf = results / f"r{i}.json"
        assert rf.exists(), (
            f"工作进程 {i}（pid={procs[i].pid}）没有留下结果文件，退出码 "
            f"{procs[i].returncode}。日志尾部：\n"
            + (results / f"r{i}.log").read_text(encoding="utf-8", errors="replace")[-3000:]
        )
        payloads.append(json.loads(rf.read_text(encoding="utf-8")))
    return Store(ws), payloads


# --------------------------------------------------------------------- 负控


def test_negative_control_distinct_keys_write_n_rows(tmp_path: Path):
    """负控：不同的幂等键必须落 N 行。

    这一条防的是"装置本身失效"。若进程没真的跑起来、或写入被静默丢弃，
    那么"同一个键只落一行"会因为错误的原因通过。
    必须先证明这个装置数得出 N 行并发写入，那个"1 行"才是证据。
    """
    st, payloads = _run_workers(
        tmp_path, n=N, mode="once", idem_key="idem-perproc-{pid}",
    )
    assert all(p["ok"] for p in payloads), f"有进程失败：{payloads}"

    rows = st.rows("usage_ledger")
    assert len(rows) == N, f"不同的键必须落 {N} 行（装置失效？），实际 {len(rows)}"
    assert len({r["usage_id"] for r in rows}) == N, "N 行的主键必须互不相同"
    assert sum(int(r["tokens_total"]) for r in rows) == N * ONE_CHARGE_TOKENS
    assert all(p["recorded"] for p in payloads), payloads
    assert not any(p["duplicate"] for p in payloads), payloads


# --------------------------------------------------------------------- 正控


def test_same_idem_key_over_charge_reply_writes_exactly_one_row(tmp_path: Path):
    """验收判据：同一幂等键经 `modelcost.charge_reply` 并发提交 N 次。

    必须满足四件事，缺一不可：

    - 账本只有一行（`usage_ledger` 只能产生一条记录）；
    - 只扣一次费/额度（总 token 等于单笔，而不是 N 倍）；
    - 其余 N−1 次返回幂等结果（`charged=False, reason="duplicate"`），
      且 `usage_id` 指向那一行；
    - 不报 500（所有进程 `ok=True`，没有任何异常逃出去）。
    """
    st, payloads = _run_workers(
        tmp_path, n=N, mode="reply", task_id="race", call_index=0,
    )
    assert all(p["ok"] for p in payloads), f"有进程抛异常（相当于 500）：{payloads}"

    rows = st.rows("usage_ledger")
    assert len(rows) == 1, (
        f"同一幂等键必须只落一行，实际 {len(rows)} 行 —— "
        f"这就是重复记账（每行 usage_id 都不同，主键去重救不了）"
    )
    total = sum(int(r["tokens_total"]) for r in rows)
    assert total == ONE_CHARGE_TOKENS, f"只扣一次费，总 token 应为 {ONE_CHARGE_TOKENS}，实际 {total}"

    charged = [p for p in payloads if p["charged"]]
    dup = [p for p in payloads if not p["charged"]]
    assert len(charged) == 1, f"恰好一个进程真正入账，实际 {len(charged)}：{payloads}"
    assert len(dup) == N - 1, payloads
    assert all(p["reason"] == "duplicate" for p in dup), payloads
    assert all(p["usage_id"] == rows[0]["usage_id"] for p in payloads), (
        "重复请求必须返回同一笔账的 usage_id（幂等结果要指向那一行）"
    )


def test_same_idem_key_over_charge_once_writes_exactly_one_row(tmp_path: Path):
    """同一个判据在原语层（`TokenMeter.charge_once`）也成立。

    与上一条分开的理由：上一条走的是 `modelcost` 的完整翻译路径（含无锁快速通道），
    这一条直接压 `charge_once`。两条都绿才说明"锁内判重"这件事本身成立，
    而不是"快速通道恰好挡住了"。
    """
    st, payloads = _run_workers(
        tmp_path, n=N, mode="once", idem_key="idem-mp-once",
    )
    assert all(p["ok"] for p in payloads), payloads

    rows = st.rows("usage_ledger")
    assert len(rows) == 1, f"同一幂等键必须只落一行，实际 {len(rows)} 行"
    assert sum(int(r["tokens_total"]) for r in rows) == ONE_CHARGE_TOKENS

    assert len([p for p in payloads if p["recorded"]]) == 1, payloads
    assert len([p for p in payloads if p["duplicate"]]) == N - 1, payloads
    assert all(p["usage_id"] == rows[0]["usage_id"] for p in payloads), payloads


def test_repeated_runs_never_accumulate(tmp_path: Path):
    """同一个工作区连跑两轮 ⇒ 仍然是 1 行。

    这一条盯的是"第二次运行"这种现实形态：进程重启、任务重放，或用户把同一条
    命令再敲一遍（正是 `run_topic` 的既有用法）。此时无锁快速通道就能命中，
    `charge_once` 在锁内也应命中 —— 两条路都必须指向同一行。
    """
    ws = tmp_path / "ws"
    st1, p1 = _run_workers(tmp_path, n=N, mode="reply", task_id="race", call_index=0,
                           ws=ws, tag="-1")
    assert all(p["ok"] for p in p1), p1
    assert len(st1.rows("usage_ledger")) == 1
    assert len([p for p in p1 if p["charged"]]) == 1, p1

    st2, p2 = _run_workers(tmp_path, n=N, mode="reply", task_id="race", call_index=0,
                           ws=ws, tag="-2")
    assert all(p["ok"] for p in p2), p2
    rows = st2.rows("usage_ledger")
    assert len(rows) == 1, f"重放不该再写一笔账，实际 {len(rows)} 行"
    assert not any(p["charged"] for p in p2), f"第二轮全部应当是幂等重放：{p2}"
    assert all(p["reason"] == "duplicate" for p in p2), p2


# --------------------------------------------------------------------- 装置自证


def test_reply_mode_really_exercises_the_race_window(tmp_path: Path):
    """装置自证：`reply` 模式确实把"读账 → 写账"之间的窗口拉开过。

    判据落在工作进程自己报告的屏障参与上：4 个进程都必须经历
    "外层读到没有这笔账 ⇒ 在 `postread` 屏障上等齐同伴"。
    若这道屏障从没被跨过（比如钩子没装上、或外层读直接命中了），
    上面那条"只落一行"就退化成"顺序执行本来就不会重复"——
    绿灯，但什么都没验证。
    """
    st, payloads = _run_workers(tmp_path, n=N, mode="reply", task_id="race", call_index=0)
    barrier_files = list((tmp_path / "barrier").glob("postread.*"))
    assert len(barrier_files) == N, (
        f"4 个进程都必须真的在扩展后的窗口里会合，实际只有 {len(barrier_files)} 个 —— "
        "说明这一跑没有压到竞态窗口，正控的绿灯不成立"
    )
    assert len(st.rows("usage_ledger")) == 1


# --------------------------------------------------------------------- 原语单元


def test_row_with_idem_key_requires_an_exact_token():
    """按 token 精确比对：`idem-abc123` 不许命中 `idem-abc1234`。

    子串比对会把两个不同的键判成同一笔 ⇒ 静默少记一笔账。
    它比多记更难发现（账面上一切自洽），所以这里把它钉死。
    """
    from agentflow.tokenmeter import row_with_idem_key

    rows = [{"usage_id": "0000", "note": "modelgw;ok；idem-abc1234"}]
    assert row_with_idem_key(rows, "idem-abc1234") is not None
    assert row_with_idem_key(rows, "idem-abc123") is None, "子串命中必须被拒绝"
    assert row_with_idem_key([{"usage_id": "0000", "note": "见 idem-abc1234 一行"}], "idem-abc1234") is None, (
        "键必须是一个**独立 token**，不是正文里出现过"
    )


def test_row_with_idem_key_rejects_empty_key():
    """空键是错误而不是"匹配不上"：空键会让每一行都命中。"""
    from agentflow.tokenmeter import row_with_idem_key

    with pytest.raises(ValueError, match="idem_key 不能为空"):
        row_with_idem_key([{"note": "x"}], "")


def test_marker_of_is_stable_and_hex_only():
    """标记必须只含 `[a-z0-9-]`（否则会与 `note` 的分隔符打架）。"""
    from agentflow.tokenmeter import marker_of

    m = marker_of("idem", "t-0001", 0)
    assert m == marker_of("idem", "t-0001", 0), "同一个输入必须给出同一个键"
    assert m.startswith("idem-")
    assert re.fullmatch(r"[a-z0-9-]+", m), m
    assert marker_of("settle", "t-0001") != m
    # 带空格 / 全角分号的 task_id 也不会污染 note
    dirty = marker_of("idem", "a b；c", 0)
    assert re.fullmatch(r"[a-z0-9-]+", dirty), dirty


def test_charge_once_rejects_unusable_keys(store: Store):
    """含空白或分隔符的键必须被拒绝：它会被拆成多个 token，判重就指向别处。"""
    from agentflow.tokenmeter import Charge, TokenMeter

    meter = TokenMeter(store)
    c = Charge(role="A", scope="search", tokens_in=1, note="x")
    for bad in ("", "   ", "a b", "a；b"):
        with pytest.raises(ValueError):
            meter.charge_once(c, idem_key=bad)
    assert store.rows("usage_ledger") == [], "被拒绝的调用不许留下任何行"


def test_charge_once_zero_value_still_needs_a_note(store: Store):
    """零值守卫必须在追加幂等键之前判。

    否则键会让 `note` 非空，`UsageEntry.validate` 就会放行一条
    "只有幂等键、不含任何业务信息"的零值行 —— 那正是守卫要挡的污染。
    """
    from agentflow.tokenmeter import Charge, TokenMeter

    meter = TokenMeter(store)
    with pytest.raises(ValueError, match="零值花销必须写 note"):
        meter.charge_once(Charge(role="A", scope="search", note=""), idem_key="idem-x")
    assert store.rows("usage_ledger") == []


def test_charge_once_duplicate_does_not_burn_an_id(store: Store):
    """重复入账不该消耗一个 `usage_id`。

    若判重放在 `alloc_id` 之后，每次重放都会在计数器上留下一个永久空洞
    （本项目的 `id_gap` 判据会把它报出来，但那时已经分不清
    "有人在重放"与"真的丢了一个号"）。
    """
    from agentflow.tokenmeter import Charge, TokenMeter

    meter = TokenMeter(store)
    c = Charge(role="A", scope="search", tokens_in=10, note="x")
    first = meter.charge_once(c, idem_key="idem-once")
    after_first = dict(store.read("counters")["counters"])
    second = meter.charge_once(c, idem_key="idem-once")
    after_second = dict(store.read("counters")["counters"])

    assert first["recorded"] and not first["duplicate"]
    assert second["duplicate"] and not second["recorded"]
    assert second["usage_id"] == first["usage_id"]
    assert after_first == after_second, "重复入账不该推进 ID 计数器"
    assert len(store.rows("usage_ledger")) == 1


def test_charge_once_different_keys_are_two_rows(store: Store):
    """别把合法的第二笔当成重复（与上面那条构成一对）。"""
    from agentflow.tokenmeter import Charge, TokenMeter

    meter = TokenMeter(store)
    c = Charge(role="A", scope="search", tokens_in=10, note="x")
    a = meter.charge_once(c, idem_key="idem-a")
    b = meter.charge_once(c, idem_key="idem-b")
    assert a["recorded"] and b["recorded"]
    assert a["usage_id"] != b["usage_id"]
    assert len(store.rows("usage_ledger")) == 2


def test_charge_once_marker_lands_as_the_last_note_token(store: Store):
    """键落在 `note` 的最后一个 token，且重试说明在它之前。

    顺序固定才可读、也才稳定：键的位置若随 `attempts` 变化，
    排查时就无法用"最后一段"来快速认账。
    """
    from agentflow.tokenmeter import Charge, TokenMeter, note_tokens

    meter = TokenMeter(store)
    meter.charge_once(
        Charge(role="A", scope="search", tokens_in=10, attempts=2, note="base"),
        idem_key="idem-last",
    )
    note = store.rows("usage_ledger")[0]["note"]
    toks = note_tokens(note)
    assert toks[-1] == "idem-last"
    assert any("含重试 2 次" in t for t in toks)
    assert toks.index("base") < len(toks) - 1
