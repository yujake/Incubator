# -*- coding: utf-8 -*-
"""把写好的正文编成 PDF：`agentflow.papercompile` + `doc.paper_compile`（批 R72）。

## 这一条判的是什么（旧路退场之后）

业主 2026-10-13 裁定逐字：「paper_package 里那些东西都是古早废案了，我们要智能体写文章」，并选定范围 A（整条 `paper_package` 路退场：一个动作 + 五件工具 + 收工门一格 +
三个模块）。现在只剩一件事：正文由智能体自己写进 `out/paper/main.tex`，框架把它编成 `main.pdf`并留一份回执（`.docstring` 与逐条理由见 `draft/117`）。判据分四组：

1. 三态不许折平：`not_applicable`（还没写正文）/ `unknown`（没引擎、超时、
这一次没编出 PDF）/ `computed`（这一趟拿到 PDF）；
2. 两栏不互相冒充：本机 MiKTeX 会写完 PDF 却以 `0xC0000409` 退出 ⇒ 产物
（`pages` / `pdf_bytes` / `pdf_fresh`）与引擎退出码分开读；
3. 回执是"这份 PDF 是不是盘上这份正文编的"的唯一读数：改了正文不重编 ⇒
`receipt_matches_tex()` 回 `False`（那不是"没编过"，也不是"没查成"）；
4. 失败要带着为什么：引擎自己说的话（stdout / stderr 尾巴）随读数回来 ——
旧路 `G.paper_package` 失败时只回一句"脚本不在盘上"，那一课不随旧路退场而失效（`draft/116` §4）。

夹具（假引擎 + 造正文）只有一处：`tests/paperfixture.py`。它不碰 `main.tex`（真机血案：生成器整份重写正文，把 G 改的那一段抹掉，`draft/37` §1.1）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil

import pytest

import paperfixture as FX
from agentflow import papercompile as PC
from agentflow.tools import build_registry

ALL_ENGINES_MISSING = not any(shutil.which(e) for e in PC.ENGINES)


# ============================================================ 一、三态（模块层）


def test_the_public_helpers_read_what_they_say(tmp_path: pathlib.Path):
    """`package_dir` / `file_digest` / `read_receipt` 三个公开函数各有直接判据。

    为什么单列这一条：发布门的 `coverage` 子门按"这个函数名在 `tests/` 里出现过"读
    "有没有直接测试"（`tools/coverage_zero_test.py` 的口径）—— 少了它，这三个会被读成
    "零直接测试"，于是要么去豁免表里加一行、要么这条门红。直接判它们本身更省事，也更真。
    """
    root = tmp_path / "projects/p1"
    tex = FX.write_paper(root)
    assert PC.package_dir(root) == root / "out" / "paper", PC.package_dir(root)
    assert PC.file_digest(tex) == hashlib.sha256(tex.read_bytes()).hexdigest()
    # 读不到的文件不编哈希（空串就是"读不到"）
    assert PC.file_digest(root / "nope.tex") == ""
    receipt, why = PC.read_receipt(root)
    assert receipt is None and PC.RECEIPT_NAME in why, (receipt, why)


def test_a_project_without_tex_is_not_applicable(tmp_path: pathlib.Path):
    """还没写正文 ⇒ `not_applicable`（合法初态），不是失败、也不是"没查成"。"""
    got = PC.compile_paper(tmp_path / "projects/p1")
    assert got["tri"] == "not_applicable" and got["ok"] is False, got
    assert got["runs"] == 0 and got["exit_codes"] == [], got
    assert "还没有可编的正文" in got["reason"], got["reason"]


def test_a_compile_writes_a_receipt_that_matches_the_tex(tmp_path: pathlib.Path):
    """正控：假引擎编一遍 ⇒ `computed`，回执在盘上且对得上盘上这份正文。"""
    got = FX.compiled_project(tmp_path / "projects/p1")
    assert got["tri"] == "computed" and got["ok"] is True, got
    assert got["pdf_fresh"] is True, got
    assert got["exit_codes"] == [0, 0], got  # 两遍（LaTeX 的交叉引用要跑两遍）
    receipt = json.loads(pathlib.Path(got["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["tex_sha256"] == hashlib.sha256(
        (PC.package_dir(tmp_path / "projects/p1") / PC.TEX_NAME).read_bytes()).hexdigest(), receipt
    assert receipt["written_by"].startswith("agentflow.papercompile"), receipt
    assert PC.receipt_matches_tex(tmp_path / "projects/p1")[0] is True


def test_editing_the_tex_makes_the_pdf_stale(tmp_path: pathlib.Path):
    """改了正文不重编 ⇒ 回执说的还是旧那一份正文（`False`，不是 `None`）。

    这一条是整条退场的落点：收工门那一格判的就是它（"这份 PDF 是盘上这份正文编的吗"）。
    """
    root = tmp_path / "projects/p1"
    FX.compiled_project(root)
    FX.write_paper(root, FX.MINIMAL_TEX + "\nExtra paragraph the PDF does not know about.\n")
    fresh, why = PC.receipt_matches_tex(root)
    assert fresh is False, (fresh, why)
    assert "旧" in why and "重编" in why, why


def test_a_missing_receipt_is_unknown_not_stale(tmp_path: pathlib.Path):
    """回执读不到 ⇒ `None`（判不了）。"没查成"不许折成"漂了"，也不许折成"对得上"。"""
    root = tmp_path / "projects/p1"
    FX.compiled_project(root)
    (PC.package_dir(root) / PC.RECEIPT_NAME).unlink()
    fresh, why = PC.receipt_matches_tex(root)
    assert fresh is None and PC.RECEIPT_NAME in why, (fresh, why)


def test_a_corrupt_receipt_is_unknown(tmp_path: pathlib.Path):
    """回执坏了（不是 JSON）同样判 `None`：坏文件不是"漂了"的证据。"""
    root = tmp_path / "projects/p1"
    FX.compiled_project(root)
    (PC.package_dir(root) / PC.RECEIPT_NAME).write_text("{ 不是 JSON", encoding="utf-8")
    fresh, why = PC.receipt_matches_tex(root)
    assert fresh is None and "读不出来" in why, (fresh, why)


# ============================================================ 二、两栏（产物 / 退出码）


def test_a_nonzero_exit_that_still_wrote_the_pdf_is_computed(tmp_path: pathlib.Path):
    """引擎非 0 退出但写完了 PDF（本机 MiKTeX 的真实形态）⇒ `computed`，两栏都如实带上。

    这就是第二次 T2 的 `exit_codes=[3221226505, 3221226505]` + `pages=3` 那一档：
    判据是产物，不是退出码；但退出码也不许被抹掉。
    """
    root = tmp_path / "projects/p1"
    FX.write_paper(root)
    engine = FX.fake_engine(root / "_engine", exit_code=1, stderr="MiKTeX: post-mortem crash\n")
    with FX.use_engine(engine):
        got = PC.compile_paper(root)
    assert got["tri"] == "computed" and got["ok"] is True, got
    assert got["exit_codes"] == [1, 1], got
    assert got["pdf_fresh"] is True and got["pdf_bytes"], got
    assert "退出码 1" in got["reason"], got["reason"]


def test_an_engine_that_writes_nothing_is_unknown_and_keeps_the_old_pdf(tmp_path: pathlib.Path):
    """引擎这次什么都没产 ⇒ `unknown` + `pdf_fresh=False`。

    盘上那份上一次编的 PDF 不许当成本次读数（旧路的口径含糊处：只看文件在不在）。
    同时不删旧 PDF（编译失败不该顺手毁掉上一份能看的稿子）。
    """
    root = tmp_path / "projects/p1"
    first = FX.compiled_project(root)
    old_pdf = pathlib.Path(first["pdf"])
    assert old_pdf.is_file()
    engine = FX.fake_engine(root / "_engine2", exit_code=2, writes_pdf=False,
                            stdout="", stderr="! LaTeX Error: something is wrong\n")
    with FX.use_engine(engine):
        got = PC.compile_paper(root)
    assert got["tri"] == "unknown" and got["ok"] is False, got
    assert got["pdf_fresh"] is False, got
    assert got["pages"] is None and got["pdf_bytes"] is None, got
    assert old_pdf.is_file(), "失败的那一次不许把上一份 PDF 删掉"


def test_a_missing_engine_is_unknown_not_a_crash(tmp_path: pathlib.Path):
    """引擎名字不存在 ⇒ `unknown`（不是异常逃出去，也不是 `computed`）。"""
    root = tmp_path / "projects/p1"
    FX.write_paper(root)
    with FX.use_engine(root / "_nope" / "no-such-engine"):
        got = PC.compile_paper(root)
    assert got["tri"] == "unknown" and got["ok"] is False, got
    assert got["exit_codes"] == [-1], got
    assert "no-such-engine" in got["reason"] or "FileNotFoundError" in got["reason"], got["reason"]


# ============================================================ 三、失败要带着为什么


def test_the_engine_tail_is_carried_when_the_compile_fails(tmp_path: pathlib.Path):
    """编不过时读数里带着引擎自己说的话（stdout / stderr 尾巴）。

    这一条是旧路那一课的延续：`t3e` 那趟 `G.paper_package` 只回一句"脚本不在盘上"，
    而脚本的 stderr 当时就在手边（`draft/116` §4）。LaTeX 把错误印在 stdout 上
    （`.log` 的转录），所以两栏都留。
    """
    root = tmp_path / "projects/p1"
    FX.write_paper(root)
    engine = FX.fake_engine(root / "_engine", exit_code=1, writes_pdf=False,
                            stdout="! Undefined control sequence.\n", stderr="engine: giving up\n")
    with FX.use_engine(engine):
        got = PC.compile_paper(root)
    assert got["tri"] == "unknown", got
    assert "Undefined control sequence" in got["engine_stdout_tail"], got["engine_stdout_tail"]
    assert "giving up" in got["engine_stderr_tail"], got["engine_stderr_tail"]


def test_the_receipt_on_disk_carries_the_engine_tail(tmp_path: pathlib.Path):
    """回执也留一份引擎的话：事后读盘的人（H / 收工门 / 人）不必重跑才能知道为什么。"""
    root = tmp_path / "projects/p1"
    FX.write_paper(root)
    engine = FX.fake_engine(root / "_engine", exit_code=3, writes_pdf=False,
                            stderr="engine: out of memory\n")
    with FX.use_engine(engine):
        PC.compile_paper(root)
    receipt = json.loads((PC.package_dir(root) / PC.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert "out of memory" in receipt["stderr_tail"], receipt
    assert receipt["pdf_fresh"] is False and receipt["exit_codes"] == [3, 3], receipt


# ============================================================ 四、工具面与权限面


def _registry(tmp_path: pathlib.Path):
    return build_registry(workspace_root=str(tmp_path)).registry


def test_only_g_gets_the_compile_tool(tmp_path: pathlib.Path):
    """权限面：只有 G 拿得到 `doc.paper_compile`（写盘 + 起子进程那一档）；M / H 没有。"""
    reg = _registry(tmp_path)
    assert "doc.paper_compile" in [s.name for s in reg.for_role("G")], "G 的工具面上没有它"
    for role in ("M", "H"):
        names = [s.name for s in reg.for_role(role)]
        assert "doc.paper_compile" not in names, f"{role} 不该拿到编译工具：{names}"
    spec = reg.get("doc.paper_compile")
    assert spec.side_effect == "write_local" and spec.declared_external == "exec", (
        spec.side_effect, spec.declared_external)
    # 旧路的四条工具一个都不许残留在任何角色的工具面上
    gone = {"doc.paper_render", "doc.paper_build", "doc.paper_anchor", "doc.paper_state"}
    for role in ("G", "H", "M"):
        assert not (gone & {s.name for s in reg.for_role(role)}), role


def test_the_tool_separates_no_source_from_compile_failed(tmp_path: pathlib.Path):
    """工具层三态：没正文 ⇒ `paper_no_source`；编不出来 ⇒ `paper_compile_failed`。"""
    reg = _registry(tmp_path)
    project = tmp_path / "projects/p1"
    project.mkdir(parents=True)
    res = reg.call("doc.paper_compile", role="G", project="projects/p1")
    assert not res.ok and res.meta.get("kind") == "paper_no_source", (res.error, res.meta)
    assert res.meta.get("tri") == "not_applicable", res.meta

    FX.write_paper(project)
    engine = FX.fake_engine(project / "_engine", exit_code=1, writes_pdf=False,
                            stderr="boom\n")
    with FX.use_engine(engine):
        res2 = reg.call("doc.paper_compile", role="G", project="projects/p1")
    assert not res2.ok and res2.meta.get("kind") == "paper_compile_failed", (res2.error, res2.meta)
    assert "boom" in str(res2.meta.get("engine_stderr_tail")), res2.meta


def test_the_tool_compiles_a_written_paper(tmp_path: pathlib.Path):
    """工具层正控：正文写好、假引擎在 ⇒ `ok=True`，回执落盘且对得上。"""
    reg = _registry(tmp_path)
    project = tmp_path / "projects/p1"
    FX.write_paper(project)
    engine = FX.fake_engine(project / "_engine")
    with FX.use_engine(engine):
        res = reg.call("doc.paper_compile", role="G", project="projects/p1")
    assert res.ok, (res.error, res.meta)
    assert res.data["tri"] == "computed" and res.data["pdf_fresh"] is True, res.data
    assert PC.receipt_matches_tex(project)[0] is True


def test_the_tool_refuses_a_project_outside_the_workspace(tmp_path: pathlib.Path):
    """越界的 `project` 一律拒（工具层要起子进程、还把 cwd 设成它 ⇒ 不许放宽）。"""
    reg = _registry(tmp_path)
    for bad in ("../elsewhere", str(tmp_path), "projects/not-on-disk"):
        res = reg.call("doc.paper_compile", role="G", project=bad)
        assert not res.ok and res.meta.get("kind") == "bad_project", (bad, res.error, res.meta)


# ============================================================ 五、真引擎（有就编一遍）


@pytest.mark.skipif(ALL_ENGINES_MISSING, reason="本机 PATH 上没有 LaTeX 引擎")
def test_a_real_engine_compiles_the_minimal_paper(tmp_path: pathlib.Path,
                                                  monkeypatch: pytest.MonkeyPatch):
    """真引擎冒烟：装了 LaTeX 就真编一份出来（假引擎那一组判不了"框架内置编译真的能跑"）。

    页数 >= 1 是产物的读数；退出码单列（MiKTeX 收尾崩溃那一档在本机真实存在）。
    """
    monkeypatch.delenv(PC.ENGINE_ENV, raising=False)
    root = tmp_path / "projects/p1"
    FX.write_paper(root)
    got = PC.compile_paper(root, timeout_sec=300.0)
    assert got["tri"] == "computed" and got["ok"] is True, got
    assert (got["pages"] or 0) >= 1, got
    assert PC.receipt_matches_tex(root)[0] is True, got
