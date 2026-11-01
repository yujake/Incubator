# -*- coding: utf-8 -*-
"""A：`agentflow web` 从任意 cwd 起，起的都是"最近的工作区"，且端口会自己找。

## 业主的原话（2026-11-01）

「开网页怎么那么累？」实测三种累：要么 `python -m agentflow.webui …` 必须在 `src/` 下
（否则 `ModuleNotFoundError: No module named 'agentflow'`），要么得自己拼 `--root` 绝对路径、
自己挑端口，要么端口被占时只留一句 connection refused。

## 这一组守什么（每条都是"改前红"的那种）

1. 从任意 cwd 都能起，而且读的是对的那个工作区：同一条命令在仓库根、仓库里的 `temp/`、
   工作区自己这三处执行，`/api/state` 回来的 `root` 都必须是"最近的工作区"。
   改前 `web` 的工作区缺省就是 cwd ⇒ 在仓库根/`temp/` 起出来的服务读的是空目录
   （服务能绑上、URL 能打印，但看的是错的地方 —— 那种绿最坏）。
2. 缺省端口从 8700 起自动挑，被占就换下一个并说明：改前 `web` 把 8788 当显式端口
   转发给 `webui.run`，于是"自动换号"那条路在结构上走不到（显式端口被占只会起不来）。
3. 打印出来的 URL 真能 200：从 URL 里取端口，探一次 `/api/state`。
4. 显式 `--port` 被占 ⇒ 受控拒绝并提示换号：改前只有 webui 那句"换 --port 0"，
   没有"换到哪个号"的提示。

## 为什么是孩子进程

业主的用法是"开一个服务、一直开着"。只有真起一个进程，才能同时看见 URL 那一行、
换号那行说明、以及 `/api/state` 的 200；进程内 `serve()` 测不出"这条命令从别的 cwd 能不能起"。

## 判据怎么读

`_Spawn.wait_url` 只认第一行能解析成 JSON 且带 url 的输出；`--json` 档里人话一律走 stderr，
所以 stdout 逐行可解析（这一点由 `_spawn` 的注释与本文件的断言共同钉住）。
"""
from __future__ import annotations

import json
import os
import pathlib
import queue
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

#: 交付包根（`agentflow/`），孩子进程用它的 `src/` 当 PYTHONPATH。
REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src"

#: 业主定的自动挑号起点（与 `cli.WEB_PORT_START` 同口径；这里写死是为了让"改前"也能读到它）。
PORT_START = 8700

#: 孩子进程等 URL 的上限（秒）。导入 `agentflow.cli` 在本机约 1–2 秒，给足余量。
URL_TIMEOUT = 90.0


def _workspace(path: pathlib.Path) -> pathlib.Path:
    """造一个最小的"工作区"：标记文件 + `data/`。

    为什么不用 `Store.init()`：这一组查的是"起服务的命令把哪个目录当工作区"，
    不是表结构；落一个标记文件（`projects.classify` 与 `_is_workspace_dir` 都认它）
    就足以让"这是工作区"成立，而且让用例快、不写十几张空表。
    """
    path.mkdir(parents=True, exist_ok=True)
    (path / "data").mkdir(exist_ok=True)
    (path / ".agentflow-workspace").write_text("agentflow workspace\n", encoding="utf-8")
    return path


def _env() -> dict[str, str]:
    """孩子进程的环境：把 `src/` 放上 PYTHONPATH（不装包也能从任意 cwd 起），并钉 UTF-8。"""
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8",
           "PYTHONUTF8": "1"}
    env.pop("AGENTFLOW_WEB_TOKEN", None)   # 本机 shell 里带着口令的话，孩子进程会 401
    return env


class _Child:
    """一个 `agentflow web` 孩子进程：stdout/stderr 合流，逐行收进 `lines`。"""

    def __init__(self, cwd: pathlib.Path, *extra: str) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "agentflow", "web", *extra],
            cwd=str(cwd), env=_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        self.lines: list[str] = []
        self.queue: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._pump, name="web-child-stdout", daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        stream = self.proc.stdout
        if stream is None:  # pragma: no cover - Popen 给了 PIPE，这一支只是类型收窄
            return
        for line in stream:
            self.lines.append(line)
            self.queue.put(line)

    def blob(self) -> str:
        return "".join(self.lines)

    def wait_url(self, timeout: float = URL_TIMEOUT) -> dict:
        """等到第一行能解析成"带 url 的 JSON"的输出；进程先退出就把它的全部输出抛出来。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.queue.get(timeout=0.2)
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise AssertionError(
                        f"网页进程没等到 URL 就退出了（code={self.proc.returncode}）：\n"
                        + self.blob()[-3000:])
                continue
            text = line.strip()
            if not text.startswith("{"):
                continue
            try:
                doc = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict) and doc.get("url"):
                return doc
        raise AssertionError(f"{timeout:.0f} 秒内没等到 URL 那一行：\n" + self.blob()[-3000:])

    def stop(self, timeout: float = 15.0) -> int:
        """杀掉孩子进程并收齐它剩下的输出；返回退出码（被 kill 时非 0）。"""
        try:
            if self.proc.poll() is None:
                self.proc.kill()
        except OSError:
            pass
        try:
            code = self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:  # pragma: no cover - 极端情况下不许挂住整批
            code = -1
        try:
            self._reader.join(timeout=timeout)
        except RuntimeError:  # pragma: no cover
            pass
        return int(code)


def _port_of(url: str) -> int:
    from urllib.parse import urlsplit

    got = urlsplit(url).port
    assert got, f"URL 里没有端口：{url}"
    return int(got)


def _api_state(url: str) -> dict:
    """探一次 `/api/state`（判据 ③：打印出来的 URL 必须真能 200）。"""
    target = url.rstrip("/") + "/api/state"
    with urllib.request.urlopen(target, timeout=20) as resp:  # noqa: S310 - 只连本机临时服务
        assert resp.status == 200, (target, resp.status)
        return json.loads(resp.read().decode("utf-8"))


def _free_port(start: int = 8740, span: int = 20) -> int:
    """从 `start` 起找一个真的能绑的空端口（绑完就放，随后交给孩子进程去占）。"""
    for port in range(start, start + span):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise AssertionError(f"{start}..{start + span - 1} 全都被占了，这条判据的夹具前提不成立")


# ====================================================================== ① 任意 cwd
@pytest.mark.parametrize("where", ["仓库根", "仓库里的 temp", "工作区自己"])
def test_web_serves_the_nearest_workspace_from_any_cwd(tmp_path: pathlib.Path,
                                                       where: str) -> None:
    """① 同一条命令在三种 cwd 下都起在"最近的工作区"上（不是 cwd 上）。"""
    repo = tmp_path / "repo"
    ws = _workspace(repo / "projects" / "topic-1")
    assert not (repo / ".agentflow-workspace").exists(), "夹具前提：仓库根不是工作区"
    cwds = {"仓库根": repo, "仓库里的 temp": repo / "temp", "工作区自己": ws}
    cwd = cwds[where]
    cwd.mkdir(parents=True, exist_ok=True)

    child = _Child(cwd, "--json")
    try:
        doc = child.wait_url()
        root = pathlib.Path(str(doc.get("root") or ""))
        # ③ 打印出来的 URL 真能 200
        state = _api_state(str(doc["url"]))
        assert state.get("root") == str(ws.resolve()), (
            f"cwd={cwd} 起的服务读的是 {state.get('root')}，不是最近的工作区 {ws.resolve()}")
        assert root == ws.resolve(), (doc, "打印的 root 与 /api/state 的不一致")
    finally:
        child.stop()


# ====================================================================== ② 自动换号
def test_web_moves_to_the_next_port_when_the_starting_port_is_taken(tmp_path: pathlib.Path) -> None:
    """② 8700 起挑；被占就换下一个，并且说清换成哪个号。"""
    ws = _workspace(tmp_path / "ws")
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", PORT_START))
    holder.listen(1)
    try:
        child = _Child(ws, "--json")
        try:
            doc = child.wait_url()
            used = _port_of(str(doc["url"]))
            assert used > PORT_START, (
                f"{PORT_START} 被占，却仍旧用了 {used}：\n" + child.blob()[-2000:])
            # ③ 换号之后打印的 URL 照样能 200
            state = _api_state(str(doc["url"]))
            assert state.get("root") == str(ws.resolve())
        finally:
            child.stop()
        blob = child.blob()
        assert "自动挑端口" in blob, f"换号了却没说：\n{blob[-2000:]}"
        assert str(used) in blob, f"说明里没点名换成哪个号：\n{blob[-2000:]}"
    finally:
        holder.close()


# ====================================================================== ④ 显式端口被占
def test_an_explicit_port_that_is_taken_is_refused_with_a_hint(tmp_path: pathlib.Path) -> None:
    """④ 显式 `--port` 被占 ⇒ 受控拒绝（非 0）并提示"换到哪个号"。"""
    other = _workspace(tmp_path / "other")
    ws = _workspace(tmp_path / "ws")
    port = _free_port()
    first = _Child(other, "--json", "--port", str(port))
    try:
        doc = first.wait_url()
        assert _port_of(str(doc["url"])) == port, (doc, port)

        second = _Child(ws, "--json", "--port", str(port))
        try:
            code = second.proc.wait(timeout=URL_TIMEOUT)
        finally:
            second.stop()
        blob = second.blob()
        assert code != 0, f"显式端口被占却成功了：\n{blob[-2000:]}"
        assert "被占" in blob, f"没说是端口被占：\n{blob[-2000:]}"
        assert f"--port {port + 1}" in blob, (
            f"没有「换一个号」的提示（应给出 --port {port + 1}）：\n{blob[-2000:]}")
    finally:
        first.stop()
