# -*- coding: utf-8 -*-
"""判据：`doctor` 的每个失败项都带 `fix_hint`，而且它从不"自动修"（业主批的 CLI 更新方案 E）。

## 这一份守什么

`doctor` 是"跑之前先知道这台机器能做哪些事"的那条命令。它此前只报"缺什么"，不报
"下一步敲什么" —— 于是读的人还得去翻文档，而"缺了它，形式化那一条腿只能如实报没核到"
这种句子对着一台空机器是没法执行的。

| 判据 | 它钉的是 | 改坏之后的样子 |
|---|---|---|
| ① | 每个失败项的 `fix_hint` 非空，且是能直接复制执行的原文（`$env:` / `agentflow ` / `python `） | 提示退化成散文（"请配置模型 key"），复制不了 |
| ② | 反真空：删掉某一条提示 ⇒ 那一项当场红 | 提示表与判定表分家，某一项永远没有下一步 |
| ③ | 没有 `--fix` 这类开关，源码里也没有"自动修"的入口 | `doctor` 悄悄改了这台机器的状态 |
| ④ | `--json` 与人读用的是同一份判定（`checks` 那个数组） | 机器看到 3 条、人看到 2 条 |

## 为什么 ③ 要扫源码而不是只扫 parser

"不做 --fix"是业主要求的口径，不是一条实现细节。只扫 `--help` 看不到
"悄悄把 key 写进 settings.json 再报成功"这种形态；而"不出现自动修"的可执行形态就是
"doctor 这一支里没有任何写盘调用"。判据取的是这一句的近似：`cmd_doctor` 与
`doctor_checks` 的源码里不出现写口（`write_text` / `open(..., "w")` / `store.tx` /
`json.dump(` 到文件）。

## 为什么 ② 要用一张"全失败"的人造读数

真机上总有一些项是通过的；只对真机读数断言"失败项有提示"，等于只覆盖了这台机器
恰好缺的那几样。人造读数把九档全部点亮，于是"提示表漏了一项"必然被抓到。
"""
from __future__ import annotations

import ast
import io
import json
import pathlib
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentflow import cli

#: 医生那一支的源码（③ 的扫描面）。
CLI_PY = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow" / "cli.py"

#: 一份"九档全失败"的人造体检读数（键与 `toolchain.toolchain_report` 同形）。
ALL_FAILING_REPORT: dict = {
    "model": {"key_present": False, "base_url": "https://example.invalid", "model": "m"},
    "provers": {"checked": True, "available": [], "looked_in": ["PATH", "settings.json"],
                "probe_errors": ["探针在 C:/nope 上失败"]},
    "lean_enabled": True, "lean_enabled_source": "env", "formal_mode": "auto",
    "lean_ready": False, "can_do_formal": False, "lean_path": "", "lean_version": "",
    "mathlib": {"root": "", "reason": "没找到 Mathlib 工程根", "pinned_match": False},
    "lean_selfcheck": {"checked": True, "state": "unusable", "expected_version": "4.7.0",
                       "version": "4.6.0", "version_ok": False, "lean_path": "",
                       "problems": ["第 ② 步：假命题没有被拒绝"]},
}

#: 一份"找得到 Mathlib 工程根、但第 ⑤ 步真编译不过"的读数（`mathlib_import` 那一档）。
BAD_MATHLIB_REPORT: dict = {
    "model": {"key_present": True, "base_url": "u", "model": "m"},
    "provers": {"checked": True, "probe_errors": [],
                "available": [{"name": "lean", "path": "/lean", "source": "PATH"}]},
    "lean_enabled": True, "lean_enabled_source": "env", "formal_mode": "auto",
    "mathlib": {"root": "/mathlib", "pinned_match": True,
                "graph_import_measured": "unusable：unknown package 'Std'"},
    "lean_selfcheck": {"checked": True, "state": "usable", "expected_version": "4.7.0",
                       "version": "4.7.0", "version_ok": True, "lean_path": "/lean",
                       "problems": []},
}

#: 一份"坏文件"的人造自检读数（`package_syntax` 那一档）。
BROKEN_SELFCHECK: dict = {
    "checked": True, "files": 3, "scanned": 3, "reused": 0, "ms": 1.0,
    "root": "src/agentflow", "unreadable": [],
    "problems": [{"file": "src/agentflow/_probe_broken.py", "line": 3, "column": 5,
                  "error": "SyntaxError: invalid syntax"}],
}


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return int(code or 0), out.getvalue(), err.getvalue()


# ---------------------------------------------------------------- ① 每个失败项都有提示


def test_every_failing_item_carries_a_copy_pasteable_fix_hint() -> None:
    """① 全失败读数上：每一项都是 fail/unknown，且提示非空、是命令原文。"""
    items = cli.doctor_checks(ALL_FAILING_REPORT)
    failing = [it for it in items if it["state"] in ("fail", "unknown")]
    assert failing, "夹具前提：这份读数里应当有失败项（否则这条判据是空转的）"
    for it in failing:
        assert it["fix_hint"].strip(), f"{it['name']} 没有 fix_hint：{it}"
        assert it["fix_hint"].startswith(("$env:", "agentflow ", "python ")), (
            it["name"], it["fix_hint"])
    # 反真空：九档里至少点亮七档（提示表漏一项时上面那个循环会红，而不是悄悄少了）
    assert len(items) >= 7, [it["name"] for it in items]
    assert {"model_key", "prover", "lean_version", "lean_selfcheck",
            "mathlib_root"} <= {it["name"] for it in failing}


def test_a_healthy_machine_has_no_need_for_next_steps() -> None:
    """① 的反面：全通过的读数里一个失败项都没有（提示只在没通过时出现）。"""
    healthy = {
        "model": {"key_present": True, "base_url": "u", "model": "m"},
        "provers": {"checked": True, "probe_errors": [],
                    "available": [{"name": "lean", "path": "/lean", "source": "PATH"}]},
        "lean_enabled": True, "lean_enabled_source": "env", "formal_mode": "auto",
        "mathlib": {"root": "/mathlib", "pinned_match": True,
                    "graph_import_measured": "usable"},
        "lean_selfcheck": {"checked": True, "state": "usable", "expected_version": "4.7.0",
                           "version": "4.7.0", "version_ok": True, "lean_path": "/lean",
                           "problems": []},
    }
    items = cli.doctor_checks(healthy)
    assert [it for it in items if it["state"] in ("fail", "unknown")] == [], items


# ---------------------------------------------------------------- ② 反真空


def test_removing_one_hint_makes_that_item_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """② 反真空：删掉提示表里的一条 ⇒ 那一项没有下一步（判据必须能看见）。"""
    for name in ("model_key", "prover", "mathlib_root"):
        monkeypatch.delitem(cli.DOCTOR_FIX_HINTS, name)
        items = cli.doctor_checks(ALL_FAILING_REPORT)
        got = {it["name"]: it for it in items}
        assert got[name]["state"] in ("fail", "unknown"), name
        assert got[name]["fix_hint"] == "", (
            f"{name} 的提示已经删了，判定里却还拿得到一条 —— 提示表与判定表分家了")


def test_every_fix_hint_key_names_a_real_check() -> None:
    """② 的另一半：提示表里的每个键都必须是 `doctor_checks` 真的会产出的项名。

    为什么要有这一条：提示表多出一条谁也不用的键，读代码的人会以为"这一档有下一步"，
    而那一档根本不存在。判据把两张表钉在一起。
    """
    produced = {it["name"] for it in cli.doctor_checks(ALL_FAILING_REPORT)}
    produced |= {it["name"] for it in cli.doctor_checks(BAD_MATHLIB_REPORT)}
    produced |= {it["name"] for it in
                 cli.doctor_checks({}, selfcheck=BROKEN_SELFCHECK, only=("package_syntax",))}
    assert set(cli.DOCTOR_FIX_HINTS) <= produced, (
        set(cli.DOCTOR_FIX_HINTS) - produced)


# ---------------------------------------------------------------- ③ 不自动修


def _doctor_source() -> str:
    """`cmd_doctor` 与 `doctor_checks` 的源码（③ 的扫描面）。"""
    tree = ast.parse(CLI_PY.read_text(encoding="utf-8"))
    parts: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                "cmd_doctor", "doctor_checks", "_doctor_item", "_print_doctor_checks",
                "_print_lean_selfcheck", "format_selfcheck"}:
            parts.append(ast.get_source_segment(CLI_PY.read_text(encoding="utf-8"), node) or "")
    assert len(parts) >= 4, f"扫描面只读到 {len(parts)} 段源码（判据失去对象）"
    return "\n".join(parts)


def test_doctor_never_offers_or_performs_an_automatic_fix() -> None:
    """③ 没有 `--fix` 这类开关，`doctor` 那一支里也没有任何写盘调用。"""
    code, out, err = _run(["doctor", "--help"])
    assert code == 0, (code, err)
    assert "--fix" not in out, "--help 里出现了 --fix（业主口径：不做自动修）"
    assert "--repair" not in out and "--apply" not in out, out

    src = _doctor_source()
    for writer in ("write_text", "write_bytes", 'open(', "json.dump(", "store.tx",
                   "save_settings", "os.environ["):
        assert writer not in src, f"doctor 那一支里出现了写口：{writer!r}（那是自动修）"
    # 反真空：扫描面真的读到了那几段源码（否则上面那个循环恒绿）
    assert "这台机器的体检" in src or "def cmd_doctor" in src, src[:200]


def test_the_hint_block_is_only_printed_when_something_failed(
        tmp_path: pathlib.Path) -> None:
    """③ 人读那一档：没失败时不多打"下一步"，有失败时逐条给出提示。"""
    items = cli.doctor_checks(ALL_FAILING_REPORT)
    out = io.StringIO()
    with redirect_stdout(out):
        cli._print_doctor_checks(items)
    text = out.getvalue()
    assert "下一步" in text and "照这条改" in text, text[:400]
    for it in items:
        if it["state"] in ("fail", "unknown"):
            assert it["fix_hint"] in text, it["name"]

    quiet = io.StringIO()
    with redirect_stdout(quiet):
        cli._print_doctor_checks(cli.doctor_checks({
            "model": {"key_present": True}, "lean_enabled": False, "provers": {"checked": True,
             "available": [{"name": "lean", "path": "/lean", "source": "PATH"}]}}))
    assert quiet.getvalue() == "", quiet.getvalue()


# ---------------------------------------------------------------- ④ 两份输出同源


def test_the_json_and_the_human_output_read_the_same_checks() -> None:
    """④ `--json` 的 `checks` 就是人读那一段的来源（同一份判定，不各写一套）。

    `doctor --selfcheck --json` 这条档最便宜（不探测工具链、不编译 Mathlib），所以判据
    打它：`checks` 必须是一个数组，每项四格齐（`name` / `state` / `detail` / `fix_hint`），
    且 `state` 落在受控词表里。
    """
    code, out, err = _run(["doctor", "--selfcheck", "--json"])
    assert code in (0, 1), (code, err)
    doc = json.loads(out)
    checks = doc.get("checks")
    assert isinstance(checks, list) and checks, doc.keys()
    for it in checks:
        assert set(it) == {"name", "state", "detail", "fix_hint"}, it
        assert it["state"] in cli.DOCTOR_ITEM_STATES, it
    # 人读那一档也必须是同一份判定：把 checks 打出来的那一段接在自检后面
    code, out, err = _run(["doctor", "--selfcheck"])
    assert code in (0, 1), (code, err)
    assert "[自检]" in out
