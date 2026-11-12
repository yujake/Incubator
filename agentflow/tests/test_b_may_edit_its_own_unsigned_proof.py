# -*- coding: utf-8 -*-
"""判据（甲）：B 的唯一一格窄豁免 —— `fs.edit` 自己号段、未签的 `reports/b-proof-<六位号>.md`。

## 业主裁定 ④（逐字）

```text
「B侧进入证明优化阶段时，选中一个待优化的命题后系统自动帮其拿到稿件并复制一份
  注册成B号并清除复制版本内的V签」
```

`B.open_polish_copy` 已把副本开成 `reports/b-proof-<B 稿号>.md`（判据
`tests/test_b_open_polish_copy.py`），但这句裁定的后半句（「之后 B 在那份 B 稿上改正文」）
走不通：`tools/fs_tools.py` 的 `RESERVED_ARTIFACT_TABLE` 对 B 的两行（`prefix:reports/b-proof-`
与 `manuscript:*`）把手稿形名字一律拒写。本文件钉住那条豁免的形状。

## 豁免窄到什么程度（一条判据一格，逐条可读）

| # | 造什么 | 期望 | 钉住的东西 |
|---|---|---|---|
| a | B 对未签的 `reports/b-proof-000000.md` 调 `fs.edit` | `ok=True`，正文真的变了 | 正控：④ 的后半句走得通 |
| b | B 对「已签」的 b 稿调 `fs.edit` | 受控拒，`kind=manuscript_frozen`（冻结那一套，不新造码） | 未签这一格不是纸面 |
| c | B 对 `reports/f-proof-*.md` 调 `fs.edit` | 仍拒（`reserved_framework_artifact`） | 豁免不外溢到 F 的稿 |
| d | B 对 `reports/b-proof-*.md` 调 `fs.write` / `fs.delete` | 仍拒（同一码） | 只开 `edit` 一格 |
| e | A（别的角色）对 b 稿调 `fs.edit` | 仍拒 | 只对角色 B |
| f | 把豁免摘掉（打桩 `_b_polish_edit_allowed` ⇒ False） | a 变红 | a 的绿来自那格豁免本身 |
| g | B 对「没发过号」的 `reports/b-proof-000009.md` 调 `fs.edit` | 仍拒 | 号必须来自 B 自己的号段 |
| h | B 对 `reports/b-proof-000000-p2.md` 调 `fs.edit` | 仍拒 | 一份号一份文件（`-pN` 老名在产出侧已退役，不在豁免里） |

全部 tmp 工作区，不读写 `projects/`（真机工作区只读），不跑全量。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import manuscriptfreeze as FZ  # noqa: E402
from agentflow import manuscriptids as MID  # noqa: E402
from agentflow import proofregistry as PR  # noqa: E402
from agentflow.conductor import calling_as  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import fs_tools as FT  # noqa: E402
from agentflow.tools.fs_tools import FsContext  # noqa: E402

import _credential_fixture as CF  # noqa: E402

#: 与保留表同一档的受控码（豁免不放行时由它拒）。
KIND = "reserved_framework_artifact"

SID = "000001"
BODY_1 = "第一版正文：由定义直接得到。"
BODY_2 = "第二版正文：改用有限覆盖。"

TEXT = """# B 的证明手稿：夹具命题

- 命题号：stmt:000001
- 依赖面洗稿：已洗=true；洗的人=secretary:F；补写=无

## 命题

夹具命题。

## 证明

{body}

## 依赖

| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |
|---|---|---|
（这一份证明没有引用任何在册命题 —— 空表就是声明。）
"""


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    (pathlib.Path(st.root) / "reports").mkdir(parents=True, exist_ok=True)
    return st


def _ctx(st: Store) -> FsContext:
    return FsContext(root=pathlib.Path(st.root), actor="probe")


def _write(st: Store, rel: str, body: str = BODY_1) -> str:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEXT.format(body=body), encoding="utf-8")
    return rel


def _alloc_b(st: Store) -> str:
    """向 B 自己的号段要一个号（于是 `reports/b-proof-<号>.md` 是"已发号"的）。"""
    return MID.next_manuscript_id(st, family="b-proof")


def _read_as(st: Store, role: str, rel: str):
    """以某个角色的身份先读一次（`fs.edit` 的"读过再改"闸；与真机同一条路）。"""
    with calling_as(f"t-jia-{role}", role):
        return FT.fs_read(_ctx(st), path=rel)


def _edit_as(st: Store, role: str, rel: str, old: str, new: str):
    """以某个角色的身份调 `fs.edit`（先读一次，免得撞"没读过"那条闸）。"""
    assert _read_as(st, role, rel).ok is True
    with calling_as(f"t-jia-{role}", role):
        return FT.fs_edit(_ctx(st), path=rel, old_string=old, new_string=new)


def _signed(st: Store, rel: str, *, body: str = BODY_1) -> str:
    """一份已拿签的 b 稿：签文件在颁发表里（`artifact_path` 指着它，正文 sha 对得上）。"""
    _write(st, rel, body)
    CF.issue_credential(st.root, proof_text=body, statement_id=SID,
                        manuscript=rel, artifact_path=rel)
    return rel


# ------------------------------------------------------------------ a 正控

def test_a_b_can_edit_its_own_unsigned_proof(tmp_path: pathlib.Path) -> None:
    """a：B 对未签的 `reports/b-proof-000000.md` 调 `fs.edit` ⇒ ok=True，正文真的变了。"""
    st = _ws(tmp_path)
    mid = _alloc_b(st)
    assert mid == "000000", mid
    rel = _write(st, f"reports/b-proof-{mid}.md")
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert FZ.freeze_reading(st.root, rel)["state"] == "unsigned"

    got = _edit_as(st, "B", rel, BODY_1, BODY_2)
    assert got.ok is True, (got.to_dict(), got.meta)
    after = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")
    assert BODY_2 in after and BODY_1 not in after, after
    assert after != before
    assert got.meta.get("replacements") == 1, got.meta


# ------------------------------------------------------------------ b 反向①：已签

def test_b_a_signed_b_proof_is_still_frozen(tmp_path: pathlib.Path) -> None:
    """b：B 对「已签」的 b 稿 ⇒ 受控拒；`kind` 是冻结那一个，不是新造码。"""
    st = _ws(tmp_path)
    mid = _alloc_b(st)
    rel = _signed(st, f"reports/b-proof-{mid}.md")
    reading = FZ.freeze_reading(st.root, rel)
    assert reading["state"] == "signed", reading
    assert PR.proof_sha(BODY_1) == reading["sign_sha"], reading
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    got = _edit_as(st, "B", rel, BODY_1, BODY_2)
    assert got.ok is False, got.to_dict()
    assert got.meta.get("kind") == FZ.MANUSCRIPT_FROZEN, got.meta
    assert got.meta.get("kind") != KIND, (
        "已签那一档落回了保留表的码 ⇒ 豁免把冻结那一格吞掉了", got.meta)
    assert "已经拿签" in str(got.error), got.error
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before, (
        "拒了却改了盘上那一份")


# ------------------------------------------------------------------ c 反向②：不外溢到 F

def test_c_the_exemption_does_not_reach_f_manuscripts(tmp_path: pathlib.Path) -> None:
    """c：B 对 `reports/f-proof-*.md` 调 `fs.edit` ⇒ 仍拒（豁免只认 b- 那一族）。"""
    st = _ws(tmp_path)
    rel = _write(st, "reports/f-proof-000000.md")
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    got = _edit_as(st, "B", rel, BODY_1, BODY_2)
    assert got.ok is False, got.to_dict()
    assert got.meta.get("kind") == KIND, got.meta
    assert "框架渲染的产物" in str(got.error), got.error
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before


# ------------------------------------------------------------------ d 反向③：只开 edit

def test_d_write_and_delete_are_still_refused(tmp_path: pathlib.Path) -> None:
    """d：B 对同一条 b 稿调 `fs.write` / `fs.delete` ⇒ 仍拒（只开 `fs.edit` 一格）。"""
    st = _ws(tmp_path)
    mid = _alloc_b(st)
    rel = f"reports/b-proof-{mid}.md"
    path = pathlib.Path(st.root) / rel
    _write(st, rel)
    before = path.read_text(encoding="utf-8")

    with calling_as("t-jia-B", "B"):
        wrote = FT.fs_write(_ctx(st), path=rel, content="换一份", overwrite=True)
    assert wrote.ok is False, wrote.to_dict()
    assert wrote.meta.get("kind") == KIND, wrote.meta
    assert path.read_text(encoding="utf-8") == before, "fs.write 被拒了却改了盘上那一份"

    with calling_as("t-jia-B", "B"):
        deleted = FT.fs_delete(_ctx(st), path=rel)
    assert deleted.ok is False, deleted.to_dict()
    assert deleted.meta.get("kind") == KIND, deleted.meta
    assert path.is_file(), "fs.delete 被拒了却把那一份删了"


# ------------------------------------------------------------------ e 反向④：只对 B

def test_e_other_roles_are_still_refused(tmp_path: pathlib.Path) -> None:
    """e：A（别的角色）对同一条 b 稿调 `fs.edit` ⇒ 仍拒（豁免只对角色 B）。"""
    st = _ws(tmp_path)
    mid = _alloc_b(st)
    rel = _write(st, f"reports/b-proof-{mid}.md")
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    got = _edit_as(st, "A", rel, BODY_1, BODY_2)
    assert got.ok is False, got.to_dict()
    assert got.meta.get("kind") == KIND, got.meta
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before


# ------------------------------------------------------------------ f 反真空

def test_f_dropping_the_exemption_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """f（反真空）：把豁免摘掉 ⇒ a 那一笔立刻变红（拒）。

    打桩点就是豁免函数本身（`_b_polish_edit_allowed`），不是别的闸：于是 a 的绿
    来自这一格，而不是"B 本来就能改 b 稿"。
    """
    monkeypatch.setattr(FT, "_b_polish_edit_allowed", lambda *a, **k: False)
    st = _ws(tmp_path)
    mid = _alloc_b(st)
    rel = _write(st, f"reports/b-proof-{mid}.md")
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    got = _edit_as(st, "B", rel, BODY_1, BODY_2)
    assert got.ok is False, (
        "豁免被摘掉之后 B 仍改得动 b 稿 ⇒ a 的绿不来自那格豁免", got.to_dict())
    assert got.meta.get("kind") == KIND, got.meta
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before


# ------------------------------------------------------------------ g/h 窄度

def test_g_a_number_b_never_issued_is_still_refused(tmp_path: pathlib.Path) -> None:
    """g：号不在 B 已发号段里 ⇒ 不放行（"自己名下"不是"名字像 b 稿"）。"""
    st = _ws(tmp_path)
    assert _alloc_b(st) == "000000"
    rel = _write(st, "reports/b-proof-000009.md")
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    got = _edit_as(st, "B", rel, BODY_1, BODY_2)
    assert got.ok is False, got.to_dict()
    assert got.meta.get("kind") == KIND, got.meta
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before


def test_h_the_proof_no_suffix_is_not_exempted(tmp_path: pathlib.Path) -> None:
    """h：`-pN` 老名不在豁免里（一份号一份文件；2026-11-11 起它已不是稿名）。"""
    st = _ws(tmp_path)
    assert _alloc_b(st) == "000000"
    rel = _write(st, "reports/b-proof-000000-p2.md")
    before = (pathlib.Path(st.root) / rel).read_text(encoding="utf-8")

    got = _edit_as(st, "B", rel, BODY_1, BODY_2)
    assert got.ok is False, got.to_dict()
    assert got.meta.get("kind") == KIND, got.meta
    assert (pathlib.Path(st.root) / rel).read_text(encoding="utf-8") == before
