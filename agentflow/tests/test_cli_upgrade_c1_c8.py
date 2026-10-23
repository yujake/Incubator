# -*- coding: utf-8 -*-
"""CLI 大更新（`draft/145-CLI升级方案.md` C1–C8）的判据。

## 这一份守什么

升级的形状是"一个入口讲清干什么 / 在哪干 / 花多少钱 / 开不开 Lean，其余都是它的子模式；
老命令全部保留为别名"。形状本身不是读数，所以每一条都翻成一个能红的断言：

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| C1 | `start --dry-run` 打印将要发生的一切，且一次模型都不调、一个字节都不写 | 预检先把工作区建出来、把钱花了 |
| C2 | 四条老命令的旗标与缺省逐字不变，且四条都落到同一个执行体 | 老脚本里有一条悄悄换了语义 |
| C3 | 缺参数是"人话 + 该给哪个旗标"，不是 argparse 原文 | 用户拿到 `the following arguments are required` |
| C4 | 显式 `--budget-usd` 落进 `budget.json`，且更大的旧寄存器不许静默压过它 | 传了 10 而闸门照旧按 0.5 卡 |
| C5 | `--lean auto` 在 unusable 时继续跑但结论记 unknown 且点名原因；`--lean off` 真的关 | `bool("off")` 为真 ⇒ 关不掉 |
| C6 | 包里一个语法错误报成"文件:行 + 错误"，不是栈 | 一次误伤把整条 CLI 打成 traceback |
| C7 | `--watch` 打印的 URL 可访问，且与 `--project` 同一个工作区 | 网页开在别的工作区上，看到的是别人的读数 |
| C8 | help 首屏能看出分组，且 `--extract-rounds` 不被重复印出 | 26 个子命令分两页才看全 |

## 为什么 C2 要咬着"同一个执行体"

C2 的字面要求是"行为与今天逐字一致"，而它容易退化成"四个函数各写一遍、谁漂了都没人
看得见"。所以除了断言旗标缺省，还断言四条命令真的都走进同一个 `cli._run_spec` ——
那是"旗标只在这一层归一"这句话唯一的机器读数。

## 负控

C6 的扫描器在一个人造包上先证明自己接得上（好文件不报、坏文件报在该报的行），
再让它扫真包；C8 的分组表由一条"并集等于全部子命令"的断言守着，漏登记不会静默消失。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.request import urlopen

import pytest

from agentflow import cli

#: 仓库根（`agentflow/`）：子进程那条判据要把 `src` 接进 `PYTHONPATH`。
REPO = Path(__file__).resolve().parents[1]

#: 产物里的时间戳（固定值，让 C4 那一趟可复现）。
TS = "2026-10-22T00:00:00+08:00"


def _run(argv: list[str]) -> tuple[int, str, str]:
    """在进程内跑一次 CLI，返回 `(退出码, stdout, stderr)`。

    三路分开收：`--json` 那一档要求 stdout 可解析，所以"有没有人话混进 stdout"
    这件事必须是可断言的，而不是靠肉眼看输出。
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse: --help(0) / 用法错(2)
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue(), err.getvalue()


def _fake_project_run(seen: dict):
    """`projects.run_project` 的替身：只记下 kwargs，返回一份 cmd_project 读得动的形状。"""

    def _run_project(root, **kwargs):
        seen.update(kwargs)
        seen["_root"] = str(root)
        return {"project": {"name": "project1", "mode": "cold", "reason": "替身",
                            "path": str(Path(root) / "project1")},
                "run": {"out_dir": "", "notes": [], "ingest": {}, "extraction": {}},
                "result": None}

    return _run_project


# ============================================================ C1 试运行
def test_c1_dry_run_prints_everything_and_calls_no_model(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """C1：一次 `start --task … --project … --mode research --dry-run` 说清将要发生的一切。

    "不花钱、不写盘"要三条独立的证据：三个模型入口一个都没被调、目标项目文件夹没被建出来、
    `budget.json` 没被写。只断言输出里有一句"试运行"是不够的 —— 那句话与"真的没花"
    可以同时为假。
    """
    import agentflow.agent_loop as AL
    import agentflow.projects as PJ
    import agentflow.runflow as RF

    calls: list[str] = []

    def _refuse(where: str):
        def _inner(*_a, **_k):
            calls.append(where)
            raise AssertionError(f"试运行不许走到 {where}")
        return _inner

    monkeypatch.setattr(RF, "run_topic", _refuse("runflow.run_topic"))
    monkeypatch.setattr(PJ, "run_project", _refuse("projects.run_project"))
    monkeypatch.setattr(AL, "run_role", _refuse("agent_loop.run_role"))

    ws = tmp_path / "ws"
    code, out, err = _run(["start", "--task", "重建 Saxl 猜想论文的证明主线",
                           "--project", "p3-verify2", "--root", str(ws),
                           "--mode", "research", "--dry-run"])
    assert code == 0, (code, out, err)
    assert calls == [], calls
    for want in ("试运行", "工作区", "模型", "预算", "Lean", "会召唤"):
        assert want in out, f"预检里没有「{want}」这一格：\n{out}"
    assert not (ws / "projects" / "p3-verify2").exists(), "试运行把项目文件夹建出来了"
    assert not (ws / "budget.json").exists(), "试运行把预算寄存器写出来了"
    assert not ws.exists() or not list(ws.rglob("*")), f"试运行写了字节：{list(ws.rglob('*'))}"


def test_c1_the_dry_run_panel_renders_in_every_mode(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """C1：五档都能把那份预检打出来（不只是 `--json` 那一档）。

    为什么单开一条：`--json` 在渲染面板之前就 `return` 了，所以它证明不了面板本身能不能
    走通。实测漏过一次 `NameError` 就藏在"只有面板才走到"的那一行里 —— 而 `--json` 那条
    判据当时是绿的。
    """
    import agentflow.runflow as RF

    def _refuse(*_a, **_k):
        raise AssertionError("试运行不许调模型")

    monkeypatch.setattr(RF, "run_topic", _refuse)
    for argv in (["--mode", "topic"], ["--mode", "project"], ["--mode", "cold"],
                 ["--mode", "research"], ["--mode", "role", "--role", "M"]):
        code, out, err = _run(["start", "--task", "t", "--root", str(tmp_path / "ws"),
                               *argv, "--dry-run"])
        assert code == 0, (argv, code, out, err)
        for want in ("试运行", "工作区", "模型", "预算", "Lean", "会召唤"):
            assert want in out, (argv, want, out)


def test_c1_dry_run_json_carries_exactly_the_documented_keys(tmp_path: Path) -> None:
    """C1：`--json` 的键集合是写进 docstring 的那一份（多一个少一个都算口径漂了）。"""
    code, out, err = _run(["start", "--task", "t", "--project", "p1",
                           "--root", str(tmp_path / "ws"), "--mode", "project",
                           "--dry-run", "--json"])
    assert code == 0, (code, out, err)
    doc = json.loads(out)
    assert set(doc) == set(cli.START_PLAN_KEYS), (set(doc) ^ set(cli.START_PLAN_KEYS))


# ============================================================ C2 老命令 = 别名
def test_c2_the_four_old_entries_all_land_on_one_executor(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C2：`run` / `run-agent` / `project run` / `web` 都走进同一个执行体 `_run_spec`。

    为什么这一条与"旗标逐字不变"必须同时存在：只保旗标，四条路各写一遍照样能全绿，
    而"旗标只在这一层归一"就成了一句注释。
    """
    seen: list[str] = []
    monkeypatch.setattr(cli, "_run_spec",
                        lambda spec, args: (seen.append(spec.mode), 0)[1])
    for argv in (["run", "--topic", "t"],
                 ["run-agent", "M", "--task", "t"],
                 ["--root", str(tmp_path / "pj"), "project", "run", "--topic", "t"],
                 ["web"]):
        code, out, err = _run(argv)
        assert code == 0, (argv, code, out, err)
    assert seen == [cli.MODE_TOPIC, cli.MODE_ROLE, cli.MODE_PROJECT, cli.MODE_WEB], seen


def test_c2_the_old_flag_defaults_are_unchanged() -> None:
    """C2：四条老命令的旗标与缺省逐字不变（老脚本不许被这次升级改写）。"""
    parser = cli.build_parser()
    ns = parser.parse_args(["run", "--topic", "t"])
    assert ns.budget_usd == 1.0 and ns.max_calls == 3
    assert ns.out is None and ns.prompt_version == "v1"

    ns = parser.parse_args(["run-agent", "M", "--task", "t"])
    assert ns.rounds == 1 and ns.budget_usd is None and ns.max_steps == 30
    assert ns.resume is False and ns.json is False

    ns = parser.parse_args(["project", "run", "--topic", "t"])
    assert ns.budget_usd == 0.5 and ns.max_calls == 2 and ns.extract_rounds == 1

    ns = parser.parse_args(["web"])
    assert ns.port == 8788 and ns.allow_writes is False and ns.no_settings_write is False


def test_c2_the_mode_default_budgets_agree_with_the_old_parsers() -> None:
    """缺省额度只剩一张表（`MODE_DEFAULT_BUDGET`），三条老命令与 `start` 都照它。

    为什么要有这一条：`--budget-usd` 的缺省原本是三个写在不同 parser 上的字面量
    （1.0 / 0.5 / None）。归一之后那张表是唯一真身，但 parser 上的 default 仍然是字面量
    —— 两边一旦漂了，"同一个概念三个旗标"就换个形状回来了，而没有任何一处会红。
    """
    parser = cli.build_parser()
    assert parser.parse_args(["run", "--topic", "t"]).budget_usd == \
        cli.MODE_DEFAULT_BUDGET[cli.MODE_TOPIC]
    assert parser.parse_args(["project", "run"]).budget_usd == \
        cli.MODE_DEFAULT_BUDGET[cli.MODE_PROJECT]
    assert parser.parse_args(["run-agent", "M", "--task", "t"]).budget_usd == \
        cli.MODE_DEFAULT_BUDGET[cli.MODE_ROLE]
    for mode, argv in ((cli.MODE_TOPIC, ["--mode", "topic"]),
                       (cli.MODE_PROJECT, ["--mode", "project"]),
                       (cli.MODE_ROLE, ["--mode", "research"])):
        spec, problem = cli._spec_of_start(parser.parse_args(["start", *argv, "--task", "t"]))
        assert not problem, problem
        assert spec is not None and spec.budget_usd == cli.MODE_DEFAULT_BUDGET[mode], \
            (mode, spec)


# ============================================================ C3 缺参数 = 人话
def test_c3_a_missing_task_is_a_sentence_not_an_argparse_paragraph(tmp_path: Path) -> None:
    """C3：`start` 什么都不给时给"人话"，并点名该给哪个旗标。"""
    code, out, err = _run(["start", "--root", str(tmp_path / "ws")])
    text = out + err
    assert code == 2, (code, text)
    assert "--task" in text, text
    assert "the following arguments are required" not in text, text
    assert "Traceback" not in text, text


def test_c3_research_mode_does_not_ask_for_a_role(tmp_path: Path) -> None:
    """C3：`--mode research` 时角色缺省 M（F2 那条位置参数的坑不再有人踩）。"""
    code, out, err = _run(["start", "--task", "t", "--root", str(tmp_path / "ws"),
                           "--mode", "research", "--dry-run"])
    assert code == 0, (code, out, err)
    assert "M" in out, out


def test_c3_role_mode_without_a_role_names_the_flag(tmp_path: Path) -> None:
    """C3：`--mode role` 少 `--role` 时报的是"该给 --role"。"""
    code, out, err = _run(["start", "--task", "t", "--root", str(tmp_path / "ws"),
                           "--mode", "role", "--dry-run"])
    text = out + err
    assert code == 2, (code, text)
    assert "--role" in text, text
    assert "the following arguments are required" not in text, text


# ============================================================ C4 预算落盘
def test_c4_an_explicit_budget_is_written_to_the_register(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C4：传了 `--budget-usd 10` ⇒ 跑完 `budget.json.total_usd == 10`。"""
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    ws = tmp_path / "ws"
    code, out, err = _run(["start", "--mode", "topic", "--task", "t",
                           "--root", str(ws), "--budget-usd", "10",
                           "--out", str(tmp_path / "out")])
    assert code == 2, (code, out, err)  # 没 key ⇒ 研究启动失败，但预算那一格照样落盘
    reg = json.loads((ws / "budget.json").read_text(encoding="utf-8"))
    assert reg["total_usd"] == 10.0, reg


def test_c4_a_bigger_register_never_swallows_the_flag(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C4：寄存器里是 0.5 而命令行给 10 ⇒ 不许被静默压掉，且读数点名 0.5 → 10。

    改前的现场：`budget.json` 里留着 0.5，`--budget-usd 10` 被 `limit_usd` 的
    "寄存器优先"吃掉，于是用户以为给了 10、闸门照旧按 0.5 停 —— 而输出里一个字都没提。

    前置必须是"已经初始化过的工作区 + 一份旧寄存器"：`budget.json` 落在一个还不算
    工作区的文件夹里时，`Store.init()` 的外来条目守卫会先拒掉整个目录（那条守卫是
    另一件事，不该被这条判据顺手测到）。
    """
    from agentflow import budget as B
    from agentflow.store import Store

    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    ws = tmp_path / "ws"
    Store(ws).init()
    B.write_initial(ws, 0.5, by="old-run", note="上一趟留下的")

    code, out, err = _run(["start", "--mode", "topic", "--task", "t",
                           "--root", str(ws), "--budget-usd", "10",
                           "--out", str(tmp_path / "out")])
    assert code == 2, (code, out, err)
    reg = json.loads((ws / "budget.json").read_text(encoding="utf-8"))
    assert reg["total_usd"] == 10.0, reg
    assert B.limit_usd(ws) == 10.0, "闸门读到的上限必须就是命令行给的那一个"
    assert "0.5" in out and "10" in out and "→" in out, out
    assert len(reg["added"]) == 2, "追加史不许被覆盖式写入抹掉"


# ============================================================ C5 Lean 三档
def test_c5_lean_off_really_turns_it_off(tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """C5：`--lean off` 必须真的关（`bool("off")` 为真 ⇒ 改前它会打开检查器）。"""
    import agentflow.projects as PJ

    seen: dict = {}
    monkeypatch.setattr(cli, "_lean_first_screen", lambda root, stream=None: {})
    monkeypatch.setattr(PJ, "run_project", _fake_project_run(seen))
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")  # 前置：寄存器说"开着"

    code, out, err = _run(["--root", str(tmp_path / "ws"), "project", "run",
                           "--topic", "t", "--lean", "off"])
    assert code == 0, (code, out, err)
    assert seen.get("lean") is False, seen
    assert os.environ.get("AGENTFLOW_LEAN_ENABLED") == "1", \
        "跑完必须把注入过的环境变量还原（否则这一趟的开关漏到下一趟）"


def test_c5_lean_auto_keeps_running_and_names_why_formal_is_unknown(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C5：`--lean auto` + 自检 unusable ⇒ 照常跑，但形式化结论 unknown 且点名原因。"""
    import agentflow.leantoolchain as LT
    import agentflow.projects as PJ

    seen: dict = {}
    monkeypatch.setattr(PJ, "run_project", _fake_project_run(seen))
    monkeypatch.setattr(LT, "selfcheck", lambda **_k: {
        "checked": True, "state": "unusable", "ok": False,
        "problems": ["反控没失败：假命题 1 = 2 被接受"],
        "enabled": True, "enabled_source": "env", "source": "env",
        "lean_path": "fake-lean", "version": "4.7.0", "expected_version": "4.7.0",
        "version_ok": True, "sha256": "", "positive": {}, "negative": {},
    })
    LT.reset_reading_cache()

    code, out, err = _run(["--root", str(tmp_path / "ws"), "project", "run",
                           "--topic", "t", "--lean", "auto"])
    assert code == 0, (code, out, err)
    text = out + err
    assert "unknown" in text, text
    assert "反控没失败" in text, text
    assert seen.get("lean") is False, seen


def test_c5_lean_auto_turns_it_on_when_the_selfcheck_is_usable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C5 的反向：自检 usable ⇒ `--lean auto` 真的把它打开。

    没有这一条，`auto` 可以"永远关着"而 C5 的正控照样全绿 —— 那正是"关不掉的开关"
    换个方向回来的形态。
    """
    import agentflow.leantoolchain as LT
    import agentflow.projects as PJ

    seen: dict = {}
    monkeypatch.setattr(PJ, "run_project", _fake_project_run(seen))
    monkeypatch.setattr(LT, "selfcheck", lambda **_k: {
        "checked": True, "state": "usable", "ok": True, "problems": [],
        "enabled": True, "enabled_source": "env", "source": "env",
        "lean_path": "lean", "version": "4.7.0", "expected_version": "4.7.0",
        "version_ok": True, "sha256": "deadbeef", "positive": {}, "negative": {},
    })
    LT.reset_reading_cache()

    code, out, err = _run(["--root", str(tmp_path / "ws"), "project", "run",
                           "--topic", "t", "--lean", "auto"])
    assert code == 0, (code, out, err)
    assert seen.get("lean") is True, seen
    assert "unknown" not in (out + err), "自检 usable 时不该再说形式化结论记 unknown"


# ============================================================ C6 启动自检
def test_c6_a_syntax_error_is_reported_as_file_and_line(tmp_path: Path) -> None:
    """C6：包里一个语法错误报成"文件:行 + 错误"。先在人造包上证明扫描器接得上。"""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "good.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "broken.py").write_text("def f(:\n    return 1\n", encoding="utf-8")

    rep = cli.selfcheck_package(pkg)
    assert rep["checked"] is True, rep
    assert rep["files"] == 2, rep
    assert len(rep["problems"]) == 1, rep["problems"]
    got = rep["problems"][0]
    assert str(got["file"]).endswith("broken.py"), got
    assert got["line"] == 1, got
    text = cli.format_selfcheck(rep)
    assert "broken.py:1" in text, text
    assert "Traceback" not in text, text


def test_c6_the_entry_point_turns_a_broken_module_into_one_sentence(monkeypatch) -> None:
    """C6：`main()` 捕到 SyntaxError/ImportError ⇒ 一句"文件:行 + 错误"，退出码 2。"""

    def _boom(_args):
        raise SyntaxError("invalid syntax", ("src/agentflow/broken.py", 42, 7, "def f(:\n"))

    monkeypatch.setattr(cli, "cmd_status", _boom)
    code, out, err = _run(["status"])
    text = out + err
    assert code == 2, (code, text)
    assert "broken.py:42" in text, text
    assert "Traceback" not in text, text


def test_c6_doctor_selfcheck_scans_the_real_package() -> None:
    """C6：`doctor --selfcheck` 做显式全扫（真包上 0 个问题 ⇒ 退出码 0）。"""
    code, out, err = _run(["doctor", "--selfcheck"])
    assert code == 0, (code, out, err)
    assert "自检" in out, out
    assert "Traceback" not in (out + err), out + err


# ============================================================ C7 watch
def test_c7_watch_prints_a_reachable_url_on_the_same_workspace(tmp_path: Path) -> None:
    """C7：`start --watch` 打印的 URL 可访问，且与 `--project` 指向同一工作区。

    这一条必须起子进程：`--watch` 的语义就是"服务一直开着"，所以"URL 当时真的通"
    只能在一个活着的进程上量 —— 在同一个进程里起完再关掉，量到的就只是"能绑定"。
    """
    ws = tmp_path / "ws"
    project = ws / "projects" / "p1"
    (project / "data").mkdir(parents=True)
    (project / "data" / "counters.json").write_text("{}\n", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env.pop("AGENTFLOW_MODEL_API_KEY", None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "agentflow.cli", "start", "--watch",
         "--project", "p1", "--root", str(ws), "--port", "0", "--json"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", env=env,
    )
    try:
        line = proc.stdout.readline()
        assert line.strip(), "`start --watch` 没有打印 URL 那一行"
        doc = json.loads(line)
        assert set(("url", "root", "sid", "round")) <= set(doc), doc
        assert Path(doc["root"]).resolve() == project.resolve(), doc["root"]
        with urlopen(doc["url"], timeout=10) as resp:
            assert resp.status == 200, resp.status
            resp.read(64)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - 收尾兜底
            proc.kill()
            proc.wait(timeout=5)


# ============================================================ C8 分组 help
def test_c8_the_first_screen_is_grouped_and_lists_every_subcommand() -> None:
    """C8：help 首屏看得出研究 / 项目 / 诊断 / 运维四组，且一个子命令都没漏。"""
    code, out, err = _run(["--help"])
    assert code == 0, (code, out, err)
    for group in ("研究", "项目", "诊断", "运维"):
        assert group in out, f"help 首屏没有「{group}」这一组：\n{out}"

    parser = cli.build_parser()
    subs = [a for a in parser._actions if getattr(a, "choices", None)]
    assert len(subs) == 1, "必须保留唯一一个 subparsers action（三处判据靠它取 choices）"
    names = set(subs[0].choices)
    # 2026-10-23：26 -> 27（新增 `cache` 那一组：两档提示词缓存的状态与预热）。
    assert len(names) == 27, sorted(names)
    for name in names:
        assert name in out, f"help 里没有 {name}"

    listed = [name for _title, group in cli.SUBCOMMAND_GROUPS for name in group]
    assert set(listed) == names, set(listed) ^ names
    assert len(listed) == len(set(listed)), "分组表里有重复登记"


def test_c8_extract_rounds_is_not_printed_twice() -> None:
    """C8：`project --help` 里 `--extract-rounds` 仍只被印出那几次（回归钉）。

    改前实测是三次：usage 行、选项行、以及选项说明里那句"所以 7 本书要 --extract-rounds 7"。
    加上 `ArgumentDefaultsHelpFormatter` 那一类东西会让它变成四次（默认值再印一遍），
    而那个形态正是 `draft/145` 的 F7 记下的坑。
    """
    code, out, err = _run(["project", "--help"])
    assert code == 0, (code, out, err)
    assert out.count("--extract-rounds") == 3, out.count("--extract-rounds")
    assert cli.build_parser().parse_args(["project", "run"]).extract_rounds == 1
