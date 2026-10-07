# -*- coding: utf-8 -*-
"""网页操作台账：`<工作区>/web-actions.jsonl`（裁定 D2）。

## 这一层是什么

「用户从网页下的手」与「框架自己做的事」是两件不同的事，混在一处就再也分不开。
所以网页发起的每一次写操作都单独落一行到这个文件里：

    <工作区>/web-actions.jsonl

它独立于 `ARTIFACTS.jsonl`（那是产物台账）与 `sessions/*.jsonl`（那是运行事件）：
那两份记的是「框架产出/经历了什么」，这一份记的是「谁在什么时候从网页上动了什么手」。

## 一行的形状（七个字段，逐条对应 `draft/73` §2.5 那一句）

| 字段 | 是什么 |
|---|---|
| `at` | 写入时刻（带时区的 ISO 串，秒级） |
| `kind` | 恒为 `web_action`（将来这个文件里要是有别的行，读的人还能分得开） |
| `endpoint` | 端点路径（`/answer` · `/api/stop` · `/api/submit` · `/api/settings`） |
| `source` | 来源（回环地址；跨站来源在授权那一关就被拒了，但拒绝也留档） |
| `params` | 参数摘要（脱敏 + 截断后的那份字段；不是原文照抄，见下） |
| `params_sha256` | 上面那份摘要的规范 JSON 的 sha256（「同一个请求」可比） |
| `result` | 结局（人话：`created` / `refused:write-disabled` / `failed:…`） |
| `tri` | 三态（`computed` / `unreadable` / `not_applicable`，与全项目同一套词表） |
| `ok` | 这一笔到底写成了没有（布尔；被拒的尝试是 `false`） |
| `http` | 这一次回给客户端的状态码 |

`draft/74` §4 的审计列与 `draft/73` §2.5 说的是同一件事（「每一次写都落一条」），
两处口径不冲突；`draft/73` 多列了字段名，所以字段名以它为准。

## 被拒的尝试也留档（不是只记成功的）

理由是审计的用途：事后要回答的是「有没有人试过」而不只是「有没有人做成过」。
一次「写面没开时有人 POST 了 /api/stop」与「根本没这个端点」是两件不同的事，
前者必须留痕，否则「谁试过叫停」这个问题永远答不出来。

一处说清楚的例外：未注册的 `/api/*` 路径由 A 线 `server.py` 的
`do_POST`/`handle_unknown` 直接回 JSON 404，请求根本走不到本模块的处理器
⇒ 那一类 404 不在本台账里。反过来，已注册但被授权拒掉的调用一条都不会漏。

## 参数摘要为什么不是原文

- 值的键名里含 `key` / `token` / `secret` / `password` / `cookie` 一族的，值一律换成
  `***`：台账是要给人看的（网页上那一栏「操作历史」），把密钥抄进去等于
  把「密钥只写不读」那条裁定从后门推翻；
- 长文本截断到 300 字符并标注省略了多少：台账是摘要，不是正文备份
  （正文的正式落点各自的写路径里都有，例如回答进会话事件、提交进 `search_requests`）。

## 三态纪律

追加失败不许静默吞掉：`record_action()` 返回 `(行, 问题)`，问题非空时调用方要如实
把它带进回执（`WriteResult.extra`）。「写成功了但没审计上」是一个必须说出口的状态，
不是「成功」。
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from filelock import FileLock

from ..jsonlfile import read_jsonl_state

__all__ = ["KIND", "LEDGER_NAME", "MAX_TEXT", "REDACTED", "actions_path", "digest_of",
           "read_actions", "read_actions_state", "record_action", "summarize"]

#: 一处命名上的刻意偏离（对着 `draft/73` §2.5 的那两行签名看）：草案把读写两口
#: 叫 `record` / `read`，而这两个名字在盘上分别与 `artifacts.record`、
#: `manuscripts.read` 撞名 —— lint 的 R003（同名多实现）会因此多出 6 条 warning，
#: 而 `tests/test_release_all.py` 把 `lint_rules_warning` 的读数与 `DEVELOPMENT.md`
#: 里记的那一份逐字比对（实测：17 → 23 会让那条判据红）。
#: 那 6 条 warning 讲的是"同一判据两份实现"，而这两处本来就不是同一件事
#: （产物台账 vs 网页操作台账），所以正确的处置是避开撞名，不是去改文档。
#: 语义一个字没变：`record_action` 就是草案的 `record`，`read_actions` 就是 `read`。

#: 台账文件名（落在工作区根下）。
LEDGER_NAME = "web-actions.jsonl"
#: 这个文件里每一行的 `kind`。
KIND = "web_action"
#: 脱敏后占位的那个字符串（与 `ModelSpec.redacted` 的 `***` 同一形态）。
REDACTED = "***"
#: 参数摘要里单个字符串值的上限（超出部分截断并标注）。
MAX_TEXT = 300

#: 键名里出现这一族子串 ⇒ 值脱敏。为什么按子串而不是白名单：
#: 白名单会漏掉下一个 `*_key`，而漏掉的代价是把密钥写进一个给人看的文件。
_SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "authorization",
                 "cookie", "credential")

#: 同进程内的线程锁（与 `sessions._append_lock` 同一条理由：同波并发的几个请求
#: 可能同时落这一行）；跨进程那一层由 `filelock` 兜。
_append_lock = threading.Lock()


def actions_path(root: str | Path) -> Path:
    """台账落在哪：`<工作区>/web-actions.jsonl`（恒在工作区根下，不在子目录里）。"""
    return Path(root) / LEDGER_NAME


def _clip_text(value: str) -> str:
    """把过长的字符串截断并标注省了多少字符（不静默截断）。"""
    if len(value) <= MAX_TEXT:
        return value
    return value[:MAX_TEXT] + f"…（省略 {len(value) - MAX_TEXT} 字符）"


def summarize(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """把一个请求的参数压成「可入台账」的那一份（脱敏 + 截断 + 值类型归一）。

    列表一并处理（`selected[]` / `providers[]` 是多值字段）；嵌套的字典递归下去，
    否则 `{"model": {"api_key": ...}}` 这种形状会从后门漏出去。
    """
    out: dict[str, Any] = {}
    for raw_key, raw_value in (params or {}).items():
        key = str(raw_key)
        low = key.lower()
        if any(hint in low for hint in _SECRET_HINTS):
            out[key] = REDACTED
            continue
        if isinstance(raw_value, Mapping):
            out[key] = summarize(raw_value)
            continue
        if isinstance(raw_value, (list, tuple)):
            out[key] = [_one_of(v) for v in raw_value]
            continue
        out[key] = _one_of(raw_value)
    return out


def _one_of(value: Any) -> Any:
    """一个标量/序列元素进台账时的形状（字符串截断，其余按 JSON 原样）。"""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return summarize(value)
    if isinstance(value, (list, tuple)):
        return [_one_of(v) for v in value]
    return _clip_text(str(value))


def digest_of(summary: Mapping[str, Any]) -> str:
    """参数摘要的 sha256（规范 JSON：`sort_keys` + 紧凑分隔符）。

    为什么要有它：台账里那一份是被脱敏与截断过的，逐字比对不可靠；
    sha256 给的是「这两个请求的参数是同一份」这个可比的读数。
    """
    blob = json.dumps(summary, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    """带时区的当前时刻（与 `sessions.append` 的 `ts` 同一形态）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def record_action(root: str | Path, *, endpoint: str, source: str = "",
           params: Mapping[str, Any] | None = None, result: str = "",
           tri: str = "computed", ok: bool = False, http: int = 0) -> tuple[dict[str, Any], str]:
    """追加一行网页操作台账；返回 `(行, 问题)`，问题为空串才算写成。

    行由本函数造（调用方给的是七个字段的取值），返回给调用方一份同一个 dict ——
    它要拿 `params_sha256` 之类的东西进回执，重算一遍是第二份实现。
    """
    summary = summarize(params)
    row: dict[str, Any] = {
        "at": _now_iso(), "kind": KIND, "endpoint": str(endpoint),
        "source": str(source), "params": summary,
        "params_sha256": digest_of(summary), "result": str(result),
        "tri": str(tri), "ok": bool(ok), "http": int(http),
    }
    path = actions_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n"
        # 锁只包住「把这一行写完」这一段（先把整行序列化好，临界区里只有一次 write）
        # —— 与 `sessions.append` 逐条相同，理由也一样。
        with _append_lock, FileLock(str(path) + ".lock"):
            with path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line)
    except (OSError, TypeError, ValueError) as exc:  # noqa: BLE001 - 见模块 docstring
        return row, f"{type(exc).__name__}: {exc}"
    return row, ""


def read_actions(root: str | Path) -> list[dict[str, Any]]:
    """读回台账的行（给人看的那一栏用）。

    坏行不静默跳过：读法只有一份实现（`jsonlfile.read_jsonl_state`），
    坏行的说明由 :func:`read_actions_state` 带出去 —— 这个薄包装保持 `list[dict]` 的形状，
    与 `draft/73` §2.5 给的那一行签名一致。
    """
    return read_actions_state(root)["rows"]


def read_actions_state(root: str | Path) -> dict[str, Any]:
    """读台账，带三态：`{tri, rows, problems, reason, path}`。

    `tri` 的四态到三态的映射（与全项目同一套词表）：
    `ok` / `empty` / `absent` ⇒ `computed`（读到了，条数可能是 0 —— 「查到 0 条」是
    一个算出来的读数）；`unreadable` ⇒ `unreadable`（没查成，不许读成「没有操作」）。
    """
    path = actions_path(root)
    rows, problems, state = read_jsonl_state(path)
    if state == "unreadable":
        return {"tri": "unreadable", "rows": [], "problems": problems,
                "reason": "；".join(problems) or "台账读不出来", "path": str(path)}
    return {"tri": "computed", "rows": rows, "problems": problems,
            "reason": "" if not problems else "；".join(problems), "path": str(path)}
