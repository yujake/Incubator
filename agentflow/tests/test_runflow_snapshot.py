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

import inspect
import json
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
