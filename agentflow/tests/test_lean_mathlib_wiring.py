# -*- coding: utf-8 -*-
"""判据：Mathlib（图论）真的接在 Lean 检查器的调用链上。

## 这一批补的是哪一段缺口（2026-10-25 的现场）

盘上那份 Mathlib 是编译好的：`.lake/build/lib` 下 4100 个 `.olean`，
`Mathlib/Combinatorics/SimpleGraph` 那 38 个模块全有产物。而检查器是裸跑的
（`lean.exe <file>`，见 `leantoolchain._run` 与 `formalgw.check_lean`），裸 lean
不知道 Mathlib 在哪 —— 同一个 `.lean` 文件实测原文是

    error: unknown package 'Mathlib'
    error: unknown identifier 'SimpleGraph'

退出码 1。也就是说"装了等于没装"：`import Mathlib...` 一句都编不过，
而报告照样能打印"形式化核验"。这一批把"接线"这件事变成可证的读数。

## 四条判据（每条一个用例；第 ④ 条是反真空）

| # | 这一档 | 必须读到什么 |
|---|---|---|
| ① | 有 Mathlib | 裸命令退出码非 0 且原文含 `unknown package 'Mathlib'`；`mathlib_command` 给的那条命令退出 0 且输出里有 `SimpleGraph` |
| ② | 检测点被藏掉（没有 Mathlib） | 退回裸 lean、`mathlib.state=absent`、读数写明"无 Mathlib"，而不许因此把整次自检判成 `unusable` |
| ③ | 检测到工程根、但图论库不可用 | `mathlib.state=unusable` ＋ 检查器原文；整次自检不许是 `usable` |
| ④ | 反真空：把"Mathlib 检测"打桩成恒 True 而实际没有 | ①② 的那条断言必须红（那条命令编不过，读数不许是 `usable`） |

另加一条桥接层的判据（`tools/verify_tools.check_formal`）：设置文件里没有
`toolchain.mathlib_root` 时，桥接层必须自己把库段补上；把那一手关掉，同一个调用
必须退回 `import_unavailable`。

判据自带环境（`_clean_env`：去掉全部 `AGENTFLOW_*` 再加本用例要的那几格），
所以本机的 `settings.json` 渗不进"没有 Mathlib"那一档。需要真 Lean / 真 Mathlib
的用例在缺东西时如实 skip（跳过不等于通过，理由逐条写在 skip 消息里）。
"""
from __future__ import annotations

import os
import pathlib

import pytest

from agentflow import formalgw as FG
from agentflow import leantoolchain as LT
from agentflow.tools import verify_tools as VT

#: 本机那份真 Lean（现场实测 2026-10-22：官方 4.7.0 Windows 布局）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path

LEAN = lean_path()
#: 环境变量档能覆盖它（判据在别的机器上跑时不必改文件，与自检那一批同一个名字）。
ENV_REAL_LEAN = "AGENTFLOW_SELFCHECK_REAL_LEAN"
#: 这一批判据要等一次真编译：`import` 那条链路冷启动实测 7–11 秒，给 300 秒是余量。
COMPILE_TIMEOUT_SEC = 300.0
#: 与 `leantoolchain.GRAPH_SOURCE` 逐字同形（这里再写一份是为了"判据不读实现常量"：
#: 实现把那条 import 改坏了，这一批要跟着红，而不是跟着一起变）。
GRAPH_PROBE_SOURCE = "import Mathlib.Combinatorics.SimpleGraph.Basic\n\n#check SimpleGraph\n"


def _real_lean() -> pathlib.Path:
    """本机那份真 Lean；找不到就 skip 并说清"跳过不是通过"。"""
    override = os.environ.get(ENV_REAL_LEAN, "").strip()
    candidate = pathlib.Path(override) if override else LEAN
    if not candidate.is_file():
        pytest.skip(f"这一档没跑：本机没有真 Lean（找的是 {candidate}）—— "
                    f"要跑它请把 {ENV_REAL_LEAN} 指向一个真的 lean")
    return candidate


def _clean_env(**extra: str) -> dict:
    """一份"什么都没配"的环境（只加本用例要的那几格），于是本机 settings.json 渗不进来。

    `LEAN_PATH` 也要去掉，理由与 `AGENTFLOW_*` 不同、也更隐蔽：
    `formalgw.ensure_lean_path` 会把它写进进程环境（只加不改），于是同一次 pytest 里
    先跑过任何一条起真检查器的用例之后，这一档"没有 Mathlib"就会被上一趟留下的段
    静默变成"有 Mathlib" —— 而判据要的是一份确定的环境，不是"这一趟碰巧怎么配的"
    （实测形态：整批跑时这一档红、单跑时绿）。
    """
    base = {k: v for k, v in os.environ.items()
            if not k.startswith("AGENTFLOW_") and k != "LEAN_PATH"}
    base.update(extra)
    return base


def _detect(lean: pathlib.Path) -> dict:
    """在注入的干净环境里检测一次 Mathlib；没有就 skip（跳过不是通过）。"""
    reading = LT.mathlib_reading(env=_clean_env(), lean_exe=str(lean))
    if not reading.get("detected"):
        pytest.skip(f"这一档没跑：注入环境里没检测到 Mathlib 工程根"
                    f"（reason={reading.get('reason')}）")
    return reading


# ============================================================ ① 有 Mathlib：接线是通的


def test_criterion_1_bare_lean_cannot_see_mathlib_and_the_wired_command_can(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 ①：同一个 `.lean`，裸命令退出 1（unknown），接上 Mathlib 的命令退出 0。

    这条用例就是"接线"的硬证据：两个读数来自「同一份源码、同一个 lean.exe」，
    差别只有"知不知道 Mathlib 在哪"。

    裸那一趟必须把进程的 `LEAN_PATH` 摘掉：`_run` 缺省继承进程环境，而同一次 pytest 里
    先跑过的用例可能留下 `LEAN_PATH`（`formalgw.ensure_lean_path` 会写它）——
    留着的话"裸 lean 看不见 Mathlib"这句话就不成立了，判据会变成在量上一次的残留。
    """
    monkeypatch.delenv("LEAN_PATH", raising=False)
    monkeypatch.delenv("AGENTFLOW_MATHLIB_ROOT", raising=False)
    lean = _real_lean()
    reading = _detect(lean)
    probe = tmp_path / "graph_probe.lean"
    probe.write_bytes(GRAPH_PROBE_SOURCE.encode("utf-8"))

    bare = LT._run([str(lean), str(probe)], cwd=str(tmp_path),
                   timeout_sec=COMPILE_TIMEOUT_SEC)
    assert bare["started"] is True, bare
    assert bare["exit_code"] not in (0, None), (
        f"裸 lean 居然编过了？那这一批就没有落脚点：{bare}")
    assert "unknown package 'Mathlib'" in str(bare["output_head"]), bare["output_head"]
    assert "SimpleGraph" in str(bare["output_head"]), bare["output_head"]

    plan = LT.mathlib_command(reading, str(lean), str(probe), workdir=str(tmp_path))
    assert plan["runner"] in ("lake_env_lean", "lean_path"), plan
    got = LT._run(plan["argv"], cwd=str(plan["cwd"]), timeout_sec=COMPILE_TIMEOUT_SEC,
                  env_overlay=plan["env_overlay"] or None)
    assert got["started"] is True, got
    assert got["exit_code"] == 0, (got, plan)
    assert "SimpleGraph" in str(got["output_head"]), got["output_head"]


# ============================================================ ② 没有 Mathlib：退回裸 lean


def test_criterion_2_without_mathlib_it_falls_back_and_never_says_unusable(
        tmp_path: pathlib.Path) -> None:
    """判据 ②：检测点被藏掉（工作区里没有 `_env/`）⇒ `absent`，整次自检照旧 `usable`。

    缺库是"这一项不可用"，不是"检查器坏了"：这两件事的处置相反（装库 vs 修工具链），
    所以这里同时钉两件事 —— `mathlib` 那一格写"无 Mathlib"，而顶层的 `state` 仍是
    `usable`、`problems` 里一条 Mathlib 都不许有。
    """
    lean = _real_lean()
    ws = tmp_path / "ws"
    ws.mkdir()
    env = _clean_env(AGENTFLOW_LEAN_ENABLED="1", AGENTFLOW_LEAN_BIN=str(lean))
    # `env` 注入 ⇒ `toolchain_settings` 不落磁盘，本机 settings.json 里的
    # `toolchain.mathlib_root` 读不到；`root` 下面也没有 `_env/` ⇒ 五档全空。
    got = LT.selfcheck(env=env, root=ws, tmp_root=str(tmp_path / "tmp"))

    assert got["state"] == "usable", got
    assert got["checked"] is True and got["ok"] is True, got
    m = got["mathlib"]
    assert m["detected"] is False, m
    assert m["state"] == "absent", m
    assert "无 Mathlib" in str(m["reason"]), m["reason"]
    assert got["problems"] == [], (
        f"缺库不许写进顶层 problems（那会让整次自检不是 usable）：{got['problems']}")
    assert LT.formal_evidence_state(got) == ("verified", ""), LT.formal_evidence_state(got)


# ============================================================ ③ 检测到根、但图论不可用


def test_criterion_3_a_detected_but_unusable_graph_library_is_unusable_with_raw_reason(
        tmp_path: pathlib.Path) -> None:
    """判据 ③：工程根检测到了、图论那一项编不过 ⇒ `mathlib=unusable` 加检查器原文，
    而整次自检不许是 `usable`。

    这一档的副本是"Mathlib 形状但 `.lake/build/lib` 是空的"——也就是
    `SimpleGraph/Basic.olean` 不在的那种形态（真·改名那一趟的读数见本文件末尾的
    docstring 引用与 `draft` 里的现场记录：原文是
    `object file ...\\SimpleGraph\\Basic.olean ... does not exist`）。文件面读数是
    "工程根在"，而唯一算数的判据是"这一次编译过没过"。
    """
    lean = _real_lean()
    root = tmp_path / "mathlib4-4.7.0"
    (root / ".lake" / "build" / "lib").mkdir(parents=True)
    (root / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\n\npackage mathlib where\n", encoding="utf-8")
    (root / "lean-toolchain").write_text("leanprover/lean4:v4.7.0\n", encoding="utf-8")

    env = _clean_env(AGENTFLOW_LEAN_ENABLED="1", AGENTFLOW_LEAN_BIN=str(lean))
    got = LT.selfcheck(env=env, mathlib_root=str(root),
                       tmp_root=str(tmp_path / "tmp"))

    m = got["mathlib"]
    assert m["detected"] is True and m["source"] == "flag", m
    assert m["graph_olean"] == "", m
    assert m["exit_code"] not in (0, None), m
    assert m["state"] == "unusable", m
    assert "Mathlib" in str(m["evidence"]), m["evidence"]
    assert got["state"] == "unusable", got
    assert got["ok"] is False, got
    assert any(str(p).startswith("[Mathlib]") for p in got["problems"]), got["problems"]
    assert LT.formal_evidence_state(got)[0] == "unknown", LT.formal_evidence_state(got)


def test_criterion_3b_exit_zero_without_the_check_line_is_not_usable(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 ③ 的加强：退出码 0 但输出里没有 `SimpleGraph` ⇒ 仍然 `unusable`。

    为什么这条要单列：`lake env lean` / `lean` 的退出码只回答"这次运行有没有失败"，
    而"图论可用"要的是"这个检查器真的把 `SimpleGraph` 当成一个东西"。一个任何输入
    都退 0、还照抄版本行的东西（虚构环境那一档）在退出码上永远是"通过"——
    所以通过必须被看见，不能只靠"它没说话"。

    回显式假解释器过不了第 ④ 步（反控），而第 ⑤ 步排在它后面 —— 所以这里把第 ④ 步
    打桩成"反控成立"，只为让第 ⑤ 步真的跑到（那不是本用例要判的东西）。
    """
    if os.name != "nt":
        pytest.skip("这一档用 .bat 造回显式假解释器（Windows 专用形态）")

    def _says_control_worked(exe: str, workdir: pathlib.Path, *, timeout_sec: float) -> dict:
        return {"name": LT.NEGATIVE_NAME, "exit_code": 1, "output_head": "",
                "elapsed_ms": 0.0, "failed": True, "control_ok": True,
                "problem": "", "kind": "control_ok"}

    monkeypatch.setattr(LT, "_negative_control", _says_control_worked)
    fake = tmp_path / "fake" / "lean.bat"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_bytes(("@echo off\r\n"
                      "echo Lean (version 4.7.0, x86_64-w64-windows-gnu, commit fake)\r\n"
                      "exit /b 0\r\n").encode("utf-8"))
    root = tmp_path / "mathlib4-4.7.0"
    (root / ".lake" / "build" / "lib").mkdir(parents=True)
    (root / "lakefile.lean").write_text(
        "import Lake\nopen Lake DSL\n\npackage mathlib where\n", encoding="utf-8")
    (root / "lean-toolchain").write_text("leanprover/lean4:v4.7.0\n", encoding="utf-8")

    env = _clean_env(AGENTFLOW_LEAN_ENABLED="1", AGENTFLOW_LEAN_BIN=str(fake))
    got = LT.selfcheck(env=env, mathlib_root=str(root), tmp_root=str(tmp_path / "tmp"))

    m = got["mathlib"]
    assert m["exit_code"] == 0, m
    assert m["state"] == "unusable", m
    assert "SimpleGraph" not in str(m["evidence"]), m["evidence"]


# ============================================================ ④ 反真空


def _stub_detection_says_detected(monkeypatch: pytest.MonkeyPatch, bogus_root: pathlib.Path):
    """把"Mathlib 检测"打桩成恒 True（工程根指向一个不存在的目录，库段也是空的）。

    这是判据 ④ 的做法：检测层"说"有 Mathlib，而盘上什么都没有。
    如果第 ⑤ 步的结论是从检测层读出来的，它就会报 `usable` —— 那正是要抓的形态。
    """

    def _always_detected(**_kwargs):
        row = LT._empty_mathlib()
        row.update({"checked": True, "detected": True, "state": "unknown",
                    "root": str(bogus_root), "source": "stub",
                    "lakefile": str(bogus_root / "lakefile.lean"),
                    "lean_path": "", "lean_exe": ""})
        return row

    monkeypatch.setattr(LT, "mathlib_reading", _always_detected)


def _criterion_one_holds(tmp_path: pathlib.Path, lean: pathlib.Path,
                         reading: dict) -> bool:
    """判据 ① 的那条断言，抽出来 —— ④ 要证明它「可以被证伪」。"""
    probe = tmp_path / "graph_probe_recheck.lean"
    probe.write_bytes(GRAPH_PROBE_SOURCE.encode("utf-8"))
    plan = LT.mathlib_command(reading, str(lean), str(probe), workdir=str(tmp_path))
    got = LT._run(plan["argv"], cwd=str(plan["cwd"]), timeout_sec=COMPILE_TIMEOUT_SEC,
                  env_overlay=plan["env_overlay"] or None)
    return got["exit_code"] == 0 and "SimpleGraph" in str(got["output_head"])


def test_criterion_4_anti_vacuum_stubbed_detection_cannot_make_it_usable(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 ④：检测恒 True 而实际没有 ⇒ ① 的断言红、读数不许是 `usable`。

    没有这一条，"图论可用"可以整段照着检测层写出来：检测层说 detected 就报 usable，
    而一次编译都没发生（`toolchain.mathlib_state` 的 docstring 记过那次事故：
    盘上 `.olean` 在、`import Mathlib` 报 `unknown package 'Std'`）。这里把检测打桩成
    恒 True，然后问两件事：
      - 那条命令还能不能编过（不能 ⇒ ① 的断言是承重的）；
      - 自检读数会不会报 usable（不会 ⇒ 第 ⑤ 步没有从检测层抄结论）。
    """
    lean = _real_lean()
    bogus = tmp_path / "nowhere-mathlib"
    _stub_detection_says_detected(monkeypatch, bogus)
    ws = tmp_path / "ws"
    ws.mkdir()
    env = _clean_env(AGENTFLOW_LEAN_ENABLED="1", AGENTFLOW_LEAN_BIN=str(lean))
    got = LT.selfcheck(env=env, root=ws, tmp_root=str(tmp_path / "tmp"))

    m = got["mathlib"]
    assert m["detected"] is True, m
    assert m["state"] != "usable", (
        f"检测被打桩成 True，第 ⑤ 步居然报 usable ⇒ 它是从检测层抄的结论：{m}")
    assert got["state"] != "usable", got
    assert got["ok"] is False, got
    # ① 的那条断言在同一个打桩下必须不成立（否则它是一条空判据）
    assert _criterion_one_holds(tmp_path, lean, m) is False, (
        "检测恒 True 而盘上没有 Mathlib，那条命令却编过了 ⇒ ① 的断言看不见现实")


# ============================================================ 桥接层（verify_tools）


def test_the_bridge_reaches_mathlib_even_without_a_mathlib_root_in_settings(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`verify.check_formal` 那一层：设置文件没写 `mathlib_root` 时它必须自己补库段。

    两组读数来自同一次调用、同一份源码，差别只有"`_bridge_mathlib_lean_path` 有没有
    补那一串 `LEAN_PATH`"：
      - 补上 ⇒ `verified`；
      - 关掉（改前形态）⇒ `import_unavailable` 加原文 `unknown package 'Mathlib'`。
    第二组是"改前红"的机器形态：它证明这条判据不是照着实现写的。
    """
    lean = _real_lean()
    _detect(lean)
    # 设置文件指到一个不存在的路径 ⇒ 桥接层"自己找库"那一档是唯一的来源。
    monkeypatch.setenv("AGENTFLOW_SETTINGS", str(tmp_path / "no-settings.json"))
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(lean))
    monkeypatch.delenv("AGENTFLOW_MATHLIB_ROOT", raising=False)
    monkeypatch.delenv("LEAN_PATH", raising=False)

    def _call():
        FG._mathlib_lean_path.cache_clear()   # 两处 memo 清掉，两组读数才可比
        return VT.check_formal(
            "图论接线：True",
            source="theorem graph_wiring : True := trivial",
            checker_name="graph_wiring",
            imports=("Mathlib.Combinatorics.SimpleGraph.Basic",),
            timeout_sec=COMPILE_TIMEOUT_SEC,
        ).data or {}

    green = _call()
    assert green.get("verified") is True, green
    assert green.get("reason") == "verified", green
    assert os.environ.get("LEAN_PATH") is None, (
        "补上去的 LEAN_PATH 必须在 finally 里还原（否则下一次读数会因此变样）")

    # 改前形态：本层不补 LEAN_PATH
    monkeypatch.setattr(VT, "_bridge_mathlib_lean_path", lambda: {})
    red = _call()
    assert red.get("verified") is None, red
    assert red.get("reason") == "import_unavailable", red
    assert "unknown package 'Mathlib'" in str(red.get("verifier_output")), red.get(
        "verifier_output")


def test_the_restore_removes_lean_path_instead_of_writing_an_empty_string() -> None:
    """`_restore_lean_path` 的两种落点：原来没有 ⇒ 删掉；原来有 ⇒ 逐字还原。

    为什么这一条要单独判：写成空串也是"还回去了"的样子，而
    `formalgw.find_mathlib_root` 对"没有 `LEAN_PATH`"与"`LEAN_PATH` 是空的"
    参与回推的方式不同 —— 折平的形态是静默的（没有任何地方会报错）。
    """
    saved = {"LEAN_PATH": None}
    os.environ["LEAN_PATH"] = "x"
    VT._restore_lean_path(saved)
    assert os.environ.get("LEAN_PATH") is None, os.environ.get("LEAN_PATH")

    saved = {"LEAN_PATH": "before"}
    os.environ["LEAN_PATH"] = "x"
    VT._restore_lean_path(saved)
    assert os.environ.get("LEAN_PATH") == "before", os.environ.get("LEAN_PATH")
    os.environ.pop("LEAN_PATH", None)


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
