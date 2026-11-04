# -*- coding: utf-8 -*-
"""判据：产出面的两个"换个名字/换个落点就绕过"的口子。

## 真机读数（2026-11-04 `projects/paper-rewrite-big`，只读）

- F 把攻坚证明稿写进 `notes/F-conj000000-proof.md`（14,376 B）—— 文件名不以
  `f-proof-` 开头，`fs` 的保留表（`prefix:f-proof-`）整条失效；
- G 的论文对应表三份（`out/paper/MAPPING.json` / `MAPPING.md` /
  `mapping-appendix.tex`）由 `doc.write_mapping` 渲染（`papermapping.write_package`
  是唯一写口），而 `fs.write` 对它们是放行的 —— "手写第二份"在盘上能成功。

## 这一份钉的三条

| 判据 | 造什么 | 期望 |
|---|---|---|
| a | F 用 `fs.write` 写 `notes/F-conj000000-proof.md` / `notes/x-proof.md` | 拒 `reserved_framework_artifact`、零写入 |
| b | G 用 `fs.write` 写 `out/paper/MAPPING.json` / `MAPPING.md` / `mapping-appendix.tex` | 拒 `reserved_framework_artifact`、零写入 |
| c | 正控：F 写 `notes/x.md`、G 写 `out/paper/main.tex` | 放行（保留表不许扩成"谁都不许写"） |
| d | 反真空：框架自己的写口 `papermapping.write_package` 仍能落那三份 | 三份都在盘上（fs 闸只管 `fs.*`，不挡渲染器） |

`fs_tools.py` 里那张表是权限面（它的注释自己写明"合入前需要人逐行走查"）；
这一份把"收紧"的两行逐条钉成判据，改宽它们会立刻红。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import papermapping as PM
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry

KIND = "reserved_framework_artifact"


def _ws(path: pathlib.Path) -> tuple[pathlib.Path, object]:
    root = path / "ws"
    store = Store(root)
    store.init()
    return root, build_registry(store=store, workspace_root=root).registry


def _call(reg, role: str, tool: str, **params):
    with calling_as("t-probe", role):
        return reg.call(tool, role=role, **params)


# ============================================================ a F 的证明稿别名
def test_a_f_cannot_hand_write_a_proof_under_another_name(tmp_path):
    """a：`notes/F-conj000000-proof.md` 是攻坚稿的真机名字 —— 换名不许绕过保留表。"""
    root, reg = _ws(tmp_path)
    for rel in ("notes/F-conj000000-proof.md", "notes/x-proof.md",
                "reports/f-proof-plan-000000.md"):
        res = _call(reg, "F", "fs.write", path=rel, content="# 手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


# ============================================================ b G 的对应表三份
def test_b_g_cannot_hand_write_the_mapping_files(tmp_path):
    """b：论文对应表三份由 `doc.write_mapping` 渲染 ⇒ `fs.write` 一律拒。"""
    root, reg = _ws(tmp_path)
    for rel in ("out/paper/MAPPING.json", "out/paper/MAPPING.md",
                "out/paper/mapping-appendix.tex"):
        res = _call(reg, "G", "fs.write", path=rel, content="手写第二份对应表")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), f"{rel} 被拒了却仍落盘"


# ============================================================ c 正控
def test_c_the_gate_does_not_block_normal_outputs(tmp_path):
    """c（正控）：F 的自由笔记、G 的论文正文都不在保留表上。"""
    root, reg = _ws(tmp_path)
    res = _call(reg, "F", "fs.write", path="notes/x.md", content="自由笔记")
    assert res.ok is True, res
    assert (root / "notes" / "x.md").is_file()

    res = _call(reg, "G", "fs.write", path="out/paper/main.tex",
                content="\\documentclass{article}\\begin{document}x\\end{document}")
    assert res.ok is True, res
    assert (root / "out" / "paper" / "main.tex").is_file()


# ============================================================ d 反真空（渲染器仍能写）
def test_d_the_framework_renderer_still_writes_the_mapping_files(tmp_path):
    """d（反真空）：这一道闸只管 `fs.*` —— `papermapping.write_package` 照样落三份。"""
    project = tmp_path / "proj"
    (project / "out" / "paper").mkdir(parents=True)
    (project / "out" / "paper" / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}x\\end{document}\n", encoding="utf-8")
    row = PM.Row(kind="theorem", label="t1", env_no=1, ledger_id="stmt:000000",
                 proof_no=1, file="out/paper/main.tex", lean_file="")
    json_path, md_path, frag = PM.write_package(project, [row], workspace_root=project)
    for path in (json_path, md_path, frag):
        assert pathlib.Path(path).is_file(), path
