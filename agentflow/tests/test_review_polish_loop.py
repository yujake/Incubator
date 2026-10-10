# -*- coding: utf-8 -*-
"""审稿场景的动作半边：把论文读进来、定点改一处、让包跟上（锚回 `consistent`）。

## 为什么单独一条

§17.3 的场景一是"审核这份未发表的论文并 polish 它"。前面几节验的是"审"
（内容级判据 §24、矛盾与错文献 §23）；这一节验"polish"——论文真的被改了，
而且包跟着回来了。这是 P0 那一刀（`fs.edit` + 预算 + 观测窗口）存在的唯一理由。

两条判据里的"证据"都不是 sha 变了 / 页数对得上（§17.3 逐字禁止拿它们当通过），
而是内容级的：改动的那一段文字真的进了正文、其余正文逐字未动、
而锚的 `files` 维度（把正文算在内）回到 `consistent`。

## 夹具刻意做成"真洁净室"的形状

假渲染脚本只写锚、不碰 `main.tex` —— 真机那一轮的血案正是"生成器把 `main.tex`
整份重写"，于是 G 改的正文被渲染一把抹掉（`draft/37` §1.1）。所以这一节的负控里
专门有一条：渲染之后那处改动必须还在。
"""
from __future__ import annotations

import json
import pathlib

from agentflow import renderanchor as RA
from agentflow.store import Store
from agentflow.tools import build_registry

BEFORE = "\\date{2026-01-01}\nTheorem 1.5 states that the walk converges.\nbody\n"
AFTER_OLD = "Theorem 1.5 states that the walk converges."
AFTER_NEW = "Theorem 1.5 states that the walk converges in distribution."


def _scripts(root: pathlib.Path) -> None:
    """两个假脚本：渲染只写锚（不碰正文），编译只写回执。"""
    src = str(pathlib.Path(RA.__file__).resolve().parents[1])
    code = root / "code"
    code.mkdir(parents=True, exist_ok=True)
    (code / "make_paper.py").write_text(
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {src!r})\n"
        "from agentflow import renderanchor as RA\n"
        "from agentflow.store import Store\n"
        "root = pathlib.Path('.')\n"
        "out = root / 'out' / 'paper'\n"
        "st = Store(root)\n"
        "# 只写锚：**不碰 main.tex**（洁净室渲染器的契约，见本文件 docstring）\n"
        "(out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)),"
        " encoding='utf-8')\n"
        "print('REPRO_RESULT: ' + json.dumps({'claims': 24}))\n",
        encoding="utf-8")
    (code / "compile_paper.py").write_text(
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {src!r})\n"
        "from agentflow import renderanchor as RA\n"
        "out = pathlib.Path('out/paper')\n"
        "(out / 'main.pdf').write_bytes(b'%PDF-1.4 fake')\n"
        "rec = RA.build_receipt(out, tex_sha256=RA.file_digest(out / 'main.tex'), pages=21,"
        " markers_missing=[], pdf_bytes=13, compiler_exit_codes=[0])\n"
        "(out / RA.RECEIPT_NAME).write_text(json.dumps(rec), encoding='utf-8')\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': True, 'pages': 21,"
        " 'markers_missing': [], 'pdf': 'main.pdf', 'pdf_bytes': 13, 'pdf_header': '%PDF-',"
        " 'text_extractor': 'stub', 'runs': [], 'compiler_exit_codes': [0],"
        " 'log_tail': 'stub', 'note': '夹具'}))\n",
        encoding="utf-8")


def _project(tmp_path: pathlib.Path):
    """一个"包与台账一致"的论文项目 + 角色面上的工具注册表。"""
    out = tmp_path / "out" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    st = Store(tmp_path)
    st.init(force=True)
    _scripts(tmp_path)
    (out / "main.tex").write_text(BEFORE, encoding="utf-8", newline="\n")
    (out / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    (out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)), encoding="utf-8")
    (out / RA.RECEIPT_NAME).write_text(json.dumps(RA.build_receipt(
        out, tex_sha256=RA.file_digest(out / "main.tex"), pages=21, markers_missing=[],
        pdf_bytes=13, compiler_exit_codes=[0])), encoding="utf-8")
    reg = build_registry(store=st, workspace_root=str(tmp_path)).registry
    return st, reg, out


def _verdict(root: pathlib.Path, st: Store) -> str:
    return str(RA.check_package(root, store=st).get("verdict"))


def test_the_edit_lands_and_the_package_catches_up(tmp_path):
    """polish 的完整回路：定点改一处 ⇒ 锚漂移 ⇒ 重渲染重编译 ⇒ 锚回 consistent，
    而那处改动还在、其余正文逐字未动。"""
    st, reg, out = _project(tmp_path)
    assert _verdict(tmp_path, st) == "consistent", "夹具前提：起手是封好的包"
    before = (out / "main.tex").read_bytes()

    # 读后写那一闸（业主 2026-10-10 裁定 9甲）：定点替换要求先读过目标 ——
    # 夹具照真实循环同一条纪律（先读、再改）；本用例判的是"改完锚漂移 → 重渲染回 consistent"。
    assert reg.call("fs.read", role="G", path="out/paper/main.tex").ok, "夹具前提：先读一次"
    res = reg.call("fs.edit", role="G", path="out/paper/main.tex",
                   old_string=AFTER_OLD, new_string=AFTER_NEW,
                   note="把「收敛」补成「依分布收敛」（原文缺了这句话）")
    assert res.ok, (res.error, res.meta)
    after = (out / "main.tex").read_bytes()
    assert len(after) - len(before) == len(AFTER_NEW) - len(AFTER_OLD), "只该多出改动的那些字节"
    assert AFTER_NEW.encode("utf-8") in after and AFTER_OLD.encode("utf-8") not in after

    # 改完不渲染 ⇒ 锚必须报漂移（正文也是 `files` 维度的一部分）
    assert _verdict(tmp_path, st) == "drifted", RA.check_package(tmp_path, store=st)

    # 让包跟上：重渲染 + 重编译，两条都走 G 被点名的那两个动作
    # （`project` 要工作区相对路径：这里工作区根就是项目根 ⇒ `.`）
    rendered = reg.call("doc.paper_render", role="G", project=".")
    assert rendered.ok, (rendered.error, rendered.meta)
    compiled = reg.call("doc.paper_compile", role="G", project=".")
    assert compiled.ok, (compiled.error, compiled.meta)

    # 内容级判据（不是 sha、不是页数）：改动还在，其余正文逐字未动
    final = (out / "main.tex").read_text(encoding="utf-8")
    assert AFTER_NEW in final, "渲染把 G 改的那一段抹掉了（真机血案：生成器整份重写正文）"
    assert final.replace(AFTER_NEW, AFTER_OLD) == BEFORE, "除那处改动外，正文必须逐字未动"
    assert _verdict(tmp_path, st) == "consistent", RA.check_package(tmp_path, store=st)


def test_a_stale_sha_edit_on_the_paper_is_refused(tmp_path):
    """负控（R2 的第二条负控，落到论文上）：文件被外部改过之后，拿着旧 sha 的定点改必须被拒。

    裁定 9甲（读后写）之后这一条有两道闸，判据要接受先响的那一道：
    先读一次（记下观察版本）→ 外部改过 → 定点改 ⇒ 观察版本已经不符 ⇒ `stale_version` 先响；
    `sha256` 那条仍然留着，给"读过之后没变、但调用方自己拿的是更早那一版"的场合。
    两道都算"被拒"，所以断言收两者的并集，并钉住"盘上那处外部改动还在"。
    """
    st, reg, out = _project(tmp_path)
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
