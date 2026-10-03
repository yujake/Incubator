# -*- coding: utf-8 -*-
"""审稿场景的内容级验收（`draft/37` §17.3 的 ①②③④⑤，可离线跑）。

## 为什么需要它（而不是又一套"看起来完成了"）

§17.3 对第三档验收写了两半：该验的五条（报告九节且每栏有读数 / 定理台账每条有完整假设
与出处 / 三态分支正确且落盘可查 / 成本上限内 / 每跳提示词可读），以及
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

#: 六条内容级判据（顺序即交付说明里的顺序）。
CRITERIA: tuple[tuple[str, str], ...] = (
    ("report_sections_have_readings", "报告九节齐全，且**每节都有读数**（数字或台账引用）"),
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

_SECTION_RE = re.compile(r"^#{2,3}\s*([一二三四五六七八九])、(.+)$", re.M)
_LEDGER_REF_RE = re.compile(r"[a-z_]+:\d{4}|#\w[\w-]*|\bstmt\b|台账|页")


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

def _c_report(acc: ReviewAcceptance, report_path: str) -> None:
    """① 报告九节齐全，且每节都有读数（不是空标题）。"""
    if not str(report_path or "").strip():
        acc.criteria["report_sections_have_readings"] = "unknown"
        acc.details["report_sections_have_readings"] = "没给报告路径 ⇒ 没查成（不是通过）"
        return
    path = Path(report_path)
    if not path.is_file():
        acc.criteria["report_sections_have_readings"] = "unknown"
        acc.details["report_sections_have_readings"] = f"报告不在盘上：{path} ⇒ 没查成"
        return
    text = path.read_text(encoding="utf-8")
    sections = _SECTION_RE.findall(text)
    empty: list[str] = []
    for num, name in sections:
        # 每一节的正文 = 该标题到下一个标题之间
        start = text.find(f"{num}、")
        nxt = min([p for p in (text.find(f"{n}、", start + 1) for n in "一二三四五六七八九")
                   if p > start] or [len(text)])
        body = text[start:nxt]
        if not re.search(r"\d", body) and not _LEDGER_REF_RE.search(body):
            empty.append(f"{num}、{name.strip()}")
    acc.readings["report_sections"] = [f"{n}、{t.strip()}" for n, t in sections]
    acc.readings["report_sections_without_readings"] = empty
    if len(sections) < 9:
        acc.criteria["report_sections_have_readings"] = "fail"
        acc.details["report_sections_have_readings"] = (
            f"报告只有 {len(sections)} 节（要 9 节）⇒ 形状就不齐")
    elif empty:
        acc.criteria["report_sections_have_readings"] = "fail"
        acc.details["report_sections_have_readings"] = (
            "这些节里没有任何读数（既没有数字也没有台账引用）：" + "、".join(empty)
            + " —— 空标题不算交了这一节")
    else:
        acc.criteria["report_sections_have_readings"] = "pass"


def _c_statements(acc: ReviewAcceptance, store: Any) -> None:
    """② 定理台账每条都有完整假设与出处（含页码）。

    只查 `active` 的那些：`disputed`/`refuted`/`superseded` 本来就不许当依据，
    对它们提"必须有假设与出处"是把处置方向搞反（§17.3 问的是交付里的定理）。
    """
    if store is None:
        acc.criteria["statements_have_assumptions_and_source"] = "unknown"
        acc.details["statements_have_assumptions_and_source"] = "没有 store ⇒ 没查成"
        return
    rows = [r for r in store.rows("statements") if str(r.get("status") or "") == "active"]
    bad: list[str] = []
    for r in rows:
        sid = str(r.get("stmt_id"))
        if not str(r.get("statement_full") or "").strip():
            bad.append(f"{sid} 缺 statement_full（完整假设）")
        if not str(r.get("source_lit_id") or "").strip():
            bad.append(f"{sid} 缺 source_lit_id（出处）")
        page = r.get("page_range") or {}
        if not (page.get("start") or page.get("label")):
            bad.append(f"{sid} 缺 page_range（页码）")
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
    """
    if session_root is None:
        acc.criteria["triage_branch_recorded"] = "unknown"
        acc.details["triage_branch_recorded"] = "没有会话记录根 ⇒ 没查成"
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


def _c_cost(acc: ReviewAcceptance, store: Any, cap_usd: float | None) -> None:
    """④ 成本上限：`usage_ledger` 的合计不超过上限。

 这一条今天有一个盲区，写在读数里（不是藏起来）：
    `tokenmeter._row_for` 永远写 `round(c.usd_total, 6)`（一个 float），
    而"这次调用算不出花销"这件事记在 spend 的 `unknown_usd_calls` 里、
    不进账本行 ⇒ 一次算不出价钱的调用在账本上看起来就是零元。
    所以本判据只能说"账本上的合计没超上限"，说不出"这一轮没有漏记的花销"。
    补法：把 `unknown_usd_calls` 也落进账本（或给它一列），或者让 `usage_ledger`
    允许 `usd=None` 这一档 —— 两者都要动 `schema.py`/`tokenmeter.py`，留给人裁。
    """
    if store is None:
        acc.criteria["within_cost_cap"] = "unknown"
        acc.details["within_cost_cap"] = "没有 store ⇒ 没查成"
        return
    rows = store.rows("usage_ledger")
    total = sum(float(r.get("usd") or 0.0) for r in rows)
    acc.readings["cost"] = {"rows": len(rows), "usd": round(total, 6), "cap_usd": cap_usd,
                            "blind_spot": "账本行永远是 float（`usd_total`）⇒ "
                                          "「这次调用算不出花销」在账本上看不见"
                                          "（它在 spend 的 unknown_usd_calls 里）"}
    if cap_usd is None:
        acc.criteria["within_cost_cap"] = "unknown"
        acc.details["within_cost_cap"] = "没给成本上限 ⇒ 这一条没查成（不是通过）"
    elif total > float(cap_usd):
        acc.criteria["within_cost_cap"] = "fail"
        acc.details["within_cost_cap"] = f"花了 {total:.6f} > 上限 {float(cap_usd):.6f}"
    else:
        acc.criteria["within_cost_cap"] = "pass"


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
    rows = [r for r in store.rows("tasks") if str(r.get("status") or "") == "done"
            and str(r.get("outcome") or "") == "ok"]
    missing = [str(r.get("task_id")) for r in rows if not str(r.get("input_key") or "").strip()]
    acc.readings["hops"] = {"ok_tasks": len(rows), "without_input_key": missing,
                            "note": "提示词正文在会话记录的 llm_call 事件里"
                                    "（prompt_sha256/prompt_chars），本判据只看台账那一半"}
    if not rows:
        acc.criteria["hops_have_readable_prompts"] = "fail"
        acc.details["hops_have_readable_prompts"] = "台账里没有任何成功的召唤 ⇒ 这次审阅没跑起来"
    elif missing:
        acc.criteria["hops_have_readable_prompts"] = "fail"
        acc.details["hops_have_readable_prompts"] = (
            f"这些成功的召唤没有 input_key（{missing[:5]}）⇒ 说不清'派下去的是什么'")
    else:
        acc.criteria["hops_have_readable_prompts"] = "pass"


def _c_attachment(acc: ReviewAcceptance, store: Any, report_path: str) -> None:
    """⑥ 附件诚实（R25）：两份都要过 —— 来源不造假、不过度声称。

    两条负控（`draft/37` §16 P3 的报告行逐字要求）：

    1. 来源造假：把"我们补的手稿"写成文献里的东西（`FORGERY_MARKERS`）。
       处置方向是改正来源标注，不是补证据 —— 所以它与下面那条必须分开报；
    2. 没过 T3 写"已解决"：报告里出现 `RESOLVED_MARKERS`，而收工门的
       `load_bearing` 仍然判定"承重结论缺 T3"（同一个工作区里跑一次 `closing` 就知道）。
       处置方向是降档或补 T3。

    附件三件套（`origin=own_result` + 依据读数 + 版本 sha）由 `report_shape` 那条管；
    这一条只管诚实：说的是不是实话。
    """
    if not str(report_path or "").strip() or not Path(report_path).is_file():
        acc.criteria["attachment_is_honest"] = "unknown"
        acc.details["attachment_is_honest"] = "报告不在盘上 ⇒ 附件的诚实没查成（不是通过）"
        return
    text = Path(report_path).read_text(encoding="utf-8")
    forged = [m for m in FORGERY_MARKERS if m in text]
    overclaim = [m for m in RESOLVED_MARKERS if m in text]
    acc.readings["attachment"] = {"forgery_markers": forged, "resolved_markers": overclaim}
    problems: list[str] = []
    if forged:
        problems.append(f"来源造假：报告里出现 {forged} —— 我们补的东西不许写成文献里的")
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
    else:
        acc.criteria["attachment_is_honest"] = "pass"


def _auxiliary(acc: ReviewAcceptance, store: Any, project_dir: str) -> None:
    """那五种"容易拿到、但证明不了内容"的读数（§17.3 逐字禁止拿来当通过）。"""
    import hashlib

    from . import renderanchor as RA

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
    _c_report(acc, report_path)
    _c_statements(acc, store)
    _c_triage(acc, store, root, sid=sid)
    _c_cost(acc, store, cost_cap_usd)
    _c_hops(acc, store)
    _c_attachment(acc, store, report_path)
    _auxiliary(acc, store, project_dir)
    return acc
