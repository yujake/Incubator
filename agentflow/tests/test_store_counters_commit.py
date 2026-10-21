"""`R6-AN-1` 的仓内判据：`set_counters` 的写入不许被在飞事务的提交静默吞掉。
## 被测的形态（逐字来自 `temp/REAUDIT6-R3.json` 的 `R6-AN-1`）
`Store.tx` 的提交块曾经用事务自己那份 counters 缓存整份覆盖 `counters.json`（`doc = self._dirty_counters or self._load("counters")`）。
那份缓存是事务第一次`alloc_id` 时读的，而事务体全程不持写者锁（写者锁只在提交块里拿）。于是「事务已读 counters、尚未提交」这个窗口里 `set_counters` 落盘的写入，会被该事务的提交静默吞掉：无日志、无异常。实测（审计读数）999
消失、盘上回到旧值。
## 为什么必须是两个真子进程
窗口的两端分别是「事务体」与「提交块」，而两把锁都是文件锁：在同一个进程里用线程模拟，两个写者会在锁上相遇，窗口根本不存在（假绿）。`tests/_mp_idem_worker.py` 已经把这条装置纪律写下来了：真进程 + 文件通信、不走管道。
## 三条断言（缺一不可）
1. 计数不丢：C 用 `set_counters` 写下 `stmt=999` 并核实此刻盘上就是 999，B 提交之后盘上仍然是 999（而不是 B 那份旧缓存里的值）；2. 有可判定的痕迹：`events.jsonl` 里有一条 `op=info` /
`message=counters_commit_merged`的事件，带 `disk` / `cache` / `merged` 三个读数（`F3` 的修法）；3. 反真空：痕迹事件必须真的是从盘上读出来的 ——
所以每条断言都先钉住"读到了什么"（事件条数、三读数的形状），不许出现「因为没读到痕迹所以通过」。
## 成对对照（本文件的核心）
- 正控：当前字节的 `store.py` ⇒ 判据必须通过；- 负控：把修法撤掉（提交块改回"用旧缓存整份覆盖"）之后放进 `tmp_path` 的盘外副本⇒ 同一条判据必须变红，并把副本的 sha256 打进断言消息（指纹）；若审计冻结的那一版
`store.py`（`a3857e0a…`）的备份还在盘上，再跑一遍那一版；- 常态对照：没有并发写者时计数器照常前进、且不写痕迹事件 ——没有它，"一律写 999"或"一律写痕迹"也能让正控通过。
本文件只往 `tmp_path` 写（子进程的结果、工作区、副本都在那里），仓里一个字节都不写。
## S1r 并表（`SCHEMA_VERSION=2`）之后的改动
本文件守的是计数器提交合并判据（`R6-AN-1` / `R7-AN-1`），计数器类别只是标本。并表把 `concepts` 表与 `concept` 这一档计数器一起退役 ⇒ 标本换成`stmt`（表 `statements`，主键 `stmt_id`），
三条断言（终值 / 痕迹 / 反真空读数）与两个负控注入点一字未改。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: 与 `tests/conftest.py` 同一口径：注入 `src/`，不要求安装包。
_SRC = Path(__file__).resolve().parents[1] / "src"

#: 痕迹事件的 `message` 与它必须带的四个读数键（`F3` 的修法 + `R7-AN-1` 的 `baseline`）。
TRACE_MESSAGE = "counters_commit_merged"
TRACE_KEYS = ("disk", "cache", "baseline", "merged")

#: 夹具起点与两个方向：把 `stmt` 拨到 3 ⇒ 事务发出 `0003`、缓存变成 4。
#: - 窗口里写 999（更大）⇒ 提交后盘上 999，痕迹方向 `disk_higher`；
#: - 窗口里写 0（拨低）⇒ 提交后盘上仍是 4（`max` 语义不变），痕迹方向 `disk_lower`。
SEED = 3
OVERRIDE = 999
OVERRIDE_LOWER = 0
MERGED_WHEN_LOWER = SEED + 1

#: 负控要撤掉的那一段（提交块里"把 counters 的最终内容交给写者锁内的合并"）。
_FIXED_NEEDLE = (
    "                if counters_pending:\n"
    "                    to_write.append(\n"
    '                        (self.data / "counters.json", self._merge_counters_for_commit(t))\n'
    "                    )\n"
)
#: 改前形态（`R6-AN-1` 的缺陷形态）：用事务自己那份旧缓存整份覆盖。
_PRE_FIX_TEXT = (
    "                if counters_pending:\n"
    '                    doc = self._dirty_counters or self._load("counters")\n'
    '                    to_write.append((self.data / "counters.json", doc))\n'
)
_MERGE_CALL = "self._merge_counters_for_commit(t)"

#: `R7-AN-1` 的负控要把双向痕迹改回单向（只在盘上更高时写）。
_TWO_WAY_NEEDLE = "            if base is None or d == base:\n"
_ONE_WAY_TEXT = "            if base is None or d <= base:\n"

#: 审计冻结集里的改前 `store.py`（`REAUDIT6-R3.files_sha256_before`）。
PRE_FIX_SHA256 = "a3857e0a301436d61fd1c3acd5a7f801aad182088f68177aca81dd82279f00c2"

#: 固定时间戳：夹具行不许依赖当前时间（与 `tests/conftest.py` 同口径）。
TS = "2026-01-01T00:00:00+00:00"

#: 等标记/等子进程的上限（秒）。超时必须报错，不许静默继续 ——
#: 静默继续会把"装置没跑起来"读成"没有丢更新"。
TIMEOUT = 60.0


# --------------------------------------------------------------------------- 小工具


def _sha256(path: Path) -> str:
    """文件的 sha256（指纹用）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _clean_env() -> dict:
    """子进程环境：剥掉 `PYTHONPATH`（探针必须只看见自己那份盘外副本）。

    不剥的话，同时挂着真实 `src` 的 `PYTHONPATH` 会让探针导入到仓内的
    `agentflow` —— 那时探针读到的就不是"冻结的那一版"，而它照样会打印 YES
    （假绿：这是"装置在骗人"，不是判据在说话）。
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def _read_counters(root: Path) -> dict:
    """盘上 `counters.json` 的 `counters` 段。"""
    doc = json.loads((Path(root) / "data" / "counters.json").read_text(encoding="utf-8"))
    return dict(doc.get("counters") or {})


def _read_events(root: Path) -> list[dict]:
    """盘上 `events.jsonl` 的逐条事件（坏行也留下，不吞）。"""
    p = Path(root) / "data" / "events.jsonl"
    out: list[dict] = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"op": "corrupt", "raw": line[:160]})
    return out


def _read_child(path: Path) -> dict:
    """读子进程写下的结果文件；没有就报"装置故障"，不许当成功。"""
    if not Path(path).exists():
        raise AssertionError(f"子进程没有写下结果文件 {path}（装置故障，不是判据在说话）")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _wait_for(path: Path, label: str, timeout: float = TIMEOUT) -> None:
    """等一个标记文件出现；超时抛错（不静默继续）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if Path(path).exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"等 {label} 超时（{timeout:.0f}s）：{path}")


# --------------------------------------------------------------------------- 判据本体


def _judge(case: dict, *, override: int, direction: str, final: int) -> dict:
    """判据本体（纯函数，便于给它自己做自校）。

    通过要求三件事同时成立：盘上终值 = `final`、有痕迹事件、且那条事件带齐四个读数
    （`disk` / `cache` / `baseline` / `merged`）、点名 `stmt`、方向 = `direction`，
    并且事件是从盘上被读到的（`events_read > 0`）。
    两个方向共用这一份判据，只是参数不同（`disk_higher` / `disk_lower`）。
    """
    events = case["events"]
    traces = [e for e in events if e.get("op") == "info" and e.get("message") == TRACE_MESSAGE]
    shaped = [
        e for e in traces
        if all(isinstance(e.get(k), dict) for k in TRACE_KEYS)
        and "stmt" in (e.get("differing") or [])
        and (e.get("direction") or {}).get("stmt") == direction
        and e["disk"].get("stmt") == override
        and e["baseline"].get("stmt") == SEED
        and e["merged"].get("stmt") == final
    ]
    final_matches = case["after_commit"].get("stmt") == final
    return {
        "events_read": len(events),
        "trace_events": len(traces),
        "trace_shaped": len(shaped),
        "final": case["after_commit"].get("stmt"),
        "final_matches": final_matches,
        "pass": bool(final_matches and shaped and len(events) > 0),
    }


# --------------------------------------------------------------------------- 装置


def _run_case(pkg_root: Path, base: Path, *, override: int = OVERRIDE,
              timeout: float = TIMEOUT) -> dict:
    """跑一次「C 在窗口里写 `override` / B 提交」的并发场景，返回读到的全部原始数据。

    装置形状与 `tests/_mp_idem_worker.py` 一致：两个真子进程 + 文件通信
    （就绪 / 放行 / 结果三类标记文件都在 `base` 下，不走管道）。
    """
    from agentflow.store import Store  # noqa: PLC0415 - 只在这里用，避免子进程路径被污染

    base.mkdir(parents=True, exist_ok=True)
    ws = base / "ws"
    ready, go = base / "tx-ready.json", base / "tx-go"
    res_b, res_c = base / "tx-result.json", base / "set-result.json"

    st = Store(ws)
    st.init()
    st.set_counters({"stmt": SEED}, actor="fixture", note="夹具：把计数器拨到 3")

    script = str(Path(__file__).resolve())
    common = [sys.executable, script, "--pkg", str(pkg_root), "--root", str(ws),
              "--override", str(override)]
    b = subprocess.Popen(  # noqa: S603 - 脚本就是本文件，参数都是自己给的
        common + ["--role", "tx", "--ready", str(ready), "--go", str(go), "--result", str(res_b)]
    )
    try:
        _wait_for(ready, "tx 子进程的就绪标记", timeout)
        c = subprocess.run(  # noqa: S603
            common + ["--role", "set", "--ready", str(ready), "--result", str(res_c)],
            timeout=timeout, check=False,
        )
        assert c.returncode == 0, f"set 子进程退出码 {c.returncode}：{_read_child(res_c)}"
        go.write_text("go", encoding="utf-8")
        assert b.wait(timeout=timeout) == 0, f"tx 子进程退出码 {b.returncode}：{_read_child(res_b)}"
    finally:
        if b.poll() is None:
            b.kill()
            b.wait(timeout=10)
    b_payload = _read_child(res_b)
    c_payload = _read_child(res_c)
    assert b_payload.get("ok"), f"tx 子进程失败：{b_payload.get('error')}"
    assert c_payload.get("ok"), f"set 子进程失败：{c_payload.get('error')}"
    return {
        "ws": ws,
        "tx": b_payload,
        "set": c_payload,
        "events": _read_events(ws),
        "after_commit": _read_counters(ws),
    }


def _audit_baseline_store() -> Path | None:
    """审计冻结的那一版改前 `store.py`（在盘上就返回路径，不在就 None）。

    它不是仓内文件：`F3` 的改前备份落在 `D:\\Incubator\\temp\\FIX6-F3-bak\\`。
    文件不在时不让本用例变红 —— 负控的第一条（注入版）已经在盘外副本上跑过，
    这一条是"逐字等于审计冻结字节"的加强证据，不是唯一证据。
    """
    candidates = [
        _SRC.parents[1] / "temp" / "FIX6-F3-bak" / "store.py.bak",
        _SRC.parents[1] / "temp" / "store.py.bak",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _baseline_pkg(baseline: Path, tmp_path: Path) -> Path:
    """把审计冻结的那一版 `store.py` 放进一份当前包的盘外副本里，返回包根。

    与 `_reverted_copy` 同一形状（复制当前包 + 覆盖一个文件），但不动注入点：
    这一臂跑的是"逐字等于审计冻结字节"的那一版。
    """
    pkg = tmp_path / "negpkg-baseline"
    pkg.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_SRC / "agentflow", pkg / "agentflow")
    shutil.copy2(baseline, pkg / "agentflow" / "store.py")
    return pkg


def _baseline_can_open_statements(baseline: Path, tmp_path: Path) -> bool:
    """那一版 `store.py` 能不能开一笔 `statements` 事务？（判据 = 真的跑一次）

    为什么要问：`a3857e0a…` 早于 `statements` 表（S1r 并表那一笔）。对它来说
    `tx("statements", …)` 是"未知表"，子进程会卡在进不了事务体上 ——
    症状是 60s 超时，而超时不是判据在说话（这种"装置没跑起来"必须与判据分开）。
    判据刻意用真子进程 + 真包：写死一个版本号或者去读源码文本都会变成
    第二份判据（并且会在文件一改就静默失效）。
    """
    probe_pkg = _baseline_pkg(baseline, tmp_path / "probe-common")
    ws = tmp_path / "probe-ws"
    code = (
        "import sys, json;"
        f"sys.path.insert(0, {str(probe_pkg)!r});"
        "from agentflow.store import Store;"
        f"st = Store({str(ws)!r}); st.init();"
        "\ntry:\n"
        "    with st.tx('statements', 'counters') as tx:\n"
        "        tx.alloc_id('stmt')\n"
        "except Exception:\n"
        "    print('NO')\n"
        "else:\n"
        "    print('YES')\n"
    )
    proc = subprocess.run(  # noqa: S603 - 代码与路径都是自己给的
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=TIMEOUT, check=False,
        env=_clean_env(),
    )
    return proc.returncode == 0 and proc.stdout.strip().endswith("YES")


# --------------------------------------------------------------------------- 正控


def test_set_counters_write_survives_an_inflight_commit(tmp_path: Path) -> None:
    """正控（窗口里写更大的值）：999 必须在事务提交之后仍然在盘上，且方向痕迹为 `disk_higher`。

    前置断言（C 确实落盘）与反真空断言（事件日志真被读到）都在这里 ——
    没有它们，"盘上是 999"可能来自一个根本没跑起来的装置。
    """
    # 惰性 import（`noqa: PLC0415`）：本模块被当脚本跑（子进程）时，导入期不许
    # 先把真实树里的 `agentflow` 灌进 `sys.modules` —— 否则子进程后面
    # `sys.path.insert(0, --pkg)` 插进来的盘外副本永远抢不到（实测形态：
    # 「导入到的 store 不在 --pkg 下」，负控整套失效）。
    from agentflow import schema as S  # noqa: PLC0415

    case = _run_case(_SRC, tmp_path / "pos", override=OVERRIDE)
    verdict = _judge(case, override=OVERRIDE, direction="disk_higher", final=OVERRIDE)
    store_sha = case["tx"]["store_sha256"]
    print(f"[指纹] tx 子进程跑的 store.py = {case['tx']['store_file']} sha256/16={store_sha[:16]}"
          f"；正控期望的当前字节 = {_sha256(_SRC / 'agentflow' / 'store.py')[:16]}")
    assert case["tx"]["allocated"] == S.format_id(3), case["tx"]
    assert case["tx"]["tx_cache"] == {"stmt": SEED + 1}, case["tx"]
    assert case["set"]["on_disk"] == {"stmt": OVERRIDE}, case["set"]
    assert verdict["events_read"] >= 2, (
        f"反真空：事件日志必须真的被读到（读到 {verdict['events_read']} 条）—— "
        "读到 0 条时任何「没有痕迹」的结论都不算证据"
    )
    assert verdict["trace_events"] == 1, f"期望恰好一条痕迹事件：{verdict}"
    assert verdict["trace_shaped"] == 1, f"痕迹事件必须带四个读数并点名方向：{verdict}"
    assert verdict["final_matches"], f"计数被吞了：盘上 = {case['after_commit']}（判据 {verdict}）"
    assert verdict["pass"], verdict
    assert store_sha == _sha256(_SRC / "agentflow" / "store.py"), (
        "正控必须跑当前字节的 store.py"
    )


def test_lowering_inside_the_window_is_visible_and_the_retry_works(tmp_path: Path) -> None:
    """正控（`R7-AN-1`，窗口里拨低）：终值仍取 `max`（不倒退），但必须留下 `disk_lower` 痕迹。

    这是 `R6-AN-1` 那个缺陷形态的另一半：改前这个方向无日志、无异常、无痕迹，
    于是"显式拨低"这件事在窗口里既失效又不可判定。语义不变（`max` 只会往前推，
    改成"缓存赢"会重开 raising 方向），被修的是可判定性。

    另附审计给的对照臂：窗口结束后重试同一次拨低 ⇒ 生效
    ⇒ 被吞掉的是窗口，不是 `set_counters` 本身坏了。
    """
    from agentflow.store import Store  # noqa: PLC0415

    case = _run_case(_SRC, tmp_path / "lower", override=OVERRIDE_LOWER)
    verdict = _judge(case, override=OVERRIDE_LOWER, direction="disk_lower",
                     final=MERGED_WHEN_LOWER)
    print(f"[读数] 拨低：C 落盘时 = {case['set']['on_disk']}；提交后 = {case['after_commit']}；"
          f"痕迹 = {verdict['trace_events']} 条（方向 disk_lower）")
    assert case["set"]["on_disk"] == {"stmt": OVERRIDE_LOWER}, case["set"]
    assert verdict["events_read"] >= 2, f"反真空：事件日志必须真的被读到：{verdict}"
    assert verdict["trace_events"] == 1, f"窗口里的拨低必须留下痕迹：{verdict}"
    assert verdict["trace_shaped"] == 1, f"痕迹必须点名 disk_lower 且带四个读数：{verdict}"
    assert verdict["final"] == MERGED_WHEN_LOWER, (
        f"终值语义不许变（max ⇒ {MERGED_WHEN_LOWER}）：{verdict}"
    )
    assert verdict["pass"], verdict

    # 对照臂：窗口结束后重试 ⇒ 拨低照常生效。
    Store(case["ws"]).set_counters({"stmt": OVERRIDE_LOWER}, actor="retry")
    assert _read_counters(case["ws"])["stmt"] == OVERRIDE_LOWER, (
        "窗口结束后重试必须生效（被吞掉的是窗口，不是这个方法）"
    )


def test_quiet_commit_advances_the_counter_without_a_trace(tmp_path: Path) -> None:
    """常态对照：没有并发写者时，取号照常把计数器推前进，且不写痕迹事件。

    这一条同时钉住痕迹的触发基准：常态下盘上值是 3、缓存是 4（确实"盘上 != 缓存"），
    但那条差正是本事务自己的推进。触发条件是"盘上 != 本事务读到的基线"，
    否则每一次普通取号都会写一条痕迹，而那条痕迹的方向会把本事务自己的推进
    说成"别的写者拨低了盘上值"（假归因）。
    """
    from agentflow.store import Store  # noqa: PLC0415
    from agentflow import schema as S  # noqa: PLC0415 - 同上：导入期不许灌 sys.modules

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    st.set_counters({"stmt": SEED}, actor="fixture")
    with st.tx("statements", "counters", actor="quiet") as tx:
        tid = tx.alloc_id("stmt")
    events = _read_events(ws)
    traces = [e for e in events if e.get("message") == TRACE_MESSAGE]
    counters = _read_counters(ws)
    assert tid == S.format_id(3), tid
    assert counters["stmt"] == SEED + 1, counters
    assert counters["stmt"] != SEED, "前提：本事务的推进让盘上与读到的基线不同"
    assert len(events) >= 2, f"反真空：这一笔事务必须留下事件（读到 {len(events)} 条）"
    assert traces == [], f"没有并发写者时不该写痕迹事件：{traces}"


def test_explicit_override_after_the_commit_still_wins(tmp_path: Path) -> None:
    """双向对照之另一头：事务先提交、`set_counters` 后写 ⇒ 显式覆盖必须生效。

    `set_counters` 的 docstring 明写：窗口结束后再调用一次，拨低按正常语义生效。
    把它钉住，免得修法变成"提交永远赢"。
    """
    from agentflow.store import Store  # noqa: PLC0415

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    st.set_counters({"stmt": SEED}, actor="fixture")
    with st.tx("statements", "counters", actor="tx") as tx:
        tx.alloc_id("stmt")
    st.set_counters({"stmt": 111}, actor="override")
    assert _read_counters(ws)["stmt"] == 111, _read_counters(ws)


# --------------------------------------------------------------------------- 负控


def _reverted_copy(tmp_path: Path) -> tuple[Path, Path]:
    """把当前包整树复制到盘外，并把提交块的修法撤掉；返回 (包根, 被改的文件)。"""
    pkg = tmp_path / "negpkg"
    pkg.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_SRC / "agentflow", pkg / "agentflow")
    target = pkg / "agentflow" / "store.py"
    text = target.read_text(encoding="utf-8")
    assert text.count(_FIXED_NEEDLE) == 1, (
        "注入点必须唯一命中 —— 找不到就是负控没生效，那种情况不许被当成通过"
    )
    patched = text.replace(_FIXED_NEEDLE, _PRE_FIX_TEXT)
    assert patched != text, "替换必须真的改到字节"
    assert _PRE_FIX_TEXT in patched, "副本里必须出现改前形态"
    assert _MERGE_CALL not in patched, "撤掉之后提交块里不该再调合并"
    # 逐字节写回：`write_text` 会把 \n 翻成平台行尾（Windows 上变 CRLF），
    # 那会让副本的 sha256 变成一个与判据无关的平台产物，指纹也就不可比了。
    target.write_bytes(patched.encode("utf-8"))
    return pkg, target


def test_pre_fix_commit_swallows_the_set_counters_write(tmp_path: Path) -> None:
    """负控：把修法撤掉 ⇒ 同一条判据必须变红（999 被吞、且没有痕迹事件）。

    副本在 `tmp_path` 里（仓外），它的 sha256 与"注入点确实生效"的断言一起
    当作指纹：没有指纹的负控无法区分"判据有牙"与"我改错了地方"。
    """
    pkg, target = _reverted_copy(tmp_path)
    injected_sha = _sha256(target)
    case = _run_case(pkg, tmp_path / "neg-ws")
    assert case["tx"]["store_file"] == str(target), "负控必须真的跑那份副本"
    assert case["tx"]["store_sha256"] == injected_sha, "跑的必须是注入后的字节"
    assert case["set"]["on_disk"] == {"stmt": OVERRIDE}, (
        f"前置：C 的写入确实落盘（否则红是因为夹具坏了，不是判据在说话）：{case['set']}"
    )
    verdict = _judge(case, override=OVERRIDE, direction="disk_higher", final=OVERRIDE)
    print(f"[指纹] 负控副本 store.py = {target} sha256={injected_sha}"
          f"（改前形态在场，合并调用已撤）；终值 = {case['after_commit']}；痕迹条数 = {verdict['trace_events']}")
    assert not verdict["final_matches"], (
        f"改前形态必须丢掉 999（盘上应为旧缓存值 {SEED + 1}）：{case['after_commit']}"
        f"（负控副本 sha256={injected_sha}）"
    )
    assert verdict["trace_events"] == 0, f"改前形态不该有痕迹事件：{verdict}"
    assert not verdict["pass"], f"负控必须判红：{verdict}（副本 sha256={injected_sha}）"

    baseline = _audit_baseline_store()
    if baseline is None:
        print("[如实登记] 审计冻结的那一版改前 store.py 不在盘上 ⇒ 这一条只跑了注入版负控")
        return
    assert _sha256(baseline) == PRE_FIX_SHA256, (
        f"盘上那份备份必须逐字等于审计冻结字节：{baseline} sha256={_sha256(baseline)}"
    )
    # 前置：这一臂要跑的标本表必须在那一版里存在。
    # 审计冻结的 `a3857e0a…` 早于 `statements` 表（S1r 并表那一笔）：
    # 对它来说 `tx("statements", …)` 是"未知表"（实测：那时 `LOCK_ORDER.index`
    # 抛 `ValueError`），于是子进程进不了事务体、就绪标记永远不出现 ——
    # 症状是 60s 超时，而超时不是判据在说话。这一条与"备份不在盘上"同一口径：
    # 前置不成立就如实登记并跳过那一臂，不假装跑过（也不把它读成通过）。
    if not _baseline_can_open_statements(baseline, tmp_path):
        print("[如实登记] 审计冻结的那一版 store.py（sha256="
              f"{PRE_FIX_SHA256[:16]}…）里还没有 `statements` 表 ⇒ 这一臂不适用，"
              "注入版负控（上一段）已经覆盖同一条判据")
        return
    pkg2 = _baseline_pkg(baseline, tmp_path)
    case2 = _run_case(pkg2, tmp_path / "neg-ws2")
    assert case2["tx"]["store_sha256"] == PRE_FIX_SHA256, "这一臂必须跑审计冻结的那一版字节"
    assert case2["set"]["on_disk"] == {"stmt": OVERRIDE}, case2["set"]
    verdict2 = _judge(case2, override=OVERRIDE, direction="disk_higher", final=OVERRIDE)
    print(f"[指纹] 审计冻结版 store.py sha256={PRE_FIX_SHA256}；终值 = {case2['after_commit']}；"
          f"痕迹条数 = {verdict2['trace_events']}")
    assert not verdict2["pass"], (
        f"审计冻结的那一版必须判红：{verdict2}（sha256={PRE_FIX_SHA256}）"
    )


def _one_way_copy(tmp_path: Path) -> tuple[Path, Path]:
    """`R7-AN-1` 的负控副本：把双向痕迹条件改回单向（只在盘上更高时写）。"""
    pkg = tmp_path / "negpkg-oneway"
    pkg.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_SRC / "agentflow", pkg / "agentflow")
    target = pkg / "agentflow" / "store.py"
    text = target.read_text(encoding="utf-8")
    assert text.count(_TWO_WAY_NEEDLE) == 1, (
        "注入点必须唯一命中（那正是被下一行 continue 消费的那一行）—— "
        "找不到就是负控没生效，不许被当成通过"
    )
    patched = text.replace(_TWO_WAY_NEEDLE, _ONE_WAY_TEXT)
    assert patched != text and _ONE_WAY_TEXT in patched, "替换必须真的改到字节"
    assert _TWO_WAY_NEEDLE not in patched, "副本里不该再有双向条件"
    target.write_bytes(patched.encode("utf-8"))
    return pkg, target


def test_one_way_trace_condition_hides_the_lowering_again(tmp_path: Path) -> None:
    """负控（`R7-AN-1`）：把双向痕迹改回单向 ⇒ 拨低这个方向又变成无痕（判据必须变红）。

    注入点就是"被下一行 continue 消费"的那一行；副本 sha256 打进读数。
    同一份副本上还要跑一次 raising 方向并断言它仍然通过 ——
    那证明这次注入只打掉了"拨低"那一半，不是把整个痕迹机制关掉了。
    """
    pkg, target = _one_way_copy(tmp_path)
    sha = _sha256(target)
    case = _run_case(pkg, tmp_path / "neg-lower", override=OVERRIDE_LOWER)
    assert case["tx"]["store_sha256"] == sha, "负控必须真的跑那份副本"
    assert case["set"]["on_disk"] == {"stmt": OVERRIDE_LOWER}, (
        f"前置：C 的拨低确实落盘：{case['set']}"
    )
    verdict = _judge(case, override=OVERRIDE_LOWER, direction="disk_lower",
                     final=MERGED_WHEN_LOWER)
    print(f"[指纹] 单向痕迹副本 store.py = {target} sha256={sha}；拨低后终值 = "
          f"{case['after_commit']}；痕迹条数 = {verdict['trace_events']}")
    assert verdict["final_matches"], f"终值语义在单向版上也不变：{verdict}"
    assert verdict["trace_events"] == 0, (
        f"单向条件 ⇒ 拨低无痕（这正是 R7-AN-1 的形态）：{verdict}（副本 sha256={sha}）"
    )
    assert not verdict["pass"], f"负控必须判红：{verdict}（副本 sha256={sha}）"

    case_raise = _run_case(pkg, tmp_path / "neg-raise", override=OVERRIDE)
    verdict_raise = _judge(case_raise, override=OVERRIDE, direction="disk_higher", final=OVERRIDE)
    assert verdict_raise["pass"], (
        f"单向条件在 raising 方向本来就成立 ⇒ 这一臂必须仍通过（证明注入只打掉了拨低那一半）："
        f"{verdict_raise}（副本 sha256={sha}）"
    )


def test_the_judgement_is_neither_vacuous_nor_always_false() -> None:
    """判据自校：两种假读数必须判红，两份真读数必须判绿。

    只写"必然失败"那一半是不够的：一个恒假的判据同样没有分辨力。
    """

    def _trace(override: int, final: int, direction: str) -> dict:
        return {"op": "info", "message": TRACE_MESSAGE, "differing": ["stmt"],
                "direction": {"stmt": direction}, "merged_from_disk": ["stmt"],
                "disk": {"stmt": override}, "cache": {"stmt": SEED + 1},
                "baseline": {"stmt": SEED}, "merged": {"stmt": final}}

    higher = _trace(OVERRIDE, OVERRIDE, "disk_higher")
    lower = _trace(OVERRIDE_LOWER, MERGED_WHEN_LOWER, "disk_lower")
    lost = {"events": [], "after_commit": {"stmt": SEED + 1}}
    no_trace = {"events": [{"op": "upsert", "table": "counters"}],
                "after_commit": {"stmt": OVERRIDE}}
    ok_higher = {"events": [higher], "after_commit": {"stmt": OVERRIDE}}
    ok_lower = {"events": [lower], "after_commit": {"stmt": MERGED_WHEN_LOWER}}
    assert _judge(lost, override=OVERRIDE, direction="disk_higher",
                  final=OVERRIDE)["pass"] is False, "丢了更新且没有痕迹 ⇒ 必须红"
    assert _judge(no_trace, override=OVERRIDE, direction="disk_higher",
                  final=OVERRIDE)["pass"] is False, "只保住值而没有痕迹 ⇒ 不许通过"
    assert _judge(ok_higher, override=OVERRIDE, direction="disk_higher",
                  final=OVERRIDE)["pass"] is True, "一份真读数必须能通过（判据不许恒假）"
    assert _judge(ok_lower, override=OVERRIDE_LOWER, direction="disk_lower",
                  final=MERGED_WHEN_LOWER)["pass"] is True, "拨低方向的真读数同样必须通过"


# --------------------------------------------------------------------------- 子进程入口


def _child(argv: list[str]) -> int:
    """子进程入口：按 `--role` 扮演事务方或 `set_counters` 方。

    结果一律写进 `--result` 指定的文件（异常也写），父进程据此判断子进程真的跑了。
    不用 `multiprocessing`：那会让 pytest 的测试模块在子进程里被重新导入。
    """
    ap = argparse.ArgumentParser(description="R6-AN-1 / R7-AN-1 判据的工作子进程")
    ap.add_argument("--role", required=True, choices=("tx", "set"))
    ap.add_argument("--pkg", required=True, help="含 agentflow 包的目录（会被插到 sys.path 最前）")
    ap.add_argument("--root", required=True, help="工作区根")
    ap.add_argument("--override", type=int, default=OVERRIDE,
                    help="窗口里 set_counters 写下的值（999 = 抬高方向，0 = 拨低方向）")
    ap.add_argument("--ready", default="")
    ap.add_argument("--go", default="")
    ap.add_argument("--result", required=True)
    a = ap.parse_args(argv)

    payload: dict = {"ok": False, "role": a.role, "pid": 0}
    try:
        sys.path.insert(0, str(Path(a.pkg).resolve()))
        import agentflow.store as store_mod  # noqa: PLC0415
        from agentflow import schema as S  # noqa: PLC0415

        store_file = Path(store_mod.__file__).resolve()
        assert str(store_file).lower().startswith(str(Path(a.pkg).resolve()).lower()), (
            f"导入到的 store 不在 --pkg 下：{store_file}"
        )
        payload.update({"store_file": str(store_file), "store_sha256": _sha256(store_file),
                        "pid": os.getpid()})
        st = store_mod.Store(a.root)
        if a.role == "tx":
            with st.tx("statements", "counters", actor="child-tx", note="R6-AN-1 夹具") as tx:
                tid = tx.alloc_id("stmt")
                payload.update({
                    "allocated": tid,
                    "tx_cache": dict((st._dirty_counters or {}).get("counters") or {}),
                    "disk_before_set": _read_counters(Path(a.root)),
                })
                # 只写就绪标记（不写结果文件：结果文件是"这一趟结束了"的证据，
                # 中途写一次会让父进程在事务还没提交时就读到一份半成品）。
                #
                # 顺序（这条顺序有判据上的理由，不是风格）：就绪标记紧跟在
                # `alloc_id` 之后，早于建行。本文件的第二臂负控跑的是审计冻结的那一版
                # `store.py`（`a3857e0a…`），它早于 `statements` 表 —— 对它来说
                # `tx("statements", …)` 是"未知表"（实测：那时 `LOCK_ORDER.index`
                # 会抛 `ValueError`）。把标记写在建行之前，窗口的两端（"事务已读
                # counters" 与"提交"）在那一版上照旧成立 ⇒ 该臂仍然测得到它要测的
                # 东西；建成行本身只是"这一笔事务像真的"，不是判据（见下面的注释）。
                if a.ready:
                    Path(a.ready).write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                # 建行：计数器的判据不看它，但"取号 + 建行同一笔事务"是本仓的常态写法。
                # 冻结版上没有 `statements` 表 ⇒ 那一版上如实跳过，并把它记在结果里
                # （不静默：读结果的人看得见这一臂少做了什么）。
                try:
                    tx.upsert("statements", {
                        "stmt_id": tid, "origin": "own_result", "kind": "theorem",
                        "label": "probe", "statement_full": "probe 的命题正文（夹具）",
                        "quote_verified": None, "quote_reason": "自产结果（测试夹具）",
                        "created_at": TS,
                    })
                except (KeyError, ValueError) as exc:
                    payload["row_upsert_skipped"] = (
                        f"{type(exc).__name__}: {exc}（这一版 store/schema 还没有 statements 表）"
                    )
                _wait_for(Path(a.go), "tx 的放行标记")
            payload["after_commit"] = _read_counters(Path(a.root))
        else:
            _wait_for(Path(a.ready), "set 的就绪标记")
            payload["override"] = a.override
            payload["set_counters_returned"] = st.set_counters(
                {"stmt": a.override}, actor="child-set", note="R6-AN-1 / R7-AN-1 夹具")
            payload["on_disk"] = _read_counters(Path(a.root))
        payload["ok"] = True
    except BaseException as exc:  # noqa: BLE001 - 异常也要落盘，否则父进程只看得到"没结果"
        payload["error"] = f"{type(exc).__name__}: {exc}"
    Path(a.result).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - 只有被当脚本跑时才走这里
    raise SystemExit(_child(sys.argv[1:]))
