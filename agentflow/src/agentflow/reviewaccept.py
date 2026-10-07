# -*- coding: utf-8 -*-
"""审稿场景的内容级验收（`draft/37` §17.3 的 ①②③④⑤，可离线跑）。

## 为什么需要它（而不是又一套"看起来完成了"）

§17.3 对第三档验收写了两半：该验的五条（定理台账每条有完整假设
与出处 / 三态分支正确且落盘可查 / 成本上限内 / 每跳提示词可读 / 附件诚实），以及
明确不许拿来当"通过"的读数：`sha 变了`、`页数对得上`、`锚 consistent` 单项、
`任务数增加`、`台账行数增加`。

这两半必须一起实现，否则"验收"会退化成后者：那些信号很容易拿到（跑一次就变），
而它们证明不了内容。所以本模块的输出把两者分栏：

- `criteria`：五条内容级判据，各自一个三态值（`pass`/`fail`/`unknown`）；
- `auxiliary`：那五种"容易拿到的读数"的当前值 —— 它们只作辅助，
  一个都不参与 `passed` 的计算（这一条有专门的反真空判据：
  把五条辅助信号全部造得"漂亮"而内容不合格 ⇒ `passed` 必须仍为假）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: 五条内容级判据（顺序即交付说明里的顺序）。
#:
#: R9（`draft/52` 裁决 1 = C''）：原先的第六条 `report_sections_have_readings`
#: （"报告九节齐全且每节都有读数"）已废除 —— 那是 review 线的排版规格，
#: 被当成通用判据用。报告体例由 M 裁定，核对只核对"M 声明的体例有没有兑现"
#: （落在 `closing._check_report_shape` 的 `REPORT-STYLE.json` 那一支）。
#: 附件三件套（来源 / 依据 / 版本 sha）保留判实，由 `attachment_is_honest` 这一条承担。
CRITERIA: tuple[tuple[str, str], ...] = (
    ("statements_have_assumptions_and_source", "定理台账每条都有完整假设与出处（含页码）"),
    ("triage_branch_recorded", "三态分支正确：该问用户的真问了，且问题落盘可查"),
    ("within_cost_cap", "在成本上限内完成"),
    ("hops_have_readable_prompts", "每一跳都留下了可读的输入（`input_key`+台账引用不悬空）"),
    ("attachment_is_honest", "附件诚实：**明确标注是我们补的** + 依据读数 + 版本 sha；"
                             "没过 T3 的不许写成「已解决」（R25 的两条负控）"),
)

#: R25 负控①要挡的形态：把"我们补的"写成"文献里的"（来源造假）。
FORGERY_MARKERS: tuple[str, ...] = (
    "文献补充", "原文的补充", "摘自文献", "文献原文补充", "文献补遗",
)

#: R25 负控②要挡的形态：把没上 T3 的东西写成"已解决"。
RESOLVED_MARKERS: tuple[str, ...] = ("已解决", "已修复", "已闭合", "resolved")

#: §17.3 逐字列出的"不许当通过"的辅助读数。
AUXILIARY_SIGNALS: tuple[tuple[str, str], ...] = (
    ("tex_sha256", "主稿 sha 变了（跑一次就会变）"),
    ("pdf_pages", "页数对得上"),
    ("anchor_verdict", "渲染锚 consistent（**单项**不算通过）"),
    ("task_rows", "任务数增加"),
    ("ledger_rows", "台账行数增加"),
)

#: R9（`draft/52` 裁决 1 = C''）之后，本模块不再判报告形状：
#: 旧的两条实现（节标题正则、"九节齐全且每节有读数"那条判据，以及只被后者用到的
#: "什么算读数"正则）随 R9 一起删掉了 —— 名字刻意不再写在这里：它们已经不存在，
#: 把删掉的符号名当引用写进注释，读的人按图索骥只会扑空（引用判据 `R5-AN-10` 的口径）。
#: 报告体例归 M，核对只核对"M 声明的体例有没有兑现" —— 那一支在
#: `closing._check_report_shape`（读 `REPORT-STYLE.json`）。


@dataclass
class ReviewAcceptance:
    """一次审稿的内容级验收读数（辅助读数分栏放着，不参与 `passed`）。"""

    criteria: dict[str, str] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)
    auxiliary: dict[str, Any] = field(default_factory=dict)
    readings: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> list[str]:
        """内容级判据里没通过的那些（`unknown` 也算没通过，见 `passed`）。"""
        return sorted(k for k, v in self.criteria.items() if v != "pass")

    @property
    def passed(self) -> bool:
        """五条内容级判据全 `pass` 才为真 —— 辅助读数一个都不参与。"""
        return all(v == "pass" for v in self.criteria.values())

    def to_dict(self) -> dict[str, Any]:
        """整份验收读数（判据与辅助读数分栏给出，下游不必自己分）。"""
        return {
            "passed": self.passed,
            "criteria": dict(self.criteria),
            "details": dict(self.details),
            "failed": self.failed,
            "auxiliary": dict(self.auxiliary),
            "readings": dict(self.readings),
            "auxiliary_note": "辅助读数只供人看：它们都很容易变，证明不了内容（§17.3 逐字禁止）",
        }

    def summary(self) -> str:
        """一句话读数（交付说明用；未通过时明说辅助读数不构成通过）。"""
        if self.passed:
            return "审稿验收：五条内容级判据全过"
        return (f"审稿验收：未通过（{self.failed or '无'}）—— "
                "注意：sha/页数/锚/行数这些辅助读数**不构成通过**")


# ------------------------------------------------------------------ 各条判据

def _c_statements(acc: ReviewAcceptance, store: Any) -> None:
    """② 定理台账每条都有完整假设与出处 —— 而"出处"按来源分档（§68 人裁的甲档）。

    只查 `active` 的那些：`disputed`/`refuted`/`superseded` 本来就不许当依据，
    对它们提"必须有假设与出处"是把处置方向搞反（§17.3 问的是交付里的定理）。

    ## 两种来源要的"出处"不是同一件东西

    - `external_lit`（从文献里摘的）：`source_lit_id` 必须有，且 `page_range`
      的 `start` 或 `label` 至少一个非空 —— 缺页码的摘录无法复核；
    - `own_result`（我们自己得的）：出处是「我们自己的产物」，要的是
      `doc_id` 或 `line_range`（`line_range` 的 `start`/`label` 至少一个非空）；
      对它提 `page_range` 是把"文献第几页"套到"我们自己证的"上来。

    为什么必须与写入口说同一件事：判据要求而写入口放行的字段，会在台账里
    长期躺着"看着有、其实没有"的行（第十三趟那六条空 `page_range` 就是这么进去的）。
    `agent_b/register_statement.py` 的预检与这里逐条对齐（§68）。
    """
    if store is None:
        acc.criteria["statements_have_assumptions_and_source"] = "unknown"
        acc.details["statements_have_assumptions_and_source"] = "没有 store ⇒ 没查成"
        return
    rows = [r for r in store.rows("statements") if str(r.get("status") or "") == "active"]
    bad: list[str] = []
    for r in rows:
        sid = str(r.get("stmt_id"))
        origin = str(r.get("origin") or "")
        if not str(r.get("statement_full") or "").strip():
            bad.append(f"{sid} 缺 statement_full（完整假设）")
        page = r.get("page_range") or {}
        line = r.get("line_range") or {}
        if origin == "own_result":
            if not (str(r.get("doc_id") or "").strip()
                    or line.get("start") or str(line.get("label") or "").strip()):
                bad.append(f"{sid} 缺 own_result 的出处（doc_id 或 line_range）")
        elif origin == "external_lit":
            if not str(r.get("source_lit_id") or "").strip():
                bad.append(f"{sid} 缺 source_lit_id（出处）")
            if not (page.get("start") or str(page.get("label") or "").strip()):
                bad.append(f"{sid} 缺 page_range（页码）")
        else:
            # 词表外的来源：这一行的"出处该是哪一栏"没有定义 ⇒ 按缺字段记（fail），
            # 而不是拿 external_lit 的规则蒙一个结论。
            bad.append(f"{sid} 的 origin={origin!r} 不在 STATEMENT_ORIGINS 里 ⇒ "
                       "说不出它的出处该填哪一栏")
    acc.readings["active_statements"] = len(rows)
    acc.readings["statements_missing_fields"] = bad
    if not rows:
        # 台账是空的：这不是"都合规"，而是"没有内容可审" ⇒ fail（不是 unknown：
        # 没东西可审这件事本身是查清楚了的）。
        acc.criteria["statements_have_assumptions_and_source"] = "fail"
        acc.details["statements_have_assumptions_and_source"] = (
            "定理台账里一条 active 命题都没有 ⇒ 这次审阅没有交出内容"
            "（空台账不是合规，是没做）")
    elif bad:
        acc.criteria["statements_have_assumptions_and_source"] = "fail"
        acc.details["statements_have_assumptions_and_source"] = "；".join(bad[:6])
    else:
        acc.criteria["statements_have_assumptions_and_source"] = "pass"


def _c_triage(acc: ReviewAcceptance, store: Any, session_root: Any,
              *, sid: str | None = None) -> None:
    """③ 三态分支正确：该问用户的真问了，且问题落盘可查。

    判据取的是"问过的问题有没有落盘 + 有没有被回答"这两个读数，
    以及"没回答时门必须拦住"（`closing` 的 `user_pending`）。
    这一条不判"该不该问"（那是语义判断，属 P2 的提示词面）。

    `sid` 必须跟着运行走（见 `check_review` 的说明）：不带它时按默认会话读，
    而真机跑的每一趟都有自己的 sid ⇒ 提问会被读成"没问过"。
    `sid=closing.NO_SESSION`（调用方没有会话身份）⇒ 这一格 `unknown`：
    与 `closing.user_pending` 同一套三态，理由见那边的 `NO_SESSION`。

    ## 无人值守的那一趟（`draft/37` §66 的三档，当前采用乙）

    一次没人值守的运行里，"问了而用户没答"这一格注定是 `fail`。这不是判据的缺陷，
    而是"必须停在等待用户"这条纪律的读数。三档登记（供人改口径）：

    - 甲：把"正确地停下来等"判成 `pass`（要能区分"停在等"与"做完了"，
      今天的数据面上判不了：交付说明里没有"我停在等什么"这一栏的机械位置）；
    - 乙（「当前」）：保持 `fail` —— 它准确定位了"这一趟不能交付"；
      口径写进 PAPER_PACK（"无人值守那一趟拿不到这一格，答完再 `--resume`"）
      与本节，并由 `tests/test_paper_pack.py` 的内容判据钉住；
    - 丙：给这一格加第四态（"停在等用户"），要动 `CRITERIA` 的三态口径
      （`pass/fail/unknown` 是全项目共用的读数口径）。

    甲/丙都要改口径本身，所以留给人裁；乙这一档今天是「有判据」的。
    """
    if session_root is None:
        acc.criteria["triage_branch_recorded"] = "unknown"
        acc.details["triage_branch_recorded"] = "没有会话记录根 ⇒ 没查成"
        return
    from .closing import NO_SESSION

    if sid == NO_SESSION:
        acc.criteria["triage_branch_recorded"] = "unknown"
        acc.details["triage_branch_recorded"] = (
            "这次审阅没有会话身份（装配期没注入 sid）⇒ 「该问的问了」这条**没查成**"
            "（按缺省会话读会把别的会话的提问算进来，或把本会话的提问读丢）")
        return
    from . import userio as U

    pending = U.pending_questions(session_root, sid=sid)
    replies = U.read_replies(session_root, sid=sid)
    acc.readings["questions"] = {"asked": len(pending) + len(replies),
                                "answered": len(replies),
                                "pending": [q.qid for q in pending]}
    if pending:
        acc.criteria["triage_branch_recorded"] = "fail"
        acc.details["triage_branch_recorded"] = (
            f"还有 {len(pending)} 个问题没被回答（{', '.join(q.qid for q in pending[:4])}）"
            "⇒ 正确的分支是**停在「等待用户」**，不是继续往下做")
    elif not replies:
        acc.criteria["triage_branch_recorded"] = "unknown"
        acc.details["triage_branch_recorded"] = (
            "这一次一次都没问过用户 ⇒ 「该问的问了」这条**没查成**"
            "（不是通过：没有提问记录与'问得对'不是同一件事）")
    else:
        acc.criteria["triage_branch_recorded"] = "pass"


def _session_spend_usd(session_root: Any, sid: str | None) -> tuple[float | None, int, int]:
    """会话事件里这一趟的花销：返回 `(合计 usd, 算不出价钱的调用数, llm_call 条数)`。

    `None` 的合计 = 「没查成」（没有会话根 / 没有 sid / 读不出来），不是"花了零"。

    ## 为什么本判据需要第二个数源（`draft/37` §64 的真机读数）

    `within_cost_cap` 原先只读 `usage_ledger`。而 `run-agent` 这条路
    「一次调用都没往账本里记过」：第 11 趟会话里 30 次调用合计 0.289069 美元，
    账本 9 行全是 0.000000 —— 于是这一格报"没超上限"，而真花销是上限的三倍
    （cap=0.10 时实测 `pass`）。钱一直都在会话事件的 `llm_call.usd` 里，
    所以判据必须两头都看：账本说多少、这一趟实际花了多少。
    """
    if session_root is None or sid is None:
        return None, 0, 0
    from . import sessions as SS

    events, _problems = SS.read_session(session_root, sid=sid)
    calls = [e for e in events if str(e.get("kind") or "") == "llm_call"]
    total = 0.0
    unknown = 0
    for e in calls:
        usd = e.get("usd")
        if usd is None:
            unknown += 1
        else:
            total += float(usd or 0.0)
    return round(total, 6), unknown, len(calls)


def _c_cost(acc: ReviewAcceptance, store: Any, cap_usd: float | None, *,
            session_root: Any = None, sid: str | None = None) -> None:
    """④ 成本上限：账本合计与会话事件两头看，取「看得见的最大花销」判上限。

 这一条此前有一个盲区（写在读数里，不是藏起来）：
    `tokenmeter._row_for` 永远写 `round(c.usd_total, 6)`（一个 float），
    而"这次调用算不出花销"这件事记在 spend 的 `unknown_usd_calls` 里、
    不进账本行 ⇒ 一次算不出价钱的调用在账本上看起来就是零元。
    所以本判据只能说"账本上的合计没超上限"，说不出"这一轮没有漏记的花销"。
    补法：把 `unknown_usd_calls` 也落进账本（或给它一列），或者让 `usage_ledger`
    允许 `usd=None` 这一档 —— 两者都要动 `schema.py`/`tokenmeter.py`，留给人裁。

  §64 的处置（人已授权这一轮动禁改区，但「没有」动 `schema.py`，理由如下）：
    真正被撞破的不是"算不出价钱"这一档，而是「账本整条路没记账」
    （`LlmSeam` 根本没有 meter ⇒ 30 次调用 0 行）。修法是把缝接上账本
    （`llmseam.LlmSeam.meter`），于是账本对新运行不再说谎；
    而为了让"任何一条忘了记账的路"都能被抓住，这里加上第三个读数：
    会话事件里的花销。三条口径：
      ① 上限判据用 `max(账本, 会话)` —— 保守，绝不按小的那个放行；
      ② 会话里花得比账本多 ⇒ 「fail」（"账本没跟上这一趟"，处置是修记账，不是改上限）；
      ③ 会话里有算不出价钱的调用 ⇒ 「unknown」（说不清花了多少，不是通过）。
    为什么不给 `usage_ledger.usd` 加 `None` 档：今天每一个读者都写着
    `float(r.get("usd") or 0.0)` —— 加一个 `None` 只会多出一条「新的」静默零路径，
    而不是消掉旧的。所以"算不出来"留在 `note` 里（写入方如实写），
    由这条判据判成 `unknown`。这一条要动 `schema.py`（FC-27），本轮不动。
    """
    if store is None:
        acc.criteria["within_cost_cap"] = "unknown"
        acc.details["within_cost_cap"] = "没有 store ⇒ 没查成"
        return
    rows = store.rows("usage_ledger")
    total = sum(float(r.get("usd") or 0.0) for r in rows)
    seen, unpriced, calls = _session_spend_usd(session_root, sid)
    acc.readings["cost"] = {"rows": len(rows), "usd": round(total, 6), "cap_usd": cap_usd,
                            "session_usd": seen, "session_calls": calls,
                            "unpriced_calls": unpriced,
                            "blind_spot": "账本行永远是 float（`usd_total`）⇒ "
                                          "「这次调用算不出花销」在账本上看不见"
                                          "（它在 spend 的 unknown_usd_calls 里）"}
    if cap_usd is None:
        acc.criteria["within_cost_cap"] = "unknown"
        acc.details["within_cost_cap"] = "没给成本上限 ⇒ 这一条没查成（不是通过）"
        return
    spent = max(total, float(seen or 0.0))
    if spent > float(cap_usd):
        acc.criteria["within_cost_cap"] = "fail"
        acc.details["within_cost_cap"] = (
            f"花了 {spent:.6f} > 上限 {float(cap_usd):.6f}"
            f"（账本 {total:.6f} / 会话事件 {seen if seen is not None else '没查成'}）")
    elif unpriced:
        acc.criteria["within_cost_cap"] = "unknown"
        acc.details["within_cost_cap"] = (
            f"会话里有 {unpriced} 次调用算不出价钱（价格表不可用）⇒ "
            f"「花了多少」说不清，这一格不是通过（账本合计 {total:.6f}）")
    elif seen is not None and float(seen) > total + 1e-9:
        acc.criteria["within_cost_cap"] = "fail"
        acc.details["within_cost_cap"] = (
            f"账本没跟上这一趟：账本合计 {total:.6f} < 会话事件里的花销 {float(seen):.6f}"
            f"（{calls} 次调用）⇒ 有调用没记账。处置是修记账那条路"
            "（`llmseam.LlmSeam.meter` / 调用点的 meter 接线），不是改成本上限")
    else:
        acc.criteria["within_cost_cap"] = "pass"


def _hop_rows(store: Any) -> tuple[list[Any], int]:
    """这一趟的委托（召唤）行；返回 `(召唤行, 被排除的顶趟行数)`。

    ## 为什么必须排除顶趟行（A 线 F1 的"往前走半"之后，主控 2026-10-06 裁定）

    现在每一趟顶层运行会在 `tasks` 里留一条顶趟行（`role=M`、`action="run"`、
    `called_by="user"`、`depth=1`、`input_key="top:…"`）。它是用户发起的那一趟，
    不是一次召唤 —— 而这一格（`hops_have_readable_prompts`）数的是委托：
    把用户自己发起的那一趟算进去，"派了几跳 / 成了几跳"会凭空 +1。

    口径取 `called_by != "user"`（而不是 `action != "run"`）：判据问的是
    "这一行是不是被召唤出来的"，`called_by` 就是那个字段（`action` 只是
    顶趟行当前的取值，将来换名字也不会让这条判据失效）。缺 `called_by` 的历史行
    按"不是用户发起"处理（老台账里没有这个字段，行数不该因此变化）。

    排除本身必须可见：返回值第二个分量是行数，读数里如实报出来 ——
    静默滤掉与"本来就只有这么多"在读的人眼里是同一件事，而那正是本项目最忌的形态。
    """
    if store is None:
        return [], 0
    done = [r for r in store.rows("tasks")
            if str(r.get("status") or "") == "done"
            and str(r.get("outcome") or "") == "ok"]
    hops = [r for r in done if str(r.get("called_by") or "") != "user"]
    return hops, len(done) - len(hops)


def _c_hops(acc: ReviewAcceptance, store: Any) -> None:
    """⑤ 每一跳都留下了可读的输入（`input_key` 非空 + 台账引用不悬空）。

 这一条查的是台账那一半：提示词的正文在会话记录的 `llm_call` 事件里
    （`prompt_sha256` / `prompt_chars`），本函数不读它 —— 两个读数各自都有落点，
    合起来才是"每跳提示词可读"（§15.3）。把边界写出来，免得读的人以为已经全查了。
    """
    if store is None:
        acc.criteria["hops_have_readable_prompts"] = "unknown"
        acc.details["hops_have_readable_prompts"] = "没有 store ⇒ 没查成"
        return
    rows, top_run_rows = _hop_rows(store)
    missing = [str(r.get("task_id")) for r in rows if not str(r.get("input_key") or "").strip()]
    acc.readings["hops"] = {
        "ok_tasks": len(rows),
        # 排除本身可见：这一趟有几行是"用户发起的那一趟"（不算召唤）
        "excluded_top_run_rows": top_run_rows,
        "without_input_key": missing,
        "note": "提示词正文在会话记录的 llm_call 事件里"
                "（prompt_sha256/prompt_chars），本判据只看台账那一半；"
                "`excluded_top_run_rows` 是本次**排除掉的顶趟行**（`called_by=\"user\"`）："
                "那一条是用户发起的那一趟，不是一次召唤",
    }
    if not rows:
        acc.criteria["hops_have_readable_prompts"] = "fail"
        acc.details["hops_have_readable_prompts"] = "台账里没有任何成功的召唤 ⇒ 这次审阅没跑起来"
    elif missing:
        acc.criteria["hops_have_readable_prompts"] = "fail"
        acc.details["hops_have_readable_prompts"] = (
            f"这些成功的召唤没有 input_key（{missing[:5]}）⇒ 说不清'派下去的是什么'")
    else:
        acc.criteria["hops_have_readable_prompts"] = "pass"


def _dangling_report_refs(text: str, store: Any) -> tuple[list[str], str]:
    """报告里点名的台账行是否真的存在；返回 `(不存在的那些, 没查成的原因)`（`draft/37` §70）。

    ## 为什么要这一条

    第十四趟真机：`reviewaccept` 六条「全过」、`closing.can_close=True`，
    而交付说明里写着"4 条登记进 `statements`（0000/0001/0002/0003）"、
    表格里逐行给 `statements 0001 / 0002 / 0003` —— 「台账里只有 0000 一条」。
    那三行是模型在两次被拒之后（第一次 `page_range` 传成了字符串）自己"补"出来的：
    它把打算做的事写成了已经做完的事，而「没有任何判据看这件事」
    （旧的九节判据只问"每节有没有读数"，不问"读数是不是真的" —— 那条判据
    已按 R9 废除，它的实现也随之删掉，名字不再写在这里：见本模块顶部那段注释）。

    判据的形状刻意保守：只认「带前缀的 4 位号」（`statements 0001` / `statements:0001` /
    `lit:0000` / `documents 0000` / `doc:0000`），不认裸的 4 位数
    （报告里有大量页码、行号、年份，裸数字会把判据变成噪音）。

    ## 为什么返回一个"没查成的原因"而不是空表

    没有 store 时返回空表，会把「没查」折成「都查到了」—— lint R002 点的就是这个形态，
    它在本文件上真的红了一次（`if store is None: return []`）。三态纪律：
    查过了没问题 / 查过了有问题 / 没查成，三者必须分得开。

    为什么它属于"附件诚实"这条：引用一个不存在的行，与"把别人的东西写成我们的"
    是同一类错 —— 都是「说的与盘上的不是一回事」，处置方向也一样（去把事做了）。
    """
    import re

    if store is None:
        return [], "没有 store ⇒ 报告里的台账引用没查成（不是「都查到了」）"
    kinds = (("statements", "stmt_id", r"\bstatements?[:：]?\s*(\d{4})"),
             ("literature", "lit_id", r"\b(?:lit|literature)[:：]?\s*(\d{4})"),
             ("documents", "doc_id", r"\b(?:doc|documents?)[:：]?\s*(\d{4})"))
    dangling: list[str] = []
    for table, id_field, pattern in kinds:
        wanted = {m for m in re.findall(pattern, text, flags=re.IGNORECASE)}
        have = {str(r.get(id_field) or "") for r in store.rows(table)}
        for rid in sorted(wanted - have):
            dangling.append(f"{table} {rid}")
    return dangling, ""


def _c_attachment(acc: ReviewAcceptance, store: Any, report_path: str) -> None:
    """⑥ 附件诚实（R25）：三份都要过 —— 来源不造假、不过度声称、引用的台账行真的存在。

    三条负控（`draft/37` §16 P3 的报告行逐字要求 + §70 的真机读数）：

    1. 来源造假：把"我们补的手稿"写成文献里的东西（`FORGERY_MARKERS`）。
       处置方向是改正来源标注，不是补证据 —— 所以它与下面那条必须分开报；
    2. 没过 T3 写"已解决"：报告里出现 `RESOLVED_MARKERS`，而收工门的
       `load_bearing` 仍然判定"承重结论缺 T3"（同一个工作区里跑一次 `closing` 就知道）。
       处置方向是降档或补 T3；
    3. 「引用的台账行不存在」（`draft/37` §70 的第十四趟真机读数）：报告里逐条写着
       `statements 0001/0002/0003`，而台账里只有 `0000` —— 六条判据全绿、
       `closing.can_close=True`，交付说明却在引用不存在的行。
       处置方向是「去把它真的登记上」（或把没做成的写成没做成），不是改判据。

    附件三件套（`origin=own_result` + 依据读数 + 版本 sha）由 `report_shape` 那条管；
    这一条只管诚实：说的是不是实话。

    ## 报告路径必须按工作区根解析（`draft/37` §69 的真机读数）

    这一格此前用 `Path(report_path).is_file()` 直接判 —— 而模型给的报告路径是
    「相对工作区」的（`out/review/REPORT.md`，见 PAPER_PACK 的第九节口径），
    于是它在真机上判成"报告不在盘上 ⇒ 没查成"：第十三趟的 8,790 字节报告就在盘上，
    而这一格是 `unknown`（`unknown` 会挡住 `passed`）。
    §60 修 `closing` 的锚/报告形状与 `reviewaccept` 的报告节数/辅助读数时「漏了这一处」，
    而当时的判据（`test_relative_paths_under_workspace`）只断言了报告节数与 tex sha ——
    判据没看的那一格，正是漏掉的那一格。现在与另外三处共用同一个解析口。
    """
    from .closing import resolve_under_workspace

    report_path = resolve_under_workspace(store, report_path)
    if not str(report_path or "").strip() or not Path(report_path).is_file():
        acc.criteria["attachment_is_honest"] = "unknown"
        acc.details["attachment_is_honest"] = "报告不在盘上 ⇒ 附件的诚实没查成（不是通过）"
        return
    text = Path(report_path).read_text(encoding="utf-8")
    forged = [m for m in FORGERY_MARKERS if m in text]
    overclaim = [m for m in RESOLVED_MARKERS if m in text]
    dangling, refs_why = _dangling_report_refs(text, store)
    acc.readings["attachment"] = {"forgery_markers": forged, "resolved_markers": overclaim,
                                  "dangling_refs": dangling,
                                  "refs_check": refs_why or "checked"}
    problems: list[str] = []
    if forged:
        problems.append(f"来源造假：报告里出现 {forged} —— 我们补的东西不许写成文献里的")
    if dangling:
        problems.append(
            "引用的台账行不存在：" + "、".join(dangling[:6])
            + " —— 报告点了盘上没有的行（真机实测：说登记了 4 条 statements、台账里只有 1 条）")
    if overclaim:
        # "已解决"本身不违规 —— 只有当收工门仍在说"承重结论缺 T3"时它才是过度声称。
        # 这正是"两条判据互相咬"的形态：措辞的诚实由证据状态裁定，不由措辞自己裁定。
        if store is not None:
            from . import closing as CL

            gate = CL.check_closing(store, checks=("load_bearing",))
            still_bad = gate.status.get("load_bearing") == "fail"
            acc.readings["attachment"]["load_bearing"] = gate.status.get("load_bearing")
            if still_bad:
                problems.append(
                    f"过度声称：报告写了 {overclaim}，而收工门的承重判据仍是 fail"
                    "（有 proof 级的结论没有 T3 背书）⇒ 要么降档并改措辞，要么补 T3")
    if problems:
        acc.criteria["attachment_is_honest"] = "fail"
        acc.details["attachment_is_honest"] = "；".join(problems)
    elif refs_why:
        # 查过了没问题的那些已经过了，但"引用悬空"这一格没查成 ⇒ 这一条记 unknown
        # （不是 pass）：三态纪律，没查成不许折成通过。
        acc.criteria["attachment_is_honest"] = "unknown"
        acc.details["attachment_is_honest"] = refs_why
    else:
        acc.criteria["attachment_is_honest"] = "pass"


def _auxiliary(acc: ReviewAcceptance, store: Any, project_dir: str) -> None:
    """那五种"容易拿到、但证明不了内容"的读数（§17.3 逐字禁止拿来当通过）。

    相对路径按工作区根解析（与 `closing` 共用一份实现）：否则"相对工作区"
    这个契约在两次判据里会有两个口径，而错的读数看起来像"文件不在"（`draft/37` §60）。
    """
    import hashlib

    from . import renderanchor as RA
    from .closing import resolve_under_workspace

    project_dir = resolve_under_workspace(store, project_dir)

    aux: dict[str, Any] = {}
    tex = Path(project_dir) / "out" / "paper" / "main.tex" if project_dir else None
    aux["tex_sha256"] = (hashlib.sha256(tex.read_bytes()).hexdigest()[:12]
                         if tex is not None and tex.is_file() else "")
    pdf = Path(project_dir) / "out" / "paper" / "main.pdf" if project_dir else None
    aux["pdf_pages"] = None
    if pdf is not None and pdf.is_file():
        try:  # 页数只作辅助：读不出来就 None，不许编一个数
            from .extract import page_count as _page_count
            aux["pdf_pages"] = _page_count(pdf)
        except Exception:  # noqa: BLE001 —— 辅助读数读不到就算了，它不参与判定
            aux["pdf_pages"] = None
    aux["anchor_verdict"] = (RA.check_package(project_dir, store=store).get("verdict")
                             if project_dir else "")
    aux["task_rows"] = len(store.rows("tasks")) if store is not None else 0
    aux["ledger_rows"] = (len(store.rows("literature")) + len(store.rows("concepts"))
                          + len(store.rows("relations"))) if store is not None else 0
    acc.auxiliary = aux


def check_review(store: Any, *, project_dir: str = "", report_path: str = "",
                 session_root: Any = None, cost_cap_usd: float | None = None,
                 sid: str | None = None,
                 ) -> ReviewAcceptance:
    """跑一次审稿场景的内容级验收（辅助读数不参与 `passed`）。

    `session_root` 不给时取 `store.root`。任何一格缺少必要输入 ⇒ `unknown`
    （"没查成"），而 `unknown` 不是通过。

    `sid` 必须给这一趟运行的那个 sid（`draft/37` §58 的真机读数）：
    第九趟的提问落在 `sessions/real9.jsonl` 里，而本函数此前不带 `sid` ⇒
    `pending_questions(root)` 按默认会话读，什么都没读到，于是
    `triage_branch_recorded` 报"一次都没问过用户" —— 而那一趟明明问了（`q0001`）。
    判据看不见带 sid 的提问，这一格就永远只能是 unknown，而病因在调用姿势上，
    不在主控身上。
    """
    acc = ReviewAcceptance()
    root = session_root if session_root is not None else getattr(store, "root", None)
    _c_statements(acc, store)
    _c_triage(acc, store, root, sid=sid)
    _c_cost(acc, store, cost_cap_usd, session_root=root, sid=sid)
    _c_hops(acc, store)
    _c_attachment(acc, store, report_path)
    _auxiliary(acc, store, project_dir)
    return acc
