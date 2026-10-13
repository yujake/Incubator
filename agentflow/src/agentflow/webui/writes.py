# -*- coding: utf-8 -*-
"""用户端 Web 界面的写路径（四个端点 + 授权 + 审计）。

## 这一层是什么

`answer(root, form)` —— 从 `webui.py` 的 `answer` 原样搬来、只改了个名字
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

## W3/W4 在这一层加了什么（裁定 C2 / D2 / E1 / I1）

三件新的写端点，每一件都走既有的闸门、不另写一条写路径：

| 端点 | 既有闸门（出处） |
|---|---|
| `POST /api/stop` | `stopctl.request_stop_detail`（`stopctl.py:65`）· 强制停再走 `stopctl.kill_registered`（`stopctl.py:392`） |
| `POST /api/submit` | `interactions.next_prefixed_id`（`interactions.py:1233`）＋ `store.tx`（`store.py:890`）＋ `SearchRequest.validate`（`schema.py:243`） |
| `POST /api/settings` | `settings.write_settings`（本批新增，见 `settings.py`）—— 它自己就是那条唯一写入口 |

`/api/task` 不做（裁定 I1：`userio` 里没有"用户 → M 留言"这条通道，
硬做等于在权限面之外开一条写路径）。

`POST /answer` 的行为一个字不改（它由 A 线 `server.py` 的 `handle_answer` 调
:func:`answer`）：它的闸门就是 `userio.answer_question`，`draft/73` §2.5 那一行
逐字写着"现状，不动"。所以本模块只给它补审计（写一行 `web-actions.jsonl`），
不改它的状态码、不改它的正文 —— `tests/test_webui.py` 那 21 条靠的就是这一点。

新端点的授权矩阵（裁定 C2）按 `draft/74` §4 的口径三层，次序即下面的检查次序：
回环来源 ⇒ CSRF（`X-CSRF-Token`，与 `index.html` 里注入的每进程令牌比对）⇒
`allow_writes`（`agentflow web --allow-writes`，W0 已透传到句柄上）。
`/api/settings` 另加一层 `settings_write`（`--no-settings-write` 关掉它）。

三态与状态码（失败不许折成 200）：

| 情形 | 码 | `WriteResult.tri` |
|---|---|---|
| 写成了 | 200 | `computed` |
| 未开写面 / CSRF 不对 / 非回环来源 | 403 | `not_applicable` |
| 缺 `confirm=1` / 参数不合法（整批不写） | 400 | `not_applicable` |
| 闸门抛异常或结局说不清 | 500 | `unreadable` |

每一次到达本模块处理器的写尝试（含被拒的）都追加一行
`<工作区>/web-actions.jsonl`（裁定 D2，实现见 :mod:`agentflow.webui.audit`）。
一处说清楚的例外：未注册的 `/api/*` 路径由 A 线 `server.py` 直接回 JSON 404，
请求走不到这里 ⇒ 那一类 404 不在台账里（它不是一次"写尝试"，是一次"没有这条路"）。
"""

from __future__ import annotations

import secrets
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Mapping, Sequence

from .. import budget as B
from .. import interactions as X
from .. import schema as S
from .. import sessions as SS
from .. import settings as SET
from .. import stopctl as SC
from .. import userio as U
from ..store import Store
from . import audit
from .state import _clip, _e, _sid_ok, _text, answer_text_of, snapshot

__all__ = ["HANDLERS", "MISSING_TYPES", "PENDING_ENDPOINTS", "ROUTES",
           "UNCHECKED_TYPES", "answer", "authorize", "handle_budget", "handle_settings",
           "handle_stop",
           "handle_submit", "type_decls"]

#: 处理器的落点（与 `readers.py`/`sse.py` 同一条约定）：键 = `ROUTES` 第三元素，
#: 值 = `(handler, params, query)` 签名的函数、`handler` 是 `WebHandler` 实例。
#: `/answer` 由 `WebHandler` 自己的方法实现（W0 从单文件搬过来的那一支）；
#: C 线新加的三条写端点把 handler 放这里 —— 于是不必去改 A 线的 `server.py`。
HANDLERS: dict[str, Any] = {}

#: 契约判据 C 的欠账登记（`{接口名: 理由}`）：本模块声明、但夹具上还读不出键的接口。
UNCHECKED_TYPES: dict[str, str] = {}

#: 契约判据 D 的例外面（`{端点: 理由}`）：声明了但后端还没落地的写端点。落地后删掉。
#: 本批三条写端点都已注册 ⇒ 这张表保持空（判据 D 的反向断言要求"落地即撤销"）。
PENDING_ENDPOINTS: dict[str, str] = {}

#: 本模块挂到总路由表上的写端点：`(method, path 模式, 处理器名字)`。
#: 总表是 `webui/routes.py` 拼出来的（`自有 + READER_ROUTES + WRITE_ROUTES`），
#: 所以 C 线加端点改的是这一行，不用去碰 A 线的文件（`draft/78 §3` 的接缝）。
#:
#: `/answer` 那一行仍指向 A 线 `WebHandler.handle_answer`（`server._invoke` 先找方法、
#: 再找子表）：它的行为与状态码一个字都不许变（`tests/test_webui.py` 里 21 条钉着），
#: 所以它不进 C 线的授权矩阵 —— `draft/73` §2.5 给它的闸门栏逐字是"现状，不动"。
#: C 只给它补审计（`answer()` 里那一笔）。
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/answer", "handle_answer"),
    ("POST", "/api/stop", "handle_stop"),
    ("POST", "/api/submit", "handle_submit"),
    ("POST", "/api/settings", "handle_settings"),
    # 业主 2026-10-12 的预算窗口：追加 / 重设额度（写面，走同一套授权、
    # CSRF、审计与 `confirm=1`）。
    ("POST", "/api/budget", "handle_budget"),
    ("POST", "/api/run", "handle_start_run"),
    ("POST", "/api/task", "handle_interject"),
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


# ====================================================================== 授权（裁定 C2）
#: 三态词表（与 `readers.TRI_*` / `types.ts` 的 `Tri` 同一套；字符串不许互相顶替）。
TRI_COMPUTED = "computed"
TRI_NOT_APPLICABLE = "not_applicable"
TRI_UNREADABLE = "unreadable"

#: 认作"本机"的主机名（来源校验用）。`0.0.0.0` / `::` 是绑定地址，也放进来：
#: 服务确实可能绑在它们上面，而来源地址那一道仍然会拦掉真正的外来连接。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0", "::"})

_TRI_FOR_CODE = {403: TRI_NOT_APPLICABLE, 400: TRI_NOT_APPLICABLE, 500: TRI_UNREADABLE}


def _host_of(value: str) -> str:
    """从一个 `Host` / `Origin` 头的取值里取出主机部分（去掉端口，保留方括号）。

    两种形状都要认：`Host` 是一个 authority（`127.0.0.1:8788`），
    `Origin` 是一个完整 URL（`http://evil.example:8080`）。只按冒号切会让
    `http://evil.example` 被读成主机 `http`（一个既不是回环、也不会被认出来的怪值），
    所以带 scheme 的一律交给 `urlparse`。
    """
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        try:
            parsed = urllib.parse.urlparse(raw)
        except ValueError:
            return raw
        return str(parsed.hostname or parsed.netloc or raw)
    if raw.startswith("["):                     # `[::1]:8788`
        end = raw.find("]")
        return raw[:end + 1] if end != -1 else raw
    if raw.count(":") == 1:                     # `127.0.0.1:8788`
        return raw.split(":", 1)[0]
    return raw


def _source_of(handler: Any) -> tuple[str, str]:
    """这次请求的来源（进台账那一栏），以及"它是不是回环"。

    返回 `(来源, 问题)`：问题非空 = 拒。三处都看：`Origin`（跨站 POST 会带）、
    `Host`、以及 socket 对端地址 —— 只看一处会漏掉另一处能伪造的那一格。
    """
    client = ""
    addr = getattr(handler, "client_address", None)
    if isinstance(addr, (tuple, list)) and addr:
        client = str(addr[0])
    headers = handler.headers
    for label, raw in (("Origin", headers.get("Origin", "")),
                       ("Host", headers.get("Host", ""))):
        host = _host_of(raw)
        if host and host not in _LOOPBACK_HOSTS:
            return client or host, f"{label} 不是回环地址（{host}）—— 写面只对本机开"
    if client and client not in _LOOPBACK_HOSTS:
        return client, f"对端地址不是回环（{client}）—— 写面只对本机开"
    return client or _host_of(headers.get("Host", "")) or "unknown", ""


def _csrf_ok(handler: Any) -> bool:
    """CSRF 令牌对不对。没挂令牌 ⇒ 一律拒（fail-closed，不是"没令牌就放行"）。"""
    want = str(getattr(handler, "csrf_token", "") or "")
    if not want:
        return False
    got = str(handler.headers.get("X-CSRF-Token", "") or "").strip()
    return bool(got) and secrets.compare_digest(got, want)


def authorize(handler: Any, *, endpoint: str,
              need_settings: bool = False) -> tuple[bool, int, str]:
    """写面的授权矩阵（裁定 C2）：`(放行吗, 状态码, 理由)`。次序即 `draft/74` §4。

    1. 回环来源（跨站来源一律拒）；
    2. CSRF 令牌（写请求必须带 `X-CSRF-Token`，值来自每进程的注入令牌）；
    3. `allow_writes`（`agentflow web --allow-writes`；缺省只读）；
    4. 只有 `/api/settings` 才要的第 4 层：`settings_write`（`--no-settings-write`）。

    为什么第 3 条要放在 CSRF 之后：`draft/74` §4 那一行逐字是"回环来源校验 →
    CSRF → `allow_writes` 开关"。次序不改变状态码（都是 403），改变的是理由，
    而理由要进审计台账 —— 审计读的是"为什么被拒"，写错一档就查不出来。
    """
    _source, why = _source_of(handler)
    if why:
        return False, 403, f"{endpoint}：{why}"
    if not _csrf_ok(handler):
        return False, 403, (f"{endpoint}：CSRF 令牌不对或没带"
                            "（写请求必须带 X-CSRF-Token）")
    if not bool(getattr(handler, "allow_writes", False)):
        return False, 403, (f"{endpoint}：写面没开 —— 要用 "
                            "`agentflow web --allow-writes` 才允许写")
    if need_settings and not bool(getattr(handler, "settings_write", True)):
        return False, 403, f"{endpoint}：设置写面被 --no-settings-write 关掉了"
    return True, 200, ""


# ====================================================================== 复用的小件
def _one(form: Mapping[str, Sequence[str]], name: str) -> str:
    """取表单里某个字段的第一个值（没有就给空串 —— 字段缺失是常态，不是错误）。"""
    vals = form.get(name) or []
    return _text(vals[0]) if vals else ""


def _flag(form: Mapping[str, Sequence[str]], name: str) -> bool:
    """取一个布尔表单字段（`1` / `true` / `on` / `yes` 都算真）。"""
    return _one(form, name).strip().lower() in {"1", "true", "on", "yes"}


def _finish(handler: Any, *, endpoint: str, source: str, params: Mapping[str, Any],
            code: int, result: str, ok: bool, ident: str = "",
            extra: Mapping[str, Any] | None = None, tri: str = "") -> dict[str, Any]:
    """记一行审计、回一支 `WriteResult`，并把这一支返回给调用方（判据要比对它）。

    审计与回执必须同时发生：写成功了却没审计上是一个必须说出口的状态，
    所以台账的结局（`computed` / `unreadable`）原样带进 `extra.audit`，
    而它不冒充这次写的结局（`tri` 说的是写本身）。

    `tri` 显式给了就用它（设置那一支的三态来自 `write_settings` 自己的词表，
    不能由状态码反推）；缺省按状态码推。返回值与发出去的正文是同一支：
    这里先定 `tri` 再 `_json`，不许"发一份、返回另一份"。
    """
    tri = tri or (TRI_COMPUTED if ok else _TRI_FOR_CODE.get(code, TRI_NOT_APPLICABLE))
    row, problem = audit.record_action(handler.root, endpoint=endpoint, source=source,
                               params=params, result=result, tri=tri, ok=ok, http=code)
    body: dict[str, Any] = {"ok": ok, "tri": tri, "reason": result}
    if ident:
        body["id"] = ident
    out_extra: dict[str, Any] = dict(extra or {})
    out_extra["audit"] = {
        "tri": TRI_UNREADABLE if problem else TRI_COMPUTED,
        "path": str(audit.actions_path(handler.root)),
        "params_sha256": str(row.get("params_sha256") or ""),
    }
    if problem:
        out_extra["audit"]["problem"] = problem
    body["extra"] = out_extra
    handler._json(code, body)
    return body


# ====================================================================== 三个新端点
def handle_stop(handler: Any, params: Mapping[str, str],
                query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/stop`：写停机开关（优雅停），`force=1` 再走 `kill_registered`。

    两个动作都是不可逆的，所以 `confirm=1` 是硬要求（`draft/75` §1.1 第 8 行的
    请求字段栏逐字有它）：缺确认 ⇒ 400，什么都不动。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    source, _why = _source_of(handler)
    reason = _one(form, "reason").strip() or SC.DEFAULT_REASON
    force = _flag(form, "force")
    seen = {"reason": reason, "force": force, "confirm": _flag(form, "confirm")}
    allowed, code, why = authorize(handler, endpoint="POST /api/stop")
    if not allowed:
        return _finish(handler, endpoint="/api/stop", source=source, params=seen,
                       code=code, result=f"拒绝：{why}", ok=False)
    if not _flag(form, "confirm"):
        return _finish(handler, endpoint="/api/stop", source=source, params=seen, code=400,
                       result=("拒绝：叫停不可逆，必须带 confirm=1 一次显式确认"
                               "（draft/75 §1.1 第 8 行）"), ok=False)
    try:
        payload, outcome = SC.request_stop_detail(root, reason=reason, by="web", force=force)
    except Exception as exc:  # noqa: BLE001 - 失败不许折成 200
        return _finish(handler, endpoint="/api/stop", source=source, params=seen, code=500,
                       result=(f"停机开关没写成：{type(exc).__name__}: {exc}"
                               "（盘上那一份没被动过）"), ok=False)
    extra: dict[str, Any] = {"outcome": outcome, "stop": payload, "force": force}
    if outcome == "created":
        result = f"已叫停：写下停机开关（reason={reason}）"
    elif outcome == "upgraded":
        result = "已叫停：盘上已有的停机开关被这次请求升级为 force"
    else:
        # 幂等那一档必须说清楚"这次没改动盘上任何东西"，否则读回执的人会以为
        # 是自己这一下按停的（三态纪律：说清是哪一态，不许折成一句"停好了"）。
        result = (f"停机开关已经在盘上（{_text(payload.get('by')) or '?'} 先叫停的，"
                  f"reason={_text(payload.get('reason'))}）—— 这次没有改动它")
    if force:
        try:
            killed = SC.kill_registered(root)
        except Exception as exc:  # noqa: BLE001 - 杀失败要如实报，不许静默
            killed = {"problem": f"{type(exc).__name__}: {exc}"}
        extra["killed"] = killed
        result += f"；强制停：杀 {killed.get('killed', 'unknown')} 个在册进程"
    return _finish(handler, endpoint="/api/stop", source=source, params=seen, code=200,
                   result=result, ok=True, ident=_text(payload.get("path")), extra=extra)


def handle_submit(handler: Any, params: Mapping[str, str],
                  query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/submit`：往 `search_requests` 入队一条检索请求。

    不走 `interactions.admit_search_request`（`interactions.py:1125`）：那是 I7 的
    准入配额闸门，它管的是"A 领跑那一刻放不放行"，不是"入队这一刻"
    （这条曾经写错过，更正见 `draft/73` §2.5 的表格与 `draft/74` §0.2）。
    入队这一条路与 `cli.cmd_submit`（`cli.py:103`）逐条同源：取号
    `next_prefixed_id` → `SearchRequest.validate()` → `store.tx` 里 upsert。

    参数不合法 ⇒ 整批不写 + 400（事务是"异常即不提交"，所以这里 catch 之后
    可以如实说"什么都没写"）。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    source, _why = _source_of(handler)
    topic = _one(form, "topic").strip()
    mode = _one(form, "mode").strip() or "topical"
    content = _one(form, "content")
    providers = [_text(x).strip() for x in (form.get("providers") or []) if _text(x).strip()]
    seen = {"topic": topic, "mode": mode, "content": content, "providers": providers,
            "confirm": _flag(form, "confirm")}
    allowed, code, why = authorize(handler, endpoint="POST /api/submit")
    if not allowed:
        return _finish(handler, endpoint="/api/submit", source=source, params=seen,
                       code=code, result=f"拒绝：{why}", ok=False)
    if not _flag(form, "confirm"):
        return _finish(handler, endpoint="/api/submit", source=source, params=seen, code=400,
                       result=("拒绝：入队一条检索请求要 confirm=1 一次显式确认"
                               "（ConfirmButton 的落点）"), ok=False)
    if not topic:
        return _finish(handler, endpoint="/api/submit", source=source, params=seen, code=400,
                       result="拒绝：topic 不能为空（整批未写入）", ok=False)
    store = Store(root)
    store.init()
    rid = ""
    try:
        with store.tx("search_requests", actor="web", note="web-submit") as tx:
            rows = tx.rows("search_requests")
            rid = X.next_prefixed_id(rows, "request_id", "r")
            row = S.SearchRequest(request_id=rid, timestamp=S.now_iso(), topic=topic,
                                  mode=mode, content_description=content,
                                  submitted_by="web", providers=list(providers))
            row.validate()
            tx.upsert("search_requests", row.to_dict(), note="submitted")
    except (ValueError, TypeError, KeyError) as exc:
        return _finish(handler, endpoint="/api/submit", source=source, params=seen, code=400,
                       result=(f"拒绝：请求不合法，整批未写入 —— "
                               f"{type(exc).__name__}: {exc}"), ok=False)
    except Exception as exc:  # noqa: BLE001 - 结局说不清 ⇒ unreadable，不折成成功
        return _finish(handler, endpoint="/api/submit", source=source, params=seen, code=500,
                       result=(f"入队没成：{type(exc).__name__}: {exc}"
                               "（事务未提交，盘上那份没被动过）"), ok=False)
    return _finish(handler, endpoint="/api/submit", source=source, params=seen, code=200,
                   result=(f"已入队 {rid}（topic={topic} · mode={mode}）"),
                   ok=True, ident=rid)


def handle_settings(handler: Any, params: Mapping[str, str],
                    query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/settings`：写机器级设置文件（`settings.write_settings`）。

    表单键是 `toolchain.lean_bin` 这种"段.键"形状（`draft/75` §1.1 第 10 行的
    请求字段栏）。key 只写不读（裁定 E1）：真 key 落盘，回执里恒为 `***`。

    词表映射（裁定 N1：两套字符串不许互相顶替）：
    `write_settings` 给的是 `written / refused / unknown`（`draft/73` §2.5 给这一格
    定的那一套），这里映射成 `WriteResult.tri` 的
    `computed / not_applicable / unreadable`，并把本词原样留在 `extra.settings_tri`。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    source, _why = _source_of(handler)
    values: dict[str, dict[str, str]] = {}
    for raw_key, vals in form.items():
        if "." not in str(raw_key):
            continue                      # confirm 之类的顶层字段不进设置
        section, key = str(raw_key).split(".", 1)
        values.setdefault(section, {})[key] = _text(vals[0]) if vals else ""
    allowed, code, why = authorize(handler, endpoint="POST /api/settings",
                                   need_settings=True)
    if not allowed:
        return _finish(handler, endpoint="/api/settings", source=source, params=values,
                       code=code, result=f"拒绝：{why}", ok=False)
    if not _flag(form, "confirm"):
        return _finish(handler, endpoint="/api/settings", source=source, params=values,
                       code=400,
                       result=("拒绝：写设置要 confirm=1 一次显式确认"
                               "（覆盖 key 是不可逆动作）"), ok=False)
    got = SET.write_settings(values)
    settings_tri = str(got.get("tri") or "unknown")
    mapped = {"written": TRI_COMPUTED, "refused": TRI_NOT_APPLICABLE,
              "unknown": TRI_UNREADABLE}.get(settings_tri, TRI_UNREADABLE)
    http = {"written": 200, "refused": 400, "unknown": 500}[settings_tri]
    # 回执里的三段读数来自 `write_settings`（它保证 `model.api_key` 恒为掩码）；
    # 这里原样带出去，不另拼一份（第二份就是漂移的起点）。
    extra = {"settings_tri": settings_tri, "values": got.get("values") or {},
             "permissions": got.get("permissions") or {}}
    # 三态由 `write_settings` 的词表映射而来（不由状态码反推），所以显式传进去 ——
    # 发出去的正文与这里返回的字典必须是同一支。
    return _finish(handler, endpoint="/api/settings", source=source, params=values,
                   code=http, result=str(got.get("reason") or ""),
                   ok=bool(got.get("ok")), ident=str(got.get("path") or ""),
                   extra=extra, tri=mapped)


def handle_budget(handler: Any, params: Mapping[str, str],
                  query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/budget`：追加一笔额度（`action=add`）或重设总额（`action=set`）。

    业主 2026-10-12：「用户可追加预算，运行消耗的钱从总预算里实时扣除」。
    这一条端点是那句话的台面落点 —— 运行中途点一下，下一个花钱之前的闸门
    （`llmseam.budget_limit`）就现读到新上限（`budget` 模块的 docstring 逐字解释了
    为什么这件事必须走盘上寄存器而不是一个内存参数）。

    请求字段：`action`（`add` / `set`，缺省 `add`）· `usd` · `note?` · `by?` ·
    `confirm=1`。确认是硬要求：改预算会改到"这一趟还能不能继续花钱"，
    与停机同一档（`draft/75` §1.1 第 8 行的口径）。

    三态：`budget.add_usd` / `write_initial` 的回执只有两档（`ok` 与非 `ok` + 原因），
    而"寄存器读不出来"那一档在回执里是拒绝（它算得出基数才算得对），
    于是这里把 `ok=False` 一律映射成 400 + `not_applicable`
    （"查过了、这次没写成"，不是"没查成"——盘上那一份没被动过，这是查得清的）。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    source, _why = _source_of(handler)
    action = (_one(form, "action").strip() or "add").lower()
    raw_usd = _one(form, "usd").strip()
    note = _one(form, "note")
    by = _one(form, "by").strip() or "web"
    seen = {"action": action, "usd": raw_usd, "note": note, "by": by,
            "confirm": _flag(form, "confirm")}
    allowed, code, why = authorize(handler, endpoint="POST /api/budget")
    if not allowed:
        return _finish(handler, endpoint="/api/budget", source=source, params=seen,
                       code=code, result=f"拒绝：{why}", ok=False)
    if not _flag(form, "confirm"):
        return _finish(handler, endpoint="/api/budget", source=source, params=seen, code=400,
                       result=("拒绝：改预算要 confirm=1 一次显式确认"
                               "（它改的是这一趟还能不能继续花钱）"), ok=False)
    if action not in ("add", "set"):
        return _finish(handler, endpoint="/api/budget", source=source, params=seen, code=400,
                       result=f"拒绝：action 只认 add / set（收到 {action!r}）", ok=False)
    if raw_usd == "":
        return _finish(handler, endpoint="/api/budget", source=source, params=seen, code=400,
                       result="拒绝：usd 不能为空", ok=False)
    try:
        amount = float(raw_usd)
    except (TypeError, ValueError):
        return _finish(handler, endpoint="/api/budget", source=source, params=seen, code=400,
                       result=f"拒绝：usd 读不成数字（收到 {raw_usd!r}）", ok=False)
    got = (B.add_usd(root, amount, by=by, note=note) if action == "add"
           else B.write_initial(root, amount, by=by, note=note))
    ok = bool(got.get("ok"))
    return _finish(handler, endpoint="/api/budget", source=source, params=seen,
                   code=200 if ok else 400,
                   result=(f"已{'追加' if action == 'add' else '重设'}额度："
                           f"总额现在是 ${float(got.get('total_usd') or 0.0):.6f}"
                           if ok else f"没写成：{got.get('reason') or '（没给理由）'}"),
                   ok=ok, ident=str(got.get("path") or ""),
                   extra={"action": action, "total_usd": got.get("total_usd"),
                          "entry": got.get("entry") or {},
                          "added_count": got.get("added_count"),
                          "history_lost": got.get("history_lost") or ""})


HANDLERS.update({
    "handle_stop": handle_stop,
    "handle_submit": handle_submit,
    "handle_settings": handle_settings,
    "handle_budget": handle_budget,
})


# ---------------------------------------------------------------- 网页上"说话"的两处


def _run_argv(root: Path, task: str) -> list[str]:
    """起一趟要跑的那条命令行（判据拿它比对；`dry_run` 也回它）。"""
    return [sys.executable, "-B", "-m", "agentflow", "--root", str(root),
            "run-agent", S.CONDUCTOR_ROLE, "--task", task, "--subagents"]


def _spawn_run(root: Path, task: str) -> tuple[int, str]:
    """真起一趟：detached 子进程，stdout/stderr 追加进 `runs/web-run-*.log`。

    为什么 detached 而不是在服务进程里跑：一趟是几十分钟的模型循环，跟着网页进程生灭
    会把"用户关掉标签页"变成"任务被杀"。日志落到项目自己的 `runs/` 下，网页的"在飞"页
    与 `sessions/` 照样读得到它。
    """
    import os
    import subprocess
    from datetime import datetime

    runs = root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    log = runs / f"web-run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    handle = open(log, "ab")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(_run_argv(root, task), cwd=str(root), env=env,
                            stdout=handle, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=flags,
                            close_fds=True)
    return int(proc.pid), str(log.relative_to(root)).replace("\\", "/")


def handle_start_run(handler: Any, params: Mapping[str, str],
               query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/run`：用一句话起一趟工作流（等价 CLI 的 `run-agent M --task …`）。

    请求字段：`task`（要系统做的那件事，一句话）· `confirm=1` · `dry_run?`。
    三态：没开写面 / CSRF 不对 ⇒ 403；任务为空 / 缺 confirm ⇒ 400（一个字节都不写）；
    起不来 ⇒ 500 并原样给错误；起来了 ⇒ 200 + `{pid, log, argv}`。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    source, _why = _source_of(handler)
    task = _one(form, "task").strip()
    dry = _flag(form, "dry_run")
    seen = {"task": task, "dry_run": dry, "confirm": _flag(form, "confirm")}
    allowed, code, why = authorize(handler, endpoint="POST /api/run")
    if not allowed:
        return _finish(handler, endpoint="/api/run", source=source, params=seen,
                       code=code, result=f"拒绝：{why}", ok=False)
    if not task:
        return _finish(handler, endpoint="/api/run", source=source, params=seen, code=400,
                       result="拒绝：任务不能为空 —— 它就是你要对系统说的那一句话", ok=False)
    if not _flag(form, "confirm"):
        return _finish(handler, endpoint="/api/run", source=source, params=seen, code=400,
                       result="拒绝：起一趟会真的花预算，必须带 confirm=1 一次显式确认", ok=False)
    argv = _run_argv(root, task)
    if dry:
        return _finish(handler, endpoint="/api/run", source=source, params=seen, code=200,
                       result="试运行：没有起任何进程（argv 见 extra）", ok=True,
                       extra={"argv": argv, "dry_run": True})
    try:
        pid, log = _spawn_run(root, task)
    except Exception as exc:  # noqa: BLE001 - 起不来要如实报，不许静默
        return _finish(handler, endpoint="/api/run", source=source, params=seen, code=500,
                       result=f"起不来：{type(exc).__name__}: {exc}", ok=False,
                       extra={"argv": argv})
    return _finish(handler, endpoint="/api/run", source=source, params=seen, code=200,
                   result=f"已起一趟（pid={pid}）—— 去「在飞」页看它",
                   ok=True, ident=log,
                   extra={"pid": pid, "log": log, "argv": argv})


def handle_interject(handler: Any, params: Mapping[str, str],
                query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/task`：**往正在跑的那一趟插话**（只有用户能发、只有 M 收）。

    请求字段：`body`（要说的话）· `subject?` · `sid?` · `confirm=1` · `dry_run?`。
    送达方式由 `agent_loop.send_interjection` 定义：下一步开头单列一段【插话】，
    **不打断当前步**；写进会话事件流（`agent_interjection`），所以盘上可复查。
    """
    del params, query
    from .. import agent_loop as AL
    from .. import userio as U

    form = handler._form()
    root = Path(handler.root)
    source, _why = _source_of(handler)
    body = _one(form, "body").strip()
    subject = _one(form, "subject").strip() or "用户插话"
    sid = _one(form, "sid").strip()
    dry = _flag(form, "dry_run")
    seen = {"body": body, "subject": subject, "sid": sid, "dry_run": dry,
            "confirm": _flag(form, "confirm")}
    allowed, code, why = authorize(handler, endpoint="POST /api/task")
    if not allowed:
        return _finish(handler, endpoint="/api/task", source=source, params=seen,
                       code=code, result=f"拒绝：{why}", ok=False)
    if not body:
        return _finish(handler, endpoint="/api/task", source=source, params=seen, code=400,
                       result="拒绝：插话内容不能为空", ok=False)
    if not _flag(form, "confirm"):
        return _finish(handler, endpoint="/api/task", source=source, params=seen, code=400,
                       result="拒绝：插话会改变正在跑的那一趟的做法，必须带 confirm=1", ok=False)
    if dry:
        return _finish(handler, endpoint="/api/task", source=source, params=seen, code=200,
                       result="试运行：没有写任何一条插话", ok=True, extra={"dry_run": True})
    try:
        iid, problem = AL.send_interjection(root, sender=U.USER, subject=subject,
                                            body=body, sid=(sid or None))
    except Exception as exc:  # noqa: BLE001 - 写失败不许折成 200
        return _finish(handler, endpoint="/api/task", source=source, params=seen, code=500,
                       result=f"没写成：{type(exc).__name__}: {exc}", ok=False)
    if problem:
        return _finish(handler, endpoint="/api/task", source=source, params=seen, code=400,
                       result=f"没写成：{problem}", ok=False)
    return _finish(handler, endpoint="/api/task", source=source, params=seen, code=200,
                   result=f"已投递（{iid}）：主控会在下一步开头读到，当前这一步不被打断",
                   ok=True, ident=iid,
                   extra={"interjection_id": iid, "sid": sid})


#: 两条"说话"的端点在下面才定义（它们的正文紧邻本段之上）⇒ 注册放在这里，
#: 免得 `HANDLERS.update` 引用尚未绑定的名字。
HANDLERS.update({
    "handle_start_run": handle_start_run,
    "handle_interject": handle_interject,
})


# ====================================================================== 回答（既有写路径）
def answer(root: Path, form: Mapping[str, Sequence[str]]) -> tuple[int, str, str]:
    """处理一次回答提交：返回 `(状态码, 重定向目标, HTML 正文)`。

    三态纪律：qid 不在待答清单里 ⇒ 409（不是 200），并在页面上说清是哪一档：
    已经被谁什么时候答过、还是根本没有这个号。写失败 ⇒ 500 并原样给出错误。

    审计（裁定 D2）：每一次到达这里的提交（含 409 与 500 那两档）都追加一行
    `web-actions.jsonl`。为什么审计失败不改状态码：本函数的三个返回值是 A 线
    `handle_answer` 与 `tests/test_webui.py` 钉死的契约，"写成了但没审计上"
    不该被折叠成"写失败"（那会把一次真实的落盘说成没发生）。所以审计失败走 stderr，
    而 `/api/*` 那三条端点的回执把 `extra.audit` 如实带给调用方。
    """
    def one(name: str) -> str:
        """取表单里某个字段的第一个值（没有就给空串 —— 表单字段缺失是常态，不是错误）。"""
        vals = form.get(name) or []
        return _text(vals[0]) if vals else ""

    def done(code: int, location: str, body: str) -> tuple[int, str, str]:
        """记一笔审计再原样返回 `(码, 目标, 正文)` —— 行为与拆包前逐字相同。"""
        params = {"qid": one("qid"), "sid": one("sid"),
                  "selected": [_text(x) for x in (form.get("selected") or [])],
                  "custom": one("custom"), "skip": one("skip")}
        _row, problem = audit.record_action(
            root, endpoint="/answer", source="", params=params,
            result=f"http {code}",
            tri=TRI_COMPUTED if code == 303 else TRI_NOT_APPLICABLE,
            ok=code == 303, http=code)
        if problem:
            # 审计落不下这件事必须说出口（三态纪律），但这个函数的返回契约不许改
            # ⇒ 唯一的出口是 stderr（服务端日志）。
            sys.stderr.write(f"[webui] 审计台账写失败（/answer）：{problem}\n")
        return code, location, body

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
            return done(409, "", html_body)
        html_body = (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">409 · 没有这个号</span></div>'
            f'<div class="readings">问题号 <span class="mono">{_e(qid) or "（空）"}</span>'
            " 不在任何会话的待答清单里，也不是一条已落盘的问答 —— 什么都没写。"
            '<a href="/">回首页</a> 看看现在在等什么。</div></div>')
        return done(409, "", html_body)
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
        return done(500, "", (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">500 · 写失败</span></div>'
            f'<div class="readings">落盘时抛异常：'
            f'<span class="mono">{_e(f"{type(exc).__name__}: {exc}")}</span></div></div>'))
    if problem:
        return done(500, "", (
            '<div class="card problem"><div class="card-head">'
            '<span class="badge badge-fail">500 · 写失败</span></div>'
            f'<div class="readings">会话记录没写成：'
            f'<span class="mono">{_e(problem)}</span>'
            f"（问题号 <span class=\"mono\">{_e(qid)}</span>，"
            f"会话 <span class=\"mono\">{_e(sid)}</span>）</div></div>"))
    return done(303, "/", "")
