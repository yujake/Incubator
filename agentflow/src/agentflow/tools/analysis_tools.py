"""只读角色 C 的「产出登记通道」（业主 2026-10-18 裁定「只读角色的产出要能进台账」）。

## 这个模块补的是哪一个洞（先有读数，再谈修法）
真机读数（`projects/mp3` 末节第 5 条）：`analysis_reports` = 0 —— C 的图读数没进登记表，
只在手稿 000004 与 D 的报告里。原因是 C 的「动作」（`gaps` / `handle` 等）不在 C 自己的
工具面上、只能由父代理 `conductor.summon(role="C", action=...)` 唤起；C 被派一个自由任务
时手上只有 `graph.*` / `table.*` / `fs.read`，写 `analysis_reports` 的唯一实现
（`AnalysisReport.persist`）在它的可调用面之外 ⇒ 分析只能写在回复里。这不是"模型不守
纪律"，是「通道不存在」。

## 修法（业主裁定：优先复用既有表、不新增表）
新增 `analysis.register_report`、只挂给 C：把这一趟「它自己产出的」分析登记进
`analysis_reports`（复用 `agent_c._support.AnalysisReport.persist` —— 存盘顺序、ID 分配、
文件名规则都还是那一份实现）。三条边界：① 只写 `analysis_reports` ——
`capabilities.READ_ONLY_WRITE_EXCEPTIONS["C"]` 与 `tools.base.READONLY_CALL_EXCEPTIONS`
两处都登记了它（`assert_capabilities` 第 `[5c]` 条守着）；② 只挂给 C（`roles=("C",)`；
D 有自己的 `write_report`）；③ 不碰知识表 —— 调用链上唯一的写是 `persist` 的
`st.tx("analysis_reports")`，`tests/test_readonly_output_channel.py` 用"全表行数前后不变"
守着。
"""
from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

from .. import schema as S
from .base import ToolRegistry, fail, ok, tool

#: 「这一份报告属于哪一档」的受控词表 —— 与 `schema.REPORT_KINDS` 同一份
#: （D 按 `kind` 分派解析逻辑 ⇒ 表外取值不许进表）。
REPORT_KINDS: tuple[str, ...] = S.REPORT_KINDS

#: 报告行上「改过几次、每次改了什么」那一格的名字（**追加式留痕**）。
#:
#: 为什么落在行上、而不是新开一张表：`analysis_reports` 的行在 `store.rebuild()`
#: 里是"事件行的 schema 字段 + 其余键原样保留"（`store.py` 的 `merged = {k: v for k, v
#: in row.items() if k not in canonical}`）⇒ 这一格随 `tx.upsert` 一起进事件日志，
#: 重建之后读得回来。新开一张表要动 `schema.TABLES`（磁盘格式契约）与 `verify`，
#: 而这一格的信息量只是"这一份报告被谁在什么时候因为什么改过"。
#:
#: 形状照 `statements` 的 `_statement_amend_history`（同一族：`at` / `by` / `changes`），
#: 只是多一格 `reason`（业主 2026-11-27：「必须带理由：哪一条读数与它矛盾」）与
#: 正文两份（改前 / 改后）—— 报告正文是模型的成品，只留"改了哪一格"读的人仍然看不到
#: 它原来怎么写。
AMENDMENTS_KEY = "_report_amendments"

#: 留痕最多留几条（有界读数纪律，与 `_statement_amend_history` 的 20 条同源）。
#: 超出时不静默丢：行上另记一条 `AMENDMENTS_KEY + "_dropped"` 的计数（丢了最早几条）。
MAX_AMENDMENTS = 20

#: 这一件能改的格（白名单）。`kind` 刻意不在里面：它是 D 分派解析逻辑的键，
#: 改 kind 等于把一份报告挪到另一个读法上（那不是"改报告"，是"换一份报告"）。
EDITABLE_FIELDS: tuple[str, ...] = ("request", "params", "summary", "payload", "markdown")


def _not_wired() -> Any:
    """未接线时显式失败（FC-08）：返回"没查成"，绝不返回一个假的 `report_id`。"""
    return fail(
        "analysis.register_report 未接线（装配时未提供 store）⇒ 这一行**没有登记**，"
        "不是「登记了但没有内容」",
        kind="not_wired",
    )


def _persist_analysis_report(
    store: Any,
    *,
    actor: str = "agent-C",
    kind: str,
    summary: str,
    markdown: str,
    request: str = "",
    payload: Any = None,
    params: Any = None,
    warnings: Any = None,
) -> dict:
    """把一份「已经是成品」的分析登记进 `analysis_reports`。

    复用 `agent_c._support.AnalysisReport.persist`：那是 C 落盘的唯一实现（先写 markdown
    文件、再在同一个事务里拿号写登记行）。另写一遍"怎么存"会立刻产生第二份口径
    （`FC-03` 同族），两份漂开的那一天 `reports/<rid>-<kind>.md` 与表里的 `markdown_path`
    就对不上了。参数里没有 `report_id`：号只能由 `tx.alloc_id("report")` 在持锁事务里取
    （并发两个 C 实例取到同一个号会让 upsert 静默互相覆盖）。
    """
    # 局部导入：`agent_c._support` 会顺带把 `specs.c` 拉进来，而工具层不该在
    # 导入期依赖声明层（`tools/__init__` 的模块装配顺序见那里的注释）。
    from ..agent_c._support import AnalysisReport

    rep = AnalysisReport(
        kind=str(kind or ""),
        request=str(request or ""),
        params=dict(params or {}),
        summary=str(summary or ""),
        payload=dict(payload or {}),
        markdown=str(markdown or ""),
        warnings=[str(w) for w in (warnings or [])],
    )
    # `kind` / `summary` / `markdown` / `payload` 的合法性由 `persist()` 判
    # （`S.REPORT_KINDS`、非空、可 JSON 序列化）—— 这里不另写一套校验（FC-03）。
    settled = rep.persist(store, actor=actor)
    return {
        "checked": True,
        "report_id": str(settled.get("report_id") or ""),
        "markdown_path": str(settled.get("markdown_path") or ""),
        "kind": rep.kind,
        "summary": rep.summary,
        "created_by": rep.created_by,
    }


# TOOLFACE-CLEAN（业主 2026-11-22：实现只留在代码注释里）
# 搬走的实现细节：落点是 `analysis_reports` 表（正文另写一份
# `work/C/<report_id>-<kind>.md`）；唯一写实现是 `agent_c._support.AnalysisReport.persist`
# （先写 markdown，再在同一事务里 `tx.alloc_id("report")` 取号写登记行）。
# 模型面只说「登记成一条可查的报告」，判据：`tests/test_tool_face_three_segments.py` ①②③。
@tool(
    "analysis.register_report",
    (
        "把你自己产出的分析登记成一条可查的报告（档位 + 一句话结论 + 正文）；不登记=没发生。"
    ),
    {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": list(REPORT_KINDS),
                "description": (f"报告档位（受控词表 {list(REPORT_KINDS)}）："
                                "hottest=最热门概念、paths=两概念间的链条/图读数、"
                                "cold=冷门概念、gaps=候选研究缺口、"
                                "proof_chain=证明链的路径分析（依赖边走到哪、哪一条承重）"),
            },
            "summary": {"type": "string", "minLength": 1,
                        "description": "一句话结论（D 的第一入口就是它；不许写成「见正文」）"},
            "markdown": {"type": "string", "minLength": 1,
                         "description": "报告正文（markdown）：读数、判断、边界逐条写清"},
            "request": {"type": "string",
                        "description": "这条分析是被什么要求做出来的（派活原文或你的复述）"},
            "payload": {"type": "object",
                        "description": "机器可读部分（代号链 / 度数表 / 评分明细等），D 溯源用"},
            "params": {"type": "object", "description": "这次分析用的参数（top_n / limit 等）"},
            "warnings": {"type": "array", "items": {"type": "string"},
                         "description": "这一份的已知边界（拿不到的行号、被截断的读数）"},
        },
        "required": ["kind", "summary", "markdown"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("C",),
    returns=("{'checked','report_id','markdown_path','kind','summary','created_by'}"
             "（`checked=False` = 没接线/参数非法 ⇒ 那一行没有登记）"),
    tags=("analysis", "write", "register"),

    scenario="算完图或缺口、要在回复之外留一份可回查的分析时用它；只登记自己的产出。",
    example="登记一份「最热门概念」分析 → report_id / markdown_path / created_by。",
    example_code=(
        "analysis.register_report(kind=\"hottest\", summary=\"0003 被引 12 次，最热\", "
        "markdown=\"# 热度\\n- 0003：12 次\\n\", payload={\"top\": \"0003\"})"
    ),
)
def _analysis_register_report_tool(_not_wired_fn, store, actor, **kw: Any):
    """`analysis.register_report` 的工具体（注入值由装配期 `partial` 绑定）。"""
    return _not_wired_fn() if store is None else _persist_analysis_report(
        store, actor=actor, **kw)


# ---------------------------------------------------------------------------
# 编辑入口（业主 2026-11-27 口径）
# ---------------------------------------------------------------------------
#
# 业主口径逐字：「口径A错误，口径B不准确。C 需要对自己的分析报告负责，需要核实证明链走通
# 且逻辑自然，如遇不合理的地方需要 edit 这个报告。」
#
# 现状（这一笔开工前的读数）：C 的工具面 35 件里写口只有 `analysis.register_report`
# —— 它**一次性登记**，登记完那份报告就只读；`schema.AnalysisReport` 九个字段里没有
# 任何修订位。于是"C 发现自己的报告有错"这件事在工具面上**没有出口**：它只能在回复里
# 说，而回复不进台账 ⇒ 报告照旧错着躺在 `analysis_reports` 里等 D 去读。
#
# 三条边界（这就是权限面，逐条写着）：
#   ① **只能改自己交的报告**：`created_by` 归一之后必须等于本工具的 actor（C）；
#      别人的报告（D 的、另一个 coder 的）与**别的表**一律受控拒绝 —— 后者是结构性的：
#      本工具的 schema `additionalProperties: false`，且参数里没有 `table` 这一格。
#   ② **必须带理由**：`reason` 是必填参数，写清"哪一条读数与它矛盾"；空理由拒收。
#   ③ 留痕是追加式：`AMENDMENTS_KEY` 那一格一行一条（谁 / 何时 / 为什么 / 改前 / 改后），
#      只往后长；正文另存一份修订副本（落在同一族的目录里，旧文件不动）。
#
# 三态：读不到（报告行不在 / 正文文件读不出）与改不成（不是自己的 / 没理由 / 没给改动）
# 都返回**受控拒绝**（`checked=False` + `refused` + 一句为什么），绝不折成"改好了"；
# 只有真的写进去了才 `checked=True, edited=True`。


def _owner_key(name: Any) -> str:
    """把 `created_by` / actor 归一成同一个身份键（`agent-C` / `C` / `c` 是同一人）。

    为什么归一而不是逐字比：`persist()` 落行时的 `created_by` 是**装配期注入的 actor**
    （`agent-C`），而 `schema.AnalysisReport` 的字段缺省是 `agent-C`、动作层用 `C` ——
    逐字比会让"自己的报告"在换一种写法时变成"别人的报告"（假拒），而放宽成"包含就行"
    又会让 `agent-C2` 认领 `agent-C` 的报告（越权）。所以剥掉 `agent-` 前缀、小写、
    再去掉实例段之前的那一部分后逐字比。
    """
    text = str(name or "").strip().lower()
    if text.startswith("agent-"):
        text = text[len("agent-"):]
    return text


def _read_body(root: Any, markdown_path: Any) -> str | None:
    """把一份报告的正文从盘上读回来（读不到 ⇒ `None`，不是空串）。

    三态在这里再分一次：`None` = 读不到（文件不在 / 不是普通文件 / 解码失败），
    空串 = 读到了、里面确实是空的。折成同一个值会让"这一份丢了"与"这一份是空的"
    再也分不开，而两者对"能不能改"的答案是相反的。
    """
    rel = str(markdown_path or "")
    if not rel:
        return None
    try:
        return (Path(root) / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _revision_path(current_rel: str, rev: int) -> str:
    """第 `rev` 次修订的正文落点：**现有那一份旁边**（同目录、同名 + `.r<N>`）。

    `work/C/000011-proof_chain.md` ⇒ `work/C/000011-proof_chain.r1.md`；
    若报告正文住在别的落点（例如按稿号落的 `manuscripts/<角色>/<稿号>.md`），
    修订件也跟着落在那一族里 —— 不写死目录，免得修订件与正文分家。
    """
    rel = str(current_rel or "").replace("\\", "/")
    head, _, name = rel.rpartition("/")
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    new_name = f"{stem}.r{int(rev)}{('.' + suffix) if suffix else ''}"
    return f"{head}/{new_name}" if head else new_name


def edit_report(
    store: Any,
    *,
    actor: str = "agent-C",
    report_id: str,
    reason: str,
    summary: Any = None,
    markdown: Any = None,
    payload: Any = None,
    params: Any = None,
    request: Any = None,
    **extra: Any,
) -> dict:
    """C 改自己交过的那份报告（唯一入口；`analysis.edit_report` 的工具体）。

    返回字典的键集合在**每一条分支上都相同**（`checked` / `edited` / `refused` /
    `report_id` / `changed` / `before` / `after` / `revision` / `amendments` /
    `markdown_path` / `reason` / `at`）—— 受控拒绝也有 `report_id` 与 `refused`，
    读的人不必去猜"这是没改还是没查"。
    """
    out: dict[str, Any] = {
        "checked": False, "edited": False, "refused": "",
        "report_id": str(report_id or "").strip(), "changed": [],
        "before": {}, "after": {}, "revision": 0, "amendments": 0,
        "markdown_path": "", "reason": "", "at": "",
    }
    if store is None:
        out.update(refused="not_wired",
                   reason=("analysis.edit_report 未接线（装配时未提供 store）⇒ 这份报告"
                           "**没有改动**，不是「改好了」"))
        return out
    if extra:
        out.update(refused="key_not_allowed", reason=(
            f"这一条只允许改 {list(EDITABLE_FIELDS)}（外加必填的 `report_id` / `reason`），"
            f"收到未声明的 {sorted(extra)} ⇒ 整笔不写，盘上一个字节都没变。"
            "它只改你自己交的 `analysis_reports` 那一行 —— 别的表没有可写的口。"))
        return out
    rid = out["report_id"]
    if not rid:
        out.update(refused="missing_report_id",
                   reason="没给 `report_id` ⇒ 不知道要改哪一份（这不是「报告不存在」）")
        return out
    why = str(reason or "").strip()
    if not why:
        out.update(refused="missing_reason", reason=(
            "没给 `reason` ⇒ 不改（业主 2026-11-27：必须带理由 —— 哪一条读数与它矛盾、"
            "改前是什么、改后是什么）。空理由不是一种理由。"))
        return out
    wanted: dict[str, Any] = {}
    for key, value in (("request", request), ("params", params), ("summary", summary),
                       ("payload", payload), ("markdown", markdown)):
        if value is None:
            continue
        if key in ("params", "payload") and not isinstance(value, dict):
            out.update(refused="bad_patch", reason=(
                f"`{key}` 必须是对象，收到 {type(value).__name__} ⇒ 整笔不写"))
            return out
        if key in ("summary", "markdown", "request") and not isinstance(value, str):
            out.update(refused="bad_patch", reason=(
                f"`{key}` 必须是字符串，收到 {type(value).__name__} ⇒ 整笔不写"))
            return out
        wanted[key] = value
    if not wanted:
        out.update(refused="empty_patch", reason=(
            f"一个要改的格都没给（可改 {list(EDITABLE_FIELDS)}）⇒ 这一笔没有内容可改。"
            "`kind` 不可改：它是 D 分派解析逻辑的键，换 kind 等于换一份报告。"))
        return out

    from ..agent_c._support import _atomic_write_text

    rel_md = ""
    try:
        with store.tx("analysis_reports", actor=str(actor or "agent-C"),
                      note="analysis:edit_report") as tx:
            row = tx.find("analysis_reports", report_id=rid)
            if row is None:
                out.update(refused="not_found", reason=(
                    f"`analysis_reports` 里没有主键 {rid} ⇒ 没有可改的那一行"
                    "（这是「查过了、没有这一行」，不是「改不成」）"))
                return out
            owner = _owner_key(row.get("created_by"))
            if owner != _owner_key(actor):
                out.update(refused="not_report_owner", reason=(
                    f"这一份的 `created_by` 是 {str(row.get('created_by') or '')!r}，"
                    f"而你是 {str(actor or '')!r} ⇒ 只许改自己交的报告。"
                    "别人的报告一个字节都不能改（你可以在自己的回复里指出它的问题，"
                    "但改它不在你的权限面里）"))
                return out
            out["markdown_path"] = str(row.get("markdown_path") or "")
            history = [dict(h) for h in (row.get(AMENDMENTS_KEY) or [])
                       if isinstance(h, dict)]
            # 「改前是什么」必须真的读得到 —— 而且**无条件**读：正文不在行上（行只有
            # `markdown_path`），所以"这一份报告还在不在"只能由盘上那一份回答。
            # 读不到就**受控拒**（业主三态：读不到 ≠ 改好了）。为什么不只在改正文时读：
            # 一份正文已经丢了的报告，改它的 `summary` 等于在一份读不到的报告上盖戳 ——
            # 那正是"折成改好了"的另一种形态。
            body_before = str(row.get("markdown") or "")
            if not body_before:
                body_before = _read_body(store.root, row.get("markdown_path"))
            if body_before is None:
                out.update(refused="body_unreadable", reason=(
                    f"报告 {rid} 的现有正文读不出来（markdown_path="
                    f"{str(row.get('markdown_path') or '（空）')}）⇒「改前是什么」说不清，"
                    "整笔不写。这不是「报告不存在」，是「这一份读不到」"))
                return out
            before = {k: row.get(k) for k in wanted}
            changed = {k: v for k, v in wanted.items() if row.get(k) != v}
            out["before"] = {k: before.get(k) for k in changed}
            if "markdown" in changed:
                out["before"]["markdown"] = body_before
            if not changed:
                out.update(checked=True, edited=False, revision=len(history),
                           amendments=len(history), reason=(
                               "这一笔要改的格已经是这些值 ⇒ 一个字节都没写"
                               "（幂等：不是失败，也不是改成了）"))
                return out
            rev = len(history) + 1
            merged = dict(row)
            merged.update(changed)
            if "markdown" in changed:
                text = str(changed["markdown"] or "")
                if not text.strip():
                    out.update(refused="bad_patch", reason=(
                        "`markdown` 改成空串 ⇒ 拒收：一份没有正文的报告与「没登记」分不开"))
                    return out
                prev_rel = str(row.get("markdown_path") or "")
                if not prev_rel:
                    out.update(refused="body_unreadable", reason=(
                        f"报告 {rid} 这一行没有 `markdown_path` ⇒ 改前正文读不到，"
                        "改完也说不清「改前是什么」⇒ 整笔不写"))
                    return out
                # 修改后的正文落在**现有那一份旁边**（同目录、同名 + `.r<N>`），而不是写死
                # `work/C/`：报告的落点会随"稿号/落点"口径变化（例如改成 `manuscripts/<角色>/`
                # 那一族），写死目录等于给修订件造一个与正文分家的落点 —— 下一次读
                # `markdown_path` 的人会看到两个地方各有一份，而不知道哪一份是正文。
                rel_md = _revision_path(prev_rel, rev)
                _atomic_write_text(Path(store.root) / rel_md, text)
                merged["markdown_path"] = rel_md
            entry = {
                "at": S.now_iso(),
                "by": str(actor or "agent-C"),
                "reason": why,
                "revision": rev,
                "changes": {k: {"from": out["before"].get(k), "to": v}
                            for k, v in changed.items()},
                "markdown_path_before": str(row.get("markdown_path") or ""),
                "markdown_path_after": str(merged.get("markdown_path") or ""),
            }
            kept = history + [entry]
            dropped = 0
            if len(kept) > MAX_AMENDMENTS:
                dropped = len(kept) - MAX_AMENDMENTS
                kept = kept[dropped:]
            merged[AMENDMENTS_KEY] = kept
            if dropped:
                merged["_report_amendments_dropped"] = int(
                    row.get("_report_amendments_dropped") or 0) + dropped
            # 整行重建后过与登记那一支同一套字段校验（`summary` 非空、`markdown_path`
            # 必须相对、`payload` 必须是对象）—— 改一格不许顺手写坏一行。
            try:
                fresh = S.row_from_dict("analysis_reports", dict(merged))
                fresh.validate()
                canonical = fresh.to_dict()
            except (TypeError, ValueError) as exc:
                out.update(refused="validation", reason=(
                    f"改完之后这一行不是合法的报告行（{type(exc).__name__}: {exc}）"
                    " ⇒ 整笔不写"))
                return out
            extra_keys = {k: v for k, v in merged.items() if k not in canonical}
            row_out = {**extra_keys, **canonical}
            tx.upsert("analysis_reports", row_out, note="analysis:edit_report")
    except Exception as exc:  # noqa: BLE001 — 落盘失败必须回三态，不许半笔
        out.update(checked=False, edited=False, refused="write_failed", reason=(
            f"改这份报告没成（{type(exc).__name__}: {exc}）⇒ 按原样读回去核对，"
            "不许把它当成改好了"))
        return out
    out.update(checked=True, edited=True, changed=sorted(changed),
               after={k: merged.get(k) for k in changed},
               revision=rev, amendments=len(kept),
               markdown_path=str(merged.get("markdown_path") or ""),
               reason=(f"改了 {sorted(changed)}（理由：{why}）；"
                       f"留痕第 {rev} 条，旧正文仍在 {entry['markdown_path_before'] or '（无）'}"),
               at=str(entry["at"]))
    # 产物归属：正文另存了一份新文件 ⇒ 补登记（与 `persist` 同一条口径）。
    # 登记失败**不折成"没改成"** —— 报告确实改了；把这条读数如实带回去。
    if rel_md:
        try:
            from .. import artifacts as A

            _entry, _problem = A.record_or_problem(
                store.root, path=rel_md, producer=_owner_key(actor).upper() or "C",
                kind=f"analysis-report-{str(row_out.get('kind') or 'report')}",
                note=f"C 修订自己的分析报告（第 {rev} 次）")
        except Exception as exc:  # noqa: BLE001 — 归属登记失败单独报
            _problem = f"{type(exc).__name__}: {exc}"
        if _problem:
            out["artifact_problem"] = (
                f"{_problem} ⇒ 修订正文 {rel_md} 没有产物归属登记"
                "（报告本身已改好，这一格只是归属读数缺了）")
    return out


# TOOLFACE-CLEAN（业主 2026-11-22：实现只留在代码注释里）
# 模型面只说「改自己交过的报告，必须写清哪一条读数与它矛盾」；留痕落在行上的
# `AMENDMENTS_KEY` 那一格（追加式）与修订副本（旧文件不动）两处，
# 写实现就是本文件里的 `edit_report`。
# 判据：`tests/test_cedit_edit_own_report.py` 的 a–f 六条（含两条反真空）。
@tool(
    "analysis.edit_report",
    (
        "改你自己交过的那一份报告的正文 / 结论 / 读数（必须写清哪一条读数与它矛盾）；"
        "改不了别人的，每改一次留一条痕。"
    ),
    {
        "type": "object",
        "properties": {
            "report_id": {"type": "string", "minLength": 1,
                          "description": "要改的那一份的号（你自己登记时拿到的 report_id）"},
            "reason": {"type": "string", "minLength": 1,
                       "description": ("为什么改：哪一条读数与它矛盾 / 哪一跳接不上；"
                                       "改前是什么、改后是什么要写得能对上")},
            "summary": {"type": "string",
                        "description": "改后的一句话结论（不给就不动）"},
            "markdown": {"type": "string",
                         "description": "改后的正文（不给就不动；旧正文另存一份）"},
            "payload": {"type": "object",
                        "description": "改后的机器可读部分（不给就不动）"},
            "params": {"type": "object", "description": "改后的参数（不给就不动）"},
            "request": {"type": "string", "description": "改后的需求原文（不给就不动）"},
        },
        "required": ["report_id", "reason"],
        "additionalProperties": False,
    },
    side_effect="write_local",
    roles=("C",),
    returns=("{'checked','edited','refused','report_id','changed','before','after',"
             "'revision','amendments','markdown_path','reason','at'}"
             "（`checked=False` = 受控拒绝：不是自己的 / 没有理由 / 读不到 ⇒ 一个字节都没写）"),
    tags=("analysis", "write", "edit"),

    scenario=("交完报告又核了一遍，发现读数与正文矛盾、某一跳接不上、或要补一条新命题建议时用它；只改自己的报告。"),
    example=("把同一份报告的正文补上「这一跳不成立」→ edited=True / revision / "
             "before（改前正文）/ after（改后正文）。"),
    example_code=(
        "analysis.edit_report(report_id=\"0007\", "
        "reason=\"报告里 000024 的根被标成没有依赖，"
        "而展开读数里它依赖 000016，两者矛盾\", "
        "markdown=\"# 证明链\\n- 000024 ← 000016（改后）\\n\")"
    ),
)
def _analysis_edit_report_tool(_not_wired_fn, store, actor, **kw: Any):
    """`analysis.edit_report` 的工具体（注入值由装配期 `partial` 绑定）。

    三态在**工具层**的落点：`edit_report()` 返回的是读数字典，而"没改成"必须以
    `ok=False` 交回模型（否则「受控拒绝」在模型看来与「改好了」一模一样 ——
    它只看到一次成功的工具回执）。所以这里按 `checked` 分流：真的写进去了才 `ok`。
    """
    if store is None:
        return _not_wired_fn()
    out = edit_report(store, actor=actor, **kw)
    if not out.get("checked"):
        return fail(str(out.get("reason") or "改这份报告没成"), **out)
    return ok(out, **out)


#: 装配清单：`(工具体函数, 需要从装配期注入的名字)`。
_TOOL_FUNCTIONS: tuple[tuple[Any, tuple[str, ...]], ...] = (
    (_analysis_register_report_tool, ("_not_wired_fn", "store", "actor")),
    (_analysis_edit_report_tool, ("_not_wired_fn", "store", "actor")),
)


def register(registry: ToolRegistry, *, store: Any = None, actor: str = "agent-C",
             **_: Any) -> None:
    """把 C 的产出登记通道装进注册表。

    `store` 为 None 时「照样注册」（调用时给 `not_wired`，`FC-08`）：
    "没接线"与"没有分析"是两件事，不许折叠。
    """
    for fn, deps in _TOOL_FUNCTIONS:
        bound = {"_not_wired_fn": _not_wired, "store": store, "actor": actor}
        registry.register(
            _replace_handler(fn, partial(fn, *[bound[k] for k in deps])))


def _replace_handler(fn: Any, handler: Any) -> Any:
    """把一个 `@tool` 声明过的函数换成绑定好的 handler（与其它模块同一形态）。"""
    from dataclasses import replace

    return replace(fn.__tool_spec__, handler=handler)
