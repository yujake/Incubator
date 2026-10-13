# -*- coding: utf-8 -*-
"""审阅型项目的**正常创建路径**（业主 2026-10-13：「打通正常的创建项目逻辑」）。

背景（为什么要单列这一条）：`create_project` 只铺工作区骨架，**没有**任何受支持的路径把
"那篇外部论文"放进项目 —— 于是 T1 的夹具当年是手搓的，而 2026-10-13 我为了让 T1 跑起来
手抄了一份夹具再 `init --force`（绕过"非空目录里不许凭空建 data/"那道守卫），
建出来的文件夹没有项目卡、`project list` 与产物归属都认不出它。

这一组判据钉住新那条路：`projects.create_review_project(root, paper=…)` = 走守卫建骨架
+ 铺只读基线（`source/`）+ 铺可改副本（`out/paper/main.tex`）。

口径三条（判据逐条对着它们）：
① 只读基线**不许被覆盖**（它是"改没改"的分母）；② 只给 PDF 时**不替它编正文**
（那是 G 的活，如实说"还没写"）；③ 外来目录在 `resolve` 那一层就被拒（不靠 `force` 绕）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import projects as P


def _paper(tmp: pathlib.Path, *, tex: bool = True) -> pathlib.Path:
    pdf = tmp / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake\n")
    if tex:
        (tmp / "paper.tex").write_text("\\documentclass{article}\n\\begin{document}\n"
                                       "Theorem 1.\n\\end{document}\n", encoding="utf-8")
    return pdf


def test_the_normal_path_builds_a_project_and_seeds_the_paper(tmp_path: pathlib.Path):
    """正控：建出来的是**认得出来的项目**（标记 + 项目卡），而且那篇论文铺好了。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    paper = _paper(tmp_path)
    res = P.create_review_project(ws, paper=paper, name="p-t1")
    proj = pathlib.Path(res["project"]["path"])
    assert (proj / ".agentflow-workspace").is_file(), "没有工作区标记 ⇒ classify 认不出它"
    assert (proj / "project.json").is_file(), "没有项目卡 ⇒ project list / 产物归属接不上"
    assert (proj / "data").is_dir(), "骨架没铺（data/）"
    seeded = res["seeded"]
    assert seeded["source"] == ["source/main.pdf", "source/main.tex"], seeded
    assert seeded["manuscript"] == "out/paper/main.tex", seeded
    base = (proj / "source" / "main.tex").read_text(encoding="utf-8")
    man = (proj / "out" / "paper" / "main.tex").read_text(encoding="utf-8")
    assert man == base, "可改正文必须是基线的逐字副本（起手一份、不是空的）"


def test_the_baseline_is_never_overwritten_by_a_second_seed(tmp_path: pathlib.Path):
    """负控（口径①）：只读基线已存在 ⇒ 拒绝，不静默覆盖。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    res = P.create_review_project(ws, paper=_paper(tmp_path), name="p-t1")
    proj = pathlib.Path(res["project"]["path"])
    (proj / "source" / "main.tex").write_text("改过的基线\n", encoding="utf-8")
    with pytest.raises(P.ProjectExists, match="不覆盖"):
        P.seed_source_paper(proj, paper=tmp_path / "paper.pdf")
    assert (proj / "source" / "main.tex").read_text(encoding="utf-8") == "改过的基线\n"


def test_a_pdf_without_a_tex_seeds_only_the_baseline(tmp_path: pathlib.Path):
    """口径②（三态）：只给 PDF ⇒ 只铺基线，并如实说"可改正文还没写"——不替它编。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    res = P.create_review_project(ws, paper=_paper(tmp_path, tex=False), name="p-t1")
    seeded = res["seeded"]
    assert seeded["source"] == ["source/main.pdf"], seeded
    assert seeded["manuscript"] == "", seeded
    assert "G 自己写" in seeded["note"], seeded["note"]


def test_a_user_made_folder_with_loose_files_is_adopted_not_refused(tmp_path: pathlib.Path):
    """口径③（业主 2026-10-13 更正）：用户自己在 `projects/` 里建文件夹、丢几个文件进去 ——
    **这是正常用法**，系统要收编它：原有文件一个字节都不动，且逐条记进项目卡（`user_files`）。

    改前的口径（`resolve(start="cold")` 一律拒绝非空的外来目录）正是逼出"手抄夹具 +
    `init --force`"的那条路 —— 守卫本身仍留着（`allow_nonempty=False` / `start="cold"`），
    但**不再是默认**。
    """
    ws = tmp_path / "ws"
    proj = ws / "my-review"
    proj.mkdir(parents=True)
    _paper(tmp_path)                       # 论文放在 tmp_path，稍后由用户自己丢进去
    (proj / "论文.pdf").write_bytes(b"%PDF-1.4 user dropped this\n")
    (proj / "我的笔记.txt").write_text("别动我\n", encoding="utf-8")
    res = P.adopt_project(ws, name="my-review")
    assert sorted(res["adopted"]) == ["我的笔记.txt", "论文.pdf"], res
    assert (proj / "我的笔记.txt").read_text(encoding="utf-8") == "别动我\n", "用户的文件不许被改"
    assert (proj / "论文.pdf").is_file(), "用户丢进来的论文不许被删/被搬"
    assert (proj / "data").is_dir() and (proj / "project.json").is_file(), "骨架要铺上"
    names = [u["name"] for u in res["card"].get("user_files", [])]
    assert names == ["我的笔记.txt", "论文.pdf"], names
    # 严格口径仍然可用（给"我要一个干净落点"的调用方），但只在那时拒
    Proj2 = ws / "another"
    Proj2.mkdir()
    (Proj2 / "x.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises((P.ProjectExists, P.ProjectNotAWorkspace, ValueError)):
        P.resolve(ws, "another", start="cold")
    assert (Proj2 / "x.txt").is_file(), "被拒之后不许动别人的文件"
    assert not (Proj2 / "data").exists(), "被拒之后不许凭空建 data/"
