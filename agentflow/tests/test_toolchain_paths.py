# -*- coding: utf-8 -*-
"""工具链的"在哪"这件事的判据：显式配置 → `AGENTFLOW_PROVER_PATH` → PATH（三档 + 三态）。

## 这一组守什么

2026-10-03 的现场：Lean 4.7.0 就装在机器上（仓库临时区里），而 `detect_verifier()`
报 `available=[]` —— 因为探测只认 PATH。后果不是"报错"，而是「静默降级」：
形式化那一条腿改成 cross_check，报告里只剩一句"没核到"，没有任何地方会说
"这台机器其实能做"。用户对这一条的原话是"这是坏的"。

所以这一组判据守三件事：

1. 「显式配置真的能把它找出来」（文件 / 目录 / 通用目录三档各一条），
   并且如实记下"是从哪一档找到的"（`source`）；
2. 「配了但找不到 ⇒ 算配置问题，不算"环境里没有"」（fail-closed）——
   把配置错读成"没有检查器"正是上面那个静默降级；
3. 「探测与调用不再各说各话」：同一个环境下，`detect_verifier()` 说"有 lean"
   ⟺ `formalgw.find_lean()` 给得出路径（这一条是"一处定义"的判据）。

## 用的是桩，不依赖本机装了什么

判据自己在 `tmp_path` 里造一个"检查器"（Windows 上是 `.bat`，其它平台是一个
可执行的 shell 脚本），然后「只在环境变量里」指给它 —— 于是这一组在任何机器上
都可复跑，也不会因为"这台机器恰好有 Lean"而变成真空。

「只断言"找得到"，不断言"检查通过"」：让一个桩自称 `verified` 就等于制造假证据，
那正是 FC-27 的 `verify_tools.py` 要防的事（"桥接层说谎 ⇒ proof 级证据是假的"）。
"""
from __future__ import annotations

import os
import pathlib
import stat

import pytest

from agentflow import cli
from agentflow import formalgw as FG
from agentflow import toolchain as TC
from agentflow.tools import verify_tools as VT

VERSION_LINE = "Lean (version 4.7.0, x86_64-w64-windows-gnu, commit 6fce8f7d5cd1, Release)"


def _stub(dirpath: pathlib.Path, name: str = "lean") -> pathlib.Path:
    """造一个"检查器"桩：报版本、退出码 0。返回可执行文件的路径。"""
    dirpath.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        p = dirpath / f"{name}.bat"
        p.write_text(f"@echo {VERSION_LINE}\r\n", encoding="utf-8")
    else:
        p = dirpath / name
        p.write_text(f"#!/bin/sh\necho '{VERSION_LINE}'\n", encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例都从"什么都没配"开始（不要让这台机器的真实配置渗进来）。"""
    for var in (TC.ENV_LEAN_BIN, TC.ENV_COQ_BIN, TC.ENV_ISABELLE_BIN,
                TC.ENV_PROVER_PATH, "AGENTFLOW_MATHLIB_ROOT"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------- 一、三档查找

def test_explicit_bin_pointing_at_the_executable_is_found(tmp_path: pathlib.Path,
                                                          monkeypatch):
    """正控（第一档）：`AGENTFLOW_LEAN_BIN` 指到「可执行文件」 ⇒ 找得到，且记下 source。"""
    exe = _stub(tmp_path / "leanbin")
    monkeypatch.setenv(TC.ENV_LEAN_BIN, str(exe))
    got = TC.resolve_checker("lean")
    assert got["path"] == str(exe) and got["source"] == "explicit", got
    probe = VT.detect_verifier()
    assert probe["checked"] is True and "lean" in probe["available_names"], probe
    assert probe["sources"]["lean"] == "explicit", probe


def test_explicit_bin_pointing_at_the_directory_is_found(tmp_path: pathlib.Path,
                                                         monkeypatch):
    """正控（第一档的另一种写法）：指到「目录」也认 —— "指向安装目录"是人最自然的写法。"""
    exe = _stub(tmp_path / "leanhome" / "bin")
    monkeypatch.setenv(TC.ENV_LEAN_BIN, str(exe.parent))
    got = TC.resolve_checker("lean")
    # 名字按大小写不敏感比：Windows 上 `shutil.which` 会把扩展名回成大写（`lean.BAT`）
    assert pathlib.Path(got["path"]).name.lower() == exe.name.lower(), got
    assert got["source"] == "explicit_dir", got
    assert "lean" in VT.detect_verifier()["available_names"]


def test_prover_path_directory_is_found(tmp_path: pathlib.Path, monkeypatch):
    """正控（第二档）：通用的一档 `AGENTFLOW_PROVER_PATH` 认目录列表。"""
    exe = _stub(tmp_path / "generic" / "bin")
    monkeypatch.setenv(TC.ENV_PROVER_PATH, str(exe.parent))
    got = TC.resolve_checker("lean")
    assert got["source"] == "prover_path" and got["path"], got


def test_a_stub_outside_path_is_invisible_without_configuration(tmp_path: pathlib.Path):
    """负控（反真空）：不配置时，一个「不在 PATH 上」的检查器是看不见的。

    没有这一条，"配置能让它可见"就不构成判据 —— 那可能只是碰巧找得到。
    """
    exe = _stub(tmp_path / "unconfigured" / "bin")
    assert TC.resolve_checker("lean")["path"] == "", "没配置却找到了不在 PATH 上的桩"
    assert str(exe.parent) not in (os.environ.get("PATH") or "")


# ---------------------------------------------------------------- 二、fail-closed

def test_a_broken_configuration_is_a_problem_not_an_absence(tmp_path: pathlib.Path,
                                                            monkeypatch):
    """负控（fail-closed）：配了一个「不存在」的路径 ⇒ 记成配置问题，`checked=False`。

    为什么这条重要：把"配置错"读成"环境里没有检查器"，正是那个静默降级
    （形式化悄悄退成 cross_check，而报告里只剩"没核到"）。
    """
    missing = tmp_path / "nope" / "lean.exe"
    monkeypatch.setenv(TC.ENV_LEAN_BIN, str(missing))
    probe = VT.detect_verifier()
    assert probe["checked"] is False, probe
    assert any("不存在" in p for p in probe["probe_errors"]), probe
    assert "lean" not in probe["available_names"], "配错了路径却报成'有检查器'"
    assert "没做成" in probe["reason"], probe["reason"]


def test_the_reason_says_where_it_looked(tmp_path: pathlib.Path):
    """正控（覆盖面要写出来）："环境里没有 X"只在覆盖面内成立，所以 reason 必须写清查过哪里。"""
    probe = VT.detect_verifier()
    assert "找过" in probe["reason"] or probe["available"], probe["reason"]
    assert probe["looked_in"] and all(":" in one for one in probe["looked_in"]), probe["looked_in"]


# ---------------------------------------------------------------- 三、一处定义

def test_probe_and_invocation_agree_under_the_same_environment(tmp_path: pathlib.Path,
                                                               monkeypatch):
    """正控（"一处定义"的判据）：探测说"有 lean" ⟺ 调用给得出路径。

    修之前这两件事是「两处独立」的 `shutil.which`：探测说没有、调用却能跑是可能的。
    """
    exe = _stub(tmp_path / "sameenv")
    monkeypatch.setenv(TC.ENV_LEAN_BIN, str(exe))
    assert "lean" in VT.detect_verifier()["available_names"]
    assert FG.find_lean() == str(exe), "探测说找得到，调用却给了别的答案"

    monkeypatch.delenv(TC.ENV_LEAN_BIN)
    still = "lean" in VT.detect_verifier()["available_names"]
    assert (FG.find_lean() != "") is still, (
        "探测与调用在同一个环境下不一致（这正是 '各看一遍 PATH' 的旧形态）")


# ---------------------------------------------------------------- 四、Mathlib 与 doctor

def test_mathlib_state_reads_the_root_and_says_whether_import_works(tmp_path: pathlib.Path,
                                                                   monkeypatch):
    """正控 + 负控（Mathlib 那一轴）：根在但 umbrella 的 `.olean` 不在 ⇒ 如实说"不可用"。"""
    root = tmp_path / "mathlib4"
    root.mkdir()
    (root / "lakefile.lean").write_text("-- lakefile\n", encoding="utf-8")
    (root / "lean-toolchain").write_text("leanprover/lean4:v4.7.0\n", encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_MATHLIB_ROOT", str(root))
    st = TC.mathlib_state()
    assert st["root"] == str(root), st
    assert "不可用" in st["import_mathlib"], st          # umbrella 的 .olean 还没编
    (root / ".lake" / "build" / "lib" / "lean").mkdir(parents=True)
    (root / ".lake" / "build" / "lib" / "lean" / "Mathlib.olean").write_bytes(b"x")
    ok = TC.mathlib_state()
    assert "可用" in ok["import_mathlib"], ok
    assert ok["umbrella_olean"].endswith("lean\\Mathlib.olean") or \
        ok["umbrella_olean"].endswith("lean/Mathlib.olean"), ok
    # 2026-10-04 的布局修正（`draft/37` §101）：4.7.0 的 umbrella 在 `.lake/build/lib/`
    # 而不是 `.lake/build/lib/lean/` —— 盘上那份编译完整的 Mathlib 正是这种布局，
    # 早先只认后者 ⇒ 把"装了"读成"没装"，把模型引向"换 import 列表"而不是"配 LEAN_PATH"。
    (root / ".lake" / "build" / "lib" / "lean" / "Mathlib.olean").unlink()
    (root / ".lake" / "build" / "lib" / "Mathlib.olean").write_bytes(b"x")
    legacy = TC.mathlib_state()
    assert "可用" in legacy["import_mathlib"], legacy
    assert legacy["lean_path_segments"] >= 1, legacy
    monkeypatch.delenv("AGENTFLOW_MATHLIB_ROOT")
    assert TC.mathlib_state()["root"] == TC.mathlib_state().get("root", ""), "没配就报没配"


def test_doctor_exit_codes_are_three_state(monkeypatch, capsys):
    """正控（三态退出码）：齐 ⇒ 0；查过了有缺 ⇒ 1；没查成（checked=False）⇒ 2。

    另外钉一条：「key 的值绝不出现在输出里」（它只出现在"配没配"这一格）。
    """
    class Args:
        json = False

    def fake_report(*, model=True, lean=True, checked=True):
        return {
            "model": {"key_present": model, "base_url": "（缺省）", "model": "（缺省）"},
            "provers": {"checked": checked, "available": (
                [{"name": "lean", "path": "X:\\lean.exe", "version": VERSION_LINE,
                  "source": "explicit"}] if lean else []),
                "available_names": ["lean"] if lean else [], "probe_errors":
                [] if checked else ["lean：AGENTFLOW_LEAN_BIN=… 不存在"],
                "looked_in": ["lean: AGENTFLOW_LEAN_BIN、AGENTFLOW_PROVER_PATH、PATH"],
                "reason": "（判据桩）"},
            "lean_ready": lean, "lean_path": "X:\\lean.exe" if lean else "",
            "lean_version": VERSION_LINE if lean else "",
            "mathlib": {"root": "", "reason": "没找到 Mathlib 工程根"},
            "can_do_formal": lean,
        }

    monkeypatch.setattr(TC, "toolchain_report", lambda *a, **k: fake_report())
    assert cli.cmd_doctor(Args()) == 0
    capsys.readouterr()
    monkeypatch.setattr(TC, "toolchain_report", lambda *a, **k: fake_report(lean=False))
    assert cli.cmd_doctor(Args()) == 1
    monkeypatch.setattr(TC, "toolchain_report", lambda *a, **k: fake_report(model=False))
    assert cli.cmd_doctor(Args()) == 1
    monkeypatch.setattr(TC, "toolchain_report",
                        lambda *a, **k: fake_report(checked=False))
    assert cli.cmd_doctor(Args()) == 2
    out = capsys.readouterr().out        # 先调用、再取输出（反过来读到的是上一次的）
    assert "没做成" in out, out


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
