"""R8 废案清仓的退场判据（A-1 的菜单入口 + A-2 的教学段 + A-8/A-9 的文档表）。

为什么要这个文件：`draft/65` §3 的教训 1 逐字要求"新增主入口 X ⇒ 同批把 X 加进 `MENU` +
写一条元判据断言 `X in MENU 文本`"。这条纪律在 R8 落地时只能以负向形态写：
`demo` 的菜单入口退场了，而 `run-agent` 并没有被加进 MENU（那正是 A-1 记下的坑，
`draft/65a §A-1`）⇒ 这里断言"菜单里没有 demo / 离线自检"，并把"run-agent 不在菜单里"
如实登记成一条负控（不写成"已覆盖"）。文档那两条钉住"旧路径"标注还在，
免得下一次清理把标注连同被清理的东西一起抹掉。
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _cli():
    from agentflow import cli

    return cli


def _doc(rel: str) -> str:
    """文档的真实落点：`agentflow/` 本目录优先、「仓库根」兜底。

    2026-10-18（业主）：`README.md` 挪到仓库根（`D:\\Incubator/README.md`）。本文件原先
    写死 `ROOT / rel`，README 一搬，这一族的两条判据就变成 `FileNotFoundError`
    —— 那不是"文档漂了"，是判据把对象读丢了（两者的处置完全不同）。
    兜底口径与 `tests/test_release_all.py::doc_path` 及
    `tests/test_doc_code_consistency.py::_resolve` 逐字同形；两处都找不到 ⇒ 红
    （"找不到"不许读成"通过"）。
    """
    for base in (ROOT, ROOT.parent):
        cand = base / rel
        if cand.is_file():
            return cand.read_text(encoding="utf-8")
    raise AssertionError(
        f"读不到 `{rel}`（`{ROOT}` 与仓库根 `{ROOT.parent}` 都没有）⇒ 判据的对象没了，不是通过")


# ------------------------------------------------------------------ A-1（菜单入口退场）

def test_the_demo_menu_entry_is_retired():
    cli = _cli()
    text = "\n".join(t for _k, t, _f in cli.MENU)

    assert "离线自检" not in text, f"A-1 退场的菜单项又回来了：{text}"
    assert "demo" not in text, f"A-1 退场的菜单项又回来了：{text}"
    # 反真空：把 MENU 清空也能让上面两条绿 ⇒ 先钉住"菜单还在"
    assert len(cli.MENU) >= 4, cli.MENU
    # 负控（如实登记，不写成"已覆盖"）：`run-agent` 不在菜单里 —— 这正是 A-1 记的坑。
    # 哪天有人把它加进去，这一条会红；那时应当把它改成正向断言，并把 A-1 的坑划掉。
    assert "run-agent" not in text, (
        "菜单里出现了 run-agent ⇒ A-1 的坑已经补上，请把这条负控改成正向断言（别再留着旧结论）")


def test_every_menu_key_has_an_action_and_the_retired_key_is_gone():
    cli = _cli()
    want = {k for k, _t, _f in cli.MENU}
    assert set(cli.SHELL_ACTIONS) == want, (
        f"菜单键与处理函数表对不上：{sorted(cli.SHELL_ACTIONS)} vs {sorted(want)}")
    assert "5" not in cli.SHELL_ACTIONS, "A-1 摘掉的第 5 键又回来了"


# ------------------------------------------------- A-2（旧流水线教学段）+ A-8/A-9（旧路径标注）

def _hits_with_context(text: str, needle: str, *, window: int = 4) -> list[str]:
    """含 `needle` 的行 + 它后面 `window` 行（代码块里的标注落在围栏之后再下一行）。"""
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if needle in line:
            out.append("\n".join(lines[i:i + window + 1]))
    return out


def test_the_retired_project_section_stays_retired():
    readme = _doc("README.md")
    # 判据钉的是"那段教学（教怎么跑旧流水线）不在了"，不是"那几个词一次都不许出现"——
    # 留痕行本身就逐字引了它（`draft/65` §1.3 第 1 块要求"逐字引出处分句"）。
    for gone in ("python -m agentflow.cli project plan --books D:\\books --topic",
                 "python -m agentflow.cli project run --books D:\\books --extract",
                 "--extract-rounds 7"):
        assert gone not in readme, f"A-2 删掉的旧流水线教学段又回来了（含 {gone!r}）"
    assert "已退场" in readme, "A-2 的留痕行不见了（删段必须留一行指向 `draft/65a`）"


def test_every_cli_demo_mention_is_tagged_as_the_old_path():
    # 2026-10 文档拆分：A-8/A-9 那两张"旧路径"标注表随规范一起搬走 ——
    # 它们现在住在 `docs/DEVELOPMENT-APPENDIX.md`（历史那一半），`DEVELOPMENT.md`
    # 只剩一页入口指针。判据的对象没变（"每一处 `cli demo` 都要标旧路径"），
    # 变的只是它读哪个文件：README 按「本目录优先 / 仓库根兜底」解析，
    # 标注表读它现在的落点，两边都找不到就红（`_doc` 那条）。
    for rel in ("README.md", "docs/DEVELOPMENT-APPENDIX.md"):
        text = _doc(rel)
        hits = _hits_with_context(text, "cli demo")
        assert hits, f"{rel}: `cli demo` 一个落点都没有 ⇒ 这条判据失去对象（先查是不是整段删了）"
        for block in hits:
            assert "旧路径" in block, f"{rel}: `cli demo` 的落点没标「旧路径」：{block[:120]!r}"
    # 反真空：标注不许把主路径挤掉 —— README 必须仍然写着 run-agent
    assert "run-agent" in _doc("README.md"), "README 里没有 run-agent（主路径）"
