# -*- coding: utf-8 -*-
"""判据：网页端与命令行读的是同一个落点，报的是同一批读数。

## 现场（业主 2026-11-14）

「仔细完善 CLI 端和网页端……待会你用 CLI 端起一个大真机，并开网页我监控。请做好对齐。」

同一轮里命令行刚修完三处落点缺陷（`--project` 改前不生效、数据写进被跟踪的
`agentflow/data/`；越档旗标 fail-closed；`budget --status` 只读守卫）。网页端如果不跟着
对齐，就会出现最难自查的那一类形态：「两个都"对"的读数，合起来是假的」 ——
命令行说这一趟在 `projects/P`、网页说它在仓库根，而没有任何东西会报错。

## 这一组钉住的四件事

| 判据 | 查什么 | 反真空 |
|---|---|---|
| a | 假缝起一个项目 ⇒ 网页的 project / workspace / sid / 当前轮 / 花费与 CLI 读数逐字相等 | 把"网页读当前项目"打桩成读代码检出根 ⇒ a 必红 |
| b | 网页追加 $0.10 ⇒ `budget.json` 的 `total_usd` 真增 0.10，且 CLI `inspect budget` 立刻读到 | 把预算写入打桩成不写 ⇒ b 必红 |
| c | 与 a 同一个方向的反真空（上面那一格） | —— |
| d | 与 b 同一个方向的反真空（上面那一格） | —— |
| e | `--watch` 打印的 URL 真能打开：HTTP 200，页面里有 project 名 | —— |

另外两条硬约束用读数钉住，不靠"我记得"：

- 根 `data/` 一个字节不变（跑完这一整套之后逐文件 sha256 与跑之前相同）；
- 全程不调真模型（这一组一次 `llmseam` / `providers` 都没碰）。

## 为什么这组用真服务、而不是只读函数

criterion e 要的是"`--watch` 打印的 URL 真能打开"。只对函数做断言没法回答这件事：
URL 是从 `_with_watch` 的 stdout 里抓的，而"打印的地址"与"真在服务的地址"是两件事
（本仓实测过：端口双绑时 URL 照打、请求永远进不来，见
`tests/test_webui_startup_is_not_silent.py` 的文件头）。所以这里起真服务、走真 HTTP。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import pathlib
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from agentflow import budget as B
from agentflow import cli
from agentflow import projects as P
from agentflow import sessions as SS
from agentflow.store import Store
from agentflow.tokenmeter import Charge, TokenMeter
from agentflow.webui import server as WS

#: 真机上的项目名（不是 `project1`：自动命名会把"名字从哪来"这件事掩盖掉）。
PROJECT_NAME = "p-align-20261114"
#: 这一段会话的号。命令行 `--watch --sid` 会原样印出来，网页必须照抄同一个。
SID = "2026-11-14"
#: 打进 `usage_ledger` 的那一笔花销（读数要比对，所以它必须非零）。
SPEND_USD = 0.25
#: 会话里那一条带轮号的事件（`webui.state.round_of` 读的就是这一格）。
ROUND = 3

REPO = pathlib.Path(__file__).resolve().parents[1]
TRACKED_DATA = REPO / "data"


# ====================================================================== 夹具与帮手
def _digest_tree(root: pathlib.Path) -> dict[str, str]:
    """一棵目录下每个文件的 sha256（相对路径 → 摘要）。目录不在 ⇒ 空表。"""
    out: dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        out[str(path.relative_to(root)).replace("\\", "/")] = hashlib.sha256(
            path.read_bytes()).hexdigest()
    return out


def _make_project(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """用命令行那几条同样的函数造一个项目（不花钱：一次模型都不调）。

    为什么不用 `agentflow project run`：它要走端到端主题跑，会调模型。
    这里造的是同一个形状 —— `projects.create_project` 铺骨架、`Store.init` 建表、
    `sessions.append` 落一条带轮号的事件、`TokenMeter.charge` 记一笔花销。
    四件都是命令行那条路自己用的实现，不是另写一份"测试专用落点"。
    """
    base = tmp_path / "projects"
    ref = P.resolve(base, PROJECT_NAME, start="auto")
    P.create_project(ref)
    store = Store(ref.path)
    store.init()
    problem = SS.append(ref.path, {"kind": "agent_step", "round": ROUND,
                                   "role": "M", "task": "对拍"}, sid=SID)[1]
    assert problem == "", problem
    TokenMeter(store).charge(Charge(role="M", scope="reason", tokens_in=10,
                                    tokens_out=5, usd=SPEND_USD))
    return ref.path, base


def _last_json(text: str) -> dict:
    """输出里最后一个 JSON 对象（台面输出前面可能还有带前缀的回执行）。"""
    dec = json.JSONDecoder()
    best: dict | None = None
    idx = 0
    while True:
        i = text.find("{", idx)
        if i < 0:
            break
        try:
            obj, end = dec.raw_decode(text[i:])
        except json.JSONDecodeError:
            idx = i + 1
            continue
        if isinstance(obj, dict):
            best = obj
        idx = i + end
    assert best is not None, f"输出里没有 JSON：{text!r}"
    return best


def _cli_json(argv: list[str], capsys: pytest.CaptureFixture) -> dict:
    """跑一条命令行并把最后一个 JSON 读出来（退出码必须是 0）。

    `inspect` 那一组会套一层外层四格（`ok` / `state` / `data` / `problems`，业主
    2026-10-24 批的 B 格），其余命令直接打对象本身 —— 两种形状都认，
    取的是"那段读数本身"（`data` 在的时候用 `data`）。
    """
    capsys.readouterr()
    assert cli.main(argv) == 0
    obj = _last_json(capsys.readouterr().out)
    inner = obj.get("data")
    return inner if isinstance(inner, dict) else obj


class _Watch:
    """一次 `start --watch` 的真服务：URL、印出来的四格、以及收尾。"""

    def __init__(self, url: str, printed: dict, thread: threading.Thread,
                 srv) -> None:
        self.url = url
        self.printed = printed
        self.thread = thread
        self._srv = srv

    def get(self, path: str = "/") -> tuple[int, bytes]:
        try:
            with urllib.request.urlopen(self.url.rstrip("/") + path, timeout=10) as got:
                return int(got.status), got.read()
        except urllib.error.HTTPError as exc:      # 4xx/5xx 也是"打开了"
            return int(exc.code), exc.read()

    def stop(self) -> None:
        # 真 `shutdown()`：它是唯一能让 `serve_forever()` 退出的口（也是生产路径
        # `_with_watch` 的 finally 调的那一个）。必须从别的线程调 ——
        # `BaseServer.shutdown()` 在 accept 循环自己的线程里调会等死自己。
        with contextlib.suppress(Exception):
            self._srv.shutdown()
        self.thread.join(timeout=20)
        assert not self.thread.is_alive(), "`--watch` 的线程没有退出"


@contextlib.contextmanager
def _watching(monkeypatch: pytest.MonkeyPatch, argv: list[str]):
    """把 `start --watch` 当服务起一次（`port=0`），交出 `_Watch`。

    为什么要换 `serve`：只是为了拿到那个 `srv` 句柄（收尾要用 `shutdown()`）。
    端口、bind、accept、HTTP 全部是真链路 —— 停服务也走真 `shutdown()`。
    判据 e 要回答的正是"打印出来的地址真能打开"，所以这里不许拿替身顶服务。
    """
    real_serve = WS.serve
    started: dict[str, object] = {}

    def _serve(*args, **kwargs):
        srv = real_serve(*args, **kwargs)
        started["srv"] = srv
        return srv

    monkeypatch.setattr(WS, "serve", _serve)
    out = io.StringIO()
    result: dict[str, object] = {}

    def _run() -> None:
        with contextlib.redirect_stdout(out):
            result["code"] = cli.main(list(argv))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    printed: dict = {}
    for _ in range(600):                       # 最多等 30 秒（20 ms × 600）
        text = out.getvalue()
        if text.strip().endswith("}") and "{" in text:
            printed = _last_json(text)
            break
        threading.Event().wait(0.02)
    assert printed, f"`--watch` 没有印出四格读数：{out.getvalue()!r}"
    assert "srv" in started, "`--watch` 没有起服务（serve 没被调用）"
    watch = _Watch(str(printed.get("url") or ""), printed, thread, started["srv"])
    try:
        yield watch
    finally:
        watch.stop()
        assert result.get("code") == 0, f"`--watch` 退出码不是 0：{result!r}"


@pytest.fixture()
def project(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    return _make_project(tmp_path)


# ====================================================================== a) 四格逐字
def test_a_the_page_and_the_cli_read_the_same_project_session_and_money(
        project: tuple[pathlib.Path, pathlib.Path], tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """a) 网页的 project / workspace / sid / 当前轮 / 花费与 CLI 读数逐字相等。

    命令行那一侧全走真台面（`start --dry-run --json` / `start --watch --json` /
    `inspect budget --json`），不拿 Python 直接读盘冒充"CLI 的读数"。
    """
    root, base = project
    # ---- 命令行：项目名与路径（`--dry-run` 一格字节都不写）
    plan = _cli_json(["--root", str(tmp_path), "start", "--mode", "research",
                      "--project", PROJECT_NAME, "--projects-dir", str(base),
                      "--task", "对拍", "--dry-run", "--json"], capsys)
    # ---- 命令行：URL / 工作区 / sid / 当前轮（`--watch` 的四格）
    with _watching(monkeypatch, ["--root", str(tmp_path), "start", "--watch",
                                 "--project", PROJECT_NAME, "--projects-dir", str(base),
                                 "--sid", SID, "--json", "--port", "0"]) as watch:
        printed = watch.printed
        # ---- 网页：同一份盘上的读数（真 HTTP）
        code, body = watch.get("/api/state")
        assert code == 200, (code, body[:400])
        state = json.loads(body.decode("utf-8"))
        code, body = watch.get("/api/budget")
        assert code == 200, (code, body[:400])
        budget = json.loads(body.decode("utf-8"))
    # ---- 命令行：花费（与网页 `/api/budget` 同一本账）
    money = _cli_json(["--root", str(root), "inspect", "budget", "--json"], capsys)

    # 四格逐字相等（不是"差不多"："路径归一之后相等"会把落点错位也放过）
    assert state["project"]["name"] == plan["project"]["name"] == PROJECT_NAME
    assert state["project"]["path"] == plan["project"]["path"] == str(root)
    assert state["root"] == plan["workspace"] == str(root)
    assert state["current"]["sid"] == printed["sid"] == SID
    assert state["current"]["round"] == printed["round"] == ROUND
    assert str(printed["root"]) == str(root)
    # 花费：网页与命令行读同一本 `usage_ledger`
    assert budget["spent_usd"] == money["spent_usd"] == pytest.approx(SPEND_USD)
    assert state["project"]["is_project"] is True
    assert state["current"]["found"] is True


def test_c_negative_control_reading_the_checkout_root_bends_the_reading(
        project: tuple[pathlib.Path, pathlib.Path], tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """c）反真空：把"网页读当前项目"打桩成读代码检出根 ⇒ 判据 a 必红。

    打桩的是读数本身（`webui.state.project_reading` 被换成"无视给它的根、
    一律读 `cli.DEFAULT_ROOT`"），不是调用点 —— 那正是"网页读的是根 `data/`"
    这个错误的形态。打桩之后 project 那一格指的是代码检出目录，与命令行的读数
    不再逐字相等；这条用例断言"不等"，于是它证明的是 a 那条断言能分辨落点。
    """
    from agentflow.webui import state as W

    root, base = project
    plan = _cli_json(["--root", str(tmp_path), "start", "--mode", "research",
                      "--project", PROJECT_NAME, "--projects-dir", str(base),
                      "--task", "对拍", "--dry-run", "--json"], capsys)
    real = W.project_reading

    def _stub(_root):
        """负控：无视服务起来的那个根，一律读代码检出目录（= 根 `data/` 那一侧）。"""
        return real(cli.DEFAULT_ROOT)

    monkeypatch.setattr(W, "project_reading", _stub)
    with _watching(monkeypatch, ["--root", str(tmp_path), "start", "--watch",
                                 "--project", PROJECT_NAME, "--projects-dir", str(base),
                                 "--sid", SID, "--json", "--port", "0"]) as watch:
        code, body = watch.get("/api/state")
        assert code == 200, (code, body[:400])
        state = json.loads(body.decode("utf-8"))
    assert state["project"]["path"] == str(cli.DEFAULT_ROOT), (
        "负控没生效：打桩之后 project.path 仍是这一趟的项目")
    assert state["project"]["path"] != plan["project"]["path"], (
        "打桩成读根 data/ 之后两处仍然相等 ⇒ 判据 a 分辨不出落点，它是真空的")


# ====================================================================== b) 预算窗口
def test_b_the_web_top_up_really_moves_budget_json_and_the_cli_reading(
        project: tuple[pathlib.Path, pathlib.Path], tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """b）网页追加 $0.10 ⇒ `budget.json` 的 `total_usd` 增 0.10，CLI 立刻读到。

    判据分三层，一层都不许省：

    1. 真的写了盘：直接读 `projects/<名>/budget.json` 的字节；
    2. 增量是 0.10：不是"变成了 0.10"，是在原总额上 `+0.10`（先设 0.5 再追加）；
    3. 命令行立刻读得到：`agentflow inspect budget --json --root <那个项目>` ——
       走的是台面（`cmd_budget`），不是 Python 直接读寄存器。
    """
    root, base = project
    register = root / B.REGISTER_NAME
    # 先设一个已知总额（0.5），这样"增了 0.10"与"变成了 0.10"分得开。
    assert cli.main(["--root", str(root), "budget", "--set", "0.5"]) == 0
    capsys.readouterr()
    before = json.loads(register.read_text(encoding="utf-8"))["total_usd"]
    assert before == pytest.approx(0.5)

    with _watching(monkeypatch, ["--root", str(tmp_path), "start", "--watch",
                                 "--project", PROJECT_NAME, "--projects-dir", str(base),
                                 "--sid", SID, "--json", "--port", "0",
                                 "--allow-writes"]) as watch:
        code, body = _post(watch.url, "/api/budget",
                           {"action": "add", "usd": "0.10", "by": "owner",
                            "note": "让它跑完", "confirm": "1"})
        assert code == 200, (code, body[:400])
        got = json.loads(body.decode("utf-8"))
        assert got["ok"] is True, got

    after_json = json.loads(register.read_text(encoding="utf-8"))
    assert after_json["total_usd"] == pytest.approx(before + 0.10), after_json
    # 回执里的总额那一格（`WriteResult.extra`）与盘上读数必须是同一个数 ——
    # 回执说加上了而盘上没有，正是这一类缺陷最容易被读成"成了"的形态。
    reply_total = (got.get("extra") or {}).get("total_usd")
    assert float(reply_total) == pytest.approx(before + 0.10), (reply_total, got)
    # 追加历史里留着这一笔（谁、什么时候、为什么）
    assert after_json["added"][-1]["kind"] == "add"
    assert after_json["added"][-1]["by"] == "owner"
    assert after_json["added"][-1]["usd"] == pytest.approx(0.10)

    # 命令行立刻读得到（同一个落点：`--root <那个项目>`）
    seen = _cli_json(["--root", str(root), "inspect", "budget", "--json"], capsys)
    assert seen["total_usd"] == pytest.approx(before + 0.10), seen
    # `--project` 那一档（2026-11-14 补的落点旗标）读的是同一份
    seen_by_name = _cli_json(["--root", str(tmp_path), "inspect", "budget",
                              "--project", PROJECT_NAME, "--projects-dir", str(base),
                              "--json"], capsys)
    assert seen_by_name["total_usd"] == seen["total_usd"], (seen_by_name, seen)
    assert seen_by_name["path"] == str(register), seen_by_name


def test_d_negative_control_a_stubbed_top_up_never_moves_the_cli_reading(
        project: tuple[pathlib.Path, pathlib.Path], tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """d）反真空：把"预算写入"打桩成不写 ⇒ 判据 b 必红。

    打桩的是写实现本身（`budget.add_usd` 被换成"回一句 ok、一个字节都不落盘"）——
    那正是"网页显示加上了、盘上没动"这个错误的形态。这里断言盘上的读数没有动，
    于是它证明 b 那条断言真的在读盘，而不是在读回执。
    """
    root, base = project
    register = root / B.REGISTER_NAME
    assert cli.main(["--root", str(root), "budget", "--set", "0.5"]) == 0
    capsys.readouterr()
    before_bytes = register.read_bytes()

    def _stub(_root, _usd, *, by="user", note=""):
        """负控：回执说成了，但一个字节都不写。"""
        return {"ok": True, "path": str(register), "total_usd": 0.6,
                "entry": {"kind": "add", "usd": 0.1, "by": by, "note": note},
                "added_count": 2}

    monkeypatch.setattr(B, "add_usd", _stub)
    with _watching(monkeypatch, ["--root", str(tmp_path), "start", "--watch",
                                 "--project", PROJECT_NAME, "--projects-dir", str(base),
                                 "--sid", SID, "--json", "--port", "0",
                                 "--allow-writes"]) as watch:
        code, body = _post(watch.url, "/api/budget",
                           {"action": "add", "usd": "0.10", "confirm": "1"})
        assert code == 200, (code, body[:400])
        assert json.loads(body.decode("utf-8"))["ok"] is True, body[:400]
    assert register.read_bytes() == before_bytes, (
        "负控没生效：打桩成不写之后 budget.json 仍然变了")
    seen = _cli_json(["--root", str(root), "inspect", "budget", "--json"], capsys)
    assert seen["total_usd"] == pytest.approx(0.5), (
        "打桩成不写之后 CLI 读数仍然跟着涨 ⇒ 判据 b 读的不是盘，它是真空的")


# ====================================================================== e) URL 真能开
def test_e_the_watch_url_opens_and_names_the_project(
        project: tuple[pathlib.Path, pathlib.Path], tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """e）`--watch` 打印的 URL 真能打开：HTTP 200，页面里有 project 名。

    为什么"页面里有 project 名"要当成判据：业主同时开两个项目的两页时，只有标签页与
    顶栏能告诉他"这一页是哪个项目"。名字由服务端在吐外壳时注入
    （`_inject_placeholders`），与 `/api/state` 的 `project` 同一处读数。
    """
    root, base = project
    with _watching(monkeypatch, ["--root", str(tmp_path), "start", "--watch",
                                 "--project", PROJECT_NAME, "--projects-dir", str(base),
                                 "--sid", SID, "--json", "--port", "0"]) as watch:
        assert watch.url.startswith("http://127.0.0.1:"), watch.url
        code, body = watch.get("/")
        assert code == 200, (code, body[:400])
        html = body.decode("utf-8")
        assert PROJECT_NAME in html, html[:600]
        assert 'name="agentflow-project"' in html, html[:600]
        assert f'content="{SID}"' in html, html[:600]
        assert "__PROJECT_NAME__" not in html, "占位符没被替换 —— 页面会把字面量当成项目名"
        # 第二条页面路由（`GET /index.html`）吐的是同一支外壳、同一个注入器：
        # 项目名在那条路上同样必须在（浏览器从地址栏进来走的正是这两条）。
        code, body = watch.get("/index.html")
        assert code == 200 and PROJECT_NAME in body.decode("utf-8"), (code, body[:200])
        # 静态路由那一档刻意不做替换：`web/static/` 是入库的构建产物，判据
        # （`tests/test_webui_static.py::test_the_package_static_dir_is_what_the_static_route_serves`）
        # 要求 `/static/<file>` 吐的字节与盘上那份逐字节相同（只许换 CSRF 令牌）。
        # 占位符留在产物里、由服务端在吐外壳时替换 —— 这是"产物可复核"与"页面能说清
        # 是哪个项目"两条要求的交点。
        code, body = watch.get("/static/index.html")
        assert code == 200
        assert "__PROJECT_NAME__" in body.decode("utf-8"), (
            "入库产物被就地替换过 ⇒ 静态路由不再是盘上那一份（可复核性没了）")


# ====================================================================== 落点不变
def test_the_tracked_data_directory_is_byte_identical_after_the_whole_flow(
        project: tuple[pathlib.Path, pathlib.Path], tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空（落点）：跑完整套之后，被跟踪的仓库根 `data/` 一个字节不变。

    2026-11-14 那次事故的形态是"`--project` 不生效 ⇒ 数据写进被跟踪的 `data/`"。
    这里把根 `data/` 的每个文件摘要前后各取一次：只要有一条流程把字节写到了那边，
    这条判据就红 —— 它比"我看了一眼 git status"硬。
    """
    root, base = project
    before = _digest_tree(TRACKED_DATA)
    assert before, "根 data/ 是空目录？那这条判据没有可比的字节"
    with _watching(monkeypatch, ["--root", str(tmp_path), "start", "--watch",
                                 "--project", PROJECT_NAME, "--projects-dir", str(base),
                                 "--sid", SID, "--json", "--port", "0",
                                 "--allow-writes"]) as watch:
        assert watch.get("/api/state")[0] == 200
        assert _post(watch.url, "/api/budget",
                     {"action": "add", "usd": "0.10", "confirm": "1"})[0] == 200
    assert _digest_tree(TRACKED_DATA) == before, (
        "根 data/ 被写了 —— 这一趟的落点跑到仓库根去了（`--project` 又没生效？）")
    # 项目自己那边确实写到了（正控：不是"两边都没写"）
    assert (root / B.REGISTER_NAME).is_file()
    assert (root / "data" / "events.jsonl").is_file()


# ====================================================================== HTTP 帮手
def _post(url: str, path: str, form: dict[str, str]) -> tuple[int, bytes]:
    """一个带 `X-CSRF-Token` 的表单 POST（令牌从 `GET /` 的 meta 里取，真链路）。"""
    import re

    token = ""
    with urllib.request.urlopen(url.rstrip("/") + "/", timeout=10) as got:
        html = got.read().decode("utf-8", errors="replace")
    hit = re.search(r'name="csrf-token" content="([^"]*)"', html)
    if hit is not None:
        token = hit.group(1)
    data = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + path, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "X-CSRF-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=15) as got:
            return int(got.status), got.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
