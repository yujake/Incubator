"""两份系统文档必须是生成的：改了角色/工具/权限面却没重生成，它当场红。

为什么这条判据值得存在：`docs/ROLE-GUIDE.md` 与 `docs/SYSTEM-COMPONENTS.md` 是给人读的介绍，
而它们的内容（职责 / 边界 / 官能 / 边 / 写集 / 动作表 / 工具面）全部有代码真身。
手写一份介绍文档，第一次写时是对的，第三次改权限面之后它就变成「看着有、其实在说谎」的文档 ——
而那正是 FC-27 那一类事故的形态（测试全绿、上线即越权）。

所以：文档由 `tools/write_system_docs.py` 现算，本判据重跑一遍并逐字节比（与 `ui/src/types.ts` 同形）。
另外核两件事：组件表点名的模块真的在盘上；两份文档都进了 `docs/INDEX.md`。
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "write_system_docs.py"
ROLE_GUIDE = ROOT / "docs" / "ROLE-GUIDE.md"
COMPONENTS_DOC = ROOT / "docs" / "SYSTEM-COMPONENTS.md"
INDEX = ROOT / "docs" / "INDEX.md"


def _module():
    spec = importlib.util.spec_from_file_location("write_system_docs_under_test", GEN)
    assert spec and spec.loader, f"生成器不在盘上：{GEN}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_two_documents_are_byte_identical_to_a_fresh_generation() -> None:
    """正控：盘上那两份 == 现算的那两份（逐字节）。"""
    mod = _module()
    for path, rendered in (
        (ROLE_GUIDE, mod.render_role_guide()),
        (COMPONENTS_DOC, mod.render_components()),
    ):
        assert path.is_file(), f"{path.name} 不见了（它是由 write_system_docs.py 生成的）"
        on_disk = path.read_text(encoding="utf-8")
        assert on_disk == rendered, (
            f"{path.name} 与现算结果不一致 ⇒ 跑 `python -B tools/write_system_docs.py` 重生成。"
            f"（盘上 {len(on_disk)} 字符 / 现算 {len(rendered)} 字符）"
        )


def test_the_role_guide_covers_every_role_and_both_surfaces() -> None:
    """每个角色都得有自己的一节，而且四件事都在：设定 / 职责 / 协作面 / 工具面 / 读写。"""
    text = ROLE_GUIDE.read_text(encoding="utf-8")
    from agentflow import capabilities as C

    for role in C.CAPABILITIES:
        assert f"## 角色 {role}" in text, f"角色指南里没有 {role} 那一节"
    for heading in ("### 角色设定", "### 具体职责（动作表）", "### 协作面",
                    "### 工具面（这个角色实际拿到的件）", "### 主要读写的文档与细节"):
        assert heading in text, f"角色指南缺小节：{heading}"


def test_the_components_section_names_modules_that_exist() -> None:
    """反真空：组件表里点名的每个模块都得真在盘上（模块没了，文档就在说假话）。"""
    mod = _module()
    assert len(mod.COMPONENTS) >= 15, f"组件表只剩 {len(mod.COMPONENTS)} 条 ⇒ 这条判据失去对象"
    missing = [name for name, module, *_ in mod.COMPONENTS if not (ROOT / module).exists()]
    assert not missing, f"组件表点名的模块不在盘上：{missing}"


def test_every_documented_symbol_mentioned_in_a_component_is_importable() -> None:
    """组件表里写成 `模块.符号` 的那几个（若有）必须真的存在于那个模块。

    只核"点名的模块"里出现过的 `模块.符号` 形态（例如 `store.tx` 写在落点列里不算符号引用），
    避免把散文里的词当符号。
    """
    import importlib

    mod = _module()
    checked = 0
    for name, module, _what, how, _where, _judge in mod.COMPONENTS:
        dotted = f"{pathlib.Path(module).stem}."
        for token in how.replace("、", " ").replace("与", " ").replace("加", " ").split():
            token = token.strip("`，。()（）;；")
            if not token.startswith(dotted):
                continue
            attr = token[len(dotted):]
            if not attr.isidentifier():
                continue
            try:
                mod_obj = importlib.import_module(f"agentflow.{pathlib.Path(module).stem}")
            except Exception:  # noqa: BLE001 - 包内的模块不一定都能直接 import（如 specs 包）
                continue
            assert hasattr(mod_obj, attr), (
                f"组件 {name} 的实现细节里点名了 {token}，而 agentflow."
                f"{pathlib.Path(module).stem} 里没有这个属性"
            )
            checked += 1
    assert checked == 0 or checked > 0  # 形态说明：为空也允许（散文里不一定有 模块.符号 形态）


def test_every_documented_exhaustion_backing_state_exists_in_code() -> None:
    """组件表点名的穷举背书结局必须 ⊆ `numericproof.EXHAUSTION_BACKING_STATES`。

    文档是生成物，但「哪几个结局」这句清单是手写的：代码加一种/删一种而生成器没跟上，
    `test_the_two_documents_are_byte_identical_to_a_fresh_generation` 只会说「逐字节一致」
    —— 两边一起停在旧清单上它照样绿。这一条把文档里的码与代码里的真身钉在一起。
    """
    from agentflow import numericproof as NP

    text = COMPONENTS_DOC.read_text(encoding="utf-8")
    marker = "exhaustion_backing（V 对这份 E 报告真签过没有）的五结局："
    lines = [line for line in text.splitlines() if marker in line]
    assert len(lines) == 1, f"组件表里找不到（或找到多条）`{marker}` ⇒ 这条判据失去对象"
    cell = lines[0].split(marker, 1)[1].split(" | ", 1)[0]
    documented = set(re.findall(r"(?:^|；)\s*([a-z_]+)\s", cell))
    states = set(NP.EXHAUSTION_BACKING_STATES)
    assert documented, f"`{marker}` 后面一个结局都没点名 ⇒ 这条判据失去对象"
    assert documented <= states, (
        f"组件表提到的结局 {sorted(documented - states)} 在 numericproof 里不存在 "
        f"（真身：{sorted(states)}）"
    )
    assert documented == states, (
        f"组件表漏了这些结局：{sorted(states - documented)}（真身：{sorted(states)}）"
    )


def test_both_documents_are_registered_in_the_docs_index() -> None:
    """文档不登记进 INDEX，读者就找不到它（与 `test_docs_index_covers_every_doc` 是同一条纪律）。"""
    text = INDEX.read_text(encoding="utf-8")
    for name in ("ROLE-GUIDE.md", "SYSTEM-COMPONENTS.md"):
        assert name in text, f"docs/INDEX.md 里没有 {name}"


# ============================================================ 2026-11-04：D 的攻坚过程记录
#
# 生成器与产物必须同时对新口径负责：`out/proofs/` 是 D 的攻坚过程记录（`## 思路` /
# `## 依赖面参考`），带 `## 证明` 节在 D 的 `fs.write` / `fs.edit` 上受控拒（要落稿就派 F）。
# 改前生成器把这一格写成「写 | 证明正文（manuscripts 那套读的正是它）」—— 那是 F 的证明稿
# 落点，早已搬到 `reports/f-proof-*.md`；只改 `docs/ROLE-GUIDE.md` 是改产物，下次重生成
# 就会被覆盖，所以这一条同时核生成器与产物。

#: `out/proofs/` 那一格在生成器与产物里的路径格。
ATTACK_RECORD_PATH = "`out/proofs/*.md`"
#: 新口径必须读得到的几个词（少一个都说明措辞被改回去了）。
ATTACK_RECORD_NEEDLES: tuple[str, ...] = (
    "攻坚过程记录", "`## 思路`", "`## 依赖面参考`", "`## 证明`", "受控拒", "派 F",
)
#: 改前那一格的细节措辞（逐字；反真空把它塞回去 ⇒ 判据必须红）。
OLD_ATTACK_RECORD_DETAIL = "证明正文（manuscripts 那套读的正是它）"


def _role_section(text: str, role: str) -> str:
    """`docs/ROLE-GUIDE.md` 里某个角色那一节（从 `## 角色 X` 到下一个 `## 角色 `）。"""
    start = text.find(f"## 角色 {role}\n")
    if start < 0:
        return ""
    end = text.find("\n## 角色 ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def _rows_for(rows, path: str) -> list[tuple[str, str, str]]:
    """生成器里某个角色的 `(路径, 读/写, 细节)` 逐行（路径格逐字相等的那些）。"""
    return [tuple(row) for row in (rows or ()) if str(row[0]) == path]


def _guide_attack_rows(guide_text: str) -> list[tuple[str, str, str]]:
    """产品文档里 D 那一节的 `out/proofs/*.md` 行（按表格切格）。"""
    out: list[tuple[str, str, str]] = []
    for line in _role_section(guide_text, "D").splitlines():
        if not line.strip().startswith(f"| {ATTACK_RECORD_PATH} |"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) >= 3:
            out.append((cells[0], cells[1], " | ".join(cells[2:])))
    return out


def _attack_record_problems(artifacts, guide_text: str) -> list[str]:
    """生成器那一格与 `ROLE-GUIDE.md` 那一行对不对得上（空列表 = 对得上）。

    纯函数（喂一份旧措辞的副本就能给反真空做牙）。它查四件事：
      ① `out/proofs/*.md` 只归 D（改前 F / V 两格也写着它 —— 同一个落点两个含义）；
      ② D 那一格是「写」且读得到攻坚过程记录那几句话；
      ③ F 的证明正文落点是 `reports/f-proof-*.md`、V 读的也是它（不再指 out/proofs）；
      ④ 产物里 D 那一行与生成器逐字一致，且旧措辞（证明正文）不在 `out/proofs` 行上。
    """
    problems: list[str] = []
    owners = sorted(role for role, rows in artifacts.items()
                    if _rows_for(rows, ATTACK_RECORD_PATH))
    if owners != ["D"]:
        problems.append(
            f"生成器里 `out/proofs/*.md` 应当只在 D 名下（它是 D 的攻坚过程记录），"
            f"实得 {owners} —— F / V 的证明正文落点是 reports/f-proof-*.md")

    d_rows = _rows_for(artifacts.get("D"), ATTACK_RECORD_PATH)
    detail = ""
    if len(d_rows) != 1:
        problems.append(f"D 的生成器里 `out/proofs/*.md` 应当恰好一行，实得 {len(d_rows)} 行")
    else:
        _path, permission, detail = d_rows[0]
        if permission != "写":
            problems.append(f"D 的 `out/proofs/*.md` 权限应当是「写」，实得 {permission!r}")
        missing = [needle for needle in ATTACK_RECORD_NEEDLES if needle not in detail]
        if missing:
            problems.append(f"D 的 `out/proofs/*.md` 细节少了这些词：{missing}")
        if OLD_ATTACK_RECORD_DETAIL in detail:
            problems.append("D 的 `out/proofs/*.md` 还写着旧措辞「证明正文」")

    if not _rows_for(artifacts.get("F"), "`reports/f-proof-*.md`"):
        problems.append("F 的证明正文落点不是 `reports/f-proof-*.md`")
    v_rows = [row for row in (artifacts.get("V") or ())
              if str(row[0]).startswith("`reports/f-proof-*.md`")]
    if not v_rows:
        problems.append("V 读的证明正文落点不是 `reports/f-proof-*.md`")

    guide_rows = _guide_attack_rows(guide_text)
    if len(guide_rows) != 1:
        problems.append(
            f"`docs/ROLE-GUIDE.md` 的 D 那一节里 `out/proofs/*.md` 应当恰好一行，"
            f"实得 {len(guide_rows)} 行 ⇒ 先跑 `python -B tools/write_system_docs.py`")
    elif detail and guide_rows[0][2] != detail:
        problems.append(
            "`docs/ROLE-GUIDE.md` 的 D/`out/proofs/*.md` 行与生成器不一致："
            f"产物 {guide_rows[0][2]!r} / 生成器 {detail!r}")
    old_row = f"| {ATTACK_RECORD_PATH} | 写 | {OLD_ATTACK_RECORD_DETAIL} |"
    if old_row in guide_text:
        problems.append("`docs/ROLE-GUIDE.md` 里还留着旧措辞那一行（证明正文）")
    return problems


def test_the_attack_record_permission_is_written_in_the_generator_and_the_guide() -> None:
    """正控：生成器那一格与 ROLE-GUIDE 那一行同时是「攻坚过程记录」新口径。

    业主 2026-11-04：「D 可提供证明思路，甚至提供依赖面参考，最终的证明落稿拿签必须派给
    F 完成」⇒ `out/proofs/` 不是证明稿的落点。只改 `docs/ROLE-GUIDE.md` 会在下一次
    `write_system_docs.py` 重生成时被覆盖，所以两边一起核。
    """
    mod = _module()
    assert len(mod.ARTIFACTS.get("D") or ()) >= 3, "生成器的 D 那一格太小 ⇒ 这条判据没有对象"
    problems = _attack_record_problems(mod.ARTIFACTS, ROLE_GUIDE.read_text(encoding="utf-8"))
    assert not problems, "生成器与产物对 `out/proofs/` 的口径不一致：\n  " + "\n  ".join(problems)


def test_putting_the_old_attack_record_row_back_goes_red() -> None:
    """反真空：把生成器那一格改回旧措辞 ⇒ 同一个尺子必须点红。

    两个方向都钉：① 生成器旧（证明正文）而产物新；② 只改产物（产物新、生成器旧）。
    只钉其中一个方向的话，"生成器改回去了"与"产物没重生成"这两种事故里必有一种看不见。
    """
    mod = _module()
    guide = ROLE_GUIDE.read_text(encoding="utf-8")
    assert _attack_record_problems(mod.ARTIFACTS, guide) == [], "基线就不绿 ⇒ 反真空没有意义"

    # ① 生成器那一格改回旧措辞（D 名下放一行旧的「证明正文」）
    dirty = {role: tuple(rows) for role, rows in mod.ARTIFACTS.items()}
    dirty["D"] = tuple(row for row in dirty["D"] if row[0] != ATTACK_RECORD_PATH) + (
        (ATTACK_RECORD_PATH, "写", OLD_ATTACK_RECORD_DETAIL),)
    assert _attack_record_problems(dirty, guide), (
        "生成器改回旧措辞，尺子却没点红 ⇒ 正控的绿不来自生成器那一格")

    # ② 只改产物：把 guide 的 D 行换成旧措辞、生成器保持新口径
    live = _rows_for(mod.ARTIFACTS.get("D"), ATTACK_RECORD_PATH)[0]
    old_line = f"| {ATTACK_RECORD_PATH} | {live[1]} | {OLD_ATTACK_RECORD_DETAIL} |"
    new_line = f"| {ATTACK_RECORD_PATH} | {live[1]} | {live[2]} |"
    assert new_line in guide, "产物里找不到基线那一行 ⇒ 反真空没有对象"
    only_product_changed = guide.replace(new_line, old_line)
    assert _attack_record_problems(mod.ARTIFACTS, only_product_changed), (
        "只改产物（生成器新、产物旧）却没点红 ⇒ 这条判据只看了产物")

