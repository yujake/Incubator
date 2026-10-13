# -*- coding: utf-8 -*-
"""审稿场景的动作半边：把正文读进来、定点改一处、让 PDF 跟上（回执重新对上）。

## 为什么单独一条

§17.3 的场景一是"审核这份未发表的论文并 polish 它"。前面几节验的是"审"
（内容级判据 §24、矛盾与错文献 §23）；这一节验"polish" —— 正文真的被改了，
而且盘上那份 PDF 跟着回来了。这是 P0 那一刀（`fs.edit` + 预算 + 观测窗口）存在的唯一理由。

两条判据里的"证据"都不是 sha 变了 / 页数对得上（§17.3 逐字禁止拿它们当通过），
而是内容级的：改动的那一段文字真的进了正文、其余正文逐字未动；而"跟上"那一栏
读的是**编译回执**（这份 PDF 是不是盘上这份正文编的）。

## 2026-10-13：这一条换了对象（业主裁定，`draft/117`）

旧口径：项目自带一对渲染/编译脚本，"改完要重渲染 → 重编译 → 让渲染锚回到
`consistent`"。业主 2026-10-13 裁定逐字：「paper_package 里那些东西都是古早废案了，
我们要智能体写文章」⇒ 那套脚本与渲染锚整条退场，正文由 G 自己写（`fs.write`），
框架只负责把它编成 PDF 并写回执。判据的形状一字未改：**改一处 ⇒ 盘上产物过期 ⇒
让它跟上 ⇒ 改动仍在、其余逐字未动**；变的是"过期"与"跟上"由谁读数
（`papercompile.receipt_matches_tex` / 收工门那一格 `paper`）。

旧文件里那条"真洁净室"的负控（渲染器整份重写正文、把 G 改的那一段抹掉，`draft/37` §1.1）
在这里以更强的方式保留：**框架的编译本来就不该碰正文** —— 所以"改动还在、其余逐字未动"
这一对断言现在同时在守两件事（编辑落对了、编译没有动稿子）。
"""
from __future__ import annotations

import pathlib

import paperfixture as FX

from agentflow import closing as CL
from agentflow import papercompile as PC
from agentflow.store import Store
from agentflow.tools import build_registry

BEFORE = "\\date{2026-01-01}\nTheorem 1.5 states that the walk converges.\nbody\n"
AFTER_OLD = "Theorem 1.5 states that the walk converges."
AFTER_NEW = "Theorem 1.5 states that the walk converges in distribution."


def _project(tmp_path: pathlib.Path, monkeypatch) -> tuple[Store, object, pathlib.Path]:
    """一个"正文与回执对得上"的项目 + 角色面上的工具注册表。

    假引擎经 `papercompile.ENGINE_ENV` 注入（`monkeypatch` 在用例结束时还原）——
    判据不该依赖"这台机器恰好在 PATH 上装了 LaTeX"。
    """
    out = tmp_path / "out" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    st = Store(tmp_path)
    st.init(force=True)
    engine = FX.fake_engine(tmp_path / "_engine")
    monkeypatch.setenv(PC.ENGINE_ENV, str(engine))
    FX.write_paper(tmp_path, BEFORE)
    assert PC.compile_paper(tmp_path)["tri"] == "computed", "夹具前提：起手能编出 PDF"
    reg = build_registry(store=st, workspace_root=str(tmp_path)).registry
    return st, reg, out


def test_the_edit_lands_and_the_pdf_catches_up(tmp_path: pathlib.Path, monkeypatch) -> None:
    """polish 的完整回路：定点改一处 ⇒ 盘上 PDF 过期 ⇒ 重编 ⇒ 回执重新对上，
    而那处改动还在、其余正文逐字未动。"""
    st, reg, out = _project(tmp_path, monkeypatch)
    assert PC.receipt_matches_tex(tmp_path)[0] is True, "夹具前提：起手 PDF 与正文对得上"
    before = (out / "main.tex").read_bytes()

    # 读后写那一闸（业主 2026-10-10 裁定 9甲）：定点替换要求先读过目标 ——
    # 夹具照真实循环同一条纪律（先读、再改）；本用例判的是"改完 PDF 过期 → 重编后对上"。
    assert reg.call("fs.read", role="G", path="out/paper/main.tex").ok, "夹具前提：先读一次"
    res = reg.call("fs.edit", role="G", path="out/paper/main.tex",
                   old_string=AFTER_OLD, new_string=AFTER_NEW,
                   note="把「收敛」补成「依分布收敛」（原文缺了这句话）")
    assert res.ok, (res.error, res.meta)
    after = (out / "main.tex").read_bytes()
    assert len(after) - len(before) == len(AFTER_NEW) - len(AFTER_OLD), "只该多出改动的那些字节"
    assert AFTER_NEW.encode("utf-8") in after and AFTER_OLD.encode("utf-8") not in after

    # 改完不重编 ⇒ 回执说的还是旧那一份正文
    assert PC.receipt_matches_tex(tmp_path)[0] is False, PC.receipt_matches_tex(tmp_path)
    # 而且**收工门那一格**自己说得出来（不是只有模块函数知道）：`fail` + `paper_pdf_is_stale`
    rep = CL.check_closing(st, project_dir=".", report_path="")
    assert rep.status["paper"] == "fail", rep.to_dict()
    assert [f.code for f in rep.findings if f.check == "paper"] == ["paper_pdf_is_stale"], \
        [f.to_dict() for f in rep.findings]

    # 让 PDF 跟上：正文是 G 写的，编译也只有 G 拿得到（`doc.paper_compile`）
    compiled = reg.call("doc.paper_compile", role="G", project=".")
    assert compiled.ok, (compiled.error, compiled.meta)
    assert compiled.data["tri"] == "computed", compiled.data

    # 内容级判据（不是 sha、不是页数）：改动还在，其余正文逐字未动
    final = (out / "main.tex").read_text(encoding="utf-8")
    assert AFTER_NEW in final, "编译把 G 改的那一段抹掉了（真机血案：生成器整份重写正文）"
    assert final.replace(AFTER_NEW, AFTER_OLD) == BEFORE, "除那处改动外，正文必须逐字未动"
    assert PC.receipt_matches_tex(tmp_path)[0] is True, PC.receipt_matches_tex(tmp_path)

    # 补一刀：重编之后那一格也回到 pass（"过期"与"对上"是同一格的两种读数）
    rep2 = CL.check_closing(st, project_dir=".", report_path="")
    assert rep2.status["paper"] == "pass", rep2.to_dict()


def test_a_stale_sha_edit_on_the_paper_is_refused(tmp_path: pathlib.Path,
                                                 monkeypatch) -> None:
    """负控（R2 的第二条负控，落到正文上）：文件被外部改过之后，拿着旧 sha 的定点改必须被拒。

    裁定 9甲（读后写）之后这一条有两道闸，判据要接受先响的那一道：
    先读一次（记下观察版本）→ 外部改过 → 定点改 ⇒ 观察版本已经不符 ⇒ `stale_version` 先响；
    `sha256` 那条仍然留着，给"读过之后没变、但调用方自己拿的是更早那一版"的场合。
    两道都算"被拒"，所以断言收两者的并集，并钉住"盘上那处外部改动还在"。
    """
    st, reg, out = _project(tmp_path, monkeypatch)  # noqa: F841 —— st 只用来装配注册表
    assert reg.call("fs.read", role="G", path="out/paper/main.tex").ok, "夹具前提：先读一次"
    old_sha = reg.call("fs.stat", role="G", path="out/paper/main.tex").data["sha256"]
    # 外部有人改了正文（不是 G 改的）
    (out / "main.tex").write_text(BEFORE.replace("body", "someone else changed it"),
                                  encoding="utf-8", newline="\n")
    res = reg.call("fs.edit", role="G", path="out/paper/main.tex",
                   old_string=AFTER_OLD, new_string=AFTER_NEW,
                   sha256=str(old_sha), note="基于我读到的那一版改")
    assert not res.ok, res
    assert res.meta.get("kind") in ("stale_version", "sha_mismatch"), (res.error, res.meta)
    assert "someone else changed it" in (out / "main.tex").read_text(encoding="utf-8"), (
        "被拒之后不许动文件")
