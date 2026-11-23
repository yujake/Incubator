# -*- coding: utf-8 -*-
"""审稿场景的内容级验收（五条，可离线跑）。

## 为什么需要它（而不是又一套"看起来完成了"）

第三档验收写了两半：该验的五条（定理台账每条有完整假设
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
from typing import Any, Mapping

#: 五条内容级判据（顺序即交付说明里的顺序）。
#:
#: 报告九节那种"排版规格"不在本表：那是 review 线的体例，由 M 裁定，
#: 核对只核对"M 声明的体例有没有兑现"（落在 `closing._check_report_shape`
#: 的 `REPORT-STYLE.json` 那一支）。附件三件套（来源 / 依据 / 版本 sha）
#: 保留判实，由 `attachment_is_honest` 这一条承担。
CRITERIA: tuple[tuple[str, str], ...] = (
    ("statements_have_assumptions_and_source",
     "定理台账每条都有完整假设与出处（引外部文献的要页码）"),
    ("triage_branch_recorded", "三态分支正确：该问用户的真问了，且问题落盘可查"),
    ("within_cost_cap", "在成本上限内完成"),
    ("hops_have_readable_prompts", "每一跳都留下了可读的输入（`input_key`+台账引用不悬空）"),
    ("attachment_is_honest", "附件诚实：明确标注是我们补的 + 依据读数 + 版本 sha；"
                             "没过 T3 的不许写成「已解决」（R25 的两条负控）"),
)

#: 负控①要挡的形态：把"我们补的"写成"文献里的"（来源造假）。
FORGERY_MARKERS: tuple[str, ...] = (
    "文献补充", "原文的补充", "摘自文献", "文献原文补充", "文献补遗",
)

#: 负控②要挡的形态：把没上 T3 的东西写成"已解决"。
RESOLVED_MARKERS: tuple[str, ...] = ("已解决", "已修复", "已闭合", "resolved")

#: 逐字列出的"不许当通过"的辅助读数。
AUXILIARY_SIGNALS: tuple[tuple[str, str], ...] = (
    ("tex_sha256", "主稿 sha 变了（跑一次就会变）"),
    ("pdf_pages", "页数对得上"),
    ("receipt_matches_tex", "这份 PDF 是从盘上这份 tex 编的（单项不算通过）"),
    ("task_rows", "任务数增加"),
    # 键名曾是 `ledger_rows`，与 usage_ledger 的行数同名不同物：这里数的是概念图
    # 三张表（`literature` + 概念行 + `relations`）的行数，见 `_auxiliary`。
    # 刻意不取 `acceptance_rows`：`closing` 里已有 `acceptance_rows_unreadable` /
    # `acceptance_rows_unknown` 两个码，指的是「验收表的行」，取那个名会造出新的
    # 一名两义。
    ("concept_graph_rows", "台账行数增加（文献 + 概念 + 关系）"),
)

#: 本模块不判报告形状：报告体例归 M，核对只核对"M 声明的体例有没有兑现" ——
#: 那一支在 `closing._check_report_shape`（读 `REPORT-STYLE.json`）。


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
                "注意：sha/页数/锚/行数这些辅助读数不构成通过")


# ------------------------------------------------------------------ 各条判据

def _range_has_start_or_label(value: Any) -> bool:
    """`page_range` / `line_range` 的"填了内容"判据：`start` 或 `label` 至少一个非空。

    两个字段用同一把尺：`external_lit` 的 `page_range` 与 `own_result` 的
    `line_range` 是同一件事（出处落在哪儿）的两个落点。不是 Mapping 的旧行
    （历史上出现过字符串形态）按"没有可用区间"读 —— 与原来那两句判据等价，
    只是不再因为形态不对而在读侧抛异常。
    """
    if not isinstance(value, Mapping):
        return False
    return bool(value.get("start") or str(value.get("label") or "").strip())


def statement_source_problem(row: Mapping[str, Any]) -> str:
    """一条 `active` 命题的「出处」那一栏该怎么填 ⇒ 空串 = 合格，否则一句可读的缺项。

    ## 按来源分档

    - `own_result`（我们自己得的）：出处是「我们自己的产物」⇒ 要 `doc_id` 或
      `line_range`；对它提 `page_range` 是把"文献第几页"套到"我们自己证的"上来；
    - `external_lit`（从文献里摘的）：要 `source_lit_id`，还要 `page_range`
      （`start` 或 `label` 至少一个非空）—— 缺页码的摘录无法复核；
      概念行（`kind="concept"`）也在这条线上，不豁免（理由见下一节）；
    - 词表外的 `origin`：说不出它的出处该填哪一栏 ⇒ 记缺字段（不拿 `external_lit`
      的规则蒙一个结论）。

    ## 概念行为什么不豁免

    概念行（`kind="concept"`）同样要页码：按"定义型行给不出页码"判过豁免，
    随后被真机数据否掉 —— B 自己用 `own.register_statement(kind="concept", page_range=...)`
    写过概念行，页码取自同一概念 `relations` 行的逐字引文页（`quote_reason` 里写着
    "该定义的逐字原文引文挂在 relations 行"）。既然写入面有这一格、页码又拿得到，
    缺页码就不是"结构上做不到"，而是写侧没写（摘要路径 `conceptrows.concept_statement`
    没有这个参数，`schema.Concept` 也没有这一格）。判据不因为写侧的缺口放宽：
    放宽会把"概念行没有出处页码"变成静默通过。

    所以本函数对 `external_lit` 一律要页码（概念行也一样）；缺的那些进
    `readings["page_range_missing_by_kind"]`（按 `kind` 分栏，给写侧一份收尾清单）。
    """
    sid = str(row.get("stmt_id") or "")
    if not str(row.get("statement_full") or "").strip():
        return f"{sid} 缺 statement_full（完整假设）"
    origin = str(row.get("origin") or "")
    if origin == "own_result":
        if not (str(row.get("doc_id") or "").strip()
                or _range_has_start_or_label(row.get("line_range"))):
            return f"{sid} 缺 own_result 的出处（doc_id 或 line_range）"
        return ""
    if origin == "external_lit":
        if not str(row.get("source_lit_id") or "").strip():
            return f"{sid} 缺 source_lit_id（出处）"
        if not _range_has_start_or_label(row.get("page_range")):
            return f"{sid} 缺 page_range（页码）"
        return ""
    return (f"{sid} 的 origin={origin!r} 不在 STATEMENT_ORIGINS 里 ⇒ "
            "说不出它的出处该填哪一栏")


def _c_statements(acc: ReviewAcceptance, store: Any) -> None:
    """② 定理台账每条都有完整假设与出处 —— 而"出处"按来源与 `kind` 分档。

    只查 `active` 的那些：`disputed`/`refuted`/`superseded` 本来就不许当依据，
    对它们提"必须有假设与出处"是把处置方向搞反（问的是交付里的定理）。

    ## 哪一栏必填，口径只有一处

    `statement_source_problem`（本模块的纯函数）说"这一行缺什么"：`own_result`
    要 `doc_id`/`line_range`；`external_lit` 要 `source_lit_id` 与 `page_range`
    （概念行也一样，理由见那个函数的 docstring）。

    ## 单独计数的一格（不是静默豁免）

    自有结果缺页码进 `readings["page_range_not_required"]`：它的出处是
    `doc_id`/`line_range`，"文献第几页"不是它该填的那一栏。它不参与
    `statements_missing_fields`（那份清单是"真的缺了"），但"有多少条没有页码"
    仍然要是个读得出来的数 —— 把豁免做成静默的是本项目最忌的形态。

    缺页码的外部行另给一份 `readings["page_range_missing_by_kind"]`（按 `kind`
    分栏）：判据的裁决不变（它们在 `statements_missing_fields` 里），这一栏只是
    让"缺的是哪一类行"在读数上直接可见。

    为什么必须与写入口说同一件事：判据要求而写入口放行的字段，会在台账里
    长期躺着"看着有、其实没有"的行（空 `page_range` 就是这么进去的）。
    `agent_b/register_statement.py` 的预检与这里逐条对齐。
    """
    if store is None:
        acc.criteria["statements_have_assumptions_and_source"] = "unknown"
        acc.details["statements_have_assumptions_and_source"] = "没有 store ⇒ 没查成"
        return
    rows = [r for r in store.rows("statements") if str(r.get("status") or "") == "active"]
    bad: list[str] = []
    own_no_page: list[str] = []
    page_less_by_kind: dict[str, list[str]] = {}
    for r in rows:
        sid = str(r.get("stmt_id") or "")
        problem = statement_source_problem(r)
        if problem:
            bad.append(problem)
        if _range_has_start_or_label(r.get("page_range")):
            continue
        origin = str(r.get("origin") or "")
        if origin == "own_result":
            own_no_page.append(sid)          # 不该被要页码 ⇒ 单独计数，不判失败
        elif origin == "external_lit":
            kind = str(r.get("kind") or "?")
            page_less_by_kind.setdefault(kind, []).append(sid)
    acc.readings["active_statements"] = len(rows)
    acc.readings["statements_missing_fields"] = bad
    acc.readings["page_range_not_required"] = {
        "own_result_rows": own_no_page,
        "note": ("自有结果的出处是 `doc_id` / `line_range`，'文献第几页'不是它该填的"
                 "那一栏 ⇒ 缺页码不判失败、不进 `statements_missing_fields`，"
                 "但仍在这里单独计数（静默豁免是本项目最忌的形态）。"),
    }
    acc.readings["page_range_missing_by_kind"] = {
        # 包一层 `by_kind`：`kind` 是自由文本，真有个 kind 叫 "note" 时不许撞掉说明
        "by_kind": page_less_by_kind,
        "note": ("缺页码的外部行按 `kind` 分栏，给写侧一份收尾清单：判据的裁决"
                 "不在这里改（它们照旧在 `statements_missing_fields` 里），"
                 "这一栏只让'缺的是哪一类行'直接可见。"),
    }
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

    ## 无人值守的那一趟（三档，当前采用乙）

    一次没人值守的运行里，"问了而用户没答"这一格注定是 `fail`。这不是判据的缺陷，
    而是"必须停在等待用户"这条纪律的读数。三档登记（供人改口径）：

    - 甲：把"正确地停下来等"判成 `pass`（要能区分"停在等"与"做完了"，
      数据面上判不了：交付说明里没有"我停在等什么"这一栏的机械位置）；
    - 乙（「当前」）：保持 `fail` —— 它准确定位了"这一趟不能交付"；
      口径写进 PAPER_PACK（"无人值守那一趟拿不到这一格，答完再 `--resume`"）
      与本节，并由 `tests/test_paper_pack.py` 的内容判据钉住；
    - 丙：给这一格加第四态（"停在等用户"），要动 `CRITERIA` 的三态口径
      （`pass/fail/unknown` 是全项目共用的读数口径）。

    甲/丙都要改口径本身，所以留给人裁；乙这一档是「有判据」的。
    """
    if session_root is None:
        acc.criteria["triage_branch_recorded"] = "unknown"
        acc.details["triage_branch_recorded"] = "没有会话记录根 ⇒ 没查成"
        return
    from .closing import NO_SESSION

    if sid == NO_SESSION:
        acc.criteria["triage_branch_recorded"] = "unknown"
        acc.details["triage_branch_recorded"] = (
            "这次审阅没有会话身份（装配期没注入 sid）⇒ 「该问的问了」这条没查成"
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
            "⇒ 正确的分支是停在「等待用户」，不是继续往下做")
    elif not replies:
        acc.criteria["triage_branch_recorded"] = "unknown"
        acc.details["triage_branch_recorded"] = (
            "这一次一次都没问过用户 ⇒ 「该问的问了」这条没查成"
            "（不是通过：没有提问记录与'问得对'不是同一件事）")
    else:
        acc.criteria["triage_branch_recorded"] = "pass"


def _session_spend_usd(session_root: Any, sid: str | None) -> tuple[float | None, int, int]:
    """会话事件里这一趟的花销：返回 `(合计 usd, 算不出价钱的调用数, llm_call 条数)`。

    `None` 的合计 = 「没查成」（没有会话根 / 没有 sid / 读不出来），不是"花了零"。

    ## 为什么本判据需要第二个数源

    `within_cost_cap` 原先只读 `usage_ledger`。而 `run-agent` 这条路
    「一次调用都没往账本里记过」：会话事件里有花销、账本是零 —— 于是这一格
    报"没超上限"，而真花销可能是上限的几倍。钱一直都在会话事件的
    `llm_call.usd` 里，所以判据必须两头都看：账本说多少、这一趟实际花了多少。
    """
    if session_root is None or sid is None:
        return None, 0, 0
    from . import sessions as SS

    events, _problems = SS.read_session(session_root, sid=sid)
    total = 0.0
    unknown = 0
    calls = 0
    for e in events:
        if str(e.get("kind") or "") != "llm_call":
            continue
        calls += 1
        usd = e.get("usd")
        if usd is None:
            unknown += 1
        else:
            total += float(usd or 0.0)
    return round(total, 6), unknown, calls


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

  处置（这一轮没有动 `schema.py`，理由如下）：
    真正被撞破的不是"算不出价钱"这一档，而是「账本整条路没记账」
    （`LlmSeam` 根本没有 meter ⇒ 30 次调用 0 行）。修法是把缝接上账本
    （`llmseam.LlmSeam.meter`），于是账本对新运行不再说谎；
    而为了让"任何一条忘了记账的路"都能被抓住，这里加上第三个读数：
    会话事件里的花销。三条口径：
      ① 上限判据用 `max(账本, 会话)` —— 保守，绝不按小的那个放行；
      ② 会话里花得比账本多 ⇒ 「fail」（"账本没跟上这一趟"，处置是修记账，不是改上限）；
      ③ 会话里有算不出价钱的调用 ⇒ 「unknown」（说不清花了多少，不是通过）。
    为什么不给 `usage_ledger.usd` 加 `None` 档：每一个读者都写着
    `float(r.get("usd") or 0.0)` —— 加一个 `None` 只会多出一条「新的」静默零路径，
    而不是消掉旧的。所以"算不出来"留在 `note` 里（写入方如实写），
    由这条判据判成 `unknown`。这一条要动 `schema.py`（FC-27），不动。
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

    ## 为什么必须排除顶趟行

    每一趟顶层运行会在 `tasks` 里留一条顶趟行（`role=M`、`action="run"`、
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
    done = 0
    hops: list[Any] = []
    for r in store.rows("tasks"):
        if str(r.get("status") or "") != "done":
            continue
        if str(r.get("outcome") or "") != "ok":
            continue
        done += 1
        if str(r.get("called_by") or "") != "user":
            hops.append(r)
    return hops, done - len(hops)


def _c_hops(acc: ReviewAcceptance, store: Any) -> None:
    """⑤ 每一跳都留下了可读的输入（`input_key` 非空 + 台账引用不悬空）。

 这一条查的是台账那一半：提示词的正文在会话记录的 `llm_call` 事件里
    （`prompt_sha256` / `prompt_chars`），本函数不读它 —— 两个读数各自都有落点，
    合起来才是"每跳提示词可读"。把边界写出来，免得读的人以为已经全查了。
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
                "`excluded_top_run_rows` 是本次排除掉的顶趟行（`called_by=\"user\"`）："
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
    """报告里点名的台账行是否真的存在；返回 `(不存在的那些, 没查成的原因)`。

    ## 为什么要这一条

    模型会把打算做的事写成已经做完的事：交付说明里写着"4 条登记进 `statements`
    （0000/0001/0002/0003）"、表格里逐行给 `statements 0001 / 0002 / 0003` ——
    而「台账里只有 0000 一条」。此前没有判据看这件事（旧的九节判据只问"每节有没有
    读数"，不问"读数是不是真的"）。

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

    from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）

    if store is None:
        return [], "没有 store ⇒ 报告里的台账引用没查成（不是「都查到了」）"
    kinds = (("statements", "stmt_id",
              rf"\bstatements?[:：]?\s*({S.ID_OR_LEGACY_PATTERN})"),
             ("literature", "lit_id",
              rf"\b(?:lit|literature)[:：]?\s*({S.ID_OR_LEGACY_PATTERN})"),
             ("documents", "doc_id",
              rf"\b(?:doc|documents?)[:：]?\s*({S.ID_OR_LEGACY_PATTERN})"))
    dangling: list[str] = []
    for table, id_field, pattern in kinds:
        wanted = {m for m in re.findall(pattern, text, flags=re.IGNORECASE)}
        have = {str(r.get(id_field) or "") for r in store.rows(table)}
        for rid in sorted(wanted - have):
            dangling.append(f"{table} {rid}")
    return dangling, ""


def _c_attachment(acc: ReviewAcceptance, store: Any, report_path: str) -> None:
    """⑥ 附件诚实：三份都要过 —— 来源不造假、不过度声称、引用的台账行真的存在。

    三条负控：

    1. 来源造假：把"我们补的手稿"写成文献里的东西（`FORGERY_MARKERS`）。
       处置方向是改正来源标注，不是补证据 —— 所以它与下面那条必须分开报；
    2. 没过 T3 写"已解决"：报告里出现 `RESOLVED_MARKERS`，而收工门的
       `load_bearing` 仍然判定"承重结论缺 T3"（同一个工作区里跑一次 `closing` 就知道）。
       处置方向是降档或补 T3；
    3. 「引用的台账行不存在」：报告里逐条写着
       `statements 0001/0002/0003`，而台账里只有 `0000` —— 判据全绿而交付说明
       在引用不存在的行。处置方向是「去把它真的登记上」（或把没做成的写成没做成），
       不是改判据。

    附件三件套（`origin=own_result` + 依据读数 + 版本 sha）由 `report_shape` 那条管；
    这一条只管诚实：说的是不是实话。

    ## 报告路径必须按工作区根解析

    这一格曾经用 `Path(report_path).is_file()` 直接判 —— 而模型给的报告路径是
    「相对工作区」的（`out/report/REPORT.md`，见 PAPER_PACK 的第九节口径），
    于是它在真机上判成"报告不在盘上 ⇒ 没查成"，而报告就在盘上（`unknown` 会挡住
    `passed`）。现在与另外三处共用同一个解析口。
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
    """那五种"容易拿到、但证明不了内容"的读数（逐字禁止拿来当通过）。

    相对路径按工作区根解析（与 `closing` 共用一份实现）：否则"相对工作区"
    这个契约在两次判据里会有两个口径，而错的读数看起来像"文件不在"。
    """
    import hashlib

    from . import conceptrows as CR   # 并表过渡期：概念那一份走合成视图
    from . import papercompile as PC
    from .closing import resolve_under_workspace

    project_dir = resolve_under_workspace(store, project_dir)

    aux: dict[str, Any] = {}
    # 正文 / PDF 的落点只有一个来源：`papercompile.package_dir`（2026-11-22 从
    # `out/paper/` 挪到 `out/package/`）。这里抄旧字面量会让这两格永远空 ——
    # 空与"没有主稿"在页面上长得一样，而那正是这一批要消掉的误读。
    pkg = PC.package_dir(project_dir) if project_dir else None
    tex = (pkg / PC.TEX_NAME) if pkg is not None else None
    aux["tex_sha256"] = (hashlib.sha256(tex.read_bytes()).hexdigest()[:12]
                         if tex is not None and tex.is_file() else "")
    pdf = (pkg / PC.PDF_NAME) if pkg is not None else None
    aux["pdf_pages"] = None
    if pdf is not None and pdf.is_file():
        try:  # 页数只作辅助：读不出来就 None，不许编一个数
            from .extract import page_count as _page_count
            aux["pdf_pages"] = _page_count(pdf)
        except Exception:  # noqa: BLE001 —— 辅助读数读不到就算了，它不参与判定
            aux["pdf_pages"] = None
    _matched, _why = (PC.receipt_matches_tex(project_dir) if project_dir else (None, ""))
    aux["receipt_matches_tex"] = ("unknown" if _matched is None
                                 else ("consistent" if _matched else "drifted"))
    aux["task_rows"] = len(store.rows("tasks")) if store is not None else 0
    # 概念图行数（验收口径）：概念那一份读合成视图（并表过渡期：老表 + 新标准
    # `kind="concept"`，同号去重）—— 它是给人看的辅助读数，读一边都会在迁移前后各错一次。
    # 名字里带 `concept_graph`：它数的是 文献 + 概念 + 关系（概念图三张表），不是
    # `usage_ledger` 的行数（那个数在 `readers._closing_cost` /
    # `modelcost.reconcile_usage` 的 `usage_ledger_rows` 上）。
    _ledger_concepts = (CR.view(store) if store is not None else {"checked": False, "rows": []})
    aux["concept_graph_rows"] = ((len(store.rows("literature")) + len(_ledger_concepts["rows"])
                                  + len(store.rows("relations"))) if store is not None else 0)
    if store is not None and not _ledger_concepts["checked"]:
        aux["concept_graph_rows_problem"] = "概念那一份没读成（合成视图 checked=False）"
    acc.auxiliary = aux


def check_review(store: Any, *, project_dir: str = "", report_path: str = "",
                 session_root: Any = None, cost_cap_usd: float | None = None,
                 sid: str | None = None,
                 ) -> ReviewAcceptance:
    """跑一次审稿场景的内容级验收（辅助读数不参与 `passed`）。

    `session_root` 不给时取 `store.root`。任何一格缺少必要输入 ⇒ `unknown`
    （"没查成"），而 `unknown` 不是通过。

    ## 生产出口（`agentflow closing`）

    这一层的唯一生产调用者是只读出口 CLI `agentflow closing`（`cli.cmd_closing`），
    读数分栏打在收工门读数之后 —— 为什么挑那个出口：收工门问的正是"这份交付能不能交"，
    而本模块问的是同一份交付的同一个问题，只是判据在内容层；两者的入参
    （`project_dir` / `report_path` / `session_root` / `sid`）本来就是同一批，
    而那批入参在 `cmd_closing` 里已经收齐了 ⇒ 不需要新开一条面。

    接线只加"谁调用它、读数落到哪"：六条判据、三态口径、`passed` 的算法
    （辅助读数一个都不参与）一个字都没动，`cmd_closing` 的退出码也仍然只由
    收工门定 —— 接线不改变任何判定强度。出口缺省就跑，`--no-review-acceptance`
    是显式关掉它（关掉时那一段读数说明自己是"没查成"，不许读成"内容级验收通过了"）。

    `sid` 必须给这一趟运行的那个 sid：不带它时 `pending_questions(root)` 按默认
    会话读，这一趟的提问会被读成"一次都没问过用户"，于是 `triage_branch_recorded`
    永远只能是 unknown —— 病因在调用姿势上，不在主控身上。

    `sid=closing.NO_SESSION` 是第三个输入（与 `sid=None` 刻意分开，口径见
    `closing.NO_SESSION`）：它说的是"调用方没有会话身份"，那一格记 `unknown`。
    CLI 出口拿不到运行内那个 sid，所以它传 `NO_SESSION` 而不是 `None`
    —— 折进 `None` 会按缺省会话读，那是假绿形态。
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
