# -*- coding: utf-8 -*-
r"""业主裁定：「需要保证后续写论文不出现异常字符，给 H 加个工具审」。

## 这一条判据守的是什么

论文是要发出去的东西，而「异常字符」这一类错误有一个共同特征：「看起来没问题」。
`main.tex` 里一行 `…（原文 1188 字，已截断）` 在编辑器里像是排版注释，在 PDF 里像是
一句中文小字；一个零宽连接符（U+200B）在编辑器里根本看不见，在 LaTeX 里会
把 `\cite` 与前面的词粘成一个 token；一个不换行空格（U+00A0）会让断行算法
在那一段彻底失效。这些都不会让 `test_*` 变红，也不会让编译失败 —— 它们只在
「读者手里」变成错字、错行、错引用。

所以判据不是「H 有没有一件工具」，而是「这件工具报的读数是不是真的」。四条各钉一件事：

- g1：真实的论文正文（`projects/paper-rewrite-80/out/paper/main.tex`，只读）里
  那 9 个 CJK 字符必须一条不少地被报出来，且 `path` 指的就是那份文件、`line` 是 936。
  那条正文昨天是真的：`…（原文 1188 字，已截断）` = 6 个统一表意（原文/字/已/截/断）
  + 3 个全角标点（`（` `，` `）`）。把 CJK 那一档收窄成「只有 U+4E00–9FFF」，
  这条只数到 6 ⇒ 红（这正是 `counts['cjk'] == 9` 不能写成 `>= 1` 的理由：
  「报出了几个」与「该报的都在」是两件事）。
- g2：负控的正面 —— 一份干净的英文 tex 必须 `counts` 全 0 且 `checked=True`。
  没有这一条，「永远报一堆东西」也能通过 g1。
- g3：读不成（路径不存在 / 是个二进制文件）⇒ `checked=False` + `reason` 非空。
  不许折成「零命中」：那正是本项目反复踩的坑（三态纪律 —— 「没查成」与
  「查过了、干净」必须分得开，`review.scan_document` 的 `dep_check` 同形）。
- g4：零宽字符与替换字符各造一个样本 ⇒ 各自被认出且 `kind` 分档正确。
  用来钉「六档不是摆设」：这两档在真实论文里几乎不出现，只有造样本才验得到。
- g5（附带）：这件工具只声明给 H —— 别的角色（含另外两个只读角色 C / V）拿不到它。
  「H 能审」与「谁都能审」在权限面上是两件事。

## 这一条判据不证明什么

它不检查 `excerpt` 写得好不好（那是给人看的），也不检查 H 会不会用这件工具
（那是提示词面的事，见 `tests/test_agent_prompts.py`）。它只回答一个问题：
「这把尺子量出来的数，是不是真的」
"""

from __future__ import annotations

import pathlib

import pytest

from agentflow.store import Store
from agentflow.tools import ROLES, build_registry
from agentflow.tools import review_tools as RT
from agentflow.tools.base import ToolRegistry

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 被判的那份真实论文正文（只读：本文件任何一行都不许写它）。
#: `projects/` 整个目录在 `.gitignore` 里，所以这条判据依赖工作机上真的跑过那一趟
#: —— 它不在了 ⇒ 下面那条 `pytest.fail` 会如实说「没查成」，而不是静默跳过。
TEX_REL = "projects/paper-rewrite-80/out/paper/main.tex"
TEX = REPO / pathlib.Path(TEX_REL)

#: 那一行 / 那 9 个字符的读数（口径见模块 docstring 的 g1）。
CJK_LINE = 936
CJK_CHARS = 9

#: 六档 `kind` 的受控词表（`counts` 的键域；每一档都要在读数里出现，哪怕是 0）。
KINDS = ("cjk", "control", "zero_width", "replacement", "bidi", "nbsp")


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    return ws


def _full_registry(tmp_path: pathlib.Path) -> ToolRegistry:
    """整张工具面（临时工作区里装配，不碰仓库里的任何目录）。"""
    ws = _ws(tmp_path)
    return build_registry(store=Store(ws), workspace_root=ws, roles=tuple(ROLES),
                          strict=True).registry


def _review_registry(root: pathlib.Path) -> ToolRegistry:
    """只装审校那一组工具，工作区根钉在 `root` 上（g1 要读仓库里的真论文）。

    为什么不直接用 `_full_registry` 再把根指到仓库：装配整张工具面会给
    `workspace_root` 铺一堆簿记（`out/clock` 之类）。g1 只需要一条「从
    `register()` 装进来的真工具」的路径，钉一个只读的根就够。
    """
    reg = ToolRegistry(name="h-integrity")
    RT.register(reg, store=None, root=root)
    return reg


def _scan(reg: ToolRegistry, *paths: str, limit: int | None = None) -> dict:
    """调一次工具，返回 `data`（失败的调用直接判红 —— 这条判据要的是读数）。"""
    args: dict = {"paths": list(paths)}
    if limit is not None:
        args["limit"] = limit
    res = reg.call("review.scan_text_integrity", role="H", **args)
    assert res.ok, f"工具调用失败（{res.meta.get('kind')}）：{res.error}"
    assert isinstance(res.data, dict), f"data 不是字典：{type(res.data).__name__}"
    return res.data


def _total(counts: dict) -> int:
    return sum(int(counts.get(k, 0)) for k in KINDS)


# ---------------------------------------------------------------- g1：真论文


def test_g1_the_real_paper_reports_all_nine_cjk_characters(tmp_path: pathlib.Path) -> None:
    """g1：真论文正文里那 9 个 CJK 字符必须一条不少，`path` / `line` 指得准。

    「只读」是这条判据的一部分：`_review_registry` 的工具只声明 `side_effect="read"`，
    而本文件从头到尾没有一处写 `TEX`（改它的是 G，不是 H）。
    """
    if not TEX.is_file():
        pytest.fail(
            f"被审的论文正文不在盘上：{TEX}（`projects/` 已在 .gitignore 里）⇒ "
            "这一条「没查成」，不是「论文里没有异常字符」")

    before = TEX.read_bytes()
    reg = _review_registry(REPO)
    data = _scan(reg, TEX_REL)

    assert data["checked"] is True, f"真论文读不成？reason={data['reason']!r}"
    assert data["counts"]["cjk"] == CJK_CHARS, (
        f"报出 {data['counts']['cjk']} 个 CJK 字符，而那一行有 {CJK_CHARS} 个"
        f"（6 个统一表意 + 3 个全角标点）—— 少报就是漏检："
        f"{[(f['line'], f['codepoint']) for f in data['findings'] if f['kind'] == 'cjk']}")
    assert _total(data["counts"]) == CJK_CHARS, (
        f"这份正文除了那 9 个 CJK 之外还有别的异常字符：counts={data['counts']}")

    # `path` 必须是「那份文件」（工具返回工作区相对路径 ⇒ 拼回去要指到同一个文件）。
    scanned = [str(p) for p in data["scanned"]]
    assert scanned == [TEX_REL], f"`scanned` 不是这次真的读过的那一份：{scanned}"
    assert (REPO / data["findings"][0]["path"]).resolve() == TEX.resolve(), (
        f"findings 里的 path 指的不是被审的那份文件：{data['findings'][0]['path']!r}")

    cjk = [f for f in data["findings"] if f["kind"] == "cjk"]
    assert {f["line"] for f in cjk} == {CJK_LINE}, (
        f"CJK 字符的行号不是第 {CJK_LINE} 行：{sorted({f['line'] for f in cjk})}")
    # 逐字码位（6 表意 + 3 全角）—— 「9 个」这个数由它们拼出来，不是另一份口径。
    assert [f["codepoint"] for f in cjk] == [
        "U+FF08", "U+539F", "U+6587", "U+5B57", "U+FF0C", "U+5DF2", "U+622A",
        "U+65AD", "U+FF09",
    ], [(f["column"], f["codepoint"]) for f in cjk]
    assert [f["column"] for f in cjk] == [2, 3, 4, 11, 12, 13, 14, 15, 16], (
        f"列号与那一行对不上：{[f['column'] for f in cjk]}")

    # 只读：扫完之后盘上那份文件一个字节都没变。
    assert TEX.read_bytes() == before, "这次扫描改动了论文正文 —— 那已经不是只读工具了"


# ---------------------------------------------------------------- g2：干净英文


def test_g2_a_clean_english_tex_is_zero_and_checked_true(tmp_path: pathlib.Path) -> None:
    """g2 负控：干净的英文 tex ⇒ `counts` 全 0 且 `checked=True`。

    没有这一条，「永远报一堆东西」也能让 g1 绿。
    """
    ws = _ws(tmp_path)
    clean = ws / "clean.tex"
    clean.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "The abelian group $G$ is commutative; see \\cite{lit000001}.\n"
        "\\end{document}\n",
        encoding="utf-8",
        newline="",
    )

    reg = _full_registry(tmp_path)
    data = _scan(reg, "clean.tex")

    assert data["checked"] is True, f"干净文件读不成：reason={data['reason']!r}"
    assert data["findings"] == [], f"干净英文 tex 里报出了东西：{data['findings']}"
    assert {k: data["counts"][k] for k in KINDS} == {k: 0 for k in KINDS}, (
        f"counts 不是全 0：{data['counts']}")
    # 反真空：六档一个不少地出现在 counts 里 —— 少一档就意味着「那一档没被查」，
    # 而它与「那一档是 0」在读数上必须分得开（三态纪律）。
    assert sorted(data["counts"]) == sorted(KINDS), (
        f"counts 的键域不是六档全在：{sorted(data['counts'])}")


# ---------------------------------------------------------------- g3：读不成


def test_g3_an_unreadable_path_is_checked_false_not_zero_hits(tmp_path: pathlib.Path) -> None:
    """g3：读不成 ⇒ `checked=False` + `reason` 非空，不许折成「零命中」。

    两种「读不成」各一次：
      (a) 路径不存在（盘上没有这份文件）；
      (b) 盘上有，但它是二进制（不是 UTF-8 文本）⇒ 那一份没有「字符」可数。
    """
    ws = _ws(tmp_path)
    reg = _full_registry(tmp_path)

    missing = _scan(reg, "no/such/file.tex")
    assert missing["checked"] is False, (
        "路径不存在却报 `checked=True` ⇒ 「没查成」被折成了「查过了、干净」")
    # 理由串是这条判据唯一可审的部分：空的 reason 与「查过了、干净」在读数上同形。
    assert str(missing["reason"]).strip(), "读不成却没给理由"
    assert missing["findings"] == [] and _total(missing["counts"]) == 0
    assert missing["scanned"] == [], f"没读成的路径却进了 scanned：{missing['scanned']}"

    binary = ws / "binary.tex"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe\x01binary-not-text")
    got = _scan(reg, "binary.tex")
    assert got["checked"] is False, (
        "二进制文件却报 `checked=True` ⇒ 它要么被当成空文本、要么被硬解成乱码字符")
    assert str(got["reason"]).strip(), "二进制文件读不成却没给理由"
    assert got["findings"] == [] and _total(got["counts"]) == 0
    assert got["scanned"] == []


# ---------------------------------------------------------------- g4：两只不常见的档


def test_g4_zero_width_and_replacement_are_told_apart(tmp_path: pathlib.Path) -> None:
    """g4：零宽字符（U+200B）与替换字符（U+FFFD）各造一个样本 ⇒ 各自被认出。

    这两档在真实论文里几乎不出现（那正是它们危险的原因：没人会注意到），
    所以只有造样本才验得到。判据同时钉住 `kind` 的分档 —— 两档折成一档
    （比如都报 `control`）时这条会红。
    """
    ws = _ws(tmp_path)
    zw = ws / "zero-width.tex"
    zw.write_text("smart\u200bword and a soft\u200dbreak\n", encoding="utf-8", newline="")
    rep = ws / "replacement.tex"
    rep.write_text("bad \ufffd byte\n", encoding="utf-8", newline="")

    reg = _full_registry(tmp_path)

    got = _scan(reg, "zero-width.tex")
    assert got["checked"] is True, got["reason"]
    assert got["counts"]["zero_width"] == 2, got["counts"]
    assert [f["kind"] for f in got["findings"]] == ["zero_width", "zero_width"], (
        f"零宽字符被归到了别的档：{[(f['kind'], f['codepoint']) for f in got['findings']]}")
    assert [f["codepoint"] for f in got["findings"]] == ["U+200B", "U+200D"]
    assert [f["column"] for f in got["findings"]] == [6, 22]

    got = _scan(reg, "replacement.tex")
    assert got["checked"] is True, got["reason"]
    assert got["counts"]["replacement"] == 1, got["counts"]
    assert [(f["kind"], f["codepoint"]) for f in got["findings"]] == [("replacement", "U+FFFD")]

    # 一次扫两份：两条路径都在 `scanned` 里，`detail` 逐路径给读数（不是只给合计）。
    both = _scan(reg, "zero-width.tex", "replacement.tex")
    assert sorted(both["scanned"]) == ["replacement.tex", "zero-width.tex"]
    assert len(both["detail"]) == 2, f"detail 不是逐路径的：{both['detail']}"
    assert both["counts"]["zero_width"] == 2 and both["counts"]["replacement"] == 1


# ---------------------------------------------------------------- g5：只给 H


def test_g5_only_h_can_see_the_text_integrity_scanner(tmp_path: pathlib.Path) -> None:
    """g5：这件工具只声明给 H（另外两个只读角色 C / V 也拿不到它）。

    「H 能审」与「谁都能审」在权限面上是两件事：审校者的尺子如果人人都有，
    「谁审的」就不再说明任何事。
    """
    reg = _full_registry(tmp_path)
    assert "review.scan_text_integrity" in {s.name for s in reg.for_role("H")}, (
        "H 的工具面上没有这件只读审计工具")
    others = [r for r in ROLES if r != "H"
              if "review.scan_text_integrity" in {s.name for s in reg.for_role(r)}]
    assert others == [], f"这些角色不该拿到它：{others}"
    spec = reg.get("review.scan_text_integrity")
    assert spec.roles == ("H",), spec.roles
    assert spec.side_effect == "read", spec.side_effect
