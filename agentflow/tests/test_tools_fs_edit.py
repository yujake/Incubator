# -*- coding: utf-8 -*-
"""`fs.edit` 的判据（`draft/37` §16 P0 / R2）：定点替换是"改 51 KB 论文"唯一在预算内的路。

为什么这一条是整个 polish 线的前提（真机实测 2026-10-01）：
`fs.write` 是整文件覆盖语义，而观测层每次只回显约 3,000 字 —— 一篇 51,285 字节
（≈25.6K token）的论文要改一处措辞，用整文件覆盖意味着"一次回复里逐字吐出全文"，
而模型单次输出上限 4,096 token ⇒ 物理上写不出来。G 因此三次拒绝改稿，
理由是"无法逐字重建全文，盲写有静默损坏正文的风险" —— 那是正确的行为，
错的是工具。这一条判据钉三件事：

1. 正控：在 51 KB 的正文里做一次 20 字的定点替换 ⇒ 只改那一处（其余字节逐字不变），
   并回前后 sha256 + `note`；
2. 负控一（歧义）：`old_string` 出现两次 ⇒ 拒绝（`ambiguous`），一个字都不许改；
3. 负控二（版本）：调用方给的 `sha256` 与盘上现版不符 ⇒ 拒绝（`sha_mismatch`），
   一个字都不许改；
4. 另外三条边界（空 `old_string` / 找不到 / `new_string` 超上限）也必须有各自的拒绝理由。
"""
from __future__ import annotations

import hashlib
import pathlib

from agentflow.tools import fs_tools
from agentflow.tools.base import ToolRegistry


def _registry(root: pathlib.Path) -> ToolRegistry:
    reg = ToolRegistry(name="fs-edit")
    reg.bound_role = "A"  # `P-14`：`fs.edit` 是写工具，只读角色拿不到
    fs_tools.register(reg, root=root)
    return reg


def _paper(root: pathlib.Path) -> pathlib.Path:
    """造一份"像论文那样大"的文件：约 51 KB、含两处相同措辞（供歧义负控）。"""
    body = [f"% 第 {i} 行：\\begin{{theorem}}...\\end{{theorem}}" for i in range(1200)]
    body[300] = "\\begin{lemma}[floor lemma]\\label{lem:floor} $|d_n-F(C_n)|<\\binom m2$ \\end{lemma}"
    body[900] = "\\begin{remark} what is missing is the proof of the two steps \\end{remark}"
    body[901] = "\\begin{remark} what is missing is the proof of the two steps \\end{remark}"
    path = root / "out" / "paper" / "main.tex"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body) + "\n", encoding="utf-8", newline="")
    return path


def test_fs_edit_changes_exactly_one_place_and_reports_hashes(store):
    """正控：只改那一处（其余字节逐字不变），并回前后 sha + note。"""
    root = pathlib.Path(store.root)
    paper = _paper(root)
    before = paper.read_bytes()
    assert len(before) > 40_000, f"夹具太小（{len(before)} 字节）⇒ 这条判据失去意义"
    reg = _registry(root)

    old = "$|d_n-F(C_n)|<\\binom m2$"
    new = "$|d_n-F(C_n)|\\le\\binom m2$"
    got = reg.call("fs.edit", path="out/paper/main.tex", old_string=old, new_string=new,
                   sha256=hashlib.sha256(before).hexdigest(), note="严格不等号在 n=0 时依赖边界说明，改为 ≤")

    assert got.ok, got.error
    after = paper.read_bytes()
    # ① 只改了那一处：字节数差值 = 新串 - 旧串，且其余部分逐字不变
    assert got.data["sha256_before"] == hashlib.sha256(before).hexdigest()
    assert got.data["sha256_after"] == hashlib.sha256(after).hexdigest()
    assert got.data["replacements"] == 1
    assert got.data["bytes_after"] - got.data["bytes_before"] == len(new.encode()) - len(old.encode())
    assert before.replace(old.encode(), new.encode()) == after, "除了那一处，其余字节必须逐字不变"
    assert got.data["note"].startswith("严格不等号"), "note（依据）必须回在产物里，供审计"
    # ② 盘的 sha 与返回值一致（不许"报了 sha 但没真写"）
    assert got.data["sha256_after"] == hashlib.sha256(paper.read_bytes()).hexdigest()


def test_fs_edit_refuses_an_ambiguous_match(store):
    """负控一：`old_string` 出现两次 ⇒ 拒绝，且一个字都不许改。"""
    root = pathlib.Path(store.root)
    paper = _paper(root)
    before = paper.read_bytes()
    reg = _registry(root)

    ambiguous = "what is missing is the proof of the two steps"
    assert paper.read_text(encoding="utf-8").count(ambiguous) == 2, "夹具前提：这句必须出现两次"
    got = reg.call("fs.edit", path="out/paper/main.tex", old_string=ambiguous, new_string="X")

    assert not got.ok, "歧义匹配必须拒绝（替换错地方比不替换更坏）"
    assert "两次" in (got.error or "") or "2 次" in (got.error or ""), got.error
    assert paper.read_bytes() == before, "被拒绝的那一次不许改到盘上的任何字节"
    # 正控对照：显式 allow_multiple=true 才允许"每一处都换"
    ok = reg.call("fs.edit", path="out/paper/main.tex", old_string=ambiguous, new_string="X",
                  allow_multiple=True)
    assert ok.ok and ok.data["replacements"] == 2, ok.error


def test_fs_edit_refuses_a_stale_sha(store):
    """负控二：`sha256` 与盘上现版不符 ⇒ 拒绝（防"我拿的是别人改之前的那一版"）。"""
    root = pathlib.Path(store.root)
    paper = _paper(root)
    before = paper.read_bytes()
    stale = hashlib.sha256(b"another version").hexdigest()
    reg = _registry(root)

    got = reg.call("fs.edit", path="out/paper/main.tex",
                   old_string="\\begin{lemma}[floor lemma]", new_string="\\begin{lemma}[FLOOR]",
                   sha256=stale)
    assert not got.ok and "sha256" in (got.error or ""), got.error
    assert paper.read_bytes() == before, "版本不符时一个字都不许改"


def test_fs_edit_refuses_the_three_other_edges(store):
    """边界：空 `old_string` / 找不到 / `new_string` 超上限 —— 各自的拒绝理由必须分得开。"""
    root = pathlib.Path(store.root)
    paper = _paper(root)
    before = paper.read_bytes()
    reg = _registry(root)

    empty = reg.call("fs.edit", path="out/paper/main.tex", old_string="", new_string="X")
    missing = reg.call("fs.edit", path="out/paper/main.tex", old_string="这段不在文件里", new_string="X")
    huge = reg.call("fs.edit", path="out/paper/main.tex", old_string="\\begin{lemma}[floor lemma]",
                    new_string="X" * (fs_tools.MAX_EDIT_BYTES + 1))
    assert not empty.ok and "old_string 不能为空" in (empty.error or ""), empty.error
    assert not missing.ok and "找不到" in (missing.error or ""), missing.error
    assert not huge.ok and "上限" in (huge.error or ""), huge.error
    assert paper.read_bytes() == before, "三条边界都不许改到盘上的字节"
    # 反真空：工具不是"永远拒绝" —— 文件里真实存在的一句必须改得动
    ok = reg.call("fs.edit", path="out/paper/main.tex", old_string="% 第 5 行",
                  new_string="% 第 5 行（改）", note="反真空对照")
    assert ok.ok and ok.data["replacements"] == 1, ok.error
