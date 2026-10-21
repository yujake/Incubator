"""论文语言判据：`out/paper/main.tex` 全文必须是英文（CJK 字符数 == 0）。

这一条守什么（业主 2026-10-18 改口径后的唯一硬判据）：同一天的两版口径在这里分界：导言区只是推荐配方 —— mp3 那份（`ctexart` +
`amsmath,amssymb,amsthm` +`geometry(margin=2.5cm)` + `booktabs` + 三个 `\\theoremstyle` 段与九个 `\\newtheorem`）
是业主看着最舒服的一份，写进提示词时说的是「推荐这样写，你可以按论文需要调整宏包与定理环境名」⇒ 本文件不断言导言区与模板逐字一致，也不断言宏包集合、`\\author` / `\\date` 的写法 —— 那些都在"推荐"那一侧，
判它们等于把建议变成合同。- 语言是硬线 —— 标题、摘要、正文、定理与证明、图表标题、参考文献一律英文，全文 CJK 字符数为 0，`%` 注释里也不留中文。为什么这条能当硬线：它是可机械判的形态，而"提示词里写了英文"只是嘱托；
没有这条读数时，混进正文的中文不会被任何东西拦下。判据对象（三态里必须分开的那两态）：扫 `projects/*/out/paper/main.tex`（存在的才算）。扫不到任何一篇 ⇒ 判红："没扫到"与"扫到了且干净"是两件事，
折成同一个绿就是本项目反复踩的"没查成"坑（`scripts/noai_gate.py` 的 `2 = unknown` 同一条纪律）。`main.tex` 里有一类是不是论文的：`build_document` 早年把台账稿渲染
到`out/paper/main.tex`（`specs/g.py` 的 `out_path` 那一格记着成因：26 KB 的正文被覆盖成4 KB 的台账稿）。现存 1 份这样的产物（见 `NON_LATEX_MAIN_TEX`）。
对它的处置是逐条登记而不是"见到就跳过"也不是"见到就红"：跳过 = 静默 —— 下一份"台账稿写进 main.tex"从此看不见（那正是这条判据想抓的形态）；- 红 = 让这条判据替另一件事（"main.tex 得是
LaTeX"）背锅，而那份产物是 2026-10-04一次作废跑留下的，不在任何交付物里，改成英文 LaTeX 等于凭空造一篇论文；- 所以：已知的带日期登记（表里那一条），未知的一律判红。负控（都在这里跑真的判据本体）：
往一篇论文（副本）里塞中文 —— 正文一句、`%` 注释一句 ⇒ 必须红，且报出的行号就是那两行；2. 同一份文件去掉中文 ⇒ 必须绿（证明它不是"见到文件就红"）；3. 一篇都扫不到（空目录）⇒ 必须红，不许静默通过；4.
一份没登记过的非 LaTeX `main.tex` ⇒ 必须红（证明"不是论文"不是免检通道）。这条判据是工作区绑定的：它扫的是盘上真实的 `projects/`，而 `projects/` 在`.gitignore` 第 164
行里（不入库）。两种"没有东西可查"的形态必须分开（业主 2026-10-18定的口径）：`projects/` 目录整个不存在（= 刚 clone、从没跑过论文）⇒ `pytest.skip`，理由逐字写「干净克隆里没有
projects/，这条判据没有对象」—— 那是正常状态，不是缺陷；- `projects/` 存在但没有一篇 LaTeX 稿 ⇒ 判红（负控 ③ 守这一条）：那说明有人跑过、目录在，却一篇论文都读不到 ——
"没查成"不许折叠成"查过了没问题"。

判据本体 `language_problems()` 保持纯函数且严格（空目录 ⇒ 红）：skip 只发生在pytest 用例这一层，不改本体，否则负控 ③ 就失去对象。
"""
from __future__ import annotations

import pathlib

import pytest

#: 仓库根（`tests/` 的上一级）：判据扫的是盘上真实的论文，不是夹具。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: CJK 与「中文排版里会出现的非 ASCII」的码位区间（闭区间）。
#:
#: 为什么不是一个字符类：`re` 的 `\u` 转义在 4 位以上（扩展 B–H，U+20000 以上）
#: 写不进普通字符类，而中文正文里混进一个生僻字照样算"正文里有中文"。
#: 区间之外的东西（希腊字母、`\'e`、`—`）不算 —— 数学习惯用它们。
CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x2E80, 0x2EFF),    # CJK 部首补充
    (0x2F00, 0x2FDF),    # 康熙部首
    (0x3000, 0x303F),    # CJK 标点（、。「」《》…，含 U+3000 全角空格）
    (0x3040, 0x30FF),    # 平假名 / 片假名（中文稿里常混）
    (0x3100, 0x312F),    # 注音符号
    (0x31C0, 0x31EF),    # CJK 笔画
    (0x3200, 0x32FF),    # 带圈的 CJK 字母与月份
    (0x3400, 0x4DBF),    # 扩展 A
    (0x4E00, 0x9FFF),    # 基本汉字区
    (0xF900, 0xFAFF),    # 兼容汉字
    (0xFE30, 0xFE4F),    # 竖排标点（更早的 CJK 兼容形式）
    (0xFF00, 0xFFEF),    # 全角 ASCII 与全角标点
    (0x20000, 0x2FA1F),  # 扩展 B–F + 兼容补充
    (0x30000, 0x3134F),  # 扩展 G–H
)

#: 已知的、不是 LaTeX 论文的 `main.tex`（仓库根相对路径，逐条登记）。
#:
#: 2026-10-18 空表：原来那一条是 2026-10-04 `p5-review-t5` 的产物
#: （`build_document` 按 `out_path` 把台账稿渲染进 `out/paper/main.tex`，
#: 3992 字节 markdown，开头 `# What survives…` / `- 稿件代号：doc:0000`）。
#: 业主裁定「按建议」删除该产物 ⇒ 表随之清空，登记不许僵死
#: （见 `test_the_registered_non_latex_artifact_is_still_the_one_on_disk`）。
#:
#: 机制保留：新出现的非 LaTeX `main.tex` 仍一律判红（负控 ④ 守这一条），
#: 要豁免只能往本表里逐条登记（带日期与成因）。空表不等于免检。
NON_LATEX_MAIN_TEX: frozenset[str] = frozenset()


def is_cjk(ch: str) -> bool:
    """这一个字符算不算 CJK（判据的原子谓词，负控也走它）。"""
    code = ord(ch)
    return any(low <= code <= high for low, high in CJK_RANGES)


def cjk_hits(text: str) -> list[tuple[int, int, str]]:
    """`(行号, 列号, 字符)`，行号与列号都从 1 起；空列表 = 全文英文。

    报行号而不是只报"有多少个"：判据红的时候人得能直接跳到那一行去改，
    否则"有 3 个 CJK 字符"在 40 KB 的正文里等于没说。
    """
    hits: list[tuple[int, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for column, ch in enumerate(line, start=1):
            if is_cjk(ch):
                hits.append((lineno, column, ch))
    return hits


def main_tex_files(root: pathlib.Path) -> list[pathlib.Path]:
    """`<root>/projects/*/out/paper/main.tex`（存在的才算），按路径排序。"""
    return sorted((root / "projects").glob("*/out/paper/main.tex"))


def _relative(root: pathlib.Path, path: pathlib.Path) -> str:
    return path.relative_to(root).as_posix()


def is_latex_document(text: str) -> bool:
    """这份 `main.tex` 到底是不是一篇 LaTeX 稿（判据：出现 `\\documentclass`）。"""
    return "\\documentclass" in text


def paper_files(root: pathlib.Path) -> list[pathlib.Path]:
    """论文：`main.tex` 里真的是一篇 LaTeX 稿的那些（读不成 UTF-8 的也算候选）。

    读不成的那一类仍留在候选里（`language_problems` 会把它判红），
    否则"编码坏掉"就等于"不是论文"⇒ 又成了一条免检通道。
    """
    papers: list[pathlib.Path] = []
    for path in main_tex_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            papers.append(path)
            continue
        if is_latex_document(text):
            papers.append(path)
    return papers


def language_problems(root: pathlib.Path) -> list[str]:
    """判据本体：空列表 = 绿；非空 = 逐条问题串。

    纯函数（只吃一个根目录）：负控把根指到 `tmp_path` 时走的是同一条代码路径
    —— 负控要是另写一份实现，它证明的只是"另一份实现会红"。
    """
    papers = paper_files(root)
    # 未登记的非 LaTeX `main.tex`：不是论文，但也不许静默消失（负控 ④）
    unregistered = [
        _relative(root, path) for path in main_tex_files(root)
        if _relative(root, path) not in NON_LATEX_MAIN_TEX
        and path not in papers
    ]
    problems: list[str] = []
    if not papers:
        problems.append(
            f"扫不到任何一篇论文（{root / 'projects'}/*/out/paper/main.tex 里没有 "
            f"LaTeX 稿）⇒ 这条判据没检验任何东西；「没查成」不是「查过了没问题」，判红")
    for rel in unregistered:
        problems.append(
            f"{rel}：不是 LaTeX 稿（没有 \\documentclass），也不在 `NON_LATEX_MAIN_TEX` "
            f"的登记表里 ⇒ 先弄清楚它是什么（台账稿写进 main.tex？），再登记或修好")
    for path in papers:
        rel = _relative(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # 非 UTF-8 的稿子读不成 ⇒ 也算红（不是崩）
            problems.append(f"{rel}：不是 UTF-8，读不成（{exc}）⇒ 无从判断语言")
            continue
        hits = cjk_hits(text)
        if not hits:
            continue
        lines = sorted({lineno for lineno, _, _ in hits})
        raw = text.splitlines()
        samples = [f"第 {lineno} 行：{raw[lineno - 1].strip()[:80]}"
                   for lineno in lines[:5]]
        problems.append(
            f"{rel}：{len(hits)} 个 CJK 字符，落在第 {lines} 行"
            f"（共 {len(raw)} 行）—— 论文全文必须是英文，注释里也不留中文。\n    "
            + "\n    ".join(samples))
    return problems


# ==================================================================== 正控（盘上真论文）


def _skip_if_no_projects_dir() -> None:
    """干净克隆（`projects/` 整个不存在）⇒ skip；目录存在就一定要判（空目录仍红）。"""
    if not (REPO_ROOT / "projects").is_dir():
        pytest.skip("干净克隆里没有 projects/，这条判据没有对象（目录存在但空仍判红）")


def test_every_paper_is_written_in_english() -> None:
    """正控：盘上每一篇论文（`projects/*/out/paper/main.tex` 的 LaTeX 稿）都是英文。"""
    _skip_if_no_projects_dir()
    problems = language_problems(REPO_ROOT)
    assert problems == [], (
        "论文里出现了不该出现的东西（正文必须是英文；非 LaTeX 的 main.tex 要登记）"
        "—— 逐条读数：\n" + "\n".join(problems))


def test_the_criterion_really_scans_the_papers_it_claims_to_scan() -> None:
    """反真空：这条判据不是"扫了 0 篇所以绿"。

    没有这一条，一个把 `projects/` 拼错的实现会永远绿（"扫不到"那一句守卫
    也是它自己写的，写错时并不比主断言更可靠）。
    """
    _skip_if_no_projects_dir()
    files = paper_files(REPO_ROOT)
    assert files, f"{REPO_ROOT / 'projects'}/*/out/paper/main.tex 里一篇 LaTeX 稿都没有"
    scanned = 0
    for path in files:
        assert path.read_text(encoding="utf-8").strip(), f"{path} 是空文件 —— 空稿不算「英文」"
        scanned += 1
    assert scanned == len(files) >= 1, (scanned, len(files))
    # 盘上真实的四篇（mp1–mp4）必须都在扫描面里：判据扫的是"论文"，不是"某个名字"
    assert scanned >= 4, f"只扫到 {scanned} 篇 —— 少于 mp1–mp4 那四篇"


def test_the_registered_non_latex_artifact_is_still_the_one_on_disk() -> None:
    """登记表不许僵死：盘上那份非 LaTeX `main.tex` 与 `NON_LATEX_MAIN_TEX` 对得上。

    这条不是"给那条豁免找一个理由"，而是反过来：登记表过期（那份产物被修好/删掉）
    也就该清表，否则下一个人会以为它还在。
    """
    _skip_if_no_projects_dir()
    on_disk = {_relative(REPO_ROOT, path) for path in main_tex_files(REPO_ROOT)
               if path not in paper_files(REPO_ROOT)}
    assert on_disk == set(NON_LATEX_MAIN_TEX), (
        "盘上的非 LaTeX `main.tex` 与登记表对不上：\n"
        f"  盘上：{sorted(on_disk)}\n  登记：{sorted(NON_LATEX_MAIN_TEX)}")


# ==================================================================== 负控（同一条代码路径）


def _write_paper(root: pathlib.Path, name: str, body: str) -> pathlib.Path:
    """在临时工作区里造一份 `projects/<name>/out/paper/main.tex`。"""
    paper = root / "projects" / name / "out" / "paper" / "main.tex"
    paper.parent.mkdir(parents=True, exist_ok=True)
    paper.write_text(body, encoding="utf-8")
    return paper


_ENGLISH_PAPER = """\\documentclass[11pt]{ctexart}
\\usepackage{amsmath,amssymb,amsthm}
\\begin{document}
The covering radius of a finite set of rotations is analysed below.
\\end{document}
"""


def test_negative_control_chinese_in_a_paper_turns_the_criterion_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ①：正文塞一句中文、`%` 注释再塞一句 ⇒ 必须红，且行号指到那两行。"""
    body = _ENGLISH_PAPER.replace(
        "The covering radius of a finite set of rotations is analysed below.",
        "The covering radius is analysed below.\n"
        "% 这里是一句中文注释（注释里也不许留中文）\n"
        "We prove the following theorem: 每个覆盖半径都有下界。")
    _write_paper(tmp_path, "mpX", body)
    problems = language_problems(tmp_path)
    assert problems, "负控失效：塞了中文却判绿 —— 这条判据抓不住混进正文的中文"
    joined = "\n".join(problems)
    # 行号：替换把第 4 行拆成三行 ⇒ 注释落在第 5 行、中文那句定理在第 6 行
    assert "第 [5, 6] 行" in joined, joined
    assert "这里是一句中文注释" in joined, joined


def test_positive_control_the_same_paper_without_chinese_is_green(
        tmp_path: pathlib.Path) -> None:
    """负控 ②（另一半）：把中文去掉、其余一字不动 ⇒ 必须绿。

    没有这一半，一个"见到文件就红"的实现也能通过负控 ①。
    """
    _write_paper(tmp_path, "mpY", _ENGLISH_PAPER)
    assert language_problems(tmp_path) == [], (
        "纯英文的论文被判红了 ⇒ 判据把非 CJK 的字符也算进去了")


def test_negative_control_no_papers_at_all_is_red_not_silently_green(
        tmp_path: pathlib.Path) -> None:
    """负控 ③：一篇都扫不到 ⇒ 判红（"没查成"不许折叠成"查过了没问题"）。"""
    (tmp_path / "projects").mkdir()
    problems = language_problems(tmp_path)
    assert problems, "负控失效：扫不到论文却判绿 —— 这条判据会静默通过"
    assert "扫不到" in "".join(problems), problems


def test_negative_control_an_unregistered_non_latex_main_tex_turns_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ④：没登记过的非 LaTeX `main.tex` ⇒ 红（"不是论文"不是免检通道）。

    反过来说：真机上现存的那一份在 `NON_LATEX_MAIN_TEX` 里逐条登记着（带日期与成因），
    所以正控绿；这一条守的是"下一份"。
    """
    _write_paper(tmp_path, "mpZ", "# 一篇 markdown 台账稿\n\n- 稿件代号：`doc:0000`\n")
    problems = language_problems(tmp_path)
    assert problems, "负控失效：一份不是 LaTeX 的 main.tex 混进来却判绿"
    assert "不是 LaTeX 稿" in "".join(problems), problems
    assert "NON_LATEX_MAIN_TEX" in "".join(problems), problems
