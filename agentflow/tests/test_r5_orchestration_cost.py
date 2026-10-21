"""`G-1` / `G-2` / `G-3` / `R5-AN-1` 的回归判据（编排与成本，落点都不在 FC-27 清单里）。

改前备份（`R7-R5-3` 更正）：这份 docstring 此前列着四份 `temp/zone-backup-r5-*.py`，
而那一批没有留下这类备份（`draft/28` §13 逐字登记过这件事），四份一份都不存在。
真实情况有两条可核的线索，都不需要编造文件名：

- 那一批的改前字节由审计产物钉住：`temp/REAUDIT6-R5.json` 的 `files_sha256_before`
  里逐文件记着 sha256（本文件自己也在里面）；
- 第 6 轮修复批（`F5`）真的留了改前副本，命名是 `temp/FIX6-F5-before_<路径下划线化>.py`
  （`src/agentflow/runflow.py` / `modelcost.py` / `conductor.py` / `tools/table_tools.py` 四份）。

为什么把这件事写进 docstring 而不是删掉：读这段的人要能回答"改前的形态去哪找"，
而不是得到一串不存在的文件名（`R7-R5-3` 那类缺陷的形态就是"注释里的引用没人核"）。

| 条目 | 缺陷（改前实测） | 本文件里"改前必红"的那条 |
|---|---|---|
| `G-1` | `LocalBackend.call` 收下 `token` 却末行 `return fn(given)` ⇒ 取消到不了在跑的 handler；`raise_if_cancelled` 调用点为 0；子进程（Lean）完全在取消面之外 | `test_a_running_handler_sees_the_token` / `test_cancel_kills_a_running_child_process` |
| `G-2` | 幂等键只按主题命名 ⇒ 同一主题跑第二遍整轮被判 duplicate，账本少记一轮真实花费，而第二次的报告把第一次的钱记在自己名下 | `test_two_runs_of_the_same_topic_are_not_deduplicated` |
| `G-3` | `run_topic` 给账本行写了 `task_id` 却从不建 `tasks` 行 ⇒ 每跑一次全库审计多两条 error 级 `dangling_usage_task` | `test_a_run_creates_the_task_row_verify_wants` |
| `R5-AN-1` | 取号在 `store.tx` 之外 ⇒ 两个并发 `agentflow run` 撞同一个 `t-NNNN`：`tasks` 只剩 1 行、存活行 `tokens` 是两跑之和、两条 usage 都挂同一行，而 `verify_all` 的 code 集合是 `[]`（静默） | `test_two_concurrent_runs_never_share_a_task_id` |

## `R5-AN-1` 改掉的契约（读本文件前先读这段）

`tasks` 那一行现在分两次写，两个写入点必须在同一个 `store.tx` 语义下理解：

1. 开跑时（取号那一段）：在 `store.tx("tasks")` 内取号，并在同一个临界区里落一行
   占位行（`status="running"`、`outcome=None`、`tokens=0`、`ended_at=None`）。
   落行是取号的一部分：`interactions.next_prefixed_id` 是纯函数、没有计数器，
   号只有在盘上可见时才对下一个并发进程有意义；
2. 收工时（`_settle_run_task`）：按同一个 `task_id` 把那一行整行改写成终态。

⇒ 与本次改动前相比，契约变了三件事（不是"判据被改松了"）：

- 跑到一半的库里可能出现 `status="running"` 的行（崩在收工之前），
  这时 `verify_all` 报的是 warning `task_still_running` —— 那是事实，不是噪音；
- 即使 `_settle_run_task` 写失败，账本行也不再悬空（占位行已经在），
  所以 `dangling_usage_task` 不再是这个形态的判据；
- 因此"没写成终态"这件事的判据是「那一行仍是 `running` 且没被改写」，
  而不是"`tasks` 表是空的"（后者是本次改动前的形态）。

### 为什么这一条非要改契约（改前最小修法的实测读数）

"只把取号搬进 `store.tx`、不落行"这条最小修法不成立：第二个进程在第一个
进程写行之前进 tx，读到的还是同一份快照。实测（两真进程 + 起跑屏障，
`temp/fix6_f5-minimal.txt`）：`E1/E2/E3/E5` 四条判据全部仍为 `False`
（撞号、丢行、`tokens` 混算、usage 指错行，一个都没消失）。
落行之后同一套读数全部翻面（`temp/fix6_f5-after-an1.txt`）。
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import time
import tokenize

import pytest

from agentflow import cancellation as CX
from agentflow import modelcost
from agentflow import modelgw
from agentflow import schema as S

#: 一次自检调用（11 in / 3 out，无缓存命中栏）该值多少钱 —— **现算**，不抄数。
#:
#: 为什么现算（2026-10-14 业主改了花销口径：三档 token + 峰谷两价）：把
#: `6e-06` 那样的数抄进判据，等于把"当时的价目表"冻进判据里 —— 调一次价就假红一次。
#: 峰谷那一位钉在**低谷**（`AGENTFLOW_MODEL_PEAK=0`）：读墙钟的话，同一条判据在峰值
#: 时段会算出差一倍的钱（那正是"花销不可复现"）。


@pytest.fixture(autouse=True)
def _pin_off_peak(monkeypatch):
    """本文件的用例都在低谷价上判 —— **按用例作用域钉**，不许在导入期动环境。

    这里此前是模块级的 `os.environ.setdefault(modelcost.ENV_PEAK, "0")`。
    它看着无害，实际是**进程级**的：pytest 在**收集期**就把每个测试文件导入一遍，
    于是这条 setdefault 在任何用例跑起来之前就已经改了整台进程的环境
    ——`test_cost_matches_vendor.py::test_peak_and_off_peak_are_chosen_by_the_clock`
    因此在全量跑里拿到 `peak_source='env'` 而红、单跑那个文件却是绿的
    （实测 2026-10-14：全量 9 failed 里有它一条，隔离跑 46 passed）。
    "只在跑这个文件时才生效"才是这里真正想要的语义。
    """
    monkeypatch.setenv(modelcost.ENV_PEAK, "0")


def _one_call_usd(tokens_in: int = 11, tokens_out: int = 3) -> float:
    """一次自检调用的美元数（走**唯一那一处**价目表，与生产口径同源）。"""
    price, _reading = modelcost.price_for("deepseek", modelgw.DEFAULT_MODEL)
    return round((tokens_in * price.usd_per_m_in
                  + tokens_out * price.usd_per_m_out) / 1_000_000.0, 6)


from agentflow.conductor import LocalBackend
from agentflow.modelgw import ModelSpec
from agentflow.runflow import run_topic
from agentflow.store import Store

TS1 = "2026-03-01T00:00:01+00:00"
TS2 = "2026-03-01T00:00:02+00:00"
ABSTRACT = "An abelian group is a group in which the commutative law holds."


def _reply(text: str) -> str:
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    }, ensure_ascii=False)


def _transport(text: str):
    def _t(url: str, headers: dict, data: bytes, timeout_sec: float):  # noqa: ARG001
        return 200, _reply(text)

    return _t


def _search(topic: str, *, limit: int, timeout_sec: float):  # noqa: ARG001
    return [{"source": "selftest", "title": "Abelian groups", "year": 1930,
             "doi": "10.1000/selftest", "abstract": ABSTRACT}]


def _run(store: Store, tmp_path: pathlib.Path, name: str, *, now: str):
    text = f"- 阿贝尔群是交换群 || {ABSTRACT}\n"
    return run_topic(
        store, topic="同一个主题", budget_usd=1.0, out_dir=tmp_path / name,
        transport=_transport(text), spec=ModelSpec(api_key="selftest-key"),
        max_calls=1, search_fn=_search, now=now,
    )


# ============================================================ G-1（handler 面）


class _Probe:
    """一个"跑得慢"的角色实例：`slow` 在循环里检查取消，`plain` 什么都不看。"""

    def __init__(self) -> None:
        self.seen: list[object] = []

    def slow(self, n: int = 0) -> str:
        self.seen.append(CX.current_token())
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            CX.raise_if_cancelled()
            time.sleep(0.01)
        return "跑完了"

    def plain(self, n: int = 0) -> str:
        self.seen.append(CX.current_token())
        return "没看取消"


class _ProbeBackend(LocalBackend):
    """把 `resolve` 换成一个固定实例（不起真 agent），其余走 `LocalBackend.call`。

    `resolve` 的签名必须与 `LocalBackend.resolve` 逐字同形（`role, instance=""`）：
    2026-09-30 加了实例轴之后，`Conductor` 会带 `instance` 调它 ——
    少一个形参就会在并发线程里抛 `TypeError`，而那种失败会被记成
    `failed`，看起来像角色崩了（实测过：三条 R5 用例当场变红）。
    """

    def __init__(self, obj: object) -> None:
        self._obj = obj
        self.store = None

    def resolve(self, role: str, instance: str = ""):  # noqa: ARG002
        return self._obj


@pytest.fixture
def probe_registry(monkeypatch):
    """把探针动作注册进能力表（否则 `LocalBackend.call` 的 `find_action` 找不到它）。

     实测：`C.CAPABILITIES` 的每个角色值是 tuple，不是 dict
    （`monkeypatch.setitem` 会去 `.get` 而炸）。所以这里整体替换那个角色的元组。
    """
    import dataclasses

    from agentflow import capabilities as C

    spec = C.ActionSpec(
        role="G", action="slow_probe", summary="G-1 探针：会检查取消",
        params={"type": "object", "properties": {}}, returns="str",
        side_effect="read", handler_name="slow", external="none",
    )
    plain = dataclasses.replace(spec, action="plain_probe", handler_name="plain")
    monkeypatch.setitem(C.CAPABILITIES, "G", (*C.CAPABILITIES["G"], spec, plain))
    return spec


def test_a_running_handler_sees_the_token(probe_registry) -> None:
    """负控（核心）：跑着的 handler 必须能读到 同一个 token。

    改前 `LocalBackend.call` 的末行是 `return fn(given)` ⇒ `current_token()` 是 `None`，
    取消到不了在跑的 handler。
    """
    obj = _Probe()
    backend = _ProbeBackend(obj)
    token = CX.CancelToken()
    backend.call("G", "plain_probe", {}, token=token)
    assert obj.seen == [token], f"handler 读到的 token 是 {obj.seen!r}，不是调用方那一个"


def test_cancelling_mid_flight_makes_the_handler_raise(probe_registry) -> None:
    """负控 2：跑着的 handler 在取消后必须抛 CancelRequested（不是跑完）。"""
    import threading

    obj = _Probe()
    backend = _ProbeBackend(obj)
    token = CX.CancelToken()
    box: dict = {}

    def _go():
        try:
            backend.call("G", "slow_probe", {}, token=token)
            box["result"] = "done"
        except CX.CancelRequested as exc:
            box["result"] = "cancelled"
            box["detail"] = str(exc)

    th = threading.Thread(target=_go, daemon=True)
    th.start()
    time.sleep(0.15)
    token.cancel("user", detail="人按了停止", by="probe")
    th.join(timeout=2.0)
    assert box.get("result") == "cancelled", box
    assert "人按了停止" in box.get("detail", ""), box


def test_an_already_cancelled_token_does_not_enter_the_handler(probe_registry) -> None:
    """负控 3：调用前就取消了 ⇒ 不进 handler（别白干一轮、更别写半张表）。"""
    obj = _Probe()
    backend = _ProbeBackend(obj)
    token = CX.CancelToken()
    token.cancel("user", detail="起跑前就停了", by="probe")
    with pytest.raises(CX.CancelRequested):
        backend.call("G", "plain_probe", {}, token=token)
    assert obj.seen == [], "已经取消了却还是进了 handler"


def test_cancel_kills_a_running_child_process() -> None:
    """负控 4（子进程面）：`run_cancellable` 起的进程必须被 `cancel()` 杀掉。

    这一条钉的是"跑 600 秒的 Lean 检查"那个形态：协作式取消对子进程不成立
    （它没有"安全停下的点"），所以由 `cancel()` 主动杀。
    """
    import threading

    token = CX.CancelToken()
    box: dict = {}

    def _go():
        box["out"] = CX.run_cancellable(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_sec=60.0, token=token,
        )

    th = threading.Thread(target=_go, daemon=True)
    th.start()
    # 等它真的把进程注册上（不然可能在起进程之前就取消了，测不到"杀"）
    deadline = time.monotonic() + 5.0
    while token.spawned_count == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert token.spawned_count == 1, "探针的前提没建立：进程没被注册到 token 上"
    t0 = time.monotonic()
    token.cancel("user", detail="杀子进程", by="probe")
    th.join(timeout=10.0)
    elapsed = time.monotonic() - t0
    out = box.get("out") or {}
    assert out.get("cancelled") is True, out
    assert out.get("timed_out") is False, "取消被记成了超时 —— 两者处置不同，不许折叠"
    assert elapsed < 5.0, f"取消没有让它尽快结束（{elapsed:.2f}s）"
    assert token.spawned_count == 0, "杀完之后出生表该是空的"


def test_run_cancellable_without_a_token_still_works() -> None:
    """正控：没有 token 时照常起进程（别把"可取消"做成"必须取消"）。"""
    out = CX.run_cancellable([sys.executable, "-c", "print('hi')"], timeout_sec=60.0)
    assert out["exit_code"] == 0 and out["cancelled"] is False
    assert "hi" in out["stdout"]


# ============================================================ G-2（幂等键）


def test_two_runs_of_the_same_topic_are_not_deduplicated(store: Store,
                                                         tmp_path: pathlib.Path) -> None:
    """负控（核心）：同一工作区、同一主题跑两次 ⇒ 两次都真的记账。

    改前第二次整轮被判 `duplicate`（幂等键只按主题），账本只有 2 行、
    而第二次的 `cost.json` 却带着第一次的钱。
    """
    first = _run(store, tmp_path, "a", now=TS1)
    second = _run(store, tmp_path, "b", now=TS2)

    ledger_rows = store.rows("usage_ledger")
    # （`max_calls=1` ⇒ 每次运行恰好 1 次模型调用 ⇒ 两次运行 2 行。
    #  改前这里是 2 行没错，但第二行是第一次的复制品：`idem_key` 相同、
    #  tokens/usd 相同、第二次的真实调用根本没进账。）
    assert len(ledger_rows) == 2, (
        f"两次运行共应有 2 条账本行，实际 {len(ledger_rows)} 条："
        f"{[(r['task_id'], r['idem_key']) for r in ledger_rows]}"
    )
    keys = [r["idem_key"] for r in ledger_rows]
    assert len(set(keys)) == 2, f"两次运行的幂等键必须不同（否则第二次整轮被判重放）：{keys}"
    assert len({r["task_id"] for r in ledger_rows}) == 2, ledger_rows
    assert first["spent_usd"] > 0 and second["spent_usd"] > 0
    cost2 = json.loads((tmp_path / "b" / "cost.json").read_text(encoding="utf-8"))
    assert all(c["charged"] is True for c in cost2["per_call"]), cost2["per_call"]
    assert not any(c["reason"] == "duplicate" for c in cost2["per_call"]), cost2["per_call"]


def test_the_two_runs_get_different_task_ids(store: Store, tmp_path: pathlib.Path) -> None:
    """判据的接口面：两次运行的 `task_id` 必须不同（幂等键按运行命名）。"""
    first = _run(store, tmp_path, "a", now=TS1)
    second = _run(store, tmp_path, "b", now=TS2)
    ids = {r["task_id"] for r in store.rows("usage_ledger")}
    assert len(ids) == 2, ids
    assert first["exit_code"] == 0 and second["exit_code"] == 0


# ============================================================ G-3（任务行）


def test_a_run_creates_the_task_row_verify_wants(store: Store, tmp_path: pathlib.Path) -> None:
    """负控（核心）：跑一次之后 `verify_all` 不许再有 `dangling_usage_task`。

    改前 `tasks` 表行数恒为 0 ⇒ 每跑一次多两条 error 级发现。
    """
    from agentflow.verify import verify_all

    out = _run(store, tmp_path, "a", now=TS1)
    assert out["exit_code"] in (0, 2)

    tasks = store.rows("tasks")
    assert len(tasks) == 1, f"这次运行应写 1 行 tasks，实际 {len(tasks)}"
    row = tasks[0]
    assert row["role"] == "M" and row["action"] == "run"
    assert row["task_id"] in {r["task_id"] for r in store.rows("usage_ledger")}
    assert row["tokens"] > 0, "tokens 必须从 meter 抄回（与账本同一条口径）"
    assert row["status"] == "done" and row["outcome"] == "ok", row

    rep = verify_all(store)
    codes = [i.code for i in rep.errors]
    assert "dangling_usage_task" not in codes, codes


def test_the_task_row_is_missing_if_we_take_it_away(monkeypatch, store: Store,
                                                    tmp_path: pathlib.Path) -> None:
    """负控 2（`R5-AN-1` 之后的新口径）：行真的不在时，那条判据必须红。

    契约变了（见模块 docstring）：`tasks` 行现在由"开跑时的占位行 + 收工时的
    终态改写"两次写共同保证，所以"settle 写失败"不再等于"表里没有行"。
    这一条守的是判据本身有没有牙：把那一行从库里删掉，`verify_all` 必须
    报出 `dangling_usage_task` —— 而不是恒真地报"没问题"。

    造法刻意分两步：先正常跑一次（表里有一行终态行），删掉它，再比两份读数。
    没有"删之前是干净的"这一步，`dangling_usage_task` 也可能是别处引入的。
    """
    from agentflow.verify import verify_all

    _run(store, tmp_path, "a", now=TS1)
    assert len(store.rows("tasks")) == 1
    before = [i.code for i in verify_all(store).errors]
    assert "dangling_usage_task" not in before, before

    # 把那一行从库里拿掉（直接清空表的快照：判据读的是库，不是内存里的对象）。
    # 先 upsert 一次是为了把 `tasks` 标脏 —— `Tx` 只在 `upsert` 里记脏表，
    # 单纯清空 list 不会触发落盘（那会变成"内存里删了、盘上还在"的假注入）。
    with store.tx("tasks", actor="probe", note="R5-AN-1 负控：删掉任务行") as tx:
        tx.upsert("tasks", dict(store.rows("tasks")[0]))
        tx.rows("tasks").clear()

    assert store.rows("tasks") == [], "注入没生效：任务行还在，那这条判据读不到事实"
    after = [i.code for i in verify_all(store).errors]
    assert "dangling_usage_task" in after, (
        f"任务行被删掉之后账本行悬空了，判据却没有响：{after}"
    )


def _run_two_processes(tmp_path: pathlib.Path, *, delay: float) -> tuple[dict, dict, Store]:
    """起两个真进程并发跑 `run_topic`，返回两份结果与工作区。

    为什么必须是真进程：`R5-AN-1` 的窗口是"两个进程各读一份无锁快照、各取号"，
    同进程里 `store` 的缓存与进程内锁会把它掩盖掉。起跑屏障
    （`_runflow_mp_worker._wait_for_go`）保证两个取号窗口真的重叠 ——
    没有它，"并发"会退化成"先后"，测试得到一个恒绿的假象。

    为什么结果走文件：本项目受限执行环境里管道是明确的失败面
    （子进程用管道存输出会 EPERM），所以子进程把结果写进 JSON 文件。
    """
    import subprocess

    worker = pathlib.Path(__file__).resolve().parent / "_runflow_mp_worker.py"
    ws = tmp_path / "ws"
    barrier = tmp_path / "barrier"
    procs: list[tuple[str, subprocess.Popen, pathlib.Path]] = []
    for tag, now, topic in (("a", TS1, "并发甲"), ("b", TS2, "并发乙")):
        log = (tmp_path / f"child-{tag}.log").open("wb")  # noqa: SIM115
        proc = subprocess.Popen(
            [sys.executable, str(worker), "--ws", str(ws), "--out", str(tmp_path / tag),
             "--topic", topic, "--now", now, "--barrier", str(barrier), "--n", "2",
             "--result", str(tmp_path / f"res-{tag}.json"), "--delay", str(delay)],
            stdout=log, stderr=subprocess.STDOUT, cwd=str(worker.parent),
        )
        procs.append((tag, proc, log))

    # 等两个子进程都到起跑屏障，再放行；任何一个没到就断言失败（装置故障不许
    # 被读成"修复生效"）。
    deadline = time.monotonic() + 120.0
    while len(list(barrier.glob("ready.*"))) < 2:
        assert time.monotonic() < deadline, (
            f"起跑屏障超时：只有 {len(list(barrier.glob('ready.*')))}/2 个进程就绪。"
            f"子进程日志：{[(t, p.poll()) for t, p, _ in procs]}"
        )
        time.sleep(0.01)
    barrier.mkdir(parents=True, exist_ok=True)
    (barrier / "go.2").write_text("1", encoding="utf-8")

    results: dict[str, dict] = {}
    for tag, proc, log in procs:
        code = proc.wait(timeout=180.0)
        log.close()
        results[tag] = json.loads((tmp_path / f"res-{tag}.json").read_text(encoding="utf-8"))
        assert code == 0, (
            f"子进程 {tag} 以 {code} 退出（装置故障，不是被测结论）——"
            f"见 {tmp_path / f'child-{tag}.log'}"
        )
    return results["a"], results["b"], Store(ws)


def test_two_concurrent_runs_never_share_a_task_id(tmp_path: pathlib.Path) -> None:
    """`R5-AN-1` 正控（核心）：两个真进程并发跑 ⇒ 两个不同的 `t-NNNN`、两行、各记各的账。

    改前实测（`temp/reaudit6-R5-p6.txt` 与 `temp/fix6_f5-smoke-pre.txt`）：
    两个进程都拿到 `t-0001`；`tasks` 表只剩 1 行而它的 `tokens` 是两跑之和
    （28 = 14 + 14）；两条 `usage_ledger` 都挂 `t-0001`；`verify_all` 的 code
    集合是 `[]` —— 静默丢行，一条判据都不响。

    判据四条，各自对应一种失真（少任何一条，另外三条都可能在"两个进程其实
    没并发"的装置故障下通过）：
    E1 两个 task_id 不同；E2 `tasks` 恰好两行；E3 每行 tokens = 自己那一跑；
    E5 每一条 usage 挂到自己那一行上。

    `now` 必须显式给（两个不同的值）：`now=None` 时生产形态的运行标识带随机
    后缀，两条账不会互判重放，而显式不同的 `now` 让"这是两次独立逻辑运行"
    这件事在账本上也成立 —— 见 `R5-F5` 与 `draft/28` §84.3 ①。
    """
    from agentflow.verify import verify_all

    first, second, store = _run_two_processes(tmp_path, delay=2.0)

    tasks = sorted(store.rows("tasks"), key=lambda r: str(r["task_id"]))
    usage = store.rows("usage_ledger")
    ids = [t["task_id"] for t in tasks]
    assert len(ids) == 2, f"E2 两次并发运行必须各留一行 tasks，实际 {ids}：{tasks}"
    assert len(set(ids)) == 2, f"E1 两个并发运行撞了同一个 task_id：{ids}"

    # E3：每一行的 tokens 只算自己那一跑（改前存活行的 28 是两跑之和）。
    per_run = {t["task_id"]: int(t["tokens"]) for t in tasks}
    assert sorted(per_run.values()) == [14, 14], (
        f"E3 每行 tokens 必须是自己那一跑的 14（不是两跑之和）：{per_run}"
    )
    for t in tasks:
        assert t["status"] == "done" and t["ended_at"], t

    # E5：账本每一行都必须挂到「自己」那一行上，且两行都被挂到。
    assert len(usage) == 2, usage
    hung = {str(u["task_id"]) for u in usage}
    assert hung == set(ids), f"E5 usage 挂错了行：{hung} vs {ids}"
    for u in usage:
        assert int(u["tokens_total"]) == 14, u

    # 两个子进程各自的产物也要自洽：自己那一跑的花费（14 token，价按价目表现算）。
    for label, res in (("a", first), ("b", second)):
        assert res["exit_code"] == 0, (label, res)
        assert res["task_row"]["written"] is True, (label, res)
        per_call = json.loads((tmp_path / label / "cost.json").read_text(encoding="utf-8"))
        assert all(c["charged"] is True for c in per_call["per_call"]), (label, per_call)
        assert per_call["calls_usd"] == _one_call_usd(), (label, per_call["calls_usd"])
        # `F5-FOUND-1`：并发下每一跑的 `spent_usd_this_run` 必须等于「自己」的
        # `calls_usd`。改前它是"工作区增量"（开跑基线到现在的差），而另一个进程
        # 在基线之后入的账会落进这个差里 ⇒ 第二次跑完的那一跑会报出两倍的钱。
        assert per_call["spent_usd_this_run"] == per_call["calls_usd"], (
            f"{label} 那一跑的 spent_usd_this_run={per_call['spent_usd_this_run']} "
            f"与自己的 calls_usd={per_call['calls_usd']} 不等 ⇒ 预算是按工作区增量算的"
        )
        assert per_call["reconciled_with_usage_ledger"] is True, (label, per_call)
        assert per_call["budget_exhausted"] is False, (label, per_call)

    # 改前这里什么都不报（`errors=[] warnings=[]`）—— 判据真空才是这条缺陷
    # 最危险的地方，所以把"也没有别的发现"一并钉住：它证明两行是真的合法，
    # 而不是"靠多报几条别的发现把它盖过去"。
    rep = verify_all(store)
    assert [i.code for i in rep.errors] == [], [i.code for i in rep.errors]
    assert [i.code for i in rep.warnings] == [], [i.code for i in rep.warnings]


def test_the_task_row_carries_no_fake_artifact_kinds(store: Store,
                                                     tmp_path: pathlib.Path) -> None:
    """`R5-F3`（第一次重审实测的修法）：`tasks.artifacts` 不许再放文件名。

    `verify.py` 的契约是"每一项形如 `<表名>:<行 id>`，指向库里真的存在的一行"。
    改前 `_settle_run_task` 把 `ARTIFACTS` 的六个文件名塞进这个字段，
    于是每跑一次 `agentflow run` 新增 6 条 `unknown_artifact_kind` warning ——
    而当时的用例只断言 `errors`，所以这一档结构上不可见。
    现在 `artifacts` 留空（那六件东西是磁盘文件，不是表里的行），
    它们的名字进 `detail`。
    """
    from agentflow.runflow import ARTIFACTS
    from agentflow.verify import verify_all

    _run(store, tmp_path, "a", now=TS1)
    row = store.rows("tasks")[0]
    assert list(row.get("artifacts") or []) == [], row.get("artifacts")
    for name in ARTIFACTS:
        assert name in str(row.get("detail") or ""), (
            f"产物名 {name} 必须仍然可见（挪进 detail），否则是丢信息而不是改字段"
        )
    all_codes = [i.code for i in verify_all(store).issues]
    assert "unknown_artifact_kind" not in all_codes, all_codes
    assert "dangling_task_artifact" not in all_codes, all_codes


def test_the_artifact_kind_rule_really_fires_on_file_names(store: Store,
                                                           tmp_path: pathlib.Path) -> None:
    """`R5-F3` 负控：把那一行改回"六个文件名" ⇒ `verify_all` 必须报出这类 warning。

    没有这一条，上面那条"0 条 warning"可能只是因为 `verify_all` 根本没在查这件事
    （判据真空）。这里直接把改前形态写回库里，证明那条判据真的会响。
    """
    from agentflow.runflow import ARTIFACTS
    from agentflow.verify import verify_all

    _run(store, tmp_path, "a", now=TS1)
    row = dict(store.rows("tasks")[0])
    row["artifacts"] = S.sorted_unique([str(a) for a in ARTIFACTS])
    with store.tx("tasks", actor="probe", note="R5-F3 负控") as tx:
        tx.upsert("tasks", row)
    codes = [i.code for i in verify_all(store).issues]
    assert codes.count("unknown_artifact_kind") >= len(ARTIFACTS), codes


# ============================================================ `R5-F4`（status 可达性）


def test_the_verdict_covers_every_reason_run_topic_can_produce() -> None:
    """`R5-F4` 正控：`_run_task_verdict` 必须对真实理由词表给出三档内的结论。

    改前这里有两个谎：`failed` 一档不可达（旧实现只认字面量 `"error"`，而
    `run_topic` 赋给 `reason` 的是 `reply.error_kind`），以及一段
    `if reason in (…): pass` 的空块（看起来在分档、实际什么都没做）。
    判据分两半：每个真实理由都落 `TASK_STATUSES` 里的一档；
    "查过了、确实不行"的模型错误码必须落 `failed`，而"没查成"那一档落 `done`。
    """
    from agentflow import runflow as RF
    from agentflow.modelgw import MODEL_ERROR_KINDS, NOT_CHECKED

    reasons = (set(MODEL_ERROR_KINDS) | set(RF.RUN_TOPIC_REASON_LITERALS)
               | {"cancelled", "error", "一个谁也不认识的结局"})
    assert len(reasons) > 5, "词表空了 —— 这条判据没有输入（真空通过）"
    for r in sorted(reasons):
        status, outcome = RF._run_task_verdict(reason=r, exit_code=1)
        assert status in RF.TASK_STATUSES, (r, status)
        assert outcome in {"ok", "no_result", "failed", "cancelled"}, (r, outcome)

    hard = [r for r in MODEL_ERROR_KINDS if r not in NOT_CHECKED]
    assert hard, "`MODEL_ERROR_KINDS` 里必须至少有一个『查过了、确实不行』的码"
    for r in hard:
        assert RF._run_task_verdict(reason=r, exit_code=1) == ("failed", "failed"), r
    for r in sorted(NOT_CHECKED):
        assert RF._run_task_verdict(reason=r, exit_code=2)[0] == "done", r
    # `cancelled` 只对将来接进取消面的调用方成立 —— `run_topic` 不产出它
    assert "cancelled" not in RF.RUN_TOPIC_REASON_LITERALS


def test_run_topic_reason_literals_are_declared() -> None:
    """`R5-F4` 负控（判据自己守自己）：`run_topic` 里新加的 `reason = "…"` 必须登记。

    没有这一条，`RUN_TOPIC_REASON_LITERALS` 会随时间烂成一句过期的注释，
    而"某个结局在我没分档的情况下悄悄落进 done/no_result"正是这条要防的形态。
    """
    import ast
    import pathlib

    from agentflow import runflow as RF

    src = pathlib.Path(RF.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _body_of(name: str) -> ast.FunctionDef | None:
        return next((n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == name), None)

    fn = _body_of("run_topic")
    assert fn is not None, "找不到 `run_topic` —— 判据的落点变了"
    # `T-7` 之后 `run_topic` 的函数体按段搬进了 `_phase_*`（只搬位置、不改语义）。
    # 扫描面必须跟着搬：只扫 `run_topic` 的话，这条判据会以"一个都没扫到"的方式
    # 真空通过 —— 拆分当天就是这么红的，下面那句 `assert assigned` 抓住了它。
    # 取法：`run_topic` 的函数体 + 它在函数体里直接按名字调用的模块级函数。
    holders: list[ast.FunctionDef] = [fn]
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        callee = _body_of(node.func.id)
        if callee is not None and callee is not fn and callee not in holders:
            holders.append(callee)

    def _literals(expr: ast.AST) -> set[str]:
        """一个赋值右侧"结果可能是哪些字符串"。

        只跟着会原样成为结果的形状走（常量 / 三元 / `or` 链），
        不 `ast.walk` 整棵子树 —— 后者会把 `evidence["status"]` 里的 `"status"`
        也算成理由（第一版就是这么误报的）。
        """
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}
        if isinstance(expr, ast.IfExp):
            return _literals(expr.body) | _literals(expr.orelse)
        if isinstance(expr, ast.BoolOp):
            out: set[str] = set()
            for v in expr.values:
                out |= _literals(v)
            return out
        return set()

    assigned: set[str] = set()
    for holder in holders:
        for node in ast.walk(holder):
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "reason" for t in node.targets):
                continue
            assigned |= _literals(node.value)
    assert assigned, "一个 `reason = \"…\"` 都没扫到 ⇒ 扫描器没接上（真空通过）"
    assert assigned == set(RF.RUN_TOPIC_REASON_LITERALS), (
        f"`run_topic` 赋给 reason 的字面量 {sorted(assigned)} 与声明的 "
        f"{sorted(RF.RUN_TOPIC_REASON_LITERALS)} 不一致 —— "
        "新加的结局必须同时在 `_run_task_verdict` 里分档（`R5-F4`）"
    )


# ============================================================ `R5-F5`（幂等键残余）


def _run_topic(store: Store, tmp_path: pathlib.Path, name: str, topic: str,
               *, now: str | None, budget: float = 1.0) -> dict:
    text = f"- 阿贝尔群是交换群 || {ABSTRACT}\n"
    return run_topic(
        store, topic=topic, budget_usd=float(budget), out_dir=tmp_path / name,
        transport=_transport(text), spec=ModelSpec(api_key="selftest-key"),
        max_calls=1, search_fn=_search, now=now,
    )


def test_default_path_runs_in_the_same_second_are_not_deduped(
        monkeypatch, store: Store, tmp_path: pathlib.Path) -> None:
    """`R5-F5` 负控（核心）：生产形态（不给 `now`）同一秒跑两次 ⇒ 两次都记账。

    改前运行标识只由「主题 + `now`」决定，而 `S.now_iso()` 是秒粒度 ⇒
    同一秒内两次真运行撞同一个幂等键，第二次真发出去的请求在账上不存在
    （重审实测：`usage_ledger` 只有 1 行、`per_call` 全是 duplicate）。
    这里把时钟钉死在同一个秒上，正是那个形态。
    """
    monkeypatch.setattr(S, "now_iso", lambda: TS1, raising=True)
    first = _run_topic(store, tmp_path, "a", "同一个主题", now=None)
    second = _run_topic(store, tmp_path, "b", "同一个主题", now=None)

    rows = store.rows("usage_ledger")
    assert len(rows) == 2, (
        f"同一秒的两次生产形态运行共应有 2 条账本行，实际 {len(rows)} 条："
        f"{[(r['task_id'], r['idem_key']) for r in rows]}"
    )
    assert len({r["idem_key"] for r in rows}) == 2, rows
    cost2 = json.loads((tmp_path / "b" / "cost.json").read_text(encoding="utf-8"))
    assert all(c["charged"] is True for c in cost2["per_call"]), cost2["per_call"]
    assert first["spent_usd"] > 0 and second["spent_usd"] > 0


def test_topics_sharing_a_100_char_prefix_are_not_deduped(store: Store,
                                                          tmp_path: pathlib.Path) -> None:
    """`R5-F5` 负控 2：两个前 100 字相同、后缀不同的主题不许互判重放。

    改前运行标识取 `topic[:100]` ⇒ 两个不同的主题在同一个 `now` 下算出同一个键，
    第二个被整轮判 `duplicate`。不同的主题本来就该是不同的逻辑运行。
    """
    prefix = "同一个主题" * 25           # 125 字，远超 `topic[:100]`
    assert prefix[:100] == (prefix + "-甲")[:100] == (prefix + "-乙")[:100]
    first = _run_topic(store, tmp_path, "a", prefix + "-甲", now=TS1)
    second = _run_topic(store, tmp_path, "b", prefix + "-乙", now=TS1)

    rows = store.rows("usage_ledger")
    assert len(rows) == 2, (
        f"两个不同主题在同一 now 下共应有 2 条账本行（截断撞键的形态），实际 {len(rows)} 条："
        f"{[(r['task_id'], r['idem_key']) for r in rows]}"
    )
    cost2 = json.loads((tmp_path / "b" / "cost.json").read_text(encoding="utf-8"))
    assert all(c["charged"] is True for c in cost2["per_call"]), cost2["per_call"]
    assert first["exit_code"] == 0 and second["exit_code"] == 0


def test_the_same_topic_with_the_same_explicit_now_is_still_deduped(
        store: Store, tmp_path: pathlib.Path) -> None:
    """正控（不许扩大化）：显式给同一个 `now` ⇒ 仍然算"同一次逻辑运行"。

    这条与上面两条是同一个取舍的两面：显式 `now` 是调用方在声明"这是同一次逻辑
    运行"（复现、判据都靠它），默认路径才是"每一次调用都是一次独立运行"。
    没有这一条，"把幂等键做成永远不重"也能让上面两条通过 ——
    而那会把 `G-2` 想保住的那件事（同一次逻辑运行不重复扣费）一起删掉。
    """
    _run_topic(store, tmp_path, "a", "同一个主题", now=TS1)
    _run_topic(store, tmp_path, "b", "同一个主题", now=TS1)
    rows = store.rows("usage_ledger")
    assert len(rows) == 1, (
        f"显式同一个 now 的第二次运行应认出是重放（`G-2` 契约），实际 {len(rows)} 条"
    )
    cost2 = json.loads((tmp_path / "b" / "cost.json").read_text(encoding="utf-8"))
    assert cost2["per_call"][0]["reason"] == "duplicate", cost2["per_call"]
    assert cost2["per_call"][0]["charged"] is False, cost2["per_call"]


def test_the_replay_path_still_reports_a_scope_per_call(store: Store,
                                                        tmp_path: pathlib.Path) -> None:
    """`R5-AN-2` 正控（核心）：重放路径上逐笔的归口也必须看得见。

    改前 `charge_reply` 的四条返回分支里，只有无锁快速通道那条 duplicate 分支
    没有 `scope`（另外三支都有）⇒ 重放那一跑的 `cost.json` 里
    `per_call[].scope` 是空串。G-20 的承诺是"逐笔看得见归口，汇总才对得上账"，
    而这条承诺在重放路径上是空的；套件看不见它，因为唯一断言逐笔 scope 的用例
    （`test_usage_scope_attribution.py`）跑的是一次全新运行。

    判据同时钉住两件事：四支返回同形（`scope` 这个键恒在场），
    且重放那一笔的归口取自账本（与首次那一笔相同），不是空串。
    """
    from agentflow.runflow import SCOPE_ANSWER

    _run_topic(store, tmp_path, "a", "同一个主题", now=TS1)
    _run_topic(store, tmp_path, "b", "同一个主题", now=TS1)
    cost2 = json.loads((tmp_path / "b" / "cost.json").read_text(encoding="utf-8"))
    per_call = cost2["per_call"]
    assert per_call and per_call[0]["reason"] == "duplicate", per_call
    for c in per_call:
        assert "scope" in c, f"重放路径的返回缺 scope 键（四支必须同形）：{c}"
        assert c["scope"] == SCOPE_ANSWER, (
            f"重放路径上逐笔的归口成了 {c['scope']!r} ⇒ G-20 的承诺在这条路径上是空的"
        )


def test_the_replay_path_is_not_reported_as_a_reconciliation_failure(
        store: Store, tmp_path: pathlib.Path) -> None:
    """`R5-AN-3` 正控（核心）：正常重放不许被判成"账本对不上"。

    改前 `calls_usd` 把 records 里每一笔的 `usd` 都加起来，而重放那一笔的 `usd`
    是继承自上一次运行的（duplicate 分支返回 prior 行的 usd），本次真实增量
    是 0 ⇒ 一次完全正常、被刻意支持的重放被自检位判成对账失败
    （实测读数：`spent_usd_this_run=0.0` 而 `calls_usd` 是那一次调用的价，`reconciled=False`）。
    自检位在正常操作上翻红就等于它失去区分力。

    判据只钉"重放 ⇒ 0 == 0"这一半；另一半（真漏账必须报红）由
    `test_the_reconciliation_flag_still_catches_a_real_gap` 守。
    """
    _run_topic(store, tmp_path, "a", "同一个主题", now=TS1)
    _run_topic(store, tmp_path, "b", "同一个主题", now=TS1)
    cost2 = json.loads((tmp_path / "b" / "cost.json").read_text(encoding="utf-8"))
    assert cost2["per_call"][0]["charged"] is False, cost2["per_call"]
    assert cost2["calls_usd"] == 0, (
        f"重放这一跑没有任何一条调用真的入账 ⇒ calls_usd 必须是 0：{cost2['calls_usd']}"
    )
    assert cost2["spent_usd_this_run"] == 0, cost2["spent_usd_this_run"]
    assert cost2["reconciled_with_usage_ledger"] is True, (
        "正常重放被判成对账失败 ⇒ 这个自检位在正常操作上就翻红，失去区分力"
    )


def test_the_reconciliation_flag_still_catches_a_real_gap(monkeypatch, store: Store,
                                                          tmp_path: pathlib.Path) -> None:
    """`R5-AN-3` 负控（不许扩大化）：真的漏账时那个自检位必须变红。

    没有这一条，"永远报 reconciled=True"也能让上面那条通过 ——
    而那样一来这个位就成了一句恒真的话。
    造法：让 `charge_reply` 返回 `charged=True` 但 `usd=0`，而账本照旧记钱
    （真漏账的形态：调用入账了，产物里的逐次相加却看不见它）。
    """
    from agentflow import modelcost as MC

    real = MC.charge_reply

    def _gap(meter, reply, **kw):
        out = real(meter, reply, **kw)
        return {**out, "usd": 0.0}

    monkeypatch.setattr(MC, "charge_reply", _gap, raising=True)
    import agentflow.runflow as RF

    monkeypatch.setattr(RF, "charge_reply", _gap, raising=True)
    _run_topic(store, tmp_path, "a", "同一个主题", now=TS1)
    cost = json.loads((tmp_path / "a" / "cost.json").read_text(encoding="utf-8"))
    assert cost["per_call"][0]["charged"] is True, cost["per_call"]
    assert cost["calls_usd"] == 0 and cost["spent_usd_this_run"] > 0, cost
    assert cost["reconciled_with_usage_ledger"] is False, (
        "有一条调用入了账、逐次相加却在产物里看不见它 —— 这个位必须报红"
    )


# ============================================================ `R5-F6`（settle 失败可见）


def test_a_failed_settle_is_visible_in_the_manifest(monkeypatch, store: Store,
                                                    tmp_path: pathlib.Path) -> None:
    """`R5-F6` 负控（核心）：`tasks` 那一行写不成终态时，产物里必须看得见。

    改前 `_settle_run_task` 的返回值从未被读过，而它的 docstring 说写失败
    "会被记进 detail 并让这一项在返回值里可见" —— 两件都不成立：写失败恰恰
    意味着那一行 `tasks` 不在，于是连 `detail` 都留不下来，消费者完全看不出来。
    注入的是 `store.tx("tasks")`（不是把整个函数换掉）：被测对象就是
    "那一笔写入失败之后会发生什么"。

    `R5-AN-1` 之后这一条的判据变了（见模块 docstring）：占位行在开跑时
    已经落库，所以"settle 失败"不再等于"表里 0 行"，而是等于
    "那一行仍是 `running`、字段一个都没被改写"。这个新口径比旧口径强：
    它同时证明"占位行没有被失败的那次写入污染"。

    这是真负控：把 `_settle_run_task` 里的改写改回"不写"（注入本身），
    断言就必须红 —— 因为那时表里连占位行都不会有（改前形态表里是 0 行），
    而这条用例的两条断言（有那一行、且它是 running）都会落空。
    """
    real_tx = store.tx
    state: dict = {"rows": None}
    injected: dict = {"fired": False}

    @contextlib.contextmanager
    def _boom(*tables, **kw):
        if "tasks" in tables and injected["fired"]:
            # 取号那一次已经过去了 ⇒ 这一笔就是收工时的终态改写。
            raise RuntimeError("注入：tasks 写不进去（磁盘满 / 校验拒了都长这样）")
        # 其余情况跑真的 tx。占位行那一次跑完之后把盘上的行记下来，
        # 作为"收工失败之后这一行该是什么样"的对照物。
        with real_tx(*tables, **kw) as tx:
            yield tx
        if "tasks" in tables and not injected["fired"]:
            state["rows"] = [dict(r) for r in store.rows("tasks")]
            injected["fired"] = True

    monkeypatch.setattr(store, "tx", _boom, raising=True)
    out = _run(store, tmp_path, "a", now=TS1)
    assert out["exit_code"] in (0, 2), "settle 失败不许改退出码（产物已经落盘）"

    assert injected["fired"] is True, "注入没生效：收工时的 tasks 写入根本没发生"
    assert state["rows"], "注入没生效：连占位行都没写进去，那这条用例测的不是它"
    tasks = store.rows("tasks")
    assert len(tasks) == 1, f"占位行必须还在（没被失败的那次写入动过）：{tasks}"
    row = tasks[0]
    assert row["status"] == "running", (
        f"失败的 settle 不许把这一行写成终态，实际 status={row['status']!r}：{row}"
    )
    assert row.get("ended_at") is None, row
    assert int(row["tokens"]) == 0 and float(row["usd"]) == 0.0, row
    # 逐字段比对：盘上的行与"取号那一刻的行"必须逐字节相同（没有被改写）。
    assert dict(row) == state["rows"][0], (
        f"占位行被改写了：\n改前 {state['rows'][0]}\n改后 {row}"
    )

    man = json.loads((tmp_path / "a" / "run-manifest.json").read_text(encoding="utf-8"))
    assert man["task_row"]["written"] is False, man["task_row"]
    assert "注入" in man["task_row"]["error"], man["task_row"]
    # 产物里报的那个 task_id 必须就是占位行那个 —— 否则"挂点缺失"说的不是这一行。
    assert man["task_row"]["task_id"] == row["task_id"], (man["task_row"], row)
    assert any("tasks" in u and "没写成" in u for u in man["unknowns"]), man["unknowns"]


def test_a_small_budget_ignores_the_workspaces_history(store: Store,
                                                       tmp_path: pathlib.Path) -> None:
    """`G-4` 回归：额度是"这一次运行"的，工作区里已经花掉的钱不许提前熔断它。

    工作区里先有一笔别的花销（模拟"这个工作区已经用了很久"），再跑一次
    `budget_usd=一次调用的价`（现算，见 `_one_call_usd()`；远小于那笔历史花销）
    且 `max_calls=2` 的运行：第一次调用必须真的发出去；第二次调用之前的熔断
    才该停下它（`stopped_by == "budget"`、`reason == "budget_exhausted"`）。

    `F5-FOUND-1` 之后这条判据的实现口径是"按 `task_id` 过滤账本"；
    改前是"开跑时的账本基线 + 工作区增量"。两种口径在不可重叠的场景下
    给出同一个答案，所以这条用例对两种实现都是绿的 —— 它守的是口径的
    意图（额度是本次运行的）。并发下的差别由
    `test_two_concurrent_runs_never_share_a_task_id` 里那几条
    `spent_usd_this_run` 断言守。

    注意 `budget_exhausted` 这一位是"熔断器是否响过"，由 `stopped_by` 权威表达：
    额度小到连一次调用都盖不住时，第一次调用照发（金额是调用粒度，不能再切），
    跑完看账面当然超了 —— 那时 `reason == "success"`、`stopped_by == "max_calls"`。
    这里刻意不用那种"额度小于单次价"的输入去判熔断。
    """
    from agentflow.modelcost import charge_reply
    from agentflow.modelgw import ModelReply
    from agentflow.tokenmeter import TokenMeter

    # 工作区里先记一笔"历史花销"（另一个 task 的账；价目表现算，量级见下面的断言）。
    hist = TokenMeter(store, budget_usd=100.0)
    charge_reply(hist, ModelReply(ok=True, text="4", tokens_in=1_000_000,
                                  tokens_out=1_000_000, attempts=1, model="m",
                                  scope="reason"),
                 task_id="t-9999", call_index=0, scope="reason", now=TS1)

    text = f"- 阿贝尔群是交换群 || {ABSTRACT}\n"
    res = run_topic(
        store, topic="同一个主题", budget_usd=_one_call_usd(), out_dir=tmp_path / "tiny",
        transport=_transport(text), spec=ModelSpec(api_key="selftest-key"),
        max_calls=2, search_fn=_search, now=TS1,
    )
    cost = json.loads((tmp_path / "tiny" / "cost.json").read_text(encoding="utf-8"))
    assert res["calls"] == 1, (
        f"历史花销不许提前熔断这一次运行：它应当发出第一次调用（{_one_call_usd()} = 额度），"
        f"第二次之前才停（实际 calls={res['calls']}）"
    )
    assert res["reason"] == "budget_exhausted", (
        f"第二次调用之前的熔断必须被记成 budget 熔断：{res['reason']}"
    )
    assert cost["calls_usd"] == cost["spent_usd_this_run"] == _one_call_usd(), cost
    assert cost["usage_ledger"]["usd"] > 10 * cost["spent_usd_this_run"], (
        "账本累计必须同时给出，而且它比本次运行大得多 —— 这才是两个口径的分辨点"
    )


def test_the_task_row_survives_a_rebuild_byte_for_byte(store: Store,
                                                       tmp_path: pathlib.Path) -> None:
    """`I-9` 回归：跑一次之后 `rebuild()` 必须逐字节重现 `tasks.json`。

    为什么 `R5-AN-1` 必须带这一条：那一行现在是"开跑写占位行、收工整行改写"
    两次写，而快照按 dict 的键顺序序列化、`rebuild()` 用 `Task.to_dict()` 重建。
    两次写的字段集合或键顺序只要不一致，`tasks.json` 在 `rebuild()` 之后
    就逐字节不同 —— 数据一个字段都没错，但"可重建"这条承诺破了，
    而且没有任何判据会响。

    本批实测踩到过：占位行第一版是手工列的十五个字段（少了
    `parent_task_id` / `refusal_reason` / `error`），盘上是 1091 字节、
    rebuild 之后 1172 字节（读数 `temp/fix6_f5-shape.txt`）。
    现在两处都走 `_new_task_row`（内部 `Task.to_dict()`），相等由构造保证。
    """
    _run(store, tmp_path, "a", now=TS1)
    before = (store.data / "tasks.json").read_bytes()
    assert f"t-{S.format_id(1)}".encode() in before, "前置条件没建立：盘上那一行没写出来"
    store.rebuild()
    after = (store.data / "tasks.json").read_bytes()
    assert before == after, (
        f"rebuild 之后 tasks.json 变了（{len(before)} -> {len(after)} 字节）——"
        "两次写的字段集合或键顺序不一致（I-9）"
    )


def test_the_settle_signature_and_docstring_agree_with_the_implementation() -> None:
    """`R5-AN-5`：`_settle_run_task` 的接口面（签名 + docstring）必须说真话。

    改前两处都不是真话（读数 `temp/reaudit6-R5-p4.txt`）：

    - docstring 的六条口径清单里写着 `artifacts` 是"本运行承诺的六件产物"，
      而同一屏的实现是 `artifacts=[]`（`R5-F3` 已经改掉的旧形态）——
      照那句 docstring 写回去会立刻新增 6 条 `unknown_artifact_kind` warning；
    - 两个形参 `out` / `ledger` 在函数体里从未被使用，而 docstring 把它们
      当契约在列 —— 形参也是接口面，列着不用会让读的人以为
      "产物目录与账本汇总参与了这一行的构造"。

    判据取两半：签名里不许有未被使用的形参（按 AST 逐形参核）；
    docstring 与 `artifacts` 有关的那一条必须说的是"留空 + 名字进 detail"。
    负控见 `temp/fix6_f5-neg-V5-an5-old-doc.txt` 与 `-V5b-an5-params.txt`。

    判据读的源码路径从 `__file__` 推（不从 `inspect.getsourcefile` 或
    `agentflow.__file__` 推）：`sys.path` 上可能有另一份 `agentflow`
    （负控就是在整树副本上跑的），而 `linecache` 按键缓存 —— 一旦缓存了
    另一份的路径，`inspect.getsource` 就可能去读一个不存在的文件，
    那会让这条判据在任何变体上都红（假红比假绿更难查）。
    """
    import ast

    src_path = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "runflow.py"
    assert src_path.is_file(), f"判据的落点不对（找不到 {src_path}）"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "_settle_run_task"), None)
    assert node is not None, "找不到 `_settle_run_task` —— 判据的落点变了"

    body_names = {n.id for n in ast.walk(node)
                  if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    args = [a.arg for a in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
    unused = [a for a in args if a not in body_names and a != "store"]
    assert args, "没扫到形参 ⇒ 扫描器没接上（真空通过）"
    assert unused == [], (
        f"`_settle_run_task` 有从未被使用的形参 {unused} —— 形参是接口面，"
        "列着不用会让读 docstring 的人以为它参与了构造"
    )

    doc = ast.get_docstring(node) or ""
    assert "artifacts" in doc, "docstring 里必须仍有一条 `artifacts` 的说明"
    assert "本运行承诺的六件产物" not in doc, (
        "这句是 `R5-F3` 已经判为缺陷、并改掉的旧形态（六个文件名会新增 6 条 "
        "`unknown_artifact_kind` warning）—— docstring 不许再这么写"
    )


def test_a_model_side_failure_lands_as_a_failed_task_row(store: Store,
                                                        tmp_path: pathlib.Path) -> None:
    """正控（`FINAL-R5-01`，最后一次集中审查抓到的那条）：模型侧"查过了、确实不行"
    的结局必须真的写进 `tasks` 行，而不是把占位行永远留在 `running`。

    改前 `_new_task_row` 从不设 `error`，而 `schema.Task.validate` 要求
    `status="failed"` 必须带非空 `error` 且 `outcome="failed"` ⇒ 收工那次
    `validate` 抛异常、`written=False`，占位行停在 `running`。
    受害面逐字是 `modelgw.MODEL_ERROR_KINDS` 里不在 `NOT_CHECKED` 的那三个码
    （`auth_failed` / `rate_limited` / `bad_response`）—— 也就是说
    "模型侧确实失败了"这一类在台账上根本不可达。

    为什么这条改前不会被现有用例抓住：`test_the_verdict_covers_every_reason_run_topic_can_produce`
    只断言 `_run_task_verdict` 这个纯映射函数的返回值，而缺陷在
    "把返回值写进行"这一步 —— 映射对、写入失败。

    这一条走的是真路径（401 的 transport ⇒ `reply.error_kind="auth_failed"`
    ⇒ `reason` 落进 `MODEL_ERROR_KINDS`），不是直接调私有函数。
    """

    def _transport_401(url: str, headers: dict, data: bytes,  # noqa: ARG001
                       timeout_sec: float):
        return 401, json.dumps({"error": {"message": "invalid api key"}})

    res = run_topic(
        store, topic="同一个主题", budget_usd=1.0, out_dir=tmp_path / "fail",
        transport=_transport_401, spec=ModelSpec(api_key="selftest-key", max_retries=0),
        max_calls=1, search_fn=_search, now=TS1,
    )
    man = json.loads((tmp_path / "fail" / "run-manifest.json").read_text(encoding="utf-8"))
    # 退出码 1 = "查过了、有问题"（`auth_failed` 不在 `NOT_CHECKED` 里 ⇒ 不是 2）。
    assert res["exit_code"] == 1 and res["reason"] == "auth_failed", res
    assert man["task_row"]["written"] is True, man["task_row"]

    rows = store.rows("tasks")
    assert len(rows) == 1, rows
    row = rows[0]
    # 三件事一起钉：终态、outcome、非空的 error（缺任何一条 validate 都会拒）。
    assert row["status"] == "failed", row
    assert row["outcome"] == "failed", row
    assert str(row["error"] or "").strip(), row
    assert row["ended_at"], row

    # 负控（本条的装置自控）：把 error 去掉再走一次同样的写入路径，必须当场被拒
    # —— 否则"补上 error"这件事只是装饰，判据没有牙。
    with pytest.raises(ValueError):
        S.Task(**{**row, "error": None}).validate()


def test_the_settle_success_is_also_visible(store: Store, tmp_path: pathlib.Path) -> None:
    """正控（不许扩大化）：写成功时 `task_row.written` 必须是 `True`、`error` 空。

    没有这一条，"永远写 False"也能让上面那条通过，而那样会把每一次正常运行
    都报成"账本挂点缺失"。
    """
    _run(store, tmp_path, "a", now=TS1)
    man = json.loads((tmp_path / "a" / "run-manifest.json").read_text(encoding="utf-8"))
    assert man["task_row"]["written"] is True, man["task_row"]
    assert man["task_row"]["error"] == "", man["task_row"]
    assert len(store.rows("tasks")) == 1
    assert not any("没写成" in u for u in man["unknowns"]), man["unknowns"]


# ============================================================ `R5-AN-4`（过期引用）
#: `R5-AN-4` 实测已经指错地方的四处引用（逐字取自审计读数
#: `temp/reaudit6-R5-p4.txt`）。判据是"这些字符串不许再出现在本批的四个文件里"：
#: 它们指向的行分别是撤回语义的注释、一个空行、一段 sleep 说明与一行 `for`。
#: 换成符号名（`verify.verify_all` / `interactions.next_prefixed_id` /
#: `store.MAX_ID` / 用例里的 `is_valid_id` 断言）之后，行号漂移不再影响引用
#: —— 与 `AGENTS.md` 自己的约定一致（"理由里写符号名、刻意不写行号，因为行号易失"）。
#:
#: 为什么不写一条"扫全仓 `\\w+\\.py:\\d+` 并解析每一处"的通用判据：全仓仍有
#: 三十余处这种引用，其中多数指向的是别处的文档或设计稿（`draft/`、参考实现），
#: 拿一条通用判据去判它们只会造出一盏靠别人改文件才能变绿的灯。这里只钉本批
#: 已经实测指错的那四处 —— 判据的范围与它的证据范围一致。
_STALE_REFS = (
    ("agentflow/conductor.py", "verify.py:708-713"),
    ("agentflow/tools/table_tools.py", "interactions.py:1134"),
    ("agentflow/tools/table_tools.py", "store.py:52-53"),
    ("agentflow/tools/table_tools.py", "tests/test_agent_c_service.py:637"),
)


# ============================================================ 引用型缺陷的机械判据
# `R7-R5-1` / `R7-R5-2` / `R7-R5-3` 同形（引用了不存在的东西）⇒ 根因是"注释与 docstring 里的引用没人核"，所以落一条机械判据。口径（抄第 7 轮审计者那台探针 `temp/reaudit7-R5-p3.py`）：
# ① 只取反引号包着的私有符号名（下划线 + 字母开头，裸写不算）；② 该 token 作为真符号（`.py` 的 `NAME` 记号，不含注释 / docstring / 字符串 / `.md` 正文）出现 ≤ 1 次 ⇒ 悬空；③ 路径只取 `temp/...` 形态。
# ② 为何按符号面数而非文本面（`R5-AN-10-1`）：按文本数时，在本文件里随手写下那个 token 就能把计数从 1 抬到 2 ⇒ 真悬空被"治好"、判据安静变绿（第 10 轮 `symbCrit` 档实测 passed）。
# 换面后"只有文本提及"的那些逐条登记进 `_REF_KNOWN_MENTION_TOKENS`，与仓里读数逐条等额（多一个、少一个都红）——登记是一条会被 review 的 diff，不是放宽口径。
# 记号豁免：与引用同一行写逐字三个汉字 `非指代` 才跳过，且该文件必须落在 `_REF_EXEMPTED_EXPECTED_FILES`（豁免是暗门，放行要留可见登记）；死活由 `test_the_reference_exemption_marker_is_alive` 独立判（全仓零豁免 ⇒ 报"机制死了"）。
# 范围按第 8 轮那台宽扫（`temp/REAUDIT8-R5.json` / `temp/reaudit8-R5-p8.py`）扩到整棵树：报出的范围必须与扫过的范围同宽（`F9`）。
# 本判据只判"树里有没有这个标识符"，不判"这个名字绑定了什么"：它管的是设计时那一类（只有注释在说它）。
_REF_SCAN_SUFFIXES = (".py", ".md")
#: 不参与体检的目录：`__pycache__` / `.pytest_cache` / `.git` / `.mypy_cache` / `projects` / `out` / `node_modules`。
#: `projects` 与 `out` 是未跟踪的运行产物（各次真机的工作区与探针产物），不随仓提交、每跑一次就变一次：
#: 2026-10-05 实测 p6e 工作区里 M 自己写的 `out/review/REPORT.md` 引了两个它打算写而没写的脚本
#: ⇒ 一次运行产物把判据点红，那是假报警（判据守的是仓里的引用，不是模型在运行期写下的每句话）。
#: `node_modules` 是 2026-10-07 补的（Web 端 W0 引入 Vite 之后）：`pnpm install` 的安装结果，实测
#: 1.2 万个文件、`.gitignore` §4b 明确排除（入库的是 `ui/pnpm-lock.yaml`）；不排除要白读这些文件，
#: 而且第三方 README 里下划线开头的 token 写成反引号形态就会被当成"我们引用的私有符号"（假报警）。
#: 排除的是"安装结果"，不是"我们写的前端源码"：`ui/src/**`、`ui/*.json`、`ui/*.ts` 照旧全扫。
_REF_SCAN_SKIP_DIRS = ("__pycache__", ".pytest_cache", ".git", ".mypy_cache",
                       "projects", "out", "node_modules")
#: 只对"真符号出现次数"那一维（口径第 2 条）排除的目录（`R7-⑮` 的窄修）。
#:
#: 为什么不把它并进 `_REF_SCAN_SKIP_DIRS`：那会把 temp 前缀路径的存在性那一族
#: 连同它里面的悬空提及一起废掉 —— 而那一族是有用的（`temp/_r009_fix.py`
#: 这类一次脚本的引用真的该存在）。本批只治一个病：未跟踪的 scratch 能抬高计数
#: （`R0-C2` 实测：`temp/` 下一份整树副本让每个 token 的"真符号出现次数"翻倍
#: ⇒ 一条真悬空的引用被判成不悬空 ⇒ 判据安静变绿）。
#:
#: 为什么按相对被扫树的第一段判，而不是用 `p.parts`：机制守卫
#: （`_probe_tree_copy`）把整树副本落在工作区 `temp/` 下再扫那份副本 ——
#: 用绝对路径判会把整个副本排除掉，副本读数与真树当场不同，
#: 那条负控（"副本读数必须与真树逐字相同"）就会失效。
#: 负控 = `test_a_scratch_copy_cannot_cure_a_dangling_reference`。
_REF_SYMBOL_COUNT_SKIP_DIRS = ("temp",)


def _symbol_count_skipped(p: pathlib.Path, tree: pathlib.Path) -> bool:
    """这个文件要不要从"真符号出现次数"那一维里排除（见上一条常量）。"""
    try:
        rel = p.relative_to(tree)
    except ValueError:  # 不在被扫树里（理论上不会发生）⇒ 不排除，宁可多算
        return False
    return bool(rel.parts) and rel.parts[0] in _REF_SYMBOL_COUNT_SKIP_DIRS
#: 豁免记号，逐字三个汉字。`test_the_quoted_references_in_comments_all_exist` 的
#: docstring 里必须原样出现它，且那条规定由 `..._marker_is_alive` 断言。
_REF_EXEMPT_MARK = "非指代"
#: 允许带记号跳过的引用落在哪些文件里（`F9` 实测的两处，逐条登记）。
#:
#: 为什么用一张显式的表而不是"带记号就放行"：后者是一条可以随时增宽的暗门 ——
#: 下一个人只要在悬空引用后面补三个字就能让它变绿。有了这张表，新豁免必须改这个
#: 文件（一次可见的、会被 review 的动作），而"表里的文件少了一条"也会当场变红。
_REF_EXEMPTED_EXPECTED_FILES = (
    "tests/test_core_audit_efgh.py",   # 历史叙述：修之前的旧装配点名
    "scripts/noai_gate.py",            # 示意性引用：路径词法归一的举例
)
#: 判据（引用读数）已知的"非符号提及"：这些反引号私有 token 在整棵树里
#: 没有（或只有一个）真符号出现点，但那处引用是正当的 —— 它说的是
#: 字符串形式的字典键、被删/改名之前的历史名字、测试/命名约定的片段，
#: 或"存活但已无调用点的方法"（退场后被保留的实现；代理口径对它必然误报，登记是让它如实）。
#:
#: 为什么需要这张表：口径第 2 条按真符号计数（见上面那段注释块），
#: 而 base 上有一批 token 本来就只有文本提及。不放宽它（放回去就是第 10 轮那个
#: 假绿），改成"逐条登记"：登记是"这条引用的意思是被记下来的"，不是"这条引用不用管"。
#: 登记必须落在这个文件里 ⇒ 一次可见的、会被 review 的 diff。
#:
#: 等额纪律（`test_the_quoted_references_in_comments_all_exist` 的第二条断言）：
#: 仓里出现的"非符号提及"集合必须与这张表逐条相等 —— 多一个（有人新写了一条
#: 没有解释的提及）红，少一个（登记已经过期）也红。两个方向都留痕。
#: 每条后面的括注是它属于哪一类，不是逐处行号（行号易失）。
_REF_KNOWN_MENTION_TOKENS = (
    # —— 字符串形式的字典/诊断字段键：代码里以字符串字面量出现，符号面不存在 ——
    # —— 2026-10-07 Web 批：`_keys` 从本表退出（同一条等额纪律）——
    # 它原登记为"事件行诊断键（`agent_a` 写入，多处注释在解释它）"。本轮读数：
    # 它已不满足"真符号出现 ≤ 1 次"（`temp/_mention_diff.py` 按判据自己的公式算出的
    # `mentioned_only` 30 条与本表 31 条的差集恰好只有它）⇒ 按"表里过期的条目要删掉"删掉。
    # 判据本体一个字没动：仍是"仓里只有文本提及的 token 必须与这张表逐条相等"。
    "_quote_check",               # 每行诊断字段（同上：留痕叙述）
    "_merge_note",                # I5 合并改写留痕的字符串键（`agent_b/core.py` 用 `row["_merge_note"]` 写；符号面 0 次）。引用处是 `tests/test_agent_b_gates.py` 的 docstring（并表那一笔把"改写清单"的读物从老表改成 `relations` 表时写的）
    "_washed_payload",            # S1g：`_outbound_hook` 返回里承载"洗过的那一份"的字符串键（不是符号；循环取完就 pop 掉，不并进结果）
    "_lease_expired",             # 行内键（`interactions.py` 用 r.get("_lease_expired") 读）
    "_conflict_check",            # "没检查"相关字段名（同族叙述）
    "_tables_written_by_action",  # 已删函数的残骸讨论（`capabilities.py` 的记录）
    "_mark_dirty",                # 已删 helper 的残骸讨论（`draft/28` §176 删除；`table_tools.py` 的注释在解释它为什么没了）
    "_target_text",               # 负控叙述里被删掉的字段名
    "_diag",                      # 举例用的"谁都不认识的键"
    # —— 2026-10-19：`_plan` 从本表退出（同一条等额纪律，登记过期）——
    # 它原登记为"早期散文写法（今天真名是 `_plan_mode`）"，唯一的文本提及是
    # `providers.py` 里那句 ``_plan``。这一批新增的 `tests/test_closing_attack_progress.py`
    # 里有一个**真函数** `_plan`（一个 def + 六处调用 = 7 个 NAME 记号），
    # 按判据自己的口径（真符号出现 > 1 次 ⇒ 不再是"只有文本提及"）它已经不需要豁免。
    # 这不是放宽判据：口径仍是"真符号出现 ≤ 1 次的提及要逐条登记"，变的是那个 token 的
    # 真符号读数；留着它反而会被第二条断言的反向等额规则判成"登记过期"。
    "_VERIFIER_CANDIDATES",       # 已删的候选表（`draft/37` §82：探测搬到 `agentflow.toolchain`；
                                  # `docs/PROPOSAL-side-effect-axes.md` 在讲当年的 exec 定义冲突时仍引它）
    "_mismatch",                  # 旧词表里那种"`quote` 加后缀"的取值名（词表已改写法）
    "_notify_bounce",             # 存活但已无调用点的退场实现（`agent_loop.py` 的 def；`tests/test_forced_notify.py:238` 在说它不再被调用）—— 名字是真的，读的人找得到
    "_readerthread",              # CPython **标准库**内部函数（`subprocess` 的读线程）—— 不是本仓的符号，但**名字是真的**：2026-10-15 那条"只在全量跑里红"的编码缺陷，追到的最后一帧就是它抛 `UnicodeDecodeError`（`tests/test_temp_root_pin.py:123` 与 `tests/test_role_specs_complete.py` 的留痕按纪律必须点名那一帧 —— 不点名读者就不知道红在哪一层）。留痕按纪律必须点名出事的那个东西，哪怕它在标准库里
    "_shell_demo",                # R8-A-1 退场的入口处理函数（2026-10-07 删）：`cli.py` 的留痕注释在讲"这里原有它、为什么摘掉"；留痕按纪律必须点名被删的东西
    "_persist_report",            # R8-A-6 退场的旧落盘函数（2026-10-07 已在全树无符号出现）：`DEVELOPMENT.md` 与 `DESIGN-TOOLS.md` 的说明在讲"为什么要删它"
    "_notify_gate",               # 2026-10-07 改名成 `notify_reading`（旧名在说谎：它不打回）：`agent_loop.py` 里那段改名留痕必须点名旧名 —— 留痕按纪律必须点名被删/被改的东西
    "_BASE_",                     # 别名前缀（不是完整标识符）
    "_impl",                      # 被转发的名字（`lint_rules.py` 的解释）
    "_private",                   # 判据片段（不是标识符）
    "_accepts_",                  # 测试名约定片段（不是标识符）
    "_rejects_",                  # 同上
    "_real_c",                    # 测试分组名片段
    "_and_ignores_the_rest",      # 用例改名留痕
    "_KINDS",                     # 命名约定举例（schema 的注释在说"别这样起名"）
    "_STATUSES",                  # 同上
    "_OUTCOMES",                  # 同上
    "_FORMS",                     # 同上（`draft/28` §168 的 R-30 把 `_FORMS` 加进 `VOCAB_SUFFIXES`，两处注释在说这个后缀，不是符号）
    # —— 只有一个真符号出现点的（自指定义 / 别名 / 被删函数的残留）——
    "_ROLE_PAT",                  # 赋值处一次（`tools/verify_role_specs.py`）
    "_ConcurrencyProbe",          # 兼容旧名 `_ConcurrencyProbe = ConcurrencyProbe`
    "_NO_AXIOMS",                 # `import ... as _NO_AXIOMS`
    "_NAME_EVIDENCE_TEXT",        # 常量定义处一次
    "_default_search",            # 函数定义处一次
    # —— `goal-7f5116c1` M6/M7 拆包后从本表退出的两个（登记过期，按等额纪律删掉）——
    # `_declared_name_note`（`agent_e/_support.py` 定义）与 `_short`（`agent_f/_support.py`
    # 定义）本来只有一个真符号出现点；拆包后每个用到它们的动作模块都多了一行
    # `from ._support import ... _declared_name_note`，`tokenize` 数到的 NAME 记号
    # 因此变成 3 个（> 1）⇒ 它们不再是"只有文本提及"的 token，本表必须同步删掉。
    # 这不是放宽判据：口径仍是"真符号出现 ≤ 1 次的提及要逐条登记"，
    # 变的是这两个 token 的真符号数（读数：拆包后各 3 个）。
)
_TICKED_PRIVATE = re.compile(r"`(_[A-Za-z][A-Za-z0-9_]*)`")
_TICKED_TEMP_PATH = re.compile(r"`(temp/[A-Za-z0-9_.\-]+)`")
#: 第三族（`R7-㉒`）：反引号里的 `test_*.py` 文件名必须在树里（或工作区 `temp/` 下）存在。
#:
#: 真事故 22 行：`src/agentflow/agent_c/*.py`（8 个）与 `agent_d/*.py`（14 个）的第 3 行
#: 逐字引着一个从来不存在的名字（那 22 行点的是"逐字"那一版文件名，而真判据是
#: `tests/test_agent_split_is_one_action_one_file.py`；"逐字"那半只是一次性证明）。
#: 那 22 行已改真（R1 附录 2），缺的是判据：名字再写错一个字，没有任何东西会响。
#:
#: 为什么本族只咬 `test_*.py` 这一个形态（不是所有 `*.py`）：全树反引号里的 `.py` 提及
#: 实测 582 个名字、其中 57 个按后缀规则解析不到 —— 绝大多数是史实与夹具
#: （拆包前的单文件布局名、夹具里造的脚本名、讲缺陷本身的例子）。把那一整片判红、
#: 再登记 57 条，只会把登记表烂成噪音；而真事故的形态是"点名一份测试文件"。
_TICKED_TEST_FILE = re.compile(r"`([A-Za-z0-9_./\-]*test_[A-Za-z0-9_]*\.py)`")
#: 本族已知的"不存在的 test_*.py 提及"（逐条登记并写类别；多一条、少一条都红）。
_REF_KNOWN_MISSING_TEST_FILES: tuple[tuple[str, str], ...] = (
    ("tests/test_xxx.py",
     "形态示例：`test_release_all.py` 在讲「裸名字怎么解析成 tests/<name>.py」这条规则本身"),
    ("tests/test_extract.py",
     "历史真值：那一行逐字写着它已不存在（讲那份清单原来对这类引用完全没牙）"),
    ("tests/test_does_not_exist_zzz.py",
     "负控夹具里那个「点名的文件不存在」的假名字（判据要求它被报出来）"),
    ("tests/sub/test_x.py",
     "形态示例：`tools/run_each_test_file.py` 在讲「子目录形态会被逐文件门判绿」"),
)


def _python_identifiers_in_text(p: pathlib.Path, text: str) -> list[str]:
    """该文件里"算真符号"的标识符（只在 `.py` 上有；`.md` 返回空表）。

    口径（`FIX11` 的 `C2`，第 2 条；`FIX12` 的 `R5-AN-11-3` 更正了这里的实现与说法）：
    用 `tokenize` 取 `NAME` 记号 ⇒ 字符串字面量里的提及、`.md` 正文里的提及一律不算；
    再把 docstring 所在的行剔掉（那是字符串常量，同样不产生 `NAME` 记号）⇒
    "docstring 里随手写下的名字"不算。剩下的就是这个文件里真的写在代码上的名字。

    注释不需要额外剔除，也不该被剔除：注释正文本来就不是 `NAME` 记号
    —— `tokenize` 把 `# 注释里的 _foo` 整个吐成一个 `COMMENT` 记号，注释里的名字
    根本不会进 `out`。改前这里按 `COMMENT` 记号的行号去剔 `NAME`（第二遍里
    `tok.start[0] not in drop`），而那条规则剔不掉任何注释，只能把同一行上的真代码
    整行吃掉：实测整棵树被吃掉 2533 个真代码 `NAME` 记号，330 个被 tick 的 token 里
    有 14 个两种口径计数不同（`_callable_for` 2 vs 4、`_store` 13 vs 21、
    `_search` 26 vs 30）。方向是保守的（只会假红、不会假绿），但"真符号计数"这个
    口径名不副实，所以那条规则被删掉。

    为什么用 `tokenize` 而不是正则：正则会把一个更长的名字（它以 `_ROLE_PAT` 开头）
    数成 `_ROLE_PAT` 的一次命中。

    读不到（`OSError`）或记不过（`TokenError` / `IndentationError`，例如半截写坏的
    `.py`）的文件当作"没有真符号"：宁可把它当可疑，也不假装它干净。
    """
    if p.suffix != ".py":
        return []
    try:
        lines = text.splitlines()
    except Exception:  # pragma: no cover —— 只有异常文本才会走到这里
        return []
    #: 只剔 docstring 所在的行（字符串常量，不产生 `NAME`）。刻意不剔注释行：
    #: 注释正文不是 `NAME` 记号，按行剔只会连带吃掉同一行上的真代码
    #: （`FIX12` 的 `R5-AN-11-3`：改前那条规则实测吃掉整棵树 2533 个真代码记号）。
    drop: set[int] = set()
    try:
        tree: ast.Module | None = ast.parse(text)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) \
                        and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    doc = body[0]
                    drop.update(range(doc.lineno, (getattr(doc, "end_lineno", None) or doc.lineno) + 1))
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.NAME and tok.start[0] not in drop:
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        pass
    return out


def _symbol_occurrences(tree: pathlib.Path, token: str) -> int:
    """`token` 在整棵树里作为真符号出现几次（口径见 `_python_identifiers_in_text`）。

    注意：这是单查一个 token 的便利函数，它要把整棵树重读一遍（实测约 7 秒）。
    判据自己不要用它 —— `_scan_ticked_references` 在同一次遍历里就把每个 token 的
    真符号次数算好了，放在返回值的 `symbol_counts` 里；在循环里逐个调用本函数是
    O(token 数 × 整树)，实测 329 个 token 会把这条判据从 9 秒拖到 38 分钟
    （第 10 轮买到的教训：判据自己也会成为 b79 的瓶颈）。本函数只留给
    "在探针/一次性核查里查一个名字"这种用法。
    """
    total = 0
    for p in _iter_ref_scan_files(tree):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += _python_identifiers_in_text(p, text).count(token)
    return total


class _RootNotFound(Exception):
    """在仓内却认不出仓 ⇒ 判据自己坏了（`R8-R5-1`：这一档必须是 FAILED，不是 skip）。"""


#: 根锚（`X-91.5-3`）：两条都随仓走（都在 git 里）——① 工作区根（= 仓库根）的 `.gitattributes`
#: （仓根的存在证明，且清不动：`temp/` 下那类产物是未跟踪 scratch，删一次就没了）；② 交付树
#: 自己的 `agentflow/AGENTS.md`（`copytree(agentflow, …)` 会把副本一起带走 ⇒ "整树副本"那几种
#: 布局里也认得出"这是一个含 agentflow 交付树的工作区"）。
#: 必须两条同时成立：只认 ① ⇒ 任何含 `.gitattributes` 的目录都会被当成工作区根；只认 ② ⇒
#: `copytree(agentflow, <x>/agentflow)` 那种布局会把 `<x>` 认成根（它确实含 `agentflow/AGENTS.md`），
#: 而 `<x>/temp/` 里并没有那些引用 ⇒ 判据拿错的根去核 `temp/...` 的存在性、报一片假 `missing`。
#: 改前用的是 `temp/REAUDIT6-R5.json`（未跟踪产物）：`temp/` 一清就抛 `_RootNotFound`，整条引用判据从"绿"变成"判据自己坏了"。
_ROOT_MARKERS = (pathlib.Path(".gitattributes"), pathlib.Path("agentflow") / "AGENTS.md")


def _looks_like_a_checkout(tree: pathlib.Path) -> bool:
    """`tree` 自己或它的祖先里，有没有"本仓（或它的一份整树副本）"的结构。

    判据只有一条：存在某一层 `base` 使 `base/src/agentflow/runflow.py` 是文件。
    刻意不要求同层有 `temp/` —— 整树副本的形态就是 `copytree(agentflow, <x>)`
    （`<x>/src` 在下面，而 `temp/` 在外面那个工作区根），加上 `temp/` 这一条会让
    副本被判成"仓外"。这一条只用来区分"在仓里"与"不在仓里"，不承担其它语义。
    """
    return any((base / "src" / "agentflow" / "runflow.py").is_file()
               for base in (tree, *tree.parents))


def _reference_scan_roots() -> tuple[pathlib.Path, pathlib.Path] | None:
    """`(agentflow 树, 工作区根)`；判据的落点定不下来时返回 `None`（那是真的仓外）。

    ## 三种结局，不是一个

    1. 找到 → 返回 `(tree, ws_root)`；
    2. `tree` 的祖先里有 checkout 结构、但上溯到盘符根都没找到 `_ROOT_MARKERS`
       那两条 ⇒ 抛 `_RootNotFound`：那说明"我在仓里却认不出仓"，是判据自己坏了，必须 FAILED；
    3. 连 checkout 结构都没有（例如把本文件单独拷到系统临时目录）⇒ 返回 `None`，
       调用方 `pytest.skip`：那是真的 `unknown`，不是通过。

    根锚为什么必须是随仓走的两条（`X-91.5-3`）：逐字见 `_ROOT_MARKERS` 上面那段。

    ## 为什么不是固定层级（`R8-R5-1`）

    这里此前是"最多向上三级"。第 8 轮的布局矩阵实测：`<ws>/agentflow` 与
    `copytree(agentflow, <ws>/temp/<label>)` 两种布局都能找到根，但
    `<ws>/temp/<a>/<b>`（三层）与更深找不到 ⇒ 判据退化成 `pytest.skip`，
    而在 pytest 汇总行里 `skipped` 与 `passed` 一样容易被读成"这盏灯没问题"
    —— 「未知被读成通过」，正是本仓三态纪律禁止的那件事。
    现在改成上溯到盘符根（`tree.parents` 本身有界，成本可忽略），
    并把"在仓里找不到"与"不在仓里"分成上面的第 2 / 第 3 档。
    """
    tree = pathlib.Path(__file__).resolve().parents[1]
    for base in (tree, *tree.parents):
        if all((base / marker).is_file() for marker in _ROOT_MARKERS):
            return tree, base
    if _looks_like_a_checkout(tree):
        missing = " / ".join(str(m) for m in _ROOT_MARKERS)
        raise _RootNotFound(
            f"从 {tree} 上溯到盘符根都没找到随仓走的根锚（{missing}），而这一路上有本仓的 "
            "checkout 结构 ⇒ 判据认不出自己在哪（判据自己坏了，不是 unknown）"
        )
    return None


def _iter_ref_scan_files(tree: pathlib.Path) -> list[pathlib.Path]:
    """整棵树里参与体检的文件（`.py` + `.md`），排除缓存、版本控制目录与运行产物。

    运行产物（`projects/`、`out/`）为什么不扫：见 `_REF_SCAN_SKIP_DIRS` 上的那段
    （2026-10-05 真机：模型在自己的报告里引了两个它没写的脚本 ⇒ 判据被一次运行点红）。

    排序只是为了让读数是确定的 —— 同一棵树两次跑给出同一份清单。
    """
    out = [p for p in tree.rglob("*")
           if p.is_file() and p.suffix in _REF_SCAN_SUFFIXES
           and not any(part in _REF_SCAN_SKIP_DIRS for part in p.parts)]
    return sorted(out)


def test_the_ref_scan_skips_run_artifacts_but_not_the_repo(tmp_path: pathlib.Path):
    """负控（`draft/39` D27）：运行产物里的悬空引用不算数，仓内的照旧要算。

    没有这一条，"跳过 `projects/`/`out/`"就成了一条谁也不知道范围有多大的暗门：
    把整个仓塞进 `projects/` 也能让它变绿。这里两个方向都钉住。
    """
    ws = tmp_path / "projects" / "some-run"
    (ws / "out" / "review").mkdir(parents=True, exist_ok=True)
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    # 这个悬空引用是夹具：拼出来是为了不让它自己的字面量落进判据的扫描面
    # （判据扫的是文件字节，写死它等于在本文件里制造一条真悬空引用）。
    body = "见 `temp/" + "never_written" + ".py`。\n"
    (ws / "out" / "review" / "REPORT.md").write_text(body, encoding="utf-8")
    (docs / "R.md").write_text(body, encoding="utf-8")

    got = _scan_ticked_references(tmp_path, tmp_path)
    missing = " ".join(str(x) for x in got["missing"])
    assert "docs/R.md" in missing, f"仓内的悬空引用必须照旧报出来：{got['missing']}"
    assert "REPORT.md" not in missing, f"运行产物不该被扫：{got['missing']}"


def _scan_ticked_references(tree: pathlib.Path, ws_root: pathlib.Path) -> dict:
    """扫整棵树里反引号包着的引用 ⇒ 读数（键：`files` / `tokens` / `paths` /
    `dangling` / `missing` / `exempted` / `dangling_tokens` / `symbol_counts` /
    `symbol_count_files` / `symbol_count_skipped`）。

    口径见上面那一段注释块；豁免只看同一行里的 `_REF_EXEMPT_MARK`。
    每个文件只读一遍：份数按命令当次读（别抄定值，`F9` 写下的 214 已经过期；
    复算 `python -c "import pathlib as p; r=p.Path('.'); skip={'__pycache__','.pytest_cache','.git','.mypy_cache'}; print(sum(1 for f in r.rglob('*') if f.is_file() and f.suffix in ('.py','.md') and not any(x in skip for x in f.parts)))"`
    —— 观测 2026-09-27 15:01 +08:00 ⇒ 216），读两遍是白花的时间。
    """
    pairs: list[tuple[pathlib.Path, str]] = []
    for p in _iter_ref_scan_files(tree):
        try:
            pairs.append((p, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:  # 读不到就当它不在体检范围里：既不报，也不假装干净
            continue
    blob = "\n".join(text for _, text in pairs)
    #: 口径第 2 条用的计数面：整棵树里每个名字作为真符号出现几次
    #: （见 `_python_identifiers_in_text`）。与 `blob` 的关键区别：它不含注释/docstring、
    #: 不含字符串字面量、不含 `.md` 正文 —— 所以"在判据文件里随手写下一个 token"
    #: 抬不动它（`R5-AN-10-1` 的假绿就是靠抬 `blob` 实现的）。
    symbol_counts: dict[str, int] = {}
    symbol_count_files = 0
    for p, text in pairs:
        if _symbol_count_skipped(p, tree):
            # 未跟踪的 scratch（仓的草稿目录）不是"这个名字在仓里的出处"：
            # 它进了扫描面（悬空提及照旧要报），但不许参与计数这一维。
            continue
        symbol_count_files += 1
        for name in _python_identifiers_in_text(p, text):
            symbol_counts[name] = symbol_counts.get(name, 0) + 1

    dangling: list[str] = []
    dangling_tokens: set[str] = set()
    missing: list[str] = []
    exempted: list[tuple[str, int, str]] = []
    tokens: set[str] = set()
    paths: set[tuple[str, str]] = set()
    #: 第三族（`R7-㉒`）的已知面：树里/工作区 temp 下出现过的 `.py` 基名与相对路径。
    known_names = {p.name for p, _ in pairs}
    rel_paths = {p.relative_to(tree).as_posix() for p, _ in pairs}
    temp_dir = ws_root / "temp"
    if temp_dir.is_dir():
        for p in temp_dir.glob("*.py"):
            known_names.add(p.name)
            rel_paths.add(f"temp/{p.name}")
    missing_test_files: list[str] = []
    missing_test_named: set[str] = set()
    seen_test_refs: set[tuple[str, str]] = set()
    for p, text in pairs:
        rel = p.relative_to(tree).as_posix()
        for lineno, line in enumerate(text.splitlines(), 1):
            marked = _REF_EXEMPT_MARK in line
            for tok in sorted(set(_TICKED_PRIVATE.findall(line))):
                tokens.add(tok)
                symbol_count = symbol_counts.get(tok, 0)
                # 悬空只看符号面（第 2 条）：树里没有这个标识符（或只有一个真出现点，
                # 而那一个出现点还不在登记表里）⇒ 注释里的这条引用无迹可寻。
                # 刻意不用"全树文本 ≤ 1 次"当判据：那是 `FIX11` 之前的口径，
                # 而它正是 `R5-AN-10-1` 的病根 —— 文本计数会被别处（尤其本文件里）
                # 的随手提及抬高。留它当条件会让"本文件里多写一个 token"重新拥有
                # 改变读数的能力（连它自己那条豁免都会因此整条消失）。
                if symbol_count <= 1 and tok not in _REF_KNOWN_MENTION_TOKENS:
                    dangling_tokens.add(tok)
                    if marked:
                        exempted.append((rel, lineno, f"`{tok}`"))
                    else:
                        why = (f"全树真符号只出现 {symbol_count} 次，"
                               "登记表 `_REF_KNOWN_MENTION_TOKENS` 里也没有它")
                        dangling.append(f"{rel}:{lineno}: `{tok}`（{why}）")
            for ref in sorted(set(_TICKED_TEMP_PATH.findall(line))):
                if (rel, ref) in paths:
                    continue
                paths.add((rel, ref))
                if not (ws_root / ref).exists():
                    if marked:
                        exempted.append((rel, lineno, f"`{ref}`"))
                    else:
                        missing.append(f"{rel}:{lineno}: `{ref}`")
            # ---- 第三族（`R7-㉒`）：反引号里点名的 `test_*.py` 必须真的存在
            for ref in sorted(set(_TICKED_TEST_FILE.findall(line))):
                if (rel, ref) in seen_test_refs:
                    continue
                seen_test_refs.add((rel, ref))
                if _test_file_exists(ref, tree=tree, ws_root=ws_root,
                                     known_names=known_names, rel_paths=rel_paths):
                    continue
                missing_test_named.add(ref)
                if not marked:
                    missing_test_files.append(f"{rel}:{lineno}: `{ref}`")
    return {
        "files": len(pairs),
        "tokens": len(tokens),
        "ticked_tokens": tokens,
        #: 每个（被 tick 的）token 的真符号出现次数。留在这里是为了让调用方
        #: （登记表那条断言）不必重扫整棵树：在同一次遍历里已经算好了。
        #: 走 `_symbol_occurrences(tree, tok)` 逐个查是 O(token 数 × 整树)，
        #: 实测 329 个 token 会把这条判据从秒级拖到 38 分钟。
        "symbol_counts": {tok: symbol_counts.get(tok, 0) for tok in tokens},
        #: 反真空：计数这一维到底看了多少文件、排除了多少（排除数恒为 0 说明
        #: `_REF_SYMBOL_COUNT_SKIP_DIRS` 没接上 —— 那时"没被 scratch 抬高"这句话是空的）。
        "symbol_count_files": symbol_count_files,
        "symbol_count_skipped": len(pairs) - symbol_count_files,
        "paths": len(paths),
        "dangling": dangling,
        "dangling_tokens": dangling_tokens,
        "missing": missing,
        "missing_test_files": missing_test_files,
        "missing_test_named": missing_test_named,
        "test_refs": len(seen_test_refs),
        "exempted": exempted,
    }


def _test_file_exists(ref: str, *, tree: pathlib.Path, ws_root: pathlib.Path,
                      known_names: set[str], rel_paths: set[str]) -> bool:
    """反引号里点名的 `test_*.py` 在树里（或工作区 `temp/` 下）存在吗（`R7-㉒`）。

    三档解析，缺一档就会把真引用判成缺：
    ① 基名命中扫描面里出现过的 `.py` 基名（带路径的写法与裸基名写法用的是同一个名字空间）；
    ② 相对路径的后缀命中（省略了 `src/agentflow/` 前缀的那种写法）；
    ③ 直接在树根/工作区根下找（`tests/` 与 `temp/` 两种前缀）。
    """
    name = ref.rsplit("/", 1)[-1]
    if name in known_names or any(r.endswith("/" + ref) for r in rel_paths):
        return True
    return (tree / ref).is_file() or (ws_root / ref).is_file()


def test_a_scratch_copy_cannot_cure_a_dangling_reference(tmp_path: pathlib.Path):
    """`R7-⑮` 的负控（B 方案）：草稿目录里的副本抬不动"真符号出现次数"。

    改前的病（`R0-C2` 实测）：在 `temp/` 下放一份整树副本 ⇒ 每个 token 的真符号计数
    被抬高 ⇒ 一条真悬空的引用被判成"不悬空" ⇒ 判据安静变绿，而读数里没有任何一处
    会告诉你。修法刻意窄：`temp/` 照旧进扫描面（它里面的悬空提及照旧要报、它引的
    一次脚本路径照旧要真存在），只是不许参与计数那一维
    （`_REF_SYMBOL_COUNT_SKIP_DIRS`）。

    三档读数（缺一档这条负控就退化成恒真）：
    ① 裸夹具：那条引用必须是悬空（计数 1、登记表 `_REF_KNOWN_MENTION_TOKENS` 里也没有它）；
    ② 把同名副本放进草稿目录：悬空读数逐字不变（副本抬不动计数）；
    ③ 反真空：把同一份副本放进非草稿目录 ⇒ 那条引用必须不再悬空
       （证明计数这一维还活着，②的"不变"不是因为计数坏了）。
    """
    token = "_scratch_copy_probe_dup"
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "defs.py").write_text(f"{token} = 1\n", encoding="utf-8")
    (tmp_path / "docs" / "R.md").write_text("见 `" + token + "`。\n", encoding="utf-8")

    plain = _scan_ticked_references(tmp_path, tmp_path)
    assert [x for x in plain["dangling"] if token in x], (
        f"夹具的悬空引用没被报出来 ⇒ 这条负控是空转：{plain['dangling']}")
    assert plain["symbol_count_skipped"] == 0, plain

    (tmp_path / "temp").mkdir()
    (tmp_path / "temp" / "copy_of_defs.py").write_text(f"{token} = 1\n" * 5, encoding="utf-8")
    with_scratch = _scan_ticked_references(tmp_path, tmp_path)
    assert with_scratch["dangling"] == plain["dangling"], (
        "草稿目录里的副本把那条悬空引用『治好』了 ⇒ 读数又被 checkout 影响了：\n"
        f"  放副本前：{plain['dangling']}\n  放副本后：{with_scratch['dangling']}")
    assert with_scratch["symbol_count_skipped"] == 1, with_scratch["symbol_count_skipped"]

    (tmp_path / "scratch").mkdir()
    (tmp_path / "scratch" / "copy_of_defs.py").write_text(f"{token} = 1\n" * 5,
                                                          encoding="utf-8")
    elsewhere = _scan_ticked_references(tmp_path, tmp_path)
    assert not [x for x in elsewhere["dangling"] if token in x], (
        "副本放进非草稿目录之后那条引用仍然悬空 ⇒ 计数这一维坏了，"
        f"②的『读数不变』不是因为免疫、而是因为计数没在工作：{elsewhere['dangling']}")


def test_the_reference_scan_root_anchor_is_not_a_temp_artifact() -> None:
    """`X-91.5-3` 的反真空判据：根锚必须随仓走，不许挂在一份会被清理的产物上。

    改前的锚是 `temp/REAUDIT6-R5.json`（第 6 轮的一份未跟踪审计产物）。它的坏处不是
    "今天找不到"（今天找得到），而是"清一次 `temp/` 就变成判据自己坏了"：`_RootNotFound`
    会让整条引用判据 FAILED，而读数据的人看不出真正的原因是一份审计 JSON 被删了。

    判据分三层（任何一层单独都不够）：
    ① 今天真的解析得出根（解析不出 = 判据自己坏了，不是 unknown）；
    ② 两条锚在盘上，且都不在 `temp/` 下 —— 这是"未跟踪 scratch"的形态面；
    ③ 锚表本身不许再出现 `temp…` 形态 —— 这是第 ① 层抓不到的：今天它还在盘上，
       所以 ①② 都可以是绿的，只有第 ③ 层能拦住"把锚改回 scratch"这个动作
       （负控就是在副本里做这第 ③ 层，见交付报告）。
    """
    roots = _reference_scan_roots()
    assert roots is not None, (
        "在仓里却解析不出根 —— 根锚失效（`X-91.5-3`）：`_RootNotFound` 那一支的 FAILED"
        "不许被读成 unknown"
    )
    tree, ws_root = roots
    assert tree == pathlib.Path(__file__).resolve().parents[1], tree
    assert (ws_root / "agentflow").is_dir(), f"解析出的工作区根里没有交付树：{ws_root}"

    for marker in _ROOT_MARKERS:
        p = ws_root / marker
        assert p.is_file(), f"根锚不在盘上：{p}"
        rel = p.relative_to(ws_root).as_posix()
        assert not rel.startswith("temp/"), (
            f"根锚落在未跟踪 scratch 里（`X-91.5-3` 的原形态）：{rel} —— "
            "`temp/` 一清，这条判据就会从绿变成『判据自己坏了』"
        )

    assert not any(str(m).startswith("temp") for m in _ROOT_MARKERS), (
        f"根锚表里又出现了 `temp…` 形态（把判据的身份挂回 scratch 上了）：{_ROOT_MARKERS}"
    )


def test_the_quoted_references_in_comments_all_exist() -> None:
    """注释/docstring 里引用的私有符号名与 `temp/` 路径必须真的存在。

    这是第 7 轮那三条 finding 的机械判据：`R7-R5-1`（引了一个全仓不存在的
    私有函数名 —— 那正是本判据会把"示例"也判红的原因，所以本 docstring 里
    所有引号包着的私有名都必须是真符号）、`R7-R5-2`（引的 temp 路径名字写错、
    真名是下划线）、`R7-R5-3`（列着四份不存在的 zone-backup 文件）。

    三态纪律（`R8-R5-1`）：根定不下来时先分清两件事 —— 在仓里却认不出仓
    ⇒ FAILED（判据坏了）；只有真的在仓外（连 checkout 结构都没有）才 skip。
    根锚本身是随仓走的两条（`_ROOT_MARKERS`，`X-91.5-3`），不是 `temp/` 下那份
    未跟踪的审计产物 —— 逐字理由见 `_ROOT_MARKERS` 上面的注释块，
    反真空判据是 `test_the_reference_scan_root_anchor_is_not_a_temp_artifact`。

    ## 记号豁免（逐字三个汉字：`非指代`）

    扫描范围是整棵树（见上面那段注释块，`F9` 按第 8 轮宽扫的口径扩宽）。
    其中历史叙述（`F9` 那处：说的是"修之前这里装配了两个 AgentC"，指已被删掉的
    旧装配点）与示意性引用（`F9` 那处：演示证据路径词法归一的三种等价写法）
    不指向任何东西，但不该被改 —— 改成正名或删掉都是篡改史实/示例。
    这类引用由显式记号放行：在与该引用同一行里写下记号 `非指代`
    （逐字这三个汉字，写在行内任何位置都算），扫描器跳过它，并把跳过次数报出来；
    带记号的引用还必须落在 `_REF_EXEMPTED_EXPECTED_FILES` 登记过的文件里 ——
    多一条、少一条、或换一个文件都算不符（豁免是一条暗门，放行必须留下一次
    可见的登记）。记号是活的还是死的，由
    `test_the_reference_exemption_marker_is_alive` 独立判：全仓一条豁免都没有
    时它报"机制死了"。

    负控 = 把任一引用改成不存在的名字/路径 ⇒ 本用例必红。两条方向都实测过
    （读数 `temp/fix6_f5-neg-V9-r7-dangling-refs.txt`：符号那一路让本用例 FAILED，
    路径那一路由同一份读数里 `MISSING` 的条数给出）；根解析的布局矩阵读数
    在 `temp/fix6_f5-neg-R8-layouts.txt`。`F9` 把范围扩宽之后再跑两条负控
    （注入一个悬空私有符号、注入一个悬空路径）⇒ 本用例各 FAILED，读数随该批
    报告归档，刻意不写进本 docstring：判据不该为了一份临时产物而变红。

    ## 悬空口径（`R5-AN-10-1` 之后按符号数，不按文本数）

    见上面那段注释块的第 2 条：该 token 在整棵树里作为真符号
    （`.py` 的 Python 标识符，不含注释/docstring/字符串/`.md`）出现 ≤ 1 次 ⇒ 悬空。
    这是 `FIX11` 的 `C2` 换掉的口径：改之前数的是"全树文本出现次数"，
    于是"在本文件里随手写下一个被引用的 token"（哪怕只写在注释里）就能把计数
    从 1 抬到 2，别处的悬空引用被"治好"、判据安静变绿（第 10 轮实测
    `symbCrit` / `symbBoth` 两档都是 `passed`）。

    第二条断言是逐条登记表 `_REF_KNOWN_MENTION_TOKENS`（这条口径的豁免面）：
    仓里"只有文本提及、没有真符号"的 token 必须与它逐条相等 ——
    多一个（新写的、没有解释的提及）红，少一个（登记过期）也红。
    记号豁免表 `_REF_EXEMPTED_EXPECTED_FILES` 单独判（上面的断言），两者不通用。

    这条判据的机制守卫是独立的用例
    `test_a_token_written_only_in_this_file_cannot_cure_a_dangling_reference`
    （它自己造一份"只在判据文件里提及"的注入，断言那条引用仍然报红）。
    """
    roots = _reference_scan_roots()
    if roots is None:
        pytest.skip("判据在仓外（祖先里没有本仓 checkout 结构）⇒ 未知，不是通过"
                    "（在仓内认不出仓是 FAILED，不走这一支）")
    tree, ws_root = roots
    res = _scan_ticked_references(tree, ws_root)

    # 判据自身的"接上了没有"证据：一条都没扫到就说明扫描器坏了，而不是"干净"。
    assert res["tokens"] > 10, f"私有符号扫描只接上 {res['tokens']} 个 token（扫描器坏了？）"
    assert res["paths"] > 0, "路径扫描一个都没接上（扫描器坏了？）"
    assert res["dangling"] == [], (
        "注释/docstring 里引用了全仓不存在的私有符号名 —— 读的人按图索骥会找不到东西。"
        "判据按符号面数：该 token 在整棵树里作为 `.py` 的 Python 标识符"
        "（不含注释/docstring/字符串/`.md` 的提及）出现 ≤ 1 次就算悬空。"
        "那条引用是正当的（字符串键、历史名字、约定片段）就逐条登记进 "
        "`_REF_KNOWN_MENTION_TOKENS`，别把它写没："
        f"{res['dangling']}"
    )
    assert res["missing"] == [], (
        "注释/docstring 里引用的 temp/ 路径不存在（结论可能仍是真话，但引用是坏的）："
        f"{res['missing']}"
    )
    # ---- 第三族（`R7-㉒`）：点名的 `test_*.py` 必须真的存在，且"不存在"的那些逐条等额
    assert res["test_refs"] > 0, (
        "第三族一个 `test_*.py` 提及都没接上 ⇒ 扫描器坏了（不是没问题），"
        f"读数：{res['test_refs']}")
    assert sorted(res["missing_test_named"]) == sorted(
        ref for ref, _ in _REF_KNOWN_MISSING_TEST_FILES
    ), (
        "点名的 `test_*.py` 里「不存在」的那些与登记表 `_REF_KNOWN_MISSING_TEST_FILES` 不符 —— "
        "新出现的（有人把文件名写错、或引了一份不存在的测试）要逐条登记并写清类别，"
        "登记过期的要删掉（多一条、少一条都算不符）："
        f"{sorted(res['missing_test_named'])} vs "
        f"{sorted(ref for ref, _ in _REF_KNOWN_MISSING_TEST_FILES)}；"
        f"逐处读数：{res['missing_test_files']}"
    )

    exempted_files = sorted({rel for rel, _, _ in res["exempted"]})
    assert exempted_files == sorted(_REF_EXEMPTED_EXPECTED_FILES) and (
        len(res["exempted"]) == len(_REF_EXEMPTED_EXPECTED_FILES)
    ), (
        "带记号豁免的引用与登记表 `_REF_EXEMPTED_EXPECTED_FILES` 不符 —— 豁免是暗门，"
        "每放行一条都要在表里留一次可见的登记（文件不符、多一条、少一条都算不符）："
        f"{res['exempted']} vs {list(_REF_EXEMPTED_EXPECTED_FILES)}"
    )

    #: 第 2 条的登记面必须逐条等额：多一个（仓里新出现一条只有文本提及、既没登记
    #: 也没带记号豁免的引用）或者少一个（登记已过期）都算不符。判的是"仓里实际
    #: 需要登记的 token 集合"，而不是"这一次 dangling 里出现了谁" —— 后者在干净树上
    #: 是空集，拿它做等额会退化成恒真断言（那正是本批在治的东西）。
    #: 有两处引用同时被两条路覆盖（记号豁免 + 本表），所以这里排除"该 token 还有
    #: 一条没带记号的引用"的那些 —— 两条路互相不挤占：豁免面由上面那条表断言管。
    mentioned_only = sorted(
        tok for tok in res["ticked_tokens"]
        if res["symbol_counts"].get(tok, 0) <= 1 and tok not in res["dangling_tokens"]
    )
    assert mentioned_only == sorted(_REF_KNOWN_MENTION_TOKENS), (
        "只有文本提及、没有真符号出现的 token 与登记表 `_REF_KNOWN_MENTION_TOKENS` 不符 —— "
        "登记是『这条引用的意思被记下来了』，不是『这条引用不用管』：新写下的提及要在表里"
        "留一条（并写清它属于哪一类），表里过期的条目也要删掉（多一条、少一条都算不符）："
        f"{mentioned_only} vs {sorted(_REF_KNOWN_MENTION_TOKENS)}"
    )


def test_a_wrong_test_file_name_in_a_comment_is_caught() -> None:
    """`R7-㉒` 的负控：把真事故那 22 行里点名的文件名写错一个字 ⇒ 第三族必须报。

    真事故的样本是真字符串（不是造出来的）：`src/agentflow/agent_c/*.py` 与
    `agent_d/*.py` 的第 3 行原来点的是"逐字"那一版文件名，而那份文件不存在；
    真判据是 `tests/test_agent_split_is_one_action_one_file.py`。那 22 行已改真。

    两档读数（缺一档这条负控就是空转）：
    ① 现在的真名（那 22 行里逐字就是它）⇒ 不许被报成缺；
    ② 改前的错名（把中间那段前缀去掉 —— 正是那次事故的形态）⇒ 必须被报成缺。
    错名在这里用拼接造出来：判据扫的是原始字节，写死它等于在本文件里留一条
    假引用（同 `test_the_ref_scan_skips_run_artifacts_but_not_the_repo` 的做法）。
    """
    tree, ws_root = _reference_scan_roots() or (None, None)
    assert tree is not None, "判据在仓外 ⇒ 这条负控取不到真树（那是 unknown，不是通过）"
    pairs = [(p, "") for p in _iter_ref_scan_files(tree)]
    known_names = {p.name for p, _ in pairs}
    rel_paths = {p.relative_to(tree).as_posix() for p, _ in pairs}

    def _exists(ref: str) -> bool:
        return _test_file_exists(ref, tree=tree, ws_root=ws_root,
                                 known_names=known_names, rel_paths=rel_paths)

    good = "tests/test_agent_split_is_one_action_one_file.py"
    bad = "tests/test_agent_split_is_" + "verbatim.py"
    assert _exists(good), f"那 22 行现在点的真名被判成缺：{good}（第三族会把真引用判红）"
    assert not _exists(bad), (
        f"改前的错名居然被判成存在：{bad} —— 夹具不成立（那条负控会退化）")
    assert _TICKED_TEST_FILE.search("`" + bad + "`"), "新形态没接上那个错名（正则漏了）"
    assert _TICKED_TEST_FILE.search("`" + good + "`"), "新形态没接上那个真名"


def test_the_reference_exemption_marker_is_alive() -> None:
    """反真空：豁免记号必须还在用，而且必须逐字写在上面那条判据的 docstring 里。

    为什么需要这条判据（`F9`）：豁免是一条只减不增的通道。记号被删掉、
    或扫描器改成认不出它时，`test_the_quoted_references_in_comments_all_exist`
    会重新报出那两处"悬空引用"（红）；但如果有人干脆把豁免机制整体拆掉、
    把那两处引用一起改成正名/删掉，那条判据会安静地变绿，
    而"机制死了"这件事没有任何地方会响 —— 这正是本仓三态纪律针对的形态
    （"没报"不等于"没有"）。所以这里独立地要求两件事：
    ① 判据的 docstring 里逐字出现记号；② 全仓至少有一条引用真的带着记号被跳过。
    """
    doc = test_the_quoted_references_in_comments_all_exist.__doc__ or ""
    assert _REF_EXEMPT_MARK in doc, (
        f"上面那条判据的 docstring 里没有逐字写出豁免记号 `{_REF_EXEMPT_MARK}` —— "
        "记号是给人看的约定，判据的说明里不写它，读的人就无从知道该怎么标"
    )
    roots = _reference_scan_roots()
    if roots is None:
        pytest.skip("判据在仓外（祖先里没有本仓 checkout 结构）⇒ 未知，不是通过"
                    "（在仓内认不出仓是 FAILED，不走这一支）")
    tree, ws_root = roots
    res = _scan_ticked_references(tree, ws_root)
    assert res["exempted"], (
        f"全仓没有一条引用带豁免记号 `{_REF_EXEMPT_MARK}` ⇒ 记号的豁免机制死了："
        "要么记号被删了，要么扫描器不再识别它。死掉的豁免机制会让引用的那条判据"
        "从'显式豁免两处'退回'漏报'，而它的读数看上去与'干净'一模一样"
    )


def test_the_stale_line_number_references_are_gone() -> None:
    """`R5-AN-4`：四处实测指错对象的 `文件:行号` 引用必须已经改成符号名。

    负控形态就是改前字节：把任意一处改回上面那四个字符串，这条用例必须红
    （读数见 `temp/fix6_f5-neg-V4-an4-line-refs.txt`）。

    路径从 `__file__` 推（不从 `agentflow.__file__` 推）：被测的源代码树与
    本文件在同一个仓里，而 `sys.path` 上可能有另一份 `agentflow`（负控就是
    在整树副本上跑的）—— 从 `__file__` 推才能保证"判据读的文件 == 我改的文件"。
    """
    src_root = pathlib.Path(__file__).resolve().parents[1] / "src"
    assert (src_root / "agentflow" / "runflow.py").is_file(), (
        f"判据的落点不对（找不到 {src_root / 'agentflow' / 'runflow.py'}）"
    )
    for rel, stale in _STALE_REFS:
        text = (src_root / rel).read_text(encoding="utf-8")
        assert stale not in text, (
            f"{rel} 里仍有实测指错对象的引用 {stale} —— 它指向的行不是那句话说的东西；"
            "改成符号名之后行号漂移不再影响引用"
        )


#: 机制守卫用的记号。逐字就是第 10 轮审计者那台探针用的名字（`symb` / `symbCrit` 档），
#: 本文件里它只以这个名字的字符串值出现，见下面那条用例的 docstring。
_PROBE_TOKEN = "_r10_dangling_probe_aaa"


def _module_with_the_probe_token_in_a_comment() -> dict:
    """本模块的一份内存副本，另加：记号值 + 一行不带反引号的注释提及。

    它就是审计者 `symbCrit` 档的注入（"只在判据文件里写下 token"），只是在内存里做 ——
    仓里不留假引用（判据不该为了一份临时产物而变红）。
    """
    source_like = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _PROBE_TOKEN not in _TICKED_PRIVATE.findall(source_like), (
        "记号不该已经被反引号包着出现在本文件里（那会让注入不再是'裸提及'）"
    )
    injected = (
        source_like
        + "\n# 机制守卫：下面这一行是『只在判据文件里提及』的注入，逐字不带反引号 "
        + _PROBE_TOKEN
        + "\n"
    )
    namespace = {"__file__": __file__, "__name__": __name__}
    exec(compile(injected, __file__, "exec"), namespace)  # noqa: S102 —— 注入自己写的字节
    return namespace


@contextlib.contextmanager
def _probe_tree_copy(tree: pathlib.Path, ws_root: pathlib.Path):
    """整树真副本（`shutil.copytree`，不是硬链接），落在工作区 `temp/` 下；退出时删掉。

    为什么必须有这个装置（`FIX12` 的 `R5-AN-11-1`）：机制守卫要在"别处真的有一条悬空
    引用"的树上跑判据，而改前它把那一行直接写进真仓的 `src/agentflow/runflow.py`
    （`finally` 里再还原）。那条注入在盘上存活 7.13–7.68 秒，于是

    - 硬杀 pytest（`finally` 不跑）⇒ 受审源码留在盘上：多一行假引用，外加 `write_text`
      的默认换行翻译把整份文件转成 CRLF（+1958 字节）⇒ 四道门的读数当场作废；
    - 同树并发的另一个 pytest 读到瞬时注入 ⇒ 假红。

    复制范围 = 判据扫描所需的全集：`_iter_ref_scan_files` 会 `rglob` 整棵树，所以副本
    必须覆盖全部 `.py` / `.md`（少一份，副本的符号计数就不再等于真树）；缓存目录按判据
    自己的跳过表 `_REF_SCAN_SKIP_DIRS` 跳过 —— 判据本来就看不见它们，读数不受影响。
    实测（本机 2026-09-27 16:52:23，UTC+8）：整树 274 个文件、其中 216 个被扫文件，
    `copytree` 0.63 秒。
    """
    import os
    import shutil

    dest = ws_root / "temp" / f"fix12a-probe-tree-{os.getpid()}-{int(time.time() * 1000)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tree, dest, ignore=shutil.ignore_patterns(*_REF_SCAN_SKIP_DIRS))
    try:
        yield dest
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def _probe_apparatus_reading(copy_root: pathlib.Path, tree: pathlib.Path) -> tuple[str, str]:
    """两档子进程里 `agentflow` 到底从哪儿 import（装置陷阱③）：`(副本档, 真仓档)`。

    为什么非要有这一条：`sys.path` 上很可能还有真仓那份 `agentflow`
    （`PYTHONPATH=src`，而子进程会继承环境），那时"在副本里跑断言"只是错觉 ——
    子进程读的还是真仓。这里跑两档子进程：一档把副本的 `src/` 放在最前、一档把真仓的
    放在最前，把 `agentflow.__file__` 读回来。调用方断言副本档落在副本里、真仓档落在
    真仓里、两者不同 —— 真仓那一档就是这条断言的反真空：它证明"落在副本里"这句话
    不是恒真的（装置若坏了，两档会读到同一个文件，而断言照样亮绿）。
    """
    import os
    import subprocess

    code = "import agentflow, pathlib; print(pathlib.Path(agentflow.__file__).resolve())"

    def _one(root: pathlib.Path) -> str:
        env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(root), env=env,
                              capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == 0, (
            f"子进程 import agentflow 失败（cwd={root}）：rc={proc.returncode}\n{proc.stderr}"
        )
        return proc.stdout.strip()

    return _one(copy_root), _one(tree)


def test_a_token_written_only_in_this_file_cannot_cure_a_dangling_reference() -> None:
    """机制守卫（`R5-AN-10-1` 的验收）：判据文件里的一次提及救不了别处的悬空引用。

    第 10 轮实测的假绿就是这个形态：判据的悬空口径数的是"全树文本出现次数"，
    而它把本文件里的提及也算一次 ⇒ 在本文件里随手写下被引用的 token
    （不带反引号即可）就把计数从 1 抬到 2 ⇒ 别处那条真悬空的引用不再算悬空
    ⇒ 判据安静变绿（`symbCrit` / `symbBoth` 两档实测 `passed`）。

    这条用例自己造那个注入，而且仓内一个字节都不写（`FIX12` 的 `R5-AN-11-1`）：
    注入的落点是工作区 `temp/` 下的一份整树真副本（`shutil.copytree`，见
    `_probe_tree_copy`），扫描与子进程断言都在副本上跑、跑完把副本删掉。改前这一步直接
    改写真仓的 `src/agentflow/runflow.py`（追加一行带反引号的假引用、`finally` 里再
    `write_bytes` 还原）：盘上带注入的状态实测存活 7.13–7.68 秒，硬杀 pytest 就把带假
    引用的源码留在盘上（`write_text` 的换行翻译还把整份文件转成 CRLF，+1958 字节），
    同树并发的另一个 pytest 读到瞬时注入会假红 —— 受审源码文件的字节被改，四道门的读数
    当场作废。这句 docstring 此前写的是"不动盘上的文件"，实现不是；现在实现是了
    （真仓那份受审源码的字节与 mtime 由本用例自己在末段断言钉住）。

    两个对照 ——

    ① 注入的只是文本：把本模块的源码 + 一行裸提及在内存里 `exec` 一份（不落盘），
       `dangling` 与 `dangling_tokens` 必须与不注入时逐字相同
       （旧口径下这里会少一条，这条断言当场变红）；
    ② 注入升级成"判据文件里裸写 token + 别处真有一条悬空引用"：两处注入都写在副本上
       （判据文件里一行裸提及 + 别处一条带反引号的引用），`dangling` 必须多出恰好那一条，
       且它就是本文件里那处裸提及没有治好的那条（①与②合起来才是"救不了"的完整证据）。
       副本先自证与真树读数逐字相同，这一条才归因得到注入上。

    为什么必须独立成一条：判据本体里的每条断言都是"仓里现在没问题"，
    而这条判的是判据的能力——"没报"不等于"没有"，检测能力被削弱的形态
    恰恰是"读上去与干净一模一样"，所以它要自己造一个必须报红的输入。
    """
    roots = _reference_scan_roots()
    if roots is None:
        pytest.skip("判据在仓外（祖先里没有本仓 checkout 结构）⇒ 未知，不是通过"
                    "（在仓内认不出仓是 FAILED，不走这一支）")
    tree, ws_root = roots

    plain = _scan_ticked_references(tree, ws_root)
    injected_ns = _module_with_the_probe_token_in_a_comment()
    injected = injected_ns["_scan_ticked_references"](tree, ws_root)

    assert not any(_PROBE_TOKEN in item for item in plain["dangling"]
                   + [f"{rel}:{line}: {what}" for rel, line, what in plain["exempted"]]), (
        f"仓里已经有一处 `{_PROBE_TOKEN}` 的引用 ⇒ 本用例的对照不再干净，"
        "先把那处引用处理掉（它是一处探针残留）"
    )
    assert plain["dangling_tokens"] == injected["dangling_tokens"] and (
        plain["dangling"] == injected["dangling"]
    ), (
        "在本文件里写下一行不带反引号的提及，就改变了扫描读数 ⇒ 悬空口径又被"
        "文本计数带跑了（`R5-AN-10-1` 的假绿会跟着回来）：\n"
        f"  不注入：{plain['dangling']}\n  注入后：{injected['dangling']}"
    )

    # ② 把"别处真的有一条悬空引用"补上：该 token 带反引号写进一个被扫文件 ——
    #    落点是整树真副本（工作区 `temp/` 下），真仓的字节一个都不动。
    rel_holder = "src/agentflow/runflow.py"
    holder = tree / rel_holder
    assert holder.is_file(), f"注入口的落点不对（找不到 {holder}）"
    real_bytes = holder.read_bytes()
    real_hash = hashlib.sha256(real_bytes).hexdigest()
    real_stat = holder.stat()

    with _probe_tree_copy(tree, ws_root) as copy_root:
        copy_holder = copy_root / rel_holder
        copy_criterion = copy_root / "tests" / pathlib.Path(__file__).name
        assert copy_holder.is_file() and copy_criterion.is_file(), (
            f"副本的形态不对（缺 {copy_holder} 或 {copy_criterion}）"
        )
        assert copy_holder.read_bytes() == real_bytes, (
            "副本里的受审文件与真仓不是同一份字节 ⇒ 下面那条负控读的不是被测源码"
        )
        # 装置陷阱③：`agentflow` 必须能从副本里 import，而且读出来的就是副本那份。
        from_copy, from_real = _probe_apparatus_reading(copy_root, tree)
        assert copy_root.resolve() in pathlib.Path(from_copy).resolve().parents, (
            f"子进程里的 agentflow 不在副本里（读到 {from_copy}）⇒ '在副本里跑断言'是错觉："
            "`sys.path` 上那份真仓的包会顶掉副本"
        )
        assert tree.resolve() in pathlib.Path(from_real).resolve().parents and (
            from_copy != from_real
        ), (
            f"反真空不成立：真仓档读到的也是 {from_real} ⇒ 上一条断言认不出'读错了树'"
        )
        # 副本必须与真树读数逐字相同，否则"副本上多出来的那一条"归因不到注入上。
        copy_plain = _scan_ticked_references(copy_root, ws_root)
        assert copy_plain["dangling"] == plain["dangling"] and (
            copy_plain["missing"] == plain["missing"]
        ) and copy_plain["dangling_tokens"] == plain["dangling_tokens"], (
            "整树副本的读数与真树不同 ⇒ 副本不是真树的替身，负控的归因不成立：\n"
            f"  真树: {plain['dangling']} / {plain['missing']}\n"
            f"  副本: {copy_plain['dangling']} / {copy_plain['missing']}"
        )
        # 两处注入都写在副本上（真仓一个字节都不写）：① 判据文件里一行裸提及
        # （不带反引号 ⇒ 符号面看不见它，正是第 10 轮那档假绿的形态）；② 别处一条带
        # 反引号的真悬空引用。合起来就是 `symbCrit` / `symbBoth` 两档在盘上的完整形态。
        # 一律 `read_bytes` / `write_bytes`：`write_text` 的默认换行翻译会把整份文件
        # 转成 CRLF（`R5-AN-11-1` 那条残留读数就是这么来的）。
        copy_criterion.write_bytes(
            copy_criterion.read_bytes()
            + f"\n# 机制守卫（FIX12-a）：只在判据文件里裸写 {_PROBE_TOKEN}，不带反引号\n".encode()
        )
        copy_holder.write_bytes(
            copy_holder.read_bytes()
            + f"\n#: 机制守卫（FIX11-d）：这里引用一个不存在的名字 `{_PROBE_TOKEN}`。\n".encode()
        )
        after = _scan_ticked_references(copy_root, ws_root)

    # 这条用例自己的正控（`R5-AN-11-1` 的验收）：真仓那份受审源码的字节与 mtime 都没变。
    now_bytes = holder.read_bytes()
    now_stat = holder.stat()
    assert now_bytes == real_bytes and now_stat.st_mtime_ns == real_stat.st_mtime_ns, (
        f"本用例动了真仓的 {rel_holder}：sha256 {real_hash} → "
        f"{hashlib.sha256(now_bytes).hexdigest()}，"
        f"mtime_ns {real_stat.st_mtime_ns} → {now_stat.st_mtime_ns}"
        " ⇒ 机制守卫不许写仓内任何字节（改了它，四道门的读数就作废了）"
    )
    new_items = [x for x in after["dangling"] if x not in plain["dangling"]]
    assert len(new_items) == 1 and _PROBE_TOKEN in new_items[0], (
        "本文件里那处裸提及把别处的悬空引用『治好』了 ⇒ 这盏灯又变成了假绿。"
        f"（期望多出恰好一条含 `{_PROBE_TOKEN}` 的 dangling，实得：{new_items}）"
    )
