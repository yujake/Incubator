# -*- coding: utf-8 -*-
"""判据（第 ④ 条）：`fs.write` / `fs.edit` 的 summary 与 `RESERVED_ARTIFACT_TABLE` 同源。

## 为什么需要这一条

工具声明里的 summary 是模型看得见的教法，`RESERVED_ARTIFACT_TABLE` 是保留路径判据的
唯一落点。两处说法不一致时，模型会照 summary 做却撞上表（或反过来不敢写），而任何一条
单测都不会因此变红。走查 D8（`temp/walk-fix-20261105/probe_d8.py`）实测过一次：
summary 说 `RESEARCH.md` 对 D 拒写，而表里 D 那一行已按 2026-11-04 的裁定删掉，
D 真写 `reports/RESEARCH.md` 是成功的 —— 工具面在教错。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| 正控 | 两条 summary 与表逐格一致；期望值全部从表现算（不写死角色名），表一改 summary 不跟就红 | 改前 summary 与表已经对不上（D8） |
| 反真空一 | 把 `fs.write` 的 summary 换回旧句（或塞回"`RESEARCH.md` 对 F/D/M 拒写"）⇒ 必红 | —— |
| 反真空二 | 表里加回一行 `("D", "contains:RESEARCH")`（或摘掉 D 的证明稿规则）而 summary 没跟 ⇒ 必红 | —— |
| 行为面 | summary 说的"D 能写 `RESEARCH.md` / 在任何路径写带 `## 证明` 的正文被拒"与真工具一致 | 改前 summary 与行为一致但与表不一致 |

这一组只读两处 + 调一次真工具，零模型、只落一个临时工作区。
"""
from __future__ import annotations

import pathlib
import re
import sys
from typing import Sequence

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools import fs_tools as FT

#: 受控码（与保留表同一档）。
KIND = "reserved_framework_artifact"

#: 走查 D8 的旧句（逐字；反真空一用）。
OLD_WRITE_SUMMARY = (
    "写文本文件（原子落盘；默认不覆盖已有文件）。reports/ 下框架产物（`f-proof-*` / "
    "`RESEARCH.md` / `*-research.md`）对 F / D / M 拒写（reserved_framework_artifact），"
    "改走各自的渲染动作。")


def claimed_roles(table: Sequence[tuple[str, str]], *,
                  shapes: Sequence[str]) -> list[str]:
    """从保留表现算"这些形状对哪些角色拒写"（只取具体角色行；`*` / `@` 不是角色面）。"""
    out = set()
    for role, rule in table:
        if role in ("*", "@"):
            continue
        for shape in shapes:
            if rule == shape:
                out.add(role)
    return sorted(out)


def _role_groups(text: str) -> list[set[str]]:
    """summary 里角色清单的写法（`F/D/M`、`F / D / M` 都认，顺序不论）。"""
    return [{x for x in match.group(0).replace(" ", "").split("/") if x}
            for match in re.finditer(r"[FDM](?:\s*/\s*[FDM])+", text)]


def _names_roles(text: str, roles: Sequence[str]) -> bool:
    want = set(roles)
    return bool(want) and any(group == want for group in _role_groups(text))


def summary_problems(name: str, summary: str,
                     table: Sequence[tuple[str, str]]) -> list[str]:
    """一条判据同时读 summary 与保留表（空清单 = 两处说法一致）。

    期望值全部从 `table` 现算，不在这里写死角色名 —— 表的 D 行一变，这句不跟就红。
    `fs.edit` 的 summary 明确说"同 fs.write" ⇒ 它只承担"引用 + D 可写 + `## 证明`"那几格；
    证明稿形状 / `*-research.md` / `out/proofs/*.md` / "派 F" 由 `fs.write` 那一句承担。
    """
    out: list[str] = []
    text = str(summary or "")

    proof_roles = claimed_roles(table, shapes=("prefix:f-proof-", "suffix:-proof.md"))
    research_roles = claimed_roles(table, shapes=("suffix:-research.md",))
    name_roles = sorted({role for role, rule in table
                         if role not in ("*", "@") and rule == "contains:RESEARCH"})
    d_may_write_research = not any(
        role == "D" and "RESEARCH" in rule for role, rule in table)

    if name == "fs.write":
        # ---- 证明稿形状：表里拒它的角色，summary 必须点名
        if not ("`f-proof-*`" in text and "`*-proof.md`" in text):
            out.append("summary 没写证明稿形状（`f-proof-*` / `*-proof.md`）")
        if proof_roles and not _names_roles(text, proof_roles):
            out.append(f"summary 没点名拒证明稿形状的角色 {proof_roles!r}（表里是它们）")

        # ---- 每问题工作稿：表里拒它的角色（D/M），summary 必须点名
        if research_roles:
            if "`*-research.md`" not in text:
                out.append("summary 没写每问题工作稿形状 `*-research.md`")
            if not _names_roles(text, research_roles):
                out.append(f"summary 没点名拒 `*-research.md` 的角色 {research_roles!r}")

        # ---- 内容闸与指路：这一格要能被读成"任何路径上自写 `## 证明` 才拒"，
        #      并给"落稿"的出口；例外（引用 F 的稿 / 它的 sha）必须与实现同口径（D3）。
        if "`out/proofs/*.md`" not in text:
            out.append("summary 没写 `out/proofs/*.md` 带 `## 证明` 那一档")
        if "任何路径" not in text:
            out.append("summary 没写「任何路径」那一档（内容闸不按目录、不按名字）")
        if "`reports/f-proof-<号>.md`" not in text or "sha256" not in text:
            out.append("summary 没写例外（引用盘上 `reports/f-proof-<号>.md` 或它的 sha256）"
                       "—— 实现 `_cites_an_f_manuscript` 对这两条放行，summary 比它严")
        if "派 F" not in text:
            out.append("summary 没点名「要落稿就派 F」")
    else:
        if "fs.write" not in text:
            out.append("fs.edit 的 summary 没引用 fs.write（两件的保留面是同一条）")

    # ---- RESEARCH.md：表里只有 M 拒它 ⇒ summary 必须说 D 可写、M 另拒
    if name_roles and name == "fs.write":
        nwant = "/".join(name_roles)
        if f"{nwant} 另拒 `RESEARCH.md`" not in text:
            out.append(f"summary 没写 {nwant!r} 另拒 `RESEARCH.md`（表里是它拒）")
    if d_may_write_research:
        if "D 可写 `RESEARCH.md`" not in text:
            out.append("表里没有 D 的 RESEARCH 行 ⇒ summary 必须说「D 可写 `RESEARCH.md`」")
        # 旧说法（把 RESEARCH.md 与 F/D/M 一起算拒写）必须消失。
        if re.search(r"RESEARCH\.md[^。；]{0,40}对 F ?/ ?D ?/ ?M ?拒写", text):
            out.append("summary 把 `RESEARCH.md` 说成对 F/D/M 拒写（旧说法）")
        if "`RESEARCH.md` / `*-research.md`）对" in text:
            out.append("summary 还是旧句：`RESEARCH.md` 与 `*-research.md` 并列算拒写")

    # ---- 两件共有的内容闸：任何路径上自写 `## 证明` 才拒（这一句两件都要能读出来）
    if "`## 证明`" not in text:
        out.append("summary 没写 `## 证明` 那一档（自写这一节才拒）")
    return out


def rule_source_problems(write_summary: str, edit_summary: str, rule: str) -> list[str]:
    """口径句的单源判据：`fs.write` 逐字读它，`fs.edit` 只许指到它。

    为什么不再要求两条 summary 都逐字复制（2026-11-05 改，改的不是宽度而是口径）：
    同一句话在同一个角色面上印两遍不是"更清楚"，只是把 summary 预算吃掉 ——
    压缩批次的分子里，`fs.edit` 那 103 字符的复制正是把比例顶回 76.35% 的那一笔
    （p239 压缩 `verify_proof` 那次的同一类问题：规则留在该在的那一格，别处只指路）。
    语义要求一条没少：模型从 `fs.edit` 这一格仍要能知道"规则在哪"。

    两条都判（缺一红），且两条各有反真空：
      a `rule` 逐字出现在 `fs.write` 的 summary 里；
      b `fs.edit` 的 summary 用「同 / 见 / 按 fs.write」这种可判定的说法指到它。
    """
    problems: list[str] = []
    if rule not in str(write_summary or ""):
        problems.append("fs.write 的 summary 没逐字读同一处口径句（`D_PROOF_BODY_RULE`）")
    if not re.search(r"(同|见|按)\s*`?fs\.write`?", str(edit_summary or "")):
        problems.append("fs.edit 的 summary 没指到规则在哪（要写「口径同 fs.write」这类说法）")
    return problems


def _registry(tmp_path: pathlib.Path):
    store = Store(tmp_path / "ws")
    store.init()
    return build_registry(store=store, workspace_root=tmp_path / "ws").registry


def test_the_two_summaries_and_the_table_say_the_same_thing(
        tmp_path: pathlib.Path) -> None:
    """正控：两条 summary 与 `RESERVED_ARTIFACT_TABLE` 逐格一致。

    先把表读数本身钉住（否则"两处一致"可能一致在空集上）：证明稿形状对 D/F/M 拒、
    `*-research.md` 对 D/M 拒、`RESEARCH.md` 只有 M 拒（D 那一行已按 2026-11-04 裁定删掉）。
    """
    table = FT.RESERVED_ARTIFACT_TABLE
    assert claimed_roles(table, shapes=("prefix:f-proof-", "suffix:-proof.md")) == [
        "D", "F", "M"], "表读数变了 ⇒ 下面那几条『从表现算』的期望值也跟着变"
    assert claimed_roles(table, shapes=("suffix:-research.md",)) == ["D", "M"]
    assert not any(role == "D" and "RESEARCH" in rule for role, rule in table), (
        "表里又出现了 D 的 `RESEARCH` 行 —— 先确认这是裁定要的，再同步 summary")

    reg = _registry(tmp_path)
    for name in ("fs.write", "fs.edit"):
        problems = summary_problems(name, str(reg.get(name).summary), table)
        assert problems == [], (f"{name} 的 summary 与保留表对不上", problems)


def test_the_old_sentence_is_red(tmp_path: pathlib.Path) -> None:
    """反真空一：summary 改回旧句（或塞回"`RESEARCH.md` 对 F/D/M 拒写"）⇒ 必红。"""
    table = FT.RESERVED_ARTIFACT_TABLE
    problems = summary_problems("fs.write", OLD_WRITE_SUMMARY, table)
    assert problems, "旧句仍被判一致 ⇒ 判据对 summary 那一半是真空"
    assert any("旧" in p or "RESEARCH.md" in p for p in problems), (
        "旧句红的地方不是「RESEARCH.md 对 D 拒写」那一格", problems)

    # 本笔改前（HEAD 2026-11-05：D8 修过之后、本轮扩面之前）那一句：与表一致，
    # 但没有「任何路径」这一刀 —— 新判据必须红，否则 ④ 没把本轮扩面纳入同源判据。
    before_this_fix = (
        "写文本文件（原子落盘；默认不覆盖已有文件）。`f-proof-*` / `*-proof.md` 对 "
        "F/D/M 拒写，`*-research.md` 对 D/M 拒写，M 另拒 `RESEARCH.md`；D 可写 "
        "`RESEARCH.md`，但自写 `## 证明`（含 `out/proofs/*.md`）照拒 —— 要落稿就派 F。")
    problems = summary_problems("fs.write", before_this_fix, table)
    assert any("任何路径" in p for p in problems), (
        "改前那一句（没有「任何路径」）仍判一致 ⇒ 新判据没有覆盖本轮扩面", problems)

    reg = _registry(tmp_path)
    reopened = (str(reg.get("fs.write").summary)
                + "（`RESEARCH.md` 对 F / D / M 拒写）")
    assert summary_problems("fs.write", reopened, table), (
        "把「RESEARCH.md 对 F / D / M 拒写」塞回去仍判一致 ⇒ 反真空失效")

    dropped = (str(reg.get("fs.write").summary)
               .replace("D 可写 `RESEARCH.md`；", "")
               .replace("D 可写 `RESEARCH.md`，", ""))
    assert summary_problems("fs.write", dropped, table), (
        "删掉「D 可写 `RESEARCH.md`」仍判一致 ⇒ 那一格没有被判据读到")


def test_table_drift_is_red(tmp_path: pathlib.Path) -> None:
    """反真空二：表变了而 summary 没跟 ⇒ 必红（两个方向各一发）。

    ① 表里加回一行 `("D", "contains:RESEARCH")`（D 不再能写研究手稿）；
    ② 表里摘掉 D 的证明稿规则（D 的 `f-proof-*` / `*-proof.md` 不再拒）。
    """
    table = FT.RESERVED_ARTIFACT_TABLE
    live = str(_registry(tmp_path).get("fs.write").summary)

    with_d_research = tuple(table) + (("D", "contains:RESEARCH"),)
    problems = summary_problems("fs.write", live, with_d_research)
    assert problems, (
        "表里加回 D 的 `RESEARCH` 行、summary 没跟，却判一致 ⇒ 表那一半是真空")

    without_d_proof = tuple(
        row for row in table
        if not (row[0] == "D" and row[1] in FT.D_PROOF_PATH_RULES))
    assert len(without_d_proof) == len(table) - len(FT.D_PROOF_PATH_RULES), (
        "摘 D 的证明稿规则时摘错了行 ⇒ 打桩点在核一个空集")
    problems = summary_problems("fs.write", live, without_d_proof)
    assert problems, (
        "表里摘掉 D 的证明稿规则、summary 仍说 D 拒，却判一致 ⇒ 表那一半是真空")


def test_the_summary_and_the_content_gate_agree_case_by_case(
        tmp_path: pathlib.Path) -> None:
    """同源（D3）：summary 与拒信共读的那句口径，和 `_d_proof_body_refusal` 的实际判定逐案对齐。

    读的同一处事实是 `FT.D_PROOF_BODY_RULE`（`fs.write` / `fs.edit` 的 summary 与
    `D_PROOF_BODY_MESSAGE` 都拼它，不各写一份）。每一案同时核三处：① 口径句在不在两条
    summary 与拒信里；② 直接调内容闸 `_d_proof_body_refusal` 的结论；③ 经 registry 的
    真工具结论。改前 summary 说"照拒"而实现对"引用 F 的稿"放行 ⇒ D3 就是这一格。
    """
    import hashlib

    root = tmp_path / "ws"
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry

    # 盘上落一份 F 的证明稿（框架那一侧写的，直接落盘绕过 fs 闸）。
    f_rel = "reports/f-proof-000001.md"
    target = root / f_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# F 的证明手稿\n\n## 证明\n\n1. 由定义直接得到。\n", encoding="utf-8")
    f_sha = hashlib.sha256(target.read_bytes()).hexdigest()

    plain = "# 研究手稿\n\n## 成果概述\n\n收录 F 侧成果。\n"
    own = "# 随手记\n\n## 证明\n\n1. 我自己写完了。\n"
    with_cite = plain + f"\n## 证明\n\n（转载 F 的 `{f_rel}`，sha256={f_sha}）\n"
    with_sha = plain + f"\n## 证明\n\n（转载 F 的稿，sha256={f_sha}）\n"
    with_air = plain + "\n## 证明\n\n（引用 `reports/f-proof-999999.md`）\n"
    with_heading_idea = plain + "\n## 证明思路\n\n先引 `stmt:000000`。\n"

    cases = [
        ("notes/x.md", own, True),
        ("reports/x.md", own, True),
        ("out/proofs/x.md", own, True),
        ("reports/RESEARCH.md", with_cite, False),
        ("reports/RESEARCH.md", with_sha, False),
        ("reports/RESEARCH.md", with_air, True),
        ("reports/RESEARCH.md", plain, False),
        ("reports/RESEARCH.md", with_heading_idea, False),
    ]

    # ① 口径句只有一处：`fs.write` 逐字读它，`fs.edit` 只许指到它（判据见
    #    `rule_source_problems`；不只是"读得到"，还要求 `fs.edit` 指得回 `fs.write`）。
    rule = FT.D_PROOF_BODY_RULE
    write_summary = str(reg.get("fs.write").summary)
    edit_summary = str(reg.get("fs.edit").summary)
    assert rule_source_problems(write_summary, edit_summary, rule) == [], (
        rule_source_problems(write_summary, edit_summary, rule))
    assert rule in FT.D_PROOF_BODY_MESSAGE.format(path="x"), "正文拒信没读同一处口径句"

    # 反真空：两条各删一处 ⇒ 同一条判据必须红（否则上面那句"指到规则"是纸面通过）。
    assert rule_source_problems(write_summary.replace(rule, ""), edit_summary, rule), (
        "把 RULE 从 fs.write 的 summary 里删掉却没红 ⇒ 单源判据没在看那一格")
    assert rule_source_problems(
        write_summary, edit_summary.replace("同 fs.write", "同 fs.writx"), rule), (
        "把 fs.edit 里「同 fs.write」那句删掉却没红 ⇒ 「指到规则在哪」是纸面通过")

    for rel, body, refused in cases:
        direct = FT._d_proof_body_refusal(rel, "D", body, root)
        assert (direct is not None) is refused, (rel, "直调内容闸的结论与期望不符", direct)
        with calling_as("t-probe-rule", "D"):
            res = reg.call("fs.write", role="D", path=rel, content=body, overwrite=True)
        assert (res.ok is False) is refused, (rel, body[:40], res)
        if refused:
            assert res.meta.get("kind") == KIND, (rel, res.meta)
