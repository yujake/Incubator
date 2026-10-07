# -*- coding: utf-8 -*-
"""用户端 Web 界面的写路径（今天只有一个：提交回答）。

## 这一层是什么

`answer(root, form)` —— 从 `webui.py` 的 `_answer_action` 原样搬来、只改了个名字
（`draft/73` §1.2 的 R1 拆包；改名是为了让"写面"这个名字在包里可见）。
行为一字不改：落盘仍然只走 `userio.answer_question` 这一个写入口
（事件形状由它定义，本模块不拼第二份），三态与状态码也照旧。

## 口径（与拆包前逐条相同）

- qid 与 sid 必须按 `(sid, qid)` 这一对匹配：每段会话各自从 `q0001` 开始编号，
  只按 qid 索引会让"给一个已经答过的会话再提交"通过存在性检查，往那个会话里写下
  第二条回答（跨会话串味）；
- 失败不许折成 200：不在待答清单 ⇒ 409 并分「已经答过了」与「没有这个号」两档说清；
  写失败 ⇒ 500 并原样给出错误；
- 成功 ⇒ 303 回首页（PRG：刷新不重复提交）；
- 跳过（`skip=1`）⇒ 落一条空的 `selected` 与空的 `custom`。那是"答了，答案是空"，
  不是"没答"。

## W3 会在这里加什么

`/api/stop` · `/api/submit` · `/api/settings` 三个写端点与授权/审计
（裁定 C2：写面要 `--allow-writes` 才开）。本批只有回答这一条既有写路径，
授权面一个字都没动。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import sessions as SS
from .. import userio as U
from .state import _clip, _e, _sid_ok, _text, answer_text_of, snapshot

__all__ = ["ROUTES", "answer", "type_decls"]

#: 本模块挂到总路由表上的写端点：`(method, path 模式, WebHandler 的方法名)`。
#: 总表是 `webui/routes.py` 拼出来的（`自有 + READER_ROUTES + WRITE_ROUTES`），
#: 所以 C 线在 W3 加 `/api/stop` / `/api/submit`、W4 加 `/api/settings` 时，
#: 改的是这一行，不用去碰 A 线的文件（`draft/78 §3` 的接缝）。
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/answer", "handle_answer"),
)

#: 本模块还欠的 TS 接口（`(名字, 为什么还没有)`）。写面的三态回执在 W3/W4 才有
#: 生产者，所以本批不生成它的接口 —— 生成器把这一行写成 `types.ts` 里的 TODO。
MISSING_TYPES: tuple[tuple[str, str], ...] = ()

#: 写面统一回执的字段表（`(TS 名字, 后端出处, ((字段, TS 类型), ...))`）。
#: `id` / `extra` 是"有就带上"的两栏，所以写成可选。
_TS_TYPES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("WriteResult",
     "写面端点的统一回执（W3/W4 才有生产者 ⇒ 判据 C 不覆盖它；`id`/`extra` 只是"
     "「有就带上」的两栏，所以写成可选）",
     (("ok", "boolean"), ("tri", "Tri"), ("reason", "string"),
      ("id?", "string"), ("extra?", "Record<string, unknown>"))),
)


def type_decls() -> str:
    """本模块（写面）那一段 TS 声明文本。

    形状是 `draft/78 §3` 的接缝之一：`agentflow/web/emit_types.py` 把三条零交线
    各自的 `type_decls()` 拼成 `ui/src/types.ts`。C 线加写端点时，回执接口加在这里。
    """
    parts: list[str] = []
    for name, source, fields in _TS_TYPES:
        lines = [f"/** 出处：{source}。 */", f"export interface {name} {{"]
        lines += [f"  {field}: {ts};" for field, ts in fields]
        parts.append("\n".join(lines + ["}"]) + "\n")
    return "\n".join(parts)


def answer(root: Path, form: Mapping[str, Sequence[str]]) -> tuple[int, str, str]:
    """处理一次回答提交：返回 `(状态码, 重定向目标, HTML 正文)`。

    三态纪律：qid 不在待答清单里 ⇒ 409（不是 200），并在页面上说清是哪一档：
    已经被谁什么时候答过、还是根本没有这个号。写失败 ⇒ 500 并原样给出错误。
    """
    def one(name: str) -> str:
        """取表单里某个字段的第一个值（没有就给空串 —— 表单字段缺失是常态，不是错误）。"""
        vals = form.get(name) or []
        return _text(vals[0]) if vals else ""

    qid = one("qid").strip()
    sid_in = one("sid").strip()
    selected = [_text(x) for x in (form.get("selected") or [])]
    custom = one("custom")
    skip = one("skip").strip() in {"1", "true", "on", "yes"}
    state = snapshot(root)
    # 查待答问题必须「按 (sid, qid) 这一对」，不能只按 qid：每段会话各自从 q0001 开始
    # 编号，所以同一个工作区里"另一个会话的 q0001"完全可能同时待答。只按 qid 索引时，
    # 给一个「已经答过」的会话再提交（表单带着它自己的 sid）会因为"别处还有个 q0001"
    # 而通过存在性检查，于是往那个会话里写下第二条回答 —— 跨会话串味。
    match = None
    for q in state["pending_questions"]:
        if _text(q.get("qid")) != qid:
            continue
        if sid_in and _text(q.get("sid")) != sid_in:
            continue
        match = q
        break
    if not qid or match is None:
        # 分两档说清楚：答过了（在哪个会话）/ 没有这个号
        answered: dict[str, dict[str, Any]] = {}
        for sid_item in state["sessions"]:
            sid = _text(sid_item.get("sid"))
            if not _sid_ok(sid) or (sid_in and sid != sid_in):
                continue
            events, _bad = SS.read_session(root, sid=sid)
            for e in events:
                if str(e.get("kind") or "") == "user_answer" and _text(e.get("qid")) == qid:
                    answered.setdefault(sid, dict(e))
        if answered:
            who = ", ".join(
                f'{sid}（by {_text(e.get("by")) or "user"} @ {_text(e.get("ts"))}）'
                for sid, e in answered.items())
            html_body = (
                '<div class="card problem"><div class="card-head">'
                '<span class="badge badge-unknown">409 · 已经答过了</span></div>'
                f'<div class="readings">问题号 <span class="mono">{_e(qid)}</span> '
                f"已经不在待答清单里 —— 它已经被回答过：{_e(who)}。"
                f'回答文本：<span class="mono">'
                f'{_e(_clip(answer_text_of(list(answered.values())[0]), 300))}</span>'
                "</div>"
                '<div class="readings">这不是失败，是「迟到了」：'
                "回答只会在下一趟运行被读到。<a href=\"/\">回首页</a></div></div>")
            return 409, "", html_body
        html_body = (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">409 · 没有这个号</span></div>'
            f'<div class="readings">问题号 <span class="mono">{_e(qid) or "（空）"}</span>'
            " 不在任何会话的待答清单里，也不是一条已落盘的问答 —— 什么都没写。"
            '<a href="/">回首页</a> 看看现在在等什么。</div></div>')
        return 409, "", html_body
    q = match
    sid = sid_in or _text(q.get("sid"))
    if not _sid_ok(sid):
        sid = _text(q.get("sid"))
    if skip:
        selected = []
        custom = ""
    # 口径：「选项归 `selected`、自写归 `custom`」（我们的回答口径；字段名与 DSH 一致）。
    # 这里曾经把两者拼成一句 `text` 再以 `answer=text` 落盘，于是"点了哪个选项"
    # 被记成"自己写的一句话"（实测：表单提交 `selected=全保留` ⇒ 事件里
    # `selected: []` / `custom: "全保留"`）—— 那会把"人选了它"与"人写了它"
    # 折成一档，而这正是审阅线反复要分开的两件事。落盘只走 `userio.answer_question`
    # 这一个写入口（事件形状由它定义，本模块不再拼第二份）。
    try:
        problem = U.answer_question(root, qid=qid, selected=[x.strip() for x in selected
                                                             if x.strip()],
                                    custom=custom.strip(), by="web", sid=sid)
    except Exception as exc:  # noqa: BLE001 - 写失败不许折成 200
        return 500, "", (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">500 · 写失败</span></div>'
            f'<div class="readings">落盘时抛异常：'
            f'<span class="mono">{_e(f"{type(exc).__name__}: {exc}")}</span></div></div>')
    if problem:
        return 500, "", (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">500 · 写失败</span></div>'
            f'<div class="readings">会话记录没写成：'
            f'<span class="mono">{_e(problem)}</span>'
            f"（问题号 <span class=\"mono\">{_e(qid)}</span>，"
            f"会话 <span class=\"mono\">{_e(sid)}</span>）</div></div>")
    return 303, "/", ""
