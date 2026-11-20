"""K14 的跨进程工作进程（刻意不叫 `test_*.py`，不被 pytest 收集）。

## 为什么是独立脚本 + 文件通信

与 `tests/_vreview_mp_worker.py` / `tests/_mp_idem_worker.py` 同一口径：

1. 跨平台：Windows 是 `spawn` 起点，子进程会重新导入模块；用 `python <脚本>` 直接
   执行可以绕开 pytest 的夹具发现。
2. 不走管道：受限执行环境里管道是明确的失败面；结果与屏障一律走文件。

## 两种模式

- `--mode pending`：两个进程同时 `verifications.record_pending_sign` 往同一份 pending
  台账追加。`--hold-after-id` 在取号之后睡一段 —— 修前「读行 → 取号 → 追加」三段
  都在锁外，两个进程会读到同一份行、各发 `u-000001`（round 也都是 1）；修后整段在
  同一把跨进程锁里，第二个进程在锁上等，醒来读到第一行、发 `u-000002` / round 2。
  `--no-lock` 是反真空：把修后那把锁换成 `nullcontext`（= 修前形态），撞号必须复现。
- `--mode h`：两个进程同时 `tools.review_tools._advance_review_round` + `record_finding`
  同一份稿。读与写之间的窗口用一个"文件屏障"拉开：两个进程都读完再放行。
  修前两处都在事务外读 ⇒ 轮次各写 1（丢一轮）、同键发现各落一行；修后读-改-写都在
  `store.tx` 的同一次持锁里 ⇒ 轮次 1 → 2、同键发现只有一行。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

#: 与 `tests/conftest.py` 同一口径：注入 `src/`，不要求安装包。
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import verifications as VR  # noqa: E402


def _barrier(directory: Path, name: str, n: int, timeout: float) -> None:
    """文件屏障：写自己的票，然后等齐 `n` 张票（超时抛，不静默继续）。"""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.{os.getpid()}").write_text("1", encoding="utf-8")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if len(list(directory.glob(f"{name}.*"))) >= n:
            return
        time.sleep(0.005)
    got = len(list(directory.glob(f"{name}.*")))
    raise TimeoutError(f"屏障 {name!r} 超时：只等到 {got}/{n} 个进程")


def _run_pending(args: argparse.Namespace) -> dict:
    # 打桩位置（2026-11-20 VERSPLIT2）：这两格的定义已经搬进 `v_pending_write.py`，
    # `verifications.<name>` 只是再导出那一格。函数体里读的是自己模块的全局，所以
    # 只打门面那一格等于打空气（实测：`--no-lock` 下仍然两个号，反真空静默变绿）。
    # 两处都打：定义处（现在生效）与门面那一格（将来若有人把函数体改回按门面查，也在）。
    from agentflow import v_pending_write as VPW

    for _mod, _name in ((VPW, "pending_write_lock"), (VPW, "_next_pending_verification_id"),
                        (VR, "pending_write_lock"), (VR, "_next_pending_verification_id")):
        if not hasattr(_mod, _name):
            raise SystemExit(
                f"{_mod.__name__}.{_name} 不存在 ⇒ 反真空打桩的位置又搬了，先改这里")
    if args.no_lock:
        # 反真空：把修后那把跨进程锁换回"无锁"（= 修前形态）。
        for _mod in (VPW, VR):
            _mod.pending_write_lock = lambda _root: contextlib.nullcontext()  # type: ignore[assignment]
    real = VPW._next_pending_verification_id
    hold = float(args.hold_after_id or 0.0)

    def _slow(root_):  # noqa: ANN001, ANN202 - 钩子签名与 `_next_pending_verification_id` 一致
        got = real(root_)
        if hold:
            time.sleep(hold)
        return got

    for _mod in (VPW, VR):
        _mod._next_pending_verification_id = _slow  # type: ignore[assignment]
    row = VR.record_pending_sign(
        Path(args.root),
        proof_text=args.proof_text,
        verdict={"verdict": "成立", "findings": []},
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "K14 夹具：秘书判 clean"})
    #: 结果里那两格就是判据：`verification_id` 跨文件唯一、`round` 逐行 +1。
    return {"pid": os.getpid(),
            "verification_id": str(row.get("verification_id") or ""),
            "round": row.get("round")}


def _run_h(args: argparse.Namespace) -> dict:
    from agentflow.store import Store
    from agentflow.tools import review_tools as RV

    import agentflow.schema as S

    st = Store(Path(args.root))
    st.init()
    doc_id = str(args.doc_id)
    # 造稿：走 schema 的 Document（字段齐、校验过）——与 `tests/test_agent_h.py` 的
    # `seed_document` 同一形状，但这里不 import 测试模块（子进程没有 conftest）。
    with st.tx("documents", actor="fixture", note="K14 夹具：造一份稿") as tx:
        if not any(str(r.get("doc_id")) == doc_id for r in tx.rows("documents")):
            tx.upsert("documents", S.Document(
                doc_id=doc_id, kind="paper", title="K14 夹具稿", status="draft",
                claims=[{"claim_id": "claim-1", "text": "K14 夹具：一条断言",
                         "citations": ["rel:0000"], "evidence_kind": "cross_check",
                         "disclaimer": "不构成证明", "section": "主要结果",
                         "is_negative": False}],
                content_sha256="c" * 64, review_rounds=0,
                created_at="2026-11-19T00:00:00+08:00", created_by="fixture").to_dict())

    directory = Path(args.barrier_dir) if args.barrier_dir else None
    n, timeout = int(args.n), float(args.timeout)
    real_rows = st.rows
    seen: set[str] = set()

    def _rows(table, *a, **kw):  # noqa: ANN001, ANN202 - 与 `Store.rows` 同签名
        got = real_rows(table, *a, **kw)
        # 每个进程对每张表只同步一次：修前「读在事务外」这一步因此必然发生完，
        # 两个进程才被同时放行去写（窗口由装置拉开，不靠调度运气）。
        if directory is not None and table in ("documents", "review_findings") \
                and table not in seen:
            seen.add(table)
            _barrier(directory, table, n, timeout)
        return got

    st.rows = _rows  # type: ignore[assignment]
    round_no, problem = RV._advance_review_round(st, doc_id, actor="agent-H-1")
    finding = RV.record_finding(
        st, doc_id=doc_id, kind="unsupported_claim", target="claim-1",
        message="K14 夹具：同一条发现",
        evidence="K14 夹具：判据量的是行数，不是这条话",
        actor="agent-H-1")
    return {"pid": os.getpid(), "round": int(round_no), "problem": str(problem or ""),
            "finding_id": str(finding.get("finding_id") or ""),
            "created": bool(finding.get("created")),
            "findings": len(st.rows("review_findings"))}


def run(args: argparse.Namespace) -> dict:
    _barrier(Path(args.barrier_dir), "pre", args.n, args.timeout)
    if args.mode == "pending":
        return _run_pending(args)
    return _run_h(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="K14 的跨进程判据工作进程")
    ap.add_argument("--mode", choices=("pending", "h"), required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--barrier-dir", required=True)
    ap.add_argument("--result", required=True)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--proof-text", default="K14 夹具：同一份正文（pending 台账按正文 sha 分文件）")
    ap.add_argument("--hold-after-id", type=float, default=0.0,
                    help="取号之后睡多久（放大「读-取号-追加」的窗口）")
    ap.add_argument("--no-lock", action="store_true",
                    help="反真空：把 pending 的跨进程锁换回 nullcontext")
    ap.add_argument("--doc-id", default="0000")
    args = ap.parse_args(argv)
    payload: dict
    try:
        payload = {"ok": True, **run(args)}
    except BaseException as e:  # noqa: BLE001 —— 异常也要落盘，否则父进程只看得到"没结果"
        payload = {"ok": False, "pid": os.getpid(),
                   "error": f"{type(e).__name__}: {e}"}
    Path(args.result).parent.mkdir(parents=True, exist_ok=True)
    Path(args.result).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

