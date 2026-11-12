# -*- coding: utf-8 -*-
"""两个重读面的按盘失效缓存（`/api/package` 与 `/api/artifacts`）。

## 为什么要有这一层

真机 83 那趟（63 条命题 / 1.9MB artifacts）实测：`/api/package` 4.1–4.5 s、
`/api/artifacts` 1.2–1.7 s、`/api/state` 0.5 s。前两条的几秒全花在"现算"上
（七类扫描 + 台账 join + `closing.check_closing` 的八格门），而页面每翻一次就要等一次。
这两个面又恰好是只读的：同一份盘、同一批参数，算出来的就是同一份读数。

## 冷调用那几秒花在哪

冷调用 2.4 s 不是键太细、也不是被挤出 8 档：键只占 1.3%（410 个文件 + 事件序号），
大头在 `closing.check_closing`（一次调用把 11 MB 的会话读 9 遍，约占 71%），其余是
structure 与 acceptance。同一份静止的盘，第 2/3 次调用 37–46 ms、`cache.hit=true`；
`_MAX_ENTRIES=8` 而真正会进缓存的只有 `package` / `artifacts` / `run-digest` 三面
（`/api/evidence` 与 `/api/errors` 不走这一层），远没到淘汰线。要缩短冷调用，下一刀
在 `check_closing`；把读数写在这里，免得下一个人再把"冷启动 2.4 s"当成缓存失效的缺陷
重查一遍。

## 失效键：盘状态，不是时间

```text
key_sha = sha256(  schema ‖ face ‖ 归一化后的参数 ‖ 工作区路径 ‖ 事件流最后序号
                 ‖ Σ 相关文件(相对路径, mtime_ns, size) )
```

三条口径各自防一种假绿：

1. `mtime_ns` + 大小（不是"有没有变化"的布尔）：内容改回原样、`os.replace`
   换了个 inode、只 `touch` 一下 —— 键都会变。只看大小会漏掉"同长度的改写"，
   只看 mtime 会在粗粒度时间戳的盘上漏掉同一秒内的两次写。
2. 事件流最后序号（`data/events.jsonl` 尾行那个 `seq`）：门结论（八格、
   `can_close`）不许跨过一次事件序号 —— 事件一追加，键立刻变，下一次必然现算。
   它和 `mtime`/大小是两条独立的证据：事件流被追加、后又被截断成同样大小这种事
   在 `mtime` 上看不出来，序号上看得出来。
3. 没有 TTL。这一条是有意的，也是本项目反复在治的那类缺陷的反面：

   - TTL 会把"刚刚变过"的那一份盘读成旧值（`hit=true` 但读数是旧的）—— 那是假绿；
   - TTL 也会把"十分钟没变"的那一份盘重新现算一遍 —— 那是白等。

   盘没动就命中，盘一动就作废；时间本身不是失效依据。判据
   `tests/test_webui_face_cache.py::test_pure_elapsed_time_does_not_invalidate`
   与 `::test_touching_only_the_mtime_invalidates_the_key` 从两头钉住它。

## "相关文件"为什么是整棵工作区

这两个面读的不止固定那几份台账：`_annotate_ledger_rows` 会顺着台账行去读行里
写的那个路径（可以落在工作区任何地方），`closing` 还会读 `sessions/`、`out/roster/`、
`runs/`、`code/exp/`。列一份"相关文件白名单"的代价是：将来某个读者多读一处，
白名单不会跟着长，而症状是"盘变了、读数没变"——没有任何地方会报错。

所以这里取工作区里全部文件的 stat（`os.scandir` 递归，只 stat 不读内容）：
它是"相关文件集合"的一个保守超集 —— 多算进来的文件最多让缓存少命中一次，
少算进去的文件会让读数变旧。真机量到的代价：83 工作区 576 个文件约 20 ms，
而它换掉的是 4.4 s。另有一份工作区外的输入（`settings.json`，`package_face` 会读）
按同一个形状补进键里。

## 缓存里放什么、不放什么

- 放：读模型原样（`dict`），不落盘（只在进程内存里，最多 `_MAX_ENTRIES` 份）。
  只读纪律因此是结构性的：这一层连一个临时文件都不写。
- 不放：`tri == "unreadable"` 的整面读数。盘坏了是一种读数，但它更可能是"这一趟
  没查成"；把它按盘状态缓存住会把"重试一下就好了"变成"永远读不出来"，而那只
  需要一次权限/IO 抖动。所以坏读数不缓存（下一次照常现算），代价只是坏盘时慢。

## 命中/未命中怎么可观测

处理器把这一层回的 `cache` 三格并进响应顶层（`hit` / `key_sha` / `built_at`）：
`hit` 说这一趟是现算还是复用；`key_sha` 是这一份盘的身份（同一份盘必相同）；
`built_at` 是这份数据被算出来的那一刻（命中时照原样回，不重写 —— 否则它报的
就不是"数据几岁"）。`data` 本身在两条路上是同一份对象的同一次序列化，所以
"命中与不命中逐字节相同"不是靠"小心保持一致"，而是结构上只有一条拼装路径。

## 并发

服务是 `ThreadingHTTPServer`：命中判定在锁内，现算在锁外。两个请求同时未命中时
会各算一遍（后写的那份与先写的等价：同一份盘、同一批参数），换来的是"慢的那一次
不阻塞其它请求"。缓存最多留 `_MAX_ENTRIES` 份，按最近使用淘汰 —— 页面上一页只有
两个面、参数也就几组，正常用远到不了上限。

## 与读模型契约的边界

`cache` 只加在 HTTP 响应上，不进 `package_face` / `artifacts_face` 的返回值：
`ui/src/types.ts` 的 `PackageView` / `ArtifactsView` 与那两个函数的键集合逐格对齐
（`test_webui_contracts.py` 的 C 条），读模型多一格就等于把契约与页面类型一起改坏。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Mapping

__all__ = ["CACHE_FIELDS", "CACHE_SCHEMA", "cache_entry", "cached_face", "clear_cache",
           "disk_key", "last_event_seq"]

#: 键的格式版本。改了"哪些东西进键"就加一 —— 老条目自动不再命中。
CACHE_SCHEMA = 1

#: 响应里 `cache` 那一块的键（形状契约；判据逐格比对）。
CACHE_FIELDS = ("hit", "key_sha", "built_at")

#: 最多留几份读数（按最近使用淘汰；正常页面用不到两份以上）。
_MAX_ENTRIES = 8

#: 读事件流尾巴的上限：只要最后一条可解析记录的 `seq`，不看整份日志。
_EVENT_TAIL_BYTES = 64 * 1024

#: `(面, key_sha) -> {"data": 读模型, "built_at": 建好的时刻}`；进程内存，不落盘。
_ENTRIES: "OrderedDict[tuple[str, str], dict[str, Any]]" = OrderedDict()

#: 命中判定/写入的锁。现算刻意不在锁内（慢的那一次不阻塞别的请求）。
_LOCK = threading.Lock()


# ====================================================================== 小工具
def _now_iso() -> str:
    """UTC 秒级时间（与 `package_face` 的 `generated_at` / `cachectl` 同一格式）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical(obj: Any) -> bytes:
    """一份稳定的字节串（键排序、UTF-8；参数里出现怪对象时按 `str` 收）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _settings_entry() -> tuple[str, int, int] | None:
    """工作区外那份 `settings.json` 的 stat（`package_face` 会读它）。

    它落在工程根而不是工作区里，所以整棵工作区的那一趟扫不到它；不补进来的话，
    改了设置而盘上别处没动，`/api/package` 会一直命中旧读数。取不到路径（判据注入的
    环境映射里没有这一档、或包被搬走了）就返回 `None` —— 不是错误：这一层只是少了
    一份输入，不因此拒绝缓存。
    """
    try:
        from .. import settings as S

        path = Path(S.settings_path())
    except Exception:  # noqa: BLE001 —— 拿不到路径只是少一份输入，不是"读不成"
        return None
    try:
        info = path.stat()
    except OSError:
        # 文件不在：用一个"缺席"哨兵占位。将来它被建出来 ⇒ 这一格从缺席变成 stat，
        # 键自然就变了（不占位的话"从无到有"在键里看不出来）。
        return ("<settings.json:absent>", -1, -1)
    return ("<settings.json>", info.st_mtime_ns, info.st_size)


def last_event_seq(root: str | Path) -> int:
    """`data/events.jsonl` 最后一条可解析记录的 `seq`（没有/读不成 ⇒ 0）。

    只读尾巴 `_EVENT_TAIL_BYTES` 字节：事件流真机上已经 5.6MB，而"最后序号"只需要
    最后几行。尾巴里恰好只有半行（写者正在追加）时往前找上一条可解析的 —— 那一趟的
    大小/mtime 已经变了，所以键照样会变；这里不猜一个假序号。
    """
    path = Path(str(root)) / "data" / "events.jsonl"
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            if size <= 0:
                return 0
            handle.seek(max(0, size - _EVENT_TAIL_BYTES), os.SEEK_SET)
            raw = handle.read()
    except OSError:
        return 0
    for line in reversed(raw.decode("utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict):
            try:
                return int(doc.get("seq") or 0)
            except (TypeError, ValueError):
                continue
    return 0


def _scan_files(root: Path) -> list[tuple[str, int, int]]:
    """工作区里每个文件的 `(相对路径, mtime_ns, size)`（只 stat，不读内容）。

    递归不跟目录符号链接（`is_dir(follow_symlinks=False)`）：工作区里挂一个指回
    祖先的链接时，"读一次页面"不会变成"走不完的树"。链接本身按文件记 stat
    （`follow_symlinks=True`），所以链接目标那一份的大小/时间变了键也会变。
    读不成的目录/文件各留一个哨兵元组：`-1` 不是"时间很早"，是"这一格没读成" ——
    它照样进键，于是"读不成 → 读得成"这件事也会让缓存作废。
    """
    out: list[tuple[str, int, int]] = []
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        info = entry.stat(follow_symlinks=True)
                    except OSError:
                        out.append((os.path.relpath(entry.path, str(root)), -1, -1))
                        continue
                    out.append((os.path.relpath(entry.path, str(root)),
                                int(info.st_mtime_ns), int(info.st_size)))
        except OSError:
            out.append((os.path.relpath(current, str(root)), -1, -2))
    out.sort(key=lambda row: row[0])
    return out


# ====================================================================== 键
def disk_key(face: str, root: str | Path,
             params: Mapping[str, Any]) -> tuple[str, int, int]:
    """算一份读数的失效键：`(key_sha, 文件数, 事件流最后序号)`。

    返回文件数与序号只为可观测/判据用；进键的是它们参与拼出来的那个 sha256。
    """
    root_p = Path(str(root))
    files = _scan_files(root_p)
    extra = _settings_entry()
    if extra is not None:
        files.append(extra)
    seq = last_event_seq(root_p)
    digest = hashlib.sha256()
    digest.update(b"agentflow.webui.facecache\0")
    digest.update(str(CACHE_SCHEMA).encode("ascii"))
    digest.update(b"\0")
    digest.update(str(face).encode("utf-8"))
    digest.update(b"\0")
    digest.update(_canonical(dict(params)))
    digest.update(b"\0")
    digest.update(os.fsencode(str(root_p)))
    digest.update(b"\0")
    digest.update(str(seq).encode("ascii"))
    digest.update(b"\n")
    for rel, mtime_ns, size in files:
        digest.update(os.fsencode(rel))
        digest.update(b"\0")
        digest.update(str(mtime_ns).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(files), seq


# ====================================================================== 入口
def cache_entry(face: str, key_sha: str) -> dict[str, Any] | None:
    """这一次的缓存条目（没有 ⇒ `None`）；只给判据/诊断看，不参与响应拼装。"""
    with _LOCK:
        return _ENTRIES.get((face, key_sha))


def clear_cache() -> None:
    """清空本进程的缓存（判据用；正常服务没有调用点）。"""
    with _LOCK:
        _ENTRIES.clear()


def cached_face(face: str, root: str | Path, params: Mapping[str, Any],
                compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any],
                                                                dict[str, Any]]:
    """取一份读模型：命中就直接回，未命中就 `compute()` 现算并按盘状态存住。

    返回 `(读模型, cache 元数据)`；元数据三格见 :data:`CACHE_FIELDS`。
    `compute()` 抛异常时不写缓存、异常原样上抛（读端的 500/三态由调用方那层管）。
    """
    key_sha, _files, _seq = disk_key(face, root, params)
    with _LOCK:
        entry = _ENTRIES.get((face, key_sha))
        if entry is not None:
            _ENTRIES.move_to_end((face, key_sha))
    if entry is not None:
        return entry["data"], {"hit": True, "key_sha": key_sha,
                               "built_at": str(entry["built_at"])}
    data = compute()
    built_at = _now_iso()
    # 坏读数按盘状态缓存住会把一次 IO 抖动变成"永远读不出来"；所以只缓存查成了的。
    if isinstance(data, dict) and str(data.get("tri") or "") != "unreadable":
        with _LOCK:
            _ENTRIES[(face, key_sha)] = {"data": data, "built_at": built_at}
            _ENTRIES.move_to_end((face, key_sha))
            while len(_ENTRIES) > _MAX_ENTRIES:
                _ENTRIES.popitem(last=False)
    return data, {"hit": False, "key_sha": key_sha, "built_at": built_at}
