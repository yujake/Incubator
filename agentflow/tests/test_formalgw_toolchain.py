"""`formalgw` 的工具链两问（`G-13`）：`mathlib_revision` 与 `mathlib_imports`。

## 为什么单独一个文件

`tools/coverage_zero_test.py` 的等级 2（判据/决策）在收官整批里报出这两个函数零测试
（`formalgw.py` 的 `mathlib_revision` L387、`mathlib_imports` L453）⇒ 门红了。
补测试是正确处置（不是把它们加进 `_EXONERATED` —— 那是把门改宽）。

## 这两个函数各自要守住什么

- `mathlib_revision`："未核实" 与 "版本不符" 是两件事。它返回
  `{commit, tag, source, reason}`，`commit` 为空时有三种完全不同的原因
  （戳文件没写 / 没有 git 元数据 / 读了但读不出哈希），所以 `source` 与 `reason`
  必须能把它们分开。
- `mathlib_imports`："没查成" 与 "import 失败" 是两件事（`lake` 不在 PATH ⇒
  `checked=False` + `exit_code=None`）。另外它不许在工程里留下探针文件
  （写临时文件、跑完即删）。

每条断言都配了会红的负控（"没有戳文件时不许报 commit"、"没有 lake 时不许说 import 失败"）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import formalgw as FG

_FULL = "a" * 40


def _write_stamp(root: pathlib.Path, text: str) -> pathlib.Path:
    """把戳文件写到 `root / MATHLIB_REV_STAMP`，并建出它的父目录。

    `MATHLIB_REV_STAMP` 是带子目录的相对路径（`.lake/agentflow-mathlib-rev`），
    第一版我直接 `root / STAMP` 就 `write_text` ⇒ `FileNotFoundError`（父目录不存在）。
    记在这里，免得下一个人再踩：用常量拼路径时先建父目录。
    """
    p = root / FG.MATHLIB_REV_STAMP
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ============================================================ mathlib_revision


def test_revision_reads_the_stamp_file(tmp_path: pathlib.Path) -> None:
    """正控：戳文件首行是 40 位 commit ⇒ 报它，且 `reason` 为空。"""
    stamp = _write_stamp(tmp_path, _FULL + "\n")
    assert stamp.is_file()
    out = FG.mathlib_revision(tmp_path)
    assert out["commit"] == _FULL
    assert out["source"] == "stamp"
    assert out["reason"] == ""


def test_revision_separates_unverified_from_mismatch(tmp_path: pathlib.Path) -> None:
    """核心：三种"读不出 commit"必须可分（`source` + 非空 `reason`），不许折叠成"没有 commit"。

    负控（同一夹具、只改一件事）：戳文件不存在 ⇒ `source` 必须是 `none`、且 `reason`
    必须说"既没有戳也没有 .git"。两条断言成对 —— 只写后一条的话，一个"永远返回 none"
    的实现也能通过。
    """
    # (a) 戳文件存在但首行不是 40 位哈希
    stamp_dir = tmp_path / "bad-stamp"
    stamp_dir.mkdir()
    _write_stamp(stamp_dir, "not-a-hash\n")
    bad = FG.mathlib_revision(stamp_dir)
    assert bad["commit"] == "" and bad["source"] == "stamp"
    assert "不是 40 位 commit" in bad["reason"], bad

    # (b) 戳与 .git 都没有
    empty = tmp_path / "empty"
    empty.mkdir()
    none_out = FG.mathlib_revision(empty)
    assert none_out["commit"] == "" and none_out["source"] == "none"
    assert ".git" in none_out["reason"], none_out
    assert bad["source"] != none_out["source"], "两种成因必须可分"


def test_revision_reads_git_head_directly(tmp_path: pathlib.Path) -> None:
    """`.git/HEAD` 直接是 40 位哈希时走 git 来源（与 stamp 路径互不干扰）。"""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(_FULL.upper() + "\n", encoding="utf-8")
    out = FG.mathlib_revision(tmp_path)
    assert out["source"] == "git"
    assert out["commit"] == _FULL  # 统一小写
    assert out["reason"] == ""


def test_revision_reports_an_unreadable_ref(tmp_path: pathlib.Path) -> None:
    """`.git/HEAD` 指向一个 ref、而那个 ref 文件不存在 ⇒ 仍要说清"读了但读不出"，不是"没有 commit"。"""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    out = FG.mathlib_revision(tmp_path)
    assert out["commit"] == "" and out["source"] == "git"
    assert "读不到" in out["reason"], out


# ============================================================ mathlib_imports


def test_imports_refuses_a_non_directory(tmp_path: pathlib.Path) -> None:
    """非目录 ⇒ 没做试跑（`checked=False`），而不是"import 失败"。"""
    missing = tmp_path / "nope"
    out = FG.mathlib_imports(missing)
    assert out["checked"] is False
    assert out["imports"] is False
    assert out["exit_code"] is None
    assert "不是目录" in out["reason"], out


def test_imports_without_lake_is_not_checked(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """负控：`lake` 不在 PATH ⇒ 必须报"没查成"，不许说成"Mathlib 不可用"。

    为什么必须 monkeypatch `shutil.which`：本机装没装 lake 是会变的环境事实，
    而这条判据要说的是"没有工具时它怎么回答" —— 把环境事实留给断言会让用例随机器而红或绿。
    """
    monkeypatch.setattr(FG.shutil, "which", lambda _name: None)
    out = FG.mathlib_imports(tmp_path)
    assert out["checked"] is False and out["exit_code"] is None
    assert "lake" in out["reason"], out
    assert "不可用" not in out["reason"] or "不是" in out["reason"], out


def test_imports_runs_the_probe_and_leaves_nothing_behind(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """正控：有 lake ⇒ 走 `lake env lean <checkdir>/…lean`，且跑完把探针删掉。

    "不留东西"是本函数明确承诺的性质（docstring 逐字："这次试跑不往工程里留下任何东西"），
    所以要断言 `checkdir` 里没有探针文件 —— 这是"清理真的发生了"的判据，
    不是"目录存在"这种恒真的东西。
    """
    fake_lake = tmp_path / ("lake.exe" if __import__("os").name == "nt" else "lake")
    fake_lake.write_text("", encoding="utf-8")
    monkeypatch.setattr(FG.shutil, "which", lambda _name: str(fake_lake))

    seen: dict[str, object] = {}

    def fake_probe(cmd, *, cwd, timeout_sec):  # noqa: ANN001, ANN202 —— 与真实签名同形
        seen["cmd"] = list(cmd)
        seen["cwd"] = cwd
        # 探针此刻必须存在（否则这个桩就是在为"根本没写文件"背书）
        probe = pathlib.Path(cmd[-1])
        seen["probe_existed"] = probe.is_file()
        seen["probe_text"] = probe.read_text(encoding="utf-8") if probe.is_file() else ""
        return {"checked": True, "imports": True, "exit_code": 0, "command": " ".join(cmd),
                "output": "Nat.add_comm", "reason": ""}

    monkeypatch.setattr(FG, "_run_import_probe", fake_probe)
    root = tmp_path / "mathlib"
    root.mkdir()
    out = FG.mathlib_imports(root, timeout_sec=5)

    assert out["imports"] is True
    assert seen["probe_existed"] is True, "探针文件没被写出来 ⇒ 桩替一个空实现背了书"
    assert seen["probe_text"] == FG.IMPORT_PROBE_SOURCE
    assert seen["cwd"] == str(root)
    assert list(seen["cmd"])[1:3] == ["env", "lean"], seen["cmd"]  # type: ignore[arg-type]
    leftovers = list((root / "checkdir").iterdir())
    assert leftovers == [], f"跑完不许在工程里留文件：{leftovers}"


def test_imports_reports_an_unwritable_checkdir(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """负控：`checkdir` 建不了（被一个同名文件占着）⇒ 报"没查成"，且不去调探针。"""
    fake_lake = tmp_path / "lake"
    fake_lake.write_text("", encoding="utf-8")
    monkeypatch.setattr(FG.shutil, "which", lambda _name: str(fake_lake))

    root = tmp_path / "mathlib"
    root.mkdir()
    (root / "checkdir").write_text("我是一个文件，不是目录", encoding="utf-8")

    called = {"n": 0}

    def must_not_run(*_a, **_kw):  # noqa: ANN002, ANN003, ANN202
        called["n"] += 1
        raise AssertionError("建不了目录时不该去跑探针")

    monkeypatch.setattr(FG, "_run_import_probe", must_not_run)
    out = FG.mathlib_imports(root)
    assert out["checked"] is False and out["exit_code"] is None
    assert "建不了" in out["reason"], out
    assert called["n"] == 0
