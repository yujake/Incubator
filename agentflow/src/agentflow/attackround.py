# -*- coding: utf-8 -*-
"""F 的"一轮真推理"形态（`draft/39` §3.16 + §3.19 已批准项）—— 纯判定层。

## 这一层解决什么（D15 的根）

真机读数（p6e/p6f）：`attack.step` 第 1 轮逐字返回 `no_change`（"本框架尚未接线自动推理"），
于是 `attack_plans.history` 有行、计划永远推不动。修法是给一轮定死形态：

- 一轮 = 一次全新的 LLM 会话（种子只给：子目标 + history + `best_partial` + 证据包 +
  上一个 `dead_end` 清单）；
- 每轮只能以四种产物之一收尾（不许 `no_change`）：
  `reduction` / `proof` / `counterexample_request` / `dead_end`；
- 每轮必须填策略名（通用数学工具箱里的一个：归约/反证/极值与双重计数/对称性与去同构/
  构造参数族/局部—整体/编码为 SAT-ILP/套用已知定理/小情形搜索找模式）+ "为什么用它"；
- 确实什么都做不了时，也必须落成 `dead_end` 或"缺什么"——那就是三态（`null` + 理由），
  不是 `no_change`。

已批准的加强项（§3.19）在这一层的落点：

| 条 | 落法 |
|---|---|
| 3 反例优先 / 便宜证伪 | `pre_spend_gate()` 先跑一遍确定性检查（I9）：子目标良定义吗、引的引理是不是已作废、预算还剩吗、这条路是不是已经死过 —— 全过才允许花钱 |
| 6 多路并行 | `pick_parallel_routes(n)` 给出 n 个不同策略名（同轮对多个子目标并发派活用） |
| 8 部分结果进台账 | `dead_end` 的 `best_partial` 必填（已证的引理／缩小的范围／排除的法，逐条带 id）—— 只写在散文里不算 |
| #5 禁止项 | F 的证明步骤不许用"易证/显然/trivial/clearly…"这类缝；两条合法出口：写出那一步，或显式声明 `assumption` |
| I16 超预算的诚实阻塞 | `budget_decision()` 在超过上限时给 `too_large`（不许静默截断）；拆子目标是编排方的活，这一层不自己切 |
| I11 依赖的缺陷继承 | `proof` 的每一步引到的命题必须在 `clean_ids` 里（不在 ⇒ 那一步继承缺陷，error） |

## 为什么它是一层纯函数

"一轮该收什么、什么时候才允许花钱、哪一步继承了缺陷"这三件事都不需要模型：
它们是形态与判据。把它们做成纯函数，才能离线、确定性地判（E11/E12/E13 就是这么跑的），
而模型只负责往里填内容。
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Sequence

#: 一轮的四种产物（`draft/39` §3.16）：没有 `no_change` 这一档，它是被修掉的那个形态。
PRODUCTS: tuple[str, ...] = ("reduction", "proof", "counterexample_request", "dead_end")
#: 通用数学工具箱（方法名，不含任何本题的构造或结论）：每轮必填一个。
STRATEGIES: tuple[str, ...] = (
    "归约", "反证", "极值与双重计数", "对称性与去同构", "构造参数族",
    "局部—整体", "编码为 SAT/ILP", "套用已知定理", "小情形搜索找模式",
)
#: F 不许写的"缝"（用户 2026-10-05 口径：F 禁止写"易证/显然/trivial/clearly/it is easy to see"）。
F_BANNED_MARKERS: tuple[str, ...] = (
    "易证", "显然", "trivial", "clearly", "it is easy to see", "无须证明", "显然成立",
)
#: `dead_end` 的受控理由（"这条路死了"也要说清是哪一种死法）。
DEAD_END_REASONS: tuple[str, ...] = (
    "反例", "方法不适用", "缺定义", "缺文献", "缺工具", "超出本轮预算", "需要先证别的命题",
)
#: 一轮里"每一条新子目标"必须带的东西（给不出可检验形式的就是没归约成功）。
SUBGOAL_FIELDS: tuple[str, ...] = ("goal", "testable")


class RoundError(ValueError):
    """这一轮没成形（不是"推理失败"）：产物不在四种里、缺策略名、缺必填栏。"""


def parse_round(text: str) -> dict[str, Any]:
    """把 F 那一轮的输出解析成一份成形产物；不成形 ⇒ 抛 `RoundError`（交回重说）。

    三态在这里："这一轮什么都没做出来"必须是 `dead_end`（带理由）——
    旧形态的 `no_change` 会被当不成形打回（它正是 D15 要根除的那个返回值）。
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    body = raw[start:end + 1] if (start >= 0 and end > start) else raw
    try:
        got = json.loads(body)
    except ValueError as exc:
        raise RoundError(f"这一轮的输出不是合法 JSON（{type(exc).__name__}: {exc}）") from exc
    if not isinstance(got, Mapping):
        raise RoundError("这一轮的输出必须是对象")
    if str(got.get("product") or "").strip() == "no_change" or "no_change" in raw:
        raise RoundError(
            "`no_change` 不是四种产物之一（它正是 D15 要根除的形态）："
            "什么都做不了时也要落成 `dead_end`（受控理由 + 证据 + best_partial）"
        )
    product = str(got.get("product") or "").strip()
    if product not in PRODUCTS:
        raise RoundError(f"product 必须是 {PRODUCTS} 之一，收到 {product!r}")
    strategy = str(got.get("strategy") or "").strip()
    if strategy not in STRATEGIES:
        raise RoundError(f"strategy 必须是通用工具箱里的一个 {STRATEGIES}，收到 {strategy!r}")
    why = str(got.get("why_strategy") or "").strip()
    if not why:
        raise RoundError("why_strategy 必填（这一轮为什么用这一招）—— 只写方法名等于没交代")
    out: dict[str, Any] = {"product": product, "strategy": strategy, "why_strategy": why}

    if product == "reduction":
        goals = got.get("new_subgoals")
        if not isinstance(goals, (list, tuple)) or not (1 <= len(goals) <= 3):
            raise RoundError("reduction 要给 1–3 条新子目标（不多不少：超过三条就是没归约）")
        clean: list[dict[str, str]] = []
        for i, g in enumerate(goals, 1):
            if not isinstance(g, Mapping):
                raise RoundError(f"new_subgoals[{i}] 必须是对象（{SUBGOAL_FIELDS}）")
            missing = [k for k in SUBGOAL_FIELDS if not str(g.get(k) or "").strip()]
            if missing:
                raise RoundError(
                    f"new_subgoals[{i}] 缺 {missing}：给不出可检验形式的新子目标，"
                    "不是一条归约（那种情形落 `dead_end` 并写清缺什么）")
            clean.append({"goal": str(g["goal"]).strip(), "testable": str(g["testable"]).strip()})
        out["new_subgoals"] = clean
        out["reason"] = str(got.get("reason") or "").strip()
    elif product == "proof":
        steps = got.get("steps")
        if not isinstance(steps, (list, tuple)) or not steps:
            raise RoundError("proof 要给逐步论证（steps 非空）")
        out["steps"] = [_clean_step(s, i) for i, s in enumerate(steps, 1)]
    elif product == "counterexample_request":
        spec = got.get("script_spec")
        if not isinstance(spec, Mapping):
            raise RoundError("counterexample_request 要给 script_spec（判据/参数/界的期望）")
        need = ("criterion", "params", "expected_bound")
        missing = [k for k in need if not str(spec.get(k) or "").strip()]
        if missing:
            raise RoundError(f"script_spec 缺 {missing}：没有判据的实验请求，E 没法跑")
        if not str(got.get("why_it_decides") or "").strip():
            raise RoundError("why_it_decides 必填（这个实验凭什么能判这条命题）")
        out["script_spec"] = {k: str(spec[k]) for k in need}
        out["why_it_decides"] = str(got["why_it_decides"]).strip()
    else:  # dead_end
        reason = str(got.get("reason") or "").strip()
        if reason not in DEAD_END_REASONS:
            raise RoundError(f"dead_end 的理由必须是受控值 {DEAD_END_REASONS}，收到 {reason!r}")
        if not str(got.get("evidence") or "").strip():
            raise RoundError("dead_end 必须给证据（哪一步不行）—— 只说'不行'等于没交代")
        partial = got.get("best_partial")
        if not isinstance(partial, (list, tuple)) or not partial:
            raise RoundError(
                "dead_end 的 best_partial 必填（已证的引理／缩小的范围／排除的法，逐条带 id）"
                "—— §3.19 第 8 条：部分结果不许只写在散文里"
            )
        clean_p: list[dict[str, str]] = []
        for i, item in enumerate(partial, 1):
            if not isinstance(item, Mapping) or not str(item.get("what") or "").strip():
                raise RoundError(f"best_partial[{i}] 要有 what（做了什么）")
            clean_p.append({"what": str(item["what"]).strip(),
                            "ids": [str(x) for x in (item.get("ids") or [])],
                            "why_partial": str(item.get("why_partial") or "").strip()})
        out["reason"] = reason
        out["evidence"] = str(got["evidence"]).strip()
        out["best_partial"] = clean_p
    return out


def _clean_step(step: Any, n: int) -> dict[str, Any]:
    """规范化一步证明，并把 #5 的硬禁令与"同段依据"判在这里。"""
    if not isinstance(step, Mapping):
        raise RoundError(f"steps[{n}] 必须是对象")
    text = str(step.get("text") or "").strip()
    if not text:
        raise RoundError(f"steps[{n}] 的 text 为空")
    cites = [str(x) for x in (step.get("cites") or [])]
    is_assumption = step.get("assumption") is True
    hit = [m for m in F_BANNED_MARKERS if m in text]
    if hit and not is_assumption:
        raise RoundError(
            f"steps[{n}] 出现「{'、'.join(hit)}」这类缝。两条**合法出口**（选一条）："
            "① 把这一步**写出来**（给出推导或引到在册的 id）；"
            "② 显式把它声明成前提（`assumption: true`）—— 缝是正确的事实变成错误证明的地方，"
            "不许用措辞跳过去"
        )
    if not cites and not is_assumption:
        raise RoundError(
            f"steps[{n}] 既没有引到在册的 id，也没有声明成前提（`assumption: true`）—— "
            "「每一步都要指出依据」是 I10 的最小形态"
        )
    return {"n": n, "text": text, "cites": cites, "assumption": is_assumption}


def inherit_defects(round_row: Mapping[str, Any], *, clean_ids: Iterable[str]) -> list[dict[str, Any]]:
    """I11：`proof` 的每一步引到的命题必须在 `clean_ids` 里，否则那一步继承缺陷。

    返回逐条缺陷（空列表 = 干净）。"干净"的口径由调用方给（五元位第 2/3 位为真，或显式
    `assumption`）—— 这一层只做"引用是否落在干净集合里"这一件事，不重复判五元位。
    """
    clean = {str(x) for x in clean_ids}
    out: list[dict[str, Any]] = []
    for step in (round_row.get("steps") or []):
        for cid in (step.get("cites") or []):
            if str(cid) not in clean and not step.get("assumption"):
                out.append({"step": step.get("n"), "ref": str(cid), "kind": "inherited_defect",
                            "detail": f"第 {step.get('n')} 步引了 {cid}，而它不在干净集合里 "
                                      "⇒ 这一步继承那个缺陷（I11）"})
    return out


#: 预算读数读不到时要说的话（P-09 的代码那一半，`draft/44:60`）。
#:
#: 它是"一处口径"而不是"两处措辞"：代码侧（F 写进 `why_strategy` 与返回值的
#: `budget_reading.why`）与提示词侧（`agent_prompts.ROLE_BRIEFS["E"].policy`）
#: 引用的是这一个常量 —— 哪一处被改成别的说法，
#: `tests/test_agent_f_inference.py::test_p09_the_framework_written_why_strategy_carries_the_same_sentence`
#: 就会红。
#:
#: 为什么不能写成"那时按最保守的做法办"（本仓库此前在提示词里就是那个方向）：
#: 读不到不等于不许花。把"读数缺失"折成"全局停摆"是相反的方向，
#: 而且那正是本项目最贵的缺陷形态（把 null 与 0 折成同一个值）。
BUDGET_UNREADABLE_NOTE = (
    "代价读数读不到时如实说读不到；那是「读不到」，不是「没有代价」，"
    "也不因此把所有的路都堵死"
)

#: 读数读不到时，钱由谁管（file:line 证据写成常量，好让"证据"本身可被引用与断言）。
#:
#: - `conductor.py:1063-1077`：`[4a]` FC-19 预算守卫 —— `self._meter_guard(role, budget)`
#:   在写 `running` 行之前跑（顺序是判据的一部分：干完再拒不是同一个功能）；
#: - `policy.py:338-343`：`Refusal("budget_exceeded", …, "usd_budget")` 那一档。
BUDGET_GUARD_NOTE = (
    "钱仍由全局预算守卫管：conductor.py:1063-1077 的 [4a] 开工前守卫"
    "（guard() 在写 running 行之前跑）与 policy.py:338-343 的 usd_budget 判据"
)

#: 预算读数的真源为什么还没接上（缺口登记：不许"永远 unknown 但没人说"）。
#:
#: 缺的上下文是当前这一次召唤的 `task_id`：`conductor.py:1140-1144` 把它交给了后端，
#: `agent_loop.py:2652-2656` 的循环也拿得到，但工具层拿不到 ——
#: `tools/base.py:1304-1313` 的 `ToolRegistry.call` 没有任务上下文的形参，
#: 于是 `tools/attack_tools.py:281-300` 的 `_agent_for(store)` 只有 `store`。
BUDGET_GAP_NOTE = (
    "真源还没接上：工具路径拿不到当前这一次召唤的 task_id"
    "（缺的是这个上下文：tools/base.py:1304 的 ToolRegistry.call 没有任务上下文的形参，"
    "tools/attack_tools.py:281-300 的 _agent_for(store) 只能拿到 store）"
    "⇒ 注入点暂时没有值可注入；它是残余集 R1 的「P-09 粒度口径」的前置"
    "（记账粒度是召唤级：tokenmeter.py:250-286 的 usd_for / usd_reading 都以 task_id 为键）"
)


def pre_spend_gate(*, goal: str, testable: str = "", deps_refuted: Sequence[str] = (),
                   tried_strategies: Sequence[str] = (), budget_left_usd: float | None = None,
                   ) -> dict[str, Any]:
    """花钱之前的确定性闸门（I9 + 已批准的第 3 条：先做便宜的证伪）。

    返回 `{"spend": bool, "reasons": [...], "checks": {...}}`：`spend=False` 时调用方
    不许发模型调用（省下的钱正是这一层要省的）。每一条都是盘上/参数里就有的事实，
    不需要模型参与。
    """
    checks: dict[str, Any] = {}
    reasons: list[str] = []
    checks["goal_nonempty"] = bool(str(goal or "").strip())
    if not checks["goal_nonempty"]:
        reasons.append("子目标为空 ⇒ 先让 D/M 把它说清楚（这一轮不该花钱）")
    checks["testable_given"] = bool(str(testable or "").strip())
    if not checks["testable_given"]:
        reasons.append("子目标没有可检验形式（`testable` 空）⇒ 先落 `needs_evidence` 并写清为什么")
    refuted = [str(x) for x in deps_refuted]
    checks["deps_refuted"] = refuted
    if refuted:
        reasons.append(f"引到的命题里有已被作废/反驳的：{refuted} ⇒ 先把依赖换掉再花这一轮的钱")
    tried = [str(x) for x in tried_strategies]
    remaining = [s for s in STRATEGIES if s not in set(tried)]
    checks["strategies_tried"] = {
        "tried": sorted(set(tried)), "remaining": remaining, "exhausted": not remaining,
        # 代价读数（P-09）：这句话是读数，不是否决 —— 见下面那段边界说明。
        "note": (f"{len(STRATEGIES)} 招里试过 {len(set(tried))} 招、还剩 {len(remaining)} 招"
                 + ("（已穷尽：再试只能是同一批招）" if not remaining else "")),
    }
    # ---- P-09（`draft/44:60`）：计数不否决花钱。
    #
    # 此前这里是 `checks["all_strategies_tried"] = len(set(tried)) >= len(STRATEGIES)`
    # 并把它写进 `reasons` ⇒ `spend=False`。那是"该模型抉择的事被写死成一个死旋钮"：
    # 九招试完该不该再花一轮（换子目标 vs 再试同一批招）是代价判断，不是事实。
    # 现在它只是一条读数（`strategies_tried`：试过哪几招 / 还剩哪几招 / 是否穷尽、
    # 以及一句代价读数），由 F 自己按代价裁量并把裁量写进 `why_strategy`（留痕）。
    #
    # 上面四条检查（空目标 / 没有可检验形式 / 引到已作废的命题 / 预算耗尽）照旧是事实，
    # 仍然 `spend=False` —— 删它们会让"缺定义也去花钱"，那不是同一条裁定管的事。
    checks["budget_known"] = budget_left_usd is not None
    if budget_left_usd is not None:
        checks["budget_ok"] = float(budget_left_usd) > 0
        if not checks["budget_ok"]:
            reasons.append("预算已耗尽 ⇒ 一轮都不许再开（如实写进交付，不许静默截断）")
    return {"spend": not reasons, "reasons": reasons, "checks": checks}


def budget_decision(*, cost_usd: float, cap_usd: float | None, spent_usd: float = 0.0) -> dict[str, Any]:
    """I16：超上限的一轮要显式阻塞（`too_large`），不许静默截断。

    "拆子目标"是编排方（M/D）的活，这一层不自己切 —— 所以它只回一个状态与一句人话，
    让调用方把它如实写进计划历史。
    """
    if cap_usd is None:
        return {"status": "unbounded", "note": "没有上限：按调用方自己的预算四键管"}
    projected = float(spent_usd) + float(cost_usd)
    if projected > float(cap_usd):
        return {"status": "too_large",
                "note": (f"这一轮预计 ${projected:.4f} 超过上限 ${float(cap_usd):.4f} ⇒ "
                         "如实阻塞（`too_large`），**不截断**这一轮；要拆子目标请找 M/D —— "
                         "拆解是编排方的活，不是 F 的"),
                "projected_usd": round(projected, 6)}
    return {"status": "ok", "projected_usd": round(projected, 6)}


def pick_parallel_routes(n: int, *, tried: Sequence[str] = ()) -> list[str]:
    """已批准的第 6 条：同轮跑不同策略的多路（先挑没试过的），避免"多路=同一招三遍"。"""
    want = max(0, int(n))
    tried_set = {str(x) for x in tried}
    fresh = [s for s in STRATEGIES if s not in tried_set]
    return (fresh or list(STRATEGIES))[:want]


def dead_end_row(*, strategy: str, reason: str, evidence: str,
                 best_partial: Sequence[Mapping[str, Any]],
                 why_strategy: str = "") -> dict[str, Any]:
    """造一条成形的 `dead_end` 产物（走同一套判据 —— 一处校验，不手搓 dict）。

    为什么要有这个构造器（`draft/39` §6.14 的接线）：F 的 `step` 里有几条收尾路径
    （没有 owner 侧的推理入口、没有可推进的子目标、预算用尽）本来就是"这一轮没有新事实"，
    而它们此前只写一个 `outcome="no_change"` —— 没有产物。按 §3.16，那种情形必须落成
    `dead_end`（受控理由 + 证据 + `best_partial`），于是"这一轮到底交了什么"可查。
    """
    payload = {"product": "dead_end", "strategy": strategy,
               "why_strategy": (why_strategy
                                or "这一步走不下去：没有可调用的推理入口或没有可推进的子目标"),
               "reason": reason, "evidence": evidence,
               "best_partial": [dict(x) for x in best_partial]}
    return parse_round(json.dumps(payload, ensure_ascii=False))


def selftest() -> int:
    """最小自检：四产物可解析、`no_change` 打回、#5 两条合法出口、闸门与预算阻塞。"""
    checks: list[tuple[str, bool]] = []
    red = parse_round(json.dumps({"product": "reduction", "strategy": "归约",
                                  "why_strategy": "先缩小范围",
                                  "new_subgoals": [{"goal": "证 n=3", "testable": "枚举"}]}))
    checks.append(("reduction 成形", red["product"] == "reduction"))
    try:
        parse_round('{"product": "no_change", "strategy": "归约", "why_strategy": "x"}')
        checks.append(("no_change 被打回", False))
    except RoundError:
        checks.append(("no_change 被打回", True))
    bad = json.dumps({"product": "proof", "strategy": "反证", "why_strategy": "反设",
                      "steps": [{"text": "显然成立"}]})
    try:
        parse_round(bad)
        checks.append(("#5 缝被打回", False))
    except RoundError as exc:
        checks.append(("#5 缝被打回（并给两条出口）", "合法出口" in str(exc)))
    ok = parse_round(json.dumps({"product": "proof", "strategy": "反证", "why_strategy": "反设",
                                 "steps": [{"text": "显然成立", "assumption": True}]}))
    checks.append(("声明成前提即合法", ok["steps"][0]["assumption"] is True))
    gate = pre_spend_gate(goal="证 n=3", testable="枚举", deps_refuted=["stmt:0007"])
    checks.append(("作废依赖 ⇒ 不花钱", gate["spend"] is False and gate["reasons"]))
    checks.append(("超预算 ⇒ too_large",
                   budget_decision(cost_usd=2.0, cap_usd=1.0)["status"] == "too_large"))
    checks.append(("多路挑没试过的", pick_parallel_routes(2, tried=["归约"])[:2] != ["归约", "归约"]))
    for name, good in checks:
        print(f"  [{'PASS' if good else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
