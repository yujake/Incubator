# -*- coding: utf-8 -*-
"""两档提示词缓存的用户面判据（业主 2026-10-23 的施工单）。

## 这一组守什么

| 条 | 判据 | 改前为什么红 |
|---|---|---|
| ① | 两档都有数据 ⇒ 两档都是 `found` + `fresh`；删掉一档 ⇒ 那一档 `unknown` + 理由，且不回落到另一档 | 没有 `cachectl` 之前，没有任何地方能回答"这一档落地了吗" |
| ② | 把某一档里某个目标的 `prompt_sha256` 改错 ⇒ 那一档 `fresh=False` 并点名它 | 没有"现渲染摘要 vs 读数摘要"这一比 |
| ③ | 换 key 指纹 ⇒ `key.tri="stale"` + 点名受影响智能体；网页提醒文案与命令行那一行都在 | 读数里没有 key 指纹这一格 |
| ④ | 写面：不带写面开关 ⇒ 403；不带 `confirm=1` ⇒ 400；`dry_run=1` ⇒ 零调用零花费 | 没有可点的按钮端点 |
| ⑤ | 反真空：把"新鲜度比对"打桩成恒真 ⇒ ② 必红；把"key 指纹比对"打桩成恒同 ⇒ ③ 必红 | 判据若接在别处，打桩不会让它变 |

## 默认零模型钱

本文件一个请求都不发：①–③ 用 `tmp_path` 里造的读数文件加"真渲染出来的摘要"
（渲染只算字符串，零调用）；④ 只走 `dry_run=1` 那一条路（它同步算计划、不起子进程），
并把 `cacheface._plan` 打桩、把 `_spawn_warm` 打成"被调用就失败"。真预热留给用户点按钮。

## 为什么夹具的摘要是"真渲染"的

自己编一个摘要再让它与"现渲染"对不上，那是把判据接在一根断掉的线上：`fresh` 会被
算成 `False`，而原因与"提示词改了"毫无关系。所以夹具逐目标取
`scripts/warm_prompt_cache.py::render_prompts()` 的 `prompt_sha256` —— 与产品算新鲜度
用的是同一份实现（`cachectl` 也是从这里取的）。
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
#: 前端那两个文件的落点（③ 要证明提醒文案真的上得了页面）。
BANNER_TSX = REPO / "ui" / "src" / "components" / "PromptCache.tsx"
API_TS = REPO / "ui" / "src" / "api.ts"

#: 判据自己的 CSRF 令牌（`serve(csrf_token=...)` 钉住它，于是请求头可预期）。
CSRF = "cache-panel-csrf-0123456789"

#: 夹具里那一趟用的 key 指纹（16 位十六进制形态，与 `cachectl.fingerprint` 同宽）。
KEY_A = "0123456789abcdef"
#: "换了 key"之后当前这一片（同一个工作区，另一把 key）。
KEY_B = "fedcba9876543210"


# ====================================================================== 夹具
@pytest.fixture(scope="module")
def renders() -> dict[str, dict[str, dict[str, Any]]]:
    """两档各渲染一遍（约 1 秒；只渲染字符串，零模型调用）。"""
    from agentflow import cachectl as C

    C.clear_render_cache()
    got = C.render_all()
    C.clear_render_cache()
    return got


def _key(fingerprint: str = KEY_A, model: str = "deepseek-flash",
         base_url: str = "https://api.deepseek.com/v1") -> dict[str, Any]:
    """一份"当前 key"的读数（形状与 `cachectl.key_reading()` 相同）。"""
    return {"configured": True, "source": "test", "model": model,
            "base_url": base_url, "key_chars": 32, "fingerprint": fingerprint}


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
         prompt_version: str, key: str = KEY_A, model: str = "deepseek-flash",
         base_url: str = "https://api.deepseek.com/v1",
         spent_usd: float = 0.012345) -> dict[str, Any]:
    """读数文件里的一趟（这一档的每个目标各一行，受控缺席的那几个是 `kind="absent"`）。"""
    rows = [_row(target, item, at=at) for target, item in rendered.items()]
    hidden = [target for target, item in rendered.items()
              if str(item.get("kind")) == "absent"]
    return {"schema": 1, "at": at, "verdict": "warmed", "lean_enabled": tier == "on",
            "prompt_version": prompt_version, "roles": list(rendered),
            "hidden": hidden, "rows": rows, "spent_usd": spent_usd,
            "model": model, "base_url": base_url,
            "key_fingerprint": key, "key_model": model, "key_base_url": base_url}


def _write(tmp_path: pathlib.Path, runs: list[dict[str, Any]]) -> pathlib.Path:
    path = tmp_path / "prompt_cache_warm.json"
    path.write_text(json.dumps({"schema": 1, "runs": runs}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


@pytest.fixture()
def both_tiers(tmp_path: pathlib.Path,
               renders: dict[str, dict[str, dict[str, Any]]]) -> tuple[pathlib.Path, Any]:
    """两档都新鲜的读数文件（① 的正控，也是 ② ③ 的底子）。"""
    from agentflow import agent_prompts as AP
    from agentflow import cachectl as C

    runs = [_run("off", renders["off"], at="2026-10-23T01:00:00Z",
                 prompt_version=AP.PROMPT_VERSION),
            _run("on", renders["on"], at="2026-10-23T01:05:00Z",
                 prompt_version=AP.PROMPT_VERSION)]
    return _write(tmp_path, runs), C


# ====================================================================== ① 落地与新鲜
def test_1_both_tiers_are_found_and_fresh_when_both_have_readings(
        both_tiers: tuple[pathlib.Path, Any]) -> None:
    """① 正控：两档都有数据 ⇒ 两档 `found` + `fresh`，覆盖数对得上，L 是受控缺席。"""
    path, C = both_tiers
    doc = C.status(path=path, renders=C.render_all(), key=_key())
    assert set(doc["tiers"]) == {"off", "on"}, doc["tiers"].keys()
    for tier in ("off", "on"):
        got = doc["tiers"][tier]
        assert got["tri"] == "found", (tier, got["reason"])
        assert got["warmed"] is True, tier
        assert got["fresh"] is True, (tier, got["not_fresh"], got["fresh_reason"])
        assert got["not_fresh"] == [], (tier, got["not_fresh"])
        assert got["missing"] == [], (tier, got["missing"])
    assert doc["tiers"]["off"]["covered"] == 11, doc["tiers"]["off"]["covered"]
    assert doc["tiers"]["on"]["covered"] == 12, doc["tiers"]["on"]["covered"]
    assert doc["tiers"]["off"]["absent"] == ["L"], doc["tiers"]["off"]["absent"]
    assert doc["tiers"]["on"]["absent"] == [], doc["tiers"]["on"]["absent"]
    assert doc["verdict"]["tri"] == "fresh", doc["verdict"]


def test_1b_a_deleted_tier_is_unknown_and_never_falls_back_to_the_other(
        tmp_path: pathlib.Path, renders: dict[str, dict[str, dict[str, Any]]]) -> None:
    """① 负控：删掉一档 ⇒ 那一档 `unknown` + 理由；读数一格都不许从另一档借。

    这一条是整批里最要紧的一条：`cache_readings()` 在"这一档没有读数"时给的也是
    unknown，回落（"找不到就取最近一趟"）会把这里读成一份合格的读数 —— 而那种假绿
    没有任何地方会报错。
    """
    from agentflow import agent_prompts as AP
    from agentflow import cachectl as C

    only_on = _write(tmp_path, [_run("on", renders["on"], at="2026-10-23T01:05:00Z",
                                     prompt_version=AP.PROMPT_VERSION)])
    doc = C.status(path=only_on, renders=renders, key=_key())
    off = doc["tiers"]["off"]
    assert off["tri"] == "unknown", off
    assert off["reason"] == "cache_missing_for_lean_state", off["reason"]
    assert off["warmed"] is False, off
    assert off["fresh"] is None, "没有读数时新鲜度只能是 unknown（不是 False）"
    assert off["covered"] == 0 and off["covered_fresh"] == 0, off
    # 不许回落到另一档：这一档每个目标都没有"读数里的摘要"
    recorded = {t: cell["recorded_sha256"] for t, cell in off["per_target"].items()}
    assert set(recorded.values()) == {""}, recorded
    # 而另一档照旧是新鲜的那一份（删掉一档不影响另一档）
    assert doc["tiers"]["on"]["tri"] == "found", doc["tiers"]["on"]
    assert doc["tiers"]["on"]["fresh"] is True, doc["tiers"]["on"]
    # 受控缺席照样认得出来（它由渲染决定，不由读数决定）
    assert off["absent"] == ["L"], off["absent"]
    assert "L" not in off["missing"], off["missing"]
    assert doc["verdict"]["tri"] == "unknown", doc["verdict"]


# ====================================================================== ② 新鲜度
def _corrupted(both_path: pathlib.Path, tier: str, target: str) -> pathlib.Path:
    """把某一档里某个目标那一行的 `prompt_sha256` 改错（其余一个字节不动）。"""
    doc = json.loads(both_path.read_text(encoding="utf-8"))
    for run in doc["runs"]:
        if bool(run.get("lean_enabled")) != (tier == "on"):
            continue
        for row in run["rows"]:
            if str(row.get("role")) == target:
                row["prompt_sha256"] = "0" * 64
    out = both_path.parent / f"corrupt-{tier}-{target}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def test_2_a_wrong_prompt_sha_is_named_as_not_fresh(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]]) -> None:
    """② 改错一个摘要 ⇒ 那一档 `fresh=False`，并点名是哪个目标；另一档不受牵连。"""
    path, C = both_tiers
    bad = _corrupted(path, "off", "B")
    doc = C.status(path=bad, renders=renders, key=_key())
    off = doc["tiers"]["off"]
    assert off["tri"] == "found", off
    assert off["fresh"] is False, off
    assert off["not_fresh"] == ["B"], off["not_fresh"]
    assert off["covered_fresh"] == off["covered"] - 1, (off["covered_fresh"], off["covered"])
    assert doc["tiers"]["on"]["fresh"] is True, doc["tiers"]["on"]
    assert doc["verdict"]["tri"] == "stale", doc["verdict"]
    assert doc["verdict"]["stale_tiers"] == ["off"], doc["verdict"]


# ====================================================================== ③ 换 key
def test_3_a_changed_key_is_stale_and_names_the_affected_agents(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        capsys: pytest.CaptureFixture[str]) -> None:
    """③ 换 key 指纹 ⇒ `key.tri="stale"` + 点名受影响 target；提醒文案在网页与命令行都在。"""
    path, C = both_tiers
    doc = C.status(path=path, renders=renders, key=_key(KEY_B))
    for tier in ("off", "on"):
        got = doc["tiers"][tier]["key"]
        assert got["tri"] == "stale", (tier, got)
        assert got["affected"], f"{tier} 没有点名受影响的智能体：{got}"
        assert set(got["affected"]) <= set(C.all_targets()), got["affected"]
        assert "重落" in got["text"], got["text"]
    reminder = doc["reminder"]
    assert reminder["active"] is True, reminder
    assert reminder["tri"] == "stale", reminder
    assert "重落" in reminder["text"], reminder["text"]
    assert reminder["affected"], reminder
    # 关掉横幅的那一格必须随 key 变（否则换 key 之后被关掉的提醒不会再来）
    doc_other = C.status(path=path, renders=renders, key=_key(KEY_A))
    assert doc_other["reminder"]["active"] is False, doc_other["reminder"]
    assert doc_other["reminder"]["dismiss_key"] != reminder["dismiss_key"], (
        doc_other["reminder"]["dismiss_key"], reminder["dismiss_key"])

    # 命令行这一行必须印出来（`cache status` 的最后一行就是它）
    code = C.cmd_status(_ns(readings=str(path)))
    out = capsys.readouterr().out
    assert code == C.EXIT_STALE, code
    assert "提醒：" in out and "重落" in out, out
    assert "受影响的智能体" in out or "受影响智能体" in out, out

    # 网页那条横幅：组件真的把 `reminder.text` 画出来，并且与被点名的角色同源
    assert BANNER_TSX.is_file(), BANNER_TSX
    banner = BANNER_TSX.read_text(encoding="utf-8")
    assert "reminder.text" in banner, "横幅没有渲染后端给的提醒文案"
    assert "reminder.active" in banner, "横幅没有看 active 这一格"
    assert "dismiss_key" in banner, "横幅没有按 dismiss_key 记住『关掉过』"
    # 端点声明（契约 A 的另一半：前端必须声明后端这两条）
    api_ts = API_TS.read_text(encoding="utf-8")
    assert '"/api/cache"' in api_ts and '"/api/cache/warm"' in api_ts, "api.ts 少了缓存端点"


def _ns(**kw: Any) -> Any:
    """一个最小的命令行参数命名空间（`cmd_status` / `cmd_warm` 只读这几个字段）。"""
    import argparse

    base: dict[str, Any] = {"json": False, "readings": "", "lean": "", "dry_run": False,
                            "cap_usd": None, "model": ""}
    base.update(kw)
    return argparse.Namespace(**base)


# ====================================================================== ④ 写面
@contextlib.contextmanager
def _server(root: pathlib.Path, *, allow_writes: bool) -> Iterator[str]:
    """在临时端口上起一个服务（写面开关由判据钉住）。"""
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
    body = urllib.parse.urlencode(fields or {}, doseq=True).encode("utf-8")
    headers: dict[str, str] = {"Content-Type": "application/x-www-form-urlencoded",
                              "Content-Length": str(len(body))}
    if csrf is not None:
        headers["X-CSRF-Token"] = csrf
    conn = http.client.HTTPConnection(base, timeout=20)
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
    conn = http.client.HTTPConnection(base, timeout=20)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        text = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(text)
    finally:
        conn.close()


def test_4_the_web_face_requires_the_write_switch_and_a_confirmation(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        renders: dict[str, dict[str, dict[str, Any]]]) -> None:
    """④ 写面三档：没开写面 ⇒ 403；缺确认 ⇒ 400；`dry_run=1` ⇒ 200 且零调用零花费。

    `_spawn_warm` 被打成"被调用就失败"：`dry_run` 那一条路若偷偷起了进程，判据会在这里红。
    """
    from agentflow.webui import cacheface

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("dry_run 不该起子进程（真预热才起）")

    monkeypatch.setattr(cacheface, "_spawn_warm", _boom)

    # 写面没开：403，且盘上什么都不写
    root = tmp_path / "ws-nocsw"
    root.mkdir()
    with _server(root, allow_writes=False) as base:
        code, got = _post(base, "/api/cache/warm",
                          {"lean": "off", "confirm": "1"})
    assert code == 403, (code, got)
    assert got["tri"] == "not_applicable", got
    assert "写面没开" in got["reason"], got
    # 被拒的那一次也进审计台账（`writes._finish` 的统一口径），而它没有被当成成功
    ledger = root / "web-actions.jsonl"
    assert ledger.is_file(), "被拒的写尝试也该留一行审计"
    assert '"computed"' not in ledger.read_text(encoding="utf-8"), "被拒的一次被记成了 computed"

    # 写面开着、缺 confirm：400（一个字节都不写）
    root2 = tmp_path / "ws-noconfirm"
    root2.mkdir()
    with _server(root2, allow_writes=True) as base:
        code, got = _post(base, "/api/cache/warm", {"lean": "off"})
    assert code == 400, (code, got)
    assert got["tri"] == "not_applicable", got
    assert "confirm=1" in got["reason"], got

    # 白名单：lean=both / lean=x 都不认（网页上一个按钮一档）
    with _server(root2, allow_writes=True) as base:
        code, got = _post(base, "/api/cache/warm", {"lean": "both", "confirm": "1"})
    assert code == 400, (code, got)
    assert "lean" in got["reason"], got

    # dry_run=1：200，零调用零花费（计划由打桩的那一层给，子进程那条路不许被碰）
    calls: list[dict[str, Any]] = []

    def _fake_plan(**kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return {"code": 0, "doc": {"verdict": "dry_run",
                                   "tiers": {"off": {"to_warm": ["A"], "skip_fresh": [],
                                                     "absent": ["L"], "calls": 1,
                                                     "usd_est": 0.001}},
                                   "calls_total": 1, "usd_est_total": 0.001}}

    monkeypatch.setattr(cacheface, "_plan", _fake_plan)
    with _server(root2, allow_writes=True) as base:
        code, got = _post(base, "/api/cache/warm",
                          {"lean": "off", "confirm": "1", "dry_run": "1"})
    assert code == 200, (code, got)
    assert got["ok"] is True and got["tri"] == "computed", got
    assert "0 美元" in got["reason"], got["reason"]
    assert calls and calls[0]["tiers"] == ("off",), calls
    assert got["extra"]["dry_run"] is True, got["extra"]


def test_4b_the_status_endpoint_is_a_read_only_json_face(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 的另一半：`GET /api/cache` 走通（只读；回读数是 JSON，不是 HTML）。"""
    from agentflow.webui import cacheface

    seen: list[str] = []

    def _fake_status() -> dict[str, Any]:
        seen.append("called")
        return {"schema": 1, "tiers": {"off": {"tier": "off"}},
                "reminder": {"active": False}}

    monkeypatch.setattr(cacheface, "_status", _fake_status)
    root = tmp_path / "ws-read"
    root.mkdir()
    with _server(root, allow_writes=False) as base:
        code, got = _get(base, "/api/cache")
    assert code == 200, (code, got)
    assert got["schema"] == 1 and "tiers" in got, got
    assert seen == ["called"], "处理器没被调用 ⇒ 路由接缝没接上"


def test_4c_the_endpoints_are_not_free_floating(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 反真空：把这两条端点从路由表里拿掉 ⇒ 同一条 POST 变 404。

    没有这一条，"403 / 400 / 200" 三档可能来自别的端点（例如 `/api/run` 那一族的
    前缀匹配），判据会以"有回应"的形态变绿，而缓存按钮其实没接线。
    """
    from agentflow import webui as W
    from agentflow.webui import routes

    root = tmp_path / "ws-noroute"
    root.mkdir()
    without = tuple(row for row in routes.ROUTES if "/api/cache" not in row[1])
    assert len(without) == len(routes.ROUTES) - 2, (len(routes.ROUTES), len(without))
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=True, csrf_token=CSRF,
                  routes_table=without)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"{srv.server_address[0]}:{srv.server_address[1]}"
        code, _got = _post(base, "/api/cache/warm", {"lean": "off", "confirm": "1"})
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)
    assert code == 404, f"拿掉路由之后仍然有响应（{code}）⇒ 这条判据量的不是这两条端点"


# ====================================================================== ⑤ 反真空
def test_5_the_freshness_judge_is_not_vacuous(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 把"新鲜度比对"打桩成恒真 ⇒ ② 必红（改错摘要的那一档会被读成新鲜）。"""
    path, C = both_tiers
    bad = _corrupted(path, "off", "B")
    healthy = C.status(path=bad, renders=renders, key=_key())
    assert healthy["tiers"]["off"]["fresh"] is False, "前提：改错的摘要在真判据下必须不新鲜"

    monkeypatch.setattr(C, "_sha_matches", lambda _a, _b: True)
    stubbed = C.status(path=bad, renders=renders, key=_key())
    assert stubbed["tiers"]["off"]["fresh"] is True, (
        "把比对打成恒真之后仍然读到不新鲜 ⇒ 说明这一格不是由这个比对决定的（判据接在别处）")
    assert stubbed["tiers"]["off"]["not_fresh"] == [], stubbed["tiers"]["off"]
    # 这就是 ② 会红的那一形态：同一条断言在打桩之后不成立
    assert stubbed["tiers"]["off"]["not_fresh"] != ["B"]


def test_5b_the_key_judge_is_not_vacuous(
        both_tiers: tuple[pathlib.Path, Any],
        renders: dict[str, dict[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 把"key 指纹比对"打桩成恒同 ⇒ ③ 必红（换了 key 也读成 `same`）。"""
    path, C = both_tiers
    stale = C.status(path=path, renders=renders, key=_key(KEY_B))
    assert stale["tiers"]["off"]["key"]["tri"] == "stale", "前提：换 key 在真判据下必须 stale"

    monkeypatch.setattr(C, "_key_matches", lambda _a, _b: True)
    stubbed = C.status(path=path, renders=renders, key=_key(KEY_B))
    for tier in ("off", "on"):
        assert stubbed["tiers"][tier]["key"]["tri"] == "same", stubbed["tiers"][tier]["key"]
    assert stubbed["reminder"]["active"] is False, stubbed["reminder"]
    # 这就是 ③ 会红的那一形态：提醒不再出现
    assert stubbed["reminder"]["tri"] != "stale"


# ====================================================================== 默认零花费
def test_the_dry_run_never_touches_the_spending_path(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: pathlib.Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    """默认路径零模型钱：`cache warm --dry-run` 不经过预热脚本的 `warm()`。

    把脚本那个函数打成"被调用就失败"，`--dry-run` 照旧给出计划并返回 0：
    于是"预计花费"那一格是算出来的，而不是发出去之后才有的读数。
    """
    from agentflow import cachectl as C

    mod = C._warm_module()

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("--dry-run 走到了真预热那条路（会花钱）")

    monkeypatch.setattr(mod, "warm", _boom)
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"schema": 1, "runs": []}), encoding="utf-8")
    code = C.cmd_warm(_ns(lean="off", dry_run=True, readings=str(path)))
    out = capsys.readouterr().out
    assert code == C.EXIT_FRESH, code
    assert "一个请求都没发" in out, out
    assert "预计花费" in out, out
    # 整档没有读数 ⇒ 计划里是"全部都要预热"，而不是"没有可预热的"
    assert "要预热 11 个目标" in out, out


def test_warm_refuses_an_unknown_tier(tmp_path: pathlib.Path) -> None:
    """`--lean` 只认 on / off / both：别的值不许被当成"那就预热 off 吧"。"""
    from agentflow import cachectl as C

    path = tmp_path / "x.json"
    path.write_text(json.dumps({"schema": 1, "runs": []}), encoding="utf-8")
    assert C.cmd_warm(_ns(lean="maybe", readings=str(path))) == C.EXIT_UNKNOWN


def test_the_warm_argv_names_the_tier_and_the_root(tmp_path: pathlib.Path) -> None:
    """按钮起来的那条命令逐字：`--root` 在子命令之前，`cache warm --lean <档>` 在之后。"""
    from agentflow.webui import cacheface

    argv = cacheface._warm_argv(tmp_path, "off")
    assert argv[1:4] == ["-B", "-m", "agentflow"], argv
    assert argv[4] == "--root" and argv[5] == str(tmp_path), argv
    assert argv[6:] == ["cache", "warm", "--lean", "off"], argv
    # 网页这一面只认两档（`both` 是命令行才有的那一档）
    assert cacheface.WARM_LEANS == ("on", "off"), cacheface.WARM_LEANS
