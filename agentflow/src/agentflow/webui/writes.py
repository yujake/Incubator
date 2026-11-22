# -*- coding: utf-8 -*-
"""用户端 Web 界面的写路径（四个端点 + 授权 + 审计）。

## 这一层是什么

`answer(root, form)` 是回答那一条写路径：落盘只走 `userio.answer_question` 这一个
写入口（事件形状由它定义，本模块不拼第二份），三态与状态码也照旧。

## 口径

- qid 与 sid 必须按 `(sid, qid)` 这一对匹配：每段会话各自从 `q0001` 开始编号，
  只按 qid 索引会让"给一个已经答过的会话再提交"通过存在性检查，往那个会话里写下
  第二条回答（跨会话串味）；
- 失败不许折成 200：不在待答清单 ⇒ 409 并分「已经答过了」与「没有这个号」两档说清；
  写失败 ⇒ 500 并原样给出错误；
- 成功 ⇒ 303 回首页（PRG：刷新不重复提交）；
- 跳过（`skip=1`）⇒ 落一条空的 `selected` 与空的 `custom`。那是"答了，答案是空"，
  不是"没答"。

## 三件写端点与它们的闸门（裁定 C2 / D2 / E1 / I1）

三件都走既有的闸门、不另写一条写路径：

| 端点 | 既有闸门（出处） |
|---|---|
| `POST /api/stop` | `stopctl.request_stop_detail`（`stopctl.py:65`）· 强制停再走 `stopctl.kill_registered`（`stopctl.py:392`） |
| `POST /api/submit` | `interactions.next_prefixed_id`（`interactions.py:1233`）＋ `store.tx`（`store.py:890`）＋ `SearchRequest.validate`（`schema.py:243`） |
| `POST /api/settings` | `settings.write_settings`（见 `settings.py`）—— 它自己就是那条唯一写入口 |

`/api/task` 是"用户 → M 留言"那条通道（`handle_interject`），与上面三件走同一套
闸门与审计；不给它另开一条写路径。

`POST /answer` 走同一道闸门（2026-11-21 WEBFIX1 / 审计 F4）。在它之前的那一版里
`/answer` 只靠 `userio.answer_question` 兜底：跨站页面带 `Origin: evil.example`、
不带 CSRF 也能把一条待答答掉并落盘（实测 303 + `user_answer`；同形状打 `/api/task`
是 403）。现在它由 A 线 `server.py` 的 `handle_answer` 把请求句柄交下来，和其余写
端点一样过 `来源 ⇒ CSRF ⇒ allow_writes` 三层：拒时 403 + 同一份 `kind` /
`how_to_fix`（`:func:`refusal_reading``），写成时仍是 303 / 409 / 500 那三个状态码。

新端点的授权矩阵（裁定 C2）按 `draft/74` §4 的口径三层，次序即下面的检查次序：
回环来源 ⇒ CSRF（`X-CSRF-Token`，与 `index.html` 里注入的每进程令牌比对）⇒
`allow_writes`（`agentflow web --allow-writes`，已透传到句柄上）。
`/api/settings` 另加一层 `settings_write`（`--no-settings-write` 关掉它）。
四个写端点（`/api/stop` · `/api/run` · `/api/task` · `/answer`）共用一处
:func:`_gate`，那一处再调 :func:`authorize` —— 判据只有一份。

三态与状态码（失败不许折成 200）：

| 情形 | 码 | `WriteResult.tri` |
|---|---|---|
| 写成了 | 200 | `computed` |
| 未开写面 / CSRF 不对 / 非回环来源 | 403 | `not_applicable` |
| 缺 `confirm=1` / 参数不合法（整批不写） | 400 | `not_applicable` |
| 闸门抛异常或结局说不清 | 500 | `unreadable` |

每一次到达本模块处理器的写尝试（含被拒的）都追加一行
`<工作区>/web-actions.jsonl`（裁定 D2，实现见 :mod:`agentflow.webui.audit`）。

一个必须写清楚的例外（E7）：只读档（没开 `--allow-writes`）不写这一行。
台账是工作区根上的一个文件，而缺省档在 `--help` 与模块 docstring 里叫"只读"——
写它就是"只读服务不是只读"（实测：只发过 GET 与被拒 POST 的只读服务在
`projects/chain-v1` 与 `projects/p6t2-research-20261012` 各建了一个
`web-actions.jsonl`）。所以只读档的被拒尝试只进 stderr，回执里
`extra.audit.tri = not_applicable` 并说清"没落盘"；写面开了之后照旧每一笔都留档
（判据 `tests/test_webui_read_only_does_not_write.py` 的两半）。
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
from ..store import Store, StoreError
from . import audit
from . import state as _state
from .state import _clip, _e, _sid_ok, _text, answer_text_of, snapshot

__all__ = ["HANDLERS", "MISSING_TYPES", "PENDING_ENDPOINTS", "ROUTES",
           "UNCHECKED_TYPES", "WRITES_OFF_REASON", "answer", "authorize",
           "handle_ack", "handle_budget", "handle_settings",
           "handle_stop_clear", "handle_void",
           "handle_stop",
           "handle_submit", "type_decls", "writes_allowed"]

#: 处理器的落点（与 `readers.py`/`sse.py` 同一条约定）：键 = `ROUTES` 第三元素，
#: 值 = `(handler, params, query)` 签名的函数、`handler` 是 `WebHandler` 实例。
#: `/answer` 由 `WebHandler` 自己的方法实现；
#: C 线新加的三条写端点把 handler 放这里 —— 于是不必去改 A 线的 `server.py`。
HANDLERS: dict[str, Any] = {}

#: 契约判据 C 的欠账登记（`{接口名: 理由}`）：本模块声明、但夹具上还读不出键的接口。
UNCHECKED_TYPES: dict[str, str] = {}

#: 契约判据 D 的例外面（`{端点: 理由}`）：声明了但后端还没落地的写端点。落地后删掉。
#: 三条写端点都已注册 ⇒ 这张表保持空（判据 D 的反向断言要求"落地即撤销"）。
PENDING_ENDPOINTS: dict[str, str] = {}

#: 本模块挂到总路由表上的写端点：`(method, path 模式, 处理器名字)`。
#: 总表是 `webui/routes.py` 拼出来的（`自有 + READER_ROUTES + WRITE_ROUTES`），
#: 所以 C 线加端点改的是这一行，不用去碰 A 线的文件（`draft/78 §3` 的接缝）。
#:
#: `/answer` 那一行仍指向 A 线 `WebHandler.handle_answer`（`server._invoke` 先找方法、
#: 再找子表）：路由名与实现处不变，但它与其余写端点走同一道授权闸门（F4）。
#: 2026-11-21 之前它不进那张矩阵（`draft/73` §2.5 的"现状，不动"），于是跨站表单
#: 能答掉待答；现在 `answer()` 的入口就是 `_gate(...)`。
ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/answer", "handle_answer"),
    ("POST", "/api/stop", "handle_stop"),
    ("POST", "/api/submit", "handle_submit"),
    ("POST", "/api/settings", "handle_settings"),
    # 预算窗口：追加 / 重设额度（写面，走同一套授权、
    # CSRF、审计与 `confirm=1`）。
    ("POST", "/api/budget", "handle_budget"),
    ("POST", "/api/run", "handle_start_run"),
    ("POST", "/api/task", "handle_interject"),
    # 板项收口（WEBFIX2 · F7）：页面上"知道了 / 做完了"那一只手。
    # 状态机不在这里（判据只有 `conductor.close_item` 一处），这一条只是它的门面。
    ("POST", "/api/ack", "handle_ack"),
    # 板项作废（BOARDACK，2026-11-21）：页面上"这一条不用再做了"那一只手。
    # 为什么 `/api/ack` 不够：那 6 条 block 项在迁移图里没有出边（`block → done`
    # 是倒退），而"唤醒 ⇒ 再 ack"仍被 A5 的空口 ack 闸拦（唤醒会清掉 seen_by）。
    # 唯一实现是 `conductor.void_items_by_user`（≡ `void_items(revoke=True, by_human=True)`）。
    ("POST", "/api/void", "handle_void"),
    # 撤销叫停（WEBFIX2 · F9）：把那一把还挂在盘上的停机开关撤掉，
    # 于是"叫停之后从网页再起一趟"不会白起。唯一写入口是 `stopctl.clear_stop`。
    ("POST", "/api/stop/clear", "handle_stop_clear"),
)

#: 本模块还欠的 TS 接口（`(名字, 为什么还没有)`）；写面接口已全部生成 ⇒ 空。
MISSING_TYPES: tuple[tuple[str, str], ...] = ()

#: 写面统一回执的字段表（`(TS 名字, 后端出处, ((字段, TS 类型), ...))`）。
#: `id` / `extra` 是"有就带上"的两栏，所以写成可选。`state` 也是可选：
#: 它只给"这件事有自己的一趟生命周期"的端点用（缓存预热：`plan` / `running`），
#: 与 `tri` 分处两根轴 —— `tri` 说"这次请求成没成"，`state` 说"被起的那件事到哪一步了"。
_TS_TYPES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("WriteResult",
     "写面端点的统一回执（判据 C 不覆盖它；`id`/`extra` 只是"
     "「有就带上」的两栏，所以写成可选）",
     (("ok", "boolean"), ("tri", "Tri"), ("reason", "string"),
      # 失败那几档自带（鲁棒 e：页面据此分档并给出"怎么办"）；成功那几档不带。
      ("kind?", "string"), ("how_to_fix?", "string"),
      ("id?", "string"), ("state?", "string"), ("extra?", "Record<string, unknown>"))),
)


def type_decls() -> str:
    """本模块（写面）那一段 TS 声明文本。

    渲染代码只有一份，在 `webui/state.type_decls`（本文件只留这一行转发）。

    形状是 `draft/78 §3` 的接缝之一：`agentflow/web/emit_types.py` 把三条零交线
    各自的 `type_decls()` 拼成 `ui/src/types.ts`。C 线加写端点时，回执接口加在
    `_TS_TYPES` 里。
    """
    return _state.type_decls(_TS_TYPES, ())


# ====================================================================== 授权（裁定 C2）
#: 三态词表（与 `readers.TRI_*` / `types.ts` 的 `Tri` 同一套；字符串不许互相顶替）。
TRI_COMPUTED = "computed"
TRI_NOT_APPLICABLE = "not_applicable"
TRI_UNREADABLE = "unreadable"

#: 真正算"本机"的主机名（来源校验用）。只留真回环：
#: `0.0.0.0` / `::` 是绑定地址、不是来源地址，见 :data:`_BIND_HOSTS`。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: 通配绑定地址。它回答的是"这个服务绑在哪"，不是"这条请求从哪来" ——
#: 所以它只参与"要不要拒"这一档（在这一层不当外来证据），不参与"是不是本机"：
#: 绑 0.0.0.0 的服务用 `http://0.0.0.0:8788` 打开时 `Host` 正是它，按外来地址
#: 拒会把正当用法一起拒掉；而真正的外来连接由第三层（socket 对端地址）拦，
#: 那一层看的是内核给的事实、不看头。把回环与绑定地址混在同一张表里，
#: "Host 是回环"这句话在绑 0.0.0.0 时就不成立（D9）。
_BIND_HOSTS = frozenset({"0.0.0.0", "::"})

_TRI_FOR_CODE = {403: TRI_NOT_APPLICABLE, 400: TRI_NOT_APPLICABLE, 500: TRI_UNREADABLE}

#: 没开写权限时页面上那一行原因的唯一真身（逐字，D-60 ①）。
#: 为什么它住在这里而不是前端：`--allow-writes` 是这一层开关的名字，理由与开关同处
#: 一个文件，页面只画 `/api/cache` 带出来的 `writes_reason`（与 `active.text` 同一条
#: 口径：两处各拼一份文案，两句话迟早会漂，而漂了没有地方会报错）。
WRITES_OFF_REASON = "本服务未开 --allow-writes，写按钮不可用；重启时加该参数即可"


def refusal_reading(code: int, reason: str) -> tuple[str, str]:
    """一次写失败 ⇒ `(kind, how_to_fix)`（鲁棒 e：错误块要能说清是哪一档、怎么办）。

    `kind` 是闭集（页面据此分档，不必读中文）；`how_to_fix` 是一句能直接照做的人话。
    为什么按理由串判而不是让 `authorize` 多返回一位：`authorize` 的签名
    `(放行吗, 状态码, 理由)` 是既有公开面（六个写端点与判据都按它解包），
    改元数会让"少接一位"变成运行时错；而这里的理由串全部是本模块的常量。
    """
    text = str(reason or "")
    if code == 403:
        if "CSRF" in text:
            return "csrf_token", "刷新页面重新拿令牌（每进程换一个）；不要手工拼 POST"
        if "写面没开" in text:
            return "writes_off", "用 `agentflow web --allow-writes` 重启服务（缺省只读，只读档不写盘）"
        if "设置写面" in text:
            return "settings_off", "重启时不要加 `--no-settings-write`"
        return "foreign_origin", "从本机浏览器打开这一页（跨站来源一律拒）"
    if code == 400:
        if "confirm" in text:
            return "confirm_required", "带 confirm=1 重试（不可逆动作要显式确认一次）"
        return "bad_request", "读回执里那句理由，改参数后重试"
    if code == 409:
        return "conflict", "这一条已被处理或不存在；刷新后再看"
    if code >= 500:
        return "internal", "这一份没写成（盘上没被动过）：把这一行与时间报给维护者"
    return "refused", "读回执里那句理由"


def writes_allowed(handler: Any) -> bool:
    """本服务是否开了写权限（授权矩阵第 3 层的唯一判定口径）。

    单独抽一个函数是为了让读侧（`cacheface` 的 `writes_allowed` 读数）与判侧
    （:func:`authorize`）取同一个事实：页面上说"不能写"、闸门说"放行"，那种自相
    矛盾比没有读数更坏。缺省 False（fail-closed，与 `authorize` 的 docstring 一致）。
    """
    return bool(getattr(handler, "allow_writes", False))


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

    头里那一格分三档：真回环 ⇒ 过；通配绑定地址
    （`_BIND_HOSTS`）⇒ 这一格不当证据、也不算"本机"，由第三层定；其余 ⇒ 拒。
    """
    client = ""
    addr = getattr(handler, "client_address", None)
    if isinstance(addr, (tuple, list)) and addr:
        client = str(addr[0])
    headers = handler.headers
    for label, raw in (("Origin", headers.get("Origin", "")),
                       ("Host", headers.get("Host", ""))):
        host = _host_of(raw)
        if host in _LOOPBACK_HOSTS or host in _BIND_HOSTS:
            continue
        if host:
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
              need_settings: bool = False,
              read_only: bool = False,
              source_problem: str | None = None) -> tuple[bool, int, str]:
    """写面的授权矩阵（裁定 C2）：`(放行吗, 状态码, 理由)`。次序即 `draft/74` §4。

    1. 回环来源（跨站来源一律拒）；
    2. CSRF 令牌（写请求必须带 `X-CSRF-Token`，值来自每进程的注入令牌）；
    3. `allow_writes`（`agentflow web --allow-writes`；缺省只读）；
    4. 只有 `/api/settings` 才要的第 4 层：`settings_write`（`--no-settings-write`）。

    为什么第 3 条要放在 CSRF 之后：`draft/74` §4 那一行逐字是"回环来源校验 →
    CSRF → `allow_writes` 开关"。次序不改变状态码（都是 403），改变的是理由，
    而理由要进审计台账 —— 审计读的是"为什么被拒"，写错一档就查不出来。

    `source_problem` 是 :func:`_gate` 交下来的来源判据（缺省 `None` = 本函数自己读
    一次）。为什么要这个口子：来源既要决定拒不拒，也是审计台账里"这次从哪来"那一
    格；两处各读一次可能出现"按 A 拒、记成 B"，而那种错只有翻台账时才看得见。

    `read_only=True` 是 D-60 ② 那一档：请求自己声明"我不写盘、不花钱、不起进程"
    （缓存预热的 `dry_run=1`）。这一档只保留第 1 层，理由如下：

    - 第 2、3、4 层防的是"写"与"花钱"，而这一档两样都没有：它同步算一份计划就回；
    - 第 1 层留着就够挡浏览器里的跨站请求（跨站 POST 必带 `Origin`，它在这一层被拒）；
      没有浏览器的本地进程本来就与网页同权，给它加 CSRF 不增加任何防护，只会让
      "先看计划再决定"这一步要人先去找那个每进程随机令牌 —— 实测撞到过（D-60 现场：
      手工 POST 缺 `X-CSRF-Token`，回执是 403，而人以为是没开写权限）。

    真跑那一档（`read_only=False`）一层都不许少：这是同一张矩阵的缺省形态。
    """
    if source_problem is None:
        _source, source_problem = _source_of(handler)
    if source_problem:
        return False, 403, f"{endpoint}：{source_problem}"
    if read_only:
        return True, 200, ""
    if not _csrf_ok(handler):
        return False, 403, (f"{endpoint}：CSRF 令牌不对或没带"
                            "（写请求必须带 X-CSRF-Token）")
    if not writes_allowed(handler):
        return False, 403, (f"{endpoint}：写面没开 —— 要用 "
                            "`agentflow web --allow-writes` 才允许写")
    if need_settings and not bool(getattr(handler, "settings_write", True)):
        return False, 403, f"{endpoint}：设置写面被 --no-settings-write 关掉了"
    return True, 200, ""


def _gate(handler: Any, *, endpoint: str,
          need_settings: bool = False) -> tuple[bool, int, str, str]:
    """写面的唯一一道闸门：`(放行吗, 状态码, 理由, 这次请求的来源)`。

    它只做一件事：把来源读一次，交给 :func:`authorize` 判，再把同一份来源带回去
    给审计。四个调用点（`/api/stop` · `/api/run` · `/api/task` · `/answer`）共用
    这一处 —— 谁也不许自己再拼一份"看 Origin / 看 Host / 比对 CSRF"的判断。

    判据（`:func:`authorize``）仍只有一份：`_gate` 是它的调用口，不是第二份实现。
    """
    source, problem = _source_of(handler)
    allowed, code, why = authorize(handler, endpoint=endpoint,
                                   need_settings=need_settings,
                                   source_problem=problem)
    return allowed, code, why, source


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
            extra: Mapping[str, Any] | None = None, tri: str = "",
            state: str = "") -> dict[str, Any]:
    """记一行审计、回一支 `WriteResult`，并把这一支返回给调用方（判据要比对它）。

    审计与回执必须同时发生：写成功了却没审计上是一个必须说出口的状态，
    所以台账的结局（`computed` / `unreadable`）原样带进 `extra.audit`，
    而它不冒充这次写的结局（`tri` 说的是写本身）。

    `tri` 显式给了就用它（设置那一支的三态来自 `write_settings` 自己的词表，
    不能由状态码反推）；缺省按状态码推。返回值与发出去的正文是同一支：
    这里先定 `tri` 再 `_json`，不许"发一份、返回另一份"。

    `state` 是"被起的这件事到哪一步了"（D-60 ③：缓存的 `plan` / `running`），
    与 `tri` 分处两根轴；不给就不带这一格（其余写端点的回执一个字节都不变）。

    只读档（`--allow-writes` 没开）不落盘：审计台账是
    `<工作区>/web-actions.jsonl`，写它就是在别人的目录里新建文件 —— 而缺省档在
    `--help` 与模块 docstring 里叫"只读"。于是这一档的写法是：只把这一笔打进
    stderr，回执里 `extra.audit.tri = not_applicable` 并说清"没落盘"。
    不改的另半：写面开了之后，被拒的尝试照旧留一行（判据 ③ 是它）。
    """
    tri = tri or (TRI_COMPUTED if ok else _TRI_FOR_CODE.get(code, TRI_NOT_APPLICABLE))
    body: dict[str, Any] = {"ok": ok, "tri": tri, "reason": result}
    if not ok:
        # 鲁棒 e：4xx/5xx 的回执自带「哪一档（kind）」与「怎么办（how_to_fix）」，
        # 页面据此渲染错误块，不必从中文理由里猜。成功那一支一个字节都不加。
        kind, how_to_fix = refusal_reading(code, result)
        body["kind"] = kind
        body["how_to_fix"] = how_to_fix
    if ident:
        body["id"] = ident
    if state:
        body["state"] = state
    if not writes_allowed(handler):
        summary = audit.summarize(params)
        sys.stderr.write(f"[webui] 只读档不落审计（{endpoint} → http {code}，"
                         f"ok={ok}）：{result}\n")
        out_extra: dict[str, Any] = dict(extra or {})
        out_extra["audit"] = {
            "tri": TRI_NOT_APPLICABLE,
            "path": str(audit.actions_path(handler.root)),
            "params_sha256": audit.digest_of(summary),
            "reason": ("本服务是只读档（没开 --allow-writes）：这一笔只进服务端日志，"
                       "不写 web-actions.jsonl —— 只读档一个字节都不往工作区写"),
        }
        body["extra"] = out_extra
        handler._json(code, body)
        return body
    row, problem = audit.record_action(handler.root, endpoint=endpoint, source=source,
                               params=params, result=result, tri=tri, ok=ok, http=code)
    out_extra = dict(extra or {})
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


def _replier(handler: Any, endpoint: str, source: str,
             params: Mapping[str, Any]) -> Any:
    """一支"这一面的回执"：`endpoint` / `source` / `params` 三格在每个出口都相同。

    返回的函数前半截与 :func:`_finish` 的后半截同形（`code` / `result` / `ok` 三个位置
    参数，其余照旧走关键字）。`_finish` 在调用那一刻按模块全局查找 —— 于是打桩它的
    判据照样生效。六个写端点各自有 4–9 个出口，把这三格重复写 40 遍是本文件里最大
    的一处重复（漏一格就是一条进错台账的行）。
    """
    def reply(code: int, result: str, ok: bool, **kw: Any) -> dict[str, Any]:
        return _finish(handler, endpoint=endpoint, source=source, params=params,
                       code=code, result=result, ok=ok, **kw)
    return reply


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
    reason = _one(form, "reason").strip() or SC.DEFAULT_REASON
    force = _flag(form, "force")
    seen = {"reason": reason, "force": force, "confirm": _flag(form, "confirm")}
    allowed, code, why, source = _gate(handler, endpoint="POST /api/stop")
    done = _replier(handler, "/api/stop", source, seen)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not _flag(form, "confirm"):
        return done(400, ("拒绝：叫停不可逆，必须带 confirm=1 一次显式确认"
                          "（draft/75 §1.1 第 8 行）"), False)
    try:
        payload, outcome = SC.request_stop_detail(root, reason=reason, by="web", force=force)
    except Exception as exc:  # noqa: BLE001 - 失败不许折成 200
        return done(500, (f"停机开关没写成：{type(exc).__name__}: {exc}"
                          "（盘上那一份没被动过）"), False)
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
    return done(200, result, True, ident=_text(payload.get("path")), extra=extra)


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
    topic = _one(form, "topic").strip()
    mode = _one(form, "mode").strip() or "topical"
    content = _one(form, "content")
    providers = [_text(x).strip() for x in (form.get("providers") or []) if _text(x).strip()]
    seen = {"topic": topic, "mode": mode, "content": content, "providers": providers,
            "confirm": _flag(form, "confirm")}
    allowed, code, why, source = _gate(handler, endpoint="POST /api/submit")
    done = _replier(handler, "/api/submit", source, seen)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not _flag(form, "confirm"):
        return done(400, ("拒绝：入队一条检索请求要 confirm=1 一次显式确认"
                          "（ConfirmButton 的落点）"), False)
    if not topic:
        return done(400, "拒绝：topic 不能为空（整批未写入）", False)
    try:
        store = Store(root)
        store.init()
    except (StoreError, OSError) as exc:
        # `Store.init()` 若写在 `try` 之外，而根上有网页自己写的
        # `.agentflow-stop` / `budget.json` / `web-actions.jsonl`、又没有 `data/`，
        # 它抛 `StoreError` ⇒ 冒到 `server._invoke` 的兜底分支 ⇒ 500
        # `handler_crashed`，而且 `_finish()` 没被调用（这一笔被拒的写尝试不进台账）。
        # 这是查得清的拒绝（"这个工作区没 init 过"），不是处理器崩了：
        # 受控 400 + `tri=not_applicable` + 照常走 `_finish` 落审计。
        # 不接受"把 `web-actions.jsonl` 加进 store 的根白名单"那种修法：
        # 那会放宽 `store.py` 的"别在别人的目录里凭空建库"那道守卫。
        return done(400, ("拒绝：这个工作区没有 data/（没 `agentflow init` 过），"
                          "不能入队 —— 先 `agentflow init`，或换一个已初始化的"
                          f"工作区。{type(exc).__name__}: {exc}"),
                    False, tri=TRI_NOT_APPLICABLE)
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
        return done(400, (f"拒绝：请求不合法，整批未写入 —— "
                          f"{type(exc).__name__}: {exc}"), False)
    except Exception as exc:  # noqa: BLE001 - 结局说不清 ⇒ unreadable，不折成成功
        return done(500, (f"入队没成：{type(exc).__name__}: {exc}"
                          "（事务未提交，盘上那份没被动过）"), False)
    return done(200, f"已入队 {rid}（topic={topic} · mode={mode}）", True, ident=rid)


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
    values: dict[str, dict[str, Any]] = {}
    for raw_key, vals in form.items():
        if "." not in str(raw_key):
            continue                      # confirm 之类的顶层字段不进设置
        text = _text(vals[0]) if vals else ""
        section, rest = str(raw_key).split(".", 1)
        # `models` 是三段的键（`models.<角色>.<键>`，按角色配置）：
        # 表单是平的，所以这里再切一刀；其余段仍是两段。
        if section == SET.MODELS_SECTION and "." in rest:
            slot, key = rest.split(".", 1)
            values.setdefault(section, {}).setdefault(slot, {})[key] = text
        else:
            values.setdefault(section, {})[rest] = text
    allowed, code, why, source = _gate(handler, endpoint="POST /api/settings",
                                       need_settings=True)
    done = _replier(handler, "/api/settings", source, values)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not _flag(form, "confirm"):
        return done(400, ("拒绝：写设置要 confirm=1 一次显式确认"
                          "（覆盖 key 是不可逆动作）"), False)
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
    return done(http, str(got.get("reason") or ""), bool(got.get("ok")),
                ident=str(got.get("path") or ""), extra=extra, tri=mapped)


def handle_budget(handler: Any, params: Mapping[str, str],
                  query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/budget`：追加一笔额度（`action=add`）或重设总额（`action=set`）。

    业主：「用户可追加预算，运行消耗的钱从总预算里实时扣除」。
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
    action = (_one(form, "action").strip() or "add").lower()
    raw_usd = _one(form, "usd").strip()
    note = _one(form, "note")
    by = _one(form, "by").strip() or "web"
    seen = {"action": action, "usd": raw_usd, "note": note, "by": by,
            "confirm": _flag(form, "confirm")}
    allowed, code, why, source = _gate(handler, endpoint="POST /api/budget")
    done = _replier(handler, "/api/budget", source, seen)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not _flag(form, "confirm"):
        return done(400, ("拒绝：改预算要 confirm=1 一次显式确认"
                          "（它改的是这一趟还能不能继续花钱）"), False)
    if action not in ("add", "set"):
        return done(400, f"拒绝：action 只认 add / set（收到 {action!r}）", False)
    if raw_usd == "":
        return done(400, "拒绝：usd 不能为空", False)
    try:
        amount = float(raw_usd)
    except (TypeError, ValueError):
        return done(400, f"拒绝：usd 读不成数字（收到 {raw_usd!r}）", False)
    got = (B.add_usd(root, amount, by=by, note=note) if action == "add"
           else B.write_initial(root, amount, by=by, note=note))
    ok = bool(got.get("ok"))
    return done(200 if ok else 400,
                (f"已{'追加' if action == 'add' else '重设'}额度："
                 f"总额现在是 ${float(got.get('total_usd') or 0.0):.6f}"
                 if ok else f"没写成：{got.get('reason') or '（没给理由）'}"),
                ok, ident=str(got.get("path") or ""),
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


def _run_argv(root: Path, task: str, *, sid: str = "",
              resume: bool = False) -> list[str]:
    """起一趟要跑的那条命令行（判据拿它比对；`dry_run` 也回它）。

    `sid` / `resume`（R91，业主「要能对话」）：对话页在 M 闲着的时候要让那一段
    会话接着说下去 —— 用户的话先落进收件箱（`/api/task`），再按同一句话任务
    唤醒 M（`--sid <那段会话> --resume`）。为什么必须带上原来那句话：`resume_messages`
    按"role 相同 + task 原文相同 + 是全新开始"来定重建窗口，换了任务就是另一趟
    （`--resume` 会以指纹不符拒掉，那是有意的守卫）。收件箱那一段是现读的，
    所以新留言正好落在 M 醒来的第一步里。
    """
    argv = [sys.executable, "-B", "-m", "agentflow", "--root", str(root),
            "run-agent", S.CONDUCTOR_ROLE, "--task", task, "--subagents"]
    if sid.strip():
        argv += ["--sid", sid.strip()]
    if resume:
        argv.append("--resume")
    return argv


def _spawn_detached(root: Path, argv: Sequence[str], prefix: str) -> tuple[int, str]:
    """起一个 detached 子进程，stdout/stderr 追加进 `runs/<prefix>-<时间>.log`。

    为什么抽成一处：`/api/run` 的"起一趟"与 `/api/cache/warm` 的"起一趟预热"
    若各写一遍这套五件事 —— 建 `runs/`、按时间戳命名日志、两个编码环境变量、
    Windows 的 detached 旗标、Popen 的形状 —— 就得两份同时改才不出事，而
    "文件句柄没 close"那个缺陷正是两份都没写对。

    两处各自保留的东西：日志前缀（`web-run` / `web-cache-warm`，判据按它们 glob）
    与 `runs/` 这个落点（"在飞"页与 `cwd` 都按它认）。

    返回 `(pid, 工作区相对日志路径)`；相对路径用 `/` 分隔（记录与页面都按它认）。
    """
    import os
    import subprocess
    from datetime import datetime

    runs = Path(root) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    log = runs / f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    with open(log, "ab") as handle:
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(list(argv), cwd=str(root), env=env,
                                stdout=handle, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=flags,
                                close_fds=True)
    return int(proc.pid), str(log.relative_to(Path(root))).replace("\\", "/")


def _spawn_run(root: Path, task: str, *, sid: str = "",
               resume: bool = False) -> tuple[int, str]:
    """真起一趟：detached 子进程，stdout/stderr 追加进 `runs/web-run-*.log`。

    为什么 detached 而不是在服务进程里跑：一趟是几十分钟的模型循环，跟着网页进程生灭
    会把"用户关掉标签页"变成"任务被杀"。日志落到项目自己的 `runs/` 下，网页的"在飞"页
    与 `sessions/` 照样读得到它。

    起进程那五件事（建目录 / 命名日志 / 编码环境 / Windows 旗标 / Popen）住在
    :func:`_spawn_detached` 里，与预热的 `_spawn_warm` 共用同一份。
    """
    return _spawn_detached(root, _run_argv(root, task, sid=sid, resume=resume), "web-run")


def handle_start_run(handler: Any, params: Mapping[str, str],
               query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/run`：用一句话起一趟工作流（等价 CLI 的 `run-agent M --task …`）。

    请求字段：`task`（要系统做的那件事，一句话）· `confirm=1` · `dry_run?` ·
    `sid?` + `resume?`（R91：让闲着的那段会话接着说下去 —— 对话页在 M 不跑时
    走的就是这一支；`resume` 必须配 `sid`，因为它问的是"接着哪一段跑"）。
    三态：没开写面 / CSRF 不对 ⇒ 403；任务为空 / 缺 confirm / `resume` 没给 `sid`
    ⇒ 400（一个字节都不写）；起不来 ⇒ 500 并原样给错误；起来了 ⇒ 200 + `{pid, log, argv}`。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    task = _one(form, "task").strip()
    sid = _one(form, "sid").strip()
    resume = _flag(form, "resume")
    dry = _flag(form, "dry_run")
    seen = {"task": task, "sid": sid, "resume": resume, "dry_run": dry,
            "confirm": _flag(form, "confirm")}
    allowed, code, why, source = _gate(handler, endpoint="POST /api/run")
    done = _replier(handler, "/api/run", source, seen)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not task:
        return done(400, "拒绝：任务不能为空 —— 它就是你要对系统说的那一句话", False)
    if resume and not sid:
        return done(400, ("拒绝：resume 要配 sid —— 它问的是"
                          "「接着哪一段会话跑」，缺了无从选窗口"), False)
    if not _flag(form, "confirm"):
        return done(400, "拒绝：起一趟会真的花预算，必须带 confirm=1 一次显式确认", False)
    argv = _run_argv(root, task, sid=sid, resume=resume)
    if dry:
        return done(200, "试运行：没有起任何进程（argv 见 extra）", True,
                    extra={"argv": argv, "dry_run": True})
    try:
        pid, log = _spawn_run(root, task, sid=sid, resume=resume)
    except Exception as exc:  # noqa: BLE001 - 起不来要如实报，不许静默
        return done(500, f"起不来：{type(exc).__name__}: {exc}", False,
                    extra={"argv": argv})
    return done(200,
                (f"已{'续跑' if resume else '起'}一趟（pid={pid}）"
                 f"—— 去「对话」或「在飞」页看它"),
                True, ident=log, extra={"pid": pid, "log": log, "argv": argv})


def _interject_sid_problem(sid: str) -> str:
    """`/api/task` 的 sid 硬要求：返回拒绝理由，空串 = 放行（审计 F2）。

    缺省 sid 的口径二选一，这里选"受控拒"：`sessions.session_path()` 的缺省是
    `sid or session_id()`（当天日期），于是不带 sid 的插话会落进
    `sessions/<当天日期>.jsonl` —— M 在自己的 `--sid` 段里读不到，而且那段空会话
    会把页面的「当前会话」顶掉。"当前活跃会话"听起来更聪明，但多段会话并存时它
    没有唯一答案，猜错一次就是一条没人读的插话；显式拒绝会明确告诉调用方给 sid
    （页面本来就知道自己在看哪一段）。

    sid 还必须是安全的文件名主干（`_sid_ok`：字母、数字与 `- _ .`，不许含 `..`）——
    否则 `sessions/<sid>.jsonl` 会写到 `sessions/` 之外。
    """
    if not sid:
        return ("插话必须给 sid —— 它回答的是「写进哪一段会话」。缺省不再落到当天"
                "日期那一段：M 在自己的 --sid 段里读不到，而且那段空会话会把页面的"
                "「当前会话」顶掉")
    if not _sid_ok(sid):
        return (f"sid 不是安全的会话号（{sid!r}）—— "
                "只许字母、数字与 - _ .，且不许含 ..")
    return ""


def handle_interject(handler: Any, params: Mapping[str, str],
                query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/task`：往正在跑的那一趟插话（只有用户能发、只有 M 收）。

    请求字段：`body`（要说的话）· `sid`（哪一段会话）· `subject?` ·
    `confirm=1` · `dry_run?`。`sid` 是硬要求（审计 F2）：缺了不再落到
    `sessions/<当天日期>.jsonl` —— 那是另一段会话，M 在自己的 `--sid` 段里读不到，
    还会把页面的「当前会话」顶到那段空会话上。两种可选口径里这里选"受控拒"：
    "当前活跃会话"在多段并存时没有唯一答案，猜错一次就是一条没人读的插话；拒绝
    会明确告诉调用方去给 sid（页面本来就知道它在看哪一段）。
    送达方式由 `agent_loop.send_interjection` 定义：下一步开头单列一段【插话】，
    不打断当前步；写进会话事件流（`agent_interjection`），所以盘上可复查。
    """
    del params, query
    from .. import agent_loop as AL
    from .. import userio as U

    form = handler._form()
    root = Path(handler.root)
    body = _one(form, "body").strip()
    subject = _one(form, "subject").strip() or "用户插话"
    sid = _one(form, "sid").strip()
    dry = _flag(form, "dry_run")
    seen = {"body": body, "subject": subject, "sid": sid, "dry_run": dry,
            "confirm": _flag(form, "confirm")}
    allowed, code, why, source = _gate(handler, endpoint="POST /api/task")
    done = _replier(handler, "/api/task", source, seen)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not body:
        return done(400, "拒绝：插话内容不能为空", False)
    if not _flag(form, "confirm"):
        return done(400, "拒绝：插话会改变正在跑的那一趟的做法，必须带 confirm=1", False)
    sid_problem = _interject_sid_problem(sid)
    if sid_problem:
        return done(400, f"拒绝：{sid_problem}", False)
    if dry:
        return done(200, "试运行：没有写任何一条插话", True, extra={"dry_run": True})
    try:
        iid, problem = AL.send_interjection(root, sender=U.USER, subject=subject,
                                            body=body, sid=sid)
    except Exception as exc:  # noqa: BLE001 - 写失败不许折成 200
        return done(500, f"没写成：{type(exc).__name__}: {exc}", False)
    if problem:
        return done(400, f"没写成：{problem}", False)
    return done(200,
                f"已投递（{iid}）：主控会在下一步开头读到，当前这一步不被打断",
                True, ident=iid, extra={"interjection_id": iid, "sid": sid})


#: 两条"说话"的端点在下面才定义（它们的正文紧邻本段之上）⇒ 注册放在这里，
#: 免得 `HANDLERS.update` 引用尚未绑定的名字。
# ====================================================================== 板项收口 / 撤销叫停（WEBFIX2 F7 · F9）
def _board_row(root: Path, task_id: str) -> dict[str, Any] | None:
    """台账里那一行（读不成返回 `None`：这是"没读到"，由调用方如实说）。"""
    try:
        rows = Store(root).rows("tasks")
    except (StoreError, OSError):
        return None
    for row in rows:
        if str(row.get("task_id") or "") == task_id:
            return dict(row)
    return None


def handle_ack(handler: Any, params: Mapping[str, str],
               query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/ack`：把一条板项收口（`item_state=done`）—— 用户在网页上的那只"手"。

    业主 2026-11-21 的现场：真机 `projects/lp-ball-15` 有 6 条未收口的 `notice` 板项，
    而网页上没有任何入口能收口它们 —— 路由表里没有这一条，于是它们只能等某个代理
    自己下一次醒来 ack。这一条补的就是那个入口（审计 F7）。

    ## 状态机不在这里（这是本端点的全部纪律）

    收口只有一条判定与写入点：`conductor.close_item(task_id, close=…)`
    （`conductor.py::_set_item` → `item_move` 迁移图）。本模块不判"这一项能不能
    ack"、不写行、也不自己推迁移 —— 它只把状态机给的结论转成回执，并回读那一行：

    | 台账里落成的样子 | HTTP | `tri` |
    |---|---|---|
    | `item_state=done`（迁移图放行） | 200 | `computed` |
    | 没到 `done`（空口 ack / 已到过 `block` / 不是板项 / 没这一项） | 409 | `not_applicable` |

    为什么要回读：`close_item` 在"空口 ack（业主 A5：没 `seen` 就 ack）"那一档回的
    不是空串而是 `"ack_unbacked"`（`conductor.py::_set_item` 第 2 条，`changed=False`），
    只看"返回值非空"会把一次零写入读成"收口了"。所以这里取 `tasks` 里那一行的
    `item_state` / `item_close` —— 与页面看到的是同一份事实。

    请求字段：`task_id` · `close`（`acked` / `completed` / `expired`，缺省 `acked`；
    闭集是 `schema.ITEM_CLOSES`）· `confirm=1`。
    三态：没开写面 / CSRF 不对 / 跨站来源 ⇒ 403；缺 `confirm` / 参数不合法 ⇒ 400
    （盘上一个字节不动）；状态机拒绝 ⇒ 409 并逐字给出它那句话；写抛异常 ⇒ 500。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    task_id = _one(form, "task_id").strip()
    close = _one(form, "close").strip() or "acked"
    seen = {"task_id": task_id, "close": close, "confirm": _flag(form, "confirm")}
    allowed, code, why, source = _gate(handler, endpoint="POST /api/ack")
    done = _replier(handler, "/api/ack", source, seen)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not _flag(form, "confirm"):
        return done(400, ("拒绝：收口一条板项要 confirm=1 一次显式确认"
                          "（它会让一条还在板上的事项从待办里消失）"), False)
    if not task_id:
        return done(400, "拒绝：task_id 不能为空 —— 要说清收口哪一条", False)
    if close not in S.ITEM_CLOSES:
        return done(400, f"拒绝：close 只认 {S.ITEM_CLOSES}（收到 {close!r}）", False)
    try:
        store = Store(root)
        store.init()
    except (StoreError, OSError) as exc:
        return done(400, ("拒绝：这个工作区没有 data/（没 `agentflow init` 过），"
                          f"没有台账可改 —— {type(exc).__name__}: {exc}"),
                    False, tri=TRI_NOT_APPLICABLE)
    from ..conductor import Conductor  # noqa: PLC0415 - 只在真收口时才装这一层

    try:
        state, problem = Conductor(store).close_item(task_id, close=close)
    except Exception as exc:  # noqa: BLE001 - 结局说不清 ⇒ unreadable，不折成成功
        return done(500, (f"没收口：{type(exc).__name__}: {exc}"
                          "（事务未提交，盘上那份没被动过）"), False)
    row = _board_row(root, task_id) or {}
    item_state = str(row.get("item_state") or "")
    if item_state != "done":
        return done(409, (f"没收口 {task_id}：{problem or '状态机没有把它推到 done'}"
                          f"（台账里现在是 item_state={item_state or '（空）'}）"), False,
                    tri=TRI_NOT_APPLICABLE,
                    extra={"task_id": task_id, "state_machine": state,
                           "item_state": item_state,
                           "item_close": str(row.get("item_close") or ""),
                           "seen_by": str(row.get("seen_by") or "")})
    extra = {"task_id": task_id, "item_state": item_state,
             "item_close": str(row.get("item_close") or ""),
             "seen_by": str(row.get("seen_by") or ""),
             "kind": str(row.get("kind") or ""),
             "expects": str(row.get("expects") or ""),
             "detail": str(row.get("detail") or "")[:200]}
    # 收口写的是 `tasks` 台账，不经过三个会话钩子 ⇒ 页面要刷新得靠这一帧。
    try:
        from . import sse as SSE  # noqa: PLC0415 - 避免导入期成环

        SSE.notify_state(root)
    except Exception:  # noqa: BLE001 - 推不出去不许把"已经收口了"改写成失败
        extra["notify_problem"] = "state 帧没推出去（这一笔已经落盘）"
    return done(200, f"已收口 {task_id}（item_state={item_state} · close={close}）",
                True, ident=task_id, extra=extra)


def handle_stop_clear(handler: Any, params: Mapping[str, str],
                      query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/stop/clear`：撤掉盘上的停机开关 —— "撤销叫停"那只手（审计 F9）。

    现场：叫停之后开关一直留在盘上（没有任何在跑的循环去消费它），于是"用户从网页
    再起一趟"的那一趟第一步就被这把旧开关停掉 —— 白起一趟。而路由表里没有撤销入口
    （`stopctl.clear_stop` 只有 CLI 一个调用者，`cli.py:4734`）。

    ## 唯一写入口

    删开关只有 `stopctl.clear_stop(root)` 一处（它同时通知 `set_stop_hook` 上的监听器
    `action="cleared"`，于是别的正在跑的进程也会看到"叫停被撤销了"）。本模块不 unlink
    那个文件、也不自己判"该不该撤"。

    请求字段：`confirm=1`（与其余写端点同一条闸；撤错一次叫停的代价是"这一趟本来要停
    却没停"，所以仍然要一次显式确认）。
    三态：没开写面 / CSRF 不对 / 跨站来源 ⇒ 403；缺 `confirm` ⇒ 400；撤失败 ⇒ 500。
    盘上本来就没有开关 ⇒ 200 + `extra.cleared=false`：那是"你要的状态已经成立"，
    与"撤掉了"分开说（不许折成同一个"成功"，也不许折成失败）。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    seen = {"confirm": _flag(form, "confirm")}
    allowed, code, why, source = _gate(handler, endpoint="POST /api/stop/clear")
    done = _replier(handler, "/api/stop/clear", source, seen)
    if not allowed:
        return done(code, f"拒绝：{why}", False)
    if not _flag(form, "confirm"):
        return done(400, ("拒绝：撤销叫停要 confirm=1 一次显式确认"
                          "（撤错会让本该停的那一趟继续跑）"), False)
    try:
        before = SC.read_stop(root) or {}
    except Exception:  # noqa: BLE001 - 读不成不猜：clear_stop 自己会再读一次
        before = {}
    try:
        cleared = bool(SC.clear_stop(root))
    except Exception as exc:  # noqa: BLE001 - 撤失败不许折成 200
        return done(500, (f"没撤掉：{type(exc).__name__}: {exc}"
                          "（盘上那一份没被动过）"), False)
    now = SC.read_stop(root)
    extra = {"cleared": cleared,
             # 撤之前那一份原样带出去（谁按的、什么理由、什么时候）——
             # 撤掉之后盘上已经读不到它了，这一格是这一笔唯一的留痕。
             "cleared_switch": before,
             "switch_present": now is not None,
             "stop_path": str(SC.stop_path(root))}
    try:
        from . import sse as SSE  # noqa: PLC0415 - 同 handle_ack

        SSE.notify_state(root)
    except Exception:  # noqa: BLE001 - 推不出去不改写"已经撤掉了"
        extra["notify_problem"] = "state 帧没推出去（这一笔已经落盘）"
    if not cleared:
        return done(200, ("盘上本来就没有停机开关 —— 当前没有叫停"
                          "（这一下没有改动任何东西）"), True, extra=extra)
    by = _text(before.get("by")) or "?"
    reason = _text(before.get("reason")) or "?"
    return done(200, (f"已撤销叫停（撤掉了 {by} 在 {reason} 上落的那把开关）"
                      "—— 当前没有叫停，再起一趟不会被它停掉"), True, extra=extra)

def handle_void(handler: Any, params: Mapping[str, str],
                query: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """`POST /api/void`：把一条不再需要做的板项作废（`item_close=expired`）。

    现场（BOARDACK，2026-11-21）：真机 `projects/lp-ball-15` 有 6 条 `notice` 板项停在
    `item_state=block`（优雅停止翻的），网页上收不了口。`/api/ack` 对这 6 条只能回 409
    —— `conductor.py::ITEM_MOVES` 里 `("block","done")` 是 `back`（倒退），那一档
    不许在端点这一层越过（越过就等于把迁移图与业主 A5 的空口 ack 闸一起放开）。

    另一条合法路是"唤醒 ⇒ 再 ack"，实测也不通：唤醒把 `seen_by` 清空 ⇒ `close_item`
    回 `ack_unbacked`（空口 ack）。而作废本来就不走状态机（`void_items` 边界 3：
    作废描述的是"不会有人读"，不是"有人读过"）⇒ 这一条端点接的就是那条路。

    ## 唯一写入口

    `Conductor.void_items_by_user(item_ids=[…], why=…)`（≡ `void_items(revoke=True,
    by_human=True)`）。本模块不判"这一项能不能撤"、不写行、不自己推迁移：只把
    conductor 的结论转成回执，并回读那一行判成败（与 `/api/ack` 同一条纪律）。

    | 台账里落成的样子 | HTTP | `tri` |
    |---|---|---|
    | `item_state=done` ＋ `item_close=expired`（作废落成） | 200 | `computed` |
    | 已经终态（重复作废，一格不改） | 200 | `computed`（`extra.already_closed=true`） |
    | 不是板项 / 没有这一项 / 读不成 | 409 或 500 | `not_applicable` / `unreadable` |

    为什么"已经终态"是 200 而不是 409：用户要的状态（这一条不在待办里）已经成立，
    与 `/api/stop/clear` 的 `cleared=false` 同一条三态口径（"已经是"≠"刚做成"），
    用 `extra.already_closed` 把两档分开说。

    请求字段：`task_id` · `why`（必填，逐字进那一行的 `inputs` 与事件 note）·
    `confirm=1`。三态：没开写面 / CSRF 不对 / 跨站来源 ⇒ 403；缺 `confirm` /
    缺 `why` / 空 `task_id` ⇒ 400（盘上一个字节不动）；conductor 拒 ⇒ 409 并把它的
    原话带出来；写抛异常 ⇒ 500。
    """
    del params, query
    form = handler._form()
    root = Path(handler.root)
    task_id = _one(form, "task_id").strip()
    why = " ".join(_one(form, "why").split())
    seen = {"task_id": task_id, "why": why, "confirm": _flag(form, "confirm")}
    allowed, code, gate_why, source = _gate(handler, endpoint="POST /api/void")
    done = _replier(handler, "/api/void", source, seen)
    if not allowed:
        return done(code, f"拒绝：{gate_why}", False)
    if not _flag(form, "confirm"):
        return done(400, ("拒绝：作废一条板项要 confirm=1 一次显式确认"
                          "（作废不可逆：这一条会从待办里消失，且义务不再要求完成）"),
                    False)
    if not task_id:
        return done(400, "拒绝：task_id 不能为空 —— 要说清作废哪一条", False)
    if not why:
        # 理由不是形式：`revoke:expired:` 那一格是事后复核"谁凭什么撤的"的唯一落点，
        # 缺了它这一笔在盘点时无从复核（`void_reason_or_derived` 会补一句，但那是
        # 给代理那条路的兜底，不是给人这条路的口径）。
        return done(400, ("拒绝：why 不能为空 —— 作废要写清「为什么这一条不用再做了」"
                          "（逐字进那一行的 inputs 留痕）"), False)
    try:
        store = Store(root)
        store.init()
    except (StoreError, OSError) as exc:
        return done(400, ("拒绝：这个工作区没有 data/（没 `agentflow init` 过），"
                          f"没有台账可改 —— {type(exc).__name__}: {exc}"),
                    False, tri=TRI_NOT_APPLICABLE)
    from ..conductor import Conductor  # noqa: PLC0415 - 只在真作废时才装这一层

    try:
        got = Conductor(store).void_items_by_user([task_id], why=why)
    except Exception as exc:  # noqa: BLE001 - 结局说不清 ⇒ unreadable，不折成成功
        return done(500, (f"没作废：{type(exc).__name__}: {exc}"
                          "（事务未提交，盘上那份没被动过）"), False)
    row = _board_row(root, task_id) or {}
    item_state = str(row.get("item_state") or "")
    extra = {"task_id": task_id, "item_state": item_state,
             "item_close": str(row.get("item_close") or ""),
             "expects": str(row.get("expects") or ""),
             "expects_was": str(row.get("expects_was") or ""),
             "kind": str(row.get("kind") or ""),
             "voided": [str(x) for x in (got.get("voided") or ())],
             "traces": [dict(t) for t in (got.get("traces") or ())],
             "already_closed": False}
    if not got.get("checked"):
        return done(500, (f"没作废 {task_id}：{got.get('reason') or '台账读不成'}"
                          "（不是「已经作废」）"), False, tri=TRI_UNREADABLE,
                    extra=extra)
    if item_state != "done":
        refused = [dict(r) for r in (got.get("refused") or ())]
        first = str((refused[0].get("why") if refused else "") or "")
        return done(409, (f"没作废 {task_id}："
                          f"{first or got.get('reason') or '作废没有落成'}"
                          f"（台账里现在是 item_state={item_state or '（空）'}）"), False,
                    tri=TRI_NOT_APPLICABLE, extra=extra)
    if task_id not in (extra["voided"] or []):
        # 走到这里 = 这一条在作废之前就已经是终态（conductor 那一档零写入）。
        extra["already_closed"] = True
        extra["reason_already"] = (
            "这一条在作废之前就已经收口了（conductor 报「已经是终态」）⇒ 这一下没有改动任何格")
    try:
        from . import sse as SSE  # noqa: PLC0415 - 同 handle_ack

        SSE.notify_state(root)
    except Exception:  # noqa: BLE001 - 推不出去不许把"已经作废了"改写成失败
        extra["notify_problem"] = "state 帧没推出去（这一笔已经落盘）"
    if extra["already_closed"]:
        return done(200, f"{task_id} 已经是收口状态（item_state={item_state}）—— 这一下没有改动",
                    True, ident=task_id, extra=extra)
    return done(200, (f"已作废 {task_id}（item_close=expired · 原 expects="
                      f"{extra['expects_was'] or '（空）'}）—— 这一条不再欠动作"),
                True, ident=task_id, extra=extra)


HANDLERS.update({
    "handle_start_run": handle_start_run,
    "handle_interject": handle_interject,
    "handle_ack": handle_ack,
    "handle_void": handle_void,
    "handle_stop_clear": handle_stop_clear,
})


# ====================================================================== 回答（既有写路径）
def _answer_refusal(code: int, why: str) -> str:
    """一次被写面闸门拒掉的回答 ⇒ 与 409 同形的错误卡片（不另造一套错误体）。

    `kind` / `how_to_fix` 来自 :func:`refusal_reading`：那是写端点共用的分档词表
    （`csrf_token` / `writes_off` / `foreign_origin` / …），页面上读到的分档与
    `/api/*` 那些端点逐字相同；这一层只把这两格翻译成同一张 `.card.problem`。
    """
    kind, how_to_fix = refusal_reading(code, why)
    return ('<div class="card problem"><div class="card-head">'
            f'<span class="badge badge-fail">{code} · 写回答被拒</span></div>'
            f'<div class="readings">{_e(why)}</div>'
            f'<div class="readings">分档 <span class="mono">{_e(kind)}</span>；'
            f"怎么办：{_e(how_to_fix)}</div>"
            '<div class="readings"><a href="/">回首页</a></div></div>')


def answer(root: Path, form: Mapping[str, Sequence[str]],
           *, handler: Any, audit_enabled: bool = True) -> tuple[int, str, str]:
    """处理一次回答提交：返回 `(状态码, 重定向目标, HTML 正文)`。

    闸门（2026-11-21 WEBFIX1 / 审计 F4）：它与其余写端点走同一处 :func:`_gate`
    （回环来源 ⇒ CSRF ⇒ `allow_writes`）。`handler` 是 A 线
    `WebHandler.handle_answer` 交下来的请求句柄 —— 没有它就判不了来源与令牌，
    所以它有实参、且没有缺省值。拒时 403 + :func:`_answer_refusal`（kind /
    how_to_fix 与 `/api/*` 同一份词表），盘上零写入。

    三态纪律：闸门放行之后，qid 不在待答清单里 ⇒ 409（不是 200），并在页面上
    说清是哪一档：已经被谁什么时候答过、还是根本没有这个号。写失败 ⇒ 500 并
    原样给出错误。

    审计（裁定 D2）：每一次到达写面的提交（含 403 / 409 / 500 那三档）都追加一行
    `web-actions.jsonl`。为什么审计失败不改状态码：本函数的三个返回值是 A 线
    `handle_answer` 与 `tests/test_webui.py` 钉死的契约，"写成了但没审计上"
    不该被折叠成"写失败"（那会把一次真实的落盘说成没发生）。所以审计失败走 stderr。

    `audit_enabled`：只读档（没开 `--allow-writes`）传 `False` ——
    那时闸门先回 403 `writes_off`，台账不落盘，这一笔只进 stderr。"只读"这个词
    必须守住：写 `<工作区>/web-actions.jsonl` 就是在别人的目录里新建文件。
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
        if not audit_enabled:
            # E7：只读档不写盘（`<工作区>/web-actions.jsonl` 也是盘上的一个文件）。
            sys.stderr.write(f"[webui] 只读档不落审计（/answer → http {code}）\n")
            return code, location, body
        _row, problem = audit.record_action(
            root, endpoint="/answer", source=source, params=params,
            result=f"http {code}",
            tri=TRI_COMPUTED if code == 303 else TRI_NOT_APPLICABLE,
            ok=code == 303, http=code)
        if problem:
            # 审计落不下这件事必须说出口（三态纪律），但这个函数的返回契约不许改
            # ⇒ 唯一的出口是 stderr（服务端日志）。
            sys.stderr.write(f"[webui] 审计台账写失败（/answer）：{problem}\n")
        return code, location, body

    # 先过闸门再读表单：未授权的尝试连"这条 qid 在不在"都不该问出来。
    allowed, code, why, source = _gate(handler, endpoint="POST /answer")
    if not allowed:
        return done(code, "", _answer_refusal(code, why))

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

# ====================================================================== 两档提示词缓存的写端点
# 业主：「换 key 时自动提醒重落受影响智能体的缓存」这一条要能在网页上按下去，
# 所以缓存预热也走写面。两条端点（`GET /api/cache` 只读 + `POST /api/cache/warm` 写）的
# 实现落在 `cacheface.py`，这里只是把它的子表并进本模块那两张表 —— 于是写面的授权矩阵
# （回环来源 → CSRF → `--allow-writes`）与审计台账对它逐条生效，不是因为"它长得像写端点"。
# 为什么并进写面子表而不是新开一段：`routes.compose` 的拼接公式是
# `自有 + READER_ROUTES + WRITE_ROUTES`，改公式要同时改判据（`test_a_the_subtables_really
# _reach_the_composed_route_table` 那条负控逐字比三个参数）。把两条端点并进写面子表，
# 拼接公式一个字都不用动，而"谁实现它们"仍然只有一处可读（`cacheface.py`）。
from .cacheface import HANDLERS as _CACHE_HANDLERS, ROUTES as _CACHE_ROUTES  # noqa: E402

ROUTES = ROUTES + _CACHE_ROUTES
HANDLERS.update(_CACHE_HANDLERS)
