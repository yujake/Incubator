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

## 历史工作区的 CJK：逐条登记，不静默放过

`projects/paper-rewrite-80/out/paper/main.tex` 第 936 行 `…（原文 1188 字，已截断）`
是历史工作区里真实存在的 9 个 CJK 字符；业主明令「80 不重启」⇒ 不许为了让判据变绿
去改那篇论文。但「红着不管」会让下一条混进正文的中文隐身（两者长得一模一样）。
处置因此是 `CJK_EXEMPTIONS` 那张逐条登记表：路径 / 行号 / 该行字符数 / 理由逐字写死。

登记不是免检通道，两个方向都要红：

- 盘上有 CJK 而表里没有 ⇒ 仍按上面的语言判据红（登记只豁免它点名的那一行）；
- 表里有而盘上那份文件 / 那一行 / 那个字符数对不上 ⇒ 也红（豁免腐烂：文件被修好、
  删掉、或者那一行又被改出新的中文之后，登记会自己变成一条假话）。

本次的读数落在 `language_readings()` 的三格里：`scanned`（真的读了哪几篇）、
`exemptions`（这次用上了的登记 `{path, line, count, reason}` —— 它是"问题被登记后
暂时放行"，不是"没问题"，所以必须列出来）、`problems`（非空即红）。登记项还要被
H 的只读工具 `review.scan_text_integrity()` 现场复核：同一行、同样 9 个字符，两道
尺子读数一致才放行 —— 这样豁免不会腐烂成一句空话。
"""
from __future__ import annotations

import dataclasses
import pathlib

import pytest

from agentflow.tools import review_tools as RT

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


@dataclasses.dataclass(frozen=True)
class CjkExemption:
    """一条「历史工作区里的 CJK」豁免登记（只由人逐条写；判据不自动生成）。"""

    path: str   # 仓库根相对路径（posix 分隔符）
    line: int   # 1 起
    count: int  # 这一行上的 CJK 字符数（本文件与 H 的尺子都必须读到这个数）
    reason: str

    def as_reading(self) -> dict[str, object]:
        """读数用的四格（键域与 `language_readings()["exemptions"]` 一致）。"""
        return {"path": self.path, "line": self.line,
                "count": self.count, "reason": self.reason}


#: 历史工作区里「确实是 CJK、但这次不改」的逐条登记。
#:
#: 为什么要有这张表：`projects/paper-rewrite-80/out/paper/main.tex` 第 936 行
#: `…（原文 1188 字，已截断）` 是历史工作区产物，业主明令「80 不重启」⇒ 不许
#: 为了让判据变绿去改那篇论文；但「红着不管」会让下一条混进正文的中文隐身。
#: 所以处置是「逐条登记」：路径 / 行号 / 该行字符数 / 理由写死，登记项必须
#: 仍然被扫到同样的读数（见 `_registered_reading`），否则判红。
#:
#: 为什么不是「跳过整个工作区」：那会把该工作区里「新出现」的 CJK 一并放过；
#: 判据只豁免它点名的那一行、那个字符数。
CJK_EXEMPTIONS: tuple[CjkExemption, ...] = (
    CjkExemption(
        path="projects/paper-rewrite-80/out/paper/main.tex",
        line=936,
        count=9,
        reason="业主明令 80 不重启；该文为历史工作区产物；已由 review.scan_text_integrity 可随时复核",
    ),
)


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


def _registered_reading(
        root: pathlib.Path,
        exemption: CjkExemption) -> tuple[dict[str, object] | None, str]:
    """现场复核一条登记：盘上还读得到同样的 `(行, 字符数)` 吗？

    两道尺子都要对：本文件的 `cjk_hits()`（覆盖假名 / 扩展区等，比 H 的码位表宽）
    与 H 的只读工具 `review.scan_text_integrity()`（业主让 H 审异常字符的那件）。
    两道读数不一致时返回 `(None, 理由)` —— 「这一行到底有几个 CJK」不许由一条
    路径独断，否则登记表验的就只是它自己抄的那个数。

    读不成（文件不在 / 不是 UTF-8 / H 返回 `checked=False`）也返回 `(None, 理由)`：
    「没查成」不是「零命中」，这正是本项目反复踩的三态坑。
    """
    target = root / exemption.path
    if not target.is_file():
        return None, (f"盘上找不到 {exemption.path}"
                      f"（登记：第 {exemption.line} 行 {exemption.count} 个）")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return None, f"{exemption.path} 读不成 UTF-8（{exc}）⇒ 无从复核"
    ours = [hit for hit in cjk_hits(text) if hit[0] == exemption.line]
    scan = RT.scan_text_integrity(root.resolve(), [exemption.path], limit=10**6)
    if not scan.get("checked"):
        return None, (f"review.scan_text_integrity 没查成："
                      f"{scan.get('reason') or '（无理由）'} ⇒ 没查成不是干净")
    theirs = [f for f in scan.get("findings", [])
              if f.get("kind") == "cjk" and f.get("line") == exemption.line]
    if len(ours) != len(theirs):
        return None, (f"两把尺子读数不一致：cjk_hits 读到 {len(ours)} 个，"
                      f"review.scan_text_integrity 读到 {len(theirs)} 个")
    return {"path": exemption.path, "line": exemption.line,
            "count": len(ours), "reason": exemption.reason}, ""


def language_readings(
        root: pathlib.Path,
        *,
        exemptions: tuple[CjkExemption, ...] = CJK_EXEMPTIONS) -> dict[str, object]:
    """判据本体的完整读数：`{"scanned": [...], "exemptions": [...], "problems": [...]}`。

    三格各有各的职责，少一格就会把一件事折成另一件：

    - `scanned`：这次真的读成并扫过的论文（没有它，"扫了 0 篇"会冒充"全都干净"）；
    - `exemptions`：登记表里这次真的用上了的条目 `{path, line, count, reason}`。
      它们不是"没问题"，是"问题被逐条登记后暂时放行"，所以必须列进读数（不静默通过）；
    - `problems`：非空即红。

    登记表的「双向」校验都在这里：盘上有 CJK 而表里没有 ⇒ 进 `problems`；
    表里有而盘上那份文件 / 那一行 / 那个字符数对不上 ⇒ 也进 `problems`（登记过期）。
    负控把 `exemptions=()` 传进来时走的是同一条代码路径 —— 这样"未登记就红"与
    "登记过期就红"共用同一个实现，而不是各写一份。

    纯函数（只吃一个根目录与一张登记表）：负控把根指到 `tmp_path` 时，
    被检验的仍是本函数。
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

    # 登记项先逐条现场复核：盘上还在、那一行还是那个字符数、两道尺子读数一致。
    # 复核不通过的条目「不进」matched ⇒ 它既不会被用来放行任何 CJK，也会在下面
    # 以"登记过期"进 problems（豁免腐烂要红，不能烂成一句空话）。
    matched: dict[tuple[str, int], CjkExemption] = {}
    for exemption in exemptions:
        reading, why = _registered_reading(root, exemption)
        if reading is None:
            problems.append(
                f"{exemption.path}:{exemption.line}：CJK 豁免登记过期 —— {why}；"
                f"豁免表不许僵死：盘上没了（或读不成）就删登记，或把文件/行号/字符数改对")
            continue
        if reading["count"] != exemption.count:
            problems.append(
                f"{exemption.path}:{exemption.line}：CJK 豁免登记过期 —— 盘上现在读到 "
                f"{reading['count']} 个 CJK 字符，登记写的是 {exemption.count} 个；"
                f"读数对不上就不放行")
            continue
        matched[(exemption.path, exemption.line)] = exemption

    scanned: list[str] = []
    applied: set[tuple[str, int]] = set()
    for path in papers:
        rel = _relative(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # 非 UTF-8 的稿子读不成 ⇒ 也算红（不是崩）
            problems.append(f"{rel}：不是 UTF-8，读不成（{exc}）⇒ 无从判断语言")
            continue
        scanned.append(rel)
        hits = cjk_hits(text)
        if not hits:
            continue
        raw = text.splitlines()
        by_line: dict[int, list[tuple[int, int, str]]] = {}
        for hit in hits:
            by_line.setdefault(hit[0], []).append(hit)
        open_lines: list[int] = []
        open_hits = 0
        for lineno in sorted(by_line):
            line_hits = by_line[lineno]
            exemption = matched.get((rel, lineno))
            if exemption is not None and len(line_hits) == exemption.count:
                applied.add((rel, lineno))
                continue
            open_lines.append(lineno)
            open_hits += len(line_hits)
        if open_lines:
            samples = [f"第 {lineno} 行：{raw[lineno - 1].strip()[:80]}"
                       for lineno in open_lines[:5]]
            problems.append(
                f"{rel}：{open_hits} 个 CJK 字符，落在第 {open_lines} 行"
                f"（共 {len(raw)} 行）—— 论文全文必须是英文，注释里也不留中文。"
                f"（历史工作区若业主明令不改，请往 `CJK_EXEMPTIONS` 逐条登记"
                f"路径/行号/字符数/理由；没有登记的 CJK 一律判红。）\n    "
                + "\n    ".join(samples))
    for key, exemption in matched.items():
        if key not in applied:
            problems.append(
                f"{exemption.path}:{exemption.line}：CJK 豁免登记过期 —— 盘上这一行"
                f"确实还是 {exemption.count} 个 CJK，但这次扫描没有用上它"
                f"（{exemption.path} 不在本次扫描的论文面里，例如它已不是 LaTeX 稿）；"
                f"登记项必须真的被扫到，否则它只是在挡一个不存在的对象")
    return {
        "scanned": scanned,
        "exemptions": [e.as_reading() for key, e in matched.items() if key in applied],
        "problems": problems,
    }


def language_problems(
        root: pathlib.Path,
        *,
        exemptions: tuple[CjkExemption, ...] = CJK_EXEMPTIONS) -> list[str]:
    """`language_readings()["problems"]`（保留旧签名；负控也走同一条代码路径）。"""
    return list(language_readings(root, exemptions=exemptions)["problems"])


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


def test_the_registered_cjk_exemption_is_listed_and_matches_hs_reading() -> None:
    """登记不是静默通过：登记项要作为 `exemptions` 读数出现，并仍被扫到同样读数。

    这条同时钉三件事：

    1. `language_readings()` 把 80 那份历史稿的登记列成 `{path, line, count, reason}`，
       而不是从读数里消失（「绿」必须能说出「哪一条被放行了」）；
    2. 该项目的 `problems` 为空（那 9 个字符不再冒充红）；
    3. H 的只读工具独立再读一次，仍是 `path + 第 936 行 + 9 个 cjk` —— 登记没有腐烂。
    """
    _skip_if_no_projects_dir()
    readings = language_readings(REPO_ROOT)
    assert readings["problems"] == [], (
        "登记表没能让 80 那份历史稿的 9 个 CJK 走「已登记」这条路：\n"
        + "\n".join(readings["problems"]))
    expected = {
        "path": "projects/paper-rewrite-80/out/paper/main.tex",
        "line": 936,
        "count": 9,
        "reason": "业主明令 80 不重启；该文为历史工作区产物；已由 review.scan_text_integrity 可随时复核",
    }
    assert readings["exemptions"] == [expected], readings["exemptions"]
    assert readings["scanned"] and expected["path"] in readings["scanned"], readings["scanned"]
    scan = RT.scan_text_integrity(REPO_ROOT, [expected["path"]], limit=10**6)
    assert scan["checked"] is True, scan
    cjk_on_line = [f for f in scan["findings"]
                   if f["kind"] == "cjk" and f["line"] == expected["line"]]
    assert len(cjk_on_line) == expected["count"], cjk_on_line
    assert {f["path"] for f in cjk_on_line} == {expected["path"]}, cjk_on_line


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


def _paper_with_two_cjk() -> str:
    """第 5 行是 `% 中文`（正好 2 个 CJK）的论文，供豁免表的负控写死读数用。"""
    return _ENGLISH_PAPER.replace(
        "The covering radius of a finite set of rotations is analysed below.",
        "The covering radius is analysed below.\n% 中文")


def test_negative_control_chinese_in_a_paper_turns_the_criterion_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ①：正文塞一句中文、`%` 注释再塞一句 ⇒ 必须红，且行号指到那两行。"""
    body = _ENGLISH_PAPER.replace(
        "The covering radius of a finite set of rotations is analysed below.",
        "The covering radius is analysed below.\n"
        "% 这里是一句中文注释（注释里也不许留中文）\n"
        "We prove the following theorem: 每个覆盖半径都有下界。")
    _write_paper(tmp_path, "mpX", body)
    problems = language_problems(tmp_path, exemptions=())
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
    assert language_problems(tmp_path, exemptions=()) == [], (
        "纯英文的论文被判红了 ⇒ 判据把非 CJK 的字符也算进去了")


def test_negative_control_no_papers_at_all_is_red_not_silently_green(
        tmp_path: pathlib.Path) -> None:
    """负控 ③：一篇都扫不到 ⇒ 判红（"没查成"不许折叠成"查过了没问题"）。"""
    (tmp_path / "projects").mkdir()
    problems = language_problems(tmp_path, exemptions=())
    assert problems, "负控失效：扫不到论文却判绿 —— 这条判据会静默通过"
    assert "扫不到" in "".join(problems), problems


def test_negative_control_an_unregistered_non_latex_main_tex_turns_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ④：没登记过的非 LaTeX `main.tex` ⇒ 红（"不是论文"不是免检通道）。

    反过来说：真机上现存的那一份在 `NON_LATEX_MAIN_TEX` 里逐条登记着（带日期与成因），
    所以正控绿；这一条守的是"下一份"。
    """
    _write_paper(tmp_path, "mpZ", "# 一篇 markdown 台账稿\n\n- 稿件代号：`doc:0000`\n")
    problems = language_problems(tmp_path, exemptions=())
    assert problems, "负控失效：一份不是 LaTeX 的 main.tex 混进来却判绿"
    assert "不是 LaTeX 稿" in "".join(problems), problems
    assert "NON_LATEX_MAIN_TEX" in "".join(problems), problems


# ---------------------------------------------------------------- 豁免表的负控（双向）


def test_negative_control_cjk_in_an_unregistered_workspace_turns_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ⑤：表里只登记了 A 工作区，B 工作区同样有 CJK ⇒ B 必须红。

    「登记一条」不许变成「静默放过一片」：表非空不是全仓放行，只有被点名的
    `(path, line, count)` 才放行。这一条用同一份正文造两个工作区，登记其中一个。
    """
    _write_paper(tmp_path, "mpRegistered", _paper_with_two_cjk())
    _write_paper(tmp_path, "mpUnregistered", _paper_with_two_cjk())
    table = (CjkExemption(
        path="projects/mpRegistered/out/paper/main.tex",
        line=5, count=2, reason="负控：只登记这一个工作区"),)
    readings = language_readings(tmp_path, exemptions=table)
    problems = readings["problems"]
    joined = "\n".join(problems)
    assert problems, "负控失效：未登记的工作区里有 CJK 却判绿"
    assert "mpUnregistered" in joined, joined
    assert "mpRegistered" not in joined, joined
    assert readings["exemptions"] == [table[0].as_reading()], readings["exemptions"]


def test_negative_control_a_registered_path_that_vanished_turns_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ⑥：表里多一条盘上已经不存在的登记 ⇒ 红（豁免腐烂的双向之一）。

    这一条守的是「登记表自己会烂」：文件被删/改名之后，那一条登记仍在表里
    作为一句空话挂着，下一个人会以为它还在挡着什么。
    """
    _write_paper(tmp_path, "mpLive", _ENGLISH_PAPER)
    table = (CjkExemption(
        path="projects/paper-rewrite-80/out/paper/main.tex",
        line=936, count=9, reason="负控：这条登记对应的文件不在这个根上"),)
    readings = language_readings(tmp_path, exemptions=table)
    problems = readings["problems"]
    joined = "\n".join(problems)
    assert problems, "负控失效：登记表里有一条盘上不存在的条目却判绿"
    assert "登记过期" in joined, joined
    assert "盘上找不到" in joined, joined
    assert readings["exemptions"] == [], readings["exemptions"]


def test_negative_control_a_registered_count_that_drifted_turns_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ⑦：盘上仍是 2 个、登记写 1 个 ⇒ 红；改回 2 个 ⇒ 绿（破坏-恢复）。

    这一条钉「读数是几个」：只登记路径与行号、不钉字符数的话，那一行被人
    再加两个中文也会照样放行 —— 登记就成了一句空话。
    """
    _write_paper(tmp_path, "mpDrift", _paper_with_two_cjk())
    path = "projects/mpDrift/out/paper/main.tex"
    wrong = (CjkExemption(path=path, line=5, count=1, reason="负控：读数漂了"),)
    readings = language_readings(tmp_path, exemptions=wrong)
    joined = "\n".join(readings["problems"])
    assert readings["problems"], "负控失效：登记数与盘上读数对不上却判绿"
    assert "登记过期" in joined, joined
    assert "1 个" in joined and "2 个" in joined, joined
    assert readings["exemptions"] == [], readings["exemptions"]

    fixed = (dataclasses.replace(wrong[0], count=2),)
    recovered = language_readings(tmp_path, exemptions=fixed)
    assert recovered["problems"] == [], recovered["problems"]
    assert recovered["exemptions"] == [fixed[0].as_reading()], recovered["exemptions"]


def test_negative_control_a_registered_line_that_moved_turns_red(
        tmp_path: pathlib.Path) -> None:
    """负控 ⑧：登记的行号上现在一个 CJK 都没有（中文在第 5 行）⇒ 红。

    行号不是装饰：只登记文件、按"文件里有 CJK"放行的话，中文挪到别处
    也会被同一条登记盖住。
    """
    _write_paper(tmp_path, "mpMoved", _paper_with_two_cjk())
    table = (CjkExemption(
        path="projects/mpMoved/out/paper/main.tex",
        line=6, count=2, reason="负控：行号挪了"),)
    readings = language_readings(tmp_path, exemptions=table)
    joined = "\n".join(readings["problems"])
    assert readings["problems"], "负控失效：登记行号上已经没有 CJK 却判绿"
    assert "登记过期" in joined, joined
    assert readings["exemptions"] == [], readings["exemptions"]
