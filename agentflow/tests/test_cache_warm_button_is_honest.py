# -*- coding: utf-8 -*-
"""D-60 判据：预热缓存按钮要"诚实"（无写权限说清、`dry_run` 放行、三态跟踪）。

## 这一组守什么

`draft/146` D-60 的三处缺口，一条判据一条缺口（外加负控与反真空）：

| 条 | 判据 | 改前为什么红 |
|---|---|---|
| a | 无 `--allow-writes` ⇒ `GET /api/cache` 的 `writes_allowed=false` + 逐字一句原因；页面据此禁用真预热按钮并把原因写在按钮旁 | 读数里根本没有这一格，页面只能让人按出 403 |
| b | 无 `--allow-writes` + `dry_run=1` ⇒ 200 且回执 `state="plan"`（只给计划、不起进程、不落预热记录） | `authorize` 在第 3 层（`allow_writes`）就拒了，试算跟着陪葬 |
| c | 负控：无 `--allow-writes` + `dry_run=0`（或缺省）⇒ 仍然 403，且一个子进程都没起 | 放行 dry_run 时若顺手把真跑也放过去，这一条就红 |
| d | 真预热（`_spawn_warm` 打桩）⇒ 回执 `state="running"`；轮询读数从 `running` 到 `done`；结束那一次读数是真的重取的（打桩数 `_status` 的调用次数） | 没有 `warm` 这一格，也没有"跑完自动重取" |
| e | 失败档 ⇒ `state="failed"` + 日志路径（盘上真在）+ 最后一行错误 | 同上：按完不知道成没成 |
| f | 反真空：把写权限读数打桩成恒 `true` ⇒ a 必红；把三态判定打桩成恒 `done` ⇒ d 必红 | 判据若没接在这两根线上，打桩不会让它变 |

## 为什么文案由后端给、页面只照着画

无写权限那一句必须是逐字的（业主原话）：`writes.WRITES_OFF_REASON` 是它唯一的真身，
`/api/cache` 把它原样带在 `writes_reason` 里，页面画的是那一格而不是自己另拼一份 ——
与 `active.text` 同一条口径（两处各拼一份，两句话迟早会漂，而漂了没有地方会报错）。
所以 a 条两端都钉：后端给的是那句逐字的话，页面的 `writes_reason` 真的被渲染了。

## 默认零模型钱

本文件一个真实预热都不跑：真预热那一条路全部打桩（`_spawn_warm` 只写一份假日志、
`_pid_alive` 是一个开关、`_plan` 直接给计划），`_status` 也打桩（不渲染提示词）。
`GET /api/cache` 与 `POST /api/cache/warm` 走的是真 HTTP（真路由表、真授权矩阵）。
"""
from __future__ import annotations

import contextlib
import http.client
import json
import pathlib
import threading
import urllib.parse
from typing import Any, Iterator

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
#: 页面与它的端点声明（"禁用了没有"只能从源码上读，本仓库没有 JS 测试设施）。
PANEL_TSX = REPO / "ui" / "src" / "components" / "PromptCache.tsx"
API_TS = REPO / "ui" / "src" / "api.ts"

#: 判据自己的 CSRF 令牌（`serve(csrf_token=...)` 钉住它，于是请求头可预期）。
CSRF = "d60-warm-button-csrf-0123456789"

#: 无写权限时页面上那一行原因（逐字，真身在 `writes.WRITES_OFF_REASON`）。
WRITES_OFF_LINE = "本服务未开 --allow-writes，写按钮不可用；重启时加该参数即可"

#: `dry_run=1` 的回执里必须有的那一档（它不在三态词表里：它说的是"这只是计划"）。
PLAN_STATE = "plan"

#: 预热记录文件名（`cacheface.WARM_JOB_FILE` 的落点；dry_run 不许留下它）。
WARM_RECORD = "runs/web-cache-warm.json"

#: 真预热日志的相对落点（`_spawn_warm` 的桩返回它，记录与读侧都按工作区相对路径认）。
WARM_LOG = "runs/web-cache-warm-20261024-120000.log"

#: 子进程还在跑时日志里已经有的那一行（`cachectl.warm` 发第一发之前先印它）。
KEY_LINE = ("[key] 来源=test 模型=deepseek-flash 接口=(空) key=*** "
            "指纹=0123456789abcdef （这一档：Lean 关档，上限 0.10 美元）\n")

#: 跑完那一行（`cachectl.cmd_warm` 的收尾标记之一）。
DONE_LINE = "[warmed] 关档：花费 0.000123 美元 · 12 个目标各有读数\n"

#: 失败那一行（同样是 `cmd_warm` 的收尾标记；最后一行就是给按按钮的人看的错误）。
FAIL_LINE = "[unknown] 预热没跑起来（关档）：RuntimeError: 上游 429 限流\n"


# ====================================================================== 夹具
@contextlib.contextmanager
def _server(root: pathlib.Path, *, allow_writes: bool) -> Iterator[str]:
    """在临时端口上起一个服务（写面开关由判据钉住，令牌可预期）。"""
    from agentflow import webui as W

    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=allow_writes,
                  csrf_token=CSRF)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _post(base: str, path: str, fields: dict[str, Any] | None = None, *,
          csrf: str | None = CSRF) -> tuple[int, dict[str, Any]]:
    """一次 POST（表单编码）；回执必须是 JSON 对象。"""
    body = urllib.parse.urlencode(fields or {}, doseq=True).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded",
                               "Content-Length": str(len(body))}
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    conn = http.client.HTTPConnection(base, timeout=30)
    try:
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", errors="replace")
        try:
            got = json.loads(text)
        except ValueError as exc:
            raise AssertionError(f"回执不是 JSON：{text[:200]!r}（{exc}）") from exc
        assert isinstance(got, dict), got
        return resp.status, got
    finally:
        conn.close()


def _get(base: str, path: str) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection(base, timeout=30)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(text)
    finally:
        conn.close()


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个最小工作区（缓存面只读它自己的记录与日志，不需要 store）。"""
    root = tmp_path / "ws"
    root.mkdir()
    return root


def _count_status(monkeypatch: pytest.MonkeyPatch,
                  counts: dict[str, int]) -> None:
    """把 `cacheface._status` 换成计数器（d 条靠它证明"结束那一次读数真的重取了"）。"""
    from agentflow.webui import cacheface

    def _fake() -> dict[str, Any]:
        counts["status"] = counts.get("status", 0) + 1
        return {"schema": 1, "tiers": {}, "lean_now": False, "prompt_version": "p200",
                "readings": "fixture"}

    monkeypatch.setattr(cacheface, "_status", _fake)


def _log(root: pathlib.Path, text: str = "") -> pathlib.Path:
    """造一份预热日志（父目录 `runs/` 一起造；`text` 为空就是只造目录）。"""
    path = root / WARM_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _append(path: pathlib.Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _stub_spawn(monkeypatch: pytest.MonkeyPatch, *,
                first: str = KEY_LINE) -> list[str]:
    """把 `_spawn_warm` 打成"造一份日志 + 回 pid/相对路径"的桩，返回被调的档位列表。

    为什么日志由桩来造：真预热要花钱，而"记录里的日志路径"必须是这一趟真起的那一份
    （判据要按它读日志尾），所以桩同时负责落盘与回执，二者指向同一处。
    """
    from agentflow.webui import cacheface

    seen: list[str] = []

    def _fake(runs_root: pathlib.Path, lean: str) -> tuple[int, str]:
        seen.append(str(lean))
        _log(pathlib.Path(runs_root), first)
        return 4242, WARM_LOG

    monkeypatch.setattr(cacheface, "_spawn_warm", _fake)
    return seen


def _stub_spawn_boom(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_spawn_warm` 被调就炸（"这条路上不许起子进程"的那一档）。"""
    from agentflow.webui import cacheface

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("这条路上不该起子进程（真预热才起）")

    monkeypatch.setattr(cacheface, "_spawn_warm", _boom)


def _stub_alive(monkeypatch: pytest.MonkeyPatch, alive: dict[str, bool]) -> None:
    """`_pid_alive` 换成一个开关（探活本机真进程在判据里不可控）。"""
    from agentflow.webui import cacheface

    monkeypatch.setattr(cacheface, "_pid_alive", lambda _pid: alive["value"],
                        raising=False)


# ====================================================================== a 写权限读数
def test_a_a_service_without_the_write_switch_says_so_and_the_page_disables(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """a) 无写权限 ⇒ 读数 `writes_allowed=false` + 逐字原因；页面禁用按钮、写出原因。

    改前红：读数里没有 `writes_allowed` 这一格（KeyError），页面也没有"禁用"这条路
    —— 人只能按下去吃 403。
    """
    counts: dict[str, int] = {}
    _count_status(monkeypatch, counts)
    root = _ws(tmp_path)
    with _server(root, allow_writes=False) as base:
        code, got = _get(base, "/api/cache")
    assert code == 200, (code, got)
    assert got.get("writes_allowed") is False, f"读数里没有写权限这一格：{sorted(got)}"
    assert got.get("writes_reason") == WRITES_OFF_LINE, got.get("writes_reason")
    # 没有起过预热时那一格是 unknown + 理由（不是 failed，也不是空）
    warm = got.get("warm") or {}
    assert warm.get("recorded") is False, warm
    assert warm.get("state") == "unknown", warm
    assert warm.get("reason"), warm

    # 页面：读这一格、按它禁用、把原因写在按钮旁（文案不在前端另拼一份）
    tsx = PANEL_TSX.read_text(encoding="utf-8")
    assert "writes_allowed" in tsx, "页面没读 writes_allowed 这一格"
    assert "writes_reason" in tsx, "页面没把后端给的那一句原因画出来"
    assert "const blocked = !props.writesAllowed" in tsx, tsx[:400]
    assert "disabled={disabled || props.busy || blocked}" in tsx, "真预热按钮没被禁用"
    assert "!dry && !writesAllowed" in tsx, "禁用了按钮，但 press 那条路还留着后门"
    # 而"试算"那一档只受 busy 管：它不需要写权限（② 的另一半在页面上）
    assert "disabled={props.busy} onClick={props.onPlan}" in tsx, tsx[:400]


# ====================================================================== b dry_run 放行
def test_b_a_dry_run_gets_a_plan_even_without_the_write_switch(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """b) 无写权限 + `dry_run=1` ⇒ 200 且 `state="plan"`（不起进程、不落预热记录）。

    改前红：`authorize` 第 3 层直接 403。

    请求刻意不带 `X-CSRF-Token`：试算不写盘、不花钱、不起进程，闸门里那三层
    都是为"写 / 花钱"准备的，给它留的是只读那一档（回环来源那一道照旧在）。
    """
    from agentflow.webui import cacheface

    calls: list[dict[str, Any]] = []

    def _fake_plan(**kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return {"code": 0, "doc": {"verdict": "dry_run",
                                   "tiers": {"off": {"to_warm": ["A"], "skip_fresh": [],
                                                     "absent": ["L"], "calls": 1,
                                                     "usd_est": 0.001}},
                                   "calls_total": 1, "usd_est_total": 0.001}}

    monkeypatch.setattr(cacheface, "_plan", _fake_plan)
    _stub_spawn_boom(monkeypatch)
    root = _ws(tmp_path)
    with _server(root, allow_writes=False) as base:
        code, got = _post(base, "/api/cache/warm",
                          {"lean": "off", "dry_run": "1", "confirm": "1"}, csrf=None)
    assert code == 200, f"没有写权限时试算被拒了（{code}）：{got}"
    assert got.get("ok") is True and got.get("tri") == "computed", got
    assert got.get("state") == PLAN_STATE, got.get("state")
    assert calls and calls[0].get("tiers") == ("off",), calls
    extra = got.get("extra") or {}
    assert extra.get("dry_run") is True, extra
    assert (extra.get("plan") or {}).get("tiers", {}).get("off", {}).get("to_warm") == ["A"], extra
    assert "0 美元" in str(got.get("reason")), got.get("reason")
    # 试算不落预热记录（"不写盘"这一句的机器读数；审计台账那一行是写面的统一口径，不算）
    assert not (root / WARM_RECORD).exists(), "试算居然落了预热记录"


# ====================================================================== c 负控
def test_c_a_real_warm_still_needs_the_write_switch(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c) 负控：无写权限 + 真跑（`dry_run=0` / 缺省）⇒ 仍然 403，且零子进程零记录。

    这一条与 b 成对：同一个服务进程、同一个端点，只差 `dry_run` 那一格。
    """
    from agentflow.webui import cacheface

    calls: list[dict[str, Any]] = []

    def _fake_plan(**kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return {"code": 0, "doc": {"tiers": {"off": {"to_warm": [], "usd_est": 0.0}}}}

    monkeypatch.setattr(cacheface, "_plan", _fake_plan)
    _stub_spawn_boom(monkeypatch)
    root = _ws(tmp_path)
    with _server(root, allow_writes=False) as base:
        # ① 缺省（没有 dry_run 这一格）
        code1, got1 = _post(base, "/api/cache/warm", {"lean": "off", "confirm": "1"})
        # ② 显式 dry_run=0
        code2, got2 = _post(base, "/api/cache/warm",
                            {"lean": "off", "confirm": "1", "dry_run": "0"})
        # ③ 同一个服务上，dry_run=1 仍然放行（两档真的分得开）
        code3, got3 = _post(base, "/api/cache/warm",
                            {"lean": "off", "confirm": "1", "dry_run": "1"}, csrf=None)
    for code, got in ((code1, got1), (code2, got2)):
        assert code == 403, f"真跑在没有写权限时被放行了（{code}）：{got}"
        assert got.get("ok") is False and got.get("tri") == "not_applicable", got
        assert "写面没开" in str(got.get("reason")), got.get("reason")
        assert got.get("state") != "running", got
    assert code3 == 200 and got3.get("state") == PLAN_STATE, (code3, got3)
    assert calls and len(calls) == 1, f"只有 dry_run 那一次该算计划：{calls}"
    assert not (root / WARM_RECORD).exists(), "被拒的真跑居然落了预热记录"


# ====================================================================== d 三态 + 重取
def test_d_a_real_warm_runs_from_running_to_done_and_the_readings_are_refetched(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d) 真预热 ⇒ 回执 `running`；轮询 `running` → `done`；结束那次读数真的重取。

    三态是读侧判的（记录 + 日志尾 + 探活），不是回执自报的：所以 POST 说
    `running` 之后，GET 一开始也必须是 `running`（此时日志只有 `[key]` 那一行、
    进程还活着），日志写出收尾标记之后才变 `done`。

    "完成后自动重取读数"的机器读数：`_status` 的调用次数 == GET 的次数 —— 报 `done`
    的那一次响应里带着现取的读数，不是缓存的那一份。
    """
    counts: dict[str, int] = {}
    _count_status(monkeypatch, counts)
    alive = {"value": True}
    _stub_alive(monkeypatch, alive)
    seen = _stub_spawn(monkeypatch)
    root = _ws(tmp_path)
    with _server(root, allow_writes=True) as base:
        code, got = _post(base, "/api/cache/warm", {"lean": "off", "confirm": "1"})
        assert code == 200, (code, got)
        assert got.get("state") == "running", got.get("state")
        extra = got.get("extra") or {}
        assert extra.get("pid") == 4242 and extra.get("log") == WARM_LOG, extra
        assert seen == ["off"], seen

        first_code, first = _get(base, "/api/cache")
        assert first_code == 200, first_code
        first_warm = first.get("warm") or {}
        assert first_warm.get("state") == "running", first_warm
        assert first_warm.get("recorded") is True, first_warm
        assert first_warm.get("log") == WARM_LOG, first_warm
        assert first_warm.get("pid") == 4242, first_warm
        assert counts.get("status") == 1, counts

        # 子进程跑完：日志出现收尾标记，pid 不再活着
        _append(root / WARM_LOG, DONE_LINE)
        alive["value"] = False
        second_code, second = _get(base, "/api/cache")
        assert second_code == 200, second_code
        second_warm = second.get("warm") or {}
        assert second_warm.get("state") == "done", second_warm
        assert "跑完" in str(second_warm.get("reason")), second_warm
        assert second_warm.get("last_line") == DONE_LINE.strip(), second_warm
        assert counts.get("status") == 2, (
            f"报 done 的那一次没有重取读数（_status 只被调了 {counts.get('status')} 次）")
    # 页面的那一半：轮询 + 跑完自动重取（三态词表与两个触发条件都在源码里）
    tsx = PANEL_TSX.read_text(encoding="utf-8")
    for piece in ("warm.state", "const WARM_POLL_MS", "window.setTimeout",
                  "window.clearTimeout", 'running: "跑中"', 'done: "成"', 'failed: "败"'):
        assert piece in tsx, f"页面缺 {piece}"
    assert 'previous === "running"' in tsx, "页面没有「跑完」那个边沿"
    assert 'warmState === "done" || warmState === "failed"' in tsx, tsx[:400]
    assert "face.reload();" in tsx, "跑完没有重取读数"


# ====================================================================== e 失败档
def test_e_a_failed_warm_says_failed_with_the_log_and_the_last_line(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e) 失败档 ⇒ `state="failed"` + 日志路径（盘上真在）+ 最后一行错误。"""
    counts: dict[str, int] = {}
    _count_status(monkeypatch, counts)
    alive = {"value": False}
    _stub_alive(monkeypatch, alive)
    _stub_spawn(monkeypatch, first=KEY_LINE + FAIL_LINE)
    root = _ws(tmp_path)
    with _server(root, allow_writes=True) as base:
        code, got = _post(base, "/api/cache/warm", {"lean": "off", "confirm": "1"})
        assert code == 200 and got.get("state") == "running", (code, got)
        read_code, read = _get(base, "/api/cache")
    assert read_code == 200, read_code
    warm = read.get("warm") or {}
    assert warm.get("state") == "failed", warm
    assert warm.get("log") == WARM_LOG, warm
    assert (root / str(warm.get("log"))).is_file(), "读数给的日志路径在盘上不存在"
    assert warm.get("last_line") == FAIL_LINE.strip(), warm
    assert "429" in str(warm.get("last_line")), warm
    assert "429" in str(warm.get("reason")), warm
    assert warm.get("state") != "done", "失败被折成了成功"


# ====================================================================== f 反真空
def test_f_a_the_write_permission_reading_is_not_vacuous(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 把写权限读数打桩成恒 `true` ⇒ a 的断言必红。"""
    from agentflow.webui import cacheface

    counts: dict[str, int] = {}
    _count_status(monkeypatch, counts)
    root = _ws(tmp_path)
    with _server(root, allow_writes=False) as base:
        _code, real = _get(base, "/api/cache")
    assert real.get("writes_allowed") is False, "前提：真读数在只读服务上必须是 false"

    monkeypatch.setattr(cacheface, "_writes_allowed", lambda _h: True, raising=False)
    with _server(root, allow_writes=False) as base:
        _code, stubbed = _get(base, "/api/cache")
    assert stubbed.get("writes_allowed") is True, (
        "打桩之后读数没变 ⇒ 说明这一格不是由 `_writes_allowed` 决定的（判据接在别处）")
    assert stubbed.get("writes_reason") == "", stubbed
    # 这就是 a 会红的那一形态：同一条断言在打桩之后不成立
    assert stubbed.get("writes_allowed") != real.get("writes_allowed")


def test_f_b_the_three_states_are_not_vacuous(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 把三态判定打桩成恒 `done` ⇒ d 必红（刚起的那一趟会被读成跑完了）。"""
    from agentflow.webui import cacheface

    counts: dict[str, int] = {}
    _count_status(monkeypatch, counts)
    alive = {"value": True}
    _stub_alive(monkeypatch, alive)
    _stub_spawn(monkeypatch)
    root = _ws(tmp_path)
    with _server(root, allow_writes=True) as base:
        code, _got = _post(base, "/api/cache/warm", {"lean": "off", "confirm": "1"})
        assert code == 200, code
        monkeypatch.setattr(
            cacheface, "_decide_warm_state",
            lambda *_a, **_kw: {"state": "done", "reason": "恒 done",
                                "last_line": "", "tail": []}, raising=False)
        _read_code, stubbed = _get(base, "/api/cache")
    warm = stubbed.get("warm") or {}
    assert warm.get("state") == "done", (
        "打桩之后仍然读到 running ⇒ 这一格不是由 `_decide_warm_state` 决定的")
    assert "恒 done" in str(warm.get("reason")), warm
    # 这就是 d 会红的那一形态：d 的第一条断言（刚起必须是 running）在这里不成立
    assert warm.get("state") != "running"
