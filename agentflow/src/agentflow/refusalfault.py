"""拒信必须说真话：框架内部错误的分档、落库事实、诊断不丢、审计痕迹。

## [为什么] 这个模块存在的理由（真机 `projects/lp-ball-13`，2026-11-20）

`agent_f/core.py` 的 `_merged_plan_round` 的 dict 解包被一次 lint 抹成 set 字面量 ⇒
每一次 `attack.step` 的写回都抛 `TypeError: unhashable type: 'dict'` ⇒ 工具层的
`_guard` 把它折成「校验失败：unhashable type: 'dict'（这一笔没有落库）」。三个后果
（MINE-LOOP 报告 §P0-1/§P0-2/§P0-3）：

1. 框架 bug 伪装成"你交的东西不合格"：F 15 次调用 15 次同一个拒信，只会换措辞重试，
   5 连拒之后 `no_progress_limit` 收工，而真正要修的框架那一行一次都没被说出来；
2. 拒信谎报落库：同一秒 `reports/f-proof-000001.md` 已经落了盘，拒信却说没有 ——
   模型据此以为一个字节都没写，于是重交同一份稿（其中一份其实是合格的）；
3. 诊断被吞：校验器已经算出的逐条问题（行 501/560/789 各 8 条）被一句 TypeError 顶掉；
4. 审计痕迹丢失：`history[*].refusal` 挂在那一笔写回上，写回一炸就一起没了。

## 四条判据的唯一落点

- 分档：`FRAMEWORK_FAULTS`（类型表）＋ `framework_failure`（受控码 `FRAMEWORK_ERROR_KIND`）；
  负控打桩点就是那张类型表：把它清空 ⇒ 同一支 TypeError 又回校验失败那一档。
- 落库：`disk_state`（前后两次读数）＋ `landing_reading`（三态对比）＋ `landing_sentence`
  （拒信里那句"有没有落库"只许照它说，`checked=False` 时不许说"没有"）。
- 诊断：`problems_of`（`None` = 没查 / `[]` = 查了 0 条 / 非空 = 逐条）＋
  `product_problems`（现调 `parse_handed_product`，不另写一份判据）。
- 审计：`record_step_refusal`（写回炸了之后单独补一行 `history[*].refusal`，
  打 `REFUSAL_AUDIT_MARKER` 标记，好让落库读数不把"我自己补的那一行"算成内容产物）。

## 为什么单独一个模块（不是塞进 `tools/attack_tools.py` / `agent_f/step.py`）

两处都要用它，而这两份文件都在 800 行的软基线附近（`tests/test_repo_survey_does_not_get_worse.py`
的 `src_files_gt800_lines` 一格只许降不许抬）。口径也自成一件事：它答的是
"一次拒绝的回执该说什么"，与"攻坚计划怎么写回"是两个问题。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

#: 受控码：框架内部错误（模型改哪一格都修不好）。
#:
#: 为什么必须与 `validation_error` 分开：后者说的是"你的输入不合格"，而这一档说的是
#: "框架自己坏了"。折成一档，模型就只会换措辞重试 —— 真机那 15 连拒就是这么来的。
FRAMEWORK_ERROR_KIND = "framework_error"

#: 归到框架内部错误的异常类型：模型改不成的那一族。
#:
#: 判据按类型而不按文案：模型输入不合格走显式校验（`ValueError` / `PlanError`，逐字带
#: 字段名），而这一族在真机上抓到的都是框架自己的 bug。这张表是分档的唯一落点，
#: 也是负控的打桩点（清空 ⇒ 同一支 TypeError 又回 `validation_error`）。
FRAMEWORK_FAULTS: tuple[type[BaseException], ...] = (
    TypeError, AttributeError, KeyError, IndexError, AssertionError,
    NameError, UnboundLocalError, NotImplementedError,
)

#: 拒因留痕行在 `attack_plans.history[*]` 上的标记（唯一产点 `record_step_refusal`）。
#:
#: 为什么需要它：那一行是"写回炸了之后补写的拒因"，不是这一轮的内容产物。
#: `disk_state` 数 history 行数时要把它排除在外 —— 否则"我自己补的那一行"会被读成
#: "这一笔的稿落库了"，而落库读数正是这条判据要防的那种谎。
REFUSAL_AUDIT_MARKER = "f.step:refusal"


# ---------------------------------------------------------------- 落库事实（只读）


def disk_state(store: Any, plan_id: str = "") -> dict[str, Any]:
    """这一笔调用前后的盘上读数（只读）：计划台账那一行 ＋ `reports/` 下的稿。

    三态：`checked=False` 表示没读到（原因在 `why` 里）—— 调用方据此说"查不到有没有
    落库"，不许把它折成"没有落库"（那正是 MINE-LOOP 报告 §P0-2 的形态）。
    """
    out: dict[str, Any] = {"checked": True, "why": "", "plans": None,
                           "rounds": None, "history": None, "reports": {}}
    reasons: list[str] = []
    try:
        rows = [dict(r) for r in store.rows("attack_plans")]
        out["plans"] = len(rows)
        row = (next((r for r in rows if str(r.get("plan_id") or "") == plan_id), None)
               if plan_id else None)
        if row is not None:
            out["rounds"] = int(row.get("rounds") or 0)
            out["history"] = sum(
                1 for h in (row.get("history") or [])
                if str((h if isinstance(h, Mapping) else {}).get("audit") or "")
                != REFUSAL_AUDIT_MARKER)
    except Exception as e:  # noqa: BLE001 —— 读不到就如实说，不许折成"没有"
        reasons.append(f"读不到 attack_plans：{type(e).__name__}: {e}")
    try:
        folder = Path(str(getattr(store, "root", "") or "")) / "reports"
        if folder.is_dir():
            for p in sorted(folder.glob("*.md")):
                if p.is_file():
                    got = p.stat()
                    out["reports"][p.name] = (int(got.st_size), int(got.st_mtime_ns))
    except Exception as e:  # noqa: BLE001
        reasons.append(f"读不到 reports/：{type(e).__name__}: {e}")
    if reasons:
        out["checked"] = False
        out["why"] = "；".join(reasons)
    return out


def landing_reading(before: Mapping[str, Any], after: Mapping[str, Any], *,
                    plan_id: str = "") -> dict[str, Any]:
    """两次盘上读数的对比 ⇒ 拒信里那句"有没有落库"的唯一依据。

    `landed` 三态：`True`（盘上确实多了东西）/ `False`（前后一模一样）/
    `None`（没读成 —— 不许折成 `False`）。
    """
    if not before.get("checked") or not after.get("checked"):
        return {"checked": False, "landed": None, "facts": [],
                "why": after.get("why") or before.get("why") or "盘上读数没查成"}
    facts: list[str] = []
    b_plans, a_plans = before.get("plans"), after.get("plans")
    if b_plans is not None and a_plans is not None and a_plans > b_plans:
        facts.append(f"attack_plans 多了 {a_plans - b_plans} 行（{b_plans} → {a_plans}）")
    for key, label in (("rounds", "rounds"), ("history", "history 行数")):
        b, a = before.get(key), after.get(key)
        if b is not None and a is not None and a > b:
            facts.append(f"计划 {plan_id or '（没给 plan_id）'} 的 {label} {b} → {a}")
    reports_before = before.get("reports") or {}
    reports_after = after.get("reports") or {}
    for name, got in sorted(reports_after.items()):
        old = reports_before.get(name)
        if old is None:
            facts.append(f"reports/{name} 新落了盘（{got[0]} B）")
        elif tuple(old) != tuple(got):
            facts.append(f"reports/{name} 被改写（{old[0]} B → {got[0]} B）")
    return {"checked": True, "landed": bool(facts), "facts": facts,
            "why": ("盘上前后两次读数一样（没有这一笔的写）" if not facts
                    else "盘上前后两次读数的对比")}


class LandingProbe:
    """这一笔调用前后各读一次盘（只读），供拒信说清"有没有落库"。

    为什么拒信必须照盘上的事实说：旧拒信无条件写「这一笔没有落库」，而同一秒
    `reports/f-proof-000001.md` 已经落盘 —— 模型据此以为自己一个字节都没写。
    """

    def __init__(self, store: Any, plan_id: str = "") -> None:
        self.store = store
        self.plan_id = str(plan_id or "")
        self.before = disk_state(store, self.plan_id)

    def reading(self) -> dict[str, Any]:
        after = disk_state(self.store, self.plan_id)
        return landing_reading(self.before, after, plan_id=self.plan_id)


def landing_of(landing: Any) -> dict[str, Any]:
    """把探针读成一份读数（探针不在 / 探针自己炸了 ⇒ 如实说没查成）。"""
    if landing is None:
        return {"checked": False, "landed": None, "facts": [],
                "why": "这一档没有查盘（只有写盘的入口会查）"}
    try:
        got = landing.reading() if hasattr(landing, "reading") else landing()
    except Exception as e:  # noqa: BLE001
        return {"checked": False, "landed": None, "facts": [],
                "why": f"查盘本身炸了：{type(e).__name__}: {e}"}
    return dict(got or {})


def landing_sentence(landing: Mapping[str, Any]) -> str:
    """拒信里"有没有落库"的那一句：只许照着盘上读数说（三态，不折平）。"""
    if not landing.get("checked"):
        return ("落库状态：没查成（" + str(landing.get("why") or "") + "）—— "
                "这不等于没有落库；别据此重交同一份东西。")
    if landing.get("landed"):
        facts = "；".join(str(x) for x in (landing.get("facts") or ()))
        return ("落库状态（以盘上事实为准）：已落库 —— " + facts + "。"
                "这些内容已经在盘上了，别把它们当成没写进来再交一次。")
    return ("落库状态（以盘上事实为准）：这一笔没有落库（"
            + str(landing.get("why") or "前后两次读数一样") + "）。")


# ---------------------------------------------------------------- 诊断（校验器的逐条问题）


def problems_of(problems: Callable[[], Sequence[str]] | None) -> list[str] | None:
    """校验器已经算出的逐条问题：异常路径上也要带出去，不许吞。

    调用方给的是一次只读重算（`parse_handed_product`），不是异常对象里的残片 ——
    真问题在异常发生之前就已经算完了，只是旧代码没有把它接到拒信上。

    三态：`None` = 这一档没有校验器（没查，回执里不许出现"0 条"）；`[]` = 查了、
    0 条问题（那一份本身过了逐条校验，这也是要如实说的一句）。
    """
    if problems is None:
        return None
    try:
        return [str(x) for x in (problems() or ())]
    except Exception as e:  # noqa: BLE001 —— 校验器自己也炸了就如实说，不冒充"没问题"
        return [f"（校验器没跑成：{type(e).__name__}: {e}）"]


def product_problems(product: Any) -> list[str]:
    """校验器对 `attack.step(product=…)` 这一份的逐条问题。

    为什么直接调 `parse_handed_product`：它是 `attack.step` 的第一道闸，逐条问题本来
    就由它算出来（真机：会话行 501/560/789 各 8 条「steps[k] 既没有给 cites 也没有
    声明成前提」，行 895 是 0 条 —— 而那份稿其实合格）。异常路径上再算一次是只读、
    幂等的；另写一份判据就必然与它漂。

    调用方只在"这一笔真的交了 `product`"时才传它（老路 `attack.step(plan_id=…)` 没有
    可校验的那一份）—— 于是"没交"（不查）与"交了、0 条问题"在读数上分得开。
    """
    from .agent_f.core import parse_handed_product  # 惰性：tools ↔ agent 的循环导入

    got = parse_handed_product(product)
    return [str(x) for x in (got.get("problems") or ())]


def how_to_fix(problems: Sequence[str]) -> str:
    """校验失败那一档的可执行改法（从逐条问题里读出来，不另编一套判据）。"""
    text = " ".join(problems)
    if "cites" in text or "assumption" in text:
        return ("`product.steps[k]` 的每一步要么给 `cites`（本轮在册的 id），要么写 "
                "`assumption: true` 把它声明成前提 —— 按上面点到的步号逐条补齐，再把同一份 "
                "`product` 交一次（`attack.step(plan_id=…, product=…)`）")
    if problems:
        return ("按上面逐条改那几步 / 那几格，再把同一份 `product` 交一次"
                "（`attack.step(plan_id=…, product=…)`）")
    return "按上面那句字段级报错改输入，再调一次。"


def refusal_record_line(exc: BaseException) -> str:
    """拒信里"这一轮的拒因有没有写进 history"那一句（写回炸了那一档给）。

    `record_step_refusal` 把结果挂在异常的 `refusal_record` 上；这里只读它，
    不替它下结论（没挂上 ⇒ 说没查，不说"没写进去"）。
    """
    got = getattr(exc, "refusal_record", None)
    if not isinstance(got, Mapping):
        return "审计痕迹：这一档没有单独的拒因落点（拒因只在这条回执里）。"
    if got.get("recorded"):
        return ("审计痕迹：这一轮的拒因已经写进计划台账的 `history[*].refusal`"
                "（`action=refused`），人读台账时不必只靠这条回执。")
    return ("审计痕迹：这一轮的拒因没写进计划台账（" + str(got.get("why") or "原因没记下")
            + "）—— 这是第二处缺陷，报给 M / 人 时请一并说。")


# ---------------------------------------------------------------- 两种拒信


def framework_failure(exc: BaseException, *,
                      problems: Callable[[], Sequence[str]] | None,
                      landing: Any, tool: str) -> tuple[str, dict[str, Any]]:
    """框架内部错误 ⇒ 受控码 ＋ "不是你交的东西不合格" ＋ 落库事实 ＋ 校验器的逐条读数。

    返回 `(拒信正文, meta)`：`meta["kind"]` 就是受控码（`_refusal_key` 据此另立一个
    连击键，不再与"校验失败"混着数）。
    """
    land = landing_of(landing)
    items = problems_of(problems)
    lines = [
        f"框架内部错误（{FRAMEWORK_ERROR_KIND}）：{type(exc).__name__}: {exc}",
        "这是框架侧的问题，不是你交的东西不合格 —— 换措辞重试没有用：同一份东西再交一次，"
        "框架还会在同一处抛同一个错。",
        "把它报给 M / 人（要修的是框架里抛异常的那一处，不是你的产物）。",
        landing_sentence(land),
        refusal_record_line(exc),
    ]
    if items is not None:
        if items:
            lines.append("校验器对你这一份的逐条读数（框架异常之前就算出来了，一条没丢）：")
            lines.extend(f"- {p}" for p in items)
        else:
            lines.append("校验器对你这一份的逐条读数：0 条 —— 这一份本身过了逐条校验，"
                         "拒因只在上面那条框架异常里。")
    meta = {
        "kind": FRAMEWORK_ERROR_KIND,
        "refusal_code": FRAMEWORK_ERROR_KIND,
        "reason": f"{type(exc).__name__}: {exc}",
        "exc_type": type(exc).__name__,
        "problems": items,
        "landing": land,
        "tool": tool,
        "how_to_fix": ("不要改产物的措辞；把这一条报给 M / 人（框架 bug）。"
                       "能绕开就换一条 plan 或换一个入口继续，并把这一条写进 note"),
        "refusal_record": getattr(exc, "refusal_record", None),
    }
    return "\n".join(lines), meta


def validation_failure(exc: BaseException, *,
                       problems: Callable[[], Sequence[str]] | None,
                       landing: Any, tool: str) -> tuple[str, dict[str, Any]]:
    """校验失败（模型的输入不合格）⇒ 逐条问题 ＋ 可执行的改法 ＋ 落库事实。"""
    land = landing_of(landing)
    items = problems_of(problems)
    how = how_to_fix(items or [])
    lines = [f"校验失败：{exc}"]
    if items is not None:
        if items:
            lines.append("逐条问题（校验器算出来的，不是框架异常）：")
            lines.extend(f"- {p}" for p in items)
        else:
            lines.append("逐条问题：0 条 —— 这一份本身过了逐条校验，拒因在上面那句里。")
    lines.append(f"改法：{how}")
    lines.append(landing_sentence(land))
    meta = {"kind": "validation_error", "reason": str(exc), "problems": items,
            "how_to_fix": how, "landing": land, "tool": tool}
    return "\n".join(lines), meta


# ---------------------------------------------------------------- 审计痕迹


def record_step_refusal(agent: Any, row: Mapping[str, Any],
                        history_row: Mapping[str, Any], *,
                        exc: BaseException, deploy: Mapping[str, Any]) -> dict:
    """写回炸了之后，把这一轮「为什么被拒」单独写进 `history`。

    ## 为什么要有这一支（真机 `projects/lp-ball-13`）

    `history_row["refusal"]` 本来就挂在正常写回的那一行上，而那一笔写回正是炸掉的那一笔
    —— 于是"这一轮为什么被拒"在盘上一个字都没有，审计面只剩"盘上什么也没发生"，
    而稿其实已经落盘了。

    所以拒因要有一条不经过出问题那一段的写回：事务里重读那一行，只追加一行 history，
    别的格子一格都不动（不为了一次审计留痕去猜 rounds / 子目标状态 / 计划状态）。
    这一行仍然要过 schema（`agent._validated_plan`），非法就如实失败。

    返回 `{"recorded": bool, "why": str}`：写不进去也要如实说（工具层拿它拼拒信，
    说"审计痕迹也没写进去"），绝不静默 —— 静默失败正是这一支要修的那件事。
    """
    from .agent_f._support import _history_round  # 惰性：避免包级循环导入

    refusal: dict[str, Any] = {"kind": FRAMEWORK_ERROR_KIND,
                               "framework_error": f"{type(exc).__name__}: {exc}"}
    if deploy.get("refusal"):
        # 这一轮自己的受控拒（例如命题形态闸）另存一格：它回答"为什么这一轮没产出"，
        # 而 `kind` 记的是"为什么这一笔写回没落成" —— 两件事，不折成一档。
        refusal["round_refusal"] = dict(deploy["refusal"])
    for key in ("manuscript_path", "report_path", "manuscript_id"):
        if deploy.get(key):
            refusal[key] = str(deploy[key])
    audit: dict[str, Any] = dict(history_row)
    audit["action"] = "refused"
    audit["outcome"] = "no_change"
    audit["audit"] = REFUSAL_AUDIT_MARKER
    audit["detail"] = (
        f"这一轮的写回抛了 {type(exc).__name__}: {exc} ⇒ 正常写回没有完成；"
        "这一行是那一轮拒因的唯一落点（框架内部错误，不是产物不合格）")
    audit["refusal"] = refusal
    audit.setdefault("evidence", [])
    out: dict[str, Any] = {"recorded": False, "why": ""}
    try:
        with agent.store.tx("attack_plans", actor=agent.actor,
                            note=REFUSAL_AUDIT_MARKER) as tx:
            fresh = next((dict(r) for r in tx.rows("attack_plans")
                          if str(r.get("plan_id")) == str(row.get("plan_id"))), None)
            if fresh is None:
                out["why"] = "事务里读不到这一行计划 ⇒ 拒因没有落点"
                return out
            hist = [dict(h) for h in (fresh.get("history") or [])]
            audit["round"] = _history_round(int(fresh.get("rounds") or 0), hist)
            audit["at"] = agent._stamp()
            hist.append(audit)
            fresh["history"] = hist
            tx.upsert("attack_plans", agent._validated_plan(fresh).to_dict(),
                      note=REFUSAL_AUDIT_MARKER)
        out["recorded"] = True
    except Exception as e:  # noqa: BLE001 —— 留痕失败不许掩盖原异常，只如实记下
        out["why"] = f"{type(e).__name__}: {e}"
    return out
