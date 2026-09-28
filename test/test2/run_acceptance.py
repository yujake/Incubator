"""验收测试：用这套多智能体框架**独立推导复现** `D:\\Incubator\\test\\main.pdf` 的研究成果。

## 这个脚本在验收什么

不是"我（主控）会不会做这道数学题"，而是：

> **把论文当作一份真实文献灌进去，框架能否自动走完
> 检索登记 → 抽取 → 分析 → 提问 → 矛盾闭环 → 多轮攻坚 → 数值实验 →
> 撰写复现报告 → 独立审校 → 存储一致性校验，并在每一步都留下可审计、可反驳的证据。**

每一步都有**可判定的**验收判据，并且**每一步都可能在报告里被判为"未接线/未做到"**
（那也是一种结果 —— 但不许被悄悄写成"做到了"）。

## 阶段与判据

| 阶段 | 做什么 | 验收判据 |
|---|---|---|
| P1 输入 | 把 PDF 作为**人的**检索结果登记，B 抽取概念/关系 | 引文逐字回验 `verified=25 / failed=0 / unknown=0`；**负控 3 条全部生效** |
| P2 分析 | C 跑四类分析（最热/路径/冷门/缺口） | 生成 4 份报告；`paths(K(m), S̃_m)` 必须能给出**带关系代号链**的路径 |
| P3 研究 | D 消化报告、建问题台账、检测矛盾、走研究循环 | 问题台账非空；**矛盾只取自 strong 信号**；`priority=high` 的请求确实被提交 |
| P4 攻坚 | F 为"复现该论文"立项并多轮推进 | 三维预算完整；轮数用尽必停；`stalled` 必带 `best_partial`；**未接线的子目标如实记 `no_change`** |
| P5 实验 | E 跑 5 个独立复现脚本并登记 `Experiment` | 每条都有 `code_path`+`code_hash`；`evidence_kind` **全部是 `cross_check`**；`supports` 一律配 `not_proved` |
| P6 撰写 | G 出复现报告，登记依赖 | 每条 claim 都有 `citations`；`cross_check` 断言都带 disclaimer；配套书登记为 `external_unavailable` |
| P7 审校 | H 审校 + 复审；**注入一条负控** | 干净稿 `error=0`；注入过度声称 → 必须报 `overclaim`+`error`（证明门真的会响） |
| P8 一致性 | `verify` 全库校验 | 0 error；依赖表里 `external_unavailable` 恰为配套书那条 |

## 诚实边界（写进最终报告，不许含糊）

1. **抽取器的"选择"由人提供**（`paper_seed.SeedExtractor`），不是系统自己读出来的。
   但**抽取结果的正确性由框架验证**（引文逐字回验 + 判重 + I6 闸门）。
2. **`Spec S̃_m = [−m,m]` 是论文引用的**（配套书 [6, Thm. 6.5]），本项目**无法独立验证**它。
   P6 会把这条登记为 `external_unavailable` —— 这是**正确行为**，不是缺陷。
3. **`method="formal"`（真证明）在本环境不可用**（没有 Lean/Coq），
   所以 `evidence_kind="proof"` 这条路径只能靠构造数据验证，**不能端到端跑通**。
4. **F 的 `owner ∈ {C,D,F}` 子目标不会被自动推进** —— 攻坚目前只能被"工具型子目标"驱动。
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
#: `E-9`：P5 的 `_paper_declaration_audit` 要 AST 审复现脚本（判"论文声称值是不是字面量"）
import ast
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
import importlib
import os

# ---------------------------------------------------------------- 目标实现切换
#
# 两个目标：
#   prototype —— `test/test1/src`，包名 `abflow`（第三阶段的原型）
#   formal    —— `agentflow/src`，包名 `agentflow`（正式版）
#
# 用环境变量选：`$env:AGENTFLOW_TARGET='formal'`
#
# 为什么用动态导入而不是 `if TARGET == ...: from abflow import X else: from agentflow import X`：
# 后者要求**两个包同时可导入**，而 prototype/formal 的 `schema.py` 版本并不相同
# （formal 多了 tasks/usage_ledger/eval_results 三张表）—— 同时导入会在 sys.modules 里
# 留下两个不同的 `schema` 模块，那种"同名不同版本共存"是最难查的一类错。
_AGENTFLOW_TARGET = os.environ.get("AGENTFLOW_TARGET", "prototype").strip().lower()
if _AGENTFLOW_TARGET not in ("prototype", "formal"):
    raise SystemExit(
        f"AGENTFLOW_TARGET 必须是 'prototype' 或 'formal'，收到 {_AGENTFLOW_TARGET!r}"
        "（拼错就**静默**跑在原型上，是那种最该炸的错）"
    )

if _AGENTFLOW_TARGET == "formal":
    _SRC = _HERE.parent.parent / "agentflow" / "src"
    PKG = "agentflow"
else:
    _SRC = _HERE.parent / "test1" / "src"
    PKG = "abflow"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _imp(mod: str):
    """按当前目标导入子模块。**包名只在这里出现一次。**"""
    return importlib.import_module(f"{PKG}.{mod}")


S = _imp("schema")
Store = _imp("store").Store

RUN_DIR = _HERE / "acceptance-run"
WORKSPACE = RUN_DIR / "workspace"
REPRO_SRC = _HERE / "repro"


class Phase:
    """一个阶段的执行记录。

    `ok` 三态：`True` 通过 / `False` 失败 / `None` **未执行**（例如依赖的模块不存在）。
    `None` 与 `False` 必须分开 —— "没跑"与"跑了没过"是两件事。
    """

    def __init__(self, key: str, title: str) -> None:
        self.key = key
        self.title = title
        self.ok: bool | None = None
        self.detail: dict[str, Any] = {}
        self.notes: list[str] = []
        self.error: str | None = None
        self.seconds = 0.0

    def to_dict(self) -> dict:
        return {
            "phase": self.key,
            "title": self.title,
            "ok": self.ok,
            "seconds": round(self.seconds, 2),
            "detail": self.detail,
            "notes": self.notes,
            "error": self.error,
        }


class Runner:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.phases: list[Phase] = []

    # ------------------------------------------------------------------ 工具
    def phase(self, key: str, title: str):
        """上下文管理器：跑一个阶段并记录成败。异常被记为 `ok=False` 并把栈打进 error。"""

        class _Ctx:
            def __init__(self, r: Runner) -> None:
                self.r = r

            def __enter__(self) -> Phase:
                self.p = Phase(key, title)
                self.t0 = time.time()
                self.r.phases.append(self.p)
                print(f"\n===== [{key}] {title} =====")
                return self.p

            def __exit__(self, exc_type, exc, tb) -> bool:
                self.p.seconds = time.time() - self.t0
                if exc is not None:
                    self.p.ok = False
                    self.p.error = f"{exc_type.__name__}: {exc}"
                    print(f"  !! 阶段失败：{self.p.error}")
                    traceback.print_exception(exc_type, exc, tb)
                    return True  # 不让一个阶段炸掉整轮验收 —— 但会记下来
                # ⚠️ 这里**不许**替调用方下结论（`E-6`）。
                #
                # 旧版是 `if self.p.ok is None: self.p.ok = True`，而 `Phase.ok` 的契约
                # （上面那段 docstring）是**三态**：True 通过 / False 失败 / None 未执行。
                # 那一行把 `None` 折叠成 `True` ⇒ 阶段里 `if missing: p.ok = None; return`
                # 这类"未接线"分支被记成 PASS，`summary['not_run']` 恒为 0，
                # 终结打印里 `{None: 'N/A '}` 成了死分支。实测最小复现见
                # `temp/auditE-acceptance-probe.json` 的 G1–G4。
                #
                # 现在的口径：**没显式设过 `ok` 就是没结论**（保持 None，由 main 计入非绿）。
                # 为什么不让这里默认成 `False`：那会把"这个阶段什么都没断言"记成失败，
                # 与"这个阶段跑了、断言不过"混在一起 —— 那是把三态折成两态的另一个方向。
                print(f"  -> ok={self.p.ok if self.p.ok is not None else 'None(未执行/未接线)'}"
                      f" ({self.p.seconds:.1f}s)")
                return False

        return _Ctx(self)

    @staticmethod
    def require(obj: Any, names: list[str]) -> list[str]:
        """检查对象是否具备给定方法，返回**缺失**的名单。

        为什么要显式检查而不是直接 `getattr(...)()`：I1/I8 这类交互的前提是
        "那一侧已经接线"。若某方法不存在而我们静默跳过，验收报告会显示"全绿"，
        而实际上**那条交互根本没被测过** —— 这正是本项目最忌讳的静默失败。
        """
        return [n for n in names if not callable(getattr(obj, n, None))]

    def checkpoint(self, p: Phase, cond: bool, msg: str) -> None:
        """一个可判定的验收点。失败即把阶段标红（后续检查仍会跑完）。

        通过时把 `p.ok` 推到 `True`（**除非它已经是 `False`**）：这是"这个阶段真的跑了
        且断言通过"的**唯一**证据来源。为什么必须在这里写而不是在 `__exit__` 里默认写：

        `E-6` 的修法是"`__exit__` 不再把 `None` 折叠成 `True`"（三态纪律）。
        一改完，实测全量验收变成 **10 个阶段全部 `N/A`、exit 2** —— 因为旧实现里
        "有结论"这件事**全靠 `__exit__` 那一行兜底**，`checkpoint()` 只写 `False`。
        也就是说：那一行同时承担了"没接线 ⇒ 未执行（None）"与"跑了、断言都过 ⇒ 通过（True）"
        两件相反的事，而它们只在"这一阶段有没有跑过断言"上才分得开。

        现在的分工是干净的：`checkpoint()` 记"跑到了、这一条过没过"，`__exit__` 只记
        "有没有抛异常"与耗时；**没有任何地方**会在缺少断言证据时替阶段下"通过"的结论。
        """
        if cond:
            print(f"  [OK] {msg}")
            if p.ok is not False:
                p.ok = True
        else:
            print(f"  [!!] {msg}")
            p.ok = False
            p.notes.append(f"未通过：{msg}")


# ====================================================================== 各阶段


def p1_ingest(run: Runner) -> None:
    """P1：把论文作为真实文献灌进去，走 B 的真实抽取路径。"""
    sys.path.insert(0, str(_HERE))
    import paper_seed  # noqa: PLC0415

    with run.phase("P1", "输入：登记文献 + B 抽取（引文逐字回验）") as p:
        quotes = paper_seed.check_quotes(verbose=False)
        p.detail["quotes"] = {
            "total": quotes["total"],
            "verified": quotes["verified"],
            "failed": quotes["failed"],
            "unknown": quotes["unknown"],
            "negative_controls_ok": quotes["gates_ok"],
        }
        run.checkpoint(p, quotes["verified"] == quotes["total"], f"全部 {quotes['total']} 条引文逐字可达")
        run.checkpoint(p, quotes["failed"] == 0 and quotes["unknown"] == 0, "failed=0 且 unknown=0（三分档）")
        run.checkpoint(p, quotes["gates_ok"], "引文门负控 3/3 生效（篡改引文确实被拒）")

        out = paper_seed.ingest_paper(run.store)
        b = out.get("b_result") or {}
        p.detail["b"] = b
        run.checkpoint(p, int(b.get("processed") or 0) == 1, "B 处理了 1 篇文献")
        run.checkpoint(p, int(b.get("quotes_verified") or 0) > 0, f"B 侧回验通过 {b.get('quotes_verified')} 条")
        run.checkpoint(p, int(b.get("quotes_failed") or 0) == 0, "B 侧引文 0 条失败")
        run.checkpoint(p, int(b.get("conflict_checks_skipped") or 0) == 0, "I6 闸门 0 次被跳过（无'没检查'）")


def p2_analyze(run: Runner) -> list[dict]:
    """P2：C 的四类分析。返回登记行列表（供 D 消化）。"""
    AgentC = _imp("agent_c").AgentC

    with run.phase("P2", "分析：C 的四类分析（最热/路径/冷门/缺口）") as p:
        c = AgentC(run.store, config={"hot_top_n": 5})
        rows = run.store.rows("concepts")
        name2id = {str(x.get("name") or ""): str(x.get("concept_id")) for x in rows}
        km, sm = name2id.get("K(m)"), name2id.get("S̃_m")
        p.detail["resolved"] = {"K(m)": km, "S̃_m": sm}
        run.checkpoint(p, bool(km and sm), f"能按名字解析出概念代号 K(m)={km} / S̃_m={sm}")

        reports: list[dict] = []
        for kind, call in (
            ("hottest", lambda: c.hottest(top_n=5, request="最热概念（验收 P2）")),
            ("paths", lambda: c.paths(km, sm, max_paths=5, max_len=4, request="K(m) 与 S̃_m 之间的支撑关系链")),
            ("cold", lambda: c.cold(top_n=5, request="冷门概念（验收 P2）")),
            ("gaps", lambda: c.gaps(limit=10, request="关系图缺口（验收 P2）")),
        ):
            try:
                rep = call()
            except Exception as e:  # noqa: BLE001
                p.notes.append(f"{kind} 分析抛异常：{type(e).__name__}: {e}")
                print(f"  [!!] {kind} 分析抛异常：{e}")
                p.ok = False
                continue
            reports.append({"kind": kind, "payload": getattr(rep, "payload", {}), "markdown": getattr(rep, "markdown", "")})
            # ⚠️ `persist()` **自己**开事务（`alloc_id("report")` 必须在持锁事务内）。
            # 不要再在它外面套一层 `store.tx(...)` —— 那是同进程锁重入。
            row = rep.persist(run.store, actor="agent-C") if hasattr(rep, "persist") else None
            p.detail.setdefault("reports", []).append(
                {
                    "kind": kind,
                    "ok": getattr(rep, "ok", None),
                    "truncated": getattr(rep, "truncated", None),
                    "summary": getattr(rep, "summary", "")[:200],
                    "report_id": (row or {}).get("report_id") if isinstance(row, dict) else None,
                }
            )
            print(f"  [OK] {kind}: {getattr(rep, 'summary', '')[:150]}")

        run.checkpoint(p, len(reports) == 4, f"四类分析各生成 1 份（实际 {len(reports)}）")
        pd = next((x for x in reports if x["kind"] == "paths"), None)
        if pd:
            code_chains = _find_relation_code_chains(pd["payload"])
            p.detail["paths_code_chains"] = code_chains[:5]
            run.checkpoint(p, bool(code_chains), "paths 报告里有**关系代号链**（不是只有自然语言）")
        # 保存报告登记行，供 D 阶段使用
        p.detail["report_ids"] = [x.get("report_id") for x in p.detail.get("reports", [])]
    # ⚠️ 返回的是 **`p.detail`**（含 `report_ids`）而不是 `reports` 列表：
    # D 阶段要按**登记号**去表里读报告，而不是拿内存里的 Report 对象 ——
    # 后者会绕过"报告已落库"这个事实，让"D 读不到报告"这类缺陷测不出来。
    return p.detail


def p2b_interactions(run: Runner) -> dict:
    """P2b：把 I1–I7 **逐条**走一遍（每条一个可判定断言）。

    为什么单独设一个阶段：P1/P2/P3 顺带覆盖了 I6（闸门计数）与 I3（缺口提交），
    但 I1/I4/I5/I7 的**端到端**行为不在主流程的必经之路上。
    若不做这一步，验收报告会显示"全绿"，而实际上**那四条交互从没被测过** ——
    这正是"可观测性 ≠ 正确性"。
    """
    AgentB = _imp("agent_b").AgentB
    AgentC = _imp("agent_c").AgentC
    extract_text = _imp("extract").extract_text
    NullExtractor = _imp("llm").NullExtractor

    def knowledge_bytes() -> dict[str, bytes]:
        out = {}
        for f in ("concepts.json", "relations.json", "literature.json"):
            p = run.store.data / f
            out[f] = p.read_bytes() if p.exists() else b""
        return out

    with run.phase("P2b", "交互抽查：I1/I3/I4/I5/I7 逐条端到端") as p:
        c = AgentC(run.store, config={})
        b = AgentB(run.store, extractor=NullExtractor(), extract_text=extract_text, config={})
        rows = run.store.rows("concepts")
        name2id = {str(x.get("name") or ""): str(x.get("concept_id")) for x in rows}
        km, sm = name2id.get("K(m)"), name2id.get("S̃_m")

        # ---------------- I1：C 作为可调用服务（只读、有界、三态）
        before = knowledge_bytes()
        svc: dict[str, Any] = {}
        for api in ("neighbors", "relations_between", "contradictions", "structural_duplicates"):
            fn = getattr(c, api, None)
            if not callable(fn):
                p.notes.append(f"I1 **未接线**：AgentC 缺 {api}()")
                p.ok = False
                continue
            try:
                if api == "neighbors":
                    r = fn(km, depth=2, max_nodes=200)
                elif api == "relations_between":
                    r = fn(km, sm)
                else:
                    r = fn()
            except Exception as e:  # noqa: BLE001
                p.notes.append(f"I1 {api}() 抛异常：{type(e).__name__}: {e}")
                p.ok = False
                continue
            svc[api] = r
        p.detail["I1_services"] = {
            k: {
                "checked": v.get("checked"),
                "empty": v.get("empty"),
                "truncated": v.get("truncated"),
                "count": len(v.get("nodes") or v.get("relation_ids") or v.get("contradictions")
                             or v.get("candidates") or []),
                "reason": str(v.get("reason") or "")[:180],
            }
            for k, v in svc.items()
        }
        run.checkpoint(p, all(v.get("checked") is True for v in svc.values()),
                       f"I1：4 个服务方法都返回 checked=True（实际 {sorted(svc)}）")
        run.checkpoint(p, knowledge_bytes() == before,
                       "I1：**服务面只读** —— 三张知识表逐字节不变")
        rb = svc.get("relations_between") or {}
        run.checkpoint(p, bool(rb.get("relation_ids")),
                       f"I1：relations_between(K(m), S̃_m) 找到 {len(rb.get('relation_ids') or [])} 条关系")

        # ---------------- I3：缺口直连 A（C 的 gaps 候选 → search_requests）
        gaps_fn = getattr(c, "gaps", None)
        if not callable(gaps_fn):
            p.notes.append("I3 **未接线**：AgentC 缺 gaps()")
            p.ok = False
        else:
            before_req = {r.get("request_id") for r in run.store.rows("search_requests")}
            rep = gaps_fn(limit=10, request="验收 P2b：缺口直连", submit_requests=True)
            after_req = {r.get("request_id") for r in run.store.rows("search_requests")}
            new = sorted(after_req - before_req)
            sub = [r for r in run.store.rows("search_requests") if r.get("request_id") in new]
            p.detail["I3"] = {
                "new_request_ids": new,
                "priorities": sorted({str(x.get("priority")) for x in sub}),
                "submitters": sorted({str(x.get("submitted_by")) for x in sub}),
                "payload_keys": sorted((rep.payload or {}).keys()) if hasattr(rep, "payload") else [],
                "cap": 3,
            }
            run.checkpoint(p, len(new) <= 3, f"I3：新增请求 {len(new)} ≤ 上限 3")
            run.checkpoint(p, all(str(x.get("submitted_by")) == "agent-C" for x in sub),
                           "I3：新请求 submitted_by 都是 agent-C")
            run.checkpoint(p, all(str(x.get("priority")) == "medium" for x in sub),
                           "I3：C 的请求优先级是 medium（I7 表）")
            # 负控：默认关闭时一条都不新增
            before2 = {r.get("request_id") for r in run.store.rows("search_requests")}
            gaps_fn(limit=10, request="验收 P2b：关闭提交", submit_requests=False)
            after2 = {r.get("request_id") for r in run.store.rows("search_requests")}
            run.checkpoint(p, before2 == after2,
                           "I3 **负控**：submit_requests=False（默认）时一条都不新增")

        # ---------------- I4：定向重抽取（只改目标、不重置 processed）
        #
        # ⚠️ 目标的选择要保证这条交互**真的被走到**：优先挑一条 `quote_verified=False`
        # 的关系（走 `quote_unverifiable` 路径）；本数据集里没有这样的关系时，
        # 退而用 `need_context`（只读路径）—— 否则 `run_reprocess()` 会因为
        # "没有待办"直接返回，而验收报告会显示通过，**实际上什么都没测**。
        all_rels = run.store.rows("relations")
        rid_target = next((str(r.get("relation_id")) for r in all_rels if r.get("quote_verified") is False), None)
        reason4 = "quote_unverifiable"
        if rid_target is None and all_rels:
            rid_target = str(all_rels[0].get("relation_id"))
            reason4 = "need_context"
        if not callable(getattr(b, "run_reprocess", None)):
            p.notes.append("I4 **未接线**：AgentB 缺 run_reprocess()")
            p.ok = False
        else:
            lit_before = (run.store.data / "literature.json").read_bytes()
            before_rel = {r["relation_id"]: dict(r) for r in run.store.rows("relations")}
            if rid_target:
                with run.store.tx("reprocess_requests", actor="human", note="acceptance I4") as tx:
                    pid = I_next_prefixed(tx.rows("reprocess_requests"), "reprocess_id")
                    tx.upsert("reprocess_requests", S.ReprocessRequest(
                        reprocess_id=pid, timestamp=S.now_iso(), reason=reason4,
                        submitted_by="human", relation_ids=[rid_target],
                        detail=f"验收 P2b：定向重抽取 {rid_target}（reason={reason4}）",
                    ).to_dict())
            got = b.run_reprocess()
            p.detail["I4"] = _digest_obj(got)
            p.detail["I4"]["target"] = rid_target
            p.detail["I4"]["reason"] = reason4
            rrows = run.store.rows("reprocess_requests")
            p.detail["I4"]["rows"] = [
                {"reprocess_id": x["reprocess_id"], "status": x["status"], "result": x.get("result"),
                 "touched": x.get("touched_relation_ids"), "target": x.get("relation_ids"),
                 "note": str(x.get("result_note") or "")[:160]}
                for x in rrows
            ]
            done = [x for x in rrows if str(x.get("status")) == "done"]
            p.notes.append(
                f"I4：目标 {rid_target}（reason={reason4}），受理 {len(rrows)} 条、完成 {len(done)} 条"
            )
            run.checkpoint(p, bool(rrows) and len(done) == len(rrows),
                           f"I4：提交的 {len(rrows)} 条重抽取请求全部有了终态（不是挂着的 pending）")
            p.detail["I4"]["results"] = sorted({str(x.get("result")) for x in done})
            run.checkpoint(p, all(str(x.get("result") or "").strip() for x in done),
                           "I4：每条完成的重抽取都给出了 result（'做了但没结果'不许留空）")
            run.checkpoint(p, (run.store.data / "literature.json").read_bytes() == lit_before,
                           "I4：**绝不重置 literature.processed**（literature.json 逐字节不变）")
            after_rel = {r["relation_id"]: dict(r) for r in run.store.rows("relations")}
            changed = sorted(k for k in before_rel if before_rel[k] != after_rel.get(k))
            p.detail["I4"]["changed_relations"] = changed
            if rid_target:
                run.checkpoint(p, set(changed) <= {rid_target},
                               f"I4：**只改动目标关系**（实际改动 {changed}，目标 {rid_target}）")
            else:
                run.checkpoint(p, changed == [], "I4：无可重抽取目标时，关系表一行未变（不是假装做了）")

        # ---------------- I5：结构重复（C 提出，B 决定）
        sd = svc.get("structural_duplicates") or {}
        cands = [x for x in (sd.get("candidates") or []) if not x.get("is_truncation_notice")]
        p.detail["I5"] = {"candidates": len(cands), "checked": sd.get("checked"),
                          "detail": [{k: c.get(k) for k in ("concept_ids", "proposal", "name_evidence")}
                                     for c in cands[:5]]}
        if not callable(getattr(b, "resolve_structural_duplicate", None)):
            p.notes.append("I5 **未接线**：AgentB 缺 resolve_structural_duplicate()")
            p.ok = False
        else:
            before5 = knowledge_bytes()
            outcomes = [ _digest_obj(b.resolve_structural_duplicate(x)) for x in cands[:3] ]
            p.detail["I5"]["outcomes"] = outcomes
            if not cands:
                run.checkpoint(p, knowledge_bytes() == before5,
                               "I5：**查了、没有候选** ⇒ 知识表一行未变（三态里的'查了没有'）")
            else:
                merged = [x.get("verdict") == "merge" for x in outcomes]
                p.notes.append(f"I5：{len(cands)} 个候选，实际合并 {sum(1 for m in merged if m)} 个")

        # ---------------- I7：A 按优先级取任务
        with run.store.tx("search_requests", actor="human", note="acceptance I7") as tx:
            lo = I_next_prefixed(tx.rows("search_requests"))
            tx.upsert("search_requests", S.SearchRequest(
                request_id=lo, timestamp=S.now_iso(), topic="验收：低优先级", mode="topical",
                submitted_by="agent-B", priority="low", submit_note="acceptance I7",
            ).to_dict())
            hi = I_next_prefixed(tx.rows("search_requests"))
            tx.upsert("search_requests", S.SearchRequest(
                request_id=hi, timestamp=S.now_iso(), topic="验收：高优先级", mode="topical",
                submitted_by="human", priority="high", submit_note="acceptance I7",
            ).to_dict())
        I = _imp("interactions")

        ordered = I.order_pending_requests(run.store.rows("search_requests"))
        p.detail["I7"] = {"order": [x["request_id"] for x in ordered][:6],
                          "priorities": [x.get("priority") for x in ordered][:6],
                          "high_id": hi, "low_id": lo}
        first_high = next((i for i, x in enumerate(ordered) if x.get("priority") == "high"), None)
        last_low = max((i for i, x in enumerate(ordered) if x.get("priority") == "low"), default=-1)
        run.checkpoint(p, first_high is not None and first_high < last_low,
                       "I7：排序里 high 全部排在 low 之前")
        a = None
        try:
            AgentA = _imp("agent_a").AgentA

            a = AgentA(run.store, config={"providers": [], "download": False}, providers=[], downloader=None)
        except Exception as e:  # noqa: BLE001
            p.notes.append(
                f"I7：AgentA 构造失败（{type(e).__name__}: {e}）⇒ 跳过'真的被 A 取走'这一步。"
                "排序本身已单独断言，但**注意这一条没有被端到端验证**"
            )
        if a is None:
            pass
        else:
            try:
                res = a.run_once()
                got_prio = getattr(res, "priority", None)
                p.detail["I7"]["claim"] = {"request_id": getattr(res, "request_id", None),
                                           "priority": got_prio,
                                           "queue_pending": getattr(res, "queue_pending", None)}
                run.checkpoint(p, got_prio == "high", f"I7：A 实际取走的是高优先级（priority={got_prio}）")
            except Exception as e:  # noqa: BLE001
                p.notes.append(
                    f"I7：A.run_once() 抛异常（本环境无检索后端，属预期）：{type(e).__name__}: {e}"
                )
                p.ok = None
        return p.detail


def I_next_prefixed(rows: Any, field: str = "request_id") -> str:
    """生成 ``r-NNNN`` / ``p-NNNN``（复用冻结契约里的唯一实现）。

    ⚠️ **字段名必须由调用方给出。** 最初这个帮手把 `field` 写死成 `"request_id"`，
    而重抽取请求表的字段叫 `reprocess_id` —— 于是它在 `reprocess_requests` 上生成了
    `r-0001`（因为一个 `r-` 开头的值都没找到），而 `verify` 会对这个表做
    `int("r-0001")` 并**自己崩掉**。一个参数名写错，两个模块各自出现一个字面上看不出来的错。
    """
    I = _imp("interactions")

    prefix = "p" if field == "reprocess_id" else "r"
    return I.next_prefixed_id(rows, field, prefix)


def _find_relation_code_chains(payload: Any) -> list[list[str]]:
    """在 C 的 payload 里找形如 ``["0001","0007",…]`` 的关系代号链。"""
    found: list[list[str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("relation_ids", "chain", "relation_chain") and isinstance(v, list):
                    ids = [str(x) for x in v if isinstance(x, (str, int)) and str(x).isdigit()]
                    if len(ids) >= 2:
                        found.append(ids)
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(payload)
    return found


def p3_research(run: Runner, p2: dict) -> dict:
    """P3：D 消化报告、建台账、矛盾闭环、提交检索请求。

    `p2` 是 P2 阶段返回的 detail（含 `report_ids`）。D 必须按**登记号**去表里读报告，
    而不是拿 P2 内存里的对象 —— 后者会绕过"报告确实落库了"这个事实。
    """
    AgentD = _imp("agent_d").AgentD

    with run.phase("P3", "研究：D 建问题台账 + 矛盾闭环 + 提交检索请求") as p:
        d = AgentD(run.store, config={"reports_dir": str(WORKSPACE / "reports")})
        report_ids = [x for x in ((p2 or {}).get("report_ids") or []) if x]
        p.detail["input_report_ids"] = report_ids
        run.checkpoint(p, bool(report_ids), f"拿到 {len(report_ids)} 份 C 报告的登记号")

        qids: list[str] = []
        by_id = {str(r.get("report_id")): r for r in run.store.rows("analysis_reports")}
        for rid in report_ids:
            row = by_id.get(str(rid))
            if row is None:
                p.notes.append(f"报告 {rid} 不在 analysis_reports 表里 —— D 无从消化")
                continue
            try:
                # ⚠️ 传**整行 dict**（含 payload），不是 report_id 字符串。
                # 传字符串会让 `_as_report_dict` 得到一个空报告 ⇒ 候选问题为 0，
                # 而它**不会报错** —— 这正是"静默失败"的典型形态。
                got = d.ingest(row)
            except Exception as e:  # noqa: BLE001
                p.notes.append(f"ingest({rid}) 抛异常：{type(e).__name__}: {e}")
                continue
            qids.extend([x for x in _as_id_list(got) if x])
            dec = getattr(d, "last_ingest", {}) or {}
            p.detail.setdefault("ingest_per_report", []).append(
                {
                    "report_id": rid,
                    "kind": row.get("kind"),
                    "new_questions": len(_as_id_list(got)),
                    "candidates": len(dec.get("candidates") or []),
                    "merged": len(dec.get("merged") or []),
                    "equivalent_matched": len(dec.get("equivalent_matched") or []),
                    "skipped": dec.get("skipped"),
                    "contradictions": dec.get("contradictions"),
                }
            )
        qids = sorted(set(qids))
        p.detail["questions_after_ingest"] = qids
        run.checkpoint(p, bool(qids), f"消化的报告产出了 {len(qids)} 个研究问题")

        kinds = {str(q.get("status")) for q in run.store.rows("research_questions")}
        p.detail["question_statuses"] = sorted(kinds)

        # 走一轮研究循环
        try:
            first = by_id.get(str(report_ids[0])) if report_ids else None
            rr = d.run_round(first, limit=3) if first is not None else d.run_round(limit=3)
        except Exception as e:  # noqa: BLE001
            p.notes.append(f"run_round 抛异常：{type(e).__name__}: {e}")
            rr = {"error": f"{type(e).__name__}: {e}"}
        p.detail["run_round"] = _digest_obj(rr)

        qrows = run.store.rows("research_questions")
        p.detail["questions_total"] = len(qrows)
        heavy = [q for q in qrows if str(q.get("priority")) == "high"]
        p.detail["high_priority_questions"] = len(heavy)
        run.checkpoint(p, len(qrows) >= len(qids), "问题台账只增不减（没有静默丢问题）")

        reqs = run.store.rows("search_requests")
        submitted = [x for x in reqs if str(x.get("submitted_by")) != "human"]
        p.detail["search_requests_by_submitter"] = sorted({str(x.get("submitted_by")) for x in reqs})
        p.detail["machine_submitted_requests"] = len(submitted)
        p.notes.append(
            f"机器提交的检索请求 {len(submitted)} 条"
            + ("（>0 说明缺口/矛盾闭环真的回流到 A 了）" if submitted else "（**本环境无网络检索后端，0 条是预期结果**）")
        )

        # 矛盾记录：只允许 strong 驱动问题
        cons = run.store.rows("concepts")
        p.detail["contradiction_questions"] = sum(
            1 for q in qrows if str(q.get("kind")) == "contradiction"
        )
        p.detail["concept_count"] = len(cons)

        try:
            out = d.write_report(str(WORKSPACE / "research-report.md"))
            p.detail["research_report"] = str(out)
            run.checkpoint(p, Path(str(out)).exists(), "D 写出了研究报告")
        except Exception as e:  # noqa: BLE001
            p.notes.append(f"write_report 抛异常：{type(e).__name__}: {e}")
    return p.detail


def p4_attack(run: Runner) -> dict:
    """P4：F 为"复现该论文"立项，多轮推进。"""
    AgentF = _imp("agent_f").AgentF

    with run.phase("P4", "攻坚：F 立项 + 多轮推进 + 预算终止") as p:
        missing = run.require(AgentF, ["create_plan", "step", "status"])
        if missing:
            p.ok = None
            p.notes.append(f"未接线：AgentF 缺少 {missing}")
            return p.detail
        f = AgentF(run.store, config={})
        subgoals = [
            {"sid": "sg1", "text": "独立数值验证 Spec K(m) = [−m,m]（m=3,4,5）", "owner": "E",
             "status": "todo", "script_path": "repro/exp1_k_spectrum.py", "claim_key": "SpecK(m)=[-m,m]"},
            {"sid": "sg2", "text": "独立数值验证 girth K(m)=6 与 girth S̃_m（m=3,4,5）", "owner": "E",
             "status": "todo", "script_path": "repro/exp2_girths.py", "claim_key": "girth"},
            {"sid": "sg3", "text": "独立数值探测 Spec S̃_m 的区间填充性（含 m=6 公开问题）", "owner": "E",
             "status": "todo", "script_path": "repro/exp3_chamber_spectrum.py", "claim_key": "SpecStilde(m)=[-m,m]"},
            {"sid": "sg4", "text": "独立验证 |V_K/Λ| = 2m^{m−1} 与 m-正则性", "owner": "E",
             "status": "todo", "script_path": "repro/exp4_size_regularity.py", "claim_key": "size_regularity"},
            {"sid": "sg5", "text": "独立验证 K(m) 与 S̃_m 不同构（同度数、不同围长）", "owner": "E",
             "status": "todo", "script_path": "repro/exp5_noniso.py", "claim_key": "nonisomorphic_cospectral"},
            {"sid": "sg6", "text": "检索配套书 [6] Thm 6.5 以独立验证 Spec S̃_m 的前提", "owner": "A",
             "status": "todo"},
            {"sid": "sg7", "text": "判定 Theorem 1.5 的论证是否闭合（依赖是否可独立获得）", "owner": "D",
             "status": "todo"},
        ]
        created = f.create_plan(
            "独立推导复现 main.pdf 的研究成果（Cospectral periodic graphs）",
            "reproduce:main.pdf",
            subgoals=subgoals,
            # ⚠️ 显式给预算：默认 `max_rounds=6` 小于本任务的 7 个子目标，
            # 会在还没轮到实验子目标时就 `stalled`—— 那样验收看到的是"预算不够"而不是
            # "框架跑不通"。两件事必须分开（不然会把配置问题误读成能力问题）。
            budget={"max_rounds": 9, "max_parallel_subgoals": 1,
                    "max_persist_attempts": 2, "max_depth": 1},
        )
        p.detail["create_plan"] = _digest_obj(created)
        plan_id = created.get("plan_id")
        run.checkpoint(p, bool(plan_id), f"立项成功 plan_id={plan_id}")
        if not plan_id:
            return p.detail

        timeline: list[dict] = []
        for _ in range(12):  # 远大于预算，用来证明"它会自己停"
            got = f.step(plan_id)
            timeline.append(_digest_obj(got))
            if str(got.get("status")) in ("resolved", "abandoned", "stalled", "supported_not_proved"):
                break
        p.detail["timeline"] = timeline
        p.detail["steps"] = len(timeline)

        rows = {x["plan_id"]: x for x in run.store.rows("attack_plans")}
        plan = rows.get(plan_id) or {}
        p.detail["final_status"] = plan.get("status")
        p.detail["rounds"] = plan.get("rounds")
        p.detail["budget"] = plan.get("budget")
        run.checkpoint(p, bool(plan.get("budget")), "三维预算已写入计划")
        run.checkpoint(
            p, int(plan.get("rounds") or 0) <= int((plan.get("budget") or {}).get("max_rounds", 0)),
            f"轮数 {plan.get('rounds')} 未超上限 {(plan.get('budget') or {}).get('max_rounds')}",
        )
        run.checkpoint(
            p, len(timeline) < 12,
            "**终止性**：循环在预算内自行停下（没有跑满 12 次）",
        )
        no_change = [x for x in timeline if x.get("outcome") == "no_change"]
        p.detail["no_change_rounds"] = len(no_change)
        p.notes.append(
            f"{len(no_change)} 轮被如实记为 no_change（owner∈{{C,D,F}} 的子目标不会被假装推进）"
        )
        if str(plan.get("status")) == "stalled":
            run.checkpoint(p, bool(str(plan.get("best_partial") or "").strip()),
                           "stalled 时带上了 best_partial（不谎报成功，也不丢中间成果）")
        return p.detail


#: 只有这些前缀的模块级字面量常量才算"论文声称的数值"（`E-9`）。
#: 为什么用命名约定而不是"所有字面量常量"：后者会把 `BUGS` / `DEFAULT_MAX_SECONDS` /
#: `GRID_POINTS` 这些**调参**常量也算进来（第一版就是这么误伤 5 个脚本的）。
PAPER_VALUE_PREFIXES = ("EXPECT_", "PAPER_VALUE_")


def _paper_declaration_audit(script: Path, claim: str) -> dict:
    """AST 审一个复现脚本：它的"论文声称值"是不是**可复核的声明**（`E-9`）。

    返回 `{"problems": [...], "expect_constants": [...], "anchored_checks": n}`。
    `problems` 空 = 合格。判据逐条：

    1. `PAPER_CLAIM` 存在、非空字符串、且与验收计划里那一句**逐字相等** ——
       「脚本说它验的是哪句」与「计划说论文的哪句」必须对得上。
    2. `EXPECT_*` / `PAPER_VALUE_*` 常量的右手边**必须是字面量**（`ast.literal_eval` 能求值）。
       把 `EXPECT_GIRTH_K = 6` 改成计算表达式 ⇒ 这一条当场红，而那正是 `E-9` 要堵的
       "改成计算值也能 PASS"。
    3. 每一个这样的常量都必须在一次 `ast.Compare` 里被用到 —— 声明了不比较 = 装饰。
    4. 至少一个 `check(...)`/`check_maybe(...)` 调用把这些常量之一当参数 ——
       判据要锚在**声称值**上，而不是两个计算值互相印证。

    脚本若**没有**这类常量，本条不报 problem（不逼 AI 凭空写论文常数），
    但调用方必须把它列进 `uncovered` 名单 —— 缺口要可见，不许静默通过。
    """
    problems: list[str] = []
    src = script.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return {"problems": [f"{script.name} 语法错误，无法审计：{exc}"],
                "expect_constants": [], "anchored_checks": 0}

    literals: dict[str, int] = {}
    non_literal: dict[str, int] = {}
    paper_claim: str | None = None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if tgt.id == "PAPER_CLAIM":
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                paper_claim = node.value.value
            continue
        if not tgt.id.startswith(PAPER_VALUE_PREFIXES):
            continue
        try:
            ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            non_literal[tgt.id] = node.lineno
            continue
        literals[tgt.id] = node.lineno

    for name, lineno in sorted(non_literal.items(), key=lambda kv: kv[1]):
        problems.append(
            f"{script.name} 的 `{name}`（第 {lineno} 行）右手边**不是字面量** —— "
            "论文声称值必须写死；由代码算出来时，『论文常数 vs 独立计算』"
            "就退化成『这段代码 vs 那段代码』（`E-9`）"
        )

    used_in_compare: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id in literals:
                    used_in_compare.add(sub.id)
    for name in sorted(literals, key=lambda n: literals[n]):
        if name not in used_in_compare:
            problems.append(
                f"{script.name} 的 `{name}`（第 {literals[name]} 行）声明了却没有任何比较用它"
            )

    anchored = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        fname = getattr(f, "attr", getattr(f, "id", ""))
        if fname not in ("check", "check_maybe"):
            continue
        names = {s.id for s in ast.walk(node) if isinstance(s, ast.Name)}
        if names & set(literals):
            anchored += 1
    if literals and anchored == 0:
        problems.append(
            f"{script.name} 的 check 判据里没有任何一条用到上面那些字面量常量 —— "
            "判据没有锚在论文声称值上"
        )

    if paper_claim is None:
        problems.append(
            f"{script.name} 缺模块级 `PAPER_CLAIM`（字符串字面量）—— 脚本必须自己说清"
            "『我验的是论文里的哪一句』，且那句话要与验收计划里的逐字相同"
        )
    elif paper_claim.strip() != claim.strip():
        problems.append(
            f"{script.name} 的 `PAPER_CLAIM` 与验收计划里那一句不一致："
            f"脚本说 {paper_claim!r}，计划说 {claim!r}"
        )
    return {"problems": problems, "expect_constants": sorted(literals),
            "anchored_checks": anchored}

def p5_experiments(run: Runner) -> dict:
    """P5：E 跑 5 个独立复现脚本并登记实验。"""
    AgentE = _imp("agent_e").AgentE

    with run.phase("P5", "实验：E 跑 5 个独立复现脚本 + 登记证据等级") as p:
        missing = run.require(AgentE, ["run_experiment", "evidence_for"])
        if missing:
            p.ok = None
            p.notes.append(f"未接线：AgentE 缺少 {missing}")
            return p.detail
        e = AgentE(run.store, config={}, workspace_root=WORKSPACE)
        plan = [
            ("exp1", "Spec K(m) = [−m, m]（m=3,4,5）", "SpecK(m)=[-m,m]", "repro/exp1_k_spectrum.py"),
            ("exp2", "girth K(m)=6；girth S̃_m=6（m=3）/4（m≥4）", "girth", "repro/exp2_girths.py"),
            ("exp3", "Spec S̃_m 的区间填充性（3≤m≤5 数值旁证；m=6 公开问题）",
             "SpecStilde(m)=[-m,m]", "repro/exp3_chamber_spectrum.py"),
            ("exp4", "|V_K/Λ| = 2m^{m−1}（m=3,4,5）与 m-正则性", "size_regularity",
             "repro/exp4_size_regularity.py"),
            ("exp5", "K(m) 与 S̃_m 同谱但不同构（m=4,5）", "nonisomorphic_cospectral",
             "repro/exp5_noniso.py"),
        ]
        # ⚠️ P4 的 F 可能已经把同一批实验跑过了。这里**复用已有记录**，
        # 不重跑：重跑不仅浪费（exp3 可能要几分钟），还会把"P4 已推进"这个
        # 事实淹没掉—— 验收报告就看不出两个阶段是否真的共享了同一批证据。
        #
        # ⚠️⚠️ 复用的判据必须是 **code_path（脚本）**，不是 `claim_key`。
        # 同一个脚本就是同一个实验；而 F 按**子目标**命名 claim_key
        # （`reproduce:main.pdf#sg1`），P5 按**论文命题**命名
        # （`SpecK(m)=[-m,m]`）。按 claim_key 查重于是永远查不到，
        # 同一批脚本被完整跑了两遍。
        #
        # 实测（本阶段的孤立验收）：experiments 表里 10 行、5 个脚本，
        # 每个脚本恰好两行，P4 花了 247s、P5 又花 267s 做同一件事，
        # 而 P5 的判据 `len(rows) == 5` 于是必然报红。
        #
        # 这条本身是个值得记下的模式：**判重键选错是一种静默失败** ——
        # 它不抛异常，只是把成本翻倍、把证据表弄脏，
        # 并让一个本该"通过"的判据以"实验数量不对"的面目失败。
        def _script_key(row) -> str:
            """实验的唯一身份：脚本基名（F 与 P5 对同一脚本用不同的 claim_key）。"""
            return Path(str(row.get("code_path") or "").replace("\\", "/")).name

        already: dict[str, dict] = {}
        for r in run.store.rows("experiments"):
            k = _script_key(r)
            if k:
                already.setdefault(k, r)
        results: list[dict] = []
        for tag, claim, key, script in plan:
            skey = _script_key({"code_path": script})
            if skey in already:
                row = already[skey]
                results.append({"tag": tag, "experiment_id": row.get("experiment_id"),
                                "result": row.get("result"), "evidence_kind": row.get("evidence_kind"),
                                "exit_code": row.get("exit_code"), "reused": True})
                print(f"  [OK] {tag}: 复用 P4 已登记的实验 {row.get('experiment_id')}"
                      f"（result={row.get('result')} evidence_kind={row.get('evidence_kind')}）")
                continue
            try:
                got = e.run_experiment(claim, key, script, method="numeric", timeout=900)
            except Exception as ex:  # noqa: BLE001
                p.notes.append(f"{tag} 执行失败：{type(ex).__name__}: {ex}")
                print(f"  [!!] {tag} 执行失败：{ex}")
                p.ok = False
                results.append({"tag": tag, "recorded": False, "error": f"{type(ex).__name__}: {ex}"})
                continue
            results.append({"tag": tag, **_digest_obj(got)})
            print(f"  [OK] {tag}: result={got.get('result')} evidence_kind={got.get('evidence_kind')} "
                  f"exit={got.get('exit_code')} id={got.get('experiment_id')}")
        p.detail["experiments"] = results

        rows = run.store.rows("experiments")
        p.detail["experiment_rows"] = len(rows)
        # ---- `E-9`：P5 复核"论文声称值的来源"，而不是只信脚本自报的 supports ----
        # 逐脚本 AST 审：`PAPER_CLAIM` 必须与计划表逐字相同；`EXPECT_*` 一类常量必须是
        # 字面量、必须真的参与比较、必须有 check 锚在它上面。
        # 没有这类常量的脚本**不算失败**（不逼 AI 凭空写论文常数），但要进 uncovered 名单。
        paper_problems: list[str] = []
        uncovered: list[dict] = []
        for tag, claim_text, _key, script_rel in plan:
            sp = Path(script_rel)
            if not sp.is_absolute():
                # 计划表里的路径是 `repro/expN_*.py`（相对本文件所在目录 `_HERE`）
                sp = _HERE / script_rel
            got = _paper_declaration_audit(sp, claim_text)
            paper_problems.extend(got["problems"])
            if not got["expect_constants"]:
                uncovered.append({"tag": tag, "script": sp.name,
                                  "why": "本脚本没有任何 EXPECT_* 字面量常量 ⇒ "
                                         "P5 无法复核它是否把论文常数写死"
                                         "（补这些常数需要人定论文数值，AI 不编数字）"})
            print(f"  [E-9] {tag}: EXPECT 常量 {got['expect_constants']}、"
                  f"锚定在声称值上的 check {got['anchored_checks']} 条")
        p.detail["paper_declaration_problems"] = paper_problems
        p.detail["paper_declaration_uncovered"] = uncovered
        if uncovered:
            for u in uncovered:
                p.notes.append(f"论文声称值未覆盖（残余）：{u['script']} —— {u['why']}")
                print(f"  [~~] 论文声称值未覆盖（残余）：{u['script']}")
        if paper_problems:
            p.ok = False
            for msg in paper_problems:
                p.notes.append("论文声称值不可复核：" + msg)
                print(f"  [!!] 论文声称值不可复核：{msg}")
        else:
            print("  [OK] `PAPER_CLAIM` 与验收计划逐字一致；"
                  "所有 EXPECT_* 常量都是字面量且锚在 check 上")
        # 判据要写成"**每个脚本恰好一行**"：这才是"P4 与 P5 共享同一批证据"
        # 的可判定形式。只数总数会同时放过两种错误 —— 重复登记（行数偏多）
        # 与漏跑（行数偏少）。两种都实测过。
        from collections import Counter as _Counter
        by_script = _Counter(_script_key(r) for r in rows)
        p.detail["rows_per_script"] = dict(by_script)
        dup_scripts = sorted(k for k, n in by_script.items() if n > 1)
        missing_scripts = [ _script_key({"code_path": s}) for _t, _c, _k, s in plan
                            if _script_key({"code_path": s}) not in by_script ]
        run.checkpoint(p, len(rows) == len(plan) and not dup_scripts and not missing_scripts,
                       f"登记了 {len(rows)}/{len(plan)} 条实验，且每个脚本恰好一行"
                       + (f"（重复的脚本：{dup_scripts}）" if dup_scripts else "")
                       + (f"（缺失的脚本：{missing_scripts}）" if missing_scripts else ""))
        bad_proof = [x["experiment_id"] for x in rows if str(x.get("evidence_kind")) == "proof"
                     and str(x.get("method")) != "formal"]
        run.checkpoint(p, not bad_proof, f"**FC-22**：没有计算类实验自称 proof（违规 {bad_proof}）")
        kinds = {str(x.get("evidence_kind")) for x in rows}
        p.detail["evidence_kinds"] = sorted(kinds)
        run.checkpoint(p, kinds <= {"cross_check", "heuristic"}, f"证据等级全部是计算类：{sorted(kinds)}")
        negs = {str(x.get("negation_kind")) for x in rows}
        p.detail["negation_kinds"] = sorted(negs)
        run.checkpoint(p, None not in {x.get("negation_kind") for x in rows},
                       f"每条实验都做了否定分类：{sorted(negs)}")
        no_hash = [x["experiment_id"] for x in rows if x.get("code_path") and not str(x.get("code_hash")).strip()]
        run.checkpoint(p, not no_hash, f"有脚本的实验都绑定了 code_hash（缺失 {no_hash}）")
        return p.detail


def p6_document(run: Runner, exp_detail: dict) -> dict:
    """P6：G 撰写复现报告 + 登记依赖（含不可得的配套书）。"""
    with run.phase("P6", "撰写：G 出复现报告 + 登记依赖闭合") as p:
        try:
            AgentG = _imp("agent_g").AgentG
        except Exception as ex:  # noqa: BLE001
            p.ok = None
            p.notes.append(f"未接线：无法导入 AgentG（{type(ex).__name__}: {ex}）")
            return p.detail
        missing = run.require(AgentG, ["compose_claim", "register_dependency", "build_document"])
        if missing:
            p.ok = None
            p.notes.append(f"未接线：AgentG 缺少 {missing}")
            return p.detail

        g = AgentG(run.store, config={}, workspace_root=WORKSPACE)
        exps = {x["experiment_id"]: x for x in run.store.rows("experiments")}
        rels = run.store.rows("relations")
        lit = {x["lit_id"]: x for x in run.store.rows("literature")}
        lit0 = next(iter(lit), None)

        def exp_cite(key_sub: str) -> list[str]:
            hit = [eid for eid, r in exps.items() if key_sub in str(r.get("claim_key") or "")]
            return [f"exp:{x}" for x in sorted(hit)]

        specs: list[dict] = []

        def add(text: str, cites: list[str], ek: str, section: str, *, neg: bool = False,
                nk: str | None = None) -> None:
            try:
                c = g.compose_claim(text, citations=cites, evidence_kind=ek, section=section,
                                    is_negative=neg, negation_kind=nk)
                specs.append(c)
            except Exception as ex:  # noqa: BLE001
                p.notes.append(f"compose_claim 被拒（{ex}）—— 记下来，这本身是门在工作的证据")
                print(f"  [!!] compose_claim 被拒：{ex}")

        # 引文取自论文本身的关系（rel:）或实验（exp:）
        rel_by_desc = {str(r.get("description") or "")[:20]: r["relation_id"] for r in rels}

        def rel_cite(sub: str) -> list[str]:
            hit = [rid for d, rid in rel_by_desc.items() if sub in d]
            return [f"rel:{x}" for x in sorted(hit)]

        # 前两条曾经写作 `evidence_kind="proof"`，`D-1` 的写入期判据把它们拦下了。
        # 判据是对的，改的是这里：这两条说的是"论文的 Definition 1.1/1.2 这样定义"——
        # 那是**引用别人的定义**，不是形式化检查器的产出；而本阶段最后一条断言逐字写着
        # 「本环境没有 Lean/Coq 等证明检查器，因此我们没有产出任何 proof 级证据」。
        # 也就是说旧稿件**自相矛盾**：同一份文档里既声称两条 proof 级证据，又声明一条都没有。
        # 这正是 `D-1` 要挡的那一类（`evidence_kind` 被当成可以随手填的标签）。
        # 现在它们如实标为 `cross_check`（引文级核对），disclaimer 由结构自动补上。
        add("论文的 Definition 1.1 把 K(m) 定义为 V_K 上、x 与 x±e_i 相邻的图。",
            rel_cite("K(m)") or ([f"lit:{lit0}"] if lit0 else []), "cross_check", "1. 复现对象")
        add("论文的 Definition 1.2 把 S̃_m 定义为仿射 Weyl 群关于 {s_0,…,s_{m−1}} 的 Cayley 图。",
            rel_cite("S̃_m") or ([f"lit:{lit0}"] if lit0 else []), "cross_check", "1. 复现对象")
        add("我们独立数值验证了 Spec K(m) = [−m, m]（m = 3,4,5）。",
            exp_cite("SpecK(m)") or ([f"lit:{lit0}"] if lit0 else []), "cross_check", "2. 独立验证")
        add("我们独立数值验证了 girth K(m) = 6，以及 girth S̃_3 = 6、girth S̃_m = 4（m ≥ 4）。",
            exp_cite("girth") or ([f"lit:{lit0}"] if lit0 else []), "cross_check", "2. 独立验证")
        add("我们独立验证了 |V_K/Λ| = 2m^{m−1} = 18 / 128 / 1250（m = 3/4/5）以及每个顶点恰有 m 个邻居。",
            exp_cite("size_regularity") or ([f"lit:{lit0}"] if lit0 else []), "cross_check", "2. 独立验证")
        add("我们独立数值支持了 Spec S̃_m 在 [−m,m] 上的填充性（m = 3,4,5），并对 m = 6 做了采样探测。",
            exp_cite("SpecStilde") or ([f"lit:{lit0}"] if lit0 else []), "cross_check", "2. 独立验证")
        add("K(m) 与 S̃_m 在 m = 4,5 时同谱（[−m,m]）但围长不同（6 vs 4），因此不同构。",
            exp_cite("nonisomorphic") or ([f"lit:{lit0}"] if lit0 else []), "cross_check", "3. 结论")
        # FC-25：否定型断言必须分类
        add("我们**未能**独立证明 Spec S̃_m = [−m,m]：该结果是论文引用配套书 [6, Thm. 6.5] 得到的，"
            "而该书的出版信息论文未给出，我们无法获得。",
            [f"lit:{lit0}"] if lit0 else [], "cross_check", "4. 未证明的边界", neg=True, nk="not_proved")
        add("m ≥ 6 时 Spec S̃_m = [−m,m] 的等号是论文自己列出的公开问题，我们没有解决它。",
            [f"lit:{lit0}"] if lit0 else [], "cross_check", "4. 未证明的边界", neg=True, nk="not_proved")
        add("本环境没有 Lean/Coq 等证明检查器，因此我们没有产出任何 proof 级证据。",
            [f"lit:{lit0}"] if lit0 else [], "heuristic", "5. 方法与边界", neg=True, nk="not_searched_here")

        p.detail["claims"] = len(specs)
        run.checkpoint(p, len(specs) >= 8, f"构造了 {len(specs)} 条带引用的断言")
        run.checkpoint(p, all(c.get("citations") for c in specs), "每条断言都有 citations")
        cc = [c for c in specs if c.get("evidence_kind") == "cross_check"]
        run.checkpoint(p, all(str(c.get("disclaimer") or "").strip() for c in cc),
                       f"{len(cc)} 条 cross_check 断言都自动带上了 disclaimer")

        # ---- 依赖登记：配套书是 external_unavailable
        deps: list[dict] = []
        try:
            d1 = g.register_dependency(
                f"doc:draft#claim-7", "theorem",
                "Companion book on quotient lattices, tori and periodic graphs, vol. 11, Theorem 6.5"
                "（Spec S̃_m = [−m,m] 的来源）",
                status="external_unavailable",
                status_reason="论文只给了 '[6]' 与书名/卷号/定理号，**未给出出版信息**；"
                              "本项目检索不到该书 ⇒ 无法独立核验 Theorem 1.5 的这个前提。"
                              "这正是论文 Remark 1.6 自己声明的边界。",
            )
            deps.append(_digest_obj(d1))
            if lit0:
                d2 = g.register_dependency(f"doc:draft#claim-1", "prior_art",
                                           "本复现的输入论文（PDF 全文已入库）",
                                           source_lit_id=lit0, status="closed")
                deps.append(_digest_obj(d2))
            for eid in sorted(exps):
                d3 = g.register_dependency(f"doc:draft#claim-3", "experiment",
                                           f"实验 {eid}：{exps[eid].get('claim_key')}",
                                           source_experiment_id=eid, status="closed")
                deps.append(_digest_obj(d3))
        except Exception as ex:  # noqa: BLE001
            p.notes.append(f"register_dependency 失败：{type(ex).__name__}: {ex}")
            print(f"  [!!] register_dependency 失败：{ex}")
            p.ok = False
        p.detail["dependencies"] = deps
        drow = run.store.rows("dependencies")
        p.detail["dependency_rows"] = len(drow)
        ext = [x for x in drow if str(x.get("status")) == "external_unavailable"]
        run.checkpoint(p, len(ext) == 1, f"配套书恰登记 1 条 external_unavailable（实际 {len(ext)}）")

        # ---- 出稿
        try:
            doc = g.build_document(
                "reproduction_report",
                "独立推导复现：Cospectral periodic graphs: the spectrum does not determine the graph",
                claims=specs,
                open_problems=[
                    "m ≥ 6 时 Spec S̃_m = [−m,m] 的等号（论文 §6 的公开问题）",
                    "配套书 [6, Thm. 6.5] 的证明无法获得，故 Theorem 1.5 的前提无法独立核验",
                    "更细的谱数据（谱测度/态密度）能否区分这一对图（论文 Remark 1.7 留作公开）",
                ],
                out_path=str(WORKSPACE / "reproduction-report.md"),
            )
            p.detail["document"] = _digest_obj(doc)
            doc_id = doc.get("doc_id") or doc.get("document", {}).get("doc_id")
            p.detail["doc_id"] = doc_id
            run.checkpoint(p, bool(doc_id), f"稿件已登记 doc_id={doc_id}")
            md = WORKSPACE / "reproduction-report.md"
            run.checkpoint(p, md.exists(), "复现报告 markdown 已落盘")
        except Exception as ex:  # noqa: BLE001
            p.notes.append(f"build_document 失败：{type(ex).__name__}: {ex}")
            print(f"  [!!] build_document 失败：{ex}")
            p.ok = False
        return p.detail


def p7_review(run: Runner, doc_detail: dict) -> dict:
    """P7：H 审校 + 负控（注入过度声称，门必须响）+ 复审。"""
    with run.phase("P7", "审校：H 独立复核 + 负控（注入过度声称）") as p:
        try:
            AgentH = _imp("agent_h").AgentH
            scan_document = _imp("tools.review_tools").scan_document
        except Exception as ex:  # noqa: BLE001
            p.ok = None
            p.notes.append(f"未接线：无法导入 H 或 scan_document（{type(ex).__name__}: {ex}）")
            return p.detail

        doc_id = doc_detail.get("doc_id")
        lit0_id = next((str(x.get("lit_id")) for x in run.store.rows("literature")), "0000")
        # H 实例要在**负控之前**建好：负控要用它去审那份注入的坏稿件。
        _h_holder: dict[str, Any] = {}
        if callable(getattr(AgentH, "review", None)):
            _h_holder["h"] = AgentH(run.store, config={})
        if not doc_id:
            p.ok = None
            p.notes.append("P6 没有产出的 doc_id ⇒ 审校阶段未执行")
            return p.detail

        # ---- 先做一次**纯函数负控**：不依赖 H 的落库，直接证明门会响
        good = {
            "doc_id": "0000",
            "claims": [
                {"claim_id": "c1", "text": "K(m) 是 m-正则的。", "citations": ["rel:0001"],
                 "evidence_kind": "proof"},
            ],
        }
        clean = scan_document(good, dependencies=[])
        p.detail["negative_control_clean"] = {"errors": clean["error_count"], "verdict": clean["verdict"]}
        run.checkpoint(p, clean["error_count"] == 0, "**防误伤**：干净稿件 error=0")

        overclaim = {
            "doc_id": "0000",
            "claims": [
                {"claim_id": "c1", "text": "我们已证明 Spec K(m) = [−m,m]。", "citations": ["rel:0001"],
                 "evidence_kind": "cross_check", "disclaimer": "数值交叉验证，不构成证明"},
            ],
        }
        caught = scan_document(overclaim, dependencies=[])
        p.detail["negative_control_overclaim"] = {
            "errors": caught["error_count"],
            "kinds": sorted({f["kind"] for f in caught["findings"]}),
        }
        run.checkpoint(p, caught["error_count"] >= 1 and any(
            f["kind"] == "overclaim" for f in caught["findings"]
        ), "**负控**：把 cross_check 写成功证明性措辞 → 必须报 overclaim + error")

        unsupported = {
            "doc_id": "0000",
            "claims": [{"claim_id": "c1", "text": "某个没有出处的断言。", "citations": [],
                        "evidence_kind": "proof"}],
        }
        uns = scan_document(unsupported, dependencies=[])
        p.detail["negative_control_unsupported"] = {
            "errors": uns["error_count"],
            "evidence": [f["evidence"] for f in uns["findings"] if f["kind"] == "unsupported_claim"],
        }
        ev_ok = any(
            f["kind"] == "unsupported_claim" and "citations" in f["evidence"] for f in uns["findings"]
        )
        run.checkpoint(p, ev_ok, "**负控**：无引用断言 → error，且 finding 的 evidence 里含实际值")

        # ---- **落库级负控**：把一条"过度声称"的断言**注入**稿件，H 必须抓到。
        #
        # 为什么要直接写表：`Document.validate` 与 `AgentG.compose_claim` 都会在**写入前**
        # 拒绝这种行 —— 那是第一道闸。而本步要验的是**第二道闸**：
        # H 能不能发现已经躺在库里的违规数据（历史数据、手工改过的快照、
        # `rebuild` 之前的旧文件都不受 schema 保护）。
        bad_id = None
        try:
            # ⚠️ 必须**绕过 `Store.tx`**：提交时会调 `S.validate_table`，而它会直接拒绝这条稿件（“没有引用的断言不允许进入稿件”）。
            # 这一点本身是个好消息：**schema 是第一道闸，而且它确实拦得住**。
            # 本步要验的是第二道闸（H 会不会发现已经躺在库里的坏数据），
            # 所以只能像历史数据 / 外部工具那样**直接写表**。
            with run.store.tx("documents", "counters", actor="agent-G", note="acceptance P7 inject") as tx:
                bad_id = tx.alloc_id("doc")
            doc_doc = run.store.read("documents")
            doc_doc["rows"].append({
                    "doc_id": bad_id, "kind": "reproduction_report",
                    "title": "【负控】注入了过度声称的稿件",
                    "claims": [
                        {"claim_id": "bad-1", "text": "我们已证明 Spec S̃_m = [−m,m] 对一切 m 成立。",
                         "citations": [f"lit:{lit0_id}"], "evidence_kind": "cross_check",
                         "disclaimer": "数值交叉验证，不构成证明"},
                        {"claim_id": "bad-2", "text": "某个没有出处的断言。",
                         "citations": [], "evidence_kind": "proof"},
                        {"claim_id": "bad-3", "text": "我们未能独立证明它。",
                         "citations": [f"lit:{lit0_id}"], "evidence_kind": "cross_check",
                         "disclaimer": "数值交叉验证，不构成证明", "is_negative": True},
                    ],
                    "status": "draft", "created_at": S.now_iso(), "created_by": "agent-G",
            })
            run.store._atomic_write(run.store.data / "documents.json", doc_doc)
            rev_bad = _h_holder["h"].review(bad_id)
            kinds_bad = sorted({str(x.get("kind")) for x in run.store.rows("review_findings")
                                if str(x.get("doc_id")) == str(bad_id)})
            p.detail["negative_control_document"] = {
                "doc_id": bad_id,
                "errors": _digest_obj(rev_bad).get("error_count"),
                "kinds": kinds_bad,
            }
            run.checkpoint(
                p,
                {"overclaim", "unsupported_claim", "missing_negation_kind"} <= set(kinds_bad),
                f"**落库级负控**：注入过度声称/无引用/未分类否定 ⇒ H 报出 {kinds_bad}",
            )
            # ⚠️ **负控数据必须清理掉**：它是刻意造的坏数据，留在库里会让 P8
            # 的 `verify` 报 error（而那些 error 是**我们自己注入的**，不是框架缺陷）。
            # "注入 → 观察被抓到 → 清理"是负控的完整形态；只做前两步会用一堆假
            # 红灯淹没真的结论。
            with run.store.tx("documents", "review_findings", actor="agent-H", note="acceptance P7 cleanup") as tx:
                tx._rows["documents"] = [r for r in tx.rows("documents")
                                         if str(r.get("doc_id")) != str(bad_id)]
                tx.mark_dirty("documents")
                tx._rows["review_findings"] = [r for r in tx.rows("review_findings")
                                               if str(r.get("doc_id")) != str(bad_id)]
                tx.mark_dirty("review_findings")
            p.notes.append(f"负控稿件 {bad_id} 及其 finding 已清理（不留给 P8 当假红灯）")
        except Exception as ex:  # noqa: BLE001
            p.notes.append(f"落库级负控失败：{type(ex).__name__}: {ex}")
            p.ok = False

        missing = run.require(AgentH, ["review", "verify_fixes"])
        if missing:
            p.notes.append(f"未接线：AgentH 缺少 {missing} ⇒ 落库级审校未执行")
            p.ok = None
            return p.detail

        if _h_holder.get("h") is None:
            _h_holder["h"] = AgentH(run.store, config={})
        h = _h_holder["h"]
        try:
            rev = h.review(doc_id)
        except Exception as ex:  # noqa: BLE001
            p.notes.append(f"review({doc_id}) 失败：{type(ex).__name__}: {ex}")
            p.ok = False
            return p.detail
        p.detail["review"] = _digest_obj(rev)
        p.detail["findings"] = len(run.store.rows("review_findings"))
        run.checkpoint(p, p.detail["findings"] >= 0, f"H 登记了 {p.detail['findings']} 条审校发现")
        frows = run.store.rows("review_findings")
        run.checkpoint(p, all(str(x.get("evidence") or "").strip() for x in frows),
                       "**每条发现都带 evidence**（审校者的判断也需要证据）")

        try:
            vf = h.verify_fixes(doc_id, round_no=2)
            p.detail["verify_fixes"] = _digest_obj(vf)
        except Exception as ex:  # noqa: BLE001
            p.notes.append(f"verify_fixes 失败：{type(ex).__name__}: {ex}")

        docs = {x["doc_id"]: x for x in run.store.rows("documents")}
        p.detail["doc_status"] = (docs.get(doc_id) or {}).get("status")
        p.detail["review_rounds"] = (docs.get(doc_id) or {}).get("review_rounds")
        return p.detail


def p8_verify(run: Runner) -> dict:
    """P8：全库一致性校验。"""
    verify_all = _imp("verify").verify_all

    with run.phase("P8", "一致性：verify 全库校验") as p:
        try:
            rep = verify_all(run.store, deep=False)
        except Exception as ex:  # noqa: BLE001
            p.ok = False
            p.notes.append(f"verify_all 抛异常：{type(ex).__name__}: {ex}")
            return p.detail
        d = rep.to_dict() if hasattr(rep, "to_dict") else dict(rep)
        p.detail["report"] = _digest_obj(d)
        # ⚠️ `VerifyReport.to_dict()` 给的是**已经分好档**的 `errors` / `warnings`
        # 两个列表（FC-10 三分档），字段名是 `code` 而不是 `kind`。
        errors = list(d.get("errors") or [])
        warns = list(d.get("warnings") or [])
        p.detail["error_count"] = len(errors)
        p.detail["warning_count"] = len(warns)
        p.detail["checked"] = d.get("checked")
        run.checkpoint(p, not errors, f"0 error（warning {len(warns)} 条）")
        for i in warns[:10]:
            print(f"  [warn] {i.get('table')}/{i.get('row_id')}: {i.get('code')} — {str(i.get('message'))[:150]}")
        if errors:
            for i in errors[:10]:
                print(f"  !! {i.get('table')}/{i.get('row_id')}: {i.get('code')} — {str(i.get('message'))[:160]}")
        return p.detail


def p9_summary(run: Runner) -> dict:
    """P9：汇总各表计数 + 与论文声称的逐条对照。"""
    sys.path.insert(0, str(_HERE))
    import paper_seed  # noqa: PLC0415

    with run.phase("P9", "汇总：表计数 + 论文声称 vs 独立验证") as p:
        st = run.store.stats()
        p.detail["stats"] = _digest_obj(st)
        for t in ("literature", "concepts", "relations", "analysis_reports", "research_questions",
                  "search_requests", "experiments", "attack_plans", "documents", "dependencies",
                  "review_findings"):
            print(f"  {t:22s} {len(run.store.rows(t))}")
        acc = json.loads((_HERE / "acceptance.json").read_text(encoding="utf-8"))
        claims = acc.get("claims") or []
        by_kind: dict[str, int] = {}
        for c in claims:
            by_kind[str(c.get("kind"))] = by_kind.get(str(c.get("kind")), 0) + 1
        p.detail["paper_claims"] = by_kind
        p.detail["paper_claims_total"] = len(claims)
        p.notes.append(
            "论文结论分类：" + "、".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
            + "（computable=我们可独立数值验证；quoted/proof-only/open=我们**不能**独立验证）"
        )
        print(f"  论文结论 {len(claims)} 条：" + "、".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
        # P9 是**纯汇总**阶段：它自己一条判据都没有（表计数与论文声称分类是"读数"，不是"判定"）。
        # 直接把它留成 `None` 会让整轮验收永远 exit 2（见下方 `E-6` 的退出码口径），
        # 而那也是不诚实的：那些计数**确实**被读出来了，能判定的恰恰是"前置阶段有没有给出结论"。
        #
        # 所以这里等价的判据是：**本阶段之前有没有真的给出结论的阶段** ——
        #   - 全量跑（P1..P8 都设过 ok）⇒ 前面有结论 ⇒ P9 记 pass；
        #   - `--phases P9` 单独跑（前面 0 个阶段）⇒ 没有任何可汇总的对象 ⇒ 保持 None ⇒ exit 2。
        # 后者正是这条修法的负控：旧实现在这种运行下也会打 PASS/exit 0。
        #
        # `R2-R3`（重审实测）：这里的判据旧版是"前置阶段的**列表非空**"，而打印与
        # checkpoint 理由写的是"读到了 N 个前置阶段的**结论**" —— 两者不是一回事。
        # `--phases P7,P9` 时 P7 是 `N/A`（`ok is None`，没给出任何结论），旧版仍然打印
        # "[OK] 汇总读到了 1 个前置阶段的结论" 并把 P9 记 PASS。现在判据与措辞都按
        # "**给出结论**的阶段（`ok is True` 或 `ok is False`）"算，并把 P7 那种
        # "跑了但没结论"的从计数里剔掉。
        concluded = [x for x in run.phases
                     if x.key != "P9" and x.ok is not None]
        n_na = len([x for x in run.phases if x.key != "P9"]) - len(concluded)
        if concluded:
            keys = "、".join(x.key for x in concluded)
            run.checkpoint(
                p, True,
                f"汇总读到了 {len(concluded)} 个**给出结论**的前置阶段（{keys}）"
                f"；另有 {n_na} 个前置阶段没给出结论（N/A）"
                "（P9 本身无判据，只做汇总）"
            )
        else:
            p.notes.append(
                f"前置阶段一个都没给出结论（{n_na} 个跑了但判成 N/A）⇒ 没有可汇总的对象"
                "（这不是通过）"
            )
        return p.detail


# ====================================================================== 辅助


def _arity1(fn: Any) -> bool:
    import inspect  # noqa: PLC0415

    try:
        params = [p for p in inspect.signature(fn).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    except (TypeError, ValueError):
        return True
    return len(params) == 1


def _needs_report(fn: Any) -> bool:
    import inspect  # noqa: PLC0415

    try:
        params = [p for p in inspect.signature(fn).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    except (TypeError, ValueError):
        return False
    return bool(params) and params[0].default is inspect.Parameter.empty


def _as_id_list(got: Any) -> list[str]:
    if got is None:
        return []
    if isinstance(got, str):
        return [got] if got else []
    if isinstance(got, dict):
        for k in ("question_ids", "created", "new_question_ids", "ids"):
            if isinstance(got.get(k), list):
                return [str(x) for x in got[k]]
        if got.get("question_id"):
            return [str(got["question_id"])]
        return []
    if isinstance(got, (list, tuple)):
        return [str(x) for x in got]
    return []


def _digest_obj(obj: Any, depth: int = 0) -> Any:
    """把任意对象压成可 JSON 序列化的摘要（避免验收结果里塞满 markdown）。"""
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return obj if len(obj) <= 400 else obj[:397] + "…"
    if depth >= 3:
        return f"<{type(obj).__name__}>"
    if isinstance(obj, dict):
        return {str(k): _digest_obj(v, depth + 1) for k, v in list(obj.items())[:40]}
    if isinstance(obj, (list, tuple)):
        return [_digest_obj(x, depth + 1) for x in list(obj)[:20]]
    if hasattr(obj, "to_dict"):
        try:
            return _digest_obj(obj.to_dict(), depth + 1)
        except Exception:  # noqa: BLE001
            pass
    return f"<{type(obj).__name__}>"


# ====================================================================== main


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="验收测试：独立推导复现 main.pdf")
    ap.add_argument("--root", default=str(WORKSPACE))
    ap.add_argument("--clean", action="store_true", help="先清空 workspace")
    ap.add_argument("--json", default=str(RUN_DIR / "acceptance-result.json"))
    ap.add_argument("--phases", default="", help="只跑指定阶段，逗号分隔，如 P1,P5")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if args.clean and root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    # 把独立的复现脚本复制进工作区（E 只允许在工作区内运行脚本 —— 路径穿越的最后一道闸）
    dst_repro = root / "repro"
    if REPRO_SRC.exists():
        shutil.rmtree(dst_repro, ignore_errors=True)
        shutil.copytree(REPRO_SRC, dst_repro, ignore=shutil.ignore_patterns("__pycache__", "_scratch*"))

    store = Store(root)
    store.init()
    run = Runner(store)
    only = {x.strip() for x in args.phases.split(",") if x.strip()}

    def want(key: str) -> bool:
        return not only or key in only

    print(f"workspace: {root}")
    print(f"repro 脚本: {sorted(p.name for p in dst_repro.glob('*.py')) if dst_repro.exists() else '（缺失！）'}")

    p2d: dict = {}
    p5d: dict = {}
    p6d: dict = {}
    if want("P1"):
        p1_ingest(run)
    if want("P2"):
        p2d = p2_analyze(run)
    if want("P2b"):
        p2b_interactions(run)
    if want("P3"):
        p3_research(run, p2d)
    if want("P4"):
        p4_attack(run)
    p5d = p5_experiments(run) if want("P5") else {}
    if want("P6"):
        p6d = p6_document(run, p5d)
    if want("P7"):
        p7_review(run, p6d or {"doc_id": None})
    if want("P8"):
        p8_verify(run)
    if want("P9"):
        p9_summary(run)

    result = {
        "workspace": str(root),
        "phases": [x.to_dict() for x in run.phases],
        "summary": {
            "total": len(run.phases),
            "passed": sum(1 for x in run.phases if x.ok is True),
            "failed": sum(1 for x in run.phases if x.ok is False),
            "not_run": sum(1 for x in run.phases if x.ok is None),
        },
    }
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print("\n================ 验收汇总 ================")
    for x in run.phases:
        flag = {True: "PASS", False: "FAIL", None: "N/A "}[x.ok]
        print(f"  [{flag}] {x.key} {x.title}  ({x.seconds:.1f}s)")
        for n in x.notes:
            print(f"         · {n}")
    s = result["summary"]
    print(f"\n  通过 {s['passed']} / 失败 {s['failed']} / 未执行 {s['not_run']}")
    if s["not_run"]:
        print(f"  ⇒ 有 {s['not_run']} 个阶段**没有给出结论**（未接线 / 未执行）⇒ 退出码 2（没查成，不是通过）")
    print(f"  结果 JSON: {args.json}")

    # 第三态必须**可判定地**体现在退出码上（`E-6`）。
    #
    # 旧版 `return 0 if s["failed"] == 0 else 1` 只看 failed，于是"某阶段未接线/未执行"
    # （`ok is None`）可以让整轮验收 exit 0 —— 而验收程序是"论文复现链接上了没有"的
    # **唯一自动化判据**（`tools/release_all.py` 的 acceptance 步骤）。没接线却报绿，
    # 正是本项目反复记过的"把没做读成通过"。
    #
    # 现在的口径（三档，与 `release_check.py` / `release_all.py` 同形）：
    #   0 = 所有跑到的阶段都通过，且**没有**未执行阶段；
    #   1 = 有阶段失败；
    #   2 = 没有失败，但有阶段**没给出结论**（`ok is None`）⇒ 没查成，绝不是通过。
    # `release_all.py` 给这一步的码表是 `PLAIN_EXIT = {0: "pass"}`（不含 1/2）⇒
    # 退出码 2 在编排层被记成 `unknown`（而不是 `fail`），与"没查成"的口径一致。
    if s["failed"]:
        return 1
    if s["not_run"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
