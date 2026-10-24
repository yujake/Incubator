# -*- coding: utf-8 -*-
"""判据：四条"移植期工具"搬出 CLI 之后，行为逐字节不变（业主批的 CLI 更新方案 C）。

## 这一份守什么

这一轮把 `repair` / `rebuild` / `demo` / `evidence migrate` 的实现搬到了
`tools/legacy_cli/<名字>.py`，CLI 里只留一行转发。搬东西最容易出的事是"顺手改好了"：
实现搬着搬着就有人把一句话的措辞改了、把一个退出码换了一档，而没有任何一条判据会红
（输出变了，测试照样过 —— 因为老测试断言的是"含某几个字"，不是"逐字节相同"）。

所以这里的指纹是搬走之前在同一份夹具上实测的（sha256）。三件事一起比：
stdout、stderr、退出码。改任何一个字节这条判据就红。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① | 八种调用形态的 stdout / stderr / 退出码与搬走前逐字节相同 | 搬运时顺手"优化"了一句人话 |
| ② | 转发只有一层（函数体里只有一处 `_legacy_module(...).main(args)`） | 转发层里长出第二份逻辑（两份实现又回来了） |
| ③ | 实现真的在 `tools/legacy_cli/<名字>.py` 里，且 `cli.py` 里不再有那份实现 | 搬家只搬了个空壳，实现还留在 CLI |
| ④ | 装好的包（没有 `tools/`）跑这四条 ⇒ ImportError 里那句人话 | 用户拿到一个 import 栈 |

## 为什么用指纹而不是"断言输出含某句话"

"含某句话"对措辞改动是瞎的：把"已从事件日志重建"改成"重建完成"照样绿。
指纹对任何字节改动都红 —— 这是"逐字节相同"这句话唯一可执行的形态。
临时目录名会进输出（`demo` 会打印工作区路径），所以指纹前先把它抹成 `<base>`。
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import pathlib
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentflow import cli
from agentflow import schema as S
from agentflow.store import Store

#: 搬走之前实测的指纹：名字 → (退出码, stdout sha256, stderr sha256, stdout 行数)。
#:
#: 生成方式：在同一份夹具（`_fixture`）上跑一遍下面 `CASES` 里的命令，把
#: `out.replace(str(base), "<base>")` 之后取 sha256。这一份是"搬走前"的值，
#: 搬完之后重跑必须一模一样（本轮实测一致）。
FINGERPRINTS: dict[str, tuple[int, str, str, int]] = {
    "rebuild": (0, "58d7d9438c1ea7078abe1b9e79110478ba05bceecad70308040d3fb8a099a793",
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 4),
    "rebuild-no-backup": (
        0, "58d7d9438c1ea7078abe1b9e79110478ba05bceecad70308040d3fb8a099a793",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 4),
    "repair-guard": (
        2, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "fa3355847b24ca61e9c7be2affaebbdac7f506df653ee2ecf7f63f00f1463d88", 0),
    "repair-related": (
        2, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "39ca649882cb454a0d57a99ead5e8a391748eda8701124f93470459519ea8d1a", 0),
    "demo": (0, "34239575be8aa2841acb67445cb95a0d8f937102ae1cbdb3935e11a1f8fcc8e5",
             "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 62),
    "evidence-migrate-dry": (
        0, "8d48c2ef14c101ca74e4d029d02582c50b3229ae10b0ccf7e9b118a662bbf9d6",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 1),
    "evidence-migrate-apply": (
        0, "8d48c2ef14c101ca74e4d029d02582c50b3229ae10b0ccf7e9b118a662bbf9d6",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 1),
    "evidence-store": (
        0, "20f75eb1668340694dfe5242fd2d1d53432e9f2ed94806fb638350605e8eef52",
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", 1),
}

#: 这条判据管的那四个"移植期工具"（名字 = `tools/legacy_cli/<名字>.py` 的文件名）。
LEGACY_TOOLS: tuple[str, ...] = ("rebuild", "repair", "demo", "evidence_migrate")


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue(), err.getvalue()


def _fixture(base: pathlib.Path) -> pathlib.Path:
    """固定夹具工作区：一张表 + 一条事件 + 一个带内联正文的历史产物。"""
    ws = base / "ws"
    Store(ws).init()
    tasks = [{"task_id": "t-000001", "role": "B", "action": "ingest", "called_by": "M",
              "parent_task_id": None, "depth": 1, "input_key": "@t-000001",
              "status": "done", "outcome": "ok", "refusal_reason": None, "instance": "",
              "detail": "", "error": None, "started_at": "2026-10-24T00:00:00+08:00",
              "ended_at": "2026-10-24T00:00:01+08:00", "tokens": 0, "usd": 0.0,
              "artifacts": [], "inputs": [], "kind": "", "expects": "",
              "item_state": "", "item_close": "", "seen_by": "", "seen_step": None,
              "keep_alive": False}]
    (ws / "data" / "tasks.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": tasks}, ensure_ascii=False),
        encoding="utf-8")
    with (ws / "data" / "events.jsonl").open("w", encoding="utf-8") as fh:
        for i, row in enumerate(tasks, 1):
            fh.write(json.dumps({"seq": i, "ts": "2026-10-24T00:00:00+08:00",
                                 "op": "upsert", "table": "tasks", "row": row,
                                 "actor": "conductor"}, ensure_ascii=False) + "\n")
    project = base / "proj"
    (project / "out" / "run-1").mkdir(parents=True)
    (project / "out" / "run-1" / "evidence.json").write_text(
        json.dumps({"sources": [{"source_id": "s1", "fulltext": {"text": "内联正文"}}]},
                   ensure_ascii=False), encoding="utf-8")
    return ws


def _cases(base: pathlib.Path, ws: pathlib.Path) -> list[tuple[str, list[str]]]:
    project = str(base / "proj")
    return [
        ("rebuild", ["--root", str(ws), "rebuild"]),
        ("rebuild-no-backup", ["--root", str(ws), "rebuild", "--no-backup"]),
        ("repair-guard", ["--root", str(ws), "repair"]),
        ("repair-related", ["--root", str(ws), "repair", "--related"]),
        ("demo", ["--root", str(base / "demo-ws"), "demo"]),
        ("evidence-migrate-dry", ["evidence", "migrate", project]),
        ("evidence-migrate-apply", ["evidence", "migrate", project, "--apply"]),
        ("evidence-store", ["evidence", "store", project]),
    ]


def _digest(text: str, base: pathlib.Path) -> str:
    """一条输出的指纹（先抹掉临时目录名与路径分隔符，再抹掉 import 期的横幅）。

    为什么必须抹掉 `[capabilities]` 那几行：`agentflow.capabilities` 在第一次 import
    时往 stderr 打一份参数对账横幅，而那条 import 可能发生在本次捕获里（进程里第一个
    `build_parser()`），也可能早就发生过了（同一个 pytest 进程里别的判据先 import 过）。
    那是进程生命周期的读数，不是这条命令的输出 —— 留在指纹里会让这条判据"单独跑绿、
    整个套件一起跑红"，而那种红与"搬运动了输出"无关。
    """
    lines = [line for line in text.splitlines(keepends=True)
             if not line.startswith("[capabilities]")]
    norm = "".join(lines).replace(str(base), "<base>").replace("\\", "/")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- ① 逐字节相同


def test_the_four_legacy_tools_are_byte_identical_to_their_pre_move_output(
        tmp_path: pathlib.Path) -> None:
    """① 八种调用形态的 stdout / stderr / 退出码与搬走前逐字节相同。"""
    ws = _fixture(tmp_path)
    seen = 0
    for name, argv in _cases(tmp_path, ws):
        code, out, err = _run(argv)
        want_code, want_out, want_err, want_lines = FINGERPRINTS[name]
        assert code == want_code, (name, code, want_code, out[-300:], err[-300:])
        assert _digest(out, tmp_path) == want_out, (
            f"{name} 的 stdout 变了（搬走前 {want_out[:12]}…）：\n{out[:800]}")
        assert _digest(err, tmp_path) == want_err, (
            f"{name} 的 stderr 变了（搬走前 {want_err[:12]}…）：\n{err[:800]}")
        assert len(out.replace(str(tmp_path), "<base>").replace("\\", "/").splitlines()) \
            == want_lines, name
        seen += 1
    # 反真空：八种形态都真的跑过了（少跑一种这条判据就少守一格）
    assert seen == len(FINGERPRINTS) == 8, (seen, len(FINGERPRINTS))


# ---------------------------------------------------------------- ② 转发只有一层


def _returns(func: ast.FunctionDef) -> list[ast.Return]:
    return [n for n in ast.walk(func) if isinstance(n, ast.Return)]


def test_each_forward_is_exactly_one_layer() -> None:
    """② 每个 `cmd_*` 的函数体只有一处 return，且那一处就是 `_legacy_module(..).main(args)`。

    "薄转发只有一层"的可执行形态：函数体里不许有第二份逻辑（if/for/try 一个都不许），
    返回值必须来自 `_legacy_module("<名字>").main(args)`。
    """
    tree = ast.parse((pathlib.Path(__file__).resolve().parents[1]
                      / "src" / "agentflow" / "cli.py").read_text(encoding="utf-8"))
    forwards = {"cmd_rebuild": "rebuild", "cmd_repair": "repair", "cmd_demo": "demo",
                "_evidence_migrate": "evidence_migrate"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in forwards:
            continue
        found.add(node.name)
        body = [n for n in node.body if not isinstance(n, ast.Expr)
                or not isinstance(getattr(n, "value", None), ast.Constant)]
        assert len(body) == 1, (node.name, [type(n).__name__ for n in node.body])
        returns = _returns(node)
        assert len(returns) == 1, (node.name, len(returns))
        text = ast.unparse(returns[0].value)
        assert text == f'_legacy_module({forwards[node.name]!r}).main(args)', (node.name, text)
        # 没有第二个语句、也没有别的地方偷偷干这件事
        assert not [n for n in ast.walk(node) if isinstance(n, (ast.If, ast.For, ast.While,
                                                                ast.Try, ast.With))], node.name
    assert found == set(forwards), sorted(found)


# ---------------------------------------------------------------- ③ 实现真的搬走了


def test_the_implementation_really_lives_in_tools_legacy_cli() -> None:
    """③ 实现真的在 `tools/legacy_cli/<名字>.py` 里，且 CLI 里不再有那份实现。"""
    root = pathlib.Path(__file__).resolve().parents[1]
    for name in LEGACY_TOOLS:
        path = root / "tools" / "legacy_cli" / f"{name}.py"
        assert path.is_file(), f"没有这个文件：{path}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        assert "main" in funcs, (name, funcs)
    cli_text = (root / "src" / "agentflow" / "cli.py").read_text(encoding="utf-8")
    for marker in ('st.rebuild(backup=', 'tty.bullet("没有需要迁移的产物',
                   'related_concepts 重算了', 'run_demo('):
        assert marker not in cli_text, f"实现还留在 cli.py 里：{marker!r}"


# ---------------------------------------------------------------- ④ 装好的包里那句人话


def test_a_missing_tools_directory_says_something_a_human_can_act_on(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 没有 `tools/`（装好的包）⇒ ImportError 里那句人话，而不是一个 import 栈。"""
    monkeypatch.setattr(cli, "_LEGACY_TOOLS_DIR", "legacy_cli_not_here")
    with pytest.raises(ImportError) as exc:
        cli._legacy_module("rebuild")
    assert "移植期工具不在盘上" in str(exc.value), str(exc.value)
    assert "只能在源码仓库里跑" in str(exc.value), str(exc.value)


def test_the_loader_caches_the_module() -> None:
    """加载器把模块缓存进 `sys.modules`（连跑两次不重新执行模块体）。"""
    first = cli._legacy_module("rebuild")
    second = cli._legacy_module("rebuild")
    assert first is second
    assert first.__name__ == "_agentflow_legacy_cli_rebuild"
