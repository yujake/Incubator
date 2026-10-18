"""`X-2` 剩余面的判据：pytest 的临时根必须钉在仓外（不许落回工作目录）。

## 这条缺陷在说什么（`draft/25` 的 `X-2`）

仓库根曾经冒出 `pytest-of-unknown/`。成因不是 pytest 的 bug：没有显式 basetemp 时它算
``temproot = Path(os.environ["PYTEST_DEBUG_TEMPROOT"] or tempfile.gettempdir()).resolve()``，
而 `tempfile.gettempdir()` 在没有任何可写临时目录时会退回当前工作目录；
相对路径形式的 `PYTEST_DEBUG_TEMPROOT` 也会被 `resolve()` 解到 cwd。
两种情形都会让临时目录落进仓库树里。

## 读法

`test_positive_*` = 正控（`tests/conftest.py` 导入期钉的那个根真的在仓外）；
`test_negative_control_*` = 负控（说明"不钉会怎样"，并证明逃逸开关真的能关掉钉子 ——
没有它，"这条判据有牙"就只是自述）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

#: 包根（`agentflow/`）：临时根不许出现在它的任何一层父链上。
_PROJ = Path(__file__).resolve().parents[1]
#: git 仓库根：`.git` 在包根的上一级 —— `R6-F12` 指出只查包根不够（两级都要排除）。
_REPO = _PROJ.parent


def test_positive_temp_root_is_pinned_outside_the_repo(tmp_path_factory) -> None:  # noqa: ANN001
    """正控：本次会话的 basetemp 既不在仓库树里，也不是默认的 `pytest-of-<user>` 根。

    `PYTEST_DEBUG_TEMPROOT` 由 `tests/conftest.py` 在导入期钉成绝对路径
    （`<系统临时目录>/agentflow-pytest`）；判据同时看两处读数：
    环境变量（机制）与实际 basetemp（效果）。
    """
    pinned = os.environ.get("PYTEST_DEBUG_TEMPROOT", "")
    if os.environ.get("AGENTFLOW_NO_TEMPROOT_PIN"):
        # `R6-F11`（集中审查）：这里改前是 `pytest.skip`，于是"逃逸开关被置位"
        # 不会让任何判据变红 —— 而开关被置位恰恰等于这条防线不在。
        # 现在改成硬失败：要在副本里做"关掉钉子"的实验就去 `temp/` 的整树副本里做
        # （那里的红是预期的），在真仓里置位就该红。
        raise AssertionError(
            "AGENTFLOW_NO_TEMPROOT_PIN 被置位 ⇒ X-2 的防线不在（正控必须红而不是 skip）。"
            "要做'关掉钉子'的端到端负控，请在 temp/ 的整树副本里做。"
        )
    assert pinned, "conftest 没钉 PYTEST_DEBUG_TEMPROOT ⇒ X-2 的防线不在"
    pinned_path = Path(pinned)
    assert pinned_path.is_absolute(), f"钉子必须是绝对路径（相对值会被 resolve 到 cwd）：{pinned}"

    base = tmp_path_factory.getbasetemp()
    assert base.is_dir(), base
    # `R6-F12`：只查 `agentflow/` 不够 —— git 仓库根是它的上一级（`D:\Incubator`），
    # 落在两者之间的 basetemp 同样在版本库里。两级都排除。
    assert _PROJ not in base.parents and base != _PROJ, \
        f"basetemp 落在包树里（X-2 的残留形态）：{base}"
    assert _REPO not in base.parents and base != _REPO, \
        f"basetemp 落在 git 仓库树里（两级都要排除）：{base}"
    assert "agentflow-pytest" in base.parts or ".pytest-tmp" in base.parts, \
        f"basetemp 不是我们钉的那个根（说明钉子没生效）：{base}"


def test_negative_control_relative_temp_root_resolves_into_the_working_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控：相对形式的 `PYTEST_DEBUG_TEMPROOT` 会被解到当前工作目录。

    这一条不建任何目录，证明的是"钉子不在时 pytest 会把临时根解到哪"。
    实测（2026-09-28，`agentflow/` 下）：把 `PYTEST_DEBUG_TEMPROOT` 设成
    `agentflow-residual-probe` 时，pytest 试图创建
    `D:\\Incubator\\agentflow\\agentflow-residual-probe\\pytest-of-ysc20`
    —— 就在仓库树里；`pytest-of-unknown` 那一支同理（用户名解析失败时）。
    """
    monkeypatch.setenv("PYTEST_DEBUG_TEMPROOT", "agentflow-residual-probe")
    resolved = Path(os.environ["PYTEST_DEBUG_TEMPROOT"]).resolve()
    assert resolved.parent == Path.cwd(), (
        f"相对临时根没有被解到 cwd（装置变了，这条负控失去意义）：{resolved} vs {Path.cwd()}"
    )
    assert _PROJ in resolved.parents or resolved.parent == _PROJ or Path.cwd() == _PROJ, \
        f"负控的前提是'cwd 在仓库里'：cwd={Path.cwd()} 包根={_PROJ}"


def test_negative_control_escape_hatch_really_disables_the_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """负控：逃逸开关真的能让 `_pin_temp_root()` 放弃（而不是"设了也没用"）。

    为什么要这一条：如果开关是假的，那么"关掉钉子后残留会不会出现"这个实验
    根本做不出来 —— 那正是本项目反复踩的"注入没生效却以为生效了"。
    这里直接在子进程里 import conftest 太脆（conftest 不是普通模块），
    所以改用行为等价的判据：开关置位时，conftest 的模块级常量必须为空串。
    """
    monkeypatch.setenv("AGENTFLOW_NO_TEMPROOT_PIN", "1")
    monkeypatch.delenv("PYTEST_DEBUG_TEMPROOT", raising=False)
    conftest = pytest.importorskip("conftest", reason="tests/conftest.py 不在导入路径上时跳过")
    assert conftest._pin_temp_root() == "", "逃逸开关没有生效 ⇒ 负控实验做不出来"


def test_negative_control_end_to_end_the_hatch_turns_the_positive_control_red() -> None:
    """负控（端到端，`R6-F11` 明确要求的那一条）：开关置位后跑真正控 ⇒ 必须红，
    并且那条相对临时根真的会在仓树里落地（跑完清理，并断言清理干净）。

    为什么必须端到端：上面那条只断言"函数返回值是空串"，而"正控在开关置位时会 skip"
    让整件事永远不会变红 —— `R6-F11` 的原话是"没有任何判据会因'逃逸开关被置位'而变红"。
    这一条把那个缺口堵上：它起的子进程就是真判据本身，红不红由它决定。

    代价：会临时在包根下建一个探针目录（正是负控要展示的残留形态），
    所以无论红绿都在 `finally` 里删掉并断言不存在。
    """
    probe = f"agentflow-residual-probe-e2e-{os.getpid()}"
    target = _PROJ / probe
    # ⚠️ 2026-10-15：**两侧都显式钉编码**，不依赖继承来的环境。
    #
    # 真机形态（全量跑里唯一那条"只在全量跑里红"的用例）：
    # `tests/test_role_specs_complete.py` 此前在会话级
    # `os.environ.setdefault("PYTHONIOENCODING", "utf-8")`，于是**它之后**跑到的本用例
    # 把这个变量继承给了子进程 ⇒ 子进程吐 UTF-8，而 `subprocess.run(text=True)`
    # 没给 `encoding=` ⇒ 父进程按 `locale.getpreferredencoding(False)`（本机 GBK）解 ⇒
    # `_readerthread` 抛 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xa2
    # in position 584` ⇒ `proc.stdout` 是 `None` ⇒ `out = proc.stdout + proc.stderr`
    # 抛 TypeError。**字节位置与全量跑里那一条逐字相同。**
    #
    # 为什么两侧都钉而不是只加 `encoding=`：只钉解码仍依赖"父进程环境恰好没被污染"；
    # 子进程那一侧也钉成 utf-8，这个调用就与自己跑在什么环境里**无关**了 ——
    # 这正是"编码只在起子进程那一处钉"的意思。
    env = {**os.environ, "AGENTFLOW_NO_TEMPROOT_PIN": "1",
           "PYTEST_DEBUG_TEMPROOT": probe, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "tests/test_temp_root_pin.py::test_positive_temp_root_is_pinned_outside_the_repo"],
            cwd=str(_PROJ), capture_output=True, text=True, env=env,
            encoding="utf-8", errors="replace",
        )
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0, (
            f"开关置位后正控必须红（改前它 skip，所以永远绿）：\n{out[-800:]}"
        )
        assert "NO_TEMPROOT_PIN" in out or "绝对路径" in out or "basetemp" in out, (
            f"红必须落在'钉子不在'这条理由上：\n{out[-800:]}"
        )
    finally:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    assert not target.exists(), f"负控的探针目录没清干净：{target}"
