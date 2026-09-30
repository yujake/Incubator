# -*- coding: utf-8 -*-
"""用户路径冒烟：README §0「先跑通」里那几条命令必须真的能跑，且读数与文档一致。

为什么单开一个文件：这一组判据问的不是"某个函数对不对"，而是第一次拿到这套东西的人
照文档敲下去会不会卡住。实测撞到过的形态包括：文档写 `--role` 而参数其实是位置参数、
`run-a` 在没有 provider 时静默什么都不做、`demo` 的非零退出码被当成"跑过了"。
每一条都只跑离线的那部分（要 key / 要网的路径在 §0 的"真活"那两条里，见
`agentflow/tests/test_cli_run.py` 与 `agentflow/tests/test_projects.py`）。
"""
from __future__ import annotations

import io
import json
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from agentflow import cli

#: 仓库根（`agentflow/`）：fixture 素材要从这里拷进临时工作区。
REPO = Path(__file__).resolve().parents[1]


def _run(argv: list[str]) -> tuple[int, str]:
    """在进程内跑一次 CLI，返回 `(退出码, stdout+stderr)`。

    进程内而不是起子进程：判据要的是"这条命令的退出码与输出"，而子进程会把它变成
    "解释器 + 参数拼接"的复合体（真机里 `--role` 那个坑就是这么被掩盖的）。

    两个细节都是踩过的：
    - argparse 的 `--help` 与用法错是靠 `SystemExit` 退出的 ⇒ 必须接住它，
      否则判据会以 pytest 的内部错误形式失败，而不是得到那条命令的退出码；
    - "没查成"那类说明是打到 stderr 的 ⇒ 两路都要收，否则"退出码 2 但一句话都没有"
      看起来也像通过。
    """
    buf, err = io.StringIO(), io.StringIO()
    code = 0
    with redirect_stdout(buf), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse: --help(0) / 用法错(2)
            code = int(exc.code or 0)
    return int(code or 0), buf.getvalue() + err.getvalue()


def test_help_lists_the_subcommands_the_readme_talks_about(tmp_path: Path):
    """`--help` 必须能跑，且 README 点名的那几个子命令都在里面。"""
    code, out = _run(["--help"])
    assert code == 0, out[-400:]
    for name in ("demo", "tools", "status", "verify", "project", "run-agent", "run-a"):
        assert name in out, f"--help 里没有 {name}"


def test_the_offline_demo_passes(tmp_path: Path):
    """README §0 的第二步：`demo` 自建素材并跑完整条链路，退出码 0 才是通过。

    `--root` 必须给，而且必须写在子命令之前。为什么：`cmd_demo` 会
    `rmtree(root / "demo" / "run")` 再重建，不给 `--root` 时它按 `DEFAULT_ROOT`
    落在仓库内 ⇒ "跑一次这条测试"就等于改写被跟踪的 `demo/run/data/*`，
    而别处"仓库冻结、sha256 前后不变"那类断言正是以这个仓库为前提的。
    （这条坑本项目已经用负控登记过，见 `tests/test_cli_console_encoding.py` 里
    `ENTRIES` 第三列 `needs_root` 的注释与 `temp/i1-neg-{before,after}.txt`；
    我写这条测试的第一版照样踩了它 —— 实测跑完 `demo/run/data/` 里 5 个文件的
    sha256 全变了，所以这里把 `--root` 钉住。）
    """
    root = str(tmp_path / "ws")
    code, out = _run(["--root", root, "demo"])
    assert code == 0, out[-1200:]
    assert "演示成功" in out, out[-400:]
    assert (tmp_path / "ws" / "demo").exists(), "demo 应当落在 --root 指定的目录里"


def test_status_and_tools_work_on_a_fresh_workspace(tmp_path: Path):
    """`init` → `status` → `tools --role H`：空工作区上的读数必须齐全、不报错。

    `tools --role H` 还钉住那条权限面：只读角色看不到写工具（README §0 说它是设计）。
    """
    root = str(tmp_path / "ws")
    assert _run(["--root", root, "init"])[0] == 0
    code, out = _run(["--root", root, "status"])
    assert code == 0, out[-400:]
    assert "literature" in out and "tasks" in out, out[-400:]
    code, out = _run(["--root", root, "tools", "--role", "H"])
    assert code == 0, out[-400:]
    assert "verify." in out, out[-400:]
    assert "fs.write" not in out and "table.create" not in out, "只读角色的面里出现了写工具"


def test_project_plan_says_what_it_would_do_without_writing(tmp_path: Path):
    """`project plan` 必须零写入：它是"先看看会怎么跑"的那条命令。"""
    projects = tmp_path / "projects"
    code, out = _run(["--root", str(tmp_path / "ws"), "project", "plan",
                      "--name", "probe", "--projects-dir", str(projects)])
    assert code == 0, out[-600:]
    assert "不写任何字节" in out, out[-400:]
    assert not projects.exists(), "plan 不该建任何东西"


def test_an_offline_a_run_registers_candidates_without_network(tmp_path: Path):
    """离线跑一轮 A（`--provider fixture`）：README §0 的"只想验证链路"那条路。

    判据：退出码 0、登记数 > 0、判重也真的发生了（fixture 里故意有重复候选）。
    这条同时证明"不给 provider 时不会静默用 fixture"的反面：fixture 必须显式指定。
    """
    root = tmp_path / "ws"
    assert _run(["--root", str(root), "init"])[0] == 0
    # fixture 素材要在 `init` 之后放：`init` 会拒绝往非空目录里建工作区
    # （那条守卫有事故背景，见它的报错文案）—— 顺序反过来会得到退出码 2，那是对的。
    (root / "demo" / "fixtures").mkdir(parents=True)
    shutil.copyfile(REPO / "demo" / "fixtures" / "candidates.json",
                    root / "demo" / "fixtures" / "candidates.json")
    assert _run(["--root", str(root), "submit", "--topic", "abelian group",
                 "--mode", "topical"])[0] == 0
    code, out = _run(["--root", str(root), "run-a", "--provider", "fixture"])
    assert code == 0, out[-800:]
    got = json.loads(out[out.index("{"):])
    assert got["registered"] > 0, got
    assert got["duplicated"] > 0, got
    assert got["queue_pending"] == 0, got


def test_run_agent_without_a_key_says_so_and_exits_2(tmp_path: Path, monkeypatch):
    """没 key 时 `run-agent` 必须退出码 2 + 一行人话（不是 traceback，也不是 0）。

    这是 README §0 那张对照表的第一行；它也是三态纪律在用户路径上的体现：
    "没查成"不许被读成"跑过了没问题"。
    """
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    code, out = _run(["--root", str(tmp_path / "ws"), "run-agent", "M",
                      "--task", "probe", "--max-steps", "1"])
    assert code == 2, (code, out[-400:])
    assert "没有接模型" in out, out[-400:]


def test_the_readme_subcommand_count_matches_the_live_parser():
    """README 里写的"21 个子命令"必须等于 `build_parser()` 当次给出的子命令数（`draft/36` T-4）。

    为什么值得一条判据：这是最容易漂的一类手抄数字（加一个子命令就变），
    而它此前没有任何判据 —— 只有"README 点名的几个子命令都在 `--help` 里"那一条
    （那只保证"没写错名字"，不保证"数字没错"）。老实说：这个数字今天是对的，
    加判据是为了让它以后也一直对。
    """
    import re

    from agentflow.cli import build_parser

    parser = build_parser()
    sub = next((a for a in parser._actions if getattr(a, "choices", None)), None)
    assert sub is not None, "夹具前提变了：`build_parser()` 里找不到子命令那个 action"
    live = len(sub.choices)

    text = (REPO / "README.md").read_text(encoding="utf-8")
    found = [int(n) for n in re.findall(r"(\d+)\s*个子命令", text)]
    assert found, "README 里没有『N 个子命令』这个读数了 —— 要么删干净、要么改这条判据"
    wrong = [n for n in found if n != live]
    assert not wrong, (
        f"README 写了 {wrong} 个子命令，`build_parser()` 当次给出 {live} 个"
        f"（README 里的读数：{found}）")


def test_the_readme_does_not_document_a_flag_that_does_not_exist():
    """反向判据（真机撞到过）：README 里那几条 `run-agent` 命令用到的开关，必须真的存在。

    `draft/35` 曾把角色写成 `--role`（其实是位置参数）—— 照它敲会得到
    `unrecognized arguments: --role`。判据只取以 `run-agent` 开头的那几行里的
    `--xxx`（不牵连别的子命令的开关：`§0` 里同一段还有 `project run --books` 之类）。
    """
    text = (REPO / "README.md").read_text(encoding="utf-8")
    start = text.index("## 0. 先跑通")
    text = text[start:text.index("## 1. 这是什么")]
    flags: set[str] = set()
    lines = [ln for ln in text.splitlines() if "run-agent" in ln]
    assert lines, "夹具前提：§0 里应当有 run-agent 的示例命令"
    for ln in lines:
        for token in ln.replace("`", " ").split():
            if token.startswith("--") and len(token) > 3:
                flags.add(token.strip("，。、）（:："))
    assert "--task" in flags, f"夹具前提：示例里应当有 --task（实际 {sorted(flags)}）"
    code, help_out = _run(["run-agent", "--help"])
    assert code == 0, help_out[-300:]
    for flag in sorted(flags):
        assert flag in help_out, f"README 的 run-agent 示例里写了 {flag}，但 `run-agent --help` 里没有它"
    # 位置参数那一课也钉住：README 的示例必须是 `run-agent M --task …` 形态
    assert any("run-agent M " in ln for ln in lines), lines


def test_drop_reasons_are_summarized_instead_of_repeated(tmp_path: Path):
    """剔除原因要聚合成一行：真跑实测 8 条原因全是同一个码，逐条打就是 8 行一样的字。

    这条判据钉两件事：① 同一个原因只出现一次、带计数；② `top` 之外的原因不许被丢掉
    （折算成"另有 N 类"）—— 一个会静默丢信息的摘要，比不摘要更坏。
    """
    assert cli._summarize_drop_reasons([]) == ""
    assert cli._summarize_drop_reasons(None) == ""
    assert cli._summarize_drop_reasons(["quote_not_found"] * 8) == "quote_not_found × 8"
    got = cli._summarize_drop_reasons(["b", "a", "b", "c", "d", "e"], top=2)
    assert got.startswith("b × 2、a × 1"), got
    assert "另有 3 类原因" in got, got
    # 空白原因不许变成空字符串段落（那会让"有原因"与"没原因"看起来一样）
    assert cli._summarize_drop_reasons(["  "]) == "(空原因) × 1"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
