# -*- coding: utf-8 -*-
"""判据：Lean 工具链的开机自检必须抓得住"用户提供的虚构 lean 环境"。

业主 2026-10-22 的原话：「开机自检可以做，防止用户提供虚构的lean环境」。

这一档要防的「不是」"没装 Lean"（那种情况 `toolchain.probe_checkers` 早就如实报没装），
而是一个「看起来装好了、也会打印版本、但什么都不检查」的回显器：一个五行批处理
打印一行 `Lean (version 4.7.0, ...)`、任何输入都以 0 退出，就能让
`detect_verifier` 判"可用"，于是整条 `evidence_kind="proof"` 的证据链建立在一句
"有人说过自己是 Lean"之上。唯一能机械区分"检查器"与"回显器"的东西是「反控」：
把 `theorem dsh_selfcheck_bad : 1 = 2 := rfl` 交过去，它必须「非 0 退出」。

五条判据（每条一个用例；反控那一步的负控在 ⑤）：

| # | 这一档 | 必须读到什么 |
|---|---|---|
| ① | 本机那份真 Lean（`D:\\Incubator\\_env\\lean470\\...\\lean.exe`） | `usable`、版本 4.x、正样例过、反控失败、`sha256` 非空 |
| ② | 假 lean（只打印版本、永远 0 退出） | `unusable`，`problems` 含"反控没失败" |
| ③ | 解释器不存在 | `unusable` 且 `checked=True`（"查了不可用" != "没查成"） |
| ④ | 开关关着 | `state="off"`、`checked=True`，且「一次子进程都不起」 |
| ⑤ | 反真空：把反控那一步换成"永远算通过" | ② 的那条断言必须红（否则它是一条空判据） |

判据一律自带环境（`_clean_env`）：注入的环境里「没有」任何 `AGENTFLOW_*`，
于是本机的 `settings.json` 与 `AGENTFLOW_LEAN_BIN` 渗不进来 —— 这一档要证明的是
"自检会拒绝假的"，不是"这台机器碰巧怎么配的"。
"""
from __future__ import annotations

import os
import pathlib

import pytest

from agentflow import leantoolchain as LT
from agentflow import toolchain as TC

#: 本机那份真 Lean 的落点（现场实测 2026-10-22：83,968 B、官方 4.7.0 Windows 布局）。
#: 判据不把它写死在断言里，而是"在就用、不在就跳过并说明" —— 换一台机器跑这一批时，
#: ① 会如实报"这一档没跑"，而 ②③④⑤ 与机器无关，照旧全跑。
REAL_LEAN = pathlib.Path(r"D:\Incubator\_env\lean470\lean-4.7.0-windows\bin\lean.exe")
#: 环境变量档能覆盖它（判据在别的机器上跑时不必改文件）。
ENV_REAL_LEAN = "AGENTFLOW_SELFCHECK_REAL_LEAN"


def _clean_env(**extra: str) -> dict:
    """一份"什么都没配"的环境：去掉全部 `AGENTFLOW_*`，再加上本用例要的那几格。

    为什么必须自己造：`tests/conftest.py` 把 `AGENTFLOW_SETTINGS` 钉到一个不存在的
    路径并把机器级的环境变量清掉，而 `AGENTFLOW_LEAN_ENABLED=1` 是「开着」那一档的
    套件契约。这一批要自己决定"哪一档开着、解释器在哪"，所以注入整份映射
    （`selfcheck(env=...)` 给了 `env` 就只认它）。
    """
    base = {k: v for k, v in os.environ.items() if not k.startswith("AGENTFLOW_")}
    base.update(extra)
    return base


def _real_lean() -> pathlib.Path:
    """本机那份真 Lean 的路径；找不到就跳过并说清"跳过不是通过"。"""
    override = os.environ.get(ENV_REAL_LEAN, "").strip()
    candidate = pathlib.Path(override) if override else REAL_LEAN
    if not candidate.is_file():
        pytest.skip(
            f"这一档没跑：本机没有真 Lean（找的是 {candidate}）。"
            f"跳过不等于通过 —— 要跑它请把 {ENV_REAL_LEAN} 指向一个真的 lean，"
            "并确认它在 4.x 上能被反控（假命题）拒掉"
        )
    return candidate


def _fake_lean(workdir: pathlib.Path) -> pathlib.Path:
    """写一个"看起来像 Lean"的假解释器：打印版本行、任何输入都以 0 退出。

    形态刻意贴着最容易被骗过去的那一档（业主说的"虚构环境"）：
    - `lean --version` 吐一行真的 4.7.0 版本行（`_parse_version` 会接受它）；
    - 拿一个 `.lean` 文件当参数时也退出 0（连 `1 = 2` 都"证明成功"）。
    于是第 ①②③ 步全过，「只有反控」能把它揪出来。

    Windows 上写成 `.bat`（`subprocess` 起 `.bat` 由系统 shell 兜住）；
    其余平台写 `sh` 脚本。两者都只做"回显 + 退出 0"。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = workdir / "lean.bat"
        text = ("@echo off\r\n"
                "echo Lean (version 4.7.0, x86_64-w64-windows-gnu, commit fake, Release)\r\n"
                "exit /b 0\r\n")
        path.write_bytes(text.encode("utf-8"))
        return path
    path = workdir / "lean"
    text = ("#!/bin/sh\n"
            "echo \"Lean (version 4.7.0, x86_64-w64-windows-gnu, commit fake, Release)\"\n"
            "exit 0\n")
    path.write_bytes(text.encode("utf-8"))
    path.chmod(0o755)
    return path


def _criterion_two_holds(result: dict) -> bool:
    """判据 ② 的那条断言，单独抽出来 —— ⑤ 要证明它「可以被证伪」。

    分成一个谓词的理由：⑤ 的做法是"把反控那一步换成永远算通过，然后问 ② 还成不成立"。
    若 ② 与 ⑤ 各自手写一遍断言，⑤ 证明的就只是"另一个字符串"，
    而"② 会不会红"这件事没有人看着。
    """
    return (
        result["state"] == "unusable"
        and result["checked"] is True
        and any("反控没失败" in str(p) for p in result["problems"])
    )


# ============================================================ ① 真 Lean


def test_the_real_lean_on_this_machine_passes_all_four_steps(tmp_path: pathlib.Path) -> None:
    """① 真 Lean：四步全过 ⇒ `usable`，且读数里每一格都有值。

    另外钉两件事：

    - `lean_path` 与 `toolchain.resolve_checker("lean", env)` 给出的「是同一个路径」
      （自检的查找梯子与探测的查找梯子不许各说各话 —— 那种漂移在 `toolchain.py`
      的模块 docstring 开头记过两次）；
    - `tmp_root` 下跑完是「空的」：临时 `.lean` 与正反两个样例都删净了。
    """
    exe = _real_lean()
    work = tmp_path / "work"
    got = LT.selfcheck(env=_clean_env(AGENTFLOW_LEAN_ENABLED="1",
                                     AGENTFLOW_LEAN_BIN=str(exe)),
                       tmp_root=str(work))

    assert got["checked"] is True, got
    assert got["ok"] is True, got
    assert got["state"] == "usable", got
    assert got["source"] == "env", got
    assert got["version"].startswith("4."), f"版本要解析出 4.x：{got['version']!r}"
    assert got["version_ok"] is True, got
    assert got["positive"]["exit_code"] == 0, got["positive"]
    assert got["negative"]["exit_code"] not in (0, None), got["negative"]
    assert got["negative"]["failed"] is True, got["negative"]
    assert got["negative"]["control_ok"] is True, got["negative"]
    assert len(str(got["sha256"])) == 64, f"解释器的 sha256 必须算出来：{got['sha256']!r}"
    assert got["problems"] == [], f"这一档不该有任何 problem（含卫生）：{got['problems']}"
    # 与探测层同一个答案（同一个 env 下）
    assert TC.resolve_checker("lean", env=_clean_env(
        AGENTFLOW_LEAN_BIN=str(exe)))["path"] == got["lean_path"], (
        "自检解析到的解释器与 toolchain.resolve_checker 给的不是同一个 —— "
        "两条查找梯子已经分家，这正是 toolchain.py 开头记过的那个形态")
    assert list(work.iterdir()) == [], "临时文件没删净"
    # 形式化证据的档位：usable 才允许 verified
    assert LT.formal_evidence_state(got) == ("verified", "")


# ============================================================ ② 假 lean


def test_a_fake_lean_that_echoes_a_version_and_exits_zero_is_caught(
        tmp_path: pathlib.Path) -> None:
    """② 假 lean（只打印版本、永远 exit 0）⇒ `unusable` + 反控没失败。

    这条用例的关键在最后几行断言：「正样例确实"过"了」、版本确实是 4.7.0 ——
    也就是说前三步全绿，唯一的读数是第 ④ 步"反控没失败"。把反控删掉（或者把它
    读成"通过"），这个假环境就会一路绿到底，而那正是这一整套自检要防的事。
    """
    fake = _fake_lean(tmp_path / "fake")
    got = LT.selfcheck(env=_clean_env(AGENTFLOW_LEAN_ENABLED="1",
                                      AGENTFLOW_LEAN_BIN=str(fake)),
                       tmp_root=str(tmp_path / "work"))

    assert got["checked"] is True, got
    assert got["state"] == "unusable", got
    assert got["ok"] is False, got
    assert any("反控没失败" in p for p in got["problems"]), got["problems"]
    # 前三步全过 —— 这正是"光看能不能跑"抓不住它的证据
    assert got["source"] == "env", got
    assert got["version"] == "4.7.0", got["version"]
    assert got["version_ok"] is True, got
    assert got["positive"]["exit_code"] == 0, got["positive"]
    # 第 ④ 步是唯一说不的东西：假命题也被判"证明成功"
    assert got["negative"]["exit_code"] == 0, got["negative"]
    assert got["negative"]["failed"] is False, got["negative"]
    assert got["negative"]["control_ok"] is False, got["negative"]
    # 形式化证据的档位：不是 usable ⇒ 一律 unknown，并点名原因
    evidence_state, why = LT.formal_evidence_state(got)
    assert evidence_state == "unknown" and "反控没失败" in why, (evidence_state, why)


# ============================================================ ③ 解释器不存在


def test_a_missing_interpreter_is_unusable_not_unknown(tmp_path: pathlib.Path) -> None:
    """③ 解释器不存在 ⇒ `unusable` 且 `checked=True`。

    "查了，不可用"与"没查成"必须分得开：前者该去装 Lean，后者该去看自检自己为什么没跑。
    折平的形态是 `state="unknown"`（或更糟：`off`）—— 那会让人以为开关关着，
    于是一路去查设置文件，而真相是路径写错了。
    """
    got = LT.selfcheck(env=_clean_env(AGENTFLOW_LEAN_ENABLED="1",
                                      AGENTFLOW_LEAN_BIN=str(tmp_path / "nope" / "lean.exe"),
                                      PATH=""),
                       root=None, tmp_root=str(tmp_path / "work"))

    assert got["checked"] is True, got
    assert got["state"] == "unusable", got
    assert got["ok"] is False, got
    assert got["lean_path"] == "", got
    assert got["sha256"] == "", got
    assert got["version"] == "", got
    assert any("不存在" in p for p in got["problems"]), got["problems"]
    assert any("五档都找过" in p for p in got["problems"]), got["problems"]
    # 没找到解释器 ⇒ 一个子进程都不该起（正/负样例都是空读数）
    assert got["positive"]["exit_code"] is None, got["positive"]
    assert got["negative"]["exit_code"] is None, got["negative"]


# ============================================================ ④ 开关关着


def test_the_switch_off_means_off_and_no_process_is_started(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 开关关着 ⇒ `state="off"`、`checked=True`，且「不去 spawn lean」。

    "不去跑它"这件事必须被证明，不能被相信：做法是把唯一的 spawn 点 `_run` 换成
    "一被调用就炸"的桩，并把解释器指到一个「不存在」的路径 —— 于是"它没被调用"
    这件事在这一趟里是结构性的（任何一次调用都会让本用例以 AssertionError 收场），
    而不是"看起来没输出"。
    """
    calls: list = []

    def _explode(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("开关关着时不许起任何子进程（连 --version 都不许）")

    monkeypatch.setattr(LT, "_run", _explode)
    never = tmp_path / "never-there" / "lean.exe"
    got = LT.selfcheck(env=_clean_env(AGENTFLOW_LEAN_ENABLED="0",
                                      AGENTFLOW_LEAN_BIN=str(never)),
                       tmp_root=str(tmp_path / "work"))

    assert calls == [], f"开关关着却 spawn 了 {len(calls)} 次"
    assert got["checked"] is True, got
    assert got["state"] == "off", got
    assert got["ok"] is False, got
    assert got["enabled"] is False, got
    assert got["enabled_source"] == "env", got
    # 一步都没跑：路径/版本/哈希/两个样例全是空
    assert got["lean_path"] == "" and got["version"] == "" and got["sha256"] == "", got
    assert got["positive"]["exit_code"] is None and got["negative"]["exit_code"] is None, got
    # 也没有留下任何东西（连临时目录都不该开）
    assert not (tmp_path / "work").exists(), "关着的时候不该开临时目录"
    # 形式化证据的档位：关着 != 可用
    assert LT.formal_evidence_state(got)[0] == "unknown", got


# ============================================================ ⑤ 反真空


def test_the_negative_control_is_load_bearing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把反控那一步 monkeypatch 成"永远算通过" ⇒ ② 必须红。

    做法：同一份假 lean 跑两遍。第一遍是正常路径（② 成立）；第二遍把
    `_negative_control` 换成"无条件报告反控成立"，于是同一个假环境被判成 `usable` ——
    也就是说 ② 的那条断言在这种前提下已经不成立了。这正是"反控这一步到底有没有
    被自检看见"的读数：如果 ⑤ 的第二半仍然绿，说明 ② 是一条永远绿的空白判据。
    """
    fake = _fake_lean(tmp_path / "fake")
    env = _clean_env(AGENTFLOW_LEAN_ENABLED="1", AGENTFLOW_LEAN_BIN=str(fake))
    good = LT.selfcheck(env=env, tmp_root=str(tmp_path / "work-a"))
    assert _criterion_two_holds(good), f"正常路径下 ② 就不成立，这一批判据没有落脚点：{good}"

    def _always_says_the_control_worked(exe: str, workdir: pathlib.Path, *,
                                        timeout_sec: float) -> dict:
        """把"反控必须失败"折成"反控永远成立"（这一步是被打桩的那一步本身）。"""
        return {"name": LT.NEGATIVE_NAME, "exit_code": 1, "output_head": "",
                "elapsed_ms": 0.0, "failed": True, "control_ok": True,
                "problem": "", "kind": "control_ok"}

    monkeypatch.setattr(LT, "_negative_control", _always_says_the_control_worked)
    doctored = LT.selfcheck(env=env, tmp_root=str(tmp_path / "work-b"))
    assert not _criterion_two_holds(doctored), (
        "反控那一步被换掉了，② 却照样成立 ⇒ ② 没有看见反控（它是一条空判据）")
    assert doctored["state"] == "usable", (
        f"这一档必须演示出「虚构环境混过全部门」的形态，实际读到 {doctored['state']!r}")
    assert LT.formal_evidence_state(doctored)[0] == "verified", (
        "被打桩之后假环境既然判成 usable，形式化证据就会记 verified —— "
        "这正是为什么第 ④ 步不能用任何形式的『它说自己拒了』来代替真的一次运行")


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
