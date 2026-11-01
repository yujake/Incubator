# -*- coding: utf-8 -*-
"""`/api/package` 与 `/api/artifacts` 的按盘失效缓存（业主 2026-11-02 那四条判据）。

## 这一份守什么

真机 83 那趟（63 条命题 / 1.9MB 产物）实测：`/api/package` 4.1–4.5 s、`/api/artifacts`
1.2–1.7 s —— 七类扫描与台账 join 全现算，页面"点一下要等几秒"。缓存本身不是难点，
难的是什么时候必须作废：

- 失效键 = （相关文件的 `mtime_ns` 集合 + 大小 + 事件流最后序号）；
- 不许用固定 TTL 当唯一依据 —— TTL 会把"刚变过"的那一份盘读成旧值，那正是这一轮
  一直在治的假绿；
- 命中/未命中必须可观测（响应里的 `cache` 三格），且两份读数逐字节相同。

所以这里逐条钉住四件事：快（同一份盘第二次 ≥3×）、跟着盘走（改一个相关
文件 ⇒ 下一次 `hit=false` 且返回体真的变了）、读数不变（命中与不命中两条路的
`data` 逐字节相同，只多 `cache` 元数据）、只读（任何一次读都不许写盘）。

另外两条是上面四条的负控/反真空：只改 `mtime_ns`（内容一字不动）也必须作废
（证明键是盘状态而不是 TTL）；干等一段时间不许作废（证明没有"到点就重算"的暗门）。

## 为什么用真端点量

`package_face` / `artifacts_face` 是纯函数，直接在进程内量会把"HTTP 外壳 + 序列化"
从预算里抹掉；而页面等的那几秒里这两样都在。所以这一份起真服务（`webui.serve`，
随机端口），量的是 `GET /api/*` 的墙钟。

## 夹具为什么要把盘加重

夹具工作区太小的话，一次现算与一次命中的差距会被进程抖动吃掉（判据本身会变成
噪声）。`_add_paper` 写一份 800 组定理/证明的 `main.tex`（结构扫描是真活儿），
`_add_heavy_ledger` 给台账加 12 个 512KB 的文件（`verify_entries` 每次现算 sha256）——
两项都是读侧本来就要做的事，不是往被测函数里塞睡眠。
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import pathlib
import re
import statistics
import threading
import time
import urllib.parse
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow import webui as W
from agentflow.webui import readers as R

PACKAGE = "/api/package?project_dir=.&report_path=out/review/REPORT.md"
ARTIFACTS = "/api/artifacts"

#: 端点与它要加的"重"夹具（参数化用；两边各跑一遍同一批判据）。
HEAVY = {
    "package": PACKAGE,
    "artifacts": ARTIFACTS,
}


# ====================================================================== 帮手
@contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    """随机端口起一个只读服务（与 `test_webui_source_window.py` 同一姿势）。"""
    srv = W.serve(root, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=10.0)


def _get(base: str, path: str) -> tuple[int, bytes, dict[str, Any]]:
    """一次 GET：返回 `(状态码, 原始字节, 解析后的对象)`。"""
    conn = http.client.HTTPConnection(base, timeout=120)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        raw = resp.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = {}
        return resp.status, raw, body if isinstance(body, dict) else {}
    finally:
        conn.close()


def _data_bytes(raw: bytes) -> bytes:
    """响应体里除 `cache` 元数据以外的那一部分，按 `_json` 同一条序列化口径回字节。

    比较"读数变没变"必须逐字节比：先各解一次 JSON 再比对象，会把键序与数字格式的
    漂移一并吃掉；而这一份判据要的正是"同一条序列化路径下逐字节相同"。
    """
    body = json.loads(raw.decode("utf-8"))
    body.pop("cache", None)
    return (json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
            + "\n").encode("utf-8")


def _add_paper(root: pathlib.Path, theorems: int = 800) -> pathlib.Path:
    """写一份够大的 `main.tex`（结构扫描每次都要真解析它）。"""
    pkg = root / "out" / "paper"
    pkg.mkdir(parents=True, exist_ok=True)
    lines = ["\\documentclass{article}", "\\begin{document}"]
    for i in range(theorems):
        lines.append(f"\\begin{{theorem}}夹具定理 {i}。\\end{{theorem}}")
        lines.append(f"\\begin{{proof}}夹具证明 {i}。\\end{{proof}}")
    lines.append("\\end{document}")
    tex = pkg / "main.tex"
    tex.write_text("\n".join(lines), encoding="utf-8")
    return tex


def _add_heavy_ledger(root: pathlib.Path, blobs: int = 12,
                      size: int = 512 * 1024) -> pathlib.Path:
    """给台账补几行指向大文件的产物（`verify_entries` 每次要现算 sha256）。"""
    spot = root / "out" / "heavy"
    spot.mkdir(parents=True, exist_ok=True)
    ledger = root / "ARTIFACTS.jsonl"
    with ledger.open("a", encoding="utf-8", newline="\n") as fh:
        for i in range(blobs):
            blob = spot / f"blob-{i:02d}.bin"
            blob.write_bytes(bytes([65 + i % 26]) * size)
            fh.write(json.dumps({
                "at": "2026-11-01T00:00:00Z",
                "path": str(blob.relative_to(root)).replace(os.sep, "/"),
                "sha256": hashlib.sha256(blob.read_bytes()).hexdigest(),
                "bytes": size, "producer": "probe", "kind": "file",
                "task_id": "", "exit_code": 0, "note": "缓存判据的重夹具",
            }, ensure_ascii=False) + "\n")
    return ledger


def _heavy(root: pathlib.Path, face: str) -> None:
    """按端点把它那一份"真活儿"加进夹具。"""
    if face == "package":
        _add_paper(root)
    else:
        _add_heavy_ledger(root)


def _snapshot(root: pathlib.Path) -> dict[str, tuple[int, int]]:
    """工作区里每个文件的 `(大小, mtime_ns)` —— 只读判据用它比对前后。"""
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def _last_event_seq(root: pathlib.Path) -> int:
    """盘上 `data/events.jsonl` 最后一条可解析记录的序号（判据自己算，不问被测模块）。"""
    path = root / "data" / "events.jsonl"
    if not path.is_file():
        return 0
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("seq"), int):
            return doc["seq"]
    return 0


def _append_event(root: pathlib.Path) -> int:
    """往事件流追加一条合法事件，返回它的序号。"""
    path = root / "data" / "events.jsonl"
    seq = _last_event_seq(root) + 1
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"seq": seq, "ts": "2026-11-02T00:00:00Z",
                             "op": "info", "message": "缓存判据：改事件序号"},
                            ensure_ascii=False) + "\n")
    return seq


# ====================================================================== 判据 a
@pytest.mark.parametrize("face", sorted(HEAVY))
def test_a_second_read_is_a_hit_and_at_least_three_times_faster(
        artifacts_ws: pathlib.Path, face: str) -> None:
    """① 同一份盘连调两次：第二次 `cache.hit=true` 且 ≥3× 快（这里是 3 次命中的中位）。

    正控是"第一次真的没命中"（否则"快"可能只是端点本来就快）；反真空是"第一次的
    时间真的量到了"（≥ 1ms），免得两次都被取整成 0 之后比值没有意义。
    """
    _heavy(artifacts_ws, face)
    path = HEAVY[face]
    with _server(artifacts_ws) as base:
        t0 = time.perf_counter()
        code, raw, first = _get(base, path)
        miss = time.perf_counter() - t0
        assert code == 200, (code, raw[:400])
        assert first["cache"]["hit"] is False, (
            f"第一次就读到命中 ⇒ 缓存键没有跟着这份盘/这次参数走：{first['cache']}")

        hits: list[float] = []
        bodies: list[dict[str, Any]] = []
        for _ in range(3):
            t = time.perf_counter()
            code, raw, body = _get(base, path)
            hits.append(time.perf_counter() - t)
            assert code == 200, (code, raw[:400])
            bodies.append(body)
    median_hit = statistics.median(hits)
    assert miss >= 0.001, f"第一次只量到 {miss * 1000:.3f} ms ⇒ 这个夹具压不出可比读数"
    assert all(b["cache"]["hit"] is True for b in bodies), [b["cache"] for b in bodies]
    assert median_hit * 3 <= miss, (
        f"{face}：不命中 {miss * 1000:.1f} ms / 命中中位 {median_hit * 1000:.1f} ms "
        f"⇒ 只有 {miss / max(median_hit, 1e-9):.1f}×，没到 3×")


# ====================================================================== 判据 c
@pytest.mark.parametrize("face", sorted(HEAVY))
def test_hit_and_miss_carry_byte_identical_data(artifacts_ws: pathlib.Path,
                                                face: str) -> None:
    """③ 命中与不命中两条路的 `data` 逐字节相同（只多 `cache` 元数据）。

    三次调用是同一份盘：第一次不命中、后两次命中。三条 `data` 必须逐字节相同；
    `cache.key_sha` / `built_at` 是同一份数据的两个身份，也必须相同 —— 只有 `hit`
    该从 `false` 翻成 `true`。任何"命中走另一条拼装路径"的实现在这里立刻红。
    """
    _heavy(artifacts_ws, face)
    path = HEAVY[face]
    with _server(artifacts_ws) as base:
        raws = []
        bodies = []
        for _ in range(3):
            code, raw, body = _get(base, path)
            assert code == 200, (code, raw[:400])
            raws.append(raw)
            bodies.append(body)
    datas = [_data_bytes(raw) for raw in raws]
    assert datas[0] == datas[1] == datas[2], (
        f"{face}：三条 data 不逐字节相同（长度 {[len(d) for d in datas]}）")
    metas = [b["cache"] for b in bodies]
    assert [m["hit"] for m in metas] == [False, True, True], metas
    assert len({m["key_sha"] for m in metas}) == 1, metas
    assert len({m["built_at"] for m in metas}) == 1, (
        f"命中时 built_at 被重写了 ⇒ 它报的不是这份数据是什么时候建好的：{metas}")


# ====================================================================== 判据 b
def test_changing_a_package_file_invalidates_and_changes_the_body(
        artifacts_ws: pathlib.Path) -> None:
    """② 改一个相关文件 ⇒ 下一次 `hit=false`、`key_sha` 变、`data` 真的变。

    这里的改动是"多一条定理"：`structure.paper.lines` 会涨，所以这条判据同时否掉了
    "只把 hit 翻成 false、body 原样回旧值"那种假缓存。
    """
    tex = _add_paper(artifacts_ws, theorems=40)
    with _server(artifacts_ws) as base:
        code, raw, first = _get(base, PACKAGE)
        assert code == 200, (code, raw[:400])
        assert first["cache"]["hit"] is False
        code, _raw, hit = _get(base, PACKAGE)
        assert hit["cache"]["hit"] is True

        # 同一份盘、只改这一个文件（内容变 ⇒ 大小/行数变）
        tex.write_text(tex.read_text(encoding="utf-8").replace(
            "\\end{document}",
            "\\begin{theorem}新加的定理。\\end{theorem}\n\\end{document}"),
            encoding="utf-8")

        code, raw2, after = _get(base, PACKAGE)
        assert code == 200, (code, raw2[:400])
    assert after["cache"]["hit"] is False, (
        "改了 main.tex 还命中 ⇒ 失效键没有覆盖相关文件")
    assert after["cache"]["key_sha"] != hit["cache"]["key_sha"], (
        "hit 翻了但 key_sha 没变 ⇒ 键与命中不是同一套事实")
    assert _data_bytes(raw2) != _data_bytes(raw), "返回体没变 ⇒ 命中的是旧读数"
    assert after["structure"]["paper"]["lines"] > first["structure"]["paper"]["lines"]


def test_changing_an_artifacts_file_invalidates_and_changes_the_body(
        artifacts_ws: pathlib.Path) -> None:
    """② 同一批判据落在 `/api/artifacts` 上：台账多一行 ⇒ 不命中且 `ledger` 变长。"""
    with _server(artifacts_ws) as base:
        code, raw, first = _get(base, ARTIFACTS)
        assert code == 200, (code, raw[:400])
        assert first["cache"]["hit"] is False
        code, _raw, hit = _get(base, ARTIFACTS)
        assert hit["cache"]["hit"] is True

        ledger = artifacts_ws / "ARTIFACTS.jsonl"
        with ledger.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({
                "at": "2026-11-02T00:00:00Z", "path": "out/run-1/report.md",
                "sha256": hashlib.sha256(
                    (artifacts_ws / "out" / "run-1" / "report.md").read_bytes()
                ).hexdigest(),
                "bytes": (artifacts_ws / "out" / "run-1" / "report.md").stat().st_size,
                "producer": "probe", "kind": "file", "task_id": "",
                "exit_code": 0, "note": "缓存判据：新加一行",
            }, ensure_ascii=False) + "\n")

        code, raw2, after = _get(base, ARTIFACTS)
        assert code == 200, (code, raw2[:400])
    assert after["cache"]["hit"] is False
    assert after["cache"]["key_sha"] != hit["cache"]["key_sha"]
    assert len(after["ledger"]) == len(first["ledger"]) + 1
    assert _data_bytes(raw2) != _data_bytes(raw)


def test_touching_only_the_mtime_invalidates_the_key(artifacts_ws: pathlib.Path) -> None:
    """②' 只把 `mtime_ns` 挪一下（内容一字不改）也必须作废。

    正控：`data` 不变（证明内容真的没动）；`key_sha` 变、`hit=false`（证明键里装的是
    `mtime_ns`，不是"文件大小 + TTL"这种更弱的东西）。
    """
    target = artifacts_ws / "out" / "review" / "REPORT-STYLE.json"
    with _server(artifacts_ws) as base:
        _code, raw, first = _get(base, ARTIFACTS)
        _code, _raw, hit = _get(base, ARTIFACTS)
        assert hit["cache"]["hit"] is True
        st = target.stat()
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        _code, raw2, after = _get(base, ARTIFACTS)
    assert after["cache"]["hit"] is False, "只挪 mtime 没作废 ⇒ 键里可能没有 mtime_ns"
    assert after["cache"]["key_sha"] != first["cache"]["key_sha"]
    assert _data_bytes(raw2) == _data_bytes(raw), (
        "内容没动却换了读数 ⇒ 命中/不命中两条路的拼装不一致")


def test_pure_elapsed_time_does_not_invalidate(artifacts_ws: pathlib.Path) -> None:
    """反真空：盘没动、干等一段时间不许作废（证明失效不是"到点就重算"）。

    这条是 TTL 的反面：有 TTL 的实现会在这里红，而"刚变过"的那一份盘反而会被
    TTL 读成旧值 —— 那正是这一轮一直在治的假绿。
    """
    with _server(artifacts_ws) as base:
        _code, _raw, first = _get(base, ARTIFACTS)
        assert first["cache"]["hit"] is False
        time.sleep(1.2)
        _code, raw2, later = _get(base, ARTIFACTS)
    assert later["cache"]["hit"] is True, "盘一个字没动却失效了 ⇒ 失效键里混进了时间"
    assert later["cache"]["built_at"] == first["cache"]["built_at"]


def test_a_new_event_sequence_invalidates_the_key(artifacts_ws: pathlib.Path) -> None:
    """事件流最后序号进键：追加一条事件 ⇒ 下一次不命中。

    `data` 允许不变（这两个面不重放事件流）；这一条钉的是"键里有事件序号"，
    也就是"门结论不许跨过一次事件序号"那一条的机器读数。
    """
    before_seq = _last_event_seq(artifacts_ws)
    with _server(artifacts_ws) as base:
        _code, _raw, first = _get(base, ARTIFACTS)
        _code, _raw, hit = _get(base, ARTIFACTS)
        assert hit["cache"]["hit"] is True
        seq = _append_event(artifacts_ws)
        assert seq == before_seq + 1
        _code, _raw, after = _get(base, ARTIFACTS)
    assert after["cache"]["hit"] is False, "事件序号涨了还命中 ⇒ 键里没有事件流最后序号"
    assert after["cache"]["key_sha"] != first["cache"]["key_sha"]


# ====================================================================== 参数进键
def test_a_different_query_is_a_different_key(artifacts_ws: pathlib.Path) -> None:
    """同一个工作区、不同查询参数（`cap_usd`）不许共用一份缓存。"""
    with _server(artifacts_ws) as base:
        _code, _raw, plain = _get(base, PACKAGE)
        assert plain["cache"]["hit"] is False
        _code, _raw, hit = _get(base, PACKAGE)
        assert hit["cache"]["hit"] is True
        _code, _raw, capped = _get(base, PACKAGE + "&cap_usd=0.5")
    assert capped["cache"]["hit"] is False, "换了一次参数还命中 ⇒ 参数没进键"
    assert capped["cache"]["key_sha"] != plain["cache"]["key_sha"]


# ====================================================================== 元数据形状
@pytest.mark.parametrize("face", sorted(HEAVY))
def test_cache_metadata_has_the_three_fields(artifacts_ws: pathlib.Path,
                                            face: str) -> None:
    """`cache` 恰好三格：`hit`（布尔）/ `key_sha`（64 位小写十六进制）/ `built_at`（UTC 秒）。"""
    _heavy(artifacts_ws, face)
    with _server(artifacts_ws) as base:
        _code, _raw, body = _get(base, HEAVY[face])
    meta = body["cache"]
    assert set(meta) == {"hit", "key_sha", "built_at"}, sorted(meta)
    assert isinstance(meta["hit"], bool)
    assert re.fullmatch(r"[0-9a-f]{64}", meta["key_sha"]), meta["key_sha"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", meta["built_at"]), \
        meta["built_at"]


# ====================================================================== 判据 d
@pytest.mark.parametrize("face", sorted(HEAVY))
def test_reading_never_writes_the_workspace(artifacts_ws: pathlib.Path,
                                            face: str) -> None:
    """④ 只读：不命中 + 命中 + 再读一次，工作区一个字节、一个 mtime 都不许动。

    快照比的是 `(大小, mtime_ns)`：写盘但写回同样内容也会动 mtime，所以这条比
    "内容 hash 不变"更紧。
    """
    _heavy(artifacts_ws, face)
    before = _snapshot(artifacts_ws)
    with _server(artifacts_ws) as base:
        for _ in range(3):
            code, raw, _body = _get(base, HEAVY[face])
            assert code == 200, (code, raw[:400])
    assert _snapshot(artifacts_ws) == before, "读端点写了盘"


# ====================================================================== 读模型不许带上 cache
def test_the_face_models_stay_cache_free(artifacts_ws: pathlib.Path) -> None:
    """`cache` 是 HTTP 外壳的事，不是读模型的事。

    `ui/src/types.ts` 的 `PackageView` / `ArtifactsView` 与后端键集合逐格对齐
    （`test_webui_contracts.py` 的 C 条）；把 `cache` 塞进读模型会让那份契约与页面
    类型同时失真，而这条判据在改读模型的实现上先红。
    """
    pkg = R.package_face(artifacts_ws, project_dir=".", report_path="out/review/REPORT.md")
    art = R.artifacts_face(artifacts_ws)
    assert "cache" not in pkg
    assert "cache" not in art


# ====================================================================== 端点对齐
def test_both_endpoints_go_through_the_same_cache_entry_point() -> None:
    """两个端点走同一个入口（`facecache.cached_face`），不许各写一份。

    这条是结构判据：命中/失效/元数据三件事只有一处实现，页面两个端点的读数才会
    永远同形；两处各写一份的漂移是这一层最可能的退化形态。
    """
    import inspect

    from agentflow.webui import facecache

    src = inspect.getsource(R.handle_package) + inspect.getsource(R.handle_artifacts)
    assert src.count("facecache.cached_face(") == 2, (
        "两个处理器里应当各调一次 `facecache.cached_face(`（docstring 里提到它不算）")
    assert callable(facecache.cached_face)
