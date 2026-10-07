# -*- coding: utf-8 -*-
"""用户端 Web 界面的服务端渲染（从 `webui.py` 原样搬来，语义一字不改）。

## 这一层是什么

`_page` / `_top` / `_question_card` / `_run_row` / `_event_card` / `render_root` /
`render_run` / `_not_found` —— 都是把 :func:`agentflow.webui.snapshot` 的快照渲染成
HTML 的纯函数（同一份快照渲染两次逐字节相同）。

## 它会怎样消失（裁定 P1：迁一面删一面）

SPA 的六个页面（`ui/src/pages/**`）在 W1–W4 逐面接管这些读数；每迁完一面，
这里对应的那个函数就删掉，W5 时本文件应当清空。所以搬进来的时候刻意
一行不改：它是被替换掉的旧壳，不是要被继续扩建的地方。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from .. import sessions as SS
from ..web.assets import STYLESHEET
from .state import (
    REPORT_REL,
    _age,
    _clip,
    _e,
    _esc,
    _num,
    _read_report,
    _sid_ok,
    _text,
    _usd,
    answer_text_of,
    option_view,
)

__all__ = ["render_root", "render_run"]

#: 停止理由 → 徽标词汇：三态加一档「停在等待用户」。
_STOP_BADGES = {
    "final": ("badge-pass", "跑完"),
    "budget": ("badge-unknown", "预算用尽"),
    "max_steps": ("badge-unknown", "步数用尽"),
    "not_wired": ("badge-fail", "没接线"),
    "bad_json_limit": ("badge-fail", "坏 JSON 连击"),
    "bad_args_limit": ("badge-fail", "坏参数连击"),
    # `draft/37` §136：同调用 + 同读数连着到上限 ⇒ 这一趟停在"没有新事实"。
    # 刻意不是 `badge-fail`：那不是出错，是"这一趟没有往前走"（一档读数）。
    "no_progress_limit": ("badge-unknown", "原地打转"),
    "waiting_for_user": ("badge-pending", "停在等用户"),
}


def _top(state: dict[str, Any], *, crumb: str = "") -> str:
    """页面头部：我们是谁、工作区根在哪、待回答几条、最后更新何时。"""
    pend = len(state.get("pending_questions") or [])
    badge = "badge-pending" if pend else "badge-plain"
    root = _text(state.get("root"))
    return (
        '<header class="top">'
        '<div class="brand">agentflow 用户端'
        + (f' <span class="muted">/ {_e(crumb)}</span>' if crumb else "")
        + "</div>"
        f'<div class="sub">工作区根 <span class="mono">{_e(root)}</span></div>'
        '<div class="sub">'
        f'待回答 <span class="badge {badge}">{pend}</span> 条'
        f' · 最后更新 <span class="mono">{_e(state.get("generated_at"))}</span>'
        "</div>"
        "</header>"
    )


def _page(state: dict[str, Any], title: str, body: str, *, crumb: str = "") -> str:
    """套上骨架（`<style>` 内联：零外部请求、零 CDN、零 JS）。"""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n"
        f"<style>{STYLESHEET}</style>\n"
        "</head>\n<body>\n"
        + _top(state, crumb=crumb)
        + '<main class="wrap">' + body + "</main>\n"
        + "</body>\n</html>\n"
    )


def _option_html(qid: str, index: int, opt: dict[str, Any], multi: bool) -> str:
    """一个选项：label 加粗 + description 小字 + 单选/多选控件。"""
    kind = "checkbox" if multi else "radio"
    label = _text(opt.get("label"))
    desc = _text(opt.get("description"))
    value = _esc(label)
    body = f'<span class="label">{_e(label)}</span>'
    if desc:
        body += f'<span class="desc">{_e(desc)}</span>'
    return (
        '<label class="opt">'
        f'<input type="{kind}" name="selected" value="{value}">'
        f'<span class="kv">{body}</span>'
        "</label>"
    )


def _question_card(state: dict[str, Any], q: dict[str, Any]) -> str:
    """一条待答问题：一行两组读数 + 正文 + 选项 + 提交表单。"""
    qid = _text(q.get("qid"))
    sid = _text(q.get("sid"))
    opts = list(q.get("options") or [])
    multi = bool(q.get("multi"))
    ref = _text(state.get("generated_at"))
    ts = _text(q.get("ts"))
    head = _text(q.get("role")) or "（没写角色）"
    opts_html = "".join(
        _option_html(qid, i, o, multi) for i, o in enumerate(opts)
    ) or '<div class="note">这条问题没有给选项 —— 在下面「自定义回答」里写。</div>'
    # 卡片 id 必须带上会话号：qid 是「每段会话内」的编号（两段会话各有 q0001），
    # 只用 qid 会让两张不同的卡片共用一个锚点。
    card_id = f"q-{sid}-{qid}"
    return (
        '<section class="card card-ask" id="' + _e(card_id) + '">'
        '<div class="card-head">'
        f'<span class="caption">会话</span> <span class="mono">{_e(sid)}</span>'
        f'<span class="caption">问题号</span> <span class="mono">{_e(qid)}</span>'
        f'<span class="badge badge-unknown">等回答</span>'
        '<span class="spacer"></span>'
        f'<span class="readings">谁在问 <span class="mono">{_e(head)}</span>'
        f' · 问了多久 <span class="mono">{_e(_age(ts, ref))}</span>'
        f' · 落档时间 <span class="mono">{_e(ts) or "unknown"}</span></span>'
        "</div>"
        f'<div class="question">{_e(q.get("text"))}</div>'
        f'<div class="opts">{opts_html}</div>'
        f'<form class="answer" method="post" action="/answer">'
        f'<input type="hidden" name="qid" value="{_e(qid)}">'
        f'<input type="hidden" name="sid" value="{_e(sid)}">'
        f'<label class="caption" for="custom-{_e(qid)}">自定义回答（单选时覆盖选项，'
        "多选时作为补充；用「custom 优先」的口径读回）</label>"
        f'<textarea id="custom-{_e(qid)}" name="custom" rows="3" '
        'placeholder="想说的原话"></textarea>'
        '<div class="actions">'
        '<button class="btn btn-primary" type="submit">提交回答</button>'
        '<button class="btn btn-ghost" type="submit" name="skip" value="1">跳过此问题</button>'
        '<span class="readings">跳过 = 提交空的 selected（我们的回答口径），'
        "不是「没答」</span>"
        "</div>"
        "</form>"
        "</section>"
    )


def _run_row(state: dict[str, Any], run: dict[str, Any], *, highlight: bool) -> str:
    """一行运行态：两个独立读数 + 三态徽标 + 是否停在等谁。"""
    sid = _text(run.get("sid"))
    role = _text(run.get("role")) or "（没写角色）"
    stop = _text(run.get("stop_reason")) or "unknown"
    cls, word = _STOP_BADGES.get(stop, ("badge-plain", stop))
    waiting = bool(run.get("waiting"))
    if waiting:
        cls, word = "badge-pending", "停在等用户"
    usd = _usd(run.get("usd"))
    unknown_usd = run.get("unknown_usd") or 0
    qids = ", ".join(_text(x) for x in (run.get("waiting_on") or [])) or "（没有）"
    # 两个独立读数（DSH「行里给两个独立事实」）：
    #   读数甲「盘上最后一条事件是什么」= 会话文件尾那一条事件的 kind/形状，读者是文件本身；
    #   读数乙「这一页装载了多少条事件」= 这次渲染时读进来的条数（本趟 / 本会话两条）。
    # 两者读的不是同一个东西，所以它们对不上时正说明「盘在变」或「有坏行没读进来」。
    mine = run.get("events_in_run")
    whole = run.get("events_seen")
    if whole is None:
        whole = next((s.get("events_seen") for s in state.get("sessions") or []
                      if _text(s.get("sid")) == sid), None)
    last_shape = _text(run.get("last_shape")) or "unknown"
    mark = ' <span class="badge badge-plain">最近一趟</span>' if highlight else ""
    return (
        '<div class="row">'
        f'<a class="mono" href="/run/{quote(sid)}">{_e(sid)}</a>'
        f'<span class="mono">{_e(role)}</span>'
        f'<span class="badge {cls}">{_e(word)}</span>'
        + mark
        + '<span class="spacer"></span>'
        '<span class="readings">'
        f'步数 <span class="mono">{_num(run.get("steps"))}</span>'
        f' · 盘上最后一步形状 <span class="mono">{_e(last_shape)}</span>'
        f' · 这一页装载 <span class="mono">{_num(mine)}</span> 条（本趟）'
        f' / <span class="mono">{_num(whole)}</span> 条（本会话）'
        f' · llm 调用 <span class="mono">{_num(run.get("llm_calls"))}</span>'
        f' · 花销 <span class="mono">{_e(usd)}</span> USD'
        + (f'（{_num(unknown_usd)} 次算不出价钱）' if unknown_usd else "")
        + f' · 停在等 <span class="mono">{_e(qids)}</span>'
        "</span>"
        "</div>"
    )


def render_root(state: dict[str, Any]) -> str:
    """`GET /`：全局待回答面板 + 运行态（纯函数，同一份快照两次渲染逐字节相同）。"""
    pending = list(state.get("pending_questions") or [])
    runs = list(state.get("runs") or [])
    orphans = list(state.get("orphans") or [])
    last = state.get("last_run")
    # 台账（第二个独立读数）与坏行：先算好，正文按顺序拼
    ledger = state.get("ledger") or {}
    ledger_html = (
        '<div class="card"><div class="card-head">'
        '<span class="caption">台账（第二个独立读数）</span></div>'
        f'<div class="readings">台账事件 <span class="mono">'
        f'{_num(ledger.get("events"))}</span> 条'
        f' · 台账里的任务行 <span class="mono">{_num(ledger.get("tables"))}</span>'
        f' · 落点 <span class="mono">{_e(ledger.get("path"))}</span>'
        + (f' · {_e(ledger.get("note"))}' if ledger.get("note") else "")
        + "</div></div>"
    )
    problems = list(state.get("problems") or [])
    prob_html = ""
    if problems:
        items = "".join(f'<div class="row"><span class="mono">{_e(p)}</span></div>'
                        for p in problems)
        prob_html = ('<div class="card problem"><div class="card-head">'
                     '<span class="badge badge-fail">没查成</span>'
                     f'<span class="readings">{len(problems)} 条读盘问题'
                     "（不是「没有」，是「没读到」）</span></div>" + items + "</div>")
    if pending:
        ask_html = "".join(_question_card(state, q) for q in pending)
    else:
        ask_html = ('<div class="card"><span class="badge badge-plain">没有待回答</span>'
                    ' <span class="muted">盘上没有尚未回答的提问（合法初态，'
                    "不是「没查成」——同一份读数见下方运行态与 <code>/api/state</code>）。"
                    "</span></div>")
    by_sid: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_sid.setdefault(_text(run.get("sid")), []).append(run)
    run_blocks: list[str] = []
    for sid in sorted(by_sid):
        rows = "".join(
            _run_row(state, r, highlight=(last is not None and r is last))
            for r in by_sid[sid]
        )
        run_blocks.append(
            '<div class="card">'
            f'<div class="card-head"><span class="caption">会话</span>'
            f' <a class="mono" href="/run/{quote(sid)}">{_e(sid)}</a>'
            f'<span class="spacer"></span><span class="readings">'
            f'{len(by_sid[sid])} 趟</span></div>'
            f"{rows}</div>"
        )
    if not run_blocks:
        # 三态：一趟都没有 = 「还没有跑过」，不是「一趟 0 步的运行」，也不是「没查成」。
        run_blocks.append('<div class="card"><span class="badge badge-plain">还没有跑过'
                          "</span> <span class=\"muted\">盘上没有 "
                          "<code>agent_run_start</code> 事件 —— 这个工作区一次运行都"
                          "还没开始过（合法初态）。"
                          + (f"轮次之外另有 {len(orphans)} 条零散事件，见下一栏。"
                             if orphans else "")
                          + "</span></div>")
    orphan_html = ""
    summary = state.get("orphan_summary") or {}
    groups = list(summary.get("groups") or [])
    if groups:
        body_rows = []
        for g in groups:
            sid = _text(g.get("sid"))
            body_rows.append(
                '<div class="row">'
                f'<a class="mono" href="/run/{quote(sid)}">{_e(sid)}</a>'
                '<span class="badge badge-plain">没有开始标记</span>'
                '<span class="spacer"></span>'
                f'<span class="readings">{_num(g.get("count"))} 条'
                f' · 事件种类 <span class="mono">'
                f'{_e("、".join(_text(k) for k in (g.get("kinds") or [])))}</span>'
                f' · 第 <span class="mono">{_num(g.get("first_index"))}</span>'
                f'–<span class="mono">{_num(g.get("last_index"))}</span> 条'
                f' · <span class="mono">{_e(g.get("first_ts"))}</span> → '
                f'<span class="mono">{_e(g.get("last_ts"))}</span>'
                "</span></div>")
        orphan_html = (
            f'<h2 class="sec-title">轮次之外的零散事件 '
            f'<span class="readings">共 {_num(summary.get("count"))} 条</span></h2>'
            '<div class="card"><div class="readings">这些事件不在任何一趟的运行区间里'
            "（它们前面没有 <code>agent_run_start</code>）—— 典型来源是一次不带 "
            "<code>--sid</code> 的 CLI 调用写的台账事件，或者你刚提交、还没被下一趟读到"
            "的回答。它们不代表一次运行，所以不参与「最近一趟」与运行态计数。"
            "</div>" + "".join(body_rows) + "</div>")
    body = (
        f'<h2 class="sec-title">待回答（全局，不按会话过滤）'
        f' <span class="badge {"badge-unknown" if pending else "badge-plain"}">'
        f"{len(pending)}</span></h2>"
        '<div class="stack">' + ask_html + "</div>"
        f'<h2 class="sec-title">运行态 <span class="readings">共 {len(runs)} 趟 / '
        f'{len(by_sid)} 个会话'
        + ("（最近一趟：" + _e(_text(last.get("sid"))) + " / "
           + _e(_text(last.get("role")) or "（没写角色）") + "）"
           if isinstance(last, Mapping) else "（还没有跑过）")
        + "</span></h2>"
        '<div class="stack">' + "".join(run_blocks) + "</div>"
        + orphan_html
        + prob_html
        + ledger_html
        + '<h2 class="sec-title">怎么用</h2>'
        '<div class="card"><div class="readings">'
        "提交后是 PRG（303 回首页），刷新不会重复提交；"
        "回答落进会话记录的 <code>user_answer</code> 事件，"
        "下一趟运行会读到它。读数 JSON 在 <a href=\"/api/state\">/api/state</a>。"
        "</div></div>"
    )
    return _page(state, "agentflow 用户端 · 待回答与运行态", body)


def _event_card(index: int, event: Mapping[str, Any]) -> str:
    """把一条会话事件渲染成一张可回放的卡片（界面纪律，抄自 DSH：渲染已落盘的切片）。"""
    kind = _text(event.get("kind")) or "（没有 kind）"
    ts = _text(event.get("ts"))
    role = _text(event.get("role"))
    cls = "card"
    rows: list[str] = []
    if kind == "agent_run_start":
        rows.append(f'<div class="title">这一趟开始</div>')
        rows.append(f'<div class="clip">{_e(_clip(event.get("task"), 400))}</div>')
        rows.append(
            '<div class="readings">'
            f'角色 <span class="mono">{_e(role)}</span>'
            f' · 由谁发起 <span class="mono">{_e(event.get("summoned_by"))}</span>'
            f' · 深度 <span class="mono">{_num(event.get("depth"))}</span>'
            f' · 台账号 <span class="mono">{_e(event.get("task_id"))}</span>'
            f' · 提示词版本 <span class="mono">{_e(event.get("prompt_version"))}</span>'
            "</div>")
    elif kind == "llm_call":
        rows.append('<div class="title">模型调用摘要</div>')
        rows.append(
            '<div class="readings">'
            f'说明 <span class="mono">{_e(event.get("note"))}</span>'
            f' · 模型 <span class="mono">{_e(event.get("model"))}</span>'
            f' · 协议 <span class="mono">{_e(event.get("protocol"))}</span>'
            f' · 结果 <span class="mono">{"ok" if event.get("ok") else "fail"}</span>'
            f' · tokens in/out <span class="mono">{_num(event.get("tokens_in"))}'
            f"/{_num(event.get('tokens_out'))}</span>"
            f' · 花销 <span class="mono">{_e(_usd(event.get("usd")))}</span> USD'
            f' · 提示词 <span class="mono">{_num(event.get("prompt_chars"))}</span> 字'
            f' · 回文 <span class="mono">{_num(event.get("text_len"))}</span> 字'
            f' · 落档 <span class="mono">{_e(event.get("recorded")) or "ok"}</span>'
            "</div>")
        if event.get("problem"):
            rows.append(f'<div class="clip">problem: '
                        f'<span class="mono">{_e(event.get("problem"))}</span> — '
                        f'{_e(_clip(event.get("detail"), 300))}</div>')
    elif kind == "agent_step":
        shape = _text(event.get("shape")) or "unknown"
        cls = "card"
        rows.append(f'<div class="title">第 {_num(event.get("index"))} 步 · '
                    f'<span class="mono">{_e(shape)}</span></div>')
        rows.append(f'<div class="clip">问（payload）：'
                    f'<span class="mono">{_e(_clip(event.get("payload")))}</span></div>')
        rows.append(f'<div class="clip">答（result）：'
                    f'<span class="mono">{_e(_clip(event.get("result")))}</span></div>')
    elif kind == "user_question":
        cls = "card card-ask"
        rows.append('<div class="title">问用户</div>')
        rows.append(f'<div class="question">{_e(event.get("text"))}</div>')
        rows.append(
            '<div class="readings">'
            f'问题号 <span class="mono">{_e(event.get("qid"))}</span>'
            f' · 谁在问 <span class="mono">{_e(role)}</span>'
            f' · 超时 <span class="mono">{_num(event.get("timeout_sec"))}</span> 秒'
            "</div>")
        for opt in (event.get("options") or []):
            ov = option_view(opt)
            line = f'<span class="label">{_e(ov["label"])}</span>'
            if ov["description"]:
                line += f' <span class="desc">{_e(ov["description"])}</span>'
            rows.append(f'<div class="row">{line}</div>')
    elif kind == "user_answer":
        rows.append('<div class="title">用户回答</div>')
        rows.append(f'<div class="question">{_e(answer_text_of(event))}</div>')
        rows.append(
            '<div class="readings">'
            f'问题号 <span class="mono">{_e(event.get("qid"))}</span>'
            f' · 谁答的 <span class="mono">{_e(event.get("by")) or "user"}</span>'
            f' · 迟到 <span class="mono">{_e(event.get("late"))}</span>'
            f' · selected <span class="mono">'
            f'{_e(_clip(event.get("selected"), 200))}</span>'
            f' · custom <span class="mono">'
            f'{_e(_clip(event.get("custom"), 200))}</span>'
            "</div>")
    elif kind == "agent_run_end":
        stop = _text(event.get("stop_reason")) or "unknown"
        bcls, word = _STOP_BADGES.get(stop, ("badge-plain", stop))
        cls = "card"
        rows.append(f'<div class="title">这一趟结束 '
                    f'<span class="badge {bcls}">{_e(word)}</span></div>')
        rows.append(
            '<div class="readings">'
            f'停止理由 <span class="mono">{_e(stop)}</span>'
            f' · 步数 <span class="mono">{_num(event.get("steps"))}</span>'
            f' · 召唤 <span class="mono">{_num(event.get("summons"))}</span>'
            f' · 消息 <span class="mono">{_num(event.get("messages"))}</span>'
            f' · 交付说明 <span class="mono">{_num(event.get("final_chars"))}</span> 字'
            f' · 耗时 <span class="mono">{_num(event.get("elapsed_sec"))}</span> 秒'
            "</div>")
        rows.append(f'<div class="clip">{_e(_clip(event.get("final"), 600))}</div>')
    else:
        rows.append(f'<div class="title">{_e(kind)}</div>')
        rows.append(f'<div class="clip">{_e(_clip(event, 600))}</div>')
    return (
        f'<section class="{cls}">'
        '<div class="card-head">'
        f'<span class="mono">#{index}</span>'
        f'<span class="caption">{_e(kind)}</span>'
        f'<span class="spacer"></span>'
        f'<span class="readings mono">{_e(ts) or "unknown"}</span>'
        "</div>" + "".join(rows) + "</section>"
    )


def render_run(root: str | Path, sid: str, state: dict[str, Any]) -> tuple[int, str]:
    """`GET /run/<sid>`：一趟的详情（事件卡片 + 交付说明）。返回 `(状态码, HTML)`。"""
    root_p = Path(str(root))
    if not _sid_ok(sid):
        return 404, _page(state, "没有这个会话", _not_found(state, f"会话号不安全：{sid}"))
    path = SS.session_path(root_p, sid)
    if not path.is_file():
        return 404, _page(state, "没有这个会话",
                          _not_found(state, f"会话文件不在盘上：{sid}"))
    events, problems = SS.read_session(root_p, sid=sid)
    cards = "".join(_event_card(i, e) for i, e in enumerate(events, 1))
    if not cards:
        cards = ('<div class="card"><span class="badge badge-plain">这一趟还没有事件'
                 '</span> <span class="muted">文件在盘上，但一条事件都没有。</span></div>')
    rstatus, rtext = _read_report(root_p)
    if rstatus == "ok":
        report = (f'<div class="card"><div class="card-head">'
                  f'<span class="caption">交付说明</span>'
                  f'<span class="spacer"></span><span class="readings mono">'
                  f'{_e("/".join(REPORT_REL))} · {len(rtext)} 字</span></div>'
                  f"<pre>{_e(rtext)}</pre></div>")
    elif rstatus == "missing":
        report = ('<div class="card"><div class="card-head">'
                  '<span class="badge badge-unknown">没查到</span>'
                  '<span class="readings">交付说明不在盘上：'
                  f'<span class="mono">{_e("/".join(REPORT_REL))}</span>'
                  "（合法初态：这一趟还没写）</span></div></div>")
    else:
        report = ('<div class="card problem"><div class="card-head">'
                  '<span class="badge badge-fail">没查成</span>'
                  f'<span class="readings">交付说明读不出来：{_e(rtext)}'
                  "（不是「没有」，是「没读到」）</span></div></div>")
    prob_html = ""
    if problems:
        prob_html = ('<div class="card problem"><div class="card-head">'
                     f'<span class="badge badge-fail">坏行 {len(problems)} 条</span></div>'
                     + "".join(f'<div class="row"><span class="mono">{_e(p)}</span></div>'
                               for p in problems) + "</div>")
    body = (
        '<div class="card"><div class="card-head">'
        f'<span class="caption">会话</span> <span class="mono">{_e(sid)}</span>'
        '<span class="spacer"></span>'
        f'<span class="readings">读盘读数：本会话 <span class="mono">'
        f'{len(events)}</span> 条事件 · 坏行 <span class="mono">{len(problems)}</span> 条'
        f' · 文件 <span class="mono">{_e(str(path))}</span></span>'
        "</div>"
        '<div class="readings">'
        f'盘上最后一条事件 <span class="mono">'
        f'{_e(_text(events[-1].get("kind")) if events else "unknown")}</span>'
        f" · 这一页读到 <span class=\"mono\">{len(events)}</span> 条"
        "（两个独立读数：一个来自文件尾，一个来自这次装载）</div>"
        "</div>"
        + prob_html
        + report
        + f'<h2 class="sec-title">事件回放 <span class="readings">共 {len(events)} 条</span>'
        "</h2>"
        '<div class="stack">' + cards + "</div>"
    )
    return 200, _page(state, f"agentflow · 会话 {sid}", body, crumb=sid)


def _not_found(state: dict[str, Any], why: str) -> str:
    """404 的正文（说清是什么没找到，不是把 404 折成空页）。"""
    return ('<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">404</span>'
            f'<span class="readings">{_e(why)}</span></div>'
            '<div class="readings">回到 <a href="/">首页</a> 看全局待回答与运行态。</div>'
            "</div>")
