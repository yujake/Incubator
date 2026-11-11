# -*- coding: utf-8 -*-
"""`runflow.run_topic` 的快照判据（`draft/36` 的 T-7 第 ① 条：拆之前先钉住行为）。
## 为什么 T-7 的尺子与 T-5 不一样
`verify_all` 是纯函数（同一批输入 ⇒ 同一份报告），所以 T-5 的尺子比"报告逐字相同"就够了。`run_topic` 不一样：它会调模型、写六个产物、往四张表里落行。所以这条尺子要钉住"一次运行的全部可观察后果"：
1. 返回值（`exit_code` / `reason` / `artifacts` / `spent_usd_this_run` / `not_wired`…）；
2. `out_dir` 下六件产物的内容（逐字节；时间戳用固定值 `now=TS`，所以不必遮）；
3. 这一次运行在库里落的行（`tasks` / `usage_ledger`）；
4. 公开签名（拆成若干 `_phase_*` 之后，`run_topic` 的形参一个都不许变）。
## 两次运行，两种路径（覆盖"跑模型"与"没查成"两支）
- `ok`：注入了确定性的检索 / 取全文 / 抽取 / 传输层 ⇒ 走完"检索 → 作答 → 回验 → 落产物"；
- `no-key`：`spec` 里没有 key ⇒ 退出码 2 + `retrieval_status=not_configured`（三态那一支）。
## 重新生成
```powershell cd D:\\Incubator\\agentflow$env:PYTHONUTF8='1'; python -B tests/test_runflow_snapshot.py --write ```生成
之后先看 diff：差在哪、为什么。这条命令只该在"行为确实变了"时用。
"""
from __future__ import annotations

import contextlib
import inspect
import json
import os
import pathlib
import shutil
import sys
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = pathlib.Path(__file__).resolve().parent / "golden" / "run_topic_snapshot.json"

#: 固定时间戳：产物里的时间戳必须可复现，否则断言会摇（与 `test_cli_run` 同一取值）。
TS = "2026-01-01T00:00:00+00:00"
KEY = "fixture-key-not-a-secret"
TOKENS_IN = 1000
TOKENS_OUT = 1000
ABSTRACT = "An abelian group is a group in which the commutative law holds."
VERBATIM = "the commutative law holds"

#: 六件产物（`run_topic` 的产出面）。
ARTIFACTS = ("run-manifest.json", "model-transcript.jsonl", "evidence.json",
             "claims.json", "cost.json", "report.md")


def _reply_body(text: str = "阿贝尔群是交换群。") -> str:
    """OpenAI 兼容的成功应答（token 数固定 ⇒ 花销可复算）。"""
    return json.dumps({
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": TOKENS_IN, "completion_tokens": TOKENS_OUT},
    }, ensure_ascii=False)


def _transport(status: int, body: str):
    def _t(url: str, headers, data: bytes, timeout_sec: float):
        return status, body

    return _t


def _search():
    def _s(topic: str, *, limit: int, timeout_sec: float):
        return [{"source": "fixture-search", "title": "Abelian groups", "year": 1930,
                 "doi": "10.1000/fixture", "abstract": ABSTRACT}]

    return _s


def _scrub(obj, replacements: dict[str, str]):
    """把临时目录路径换成占位符（否则快照会钉住当次的随机临时目录，每次都红）。

    与 T-5 那份快照遮时间戳同一个道理：要钉的是"行为"，不是"这次跑在哪个目录"。
    """
    if isinstance(obj, str):
        out = obj
        for real, ph in replacements.items():
            out = out.replace(real, ph)
        return out
    if isinstance(obj, dict):
        return {k: _scrub(v, replacements) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(x, replacements) for x in obj]
    return obj


#: 这一次运行可能读到的进程外配置：单价与峰谷。`modelcost.price_for` 把环境变量
#: 压在最上面（`AGENTFLOW_MODEL_PEAK` / 三档单价），而 `run_topic` 的 `price` 是在
#: `_phase_1` 里现读环境算出来的（`runflow.py:894`）⇒ 同一份代码在"shell 里 export
#: 过单价"的机器上会产出另一个 `run-manifest.json`。快照要钉的是行为，不是"这台机器
#: 的 shell 里有什么"：这一段里把它们摘掉，跑完原样放回。
_ENV_PRICE_NAMES = (
    "AGENTFLOW_MODEL_PEAK",
    "AGENTFLOW_MODEL_PRICE_IN_USD_PER_M",
    "AGENTFLOW_MODEL_PRICE_OUT_USD_PER_M",
    "AGENTFLOW_MODEL_PRICE_IN_HIT_USD_PER_M",
)


class _ClockPin:
    """把 `modelgw` 名字空间里的 `time.monotonic` 钉成 0.0，其余属性原样转发。

    ## 为什么必须钉它（4 并发实测的读数）

    `elapsed_sec` 是"这一次调用花了多少墙钟秒"：`ModelGateway` 用 `time.monotonic()`
    现读两次（`modelgw.py:798/843/857`）、`ModelReply.to_dict()` 舍到毫秒
    （`modelgw.py:694`），然后落进 `model-transcript.jsonl` 与 `run-manifest.json`
    的 `calls[].reply.elapsed_sec`。它是机器速度的读数，不是行为：

    - 单跑：恒为 0.0（探针 24 进程 × 8 轮里非并发时全是 0.0）；
    - 4 个 chunk 并发：同一个进程可能恰好在两次读数之间被调度走一个 Windows 时钟
      tick。本机 CPython 3.11.4 的 `time.monotonic()` 步长实测就是 0.0156 s
      （20 万次连续取值，非零差值只有 0.016 这一种）⇒ `elapsed_sec` 在
      0.0 / 0.015 / 0.016 之间摇，快照的 `files` 于是逐格不等。
    - 读数（`temp/_repro_concurrent.py`，4 进程 × 80 轮）：3/4 个进程各红 1 次，
      红的那个快照里 `elapsed_sec=[0.0, 0.015, 0.0]`、差异格恰好是
      `ok/files/model-transcript.jsonl` 与 `ok/files/run-manifest.json`。

    这不是快照过期、也不是行为变了（重生成逐格相同，因为重生成时单跑、读数为 0.0）。
    处置与 `now=TS` 同一条纪律：把这类"这一次跑在什么机器/什么负载下"的读数钉死。

    ## 为什么不 `monkeypatch.setattr(time, "monotonic", ...)`

    那会改掉整个进程的 `time` 模块（`filelock` 的超时、同进程里其它用例都读它）。
    这里只替换 `modelgw` 模块里的 `time` 名字，产品读时钟的落点只有
    `ModelGateway.__init__` 的 `self._clock = clock or time.monotonic` 一处。
    """

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def monotonic(self) -> float:
        """墙钟读数恒为 0.0 ⇒ `elapsed_sec` 恒为 0.0（见类 docstring）。"""
        return 0.0


@contextlib.contextmanager
def _pinned_provider_env():
    """把那四个会改变计价的环境变量摘掉，跑完原样放回（见 `_ENV_PRICE_NAMES`）。"""
    saved = {name: os.environ[name] for name in _ENV_PRICE_NAMES if name in os.environ}
    for name in _ENV_PRICE_NAMES:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name in _ENV_PRICE_NAMES:
            os.environ.pop(name, None)
        os.environ.update(saved)


@contextlib.contextmanager
def _pinned_clock():
    """在 `run_topic` 跑的这一段里把墙钟钉成 0.0（理由见 `_ClockPin`）。"""
    from agentflow import modelgw as MG

    real = MG.time
    MG.time = _ClockPin(real)
    try:
        yield
    finally:
        MG.time = real


def _run(kind: str, tmp: pathlib.Path) -> dict:
    """跑一次 `run_topic`，把"可观察后果"收成一份可比较的 dict。"""
    from agentflow import runflow as RF
    from agentflow.modelgw import ModelSpec
    from agentflow.store import Store

    ws = tmp / kind / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    out = tmp / kind / "out"
    spec = ModelSpec(api_key=(KEY if kind == "ok" else ""), max_retries=0)

    res = RF.run_topic(st, topic="阿贝尔群", budget_usd=1.0, out_dir=out,
                       transport=_transport(200, _reply_body()), spec=spec,
                       max_calls=3, now=TS, search_fn=_search())

    files = {}
    for name in ARTIFACTS:
        p = out / name
        files[name] = p.read_text(encoding="utf-8") if p.is_file() else None
    gathered = {
        "result": res,
        "files": files,
        "tasks": sorted(({k: str(v) for k, v in r.items() if k != "artifacts"}
                         for r in st.rows("tasks")), key=lambda r: r.get("task_id", "")),
        "usage": sorted(({k: str(v) for k, v in r.items()} for r in st.rows("usage_ledger")),
                        key=lambda r: r.get("usage_id", "")),
    }
    # 两次运行各自一个随机临时目录 ⇒ 路径必须遮掉（见 `_scrub`）
    return _scrub(gathered, {str(tmp): "<TMP>"})


def _snapshot() -> dict:
    """两次运行（`ok` / `no-key`）的全部可观察后果 + `run_topic` 的公开签名。"""
    from agentflow import runflow as RF

    with tempfile.TemporaryDirectory(prefix="runflow-snapshot-") as td:
        tmp = pathlib.Path(td)
        # 这条判据只许依赖自己造的状态：临时目录 + 注入的 spec/transport/search/now。
        # 反过来，凡是"这一次跑在什么机器/什么负载下"的读数都必须钉死 —— 墙钟
        # （`elapsed_sec`）与 shell 里的计价变量，见上面两个 context manager。
        with _pinned_clock(), _pinned_provider_env():
            snap = {kind: _run(kind, tmp) for kind in ("ok", "no-key")}
    snap["signature"] = str(inspect.signature(RF.run_topic))
    return snap


def test_the_snapshot_covers_both_paths_and_all_six_artifacts() -> None:
    """反真空：两次运行都要有，`ok` 那一支的六件产物一件都不许缺。

    没有这条，一份"两次运行都因为夹具坏了而空转"的快照也能绿 ——
    而它正是 T-7 拆分时唯一能挡住"某一段被搬丢"的东西。
    """
    snap = _snapshot()
    assert set(snap) >= {"ok", "no-key", "signature"}, sorted(snap)
    missing = [n for n, v in snap["ok"]["files"].items() if v is None]
    assert not missing, f"`ok` 那一支缺产物：{missing}"
    assert snap["ok"]["result"]["exit_code"] == 0, snap["ok"]["result"]
    assert snap["no-key"]["result"]["exit_code"] == 2, snap["no-key"]["result"]
    assert snap["ok"]["tasks"], "跑完一次运行应当留下 `tasks` 行"
    # 装置自测：墙钟已经钉住 ⇒ 这一次运行的 `elapsed_sec` 必须是 0.0。
    # 没有这一条，时钟钉一旦失效（产品改用别的时钟、或换了落点），核心判据又会退化成
    # "跑多快决定的" —— 而它只会偶发地红，看起来像随机。这里让它红得有名有姓。
    manifest = json.loads(snap["ok"]["files"]["run-manifest.json"])
    elapsed = [c.get("reply", {}).get("elapsed_sec") for c in manifest.get("calls", [])]
    assert elapsed and all(v == 0.0 for v in elapsed), f"时钟钉没有生效：elapsed_sec={elapsed}"


def test_run_topic_behaviour_matches_the_frozen_snapshot() -> None:
    """核心判据：返回值 / 六件产物 / 落库的行 / 公开签名，都必须与冻结快照逐字相同。"""
    if not GOLDEN.is_file():
        pytest.fail(f"快照不存在：{GOLDEN}\n"
                    "生成：python -B tests/test_runflow_snapshot.py --write（先看 diff 再提交）")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    live = _snapshot()

    bad: list[str] = []
    for kind in ("ok", "no-key"):
        if live[kind] != golden.get(kind):
            g, l = golden.get(kind, {}), live[kind]
            for key in sorted(set(g) | set(l)):
                if g.get(key) != l.get(key):
                    bad.append(f"[{kind}] {key}：快照 "
                               f"{json.dumps(g.get(key), ensure_ascii=False)[:220]} ≠ 实跑 "
                               f"{json.dumps(l.get(key), ensure_ascii=False)[:220]}")
    if live["signature"] != golden.get("signature"):
        bad.append(f"[signature] 快照 {golden.get('signature')} ≠ 实跑 {live['signature']}")
    assert not bad, (
        "`run_topic` 的行为与冻结快照不一致（T-7 只许搬移，不许改行为）：\n" + "\n".join(bad))


if __name__ == "__main__":  # pragma: no cover - 只在"行为确实变了"时手动跑
    if "--write" not in sys.argv:
        print(__doc__)
        raise SystemExit(2)
    snap = _snapshot()
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"[ok] 写入快照：{GOLDEN}（{len(snap['ok']['files'])} 件产物 × 2 条路径）")
