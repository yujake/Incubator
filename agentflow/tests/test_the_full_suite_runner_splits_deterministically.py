"""`scripts/pytest_all.py` 的判据：分块确定、单路等价、汇总带归属、dry-run 真空。

## 这个文件在守什么

全量并行跑器最容易坏在"看起来跑了、读数不可信"这一格。四条判据对应四类坏法：

1. 同一份清单、同一 `--jobs`、同一 `--chunk-by` 两次给出不同分块 —— 那么"红的是哪一路"
   每趟都不一样，顺序依赖永远归因不了。判据逐元素比对两次 dry-run 的分块。
2. `--jobs 1` 不是全清单顺序 —— 那它就不能当"直接 pytest 全量"的替身，
   定位顺序依赖时会把两件不同的事混成一件。判据要求单路分块 == 排序后的清单。
3. 汇总解析把 `ERROR`（collection error）当没有、或把汇总行的总数当通过 ——
   旧实现 `^FAILED (\\S+)` 就漏 `ERROR`，于是 rc=1 而 `failed_count=0`。
   判据喂只有 `ERROR` 的假日志，要求非 0 且失败清单里有那一条并带 chunk 归属。
4. `--dry-run` 偷偷起 pytest —— 那"只打印分块"就是一句空话。判据把 `Popen` / `run`
   打桩成"一调就炸"，要求 dry-run 仍然返回 0 且不建 run 目录。

## 为什么输入是合成树

真的树有几百个文件、几十 MB，判据不该为"分块算法"去跑全量。合成树把"字节数"与
"路径顺序"变成可控输入：`size-balance` 是否真的按字节（而不是按文件个数）一眼可验。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import pytest_all as P

REPO = Path(__file__).resolve().parents[1]


def _write(root: Path, rel: str, content: str) -> Path:
    """在合成树里写一个文件（显式 `newline`：R012 的行尾纪律）。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _tree(tmp_path: Path, sizes: list[tuple[str, int]]) -> Path:
    """建一棵 `tests/` 合成树；`sizes` 是 `(文件名, 字节数)`。"""
    for name, nbytes in sizes:
        _write(tmp_path, f"tests/{name}", "x" * nbytes)
    return tmp_path


def _dry(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    """跑一次 `--dry-run`，返回 `(退出码, stdout)`。"""
    capsys.readouterr()
    rc = P.main(["--root", str(root), "--dry-run", *args])
    return rc, capsys.readouterr().out


def _chunks(out: str) -> list[list[str]]:
    """从 dry-run 输出里取每路的文件清单（`[chunk N]` 头 + 缩进四格的行）。"""
    chunks: list[list[str]] = []
    for line in out.splitlines():
        if line.startswith("[chunk "):
            chunks.append([])
        elif chunks and line.startswith("    "):
            chunks[-1].append(line.strip())
    return chunks


def _fake_log(path: Path, lines: list[str]) -> Path:
    """写一份 pytest 形状的假日志。"""
    return _write(path.parent, path.name, "\n".join(lines) + "\n")


# ---------------------------------------------------------------- 1. 分块确定
def test_the_plan_is_elementwise_identical_on_two_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """同一清单 + 同一 jobs + 同一 chunk-by ⇒ 两次 dry-run 的分块逐元素相同。"""
    root = _tree(tmp_path, [(f"test_{i:02d}.py", 100 + i) for i in range(9)])

    rc1, out1 = _dry(root, capsys, "--jobs", "3", "--chunk-by", "size-balance")
    rc2, out2 = _dry(root, capsys, "--jobs", "3", "--chunk-by", "size-balance")

    assert (rc1, rc2) == (0, 0)
    first, second = _chunks(out1), _chunks(out2)
    assert first, "dry-run 一路都没打印出来 ⇒ 这条判据没有对象（反真空）"
    assert first == second


# ---------------------------------------------------------------- 2. 单路等价
def test_jobs_one_is_exactly_the_manifest_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--jobs 1` 的分块 == 全清单顺序，且不逐个列文件（避开 32k 命令行上限）。"""
    root = _tree(
        tmp_path,
        [("test_big.py", 100_000), ("test_a.py", 10), ("test_c.py", 10)],
    )

    rc, out = _dry(root, capsys, "--jobs", "1", "--chunk-by", "size-balance")

    assert rc == 0
    assert _chunks(out) == [["tests/test_a.py", "tests/test_big.py", "tests/test_c.py"]]

    manifest = P.build_manifest(root)
    all_files = [entry.rel for entry in manifest.files]
    argv = P.pytest_argv(all_files, all_files, passthrough=False)
    assert argv[-1] == "tests", "单路整棵树应该把 tests 交给 pytest，而不是列 799 个路径"
    assert "tests/test_big.py" not in argv
    assert len(" ".join(argv)) <= P.WINDOWS_CMDLINE_LIMIT


# ---------------------------------------------------------------- 3. 按字节而不是按个数
def test_size_balance_balances_bytes_not_counts(tmp_path: Path) -> None:
    """一个大文件 + 七个小文件、两路 ⇒ 必须 1/7，而不是 4/4（旧实现是后者）。"""
    root = _tree(
        tmp_path,
        [("test_big.py", 100_000), *[(f"test_s{i}.py", 1) for i in range(7)]],
    )
    plan = P.build_plan(P.build_manifest(root), 2, "size-balance")

    assert sorted(len(chunk.files) for chunk in plan) == [1, 7]
    big = max(plan, key=lambda chunk: chunk.bytes)
    assert big.files == ["tests/test_big.py"]
    assert max(chunk.bytes for chunk in plan) - min(chunk.bytes for chunk in plan) < 100_000


# ---------------------------------------------------------------- 4. 两路 3 failed / 5 passed
def test_two_chunks_three_failed_five_passed(tmp_path: Path) -> None:
    """假日志：chunk0 三红五绿、chunk1 五绿 ⇒ 退出码非 0，失败清单带 chunk 归属。"""
    files0 = ["tests/test_a.py", "tests/test_b.py"]
    log0 = _fake_log(
        tmp_path / "chunk-0.log",
        [
            "..F..",
            "=========================== short test summary info ===========================",
            "FAILED tests/test_a.py::test_1 - assert 1 == 2",
            "FAILED tests/test_a.py::test_2 - assert 2 == 3",
            "FAILED tests/test_b.py::test_3 - assert 3 == 4",
            "3 failed, 5 passed in 10.00s",
        ],
    )
    log1 = _fake_log(tmp_path / "chunk-1.log", [".....", "5 passed in 8.00s"])

    red = P.read_chunk(0, 1, log0, files0, ["python", "-m", "pytest"], 10.0)
    green = P.read_chunk(1, 0, log1, ["tests/test_c.py"], ["python", "-m", "pytest"], 8.0)

    assert red.status == "red"
    assert green.status == "green"
    assert P.aggregate([red, green]) != 0
    assert [(f.chunk, f.kind) for f in red.failures] == [(0, "failed")] * 3
    assert [f.nodeid for f in red.failures] == [
        "tests/test_a.py::test_1",
        "tests/test_a.py::test_2",
        "tests/test_b.py::test_3",
    ]
    total = P.totals([red, green])
    assert (total["failed"], total["passed"]) == (3, 10)


# ---------------------------------------------------------------- 5. 汇总与日志对不上
def test_a_summary_that_disagrees_with_the_log_is_unknown(tmp_path: Path) -> None:
    """汇总行说 3 failed、日志里只有 2 条 FAILED ⇒ 没查成（2），不许当成"就这两条"。"""
    log = _fake_log(
        tmp_path / "chunk-0.log",
        [
            "FAILED tests/test_a.py::test_1 - assert",
            "FAILED tests/test_a.py::test_2 - assert",
            "3 failed, 5 passed in 1.00s",
        ],
    )
    result = P.read_chunk(0, 1, log, ["tests/test_a.py"], ["pytest"], 1.0)

    assert result.status == "inconsistent"
    assert P.aggregate([result]) == 2


# ---------------------------------------------------------------- 6. dry-run 不起进程
def test_dry_run_spawns_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """dry-run 期间任何 `Popen` / `run` 都必须炸；返回 0、打印分块、不建 run 目录。"""
    root = _tree(tmp_path, [(f"test_{i}.py", 10) for i in range(4)])

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("dry-run 起子进程了 —— 那不是 dry-run")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)

    rc, out = _dry(root, capsys, "--jobs", "2")

    assert rc == 0
    assert len(_chunks(out)) == 2, "dry-run 没打印出两路 ⇒ 它可能什么也没算"
    assert not (root / "temp").exists(), "dry-run 建了 run 目录"


# ---------------------------------------------------------------- 7. ERROR 不是 pass
def test_an_error_is_not_a_pass(tmp_path: Path) -> None:
    """日志里只有 `ERROR`（collection error）没有 FAILED ⇒ 必须非 0 且清单含它。

    旧实现只匹配 `^FAILED`，在这一格给出 `failed_count=0` 而 rc=1 —— 有红却报"没有失败"。
    """
    log = _fake_log(
        tmp_path / "chunk-0.log",
        [
            "=========================== short test summary info ===========================",
            "ERROR tests/test_a.py",
            "1 error in 1.00s",
        ],
    )
    result = P.read_chunk(0, 1, log, ["tests/test_a.py"], ["pytest"], 1.0)

    assert result.status == "red"
    assert P.aggregate([result]) == 1
    assert [(f.chunk, f.kind, f.nodeid) for f in result.failures] == [
        (0, "error", "tests/test_a.py")
    ]
