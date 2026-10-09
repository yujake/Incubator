# -*- coding: utf-8 -*-
"""`verify_all` 的快照判据（`draft/36` 的 T-5 第 ① 条：拆之前先钉住输出）。

## 为什么先有它

`verify.py::verify_all` 是 1175 行、40 多条不变量的审计本体（FC-27 禁改区）。
T-5 要把它按"表级不变量"拆成若干 `_check_*`。那种拆分最容易出的错不是"报错"，
而是静默改变审计口径：某一条不变量被漏搬、循环范围少了一层、某个 `continue`
在搬移中丢了 —— 而 40 多条判据里少一条，报告照样是一份漂亮的审计报告。

所以先立这条"改前 = 改后"的尺子：对 8 个工作区（3 个真实 + 5 个合成）
把 `verify_all(store).to_dict()` 归一化之后与冻结的快照逐字比对。
拆分只许搬移：搬完之后这份快照必须一个字节都不变（除非你故意改口径 ——
那时要同时改快照，并在 `draft/28` 登记"口径变了"）。

## 快照里两个刻意的归一化（不归一化就测不稳，归一化过头就测不到东西）

1. 时间戳遮成 `<TS>`：真实工作区是"产品跑出来的"，里面必然有"现在"的时间戳
   （例如 `task_still_running` 的消息里带 `started_at=`）。不遮 ⇒ 每次都红；
   遮的范围只限 ISO 时间戳字面量，消息其余部分逐字保留。
2. 两处排序：`issues` 按 `(level, table, row_id, code, message)` 排、JSON 键排序。
   判据比的是"结论集合"，不是"生成顺序" —— 搬移过程中调整了检查的次序是允许的
   （那不改口径），而改变结论集合则会被抓住。

## 重新生成快照

```powershell
cd D:\\Incubator\\agentflow
$env:PYTHONUTF8='1'; python -B tests/test_verify_snapshot.py --write
```
生成之后先看 diff（差在哪、为什么），再提交 —— 这条命令只该在"口径确实变了"时用。
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = pathlib.Path(__file__).resolve().parent / "golden" / "verify_all_snapshot.json"

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from agentflow import conceptrows as CR  # noqa: E402  （并表：概念行的唯一读写口）

_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:?\d{2})?")


# --------------------------------------------------------------------------- 归一化


def _normalize(obj):
    """递归遮时间戳 + 排序（理由见模块 docstring）。"""
    if isinstance(obj, str):
        return _TS_RE.sub("<TS>", obj)
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_normalize(x) for x in obj]
    return obj


def _snapshot_of(store) -> dict:
    """一个工作区的审计结论（归一化 + issues 排序）。

    注意 `VerifyReport.to_dict()` 给的是 `errors` / `warnings` 两个列表，
    没有 `issues` 键（这里的 `issues` 是快照自己的合并视图）。
    第一版读的是 `d["issues"]` ⇒ 永远读到空列表 ⇒ 快照里一条 issue 都没有，
    而"反真空"那条判据当时没跑（生成脚本直接写文件）—— 是它后来抓出来的。
    """
    from agentflow.verify import verify_all

    d = verify_all(store).to_dict()
    raw = list(d.get("errors", [])) + list(d.get("warnings", []))
    issues = sorted(
        ({k: _normalize(v) for k, v in i.items()} for i in raw),
        key=lambda i: (str(i.get("level")), str(i.get("table")), str(i.get("row_id")),
                       str(i.get("code")), str(i.get("message"))),
    )
    out = {k: _normalize(v) for k, v in d.items() if k not in ("errors", "warnings")}
    out["errors"] = sorted(i["code"] for i in issues if i.get("level") == "error")
    out["warnings"] = sorted(i["code"] for i in issues if i.get("level") == "warning")
    out["issues"] = issues
    return out


# --------------------------------------------------------------------------- 8 个工作区


def _real_workspaces(tmp_path: pathlib.Path) -> dict[str, pathlib.Path]:
    """3 个真实工作区：都是产品跑出来的，不是手搭的。

    - `demo/run`：仓库里提交着的 demo 产物（`agentflow demo` 跑出来的）；
    - `默认工作区`：`agentflow/` 自己（`agentflow init` 建的那一套，`data/` 是提交着的）；
    - `fresh-demo`：临时目录里现跑一次 `demo.run_demo`（离线、确定性）——
      这样"真实"不依赖某一份提交物，也不怕它哪天被清掉。

    为什么不用 `test/test2/acceptance-run` 那种跨目录的真实工作区：它在交付物之外，
    把 `agentflow/` 单独拷走之后这条判据就没了。错误路径的覆盖面由 5 个合成工作区负责。
    """
    from agentflow.demo import run_demo
    from agentflow.store import Store

    fresh = tmp_path / "fresh-demo"
    fresh.mkdir(parents=True, exist_ok=True)
    rc = run_demo(fresh, reset=True, verbose=False)
    assert rc == 0, f"夹具前提：`run_demo` 在临时目录里必须返回 0，实得 {rc}"
    # `run_demo(root)` 建的是 `<root>/demo/run/`（与仓库里的 `demo/run/` 同一形态）
    fresh_ws = fresh / "demo" / "run"
    assert (fresh_ws / "data").is_dir(), (
        f"夹具前提：`run_demo` 应当在 {fresh_ws} 下建出工作区，实得 {sorted(p.name for p in fresh.iterdir())}")

    out = {"demo/run": REPO / "demo" / "run", "默认工作区": REPO, "fresh-demo": fresh_ws}
    for name, p in out.items():
        assert (p / "data").is_dir(), f"夹具前提：{name} 应当是一个工作区（有 data/）"
    return out


def _synthetic_workspaces(tmp_path: pathlib.Path) -> dict[str, pathlib.Path]:
    """5 个合成工作区：每个钉住一组不同的不变量，覆盖 `verify_all` 的不同分支。"""
    from agentflow import schema as S
    from agentflow.store import Store

    made: dict[str, pathlib.Path] = {}

    def _store(name: str) -> Store:
        p = tmp_path / name
        p.mkdir(parents=True, exist_ok=True)
        st = Store(p)
        st.init()
        made[name] = p
        return st

    # ① 空库：所有"逐表逐行"的检查都跑一遍但一行都没有（覆盖"零行"分支）
    _store("empty")

    # ② 最小数据集：一条已完成请求 → 一篇已处理文献 → 两个概念 → 一条 active 关系。
    #    注意它故意不同步 counters（所以会报 `counter_behind`）—— 名字叫 `minimal`
    #    而不是 `clean`：一个名不副实的夹具会让后来的人以为"verify 对干净库也报错"。
    st = _store("minimal")
    (st.library / "0000").mkdir(parents=True, exist_ok=True)
    (st.library / "0000" / "source.txt").write_text(
        "An abelian group is a group in which the commutative law holds.", encoding="utf-8")
    with st.tx("search_requests", "literature", actor="test") as tx:
        tx.upsert("search_requests", S.SearchRequest(
            request_id="r-0001", timestamp=S.now_iso(), topic="abelian group", mode="topical",
            done=True, result_lit_ids=["0000"], submitted_by="test").to_dict())
        tx.upsert("literature", S.Literature(
            lit_id="0000", title="Commutativity in abelian groups", type="J",
            summary="满足交换律的群。", path="0000/source.txt", processed=True,
            source_request_ids=["r-0001"], dedup_key="doi:10.1000/demo.abelian",
            doi="10.1000/demo.abelian", year=1930, authors=["A. Author"],
            added_at=S.now_iso()).to_dict())
    # 概念行走过渡层的统一写口（S1r 并表之后 `concepts` 已退役，`tx("concepts")` 会以
    # "未知表"失败）：老形状的行 ⇒ 新标准那一行（概念行住 `statements` 的
    # `kind="concept"`），事务要声明的表由 `tables_for_concept_write` 一处决定。
    with st.tx(*CR.tables_for_concept_write("relations", "counters"), actor="test") as tx:
        for cid, name in (("0000", "group"), ("0001", "abelian group")):
            CR.upsert_legacy_shaped(tx, S.Concept(
                concept_id=cid, name=name, definition=f"{name} 的定义。",
                related_concepts=["0001"] if cid == "0000" else ["0000"],
                created_at=S.now_iso(), updated_at=S.now_iso()).to_dict(), actor="test")
        tx.upsert("relations", S.Relation(
            relation_id="0000", concept_ids=["0000", "0001"], description="包含",
            lit_id="0000", page_range=S.PageRange(1, 1, "pp. 1-1"),
            quote="An abelian group is a group", quote_normalized="an abelian group is a group",
            quote_verified=True, created_at=S.now_iso()).to_dict())

    # ③ 悬空的 artifact（任务行引用了盘上不存在的产物）
    st = _store("dangling-artifact")
    with st.tx("tasks", actor="test") as tx:
        row = S.Task(task_id="t-0001", role="M", action="probe", called_by="cli", depth=1,
                     input_key="probe", status="done", outcome="ok", detail="跑过了",
                     started_at=S.now_iso(), ended_at=S.now_iso(),
                     artifacts=["out/never-existed.json"])
        tx.upsert("tasks", row.to_dict())

    # ④ 悬空的花销（usage_ledger 挂在一个不存在的任务号上）
    st = _store("dangling-usage")
    with st.tx("usage_ledger", "counters", actor="test") as tx:
        uid = tx.alloc_id("usage")
        tx.upsert("usage_ledger", S.UsageEntry(
            usage_id=uid, scope="reason", role="M", task_id="t-9999",
            tokens_in=10, tokens_out=5, tokens_total=15, usd=0.001,
            at=S.now_iso(), note="测试：挂在不存在的任务上").to_dict())

    # ⑤ 僵尸任务（离线审计时仍停在 running ⇒ "没有 end 的 start"）
    st = _store("zombie-task")
    with st.tx("tasks", actor="test") as tx:
        row = S.Task(task_id="t-0001", role="A", action="run_once", called_by="M", depth=1,
                     input_key="", status="running", detail="还没收工",
                     started_at=S.now_iso())
        tx.upsert("tasks", row.to_dict())

    return made


def _all_snapshots(tmp_path: pathlib.Path) -> dict[str, dict]:
    from agentflow.store import Store

    out: dict[str, dict] = {}
    for name, p in _real_workspaces(tmp_path).items():
        out[f"real:{name}"] = _snapshot_of(Store(p))
    for name, p in _synthetic_workspaces(tmp_path).items():
        out[f"synthetic:{name}"] = _snapshot_of(Store(p))
    return out


# --------------------------------------------------------------------------- 判据


def test_the_snapshot_covers_three_real_and_five_synthetic_workspaces(tmp_path: pathlib.Path) -> None:
    """反真空：分析面必须是 3 真实 + 5 合成，且快照里真的有 issue。

    最后那半句是这条判据的重点：一份"8 个工作区、0 条 issue"的快照看起来绿得漂亮，
    却几乎没有判别力（拆分时漏搬一条不变量，它照样绿）。
    第一版就是这样 —— 它读错了 `to_report()` 的键，把 issue 全丢了，
    而生成脚本不跑判据、直接写文件，所以只有这条反真空能当场抓住它。
    """
    snap = _all_snapshots(tmp_path)
    real = [k for k in snap if k.startswith("real:")]
    syn = [k for k in snap if k.startswith("synthetic:")]
    assert len(real) == 3, f"真实工作区应当是 3 个，实得 {real}"
    assert len(syn) == 5, f"合成工作区应当是 5 个，实得 {syn}"

    total = sum(len(v["issues"]) for v in snap.values())
    codes = {i["code"] for v in snap.values() for i in v["issues"]}
    assert total >= 8, (
        f"8 个工作区加起来只有 {total} 条 issue ⇒ 这份快照几乎没有判别力"
        "（夹具太干净，或者读报告的方式错了）")
    assert len(codes) >= 4, f"只覆盖了 {len(codes)} 种 issue 码 {sorted(codes)} ⇒ 覆盖面太窄"
    assert not all(not v["issues"] for v in snap.values()), "一个 issue 都没有"


def test_verify_output_matches_the_frozen_snapshot(tmp_path: pathlib.Path) -> None:
    """核心判据：8 个工作区的审计结论必须与冻结快照逐字相同。

    T-5 的拆分只许搬移 —— 搬完这一条必须仍然绿。它红了只有两种可能：
    ① 口径被改动（漏搬/多搬/循环范围变了）；② 故意改口径但没更新快照。
    两种都要人看一眼，所以报错里逐条列出差异（不是一句"快照不一致"）。
    """
    if not GOLDEN.is_file():
        pytest.fail(
            f"快照文件不存在：{GOLDEN}\n"
            "生成：python -B tests/test_verify_snapshot.py --write（生成后**先看 diff** 再提交）")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    live = _all_snapshots(tmp_path)

    assert set(live) == set(golden), (
        f"工作区集合变了：新增 {sorted(set(live) - set(golden))}、"
        f"少了 {sorted(set(golden) - set(live))}")

    bad: list[str] = []
    for name in sorted(golden):
        if live[name] != golden[name]:
            g, l = golden[name], live[name]
            detail = []
            for key in sorted(set(g) | set(l)):
                if g.get(key) != l.get(key):
                    detail.append(
                        f"{key}: 快照 {json.dumps(g.get(key), ensure_ascii=False)[:200]} ≠ "
                        f"实跑 {json.dumps(l.get(key), ensure_ascii=False)[:200]}")
            bad.append(f"[{name}] " + "；".join(detail))
    assert not bad, (
        "verify 的输出与冻结快照不一致（拆分只许搬移，不许改口径）：\n" + "\n".join(bad))


if __name__ == "__main__":  # pragma: no cover - 只在"故意改口径"时手动跑
    import tempfile

    if "--write" not in sys.argv:
        print(__doc__)
        raise SystemExit(2)
    with tempfile.TemporaryDirectory(prefix="verify-snapshot-") as td:
        snap = _all_snapshots(pathlib.Path(td))
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")
    print(f"[ok] 写入快照：{GOLDEN}（{len(snap)} 个工作区，"
          f"{sum(len(v['issues']) for v in snap.values())} 条 issue）")
