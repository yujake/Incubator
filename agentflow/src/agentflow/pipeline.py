"""编排：把 A→B→C→D 串成一条可中断、可续跑、可审计的流水线（DESIGN-TOOLS.md §5）。

## 这一层为什么不是"一个脚本"

D 的循环本来就可以手工跑：调一次 C、调一次 D、跑一遍 A、跑一遍 B、再调一次 D。
把它固化成 ``run_pipeline`` 的理由是可复现与可审计：

- 每一轮的中间产物都落盘（C 报告文件 + 登记行、``research_questions`` 台账、
  D 的报告），因此"这一轮到底发生了什么"能在事后逐条重放；
- 每一轮的摘要作为返回值回去（供 CLI 打印），不混进报告正文 ——
  给机器看的和给人看的必须分开（与 §2.2 的"登记表 + 文件双份"同一条理由）；
- 等待集（``waiting_request_ids``）落在盘上，所以即使进程被杀掉，
  下一次运行 ``poll`` 依然能判断"我上次在等哪些请求"（§4.2）。

## 三种运行模式（同一段代码，靠参数区分）

| 模式 | 触发条件 | 行为 |
|---|---|---|
| ``analyze`` | 传了 ``agent_c``（或 ``config`` 里的 ``auto_build_agents`` 打开了自动装配） | C 现场分析 → 报告落盘 |
| ``replay`` | ``agent_c=None`` | 只读 ``analysis_reports`` 里已登记的报告，按 ``report_ids`` 逐份交给 D |
| ``auto`` | ``config["agent_a"]["providers"]`` / ``agent_b`` 存在 | 顺手把 A/B 也装配上（默认关闭：跑网络检索必须是显式选择） |

``replay`` 模式不是为了省事，而是为了续跑：上一次跑到一半挂了，
这次不必重新做一遍 C 的分析（它可能很贵），直接从报告登记行接着往下走。

## A/B 缺省为 None 的含义

``agent_a=None`` / ``agent_b=None`` 表示不跑检索（只做静态分析）。
契约里明确要求允许这种模式，自检用的也是它：整条流水线不碰网络，
因此在无 API key、无网络的环境里也能端到端跑通。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import conceptrows as CR   # 并表过渡期：夹具/自检走这一处写口
from . import schema as S
from .agent_d import AgentD, install_d_tools
from .store import Store
from .tools import research_tools as RT

__all__ = ["run_pipeline", "PipelineError"]


class PipelineError(RuntimeError):
    """编排层的失败（缺 C 报告、缺映射等）。消息里必须说清"下一步该怎么办"。"""


# ---------------------------------------------------------------- 小工具


def _as_report_dict(report: Any) -> dict:
    """把 C 的报告对象 / dict 统一成 dict（同 ``agent_d`` 的处理口径）。

    为什么重复这一段而不是 import：``agent_d`` 里那份是私有函数，
    而 pipeline 还需要 ``report_id`` / ``markdown`` 这两个 D 用不到的字段
    （登记要用）。两处的字段集不同，硬凑成一个反而会把"谁依赖什么"搅乱。
    """
    if isinstance(report, Mapping):
        d = dict(report)
    else:
        d = {
            "report_id": getattr(report, "report_id", None),
            "kind": getattr(report, "kind", ""),
            "request": getattr(report, "request", ""),
            "params": getattr(report, "params", {}) or {},
            "summary": getattr(report, "summary", "") or "",
            "payload": getattr(report, "payload", {}) or {},
            "markdown": getattr(report, "markdown", "") or "",
            "warnings": list(getattr(report, "warnings", []) or []),
            "truncated": bool(getattr(report, "truncated", False)),
            "markdown_path": getattr(report, "markdown_path", None),
            "ok": getattr(report, "ok", True),
            "error": getattr(report, "error", None),
        }
    d.setdefault("payload", {})
    d.setdefault("warnings", [])
    return d


def _reports_dir(store: Store) -> Path:
    return Path(store.root) / "reports"


def _conductor_for_c(store: Store, agent_c: Any) -> Any:
    """把调用方给的那个 `AgentC` 实例接到主控的召唤面上（L-03）。

    为什么必须经 `conductor.summon`（`draft/44` 的 L-03）：`pipeline` 以前直呼
    `agent_c.handle(...)` 再自己把报告写进 `analysis_reports` —— 那条路
    ① 不写 `role=C` 的 `tasks` 行（于是 `c_analysis_runs` 读 0），
    ② 绕过策略/预算/台账三道闸门。现在报告只由 C 的动作（`handle`，它的写集里
    本来就有 `analysis_reports`，见 `capabilities.WRITE_SETS["C"]`）产出，
    pipeline 只从这一步的返回值里读 `report_id`。

    `LocalBackend({"C": agent_c})` 直接绑调用方给的同一个实例
    （`LocalBackend.resolve` 支持裸对象与 `("object", obj)` 两种写法）——
    不新建对象，也不碰 `host`。
    """
    from .conductor import Conductor, LocalBackend

    return Conductor(store, backend=LocalBackend({"C": agent_c}))


def _load_agent_c(store: Store, config: Mapping[str, Any] | None) -> Any | None:
    """惰性构造 ``agent_c.AgentC``；模块不存在时返回 None（而不是 ImportError）。

    C 由别人同时编写，pipeline 必须能在它缺席时以 ``replay`` 模式工作 ——
    否则"D 的研究循环"这件事根本没法和 C 的进度解耦。
    """
    try:
        from .agent_c import AgentC  # type: ignore[import-not-found]
    except Exception:
        return None
    cfg = dict((config or {}).get("agent_c") or {})
    return AgentC(store, config=cfg)


def _make_request_fn(agent_c: Any) -> Any:
    """拿到 C 的 ``handle``（自然语言需求 → 分析器）；没有它就用 ``analyzers`` 直接调。"""
    handle = getattr(agent_c, "handle", None)
    if callable(handle):
        return handle
    analyzers = getattr(agent_c, "analyzers", None)
    if callable(analyzers):
        return analyzers
    raise PipelineError(
        "AgentC 既没有 handle() 也没有 analyzers()：无法按需求原文分派分析器。"
        "请检查 agent_c 的接口，或改用 agent_c=None 的 replay 模式（从 analysis_reports 读已登记的报告）。"
    )


def _run_agent(agent: Any, *, limit: int | None = None) -> dict:
    """跑一次 A 或 B，返回结构化结果（异常一律转成 ``{"error": ...}``）。

    为什么 A/B 抛异常要吞掉：编排层的职责是"把流程推下去并如实报告"。
    一次 provider 网络失败不该让整条流水线丢掉已经产生的报告与台账 ——
    那些才是这轮跑出来的东西。失败会原样出现在本轮摘要里，不会被隐藏。
    """
    if agent is None:
        return {"skipped": "agent 未提供（None 表示不跑检索，只做静态分析）"}
    run = getattr(agent, "run", None)
    if not callable(run):
        return {"error": f"{type(agent).__name__} 没有 run() 方法"}
    try:
        if limit is None:
            out = run()
        else:
            # A 与 B 的参数名不同：A 用 max_requests，B 用 max_docs/limit/max
            for kw in ("max_requests", "max_docs", "limit", "max"):
                try:
                    out = run(**{kw: limit})
                    break
                except TypeError:
                    continue
            else:
                out = run()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return out if isinstance(out, dict) else {"result": out}


def _pending_request_ids(store: Store, *, include_claimed: bool = False) -> list[str]:
    """还没结束的 ``search_requests``。用于"这一轮 D 提交了哪些请求"的差集计算。"""
    out: list[str] = []
    for r in store.rows("search_requests"):
        if r.get("done"):
            continue
        if not include_claimed and r.get("claimed_by"):
            # 已被某个 A 实例领走（可能正在跑）：不重复指派，但不隐藏它
            continue
        out.append(str(r.get("request_id")))
    return sorted(out)


def _all_request_ids(store: Store) -> set[str]:
    return {str(r.get("request_id")) for r in store.rows("search_requests")}


def _status_counts(store: Store) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in store.rows("research_questions"):
        out[str(r.get("status"))] = out.get(str(r.get("status")), 0) + 1
    return out


def _select_reports(store: Store, report_ids: Sequence[str] | None, skip: Iterable[str]) -> list[dict]:
    """按 ``report_ids`` 取登记行；未指定则取全部（按 report_id 稳定排序）。"""
    rows = list(store.rows("analysis_reports"))
    if report_ids:
        want = list(dict.fromkeys(str(x) for x in report_ids))
        index = {str(r.get("report_id")): r for r in rows}
        missing = [x for x in want if x not in index]
        if missing:
            raise PipelineError(
                f"analysis_reports 里找不到这些报告号：{missing}。"
                "可用 `python -m agentflow.cli status` 看现有报告，或去掉 report_ids 让它按登记顺序全跑。"
            )
        rows = [index[x] for x in want]
    else:
        rows.sort(key=lambda r: str(r.get("report_id") or ""))
    skip_set = set(skip)
    return [r for r in rows if str(r.get("report_id")) not in skip_set]


# ---------------------------------------------------------------- 主流程


def run_pipeline(
    store: Store,
    *,
    request: str,
    gap_rounds: int = 2,
    config: Mapping[str, Any] | None = None,
    agent_c: Any | None = None,
    agent_a: Any | None = None,
    agent_b: Any | None = None,
    report_ids: Sequence[str] | None = None,
    agent_d: AgentD | None = None,
    d_report_path: str | Path | None = None,
    resume: bool = True,
) -> dict:
    """``C 分析 → D 提取问题 → D 溯源 → 缺证据则提交请求 → A 跑 → B 跑 → D poll 复查 → 重复 → D 写报告``。

    参数
    ----
    store       : 共享存储。
    request     : 需求原文（同时是 C 的分析需求与"这一轮在干什么"的审计记录）。
    gap_rounds  : 补证据的轮数（默认 2，见 §8 待决问题 3 的"每问题最多 2 轮"）。
                  从第 2 轮起不再重复做 C 的分析（报告已在盘上），
                  这样"再来一轮"的语义是"给已经提出的问题补证据"，而不是"重新分析一遍"。
    agent_c     : C 智能体。为 None 时只用 ``analysis_reports`` 里已登记的报告（replay 模式）。
    agent_a/b   : A/B 智能体。为 None 表示不跑检索（自检用这个模式，不碰网络）。
    report_ids  : 显式指定要处理的报告号（replay / 续跑用）。
    agent_d     : 允许注入已配置好的 D（例如带 LLM 钩子的实例）。
    resume      : 跳过"已经 ingest 过的问题来源"（靠 ``origin`` 去重，跨进程幂等）。

    返回
    ----
    供 CLI 打印的摘要字典：``mode`` / ``rounds`` / ``report_ids`` / ``questions`` /
    ``requests_submitted`` / ``d_report_path`` 等。每轮的细节都在 ``rounds`` 里。
    """
    cfg = dict(config or {})
    store.init()  # 幂等：表不存在就建空表（续跑时不会覆盖已有数据）
    rounds = max(0, int(gap_rounds))

    # ---------- 0. 装配 D
    reports_dir_cfg = cfg.get("agent_d") or {}
    d_cfg = dict(reports_dir_cfg)
    d_cfg.setdefault("reports_subdir", "reports")
    if not resume:
        d_cfg["dedup_by_origin"] = False
    # `auto_build_c` 必须在装配 D 之前读出来：D 需要知道"有没有 C 可以点菜"。
    # 之前这行在读它的地方（第 1 步）才定义，于是"装配 D"与"C 分析"两步对
    # 同一个配置键各读一次 —— 两处口径一旦分叉（比如一处读 `auto_build_c`、
    # 另一处读 `auto_build_agents`），I1 会以"没有 C 侧证据"的形式静默失效。
    #
    # 现在 C 的装配只发生在这里一次，D 与第 1 步共用同一个实例。修之前
    # 这里与第 1 步各装配一个 AgentC（两个实例），而两处的条件还不一样：
    # 注入 D 的判据只看 `auto_build_c`，第 1 步却看
    # `auto_build_c or auto_build_agents or build_agent_c`。于是
    # `config={"auto_build_c": False, "auto_build_agents": True}` 会得到
    # "C 在跑、D 手里却没有 C" —— 正是 I1 要求避免的那种静默退化，
    # 而它连一行警告都不会产生。现在判据合并成一个 `want_c`，不可能再分叉。
    auto_build_c = bool(cfg.get("auto_build_c", True))
    want_c = bool(auto_build_c or cfg.get("auto_build_agents") or cfg.get("build_agent_c"))
    c_autobuild_failed = False
    if agent_c is None and want_c:
        agent_c = _load_agent_c(store, cfg)
        c_autobuild_failed = agent_c is None
    if agent_d is None:
        # 必须把 C 实例显式交给 D。
        #
        # I1（DESIGN-INTERACTIONS.md §1）要求 D 能"按需向 C 点菜"：在追问某个问题时
        # 现场查 neighbors / relations_between / contradictions，而不是只消费上一次
        # 跑出来的报告。D 侧有一个惰性兜底（不传 c 时自己装配一个 AgentC），
        # 但那会让"谁负责装配 C"这件事隐式化 —— 一旦兜底行为变化，I1 会静默退化
        # 为"没有 C 侧证据"，而报告里只会多一行标注，不会报错。
        # 所以在这里显式注入：装配点唯一、可审计。
        agent_d = AgentD(store, config=d_cfg, tools=install_d_tools(store), c=agent_c)
    summary: dict[str, Any] = {
        "request": request,
        "gap_rounds": rounds,
        "mode": "replay",
        "rounds": [],
        "report_ids": [],
        "warnings": [],
    }
    if c_autobuild_failed:
        summary["warnings"].append(
            "agent_c 未传入且无法自动装配（agent_c.py 导入失败）："
            "本次按 replay 模式只读 analysis_reports 里已登记的报告。"
        )

    # ---------- 1. C 分析（可选）
    #
    # 默认行为：agent_c=None 时先试着自动装配一个 AgentC（`auto_build_c`，默认开）。
    # 为什么这是对的默认：`python -m agentflow.cli pipeline --request ...` 是设计基线里
    # 写明的用户命令，而它并不传 agent_c；如果这里不自动装配，命令一跑就报
    # "analysis_reports 里没有任何报告" —— 文档承诺的能力其实用不了。
    # 显式传 agent_c 的调用方不受影响；只想读已登记报告的续跑场景可以
    # 传 `config={"auto_build_c": False}` 或 `agent_c=...`（replay 由 report_ids 表达）。
    # （C 已在上面装配好并被同一个实例交给了 D —— 这里不再重复装配。）
    if agent_c is not None:
        summary["mode"] = "analyze"
        # ---- L-03：经 `conductor.summon`（报告只由 C 的动作产出）
        #
        # 旧形态是 `_make_request_fn(agent_c)(request)` + `_persist_report(...)`：
        # 那次分析没有 `role=C` 的 `tasks` 行、也没过策略/预算闸门 ——
        # 真机后果就是 `c_analysis_runs` 读 0（台账上像"C 一次都没跑过"）。
        # 现在走 `summon("C", "handle", {"request_text": request})`：C 的 `handle`
        # 自己 `persist()`（它的写集里本来就有 `analysis_reports`），
        # pipeline 只读回 `report_id` —— 于是"谁产出了报告"与"谁派了这活"都在台账上。
        try:
            cond = _conductor_for_c(store, agent_c)
            res = cond.summon("C", "handle", {"request_text": str(request)}, by="M",
                              input_key=f"pipeline:analyze:{str(request)[:120]}")
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(
                f"C 分析失败（{type(e).__name__}: {e}）。"
                "可以改用 agent_c=None 让 pipeline 从 analysis_reports 里读已登记的报告（replay 模式）。"
            ) from e
        report = res.payload
        info = _as_report_dict(report)
        if not res.ok or str(res.outcome or "") in ("failed", "refused", "no_result"):
            raise PipelineError(
                f"C 的分析这一步没有产出可用报告（status={res.status!r} outcome={res.outcome!r}"
                f" task_id={res.task_id!r} detail={str(res.detail or '')[:200]!r}）。"
                "台账里有它的那一行；若 kind=unknown，说明需求原文没有命中任何分析器的关键词"
                "（见 `agent_c.handle` 的分派规则）。"
                "请把需求写成如「查询 A 与 B 之间的关系」「统计最热门的 5 个概念」。"
            )
        if bool(info.get("ok", True)) is False:
            raise PipelineError(
                f"C 的报告无法登记：这次分析没有完成"
                f"（kind={info.get('kind')!r}, error={info.get('error')!r}）。"
                "失败报告不落 `analysis_reports`（它不是一份分析产物）——"
                "请把需求写成如「查询 A 与 B 之间的关系」「统计最热门的 5 个概念」。"
            )
        rid = str(getattr(report, "report_id", "") or "")
        summary["report_ids"] = [rid] if rid else []
        summary["c_analysis"] = {
            "kind": info.get("kind"),
            "summary": info.get("summary"),
            "report_id": rid,
            "task_id": res.task_id,
        }

    # ---------- 2. 取要处理的报告（replay 模式在这里读盘）
    if not summary["report_ids"]:
        # 续跑：默认跳过"已经 ingest 过问题"的报告（问题表里有同 report_id 的 origin）
        done_reports = {
            str(r.get("origin") or "").split(":")[2]
            for r in store.rows("research_questions")
            if str(r.get("origin") or "").count(":") >= 2
        }
        skip = done_reports if resume else set()
        rows = _select_reports(store, report_ids, skip)
        summary["report_ids"] = [str(r.get("report_id")) for r in rows]
        summary["reports"] = rows
        summary["skipped_reports"] = sorted(skip)
        # "库里一行报告都没有"与"报告都处理过了"是两件事：
        # 前者是用法错误（没跑 C、也没给报告），必须显式失败；
        # 后者是正常的续跑（什么都不用做，写报告即可）。把前者放过，就成了
        # "假装跑通" —— 那是本系统最不能接受的失败形态。
        if not store.rows("analysis_reports"):
            raise PipelineError(
                "analysis_reports 里没有任何报告，且没有传 agent_c：pipeline 没有可分析的输入。"
                "请先跑一次 C（传 agent_c=<AgentC 实例>，或设置 config['auto_build_agents']=True），"
                "或先用 C 把报告登记进 analysis_reports 再以 replay 模式运行。"
            )
    else:
        summary["reports"] = [
            next(
                (dict(r) for r in store.rows("analysis_reports") if str(r.get("report_id")) == rid),
                {},
            )
            for rid in summary["report_ids"]
        ]

    # ---------- 3. A/B 的缺省装配（显式开启才动网络）
    if agent_a is None and cfg.get("auto_build_agents"):
        agent_a = _build_agent_a(store, cfg, summary)
    if agent_b is None and cfg.get("auto_build_agents"):
        agent_b = _build_agent_b(store, cfg, summary)

    max_per_pass = cfg.get("max_per_pass")
    #: 已经交给 A 处理过的请求号。跨轮次保留，避免同一请求被反复"处理"。
    handled: set[str] = set()
    #: 交给 D 关注过的问题号。必须显式记账：如果只按"状态是 open/needs_evidence"
    #: 去挑，D 每轮都会重新评估那些"证据已经够、只是还没到 researching"的问题，
    #: 重复的 assess / 重复的提问尝试会把摘要淹掉，也会白白消耗查询预算。
    considered: set[str] = set()

    # ---------- 4. 逐轮
    for round_no in range(1, rounds + 1):
        rsum: dict[str, Any] = {"round": round_no, "request": request}
        #: 轮初快照（问题数/状态分布、请求数、文献数）。用于 4.7 的"什么都没变"判据。
        round_start = (
            len(store.rows("research_questions")),
            _status_counts(store),
            len(_all_request_ids(store)),
            len(store.rows("literature")),
        )

        # ---- 4.1 D：提取问题（只做一次 —— C 的报告不会因为轮次变化而变化）
        d_rounds: list[dict] = []
        if round_no == 1:
            for rep in summary.get("reports", []):
                if not rep:
                    continue
                d_rounds.append(agent_d.run_round(rep))
                considered.update(str(q) for q in (d_rounds[-1].get("ingested") or []))
        rsum["d"] = d_rounds
        rsum["submitted"] = sorted({rid for d in d_rounds for rid in d.get("submitted", [])})

        # ---- 4.2 D 复查（§4.1 的 [6]→[3] 回路）：对尚未下结论的问题重新评估。
        # 这一步让"新到的文献"真正进入 D 的判断，而不是只躺在关系表里。
        # 不足的在这里再次提问（工具层的查重会挡住"已有未完成请求"的重复提交）；
        # 就绪的会在第 4.5 步被 poll 拉回 researching。
        resum: dict[str, Any] = {"assessed": [], "submitted": [], "skipped": []}
        for q in sorted(store.rows("research_questions"), key=lambda r: str(r.get("question_id"))):
            qid = str(q.get("question_id"))
            if q.get("status") in ("answered", "dropped"):
                continue
            if qid in considered:
                resum["skipped"].append({"question_id": qid, "reason": "本轮已评估过（避免同一轮内重复评估）"})
                continue
            v = agent_d.assess(qid)
            considered.add(qid)
            # 即使 agent_a=None 也要提问（缺陷修复，见文件顶部"缺陷 3 的结论"）：
            # assess 是纯确定性判断（§4.4 的三条判据），它不依赖 A 是否接线；
            # 提交请求也只是往 `search_requests` 写一行，同样不需要 A 在线。
            # 早先这里在 agent_a=None 时跳过提问，结果是"证据不足"这件事在台账里
            # 完全看不见（问题停在 open），用户会以为 D 没工作。
            # 现在的语义：不接 A = 本轮不执行检索，但缺口照记、等待集照建；
            # 等哪次运行接上了 A，`poll` 就能把它们接下去。
            decision = agent_d.consider(qid)
            resum["assessed"].append(
                {
                    "question_id": qid,
                    "sufficient": v["sufficient"],
                    "criteria": [c["id"] for c in v["criteria"]],
                    "priority": v["priority"],
                    "confidence": v["confidence"],
                    "promoted": decision["promoted"],
                }
            )
            if decision["submitted"]:
                resum["submitted"].extend(decision["submitted"])
                if agent_a is None:
                    resum.setdefault("pending_no_a", []).extend(decision["submitted"])
        rsum["d_consider"] = resum

        # ---- 4.3 A 跑：只处理"这一轮新提交 + 之前未结束"的请求
        pending_before = _pending_request_ids(store)
        to_run = [r for r in pending_before if r not in handled]
        rsum["requests_pending"] = pending_before
        rsum["requests_to_run"] = to_run
        rsum["a"] = _run_agent(agent_a, limit=max_per_pass if to_run else 0)
        if agent_a is None and to_run:
            # A 缺席时这些请求本轮不可能被满足：把它们记进 `handled`，
            # 否则每一轮都会重新尝试一遍同样的请求，摘要里全是重复的
            # `requests_to_run`，而"空转"和"真的在查"就分不出来了。
            # 它们仍留在 `waiting_request_ids` 里（那才是权威的等待集），
            # 等这次运行之外有人跑 A 时，poll 依然能把问题接回来。
            handled.update(to_run)
            rsum["a_note"] = (
                f"agent_a=None：{len(to_run)} 条请求本轮未被执行（不跑检索）。"
                "它们仍在等待集里，语义是「交给外部/下一次运行去满足」。"
            )
        # 记下"已经被 A 领走过"的请求：请求表里的 done/outcome 才是权威状态，
        # 这里只是编排层避免反复指派同一个请求。
        for rid in to_run:
            row = next((r for r in store.rows("search_requests") if str(r.get("request_id")) == rid), None)
            if row is None or row.get("done") or row.get("outcome") or row.get("last_error"):
                handled.add(rid)
        rsum["requests_pending_after_a"] = _pending_request_ids(store, include_claimed=True)

        # ---- 4.4 B 跑：消化新文献（processed=false 的那些）
        unprocessed = [r.get("lit_id") for r in store.rows("literature") if not r.get("processed")]
        rsum["literature_unprocessed"] = unprocessed
        rsum["b"] = _run_agent(agent_b, limit=max_per_pass if unprocessed else 0)

        # ---- 4.5 D poll 复查：等待集 → 就绪 → 拉回 researching → 初步研究
        rsum["d_poll"] = agent_d.poll()
        researched: list[dict] = []
        for q in sorted(store.rows("research_questions"), key=lambda r: str(r.get("question_id"))):
            if q.get("status") != "researching":
                continue
            res = agent_d.research(str(q.get("question_id")))
            researched.append(
                {
                    "question_id": res["question_id"],
                    "confidence": res["confidence"],
                    "criteria": res["criteria"],
                    "llm_used": res["llm_used"],
                }
            )
        rsum["researched"] = researched

        # ---- 4.6 本轮落盘与统计（可中断、可续跑、可审计）
        rsum["questions"] = _status_counts(store)
        rsum["requests_total"] = len(_all_request_ids(store))
        rsum["literature"] = {
            "total": len(store.rows("literature")),
            "processed": sum(1 for r in store.rows("literature") if r.get("processed")),
        }
        summary["rounds"].append(rsum)

        # ---- 4.7 提前收敛：本轮没有任何新动作（没提问、没拉回、没研究、没新文献、
        # 也没有可执行的检索请求），再跑下去只是重复同样的判断。
        # 停下来并把原因如实写进摘要 —— "空转 N 轮"与"真的查了 N 轮"必须能区分。
        a_active = agent_a is not None and bool(to_run)
        acted = bool(
            rsum["submitted"]
            or resum["submitted"]
            or rsum["d_poll"].get("promoted")
            or researched
            or a_active
            or (agent_b is not None and bool(unprocessed))
        )
        if not acted:
            rsum["converged"] = "本轮无任何新动作（无提问/无就绪问题/无新文献/无可执行请求），提前结束"
            break
        # 第二种收敛：库里什么都没变（问题数/状态、请求数、文献数都与轮初相同）。
        # 这意味着"外部世界没有给我新东西"，再评估一次只会得到同样的结论。
        # 记录轮初快照是为了让这条判断可核实 —— 而不是靠"感觉没有进展"。
        now_state = (
            len(store.rows("research_questions")),
            _status_counts(store),
            len(_all_request_ids(store)),
            len(store.rows("literature")),
        )
        if now_state == round_start:
            rsum["converged"] = "本轮结束时库状态与轮初完全相同（无新问题/新请求/新文献），提前结束"
            break

    # ---------- 5. D 写报告（所有轮次的研究结果合并成一份）
    d_path = agent_d.write_report(d_report_path)
    summary["d_report_path"] = d_path
    summary["d_report_rel"] = _rel_to_root(store, d_path)
    summary["questions"] = _status_counts(store)
    summary["questions_total"] = sum(summary["questions"].values())
    summary["requests_total"] = len(_all_request_ids(store))
    summary["requests_submitted"] = sorted(
        {rid for rd in summary["rounds"] for rid in rd.get("submitted", [])}
    )
    return summary


def _rel_to_root(store: Store, path: str | Path) -> str:
    """把绝对路径转成相对 ``store.root`` 的路径（报告里引用时更可读，也便于搬库）。"""
    try:
        return str(Path(path).resolve().relative_to(Path(store.root).resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _build_agent_a(store: Store, cfg: Mapping[str, Any], log: dict) -> Any | None:
    """显式开启 ``auto_build_agents`` 时装配 A（需要 provider 配置）。"""
    try:
        from . import fetch as F
        from .agent_a import AgentA
        from .providers import FixtureProvider, OpenAlexProvider
    except Exception as e:
        log["warnings"].append(f"装配 agent_a 失败：{type(e).__name__}: {e}")
        return None
    acfg = dict(cfg.get("agent_a") or {})
    root = Path(store.root)
    providers = []
    for name in acfg.get("providers") or []:
        if str(name).lower() == "fixture":
            providers.append(FixtureProvider(root / "demo" / "fixtures" / "candidates.json"))
        elif str(name).lower() == "openalex":
            providers.append(OpenAlexProvider(mailto=(cfg.get("search") or {}).get("mailto") or None))
    if not providers:
        log["warnings"].append("agent_a 未装配：agent_a.providers 为空")
        return None
    downloader = F.default_downloader(cfg.get("download") or {}) if acfg.get("download", True) else None
    return AgentA(store, providers=providers, downloader=downloader, config=acfg)


def _build_agent_b(store: Store, cfg: Mapping[str, Any], log: dict) -> Any | None:
    """显式开启 ``auto_build_agents`` 时装配 B。"""
    try:
        from .agent_b import AgentB
        from .extract import extract_text
        from .llm import RuleExtractor
    except Exception as e:
        log["warnings"].append(f"装配 agent_b 失败：{type(e).__name__}: {e}")
        return None
    bcfg = dict(cfg.get("agent_b") or {})
    return AgentB(
        store,
        extractor=RuleExtractor(),
        extract_text=extract_text,
        config=bcfg,
    )


# ---------------------------------------------------------------- 自检


def _seed(store: Store) -> None:
    """造 4 个概念、5 条关系、2 篇文献 + 1 份已登记的 C 报告（离线、确定性）。"""
    concepts = [
        ("0000", "阿贝尔群", "满足交换律的群"),
        ("0001", "非交换环", "乘法不满足交换律的环"),
        ("0002", "域", "每个非零元可逆的交换环"),
        ("0003", "交换性条件", "使得运算可交换的附加条件"),
    ]
    relations = [
        ("0000", ["0000", "0002"], "An abelian group is a group in which the commutative law holds.", True, "active", "0000"),
        ("0001", ["0000", "0003"], "The commutativity condition can be relaxed for finite rings.", True, "active", "0000"),
        ("0002", ["0001", "0003"], "交换性条件不能推广到非交换环。", None, "suspect", "0001"),
        ("0003", ["0001", "0003"], "交换性条件可以推广到非交换环。", None, "suspect", "0001"),
        ("0004", ["0000", "0001"], "Abelian groups are never non-commutative rings.", False, "suspect", "0001"),
    ]
    with store.tx(*CR.tables_for_concept_write("relations", "literature", "analysis_reports"),
                   actor="seed", note="fixture") as tx:
        for cid, name, definition in concepts:
            CR.upsert_legacy_shaped(
                tx,
                S.Concept(concept_id=cid, name=name, definition=definition, normalized_name=name,
                          created_at=S.now_iso(), updated_at=S.now_iso()).to_dict(),
                note="seed",
            )
        for rid, cids, quote, ver, status, lid in relations:
            row = S.Relation(
                relation_id=rid, concept_ids=sorted(cids), description=quote, lit_id=lid,
                page_range=S.PageRange(12, 13, "pp. 12–13"), quote=quote, statement=quote,
                concept_group_key="|".join(sorted(cids)), dedup_key=f"k{rid}", status=status,
                quote_verified=ver, created_at=S.now_iso(),
            )
            row.validate()
            tx.upsert("relations", row.to_dict(), note="seed")
        for lid, title in (("0000", "Commutativity in algebra"), ("0001", "Non-commutative ring theory")):
            tx.upsert(
                "literature",
                S.Literature(lit_id=lid, title=title, type="J", summary="s", path=None,
                             processed=True, added_at=S.now_iso()).to_dict(),
                note="seed",
            )
        # 一份已登记的 C 报告：replay 模式的输入。
        # 它不带 markdown 全文（那属于 C 的落盘职责），登记行是 D 唯一需要的入口。
        tx.upsert(
            "analysis_reports",
            S.AnalysisReport(
                report_id="0000",
                kind="paths",
                request="查询 阿贝尔群 与 域 之间的关系",
                summary="找到 2 条高信息量路径；其中一条两端存在互相矛盾的表述。",
                payload={
                    "a": {"concept_id": "0000", "name": "阿贝尔群"},
                    "b": {"concept_id": "0002", "name": "域"},
                    "levels": {"high": 2, "medium": 0, "low": 0},
                    "paths": [
                        {"concept_path": ["0000", "0002"], "concept_names": ["阿贝尔群", "域"],
                         "relation_chain": ["0000"], "hops": 1, "level": "high", "score": 3.4,
                         "score_breakdown": {"quote_verified": 2.0}},
                        {"concept_path": ["0001", "0003"], "concept_names": ["非交换环", "交换性条件"],
                         "relation_chain": ["0002", "0003"], "hops": 2, "level": "high", "score": 2.1,
                         "score_breakdown": {"quote_verified": 0.0}},
                    ],
                },
                markdown_path="reports/0000-paths.md",
                created_at=S.now_iso(),
            ).to_dict(),
            note="seed",
        )
    # 报告文件也写一份：C 的 persist() 是"先写文件、再写登记行"，
    # 让 replay 模式看到的数据形状与真实情况一致。
    md_dir = _reports_dir(store)
    md_dir.mkdir(parents=True, exist_ok=True)
    (md_dir / "0000-paths.md").write_text("# C 报告（fixture）\n\n仅供 pipeline 自检使用。\n", encoding="utf-8")


class _FakeA:
    """自检用的假 A：把待办请求标记完成并登记一篇文献。

    为什么自检要造它：``agent_a=None`` 只能证明"不跑检索时编排不崩"，
    证明不了闭环（D 提问 → A 查 → B 消化 → D 复查）。这里用最少的
    确定性代码把闭环走通 —— 它不碰网络、不调 LLM，因此可重复。
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.calls = 0

    def run(self, max_requests: int | None = None) -> dict:
        self.calls += 1
        pending = [r for r in self.store.rows("search_requests") if not r.get("done")]
        if max_requests is not None:
            pending = pending[:max_requests]
        lit_ids: list[str] = []
        with self.store.tx("search_requests", "literature", actor="fake-A", note="selftest") as tx:
            for i, req in enumerate(pending):
                lit_id = f"9{i:03d}"  # 9000+ 段位，避开种子用的 0000/0001
                tx.upsert(
                    "literature",
                    S.Literature(
                        lit_id=lit_id,
                        title=f"[selfcheck] {req.get('topic')}（补齐文献 {i}）",
                        type="J",
                        summary="自检用的确定性假文献（无正文）",
                        path=None,
                        processed=False,  # 交给 B 去消化
                        source_request_ids=[str(req.get("request_id"))],
                        dedup_key=f"selfcheck:{req.get('request_id')}",
                        added_at=S.now_iso(),
                    ).to_dict(),
                    note="fake_A",
                )
                req["done"] = True
                req["outcome"] = "ok"
                req["claimed_by"] = None
                req["lease_until"] = None
                req["result_lit_ids"] = [lit_id]
                S.row_from_dict("search_requests", req).validate()
                tx.upsert("search_requests", req, note="fake_A")
                lit_ids.append(lit_id)
        return {"processed": len(pending), "registered": len(lit_ids), "outcome": "ok" if pending else None}


class _FakeB:
    """自检用的假 B：把未消化文献置 processed，并为第一条补一条通过校验的新关系。

    补关系是刻意的：D 的 poll 只有在"等待的请求结束 且 结果文献已被 B 消化"
    之后才会把问题拉回 researching（§4.2）。只置 processed 而不改关系表，
    就测不到"新证据并入证据包"这条路径。
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.calls = 0

    def run(self, max_docs: int | None = None) -> dict:
        self.calls += 1
        todo = [r for r in self.store.rows("literature") if not r.get("processed")]
        if max_docs is not None:
            todo = todo[:max_docs]
        added = 0
        with self.store.tx("literature", "relations", actor="fake-B", note="selftest") as tx:
            for lit in todo:
                lit_id = str(lit.get("lit_id"))
                # 用lit_id 派生一个稳定的关系号（9000 段），避免和种子关系冲突
                rid = f"9{S.is_valid_id(lit_id) and int(lit_id) % 1000 or 0:03d}"[:4]
                if added == 0 and rid not in {str(r.get("relation_id")) for r in tx.rows("relations")}:
                    concept_ids = ["0000", "0001"]
                    quote = "The commutativity condition extends to non-commutative rings under finiteness."
                    row = S.Relation(
                        relation_id=rid,
                        concept_ids=concept_ids,
                        description=quote,
                        lit_id=lit_id,
                        page_range=S.PageRange(3, 3, "p. 3"),
                        quote=quote,
                        statement=quote,
                        concept_group_key="|".join(concept_ids),
                        dedup_key=f"selfcheck:{rid}",
                        status="active",
                        quote_verified=True,  # 关键：给 D 一条"有原文支撑"的关系
                        created_at=S.now_iso(),
                    )
                    row.validate()
                    tx.upsert("relations", row.to_dict(), note="fake_B")
                    added += 1
                lit["processed"] = True
                lit["claimed_by"] = None
                lit["lease_until"] = None
                tx.upsert("literature", lit, note="fake_B")
        return {"processed": len(todo), "relations_added": added}


def _selftest() -> int:
    # 运行方式：在 src/ 下执行 `python -m agentflow.pipeline`（或设 PYTHONPATH=src 后在任意目录执行）
    #
    # 自检不依赖 agent_c / trace_tools / graph_tools：
    #   - agent_c=None  => replay 模式，直接读 analysis_reports 里已登记的报告；
    #   - 先跑一遍 agent_a=None / agent_b=None（静态分析模式，契约要求必须能跑通）；
    #   - 再用内置的确定性假 A/B 跑一遍闭环（提问 → 查 → 消化 → 复查）。
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # 有些 stdout 替身没有 reconfigure；切编码失败不该让自检本身挂掉
        pass

    print("=" * 72)
    root = Path(tempfile.mkdtemp(prefix="agentflow-pipeline-"))
    st = Store(root)
    st.init()
    _seed(st)
    print(f"[0] 临时工作区：{root}")
    print(f"    概念 {len(st.rows('concepts'))} / 关系 {len(st.rows('relations'))} / "
          f"文献 {len(st.rows('literature'))} / 已登记 C 报告 {len(st.rows('analysis_reports'))}")

    out = run_pipeline(
        st,
        request="查询 阿贝尔群 与 域 之间的关系",
        gap_rounds=2,
        # auto_build_c=False：本步刻意测 replay 模式（只用已登记的报告）。
        # 默认是自动装配 C（CLI 那条路径要靠它），那条路径由 [6b] 单独测。
        config={"max_questions": 5, "degree_threshold": 2, "auto_build_c": False},
        agent_c=None,   # replay：从 analysis_reports 读
        agent_a=None,   # 不跑检索
        agent_b=None,
        d_report_path=root / "reports" / "pipeline-research.md",
    )
    print(f"[1] mode={out['mode']} report_ids={out['report_ids']} rounds={len(out['rounds'])}")
    for rd in out["rounds"]:
        print(f"    --- 第 {rd['round']} 轮 ---")
        for d in rd["d"]:
            print(f"      D.ingest 新建问题={d['ingested']} 提交请求={d['submitted']}")
            for a in d["assessed"]:
                print(f"        评估 {a['question_id']}: sufficient={a['sufficient']} "
                      f"criteria={a['criteria']} confidence={a['confidence']}")
        print(f"      requests_to_run={rd['requests_to_run']} A={rd['a']}")
        print(f"      literature_unprocessed={rd['literature_unprocessed']} B={rd['b']}")
        print(f"      D.poll ready={rd['d_poll']['ready']} promoted={rd['d_poll']['promoted']}")
        print(f"      researched={rd['researched']}")
        print(f"      questions={rd['questions']}")
    print(f"[2] 汇总：问题总数={out['questions_total']} 状态={out['questions']} "
          f"请求总数={out['requests_total']} 本轮提交={out['requests_submitted']}")
    print(f"[3] D 报告：{out['d_report_rel']}（{Path(out['d_report_path']).stat().st_size} 字节）")
    # ---- 可中断/可续跑：同一份数据再跑一次，不应重复建问题
    before = len(st.rows("research_questions"))
    out2 = run_pipeline(
        st,
        request="查询 阿贝尔群 与 域 之间的关系",
        gap_rounds=1,
        config={"max_questions": 5, "auto_build_c": False},
        agent_c=None,
        agent_a=None,
        agent_b=None,
        d_report_path=root / "reports" / "pipeline-research-resume.md",
    )
    after = len(st.rows("research_questions"))
    print(f"[4] 续跑（resume=True）：问题 {before} -> {after}（应为 0 新增，origin 去重）"
          f"；report_ids={out2['report_ids']}")
    assert after == before, "续跑重复建了问题：origin 去重失效"

    print("[5] 中间产物落盘检查")
    for p in (
        root / "data" / "research_questions.json",
        root / "data" / "analysis_reports.json",
        root / "reports" / "0000-paths.md",
        Path(out["d_report_path"]),
    ):
        print(f"    {'OK ' if p.exists() else 'MISSING'} {p.relative_to(root)}")

    print("[6] 无 C 报告且禁用自动装配时应显式失败（而不是假装跑通）")
    st2 = Store(Path(tempfile.mkdtemp(prefix="agentflow-pipeline-empty-")))
    st2.init()
    try:
        run_pipeline(st2, request="查询 群 与 域 之间的关系", gap_rounds=1,
                     config={"auto_build_c": False})
    except PipelineError as e:
        print(f"    抛出 PipelineError：{str(e)[:110]}...")
    else:  # pragma: no cover
        raise AssertionError("没有 C 报告时本应显式失败")

    print("[6b] 默认 auto_build_c=True：CLI 那条路径（不传 agent_c）能自己把 C 装上")
    st2b = Store(Path(tempfile.mkdtemp(prefix="agentflow-pipeline-auto-")))
    st2b.init()
    _seed(st2b)
    try:
        out2b = run_pipeline(
            st2b,
            request="查询 阿贝尔群 与 域 之间的关系",
            gap_rounds=1,
            agent_a=None,
            agent_b=None,
            d_report_path=st2b.root / "reports" / "auto-research.md",
        )
        from_c = any(
            n.startswith("C:") for r in st2b.rows("research_questions")
            for n in [str(r.get("origin") or "")]
        )
        print(f"    mode={out2b['mode']} 自动装配的 C 报告={out2b['report_ids']} "
              f"问题={out2b['questions_total']} 状态={out2b['questions']} origin 来自 C={from_c}")
    except PipelineError as e:
        print(f"    自动装配不可用（agent_c 缺失？）：{str(e)[:90]}")

    print("[7] agent_c 外部模块存在？", end=" ")
    try:
        from .agent_c import AgentC  # noqa: F401

        print("是（本自检刻意不使用它：replay 模式已覆盖 pipeline 的全部编排逻辑）")
    except Exception:
        print("否（replay 模式仍然跑通，正是自检要证明的事）")

    # ---- 闭环：D 提问 → A 查 → B 消化 → D poll 复查 → 拉回 researching → 写报告
    print("[8] 闭环（假 A/假 B，确定性、不碰网络）")
    root3 = Path(tempfile.mkdtemp(prefix="agentflow-pipeline-loop-"))
    st3 = Store(root3)
    st3.init()
    _seed(st3)
    fake_a = _FakeA(st3)
    fake_b = _FakeB(st3)
    out3 = run_pipeline(
        st3,
        request="查询 阿贝尔群 与 域 之间的关系",
        gap_rounds=2,
        config={"max_questions": 5, "degree_threshold": 2, "auto_build_c": False},
        agent_c=None,
        agent_a=fake_a,
        agent_b=fake_b,
        d_report_path=root3 / "reports" / "loop-research.md",
    )
    for rd in out3["rounds"]:
        print(f"    --- 第 {rd['round']} 轮 --- 提交={rd['submitted']} A={rd['a']}")
        print(f"        B={rd['b']} unprocessed={rd['literature_unprocessed']}")
        print(f"        poll ready={rd['d_poll']['ready']} promoted={rd['d_poll']['promoted']}")
        print(f"        researched={[(x['question_id'], x['confidence']) for x in rd['researched']]} "
              f"状态={rd['questions']}")
        if rd.get("converged"):
            print(f"        收敛：{rd['converged']}")
    print(f"    最终状态：{out3['questions']}（期望至少有 1 个 researching，证明等待集接得上）")
    assert any(s == "researching" for s in out3["questions"]), "闭环没有把任何问题拉回 researching"
    text3 = Path(out3["d_report_path"]).read_text(encoding="utf-8")
    print(f"    闭环报告：{out3['d_report_rel']} 字数={len(text3)} "
          f"含「L3 下钻」段={'L3 下钻' in text3}")

    print("=" * 72)
    print("SELF-CHECK DONE（pipeline）")
    return 0


if __name__ == "__main__":  # pragma: no cover - 手工运行的自检块
    raise SystemExit(_selftest())
