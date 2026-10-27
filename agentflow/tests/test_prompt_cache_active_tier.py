# -*- coding: utf-8 -*-
"""当前这一趟会用哪一档缓存的判据（业主 2026-10-23 晚的补单）。

## 这一组守什么

| 条 | 判据 | 改前为什么红 |
|---|---|---|
| ① | 开关关：`active.tier="off"`、`tri="found"`、`absent` 含 L、覆盖 11/12；面板那一行是"非 Lean 版缓存" | 那时只有两档各自的状态，没有任何一格回答"现在用的是哪一档" |
| ② | 开关开：`active.tier="on"`、覆盖 12/12、`absent` 空、用的是开档那一趟；面板那一行是"Lean 版缓存" | 同上 |
| ③ | 同一个进程里 关 → 开 → 关：`active` 三次都跟着换（覆盖数、那一趟、那一行文案一起换） | 没有这一格就无从谈"跟随"；有了以后它若被缓存住，读数会停在旧档 |
| ④ | 反真空：把"哪一档在用"打桩成恒 `off` ⇒ ② 必红；把"当前开关"打桩成恒 `False` ⇒ ① 与 ③ 必红 | 判据若接在别处，打桩不会让它变 |

## 三层来源（2026-10-23 晚的小修：多进程时那一格说反了）

网页进程自己没设 `AGENTFLOW_LEAN_ENABLED`，于是"当前使用"那一格说的是网页的开关，
而不是正在跑的那一趟的开关。下面五条钉住新的口径（每一条在改之前都是红的）：

| 条 | 判据 | 改前为什么红 |
|---|---|---|
| ⑦ | 夹具工作区里有一条 lean=true 的运行记录，测试进程开关是关 ⇒ `active` 是 Lean 版、`source="run"`、文案里写"正在跑的那一趟" | 没有这一路取数，`active` 只看本进程开关 ⇒ 显示非 Lean 版；`source` 这一格根本不存在 |
| ⑧ | 同一条记录换成 lean=false、进程开关是开 ⇒ `active` 是非 Lean 版、`source="run"`（双向都测） | 同上，反方向也错 |
| ⑨ | 没有运行记录 ⇒ `source="process"`，文案里有"按本进程开关" | `source` 这一格不存在 |
| ⑩ | 运行记录读不出来 ⇒ `source="unknown"` 加理由，不许冒充 run 或 process | 同上；改前的实现会直接拿本进程开关顶上 |
| ⑪ | 反真空：把"读运行记录"打桩成恒 None ⇒ ⑦ 必红 | 判据若没真的接在那一处，打桩不会让它变 |

另有一条（`test_12`）钉住"优先正在跑"：正在跑的那一趟即使比最近一趟更早，也要取它。

## 为什么断言里现读一次真开关

`_assert_follows_the_real_switch` 不用测试自己 set 的那个值，而是现读
`leanscope.lean_on()`（模块加载时就绑好的那个函数，打桩 `cachectl._lean_now` 影响不到
它）。于是"读数说哪一档"与"开关真的是哪一档"是两条独立的线：④ 把开关打桩成恒
`False` 之后，环境里的真开关还是开着的，这条断言当场红 —— 而如果断言改成
"`active.lean` 等于我刚 set 的值"，打桩之后它照样绿，那条判据就白写了。

## 默认零模型钱

本文件一个请求都不发：①–⑥ 用 `tmp_path` 里造的读数文件加"真渲染出来的摘要"
（渲染只算字符串，零调用）；⑥ 那条端点走的是只读的 `GET /api/cache`。
"""
from __future__ import annotations

import contextlib
import http.client
import json
import os
import pathlib
import threading
from typing import Any, Iterator

import pytest

#: 真开关的读法（模块加载时绑定：打桩 `cachectl._lean_now` 不会换掉它）。
from agentflow.leanscope import lean_on as _switch_really_on

REPO = pathlib.Path(__file__).resolve().parents[1]
#: 前端那两个文件（这一行到底有没有上页面、有没有第二份文案）。
PANEL_TSX = REPO / "ui" / "src" / "components" / "PromptCache.tsx"
API_TS = REPO / "ui" / "src" / "api.ts"
#: 生成物的落点（2026-10-27 业主裁定 ⑥-5 / W4：缓存那一族的形状搬到这里了）。
TYPES_TS = REPO / "ui" / "src" / "types.ts"

#: 开关的环境变量（`settings.lean_enabled` 的第一档，`leanscope` 现读它）。
SWITCH_ENV = "AGENTFLOW_LEAN_ENABLED"

#: 夹具里两档各自那一趟的时间（③ 靠它证明"换档就换那一趟"，不是只换一个字符串）。
OFF_AT = "2026-10-23T01:00:00Z"
ON_AT = "2026-10-23T01:05:00Z"

#: 夹具里那一趟用的 key 指纹（16 位十六进制形态，与 `cachectl.fingerprint` 同宽）。
KEY_A = "0123456789abcdef"


# ====================================================================== 夹具
@pytest.fixture(scope="module")
def renders() -> dict[str, dict[str, dict[str, Any]]]:
    """两档各渲染一遍（约 1 秒；只渲染字符串，零模型调用）。"""
    from agentflow import cachectl as C

    C.clear_render_cache()
    got = C.render_all()
    C.clear_render_cache()
    return got


def _key() -> dict[str, Any]:
    """一份"当前 key"的读数（形状与 `cachectl.key_reading()` 相同）。"""
    return {"configured": True, "source": "test", "model": "deepseek-flash",
            "base_url": "https://api.deepseek.com/v1", "key_chars": 32,
            "fingerprint": KEY_A}


def _row(target: str, item: dict[str, Any], *, at: str) -> dict[str, Any]:
    """读数文件里的一行（形状照 `warm_prompt_cache._record_of` 的键集）。"""
    if str(item.get("kind")) == "absent":
        return {"role": target, "kind": "absent", "pass": 1, "at": at, "ok": True,
                "detail": str(item.get("absent_reason") or ""),
                "prompt_sha256": "", "system_sha256": "",
                "cache": {"known": False, "hit": None, "miss": None, "write": None,
                          "cache_tri": "absent"}}
    return {"role": target, "kind": str(item.get("kind")), "pass": 1, "at": at, "ok": True,
            "prompt_sha256": str(item.get("prompt_sha256") or ""),
            "system_sha256": str(item.get("system_sha256") or ""),
            "cache": {"known": True, "hit": 0, "miss": 100, "write": 100,
                      "cache_tri": "known"}}


def _run(tier: str, rendered: dict[str, dict[str, Any]], *, at: str,
         prompt_version: str) -> dict[str, Any]:
    """读数文件里的一趟（这一档的每个目标各一行，受控缺席的那几个是 `kind="absent"`）。"""
    rows = [_row(target, item, at=at) for target, item in rendered.items()]
    hidden = [target for target, item in rendered.items()
              if str(item.get("kind")) == "absent"]
    return {"schema": 1, "at": at, "verdict": "warmed", "lean_enabled": tier == "on",
            "prompt_version": prompt_version, "roles": list(rendered),
            "hidden": hidden, "rows": rows, "spent_usd": 0.012345,
            "model": "deepseek-flash", "base_url": "https://api.deepseek.com/v1",
            "key_fingerprint": KEY_A, "key_model": "deepseek-flash",
            "key_base_url": "https://api.deepseek.com/v1"}


def _write(tmp_path: pathlib.Path, runs: list[dict[str, Any]]) -> pathlib.Path:
    path = tmp_path / "prompt_cache_warm.json"
    path.write_text(json.dumps({"schema": 1, "runs": runs}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


@pytest.fixture()
def both_tiers(tmp_path: pathlib.Path,
               renders: dict[str, dict[str, dict[str, Any]]]) -> tuple[pathlib.Path, Any]:
    """两档都新鲜的读数文件（① ② ③ 的底子；两档的时间不同，③ 才量得出"换了一趟"）。"""
    from agentflow import agent_prompts as AP
    from agentflow import cachectl as C

    runs = [_run("off", renders["off"], at=OFF_AT, prompt_version=AP.PROMPT_VERSION),
            _run("on", renders["on"], at=ON_AT, prompt_version=AP.PROMPT_VERSION)]
    return _write(tmp_path, runs), C


# ====================================================================== 断言体（四条判据共用）
def _assert_follows_the_real_switch(doc: dict[str, Any]) -> None:
    """① 的断言体：`active` 必须跟随真开关（现读 `leanscope.lean_on()`，不是刚 set 的值）。

    两个方向都断言：读数说哪一档 == 真开关是哪一档；`lean_now` 与它同源。
    """
    really_on = _switch_really_on()
    active = doc["active"]
    assert active["strategy"] == "switch", active
    assert active["lean"] is really_on, (active["lean"], really_on)
    assert active["tier"] == ("on" if really_on else "off"), active
    assert doc["lean_now"] is really_on, (doc["lean_now"], really_on)


def _assert_off_shape(doc: dict[str, Any]) -> None:
    """① 的形状：关档用的是关那一趟，L 是受控缺席，那一行说"非 Lean 版缓存"。"""
    active = doc["active"]
    assert active["tri"] == "found", active
    assert active["fresh"] is True, active
    assert active["covered"] == "11/12", active
    assert active["missing"] == [], active
    assert "L" in active["absent"], active
    assert active["run_at"] == OFF_AT, active
    assert active["why"] == "", (active["why"], active["fresh"])
    assert "**非 Lean 版缓存**" in active["text"], active["text"]
    assert "L 受控缺席" in active["text"], active["text"]
    assert "开关：关" in active["text"], active["text"]


def _assert_on_shape(doc: dict[str, Any]) -> None:
    """② 的形状：开档用的是开那一趟，12/12，没有缺席，那一行说"Lean 版缓存"。"""
    active = doc["active"]
    assert active["tri"] == "found", active
    assert active["fresh"] is True, active
    assert active["covered"] == "12/12", active
    assert active["absent"] == [], active
    assert active["missing"] == [], active
    assert active["run_at"] == ON_AT, active
    assert active["why"] == "", (active["why"], active["fresh"])
    assert "**Lean 版缓存**" in active["text"], active["text"]
    assert "开关：开" in active["text"], active["text"]
    assert "非 Lean" not in active["text"], active["text"]


def _assert_three_step(rows: list[dict[str, Any]]) -> None:
    """③ 的断言体：三步（关 → 开 → 关）里 `active` 每一次都跟着换。"""
    assert [row["tier"] for row in rows] == ["off", "on", "off"], rows
    assert [row["covered"] for row in rows] == ["11/12", "12/12", "11/12"], rows
    assert rows[0]["run_at"] == OFF_AT, rows[0]
    assert rows[1]["run_at"] == ON_AT, rows[1]
    assert rows[0]["run_at"] != rows[1]["run_at"], rows
    assert "**Lean 版缓存**" in rows[1]["text"], rows[1]["text"]
    assert "**非 Lean 版缓存**" in rows[2]["text"], rows[2]["text"]
    # 第二段若停在旧值，这三条里至少一条会红（这就是"缓存停在旧档"的形态）
    assert rows[2]["text"] != rows[1]["text"], rows


def _panel_and_banner_show_that_line(active: dict[str, Any]) -> None:
    """这一行真的上得了页面：两个面孔都画 `active.text`，且前端没有第二份文案。"""
    tsx = PANEL_TSX.read_text(encoding="utf-8")
    assert "active.text" in tsx, "面板/横幅没有画后端给的这一行"
    assert tsx.count("ActiveReading") >= 3, tsx.count("ActiveReading")
    # 档名只在后端拼一次：前端若自带一份"Lean 版缓存"的字面量，两处就会漂
    assert "版缓存" not in tsx, "前端自己拼了一份档名文案（这一行只该由 active.text 出）"
    assert "CacheBanner" in tsx and "CachePanel" in tsx, "两个面孔不在这一个文件里"
    api_ts = API_TS.read_text(encoding="utf-8")
    types_ts = TYPES_TS.read_text(encoding="utf-8")
    assert "active: CacheActive" in types_ts, "types.ts 的 CacheView 少了 active 那一格"
    assert "interface CacheActive" in types_ts, "types.ts 少了 CacheActive 的声明"
    # 反向（2026-10-27）：这一族只许有一份声明 —— api.ts 里手写的那一份已删。
    assert "interface CacheActive" not in api_ts, "api.ts 又手写了一份 CacheActive（两份口径）"
    assert isinstance(active["text"], str) and active["text"] != ""


# ====================================================================== ① 开关关
def test_1_the_off_switch_uses_the_off_tier_and_says_so(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """① 开关关：`active` 是关那一档（11/12、L 受控缺席），页面上写"非 Lean 版缓存"。"""
    path, C = both_tiers
    from agentflow import agent_prompts as AP

    monkeypatch.setenv(SWITCH_ENV, "0")
    doc = C.status(path=path, renders=renders, key=_key())
    active = doc["active"]
    _assert_follows_the_real_switch(doc)
    _assert_off_shape(doc)
    assert active["prompt_version"] == AP.PROMPT_VERSION, active
    assert active["readings_prompt_version"] == AP.PROMPT_VERSION, active
    assert active["total"] == 12 and active["covered_count"] == 11, active
    _panel_and_banner_show_that_line(active)


# ====================================================================== ② 开关开
def test_2_the_on_switch_uses_the_on_tier_and_says_so(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """② 开关开：`active` 是开那一档（12/12、没有缺席），页面上写"Lean 版缓存"。"""
    path, C = both_tiers
    from agentflow import agent_prompts as AP

    monkeypatch.setenv(SWITCH_ENV, "1")
    doc = C.status(path=path, renders=renders, key=_key())
    active = doc["active"]
    _assert_follows_the_real_switch(doc)
    _assert_on_shape(doc)
    assert active["prompt_version"] == AP.PROMPT_VERSION, active
    _panel_and_banner_show_that_line(active)
    # 命令行印的是同一个字符串（CLI 与网页同口径、同一个函数出）
    assert C.cmd_status(_ns(readings=str(path))) in (C.EXIT_FRESH, C.EXIT_STALE,
                                                     C.EXIT_UNKNOWN)
    out = capsys.readouterr().out
    assert str(active["text"]) in out, out


# ====================================================================== ③ 同进程跟随
def test_3_the_active_tier_follows_the_switch_inside_one_process(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 同一个进程里 关 → 开 → 关：`active` 三次都跟着换（不许停在旧值）。"""
    path, C = both_tiers
    rows: list[dict[str, Any]] = []
    for on in (False, True, False):
        monkeypatch.setenv(SWITCH_ENV, "1" if on else "0")
        doc = C.status(path=path, renders=renders, key=_key())
        _assert_follows_the_real_switch(doc)
        rows.append(doc["active"])
    _assert_three_step(rows)


# ====================================================================== ④ 反真空
def test_4a_a_stubbed_always_off_active_reading_makes_2_red(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 把"哪一档在用"打桩成恒 `off` ⇒ ② 必红（开关开着也读成关那一档）。"""
    path, C = both_tiers
    monkeypatch.setenv(SWITCH_ENV, "1")
    healthy = C.status(path=path, renders=renders, key=_key())
    _assert_on_shape(healthy)  # 前提：真判据下这一格是开档

    monkeypatch.setattr(C, "_tier_in_use", lambda _lean: "off")
    stubbed = C.status(path=path, renders=renders, key=_key())
    assert stubbed["active"]["tier"] == "off", stubbed["active"]
    assert "**Lean 版缓存**" not in stubbed["active"]["text"], stubbed["active"]["text"]
    # 这就是 ② 会红的那一形态：同一个断言体在打桩之后不成立
    with pytest.raises(AssertionError):
        _assert_on_shape(stubbed)


def test_4b_a_stubbed_always_false_switch_makes_1_and_3_red(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 把"当前开关"打桩成恒 `False` ⇒ ① 与 ③ 必红（真开关是开，读数却说关）。"""
    path, C = both_tiers
    monkeypatch.setenv(SWITCH_ENV, "1")
    healthy = C.status(path=path, renders=renders, key=_key())
    _assert_follows_the_real_switch(healthy)  # 前提：真判据下跟随得上

    monkeypatch.setattr(C, "_lean_now", lambda: False)
    stubbed = C.status(path=path, renders=renders, key=_key())
    assert stubbed["active"]["tier"] == "off", stubbed["active"]
    # ① 的断言体：现场开关是开的，而读数说关 ⇒ 红
    with pytest.raises(AssertionError):
        _assert_follows_the_real_switch(stubbed)
    # ③ 的断言体：三段都是关 ⇒ 红
    rows: list[dict[str, Any]] = []
    for on in (False, True, False):
        monkeypatch.setenv(SWITCH_ENV, "1" if on else "0")
        rows.append(C.status(path=path, renders=renders, key=_key())["active"])
    assert [row["tier"] for row in rows] == ["off", "off", "off"], rows
    with pytest.raises(AssertionError):
        _assert_three_step(rows)


# ====================================================================== 第三态：读不出来
def test_5_a_tier_without_a_run_is_unknown_with_a_reason_and_no_fallback(
        tmp_path: pathlib.Path,
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """读不出来 ⇒ `tri="unknown"` 加理由，那一行说"当前没有可用缓存"；绝不回落到另一档。"""
    from agentflow import agent_prompts as AP
    from agentflow import cachectl as C

    only_off = _write(tmp_path, [_run("off", renders["off"], at=OFF_AT,
                                     prompt_version=AP.PROMPT_VERSION)])
    monkeypatch.setenv(SWITCH_ENV, "1")
    doc = C.status(path=only_off, renders=renders, key=_key())
    active = doc["active"]
    assert active["tier"] == "on", active
    assert active["tri"] == "unknown", active
    assert active["why"] == "cache_missing_for_lean_state", active["why"]
    assert active["covered"] == "0/12", active
    assert active["run_at"] == "", active
    assert set(active["missing"]) == set(C.all_targets()), active["missing"]
    assert active["absent"] == [], active
    assert active["text"].startswith("当前没有可用缓存"), active["text"]
    assert "cache_missing_for_lean_state" in active["text"], active["text"]
    # 不许借另一档的数：关那一档明明有 11 格，这里一格都不许出现
    assert "11/12" not in active["text"], active["text"]
    # 命令行与网页同一句（这里只量命令行；网页读的就是这个 doc）
    C.cmd_status(_ns(readings=str(only_off)))
    out = capsys.readouterr().out
    assert str(active["text"]) in out, out


# ====================================================================== 端点带着这一格
@contextlib.contextmanager
def _server(root: pathlib.Path) -> Iterator[str]:
    """在临时端口上起一个只读服务（写面开关关着，本文件不碰任何写端点）。"""
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=False)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _get(base: str, path: str) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection(base, timeout=30)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(text)
    finally:
        conn.close()


def test_6_the_cache_endpoint_carries_the_active_tier(tmp_path: pathlib.Path) -> None:
    """`GET /api/cache` 的返回里有 `active`（页面读的就是它，不是另外再算一次）。"""
    root = tmp_path / "ws-cache-active"
    root.mkdir()
    with _server(root) as base:
        code, got = _get(base, "/api/cache")
    assert code == 200, (code, got)
    assert "active" in got, got.keys()
    active = got["active"]
    assert active["tier"] in ("on", "off"), active
    assert active["strategy"] == "switch", active
    assert "当前" in active["text"], active["text"]
    assert active["tri"] in ("found", "unknown"), active


# ====================================================================== 运行记录的 lean 状态
#: 工作区根可以显式给的那一格（网页进程拿不到 root，靠它找到"这个工作区"）。
WS_ENV = "AGENTFLOW_WORKSPACE_ROOT"

#: 运行记录里那一趟的时间（与缓存读数文件里两趟的时间都不同，才量得出"读的是哪一处"）。
RECORD_AT = "2026-10-23T04:15:27Z"


def _workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个夹具工作区：`runs/` 与 `sessions/` 都在（与真工作区同形）。"""
    ws = tmp_path / "ws-run-records"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "sessions").mkdir(parents=True, exist_ok=True)
    return ws


def _lean_record(ws: pathlib.Path, *, sid: str = "lg2", lean: bool = True,
                 at: str = RECORD_AT, pid: int | None = None) -> pathlib.Path:
    """写一条"这一趟起跑时的 lean 状态"记录（`run_reading` 起跑时写的那个形状）。"""
    from agentflow import agent_prompts as AP

    path = ws / "runs" / f"cache-active-{sid}.json"
    payload = {"schema": 1, "kind": "cache_active", "sid": sid, "at": at,
               "lean_enabled": bool(lean), "tier": "on" if lean else "off",
               "prompt_version": str(AP.PROMPT_VERSION),
               "pid": int(os.getpid() if pid is None else pid),
               "workspace_root": str(ws)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def _live_pid(ws: pathlib.Path, *, sid: str = "lg2", role: str = "M",
              pid: int | None = None) -> pathlib.Path:
    """写一份还活着的进程登记（`runs/<角色>-<会话号>.pid`，判"正在跑"用的就是它）。"""
    path = ws / "runs" / f"{role}-{sid}.pid"
    path.write_text(json.dumps({"pid": int(os.getpid() if pid is None else pid),
                               "role": role, "sid": sid,
                               "started_at": "2026-10-23T12:15:27+08:00",
                               "ppid": os.getppid()}, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def _assert_run_lean_on_shape(doc: dict[str, Any]) -> None:
    """⑦ 的断言体：记录说 lean=true，本进程开关是关 —— 那一格必须说 Lean 版。"""
    active = doc["active"]
    assert active["tier"] == "on", active       # 改前这一格是 off（说了反话）
    assert active["lean"] is True, active
    assert active["tri"] == "found", (active["tri"], active["why"])
    assert active["fresh"] is True, active
    assert active["covered"] == "12/12", active
    assert active["run_at"] == ON_AT, active
    assert active["source"] == "run", active
    assert active["record_sid"] == "lg2", active
    assert active["record_at"] == RECORD_AT, active
    assert active["record_state"] == "running", active
    assert "**Lean 版缓存**" in active["text"], active["text"]
    assert "来源=正在跑的那一趟 lg2" in active["text"], active["text"]
    assert "按本进程开关" not in active["text"], active["text"]
    assert "开关：开" in active["text"], active["text"]


def test_7_a_lean_on_run_record_wins_over_the_process_switch_off(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    """⑦ 记录说 lean=true、进程开关关 ⇒ active 是 Lean 版、source=run（不许说反）。"""
    path, C = both_tiers
    ws = _workspace(tmp_path)
    _lean_record(ws, lean=True)
    _live_pid(ws)
    monkeypatch.setenv(WS_ENV, str(ws))
    monkeypatch.setenv(SWITCH_ENV, "0")
    doc = C.status(path=path, renders=renders, key=_key())
    assert doc["lean_now"] is False, doc["lean_now"]   # 前提：网页进程开关确实是关的
    _assert_run_lean_on_shape(doc)
    # 命令行与网页同一个函数出：`cache status` 印的是同一句
    assert C.cmd_status(_ns(readings=str(path))) in (C.EXIT_FRESH, C.EXIT_STALE,
                                                     C.EXIT_UNKNOWN)
    out = capsys.readouterr().out
    assert str(doc["active"]["text"]) in out, out


def test_8_a_lean_off_run_record_wins_over_the_process_switch_on(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑧ 同一条记录换成 lean=false、进程开关开 ⇒ active 是非 Lean 版、source=run。"""
    path, C = both_tiers
    ws = _workspace(tmp_path)
    _lean_record(ws, lean=False)
    _live_pid(ws)
    monkeypatch.setenv(WS_ENV, str(ws))
    monkeypatch.setenv(SWITCH_ENV, "1")
    doc = C.status(path=path, renders=renders, key=_key())
    active = doc["active"]
    assert doc["lean_now"] is True, doc["lean_now"]  # 进程开关开着，而这一格说的是运行记录
    assert active["tier"] == "off", active          # 改前这一格是 on（同样说反）
    assert active["lean"] is False, active
    assert active["source"] == "run", active
    assert active["tri"] == "found", (active["tri"], active["why"])
    assert active["covered"] == "11/12", active
    assert "L" in active["absent"], active
    assert active["run_at"] == OFF_AT, active
    assert active["record_state"] == "running", active
    assert "**非 Lean 版缓存**" in active["text"], active["text"]
    assert "L 受控缺席" in active["text"], active["text"]
    assert "来源=正在跑的那一趟 lg2" in active["text"], active["text"]
    assert "开关：关" in active["text"], active["text"]
    # 双向都测：②那一档的断言体在这里必须不成立（否则这一条只是重复了①）
    with pytest.raises(AssertionError):
        _assert_run_lean_on_shape(doc)


def test_9_without_a_run_record_the_process_switch_is_the_source(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑨ 工作区里没有运行记录 ⇒ source=process，文案里写明"按本进程开关"。"""
    path, C = both_tiers
    ws = _workspace(tmp_path)                      # runs/ 是空的
    monkeypatch.setenv(WS_ENV, str(ws))
    monkeypatch.setenv(SWITCH_ENV, "0")
    doc = C.status(path=path, renders=renders, key=_key())
    active = doc["active"]
    # 改前这一行里没有"来源"两个字：它只说"按当前开关"（等于让读者以为那就是正在跑的那一趟）
    assert "按本进程开关" in active["text"], active["text"]
    assert "这个工作区没有运行记录" in active["text"], active["text"]
    assert active["source"] == "process", active
    assert active["strategy"] == "switch", active
    assert active["tier"] == "off", active
    assert active["covered"] == "11/12", active
    assert "来源=正在跑的那一趟" not in active["text"], active["text"]
    # 前端类型里补上了来源那一格（页面不另拼文案，但契约要跟着长）：形状住在生成物里
    types_ts = TYPES_TS.read_text(encoding="utf-8")
    assert "export interface CacheActive {" in types_ts, "types.ts 少了 CacheActive 的声明"
    block = types_ts.split("export interface CacheActive {", 1)[1].split("}", 1)[0]
    assert "source: string" in block, "CacheActive 少了 source 这一格"


def test_10_an_unreadable_run_record_is_unknown_and_never_impersonates(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑩ 运行记录读不出来 ⇒ source=unknown 加理由；不许冒充 run，也不许退回 process。"""
    path, C = both_tiers
    ws = _workspace(tmp_path)
    bad = ws / "runs" / "cache-active-lg2.json"
    bad.write_text('{"sid": "lg2", "lean_enabled": ', encoding="utf-8")
    monkeypatch.setenv(WS_ENV, str(ws))
    monkeypatch.setenv(SWITCH_ENV, "1")
    doc = C.status(path=path, renders=renders, key=_key())
    active = doc["active"]
    # 改前这一行会写成"Lean 版缓存…开关：开"（拿本进程开关冒充那一趟的开关）
    assert "来源=unknown" in active["text"], active["text"]
    assert "按本进程开关" not in active["text"], active["text"]
    assert "正在跑的那一趟" not in active["text"], active["text"]
    assert "最近一趟" not in active["text"], active["text"]
    # 也不许把"没读成"画成"这一档没有读数"（那是另一条理由）
    assert "cache_missing_for_lean_state" not in active["text"], active["text"]
    assert active["source"] == "unknown", active
    assert active["tri"] == "unknown", active
    assert active["tier"] == "", active
    assert "run_record_unreadable" in active["why"], active["why"]

    # 第二种读不出来：JSON 是好的，但没记 lean 状态（这一格不能猜）
    bad.write_text(json.dumps({"sid": "lg2", "at": RECORD_AT}), encoding="utf-8")
    again = C.status(path=path, renders=renders, key=_key())
    assert again["active"]["source"] == "unknown", again["active"]
    assert again["active"]["tri"] == "unknown", again["active"]


def test_11_stubbing_the_run_record_reader_makes_7_red(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑪ 反真空：把"读运行记录"打桩成恒 None ⇒ ⑦ 必红。"""
    path, C = both_tiers
    ws = _workspace(tmp_path)
    _lean_record(ws, lean=True)
    _live_pid(ws)
    monkeypatch.setenv(WS_ENV, str(ws))
    monkeypatch.setenv(SWITCH_ENV, "0")
    healthy = C.status(path=path, renders=renders, key=_key())
    _assert_run_lean_on_shape(healthy)             # 前提：真判据下这一格是 Lean 版

    monkeypatch.setattr(C, "run_record_reading",
                        lambda **_kw: {"tri": "missing", "reason": "", "detail": "",
                                       "path": "", "state": "", "record": {}},
                        raising=False)
    stubbed = C.status(path=path, renders=renders, key=_key())
    assert stubbed["active"]["source"] == "process", stubbed["active"]
    assert stubbed["active"]["tier"] == "off", stubbed["active"]
    with pytest.raises(AssertionError):
        _assert_run_lean_on_shape(stubbed)


def test_12_a_running_run_wins_over_a_newer_finished_one(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """同一条口径的另一半：正在跑的那一趟比"最近一趟"优先（哪怕后者更新）。"""
    path, C = both_tiers
    ws = _workspace(tmp_path)
    # 正在跑的那一趟：更早，但 pid 还活着（lg2，lean=true）
    _lean_record(ws, sid="lg2", lean=True, at="2026-10-23T03:00:00Z")
    _live_pid(ws, sid="lg2")
    # 最近一趟：更晚，但没有人活着（lg3，lean=false）
    _lean_record(ws, sid="lg3", lean=False, at="2026-10-23T05:00:00Z")
    monkeypatch.setenv(WS_ENV, str(ws))
    monkeypatch.setenv(SWITCH_ENV, "0")
    doc = C.status(path=path, renders=renders, key=_key())
    active = doc["active"]
    assert "正在跑的那一趟 lg2" in active["text"], active["text"]
    assert active["source"] == "run", active
    assert active["record_sid"] == "lg2", active
    assert active["record_state"] == "running", active
    assert active["tier"] == "on", active


def _ns(**kw: Any) -> Any:
    """一个最小的命令行参数命名空间（`cmd_status` / `cmd_warm` 只读这几个字段）。"""
    import argparse

    base: dict[str, Any] = {"json": False, "readings": "", "lean": "", "dry_run": False,
                            "cap_usd": None, "model": ""}
    base.update(kw)
    return argparse.Namespace(**base)
