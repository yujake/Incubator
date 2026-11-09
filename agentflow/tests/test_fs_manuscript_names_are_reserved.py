# -*- coding: utf-8 -*-
"""判据（D5）：A / B 用 `fs.write` / `fs.edit` 写「手稿形名字」一律受控拒。

## 真机现场（`projects/paper-rewrite-98b`，2026-11-10 只读盘点）

B 用 `fs.write` 直接写 `notes/b-proof-000003-v2.md` / `notes/b-proof-000004-v2.md`
⇒ 绕过 `proofregistry.register_or_rewrite`（唯一写口），「同一命题只住一份稿」被绕过；
V 审的始终是 base 稿，v2 从未进台账。

根因（改前 HEAD `7e86f9d6` 的 `tools/fs_tools.py`）：`RESERVED_ARTIFACT_TABLE` 对 A / B
只拦 `reports/{f,b,e}-proof-*` / `reports/e-num-*` —— 规则里带 `/`，按整条路径判，
于是 `notes/` 下的同名手稿完全豁免；而 `manuscriptfamily` 已经能把 `notes/` 下的
手稿形名字判成 `family` / `legacy`。

## 这一份钉的五组读数

| 判据 | 造什么 | 期望 |
|---|---|---|
| a | A / B 写 `notes/b-proof-000001.md`、`notes/b-proof-000003-v2.md` | 受控拒 `reserved_framework_artifact`、零写入、拒信给两条正路（B 的 `AgentB.land_manuscript` / F 的 `promote_manuscript`）并点名 `-v2` |
| b | A / B 用 `fs.edit` 改 `notes/b-proof-000002.md` | 同一条闸：拒、盘上逐字未动（改正文等于绕过同一张表） |
| c | A / B 写 `reports/b-proof-000001.md` | 仍拒，且拒信仍是既有那句 —— 新档不许把既有规则挤掉/换掉 |
| d | A / B 写 `notes/f-proof-x.md`（`bad_name`）、`notes/普通笔记.md`（`unrecognized`） | 放行并落盘（2026-11-07 那次收窄的负控：不误伤普通笔记） |
| e | 把表里 `manuscript:` 两行摘掉 | a 那两条必须变绿（反真空：绿来自新规则本身，不是别处顺手写的判断） |
| f | 读整张表 | 新规则恰好是 `("A", "manuscript:*")` / `("B", "manuscript:*")` 两行；F / D / M 没有这一档，A / B 既有的四个 `prefix:reports/…` 行逐字仍在 |
| g | 直接读 `_manuscript_name_matches` | 判据就是 `manuscriptfamily.classify_name` 的 tier（`family`/`legacy` 命中，`bad_name`/`unrecognized` 不命中），不是「名字里带 `-proof-`」 |

`fs.delete` / `fs.move` 与 `fs.write` / `fs.edit` 共用 `_reserved_refusal` 这一处结论
（2026-11-10 D5 的落点），但本判据只钉任务书点名的两个写口，不扩面。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import manuscriptfamily as MF  # noqa: E402
from agentflow.conductor import calling_as  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402
from agentflow.tools import fs_tools as FT  # noqa: E402

#: 受控码（与保留表同一档）。
KIND = "reserved_framework_artifact"

#: 既有那句拒信（`reports/` 前缀规则命中时用的）。逐字断言它是为了证明
#: `reports/b-proof-*` 仍由既有行拦下，而不是被新档顺手改成了另一句话。
OLD_MESSAGE = "这一份是框架渲染的产物（证明手稿 / 研究手稿），不许手写"

#: 新档拒信里必须点名的三条：两条正路 + 一条禁令（任务书 ① 逐字要求）。
FIX_HINTS = ("AgentB.land_manuscript", "promote_manuscript", "-v2")

#: 新规则在表里的两行（顺序即表序；A 那行插在 A 的四族前缀之后，B 那行在 B 之后）。
MANUSCRIPT_ROWS = (("A", "manuscript:*"), ("B", "manuscript:*"))

#: 既有那四族前缀规则（A / B 各四行）—— 2026-11-07 / 11-08 的口径，逐字不许动。
KEPT_PREFIX_ROWS = {
    ("A", "prefix:reports/f-proof-"),
    ("A", "prefix:reports/b-proof-"),
    ("A", "prefix:reports/e-proof-"),
    ("A", "prefix:reports/e-num-"),
    ("B", "prefix:reports/f-proof-"),
    ("B", "prefix:reports/b-proof-"),
    ("B", "prefix:reports/e-proof-"),
    ("B", "prefix:reports/e-num-"),
}


def _ws(base: pathlib.Path):
    """一个空工作区 + 装配好的工具面（每次调用单独一个，避免「已存在」混进读数）。"""
    root = base / "ws"
    store = Store(root)
    store.init()
    return root, build_registry(store=store, workspace_root=root).registry


def _call(reg, role: str, tool: str, **params):
    """按某个角色的身份调一次工具（与真机同一条路：`calling_as` 挂"我是谁"）。"""
    with calling_as("t-d5-probe", role):
        return reg.call(tool, role=role, **params)


def _error(res) -> str:
    return str(getattr(res, "error", "") or "")


def test_a_notes_manuscript_shaped_names_are_refused(tmp_path: pathlib.Path) -> None:
    """a：`notes/` 下两份手稿形名字（base 稿与 `-v2`）对 A / B 都受控拒、零写入。

    改前红在哪：`RESERVED_ARTIFACT_TABLE` 里 A / B 只有 `prefix:reports/...` 四行，
    `notes/b-proof-000001.md` 与 `-v2` 都写得进去（真机 98b 的现场）。
    """
    cases = ("notes/b-proof-000001.md", "notes/b-proof-000003-v2.md")
    for role in ("A", "B"):
        for index, rel in enumerate(cases):
            root, reg = _ws(tmp_path / f"{role.lower()}-{index}")
            res = _call(reg, role, "fs.write", path=rel, content="手写的稿")
            assert res.ok is False, (role, rel, res.to_dict())
            assert res.meta.get("kind") == KIND, (role, rel, res.meta)
            assert not (root / rel).exists(), f"{role} 写 {rel} 被拒了却仍落盘"
            error = _error(res)
            for hint in FIX_HINTS:
                assert hint in error, (
                    f"{role} / {rel} 的拒信没给改法 {hint!r}：{error}")
            assert "classify_name" in error, (
                f"{role} / {rel} 的拒信没说是按什么判的：{error}")


def test_b_fs_edit_is_the_same_gate(tmp_path: pathlib.Path) -> None:
    """b：`fs.edit` 同一条闸（能改正文就等于绕过同一张保留表），且盘上逐字未动。

    直接用 `Path.write_text` 落一份（框架侧的写口不走 `fs.*`），再以 A / B 的身份
    定点替换 —— 改前这一笔会成功，于是「先手写一份、再改一份」是两条绕过路。
    """
    rel = "notes/b-proof-000002.md"
    original = "# 原件\n\n原来的正文\n"
    for role in ("A", "B"):
        root, reg = _ws(tmp_path / role.lower())
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original, encoding="utf-8")
        res = _call(reg, role, "fs.edit", path=rel,
                    old_string="原来的正文", new_string="被改过的正文")
        assert res.ok is False, (role, res.to_dict())
        assert res.meta.get("kind") == KIND, (role, res.meta)
        assert target.read_text(encoding="utf-8") == original, (
            f"{role} 改 {rel} 被拒了却改了盘上那一份")


def test_c_the_existing_reports_rule_does_not_regress(tmp_path: pathlib.Path) -> None:
    """c：`reports/b-proof-000001.md` 仍拒，且拒信仍是既有那句（既有行没被挤掉/换掉）。

    新档是按名字判的；如果它排在既有前缀行前面，`reports/` 这一路会改用新拒信 ——
    行为还是拒，但既有口径被悄悄换了一句话。这一条同时钉行为与拒信来源。
    """
    rel = "reports/b-proof-000001.md"
    for role in ("A", "B"):
        root, reg = _ws(tmp_path / role.lower())
        res = _call(reg, role, "fs.write", path=rel, content="手写的稿")
        assert res.ok is False, (role, res.to_dict())
        assert res.meta.get("kind") == KIND, (role, res.meta)
        assert OLD_MESSAGE in _error(res), (
            f"{role} / {rel} 的拒信不再是既有那句（既有 prefix 行被新档挤掉了？）："
            f"{_error(res)}")
        assert not (root / rel).exists(), f"{role} 写 {rel} 被拒了却仍落盘"


def test_d_negative_controls_are_still_writable(tmp_path: pathlib.Path) -> None:
    """d（负控）：`bad_name` 与普通笔记都放行 —— 2026-11-07 那次收窄不许被误伤。

    `notes/f-proof-x.md` 是「像手稿、号解析不出」（`bad_name`），普通笔记是
    `unrecognized`；两者都不是手稿形名字，写它们不该撞保留表。
    """
    cases = ("notes/f-proof-x.md", "notes/普通笔记.md")
    assert MF.classify_name(cases[0])["tier"] == MF.TIER_BAD
    assert MF.classify_name(cases[1])["tier"] == MF.TIER_UNRECOGNIZED
    for role in ("A", "B"):
        for index, rel in enumerate(cases):
            root, reg = _ws(tmp_path / f"{role.lower()}-{index}")
            res = _call(reg, role, "fs.write", path=rel, content="普通笔记")
            assert res.ok is True, (role, rel, res.to_dict())
            assert (root / rel).is_file(), (role, rel, "放行了却没落盘")


def test_e_dropping_the_manuscript_rows_turns_a_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """e（反真空）：摘掉表里 `manuscript:` 两行 ⇒ a 那两条必须写得进去。

    打桩点就是那张表（`fs_tools.RESERVED_ARTIFACT_TABLE`），不是匹配器：于是
    「`notes/` 下手稿形名字被拒」这件事的来源是表上新增的那两行本身。摘掉之后
    `reports/b-proof-000001.md` 仍拒 —— 既有行独立生效，摘的只是新档。
    """
    kept = tuple(row for row in FT.RESERVED_ARTIFACT_TABLE
                 if not row[1].startswith("manuscript:"))
    assert len(kept) == len(FT.RESERVED_ARTIFACT_TABLE) - len(MANUSCRIPT_ROWS), (
        "摘 manuscript 行时摘错了行数 ⇒ 这条反真空打桩点在核一个空集")
    monkeypatch.setattr(FT, "RESERVED_ARTIFACT_TABLE", kept)

    for role, index in (("A", 0), ("A", 1), ("B", 0), ("B", 1)):
        rel = ("notes/b-proof-000001.md", "notes/b-proof-000003-v2.md")[index]
        root, reg = _ws(tmp_path / f"{role.lower()}-{index}")
        res = _call(reg, role, "fs.write", path=rel, content="摘掉规则之后")
        assert res.ok is True, (
            f"manuscript 两行被摘掉了却还是拒绝（{role} / {rel}）⇒ "
            f"a 的绿不来自它们：{res.to_dict()}")
        assert (root / rel).is_file(), (role, rel)

    root, reg = _ws(tmp_path / "kept")
    res = _call(reg, "B", "fs.write", path="reports/b-proof-000001.md", content="x")
    assert res.ok is False, ("摘掉新档把既有的 reports/ 前缀规则一起摘掉了？", res.to_dict())


def test_f_the_rule_table_has_exactly_the_two_new_rows() -> None:
    """f：表读数 —— 新档恰好 A / B 两行；F / D / M 没有，A / B 既有前缀行逐字仍在。"""
    rows = tuple((who, rule) for who, rule in FT.RESERVED_ARTIFACT_TABLE
                 if rule.startswith("manuscript:"))
    assert rows == MANUSCRIPT_ROWS, (
        f"新档不是恰好 A / B 两行（F / M / D 或别的角色被扩进来了？）：{rows}")
    for role in ("F", "D", "M"):
        assert not any(who == role and rule.startswith("manuscript:")
                       for who, rule in FT.RESERVED_ARTIFACT_TABLE), (
            f"角色 {role} 也被加进了 manuscript 档 —— 与设计 3.4.2 不符")
    missing = KEPT_PREFIX_ROWS - set(FT.RESERVED_ARTIFACT_TABLE)
    assert not missing, f"A / B 既有的四族前缀行被动了：{sorted(missing)}"


def test_g_the_name_judgement_is_the_manuscriptfamily_table() -> None:
    """g：命中判据是 `manuscriptfamily.classify_name` 的 tier，不是「名字里带 -proof-」。

    改前若有人用「contains `-proof-`」实现这一档，`notes/f-proof-x.md`（`bad_name`）
    就会被误伤 —— 这条判据把四档读数逐条钉在同一个纯函数上。
    """
    for rel, tier, hit in (
        ("notes/b-proof-000001.md", MF.TIER_FAMILY, True),
        ("notes/b-proof-000003-v2.md", MF.TIER_LEGACY, True),
        ("notes/f-proof-x.md", MF.TIER_BAD, False),
        ("notes/普通笔记.md", MF.TIER_UNRECOGNIZED, False),
    ):
        assert MF.classify_name(rel)["tier"] == tier, (rel, MF.classify_name(rel))
        assert FT._manuscript_name_matches(rel) is hit, (rel, tier, hit)
