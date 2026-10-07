# -*- coding: utf-8 -*-
"""设置写面判据（W4 / 裁定 E1）。

## 守四件事，每件都有正控与负控

1. key 只写不读：真 key 落盘、响应里恒 `***`、页面读的那一面也读不到它。
   负控：把 `settings._masked_section` 改成恒等函数 ⇒ 判据当场红（撤回即绿）。
2. 原子写：写一半失败 ⇒ 盘上那份逐字节不变。负控：把原子写换成"直接截断再写"
   ⇒ 那份必须变（证明"不变"这句话有牙）。
3. 权限：回报的是实测读数（POSIX 上回读 `0o600`；Windows 上如实记
   `mode_enforced=False`，因为 POSIX 模式位管不到 ACL）。
4. 没配/没装/读不出来 ⇒ `unknown`，不崩：三档各一条。

判据全部在 `AGENTFLOW_SETTINGS` 指到临时文件的前提下跑：设置文件是机器级的
（`agentflow/settings.json`），判据绝不碰本机那一份。
"""

from __future__ import annotations

import http.client
import json
import os
import pathlib
import threading
import urllib.parse
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from agentflow import settings as SET
from agentflow import webui as W
from agentflow.store import Store
from agentflow.webui import audit, readers

#: 判据里的"真 key"（一串只可能在判据自己手里出现的东西）。
SECRET = "sk-c-line-must-never-be-echoed-0123456789"
CSRF = "line-c-csrf-token-0123456789"


def _no_secret(blob: str, secret: str = SECRET) -> list[str]:
    """一段文本里有没有真 key。与 `tests/test_settings.py` 的 `_key_echo_problems` 同族。

    做成纯函数是为了能喂"改坏了的文本"：只在正控上亮绿的判据等于没有判据。
    """
    return [f"真 key 出现在文本里（{blob.count(secret)} 处）"] if secret in blob else []


def _target(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
            initial: dict[str, Any] | None = None) -> pathlib.Path:
    """把设置落点钉到临时文件上，并按需预置一份内容。

    最后那一条断言是这套判据的安全绳：万一 `AGENTFLOW_SETTINGS` 没生效，
    `write_settings` 会落到本机那份真设置（`agentflow/settings.json`）上 ——
    判据里绝不允许发生这件事，所以在夹具这一层就把它堵死。
    """
    path = tmp_path / "settings.json"
    if initial is not None:
        path.write_text(json.dumps(initial, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    monkeypatch.setenv(SET.ENV_SETTINGS, str(path))
    assert SET.settings_path() == path, (
        f"落点没被钉住：{SET.settings_path()}（判据不许写到本机那份真设置上）")
    return path


# ====================================================================== 1 key 只写不读
def test_the_key_lands_on_disk_but_never_comes_back_in_the_return(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（E1）：文件里是真 key，返回值里恒 `***`。"""
    target = _target(tmp_path, monkeypatch)
    got = SET.write_settings({"model": {"api_key": SECRET,
                                        "base_url": "https://example.invalid/v1"}})
    assert got["ok"] is True and got["tri"] == "written", got
    # 第一处：文件里是真值
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"]["api_key"] == SECRET, on_disk
    # 第二处：返回值里是掩码
    assert got["values"]["model"]["api_key"] == SET.MASKED_KEY, got["values"]
    assert _no_secret(json.dumps(got, ensure_ascii=False, default=str)) == [], got
    # 读侧那一口照样拿得到真值（只写不读管的是"台面"，不是所有调用方）
    assert SET.model_settings()["api_key"] == SECRET, SET.model_settings()


def test_breaking_the_echo_path_makes_the_criterion_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（回显路径改坏 ⇒ 必红）：把 `_masked_section` 换成恒等函数。

    红前：改坏之后返回值里出现真 key（尺子必须报）；绿后：撤回之后同一个尺子不报。
    这是"key 不回显"这句话唯一的机器读数 —— 少了它，掩码可以哪天被谁顺手去掉，
    而所有判据照样亮绿。
    """
    target = _target(tmp_path, monkeypatch)
    original = SET._masked_section
    monkeypatch.setattr(SET, "_masked_section",
                        lambda section, seg: {str(k): str(v) for k, v in dict(seg).items()})
    doctored = SET.write_settings({"model": {"api_key": SECRET}})
    assert doctored["values"]["model"]["api_key"] == SECRET, doctored["values"]
    assert _no_secret(json.dumps(doctored, ensure_ascii=False, default=str)), \
        "回显路径已经改坏，尺子却没响"
    monkeypatch.setattr(SET, "_masked_section", original)
    healthy = SET.write_settings({"model": {"api_key": SECRET}})
    assert healthy["values"]["model"]["api_key"] == SET.MASKED_KEY, healthy["values"]
    assert _no_secret(json.dumps(healthy, ensure_ascii=False, default=str)) == []
    assert target.is_file()


def test_the_web_response_and_the_page_facing_readings_carry_no_key(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（第三处读数）：HTTP 回执、审计台账、页面读的那一面都没有真 key。

    "页面读的那一面"今天真有的两个路口：`readers.machine_face`（Machine 页的数据源）
    与 `web-actions.jsonl`（"操作历史"那一栏的数据源）。A 线的 Machine 页还没落地，
    所以这里量的是页面将要读的那两份数据，不是一张还不存在的 HTML。
    """
    root = tmp_path / "ws"
    root.mkdir()
    Store(root).init()
    _target(tmp_path, monkeypatch)
    with _server(root) as base:
        code, body, _ctype = _post(base, "/api/settings",
                                   {"model.api_key": SECRET,
                                    "model.base_url": "https://example.invalid/v1",
                                    "confirm": "1"})
    assert code == 200, (code, body[:300])
    assert _no_secret(body) == [], body
    assert json.loads(body)["extra"]["values"]["model"]["api_key"] == SET.MASKED_KEY, body
    ledger_blob = json.dumps(audit.read_actions(root), ensure_ascii=False, default=str)
    assert _no_secret(ledger_blob) == [], ledger_blob
    face_blob = json.dumps(readers.machine_face(root), ensure_ascii=False, default=str)
    assert _no_secret(face_blob) == [], face_blob
    # 文件里仍然是真值（三处读数不是"都没写进去"）
    on_disk = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["model"]["api_key"] == SECRET, on_disk


# ====================================================================== 2 原子写
def test_a_failed_replace_leaves_the_original_file_byte_identical(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（原子写）：替换那一步失败 ⇒ 原文件逐字节不变，结局是 `unknown`。"""
    before_text = json.dumps({"toolchain": {"lean_bin": "/opt/lean-original"}},
                             ensure_ascii=False, indent=2) + "\n"
    target = _target(tmp_path, monkeypatch)
    target.write_text(before_text, encoding="utf-8")
    before = target.read_bytes()
    original_replace = SET.os.replace

    def _boom(*a, **kw):  # noqa: ANN002, ANN003
        raise OSError("桩：替换失败")

    monkeypatch.setattr(SET.os, "replace", _boom)
    got = SET.write_settings({"toolchain": {"lean_bin": "/opt/lean-new"}})
    assert got["ok"] is False and got["tri"] == "unknown", got
    assert target.read_bytes() == before, "替换失败了，盘上那份却被改了"
    monkeypatch.setattr(SET.os, "replace", original_replace)
    assert target.read_text(encoding="utf-8") == before_text
    leftovers = sorted(p.name for p in target.parent.glob(".settings.json.tmp-*"))
    assert leftovers == [], f"失败之后临时文件没收走：{leftovers}"


def test_a_non_atomic_writer_would_have_changed_the_file(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（原子写有牙）：把写入口换成"直接截断再写"⇒ 那份必须变。

    没有这一条，上面那条"逐字节不变"可能只是因为什么都没写
    （一个永远不写的实现也能让"不变"成立）。
    """
    target = _target(tmp_path, monkeypatch,
                     initial={"toolchain": {"lean_bin": "/opt/lean-original"}})
    before = target.read_bytes()
    original_writer = SET._atomic_write_json

    def _naive(path, payload):  # noqa: ANN001
        # 非原子：直接往目标文件上写，然后（模拟）炸在半路
        path.write_text("{ 写了一半就炸了", encoding="utf-8")
        return "OSError: 桩（写一半炸了）"

    monkeypatch.setattr(SET, "_atomic_write_json", _naive)
    got = SET.write_settings({"toolchain": {"lean_bin": "/opt/lean-new"}})
    assert got["tri"] == "unknown", got
    assert target.read_bytes() != before, "非原子写法居然没有改动盘上那份 —— 负控自己失效了"
    # 绿后：撤回那一层、把盘上恢复成原样，再走真写的路 ⇒ 盘上是一份完整合法的 JSON。
    # 这里刻意用显式 setattr 撤回而不是 `monkeypatch.undo()`：后者会连
    # `AGENTFLOW_SETTINGS` 一起撤回，下一次写就落到本机那份真设置上
    # （我实测踩过：那一版把 `agentflow/settings.json` 写掉了，所以夹具里加了安全绳）。
    monkeypatch.setattr(SET, "_atomic_write_json", original_writer)
    target.write_bytes(before)
    assert SET.settings_path() == target, SET.settings_path()
    good = SET.write_settings({"toolchain": {"lean_bin": "/opt/lean-new"}})
    assert good["tri"] == "written" and good["ok"] is True, good
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["toolchain"]["lean_bin"] == "/opt/lean-new", on_disk
    leftovers = sorted(p.name for p in target.parent.glob(".settings.json.tmp-*"))
    assert leftovers == [], f"临时文件没被收走：{leftovers}"


# ====================================================================== 3 权限
def test_permissions_are_reported_as_measured_not_as_hoped(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（权限那格不许编）：回报的 `mode` 是回读出来的，`mode_enforced` 与它一致。

    这一条刻意不断言 `0o600`：Windows 上 POSIX 模式位管不到 ACL，回读出来就是
    `0o666` —— 断言 `0o600` 等于要求实现说谎。钉住的是"读数自洽"这条不变量。
    """
    target = _target(tmp_path, monkeypatch)
    got = SET.write_settings({"toolchain": {"lean_bin": "/opt/lean"}})
    perms = got["permissions"]
    assert got["tri"] == "written", got
    assert perms["mode"].startswith("0o"), perms
    assert perms["platform"] == os.name, perms
    real_mode = target.stat().st_mode & 0o777
    assert perms["mode"] == f"0o{real_mode:o}", (perms, oct(real_mode))
    assert perms["mode_enforced"] is (perms["mode"] == "0o600"), perms
    if not perms["mode_enforced"]:
        assert perms["note"], "没有收紧却说不出为什么 —— 那是假读数"


# ====================================================================== 4 unknown 三档
def test_no_settings_path_at_all_is_unknown_not_a_crash(
        tmp_path: pathlib.Path) -> None:
    """档①：注入环境且没给 `AGENTFLOW_SETTINGS` ⇒ `unknown`（不是异常）。"""
    got = SET.write_settings({"toolchain": {"lean_bin": "/opt/lean"}}, env={})
    assert got["ok"] is False and got["tri"] == "unknown", got
    assert SET.ENV_SETTINGS in got["reason"], got["reason"]


def test_a_broken_settings_file_is_unknown_and_is_never_overwritten(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """档②：盘上那份不是合法 JSON ⇒ `unknown`，且不许覆盖它（先修再写）。"""
    target = _target(tmp_path, monkeypatch)
    target.write_text("{ 这不是 JSON\n", encoding="utf-8")
    before = target.read_bytes()
    got = SET.write_settings({"toolchain": {"lean_bin": "/opt/lean"}})
    assert got["ok"] is False and got["tri"] == "unknown", got
    assert "读不出来" in got["reason"], got["reason"]
    assert target.read_bytes() == before, "坏文件被覆盖了 —— 那会把可修的变成不可修的"


def test_a_wrong_shaped_settings_file_is_unknown_too(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """档②的另一半：合法 JSON 但不是对象 ⇒ 同样是 `unknown`，不是崩。"""
    target = _target(tmp_path, monkeypatch)
    target.write_text("[1, 2, 3]\n", encoding="utf-8")
    got = SET.write_settings({"toolchain": {"lean_bin": "/opt/lean"}})
    assert got["tri"] == "unknown", got
    assert target.read_text(encoding="utf-8") == "[1, 2, 3]\n"


def test_unknown_keys_and_bad_values_are_refused_without_writing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """档③：未知段/未知键/非字符串值 ⇒ `refused`，盘上一个字节都不动。"""
    target = _target(tmp_path, monkeypatch, initial={"model": {"name": "deepseek-chat"}})
    before = target.read_bytes()
    for bad, needle in (({"nope": {"a": "b"}}, "不认这段设置"),
                        ({"model": {"api_keys": "x"}}, "不认 model 段的这个键"),
                        ({"toolchain": {"lean_bin": 123}}, "必须是字符串")):
        got = SET.write_settings(bad)
        assert got["ok"] is False and got["tri"] == "refused", (bad, got)
        assert needle in got["reason"], got["reason"]
    assert target.read_bytes() == before, "被拒的写入居然改了盘"


def test_other_sections_and_unmanaged_keys_survive_a_write(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（合并写）：只动被点名的那几格，其余段落与没登记过的键原样保留。"""
    target = _target(tmp_path, monkeypatch, initial={
        "toolchain": {"lean_bin": "/opt/old-lean", "coq_bin": "/opt/coqc"},
        "workspace": {"projects_dir": "projects"},
        "future_section": {"whatever": "不许被抹掉"},
    })
    got = SET.write_settings({"toolchain": {"lean_bin": "/opt/new-lean"}})
    assert got["tri"] == "written", got
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["toolchain"] == {"lean_bin": "/opt/new-lean", "coq_bin": "/opt/coqc"}, on_disk
    assert on_disk["workspace"] == {"projects_dir": "projects"}, on_disk
    assert on_disk["future_section"] == {"whatever": "不许被抹掉"}, on_disk
    assert got["values"]["toolchain"]["coq_bin"] == "/opt/coqc", got["values"]


def test_clearing_a_field_is_a_legitimate_write(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（空串是合法值）：它是"清掉这一格"的写法，不是"没给"。"""
    target = _target(tmp_path, monkeypatch,
                     initial={"model": {"api_key": "old-key", "name": "deepseek-chat"}})
    got = SET.write_settings({"model": {"api_key": ""}})
    assert got["tri"] == "written", got
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["model"]["api_key"] == "", on_disk
    # 没给 key 时回显是空串（而不是 `***`）：没写过的东西不该长得像写过
    assert got["values"]["model"]["api_key"] == "", got["values"]


def test_the_return_shape_is_the_one_the_web_face_maps(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（词表不许互相顶替，裁定 N1）：本口给的是 `written/refused/unknown`。

    `WriteResult.tri` 那一套是 `computed/unreadable/not_applicable`；两套字符串
    不许顶替，映射发生在 `webui/writes.py` 那一层（判据在 `test_webui_writes.py`）。
    """
    _target(tmp_path, monkeypatch)
    assert SET.write_settings({"toolchain": {"lean_bin": "/opt/lean"}})["tri"] == "written"
    assert SET.write_settings({"nope": {}})["tri"] == "refused"
    assert SET.write_settings({"toolchain": {"lean_bin": "/opt/lean"}},
                              env={})["tri"] == "unknown"
    for name in ("ok", "tri", "reason", "path", "values"):
        assert name in SET.write_settings({"toolchain": {"lean_bin": "/opt/lean"}}), name


# ====================================================================== 夹具
@contextmanager
def _server(root: pathlib.Path, *, allow_writes: bool = True,
            settings_write: bool = True) -> Iterator[str]:
    """起一个带写面的本机服务（设置写面判据只用到 `/api/settings`）。"""
    srv = W.serve(root, host="127.0.0.1", port=0, allow_writes=allow_writes,
                  settings_write=settings_write, csrf_token=CSRF)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{srv.server_address[0]}:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def _post(base: str, path: str, fields: dict[str, Any]) -> tuple[int, str, str]:
    body = urllib.parse.urlencode(fields, doseq=True).encode("utf-8")
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/x-www-form-urlencoded",
                              "Content-Length": str(len(body)),
                              "X-CSRF-Token": CSRF})
        resp = conn.getresponse()
        return (resp.status, resp.read().decode("utf-8", errors="replace"),
                resp.getheader("Content-Type") or "")
    finally:
        conn.close()
