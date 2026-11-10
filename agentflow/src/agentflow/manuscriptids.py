# -*- coding: utf-8 -*-
"""F 自己的手稿号源（业主 2026-11-10 裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号」）。

## 为什么另起一个号段、不走 `store.alloc_id`

`store.alloc_id(kind)` 的契约是"取号 + 在建行的那张表里查占用"：它要求事务声明目标表，
否则受控抛 `StoreError`（`F-2`：跳过占用检查会让发号器发出已被占用的号，而 `upsert`
按主键静默覆盖旧行）。手稿没有表 —— 它的占用面是盘上的 `reports/f-proof-<号>.md`。
所以手稿号走这里：同一个 `data/counters.json`、同一个六位形制，但占用检查的对象是
`reports/` 里的文件。

## 三条纪律（判据 `tests/test_f_manuscript_ids_are_its_own_source.py`）

1. 占用检查：`reports/f-proof-<号>.md` 已存在 ⇒ 号继续往前推，绝不覆盖别人的稿；
2. 并发安全：同一进程内串行（模块级 `RLock`）；跨进程并发不在本号源的承诺里
   （手稿只由 F 这一条线写，`store` 的写者锁管不到 `reports/`）；
3. 越界保护：六位用尽（`999999` 之后）⇒ 受控抛 :class:`ManuscriptIdError`，
   不静默升位宽（与 `store.alloc_id` 的 `IdExhausted` 同一条口径）。

计数器键是 `manuscript`，与 `stmt` / `plan` 并列（`data/counters.json` 的 `counters`
映射里）。语义与 `store.alloc_id` 一致：值 = 下一个待试的号，发出去之后推成 `号 + 1`；
漂移（手改了文件 / 旧盘上已经有稿）用"往前推"自愈，不静默回绕。
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from . import schema as _S

#: `data/counters.json` 里手稿这一档的键（与 `stmt` / `plan` 并列）。
COUNTER_KEY = "manuscript"

#: 手稿落点目录（工作区相对）。与 `manuscriptfamily.MANUSCRIPT_DIR` 同一个值 ——
#: 这里不 import 它，避免 `manuscriptfamily` → `vsigns` → … 的循环。
MANUSCRIPT_DIR = "reports"

#: 六位形制（`schema.ID_DIGITS` 的唯一来源；这里只做本模块自己的越界判断）。
ID_DIGITS = _S.ID_DIGITS
MAX_ID = 10 ** ID_DIGITS - 1

#: 计数器文件（工作区相对）。
COUNTERS_REL = "data/counters.json"

#: 同一进程内串行取号（跨进程不在承诺里，见模块 docstring）。
_LOCK = threading.RLock()


class ManuscriptIdError(RuntimeError):
    """手稿号发不出来（号段用尽 / 计数器文件不可用）。受控异常，不是"没号可用"。"""


def format_id(n: int) -> str:
    """整数 ⇒ 六位手稿号（与 `schema.format_id` 同一形态）。"""
    return _S.format_id(int(n))


def is_manuscript_id(value: Any) -> bool:
    """这个字符串是不是一个合法的六位手稿号（旧四位号不再作为新稿号，见下）。"""
    text = str(value or "").strip()
    return (len(text) == ID_DIGITS and text.isdigit()
            and 0 <= int(text) <= MAX_ID)


def canonical_rel(manuscript_id: Any, proof_no: Any = 1) -> str:
    """手稿号 ⇒ 规范手稿路径：`reports/f-proof-<号>[-p<N>].md`。

    `-p<N>` 是同一份稿的第 N 份证明（老后缀，与计划无关）；`N<2` 不写后缀。
    号形不对 ⇒ 空串（不猜、不拼一个看起来像号的路径）。
    """
    mid = str(manuscript_id or "").strip()
    if not is_manuscript_id(mid):
        return ""
    try:
        no = int(proof_no or 1)
    except (TypeError, ValueError):
        no = 0
    if no < 1:
        no = 1
    suffix = f"-p{no}" if no >= 2 else ""
    return f"{MANUSCRIPT_DIR}/f-proof-{mid}{suffix}.md"


def manuscript_path(root: Any, manuscript_id: Any, proof_no: Any = 1) -> str:
    """手稿号 ⇒ 工作区相对路径（`canonical_rel` 的别名，便于调用方读）。"""
    return canonical_rel(manuscript_id, proof_no)


def _root_of(root: Any) -> Any:
    """`root` 可以是工作区路径，也可以是带 `.root` 的 `Store`。

    注意 `pathlib.Path.root` 是路径锚点（`"\\"` / `"/"`）—— 不能拿 `getattr(root, "root")`
    判类型，否则传路径进来会被读成盘符根，号源写到别处去。
    """
    if isinstance(root, (str, bytes, Path)):
        return root
    return getattr(root, "root", root)


def _counters_path(root: Any) -> Path:
    return Path(str(_root_of(root))) / COUNTERS_REL


def _read_doc(root: Any) -> dict:
    """读 `data/counters.json`；读不出来 ⇒ 空计数器（坏值当 0，与 `store.alloc_id` 同口径）。

    读不出来不是"没有号可用"：占用检查会兜住被占的号，而计数器落后只是多发一次
    候选号。文件坏到完全不是对象时才当空文档（不让一次 `json.JSONDecodeError` 变成
    traceback）。
    """
    path = _counters_path(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {"schema_version": _S.SCHEMA_VERSION, "counters": {}}
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"schema_version": _S.SCHEMA_VERSION, "counters": {}}
    if not isinstance(doc, dict):
        return {"schema_version": _S.SCHEMA_VERSION, "counters": {}}
    counters = doc.get("counters")
    if not isinstance(counters, dict):
        doc["counters"] = {}
    return doc


def _write_doc(root: Any, doc: dict) -> None:
    """把 counters 文档原子写回（临时名带 pid + 线程 id，`os.replace` 同目录原子）。"""
    path = _counters_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    payload = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False,
                         default=str) + "\n"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as exc:  # noqa: BLE001 —— 写不进去要受控报出来，不是"号发完了"
        # 临时文件删不掉不影响主文件是否落盘：它只会在同目录留一个 .tmp，
        # 清理失败不该把"这一号没发出去"的受控异常换成另一个异常。
        try:
            tmp.unlink(missing_ok=True)
        except OSError:  # noqa: BLE001 —— 见上：清理失败不改变本笔的结论
            pass
        raise ManuscriptIdError(
            f"手稿号计数器写不进去（{type(exc).__name__}: {exc}）⇒ 这一号没发出去"
        ) from exc


def _occupied(root: Any, manuscript_id: str) -> bool:
    """`reports/f-proof-<号>.md` 在不在（占用检查只看规范名，见模块 docstring）。"""
    rel = canonical_rel(manuscript_id)
    return bool(rel) and (Path(str(_root_of(root))) / rel).is_file()


def reserved_manuscript_id(root: Any, manuscript_id: Any) -> bool:
    """这个号在盘上已经有一份稿（供调用方判"复用同一份稿"时核占用）。"""
    return _occupied(root, str(manuscript_id or "").strip())


def next_manuscript_id(root: Any) -> str:
    """发一个 F 自己的手稿号：`counters.manuscript` + 1，占用就继续往前推。

    返回六位号（如 `000003`）；发完把计数器推到 `号 + 1`。号段用尽 ⇒
    :class:`ManuscriptIdError`（受控，不静默升位宽）。
    """
    with _LOCK:
        doc = _read_doc(root)
        counters = doc.setdefault("counters", {})
        raw = counters.get(COUNTER_KEY, 0)
        try:
            nxt = int(raw)
        except (TypeError, ValueError):
            nxt = 0
        if nxt < 0:
            nxt = 0
        # 占用检查：规范名已存在 ⇒ 这不是"空号"，绝不覆盖别人的稿。
        while nxt <= MAX_ID and _occupied(root, format_id(nxt)):
            nxt += 1
        if nxt > MAX_ID:
            raise ManuscriptIdError(
                f"手稿号段（{ID_DIGITS} 位）已用尽（上限 {MAX_ID}）。"
                "请勿静默升位宽 —— 那会破坏所有历史手稿号的解析；"
                "要么手工归档 `reports/` 里的旧稿，要么由人裁定新号段。"
            )
        allocated = format_id(nxt)
        counters[COUNTER_KEY] = nxt + 1
        _write_doc(root, doc)
        return allocated


def peek_manuscript_counter(root: Any) -> int:
    """只读：计数器现在指到哪（不写盘）。读不出来 ⇒ 0（"没查成"由调用方按占用面判）。"""
    doc = _read_doc(root)
    try:
        return int((doc.get("counters") or {}).get(COUNTER_KEY, 0))
    except (TypeError, ValueError):
        return 0
