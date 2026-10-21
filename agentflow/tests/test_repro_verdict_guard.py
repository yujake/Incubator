"""`E-7` 的回归判据：崩溃不许被当成"负控抓住了注入的 bug"。

## 缺陷（2026-09-26 全面体检 · 子代理 E 发现）

`test/test2/repro/repro_result.py::guard` 把任何未捕获异常写成 `result="refutes"`，而 `run_all.py::verdict_of` 把"退出码非零 +
refutes"直接判成 `caught_the_injected_bug`；`caught_by()` 只用于打印、从不参与判据。于是：某个 `--inject-bug` 分支自己抛了 `ImportError` ⇒ 什么都没抓住
⇒ 仍记成"负控生效"；
- 七条负控判据整体空转，`run_all.py` 照样打印 `ALL CHECKS PASS`。这与 `run_all.py` 自己的 docstring（"the negative controls are checked
for the right failure, not just for a non-zero exit: the JSON must name the check that caught the injected bug"）和
`repro_result.emit` 的契约（"An inconclusive result is NOT a pass"）都矛盾，方向是假绿。

## 修法（两处，缺一不可）

1. `guard`：未捕获异常 ⇒ `result="inconclusive"`（退出码 2），并记 `guard_error`；
2. `verdict_of`：`refutes` 只有在点得出是哪条 check 失败时才算抓住了 bug，
否则判 `crashed`；`bugs_ok` 也显式要求点名。

只改 ① 不改 ② 仍会漏：任何一种"退出码非零 + refutes + 没点名"的记录都能混过去（本文件的 `test_a_refutes_without_a_named_check_is_crashed` 就是那一形态）。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

REPRO = pathlib.Path(__file__).resolve().parents[2] / "test" / "test2" / "repro"


def _load(name: str, filename: str):
    path = REPRO / filename
    assert path.is_file(), f"找不到 {path}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RR = _load("_repro_result_for_e7", "repro_result.py")
RA = _load("_run_all_for_e7", "run_all.py")


# ------------------------------------------------------------------ 判据层


def _rec(*, returncode: int, result: dict | None) -> dict:
    return {"script": "expX_probe.py", "returncode": returncode, "result": result,
            "banner_pass": False, "banner_fail": False, "banner_inconclusive": False}


def test_a_refutes_without_a_named_check_is_crashed() -> None:
    """负控（核心）：`refutes` 但一条 failed check 都没点名 ⇒ `crashed`。

    这条在改前必红（改前返回 `caught_the_injected_bug`）。
    """
    rec = _rec(returncode=1, result={
        "result": "refutes", "evidence_kind": "cross_check",
        "negation_kind": "no_local_evidence",
        "observations": {"exception": "ImportError: boom", "traceback": "..."},
    })
    assert RA.verdict_of(rec) == "crashed", RA.verdict_of(rec)
    assert RA._named_failing_check(rec) == []


def test_a_refutes_that_names_its_check_is_still_caught() -> None:
    """正控：点了名（`failed_checks`）⇒ 仍然算抓住了注入的 bug（别把判据改成"永远抓不住"）。"""
    rec = _rec(returncode=1, result={
        "result": "refutes", "evidence_kind": "cross_check",
        "negation_kind": "no_local_evidence",
        "observations": {"failed_checks": ["girths_match"],
                         "caught_by": "girths_match: injection detected"},
    })
    assert RA.verdict_of(rec) == "caught_the_injected_bug"
    assert RA.caught_by(rec) == "girths_match"


def test_caught_by_alone_also_counts_as_named() -> None:
    """兼容形态：只有 `caught_by` 字符串（没有 `failed_checks` 数组）也算点名。

    为什么要兼容：这是 `emit()` 在 `failed` 非空时一定会写的另一个字段，
    而历史上两类记录都存在。判据的对象是"有没有指出是哪条 check"，
    不是"用的是哪一个字段名"。
    """
    rec = _rec(returncode=1, result={
        "result": "refutes", "evidence_kind": "cross_check", "negation_kind": "x",
        "observations": {"caught_by": "girths_match: injection detected"},
    })
    assert RA.verdict_of(rec) == "caught_the_injected_bug"
    assert RA._named_failing_check(rec) == ["girths_match: injection detected"]


def test_an_inconclusive_run_is_not_a_pass() -> None:
    """负控 2：`inconclusive` ⇒ `inconclusive`（既不是 supports 也不是 caught）。"""
    rec = _rec(returncode=2, result={
        "result": "inconclusive", "evidence_kind": "cross_check",
        "negation_kind": "no_local_evidence",
        "observations": {"undecided_checks": [{"check": "budget_not_exceeded"}]},
    })
    assert RA.verdict_of(rec) == "inconclusive"


# ------------------------------------------------------------------ 产生层


def test_the_guard_reports_a_crash_as_inconclusive(tmp_path: pathlib.Path) -> None:
    """负控 3（端到端的最小形态）：`guard` 包着一个会抛的 `main` ⇒ 退出码 2 + INCONCLUSIVE。

    这条同时钉住 `guard` 与 `emit` 的接口：`guard` 自己 `sys.exit`，所以在子进程里跑。
    """
    script = tmp_path / "probe_guard.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, r'{REPRO}')\n"
        "from repro_result import guard\n"
        "def boom():\n"
        "    raise ImportError('inject-bug 分支自己炸了')\n"
        "guard(boom)\n",
        encoding="utf-8",
    )
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    out = p.stdout + p.stderr
    assert p.returncode == 2, f"崩溃必须是『没查成』(2)，实测 {p.returncode}：\n{out[-1200:]}"
    assert "ALL CHECKS INCONCLUSIVE" in p.stdout, out[-1200:]
    assert "ALL CHECKS FAIL" not in p.stdout, "崩溃被写成了『负控失败』（refutes）—— E-7 复发"
    line = next(x for x in p.stdout.splitlines() if x.startswith("REPRO_RESULT:"))
    rec = {"script": "probe_guard.py", "returncode": p.returncode,
           "result": json.loads(line.split("REPRO_RESULT:", 1)[1].strip())}
    assert RA.verdict_of(rec) == "inconclusive", RA.verdict_of(rec)
    assert rec["result"]["observations"]["guard_error"].startswith("ImportError")
