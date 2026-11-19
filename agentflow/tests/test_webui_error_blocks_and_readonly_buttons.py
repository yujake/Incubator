"""判据（鲁棒 e / f）：错误块带 kind + how_to_fix；只读档按钮禁用并写明为什么。

## 两件事，两条链

- e：任何 4xx/5xx 的写回执都要能读出"哪一档"与"怎么办"。后端在
  `writes._finish` 里对失败那一支加 `kind` / `how_to_fix`（成功那一支一个字节都不加），
  `/api/*` 的未知端点 404 也带同一对；前端 `ApiError` 把它们读出来，`ErrorBlock`
  一起摆到屏幕上。
- f：写权限是**服务进程**的事实（`--allow-writes`）。`/api/state` 现在带
  `writes_allowed` / `writes_reason`（判定口径只有 `writes.writes_allowed` 一处），
  页面据此把写按钮禁用并把理由写在按钮旁 —— 不许让人按出 403 才知道自己没权限。

## 判据的分层

1. 纯函数：`refusal_reading` 的每一档（写面没开 / CSRF / 确认缺失 / 500）；
2. 回执：`_finish` 在失败时真的把两栏写进 JSON（成功时不写）；
3. 端点：真起一个只读服务 ⇒ `GET /api/state` 的 `writes_allowed is False` 且
   `writes_reason` 逐字等于 `writes.WRITES_OFF_REASON`；`GET /api/ghost` 的 404
   带 `kind="unknown_endpoint"` 与一句 how_to_fix；
4. 页面：Budget / Home / Stop 读 `writesAllowed === false` 并把它接到 disabled 上；
   三处都用 `ErrorBlock`（不再是各页拼一句字符串）；ErrorBlock 真的印 how_to_fix。

反真空（三条负控）：把 `writes_off` 那一档的 kind 改掉 / 把页面里的
`writesAllowed === false` 删掉 / 把 ErrorBlock 的 how_to_fix 删掉 —— 三条都会红。
"""
from __future__ import annotations

import http.client
import json
import pathlib
import re
import threading

import pytest

from agentflow import webui as W
from agentflow.webui import writes as WR
from agentflow.webui import state as ST

REPO = pathlib.Path(__file__).resolve().parents[1]
UI = REPO / "ui" / "src"
BUDGET_TSX = UI / "pages" / "Budget.tsx"
HOME_TSX = UI / "pages" / "Home.tsx"
STOP_TSX = UI / "components" / "Stop.tsx"
ERROR_TSX = UI / "components" / "ErrorBlock.tsx"


class _FakeHandler:
    """只给 `_finish` 用得上的三样：root / allow_writes / _json 的出口。"""

    def __init__(self, root: pathlib.Path, *, allow_writes: bool) -> None:
        self.root = str(root)
        self.allow_writes = allow_writes
        self.allow_settings_write = True
        self.csrf_token = "t"
        self.headers = {"X-CSRF-Token": "t", "Host": "127.0.0.1:1", "Origin": ""}
        self.client_address = ("127.0.0.1", 1234)
        self.sent: dict | None = None
        self.code = 0

    def _json(self, code: int, body: dict) -> None:
        self.code = code
        self.sent = body


def test_refusal_reading_has_a_kind_and_a_hint_for_every_branch() -> None:
    """正控：每一档都有 kind + 一句能照做的 how_to_fix。"""
    cases = [
        (403, "POST /api/stop：写面没开 —— 要用 `agentflow web --allow-writes` 才允许写",
         "writes_off"),
        (403, "POST /api/stop：CSRF 令牌不对或没带（写请求必须带 X-CSRF-Token）", "csrf_token"),
        (403, "POST /api/settings：设置写面被 --no-settings-write 关掉了", "settings_off"),
        (403, "POST /api/stop：来源不是本机回环（跨站请求一律拒）", "foreign_origin"),
        (400, "拒绝：叫停不可逆，必须带 confirm=1 一次显式确认", "confirm_required"),
        (400, "拒绝：金额必须是正数", "bad_request"),
        (500, "停机开关没写成：OSError: x", "internal"),
    ]
    for code, reason, want in cases:
        kind, hint = WR.refusal_reading(code, reason)
        assert kind == want, (code, reason, kind)
        assert hint.strip(), (code, reason)
    # 负控：写面没开那一档的 kind 一旦改名，上面第一条就红（判据有对象）。
    assert WR.refusal_reading(403, cases[0][1])[0] != "writesOff"


def test_a_failed_write_carries_kind_and_how_to_fix_but_a_success_does_not(
        tmp_path: pathlib.Path) -> None:
    """回执：失败带两栏、成功不带（成功那一支一个字节都不加）。"""
    handler = _FakeHandler(tmp_path, allow_writes=False)
    body = WR._finish(handler, endpoint="POST /api/stop", source="test", params={},
                      code=403, result="拒绝：写面没开 —— 要用 `agentflow web --allow-writes` 才允许写",
                      ok=False)
    assert body["kind"] == "writes_off", body
    assert "allow-writes" in body["how_to_fix"], body
    assert handler.code == 403 and handler.sent == body
    ok_handler = _FakeHandler(tmp_path, allow_writes=True)
    ok_body = WR._finish(ok_handler, endpoint="POST /api/stop", source="test", params={},
                         code=200, result="已叫停", ok=True)
    assert "kind" not in ok_body and "how_to_fix" not in ok_body, ok_body


def _get(base: str, path: str) -> tuple[int, str]:
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read().decode("utf-8")
    finally:
        conn.close()


def test_the_state_endpoint_says_why_writes_are_off(tmp_path: pathlib.Path) -> None:
    """端点：只读服务的 /api/state 带 writes_allowed=false + 逐字理由；404 带 kind。"""
    srv = W.serve(tmp_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"{srv.server_address[0]}:{srv.server_address[1]}"
    try:
        code, text = _get(base, "/api/state")
        assert code == 200, (code, text[:200])
        snap = json.loads(text)
        assert snap["writes_allowed"] is False, snap.get("writes_allowed")
        assert snap["writes_reason"] == WR.WRITES_OFF_REASON, snap.get("writes_reason")
        code2, text2 = _get(base, "/api/ghost")
        assert code2 == 404, (code2, text2[:200])
        bad = json.loads(text2)
        assert bad["kind"] == "unknown_endpoint", bad
        assert bad["how_to_fix"].strip(), bad
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def test_snapshot_defaults_to_not_asked_not_to_cannot_write(tmp_path: pathlib.Path) -> None:
    """三态：直接调 snapshot() ⇒ `None`（没问过），不是 `False`（不能写）。"""
    snap = ST.snapshot(tmp_path)
    assert snap["writes_allowed"] is None, snap["writes_allowed"]
    assert snap["writes_reason"] == "", snap["writes_reason"]
    got = ST.snapshot(tmp_path, writes_allowed=False, writes_reason="理由")
    assert got["writes_allowed"] is False and got["writes_reason"] == "理由", got


def _page_problems(name: str, text: str) -> list[str]:
    """一张页面有没有把"只读 ⇒ 禁用 + 写明为什么"接上（纯函数，可负控）。"""
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    problems: list[str] = []
    if "writesAllowed === false" not in code:
        problems.append(f"{name} 没有读 writesAllowed === false（只读档不会禁用按钮）")
    if "disabled={" not in code:
        problems.append(f"{name} 没有把 disabled 接上")
    if "ErrorBlock" not in code:
        problems.append(f"{name} 没有用 ErrorBlock（错误被拼成一句字符串）")
    return problems


def test_the_pages_disable_writes_and_show_the_reason() -> None:
    """页面：三处写入口都接上禁用 + ErrorBlock；ErrorBlock 真的印 kind/how_to_fix。"""
    for path in (BUDGET_TSX, HOME_TSX, STOP_TSX):
        text = path.read_text(encoding="utf-8")
        assert _page_problems(path.name, text) == [], _page_problems(path.name, text)
    block = ERROR_TSX.read_text(encoding="utf-8")
    for needle in ("howToFix", "backendKind", "怎么办", "f.kind"):
        assert needle in block, f"ErrorBlock 没有 {needle}"
    # 负控：把 Budget 的只读判据删掉 ⇒ 必须红。
    budget = BUDGET_TSX.read_text(encoding="utf-8")
    assert _page_problems("Budget.tsx", budget.replace("writesAllowed === false", "false")), (
        "只读判据负控没红")
