# -*- coding: utf-8 -*-
"""保留表名单补全（2026-11-17，AU2b 甲类：真权限缺口）。

## 改前是什么形态（真机读数，业主已看过）

```text
E / G / L 用 fs.write 写 reports/f-proof-000001.md  ⇒ 全部 ok=True
D 用 fs.write 写 reports/{b-proof,e-proof,e-num}-*   ⇒ 全部 ok=True
```

`tools/fs_tools.py::RESERVED_ARTIFACT_TABLE` 是逐角色枚举的：A / B 有那四行、
F / D / M 有各自的族，而 E / G / L 一行都没有；D 也只有自己那两族
（`D_PROOF_PATH_RULES`：`f-proof-*` / `*-proof.md`），b-proof / e-proof / e-num 没落。

判据依据写在表里（2026-11-07 那一刀的原话）：「`reports/f-proof-*` 这一类落点
只有框架能写」；危害句是「一份『看起来是 F 登记条目』的稿可以由别的角色手写进盘，
而 B 的收录按 sha 认领会把它当成真稿」。

## 判据（逐角色正向 + 反向各一条，E / G / L / D 各一组）

| 组 | 反向（不属于它的族） | 正向（属于它的那一格） |
|---|---|---|
| E | 写 `reports/{f,b,e}-proof-*` ⇒ 受控拒 | 写 `reports/e-num-*`（E 自己的普通数值族）⇒ 仍 ok |
| G | 同上 ⇒ 受控拒 | 写 `out/paper/main.tex`（G 的排版产物）⇒ 仍 ok |
| L | 同上 ⇒ 受控拒 | 写 `code/formal/<名>.lean`（L 的形式化落点）⇒ 仍 ok |
| D | 写 `reports/{b,e}-proof-*` 与 `reports/e-num-*` ⇒ 受控拒 | 写 `reports/RESEARCH.md`（D 的研究手稿）⇒ 仍 ok |

反真空：把该角色那几行从表里摘掉 ⇒ 同一批"不属于它的族"的写入必须成功
（于是"被拒"的来源是表上那几行，而不是别处顺手写的判断）。

为什么 E 的正控是 `e-num` 而不是 `e-proof`：甲类点名的三族包含 `e-proof`
（它是框架渲染 + 要 V 签的穷举证明稿），而 `e-num` 是 2026-11-08 业主裁定给 E 的
普通数值族、不在本次点名的三族里 —— 不把没点名的格顺手封掉。

为什么 L 那一组在 `AGENTFLOW_LEAN_ENABLED=1` 下才有面：Lean 关着时 L 不存在
（`leanscope.is_hidden`），两个面都空。`tests/conftest.py` 在导入期把开关钉成 1，
所以这一组在判据里可达。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import fs_tools as FT
from conftest import seed_writing_material

#: 受控码（与保留表同一档）。
KIND = "reserved_framework_artifact"

#: 甲类点名的三族（规范落点 `reports/<族>-...md`）。
FAMILIES: tuple[str, ...] = ("f-proof", "b-proof", "e-proof")

#: 每一族的规范落点一行（号段形状与真机一致）。
PATHS: tuple[str, ...] = tuple(f"reports/{fam}-000001.md" for fam in FAMILIES)

#: 逐角色：这一组的反向用哪些规则（反真空时摘掉的正是这些）。
ROLE_RULES: dict[str, tuple[str, ...]] = {
    "E": tuple(f"prefix:reports/{fam}-" for fam in FAMILIES),
    "G": tuple(f"prefix:reports/{fam}-" for fam in FAMILIES),
    "L": tuple(f"prefix:reports/{fam}-" for fam in FAMILIES),
    "D": ("prefix:reports/b-proof-", "prefix:reports/e-proof-",
          "prefix:reports/e-num-"),
}


def _ws(path: pathlib.Path):
    root = path / "ws"
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry
    return root, reg


def _call(reg, role: str, tool: str, **params):
    """按某个角色的身份调一次工具（"我是谁"由 `calling_as` 挂上，与真机同一条路）。"""
    with calling_as("t-other-roles", role):
        return reg.call(tool, role=role, **params)


def _dropped(role: str, monkeypatch) -> None:
    """反真空打桩：把该角色本笔新增的那几行摘掉（其余行一个字节不动）。

    2026-11-17（DOCGATE2 ③）：`reports/<谁>-proof-<号>.md` 现在还有一行形状级
    （`("+", "proofshape:reports")`，对任何角色都成立）也在拒同一批落点。反真空要
    证明的是"被拒来自这张表"，所以那一行也得一起摘 —— 只摘角色行的话，同一批写入仍会
    被形状行拒（那不是"打桩没生效"，是同一件判据的第二个落点）。只摘角色行时"仍然被拒"
    这一条由 `test_dropping_only_the_role_rows_keeps_them_refused` 单独钉住。
    """
    gone = set(ROLE_RULES[role])
    kept = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE
                 if not (row[0] == role and row[1] in gone)
                 and not (row[0] == FT.MANUSCRIPT_ONLY_ROLE
                          and row[1].startswith(FT.PROOF_SHAPE_RULE_KIND + ":")))
    assert len(kept) == len(FT.RESERVED_ARTIFACT_TABLE) - len(gone) - 1, (
        f"{role} 那几行没找齐 ⇒ 这条反真空在核一个空集")
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", kept)


def test_dropping_only_the_role_rows_keeps_them_refused(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """③ 的落点：只摘掉某个角色的那几行 ⇒ 同一批写入仍然被拒（形状行在管）。

    这不是"反真空失效"，而是补全后的分层读数：角色行给的是各自的拒信/角色归属，
    形状行给的是"这一类落点只有框架能写"。两层都在 ⇒ 摘一层不会开门。
    """
    role = "G"
    gone = set(ROLE_RULES[role])
    kept = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE
                 if not (row[0] == role and row[1] in gone))
    assert len(kept) == len(FT.RESERVED_ARTIFACT_TABLE) - len(gone)
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", kept)
    root, reg = _ws(tmp_path)
    for rel in PATHS:
        res = _call(reg, role, "fs.write", path=rel, content="摘掉角色行之后写的")
        assert res.ok is False, (rel, "摘掉角色行就开门了 ⇒ 形状行不在管这一批落点", res.meta)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), (role, rel)


# ---------------------------------------------------------------- E


def test_e_cannot_write_other_roles_proof_families(tmp_path: pathlib.Path) -> None:
    """E 反向：三族证明稿全拒（改前三条都 `ok=True`）。"""
    root, reg = _ws(tmp_path)
    for rel in PATHS:
        res = _call(reg, "E", "fs.write", path=rel, content="E 手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert res.meta.get("role") == "E", (rel, res.meta)
        assert not (root / rel).exists(), f"E 写 {rel} 被拒了却仍落盘"


def test_e_may_still_write_its_own_numeric_family(tmp_path: pathlib.Path) -> None:
    """E 正向：`reports/e-num-*`（E 自己的普通数值族）仍然写得进去。"""
    root, reg = _ws(tmp_path)
    rel = "reports/e-num-000001.md"
    res = _call(reg, "E", "fs.write", path=rel, content="## 命题\n\n## 数值结果\n")
    assert res.ok is True, ("E 自己的数值族被误伤了", res)
    assert (root / rel).is_file()


# ---------------------------------------------------------------- G


def test_g_cannot_write_other_roles_proof_families(tmp_path: pathlib.Path) -> None:
    """G 反向：三族证明稿全拒（改前 `reports/f-proof-g.md` 这类落点写得进去）。"""
    root, reg = _ws(tmp_path)
    for rel in PATHS:
        res = _call(reg, "G", "fs.write", path=rel, content="G 手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), f"G 写 {rel} 被拒了却仍落盘"


def test_g_may_still_write_its_own_typeset_output(tmp_path: pathlib.Path) -> None:
    """G 正向：`out/paper/main.tex`（G 的论文正文）仍然写得进去。

    2026-11-17（DOCGATE2 ②）：这一格现在要过成文门（零签且零地基 ⇒ 拒），所以先补一份
    签（`seed_writing_material`）。本判据测的是保留表那一侧，补料之后断言一个字没改。
    """
    root, reg = _ws(tmp_path)
    seed_writing_material(Store(root))          # 成文门的前置料（不是本判据的被测对象）
    rel = "out/paper/main.tex"
    res = _call(reg, "G", "fs.write", path=rel, content="\\documentclass{article}\n")
    assert res.ok is True, ("G 的论文正文被误伤了", res)
    assert (root / rel).is_file()


# ---------------------------------------------------------------- L


def test_l_cannot_write_other_roles_proof_families(tmp_path: pathlib.Path) -> None:
    """L 反向：三族证明稿全拒（Lean 开着时 L 才有面）。"""
    root, reg = _ws(tmp_path)
    for rel in PATHS:
        res = _call(reg, "L", "fs.write", path=rel, content="L 手写的证明稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert not (root / rel).exists(), f"L 写 {rel} 被拒了却仍落盘"


def test_l_may_still_write_its_formal_artifact(tmp_path: pathlib.Path) -> None:
    """L 正向：`code/formal/<名>.lean`（L 的形式化落点）仍然写得进去。"""
    root, reg = _ws(tmp_path)
    rel = "code/formal/000004.lean"
    res = _call(reg, "L", "fs.write", path=rel, content="theorem t : True := trivial\n")
    assert res.ok is True, ("L 的形式化落点被误伤了", res)
    assert (root / rel).is_file()


# ---------------------------------------------------------------- D


def test_d_cannot_write_b_or_e_families(tmp_path: pathlib.Path) -> None:
    """D 反向：b-proof / e-proof / e-num 全拒（改前三条都 `ok=True`）。"""
    root, reg = _ws(tmp_path)
    for rel in ("reports/b-proof-000001.md", "reports/e-proof-000001.md",
                "reports/e-num-000001.md"):
        res = _call(reg, "D", "fs.write", path=rel, content="D 手写的别人的手稿")
        assert res.ok is False, (rel, res)
        assert res.meta.get("kind") == KIND, (rel, res.meta)
        assert res.meta.get("role") == "D", (rel, res.meta)
        assert not (root / rel).exists(), f"D 写 {rel} 被拒了却仍落盘"


def test_d_may_still_write_its_own_research_manuscript(tmp_path: pathlib.Path) -> None:
    """D 正向：`reports/RESEARCH.md`（D 的研究手稿）仍然写得进去。

    2026-11-04 补充裁定：研究手稿是 D 的既有交付物；本笔收窄的是"别人的手稿族"，
    不是 D 自己的交付面。
    """
    root, reg = _ws(tmp_path)
    rel = "reports/RESEARCH.md"
    res = _call(reg, "D", "fs.write", path=rel, content="# 研究手稿\n\n## 成果概述\n")
    assert res.ok is True, ("D 的研究手稿被误伤了", res)
    assert (root / rel).is_file()


# ---------------------------------------------------------------- 反真空 + 读数


@pytest.mark.parametrize("role", ("E", "G", "L", "D"))
def test_dropping_that_roles_rows_turns_the_refusal_green(
        tmp_path: pathlib.Path, monkeypatch, role: str) -> None:
    """反真空：把该角色那几行摘掉 ⇒ 同一批写入必须成功（"被拒"来自那几行）。"""
    _dropped(role, monkeypatch)
    root, reg = _ws(tmp_path)
    rels = ([f"reports/{fam}-000001.md" for fam in FAMILIES] if role != "D"
            else ["reports/b-proof-000001.md", "reports/e-proof-000001.md",
                  "reports/e-num-000001.md"])
    for rel in rels:
        res = _call(reg, role, "fs.write", path=rel, content="改前状态：写得进去")
        assert res.ok is True, (
            f"{role} 那几行被摘掉了却还是拒绝（{rel}）⇒ 这一组的绿不来自它们", res)
        assert (root / rel).is_file(), (role, rel)


def test_the_table_names_are_complete_for_the_five_roles() -> None:
    """读数：三族对 A / B / E / G / L 都在表上；D 另有 b/e/e-num 三行。

    为什么钉读数：名单补全这件事的形态就是"表上有哪几行"；只钉行为不钉名单，
    下一次"再加一个角色"时不会有人发现它又一次只补了一半。
    """
    table = FT.RESERVED_ARTIFACT_TABLE
    for fam in FAMILIES:
        rule = f"prefix:reports/{fam}-"
        roles = {who for who, got in table if got == rule}
        assert {"A", "B", "E", "G", "L"} <= roles, (fam, sorted(roles))
        # 这三族不许出现"表外角色"（F 是产出侧但 `f-proof-*` 走它自己的名字档；
        # M 走自己的两行）—— 名单只该是这五个加 D（b/e 两族）。
        assert roles <= {"A", "B", "D", "E", "G", "L"}, (fam, sorted(roles))
    for rule in ("prefix:reports/b-proof-", "prefix:reports/e-proof-",
                 "prefix:reports/e-num-"):
        assert "D" in {who for who, got in table if got == rule}, rule
    assert {who for who, got in table if got == "prefix:reports/f-proof-"} == {
        "A", "B", "E", "G", "L"}, "f-proof 一族不该有 D（D 的 f-proof 走它自己那两行）"
    # D 的证明稿拒信仍是同一句（派 F）：`D_OTHER_PROOF_PREFIXES` 与表里那两行同源。
    assert set(FT.D_OTHER_PROOF_PREFIXES) <= {rule for _who, rule in table}, (
        "D 的「别人的证明族」规则与表里的行漂了")
