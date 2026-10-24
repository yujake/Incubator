"""D-45 / D-46 的判据：论文语言口径（附录按论文语言出文）与附录表格的宽度。

业主 2026-10-24 的那几张截图（`draft/evidence/QQ20261024-123032.png` / `-123148.png` /
`-123228.png` / `-123651.png`）指着同一族缺陷的两半：

- D-45：英文论文里印出了「摘要」（第 1 页的摘要标题）、「参考文献」（第 6 页的页眉与
  节标题）、「证明。」（每条证明的抬头）、以及附录那一段整段中文说明 —— 语言不是
  "正文写了英文"就够了：标题、页眉、抬头、说明段同样是读者读到的论文；
- D-46：附录那张对应表宽出 `\\textwidth`，最后一列被切到页外、右侧文字竖排折行，
  「Lean 声明」与「Lean 文件」两列互相压字。

七条判据（每条 docstring 里写明"改之前为什么红"）：

1. 英文论文档渲染出来的附录里没有 CJK 字符（`[\\u4e00-\\u9fff]` 一个都不许有）；
   中文论文档渲染出来必须有 —— 后半条是反真空：语言判定得真的在判；
2. 生成的表格用了定宽列（`p{}` 或 `tabularx` 或 `\\resizebox`），且每一行的格数不超过
   表头的格数；
3. 把渲染出来的真附录拼进 `main.tex` 用 `pdflatex` 编一遍，日志里没有宽度超过 20pt 的
   `Overfull \\hbox`；没有 TeX 环境时这一条降级成静态检查（该用例 docstring 写明）；
4. 反真空：把语言判定打桩成恒中文 ⇒ 第 1 条必红；把列宽控制去掉 ⇒ 第 2 条必红；
5. G 的渲染提示词里读得到"论文语言 = 正文语言，标题与页眉也同一语言"这一层意思；
6. 英文论文档里每条证明的抬头是 `Proof.`，且导言区没有把抬头换成中文的重定义
   （`proofname` / `abstractname` / `refname` / `appendixname` 四个宏）；
7. 反真空：把 `\\renewcommand{\\proofname}{证明}` 塞回导言区 ⇒ 第 6 条必红。

口径与边界：本文件只读渲染产物与 tex 源码，不调模型、不连网。真机现场
（`D:\\Incubator\\cube2\\out\\paper`）只读；读不到时第 6 条用夹具顶上。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from agentflow import agent_prompts as AP
from agentflow import extract
from agentflow import papermapping as PM
from agentflow.tools import build_registry

#: 汉字常用区：判"附录里有没有混进中文"就用这一条正则（业主给的口径）。
CJK = re.compile(r"[\u4e00-\u9fff]")

#: 英文论文的正文（`article` + 英文散文 + 一条带 `proof` 的定理）。
ENGLISH_BODY = "\n".join([
    "\\documentclass[11pt]{article}",
    "\\usepackage{amsmath,amssymb,amsthm}",
    "\\usepackage[margin=2.5cm]{geometry}",
    "\\usepackage{booktabs}",
    "\\newtheorem{theorem}{Theorem}[section]",
    "\\begin{document}",
    "\\section{Main results}",
    "\\begin{theorem}\\label{thm:main}Every integer is the sum of two primes.\\end{theorem}",
    "\\begin{proof}",
    "By inspection of the cases above.",
    "\\end{proof}",
    "\\end{document}",
    "",
])

#: 中文论文的正文（散文为主，CJK 密度远高于 `papermapping.PAPER_LANGUAGE_CJK_RATIO`）：
#: 附录必须跟着它出中文 —— 它守着"语言判定不是恒英文".
CHINESE_BODY = "\n".join([
    "\\documentclass[11pt]{ctexart}",
    "\\begin{document}",
    "\\section{主结果}",
    "本文给出一个自足的证明：对每个整数，主定理都成立，理由逐条写在下面这一节里。",
    "证明按归纳进行，每一步都由前一步推出，读者可以逐行检查这里写下的每一步。",
    "讨论与开放问题放在最后一节，边界与反例在那里逐条说明，这里不再重复叙述。",
    "\\end{document}",
    "",
])

#: 探针里那几行对应表（故意都长：路径、声明名、整句英文的引文说明）——
#: 表格的宽度问题只在"格里有长东西"时暴露，短夹具量不出 D-46。
ROWS = (
    PM.Row(kind="theorem", label="thm:nicomachus", env_no=1,
           ledger_id="stmt:000000", proof_no=1, file="main.tex",
           lean_file="formal/000000.lean", lean_target="LCubeSum.sum_cubes",
           citation_loc_reason=(
               "own result: the proof is in this paper, Section 3, and its "
               "machine-checked counterpart is the Lean declaration sum_cubes in "
               "formal/000000.lean; there is no external source to quote")),
    PM.Row(kind="experiment", label="exp:grid", env_no=1, ledger_id="exp:000000",
           proof_no=1, file="code/r34_check.py", numeric_evidence="exp:000001",
           exhaustion_note="out/experiments/000001/exhaustion.md"),
)

#: 真机现场的论文包（只读；读不到就退回夹具）。
CUBE2_PACKAGE = Path("D:/Incubator/cube2/out/paper")

#: 提示词里必须读到的意思（去掉强调符号与空白之后逐条核；与 D-40 那套判据同一口径）。
PROMPT_NEEDLES: tuple[tuple[str, str], ...] = (
    ("论文语言 = 正文语言", "论文语言就是正文语言"),
    ("标题与页眉也是同一种语言", "标题与页眉跟正文同一种语言"),
    ("全部同一种语言", "正文与标题是同一语言"),
    ("不出现中文", "正文与标题不出现中文"),
    ("ctexart", "点名 ctexart 的默认方案会把抬头印成中文"),
    ("按论文语言生成", "附录那一段说明由渲染函数按论文语言生成"),
    ("不许手抄", "附录那一段说明不许手抄"),
    ("不许混语言", "附录那一段说明不许混语言"),
)

_EMPHASIS = re.compile(r"[\s*`]+")

_PROMPT_TASK = "整理成论文"
_PROMPT_ROOT = "D:/x"
_PROMPT_FACTS = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
                 "- 检查器：（判据夹具，与机器无关）")
_PROMPT_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
                  "- （判据夹具：这一次按自足文件写）")


# ---------------------------------------------------------------- 小工具

def _flat(text: str) -> str:
    """去掉强调符号与所有空白（判"读到的意思"，不判排版）。"""
    return _EMPHASIS.sub("", str(text))


def _paper(root: Path, body: str) -> Path:
    """把一个论文包摆到盘上（`out/paper/main.tex`），返回项目根。"""
    tex = PM.package_dir(root) / PM.PC.TEX_NAME
    tex.parent.mkdir(parents=True, exist_ok=True)
    tex.write_bytes(body.encode("utf-8"))
    return root


def _render(root: Path | None = None, **kwargs) -> str:
    """渲染一遍附录（`lean_enabled` 钉住，免得读数随机器上的开关漂）。"""
    return PM.render_appendix(ROWS, lean_enabled=True, project_root=root, **kwargs)


def _cjk_problems(text: str, *, where: str) -> list[str]:
    """这段渲染产物里混进了哪些中文（空清单 = 干净）。"""
    hits = sorted(set(CJK.findall(str(text))))
    if not hits:
        return []
    lines = [line.strip() for line in str(text).splitlines() if CJK.search(line)]
    return [f"{where} 里混进了中文：{''.join(hits)}；含中文的行：{lines[:3]}"]


def _cell_count(line: str) -> int:
    """一行表格有几个格（`&` 的转义写法是 `\\&`，所以按 `" & "` 切是安全的）。"""
    return len(line.split(" & "))


def _table_rows(text: str) -> tuple[list[str], list[str], str]:
    """从渲染产物里取出表格（表头行、正文行、列格式串）。

    只认 `\\begin{tabular}` 到 `\\end{tabular}` 之间：`% MAPPING-ROW` 那条注释不是格。
    """
    lines = str(text).splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.startswith("\\begin{tabular}")), -1)
    if start < 0:
        return [], [], ""
    spec = lines[start].strip()
    end = next((i for i in range(start, len(lines))
                if lines[i].startswith("\\end{tabular}")), len(lines))
    inside = [line for line in lines[start + 1:end]
              if line.strip() and not line.lstrip().startswith("%")]
    header = [line for line in inside if not line.startswith("\\hline")][:1]
    rows = [line for line in inside[len(header) + 1:] if not line.startswith("\\hline")]
    return header, rows, spec


def _width_problems(text: str) -> list[str]:
    """第 2 条的正文：列宽控制有没有、格数有没有越过表头（空清单 = 都过）。"""
    problems: list[str] = []
    header, rows, spec = _table_rows(text)
    controlled = ("p{" in spec) or ("tabularx" in spec) or ("\\resizebox" in str(text))
    if not controlled:
        problems.append("表格没有任何列宽控制（既没有 p{} 定宽列，也没有 tabularx "
                        "或 \\resizebox）—— 列一多就宽出 \\textwidth（D-46）")
    if "\\small" not in str(text):
        problems.append("表格没有 \\small：九列塞在 \\textwidth 里，字号不降就排不进")
    if not header:
        problems.append("渲染产物里读不到表头行（`\\begin{tabular}` 之后第一行）")
        return problems
    want = _cell_count(header[0])
    for line in rows:
        got = _cell_count(line)
        if got > want:
            problems.append(f"有一行 {got} 格，比表头的 {want} 格多：{line[:120]}")
    widths = spec.count("p{")
    if widths and widths != want:
        problems.append(f"定宽列 {widths} 个、表头 {want} 格：列格式与表头对不上")
    return problems


def _pdflatex() -> str:
    """本机有没有 `pdflatex`（没有时第 3、6、7 条降级成静态检查）。"""
    return shutil.which("pdflatex") or ""


def _compile(work: Path) -> tuple[int, str, Path]:
    """编一遍 `work/main.tex`，返回（退出码、日志、PDF 路径）。"""
    proc = subprocess.run([_pdflatex(), "-interaction=nonstopmode", "main.tex"],
                          cwd=work, capture_output=True, text=True)
    log_path = work / "main.log"
    log = (log_path.read_text(encoding="utf-8", errors="replace")
           if log_path.is_file() else proc.stdout)
    return proc.returncode, log, work / "main.pdf"


def _wide_overfulls(log: str, *, limit: float = 20.0) -> list[str]:
    """日志里宽度超过 `limit` 的 `Overfull \\hbox`（业主给的门是 20pt）。"""
    return [match.group(0) for match in
            re.finditer(r"Overfull \\hbox \(([0-9.]+)pt too wide\)[^\n]*", log)
            if float(match.group(1)) > limit]


def _max_overfull(log: str) -> float:
    """日志里最宽的那一条 `Overfull \\hbox`（读数用：报错时说清差多少）。"""
    got = [float(match.group(1)) for match in
           re.finditer(r"Overfull \\hbox \(([0-9.]+)pt too wide\)", log)]
    return max(got) if got else 0.0


def _log_segment(log: str, name: str) -> str:
    """日志里"读某个被 `\\input` 的文件"那一段（从 `(文件名` 到它自己的收尾 `)`）。

    为什么要切段：真机那份 `main.tex` 的正文自己就有几条宽 `\\texttt` 撑出的 Overfull
    （cube2 的日志里 125pt / 185pt 那几条），它们与附录无关；这一条判的是附录那张表。
    """
    lines = str(log).splitlines()
    start = next((i for i, line in enumerate(lines) if f"({name}" in line), -1)
    if start < 0:
        return ""
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == ")"),
               len(lines))
    return "\n".join(lines[start:end])


def _pdf_text(path: Path) -> str:
    """PDF 头两页的文本（判"抬头到底印成什么"只能读产物）。"""
    doc = extract.extract_text(path, max_pages=2)
    return "\n".join(getattr(doc, "pages", []) or [])


def _preamble_of(body: str) -> str:
    """一份 tex 的导言区（`\\begin{document}` 之前那一截）。"""
    return body[:body.index("\\begin{document}")].rstrip("\n")


def _body_of(body: str) -> str:
    """一份 tex 的正文（`\\begin{document}` 起）。"""
    return body[body.index("\\begin{document}"):]


def _host_tex(preamble: str, body: str = ENGLISH_BODY) -> str:
    """一份最小的英文杂志夹具：给什么导言区就用什么（第 6、7 条拿它做正反控）。"""
    return preamble.rstrip("\n") + "\n" + _body_of(body)


def _appendix_host(work: Path, appendix_text: str) -> Path:
    """第 3 条要的临时论文包：英文杂志夹具 + 渲染出来的真附录。"""
    work.mkdir(parents=True, exist_ok=True)
    (work / "mapping-appendix.tex").write_text(appendix_text + "\n", encoding="utf-8")
    (work / "main.tex").write_text(
        _host_tex(_preamble_of(ENGLISH_BODY)).replace(
            "\\end{document}", "\\input{mapping-appendix}\n\\end{document}"),
        encoding="utf-8")
    return work


# ---------------------------------------------------------------- 夹具

@pytest.fixture()
def english_paper(tmp_path: Path) -> Path:
    """英文论文档（D-45 的正控：附录必须出英文）。"""
    return _paper(tmp_path / "en", ENGLISH_BODY)


@pytest.fixture()
def chinese_paper(tmp_path: Path) -> Path:
    """中文论文档（D-45 的反真空：附录必须出中文，证明语言判定真的在判）。"""
    return _paper(tmp_path / "zh", CHINESE_BODY)


# ============================================================ 1 语言
def test_1_the_english_appendix_prints_no_cjk(english_paper: Path,
                                              chinese_paper: Path) -> None:
    """① 英文论文档渲染出来的附录里没有 CJK；中文论文档必须有（反真空的另一半）。

    改之前为什么红：`render_appendix` 根本不看论文语言 —— 标题「附录：产出对应表」、
    整段说明、表头、以及「（未开 Lean）」「（非数值证明）」两个占位格全是中文写死的，
    英文论文一渲染就带一身 CJK（cube2 的 `mapping-appendix.tex` 就是这样）。
    """
    en = _render(english_paper)
    bad = _cjk_problems(en, where="英文论文的附录")
    assert bad == [], "\n".join(bad)
    # 写侧与读侧得用同一个语言判定：落盘的那一份要与裸渲染逐字相同。
    PM.write_package(english_paper, ROWS)
    assert PM.paper_language(english_paper) == PM.PAPER_LANGUAGE_EN
    assert (PM.appendix_path(english_paper).read_text(encoding="utf-8").strip()
            == en.strip()), "写侧与读侧的附录不是同一份（语言判定各走了一条路）"
    # 读侧还把这一节认成 present：标题与正文都换了语言之后，按标题找的那条路仍然找得到。
    tex = (PM.package_dir(english_paper) / PM.PC.TEX_NAME).read_text(encoding="utf-8")
    state, problems = PM._appendix_reading(english_paper, tex, list(ROWS))
    assert (state, problems) == ("present", []), (state, problems)
    # 中文论文档那一路必须真的出中文：否则第 1 条只是"恒英文"的假绿。
    zh = _render(chinese_paper)
    assert CJK.search(zh), "中文论文档的附录里一个中文字都没有 ⇒ 语言判定没有真的在判"
    assert PM.paper_language(chinese_paper) == PM.PAPER_LANGUAGE_ZH


# ============================================================ 2 列宽
def test_2_the_table_is_built_from_fixed_width_columns(english_paper: Path) -> None:
    """② 表格用定宽列（`p{}` / `tabularx` / `\\resizebox` 之一），且每行格数不超过表头。

    改之前为什么红：列格式是 `{llllp{.12}p{.12}...}` —— 四个自然宽列里塞着
    `\\texttt{formal/000000.lean}` 与整句英文，整表 234pt 宽出 `\\textwidth`
    （cube2 `main.log` 里那条 `Overfull \\hbox (234.37341pt too wide)` 就是它），
    而且那十列里没有一处 `\\small`。
    """
    text = _render(english_paper)
    problems = _width_problems(text)
    assert problems == [], "\n".join(problems)
    header, rows, spec = _table_rows(text)
    assert header, "渲染产物里读不到表头行"
    assert rows, "渲染产物里读不到数据行（夹具的 ROWS 没进表）"
    # 列格式与表头逐格对上：九列全 p{}，列数等于 APPENDIX_COLUMN_WIDTHS 的长度。
    assert spec.count("p{") == len(PM.APPENDIX_COLUMN_WIDTHS) == _cell_count(header[0]), spec


# ============================================================ 3 编译
def test_3_the_real_appendix_compiles_without_a_wide_overfull_box(tmp_path: Path) -> None:
    """③ 真附录拼进 `main.tex` 用 `pdflatex` 编一遍：日志里没有超过 20pt 的 Overfull。

    改之前为什么红：cube2 的 `main.log` 里那条 `Overfull \\hbox (234.37341pt too wide)
    ... in paragraph at lines 6--13` 就是这张表（`mapping-appendix.tex` 的 6 到 13 行），
    另有 `lines 10--10` 那条 34.9pt（同一行的另一处）；20pt 是业主给的门。

    没有 TeX 环境时这一条降级成静态检查：只断言渲染产物带定宽列与 `\\small`
    （第 2 条已经把"没有列宽控制"判红，所以降级之后仍然不是空判）。
    """
    text = _render()
    work = _appendix_host(tmp_path / "tex", text)
    if not _pdflatex():
        problems = _width_problems(text)
        assert problems == [], "\n".join(problems)
        pytest.skip("没有 pdflatex：第 3 条降级成静态检查（渲染产物带定宽列与 \\small）")
    code, log, pdf = _compile(work)
    assert pdf.is_file(), f"pdflatex 没产出 PDF（退出码 {code}）：\n{log[-2000:]}"
    wide = _wide_overfulls(log)
    assert wide == [], (f"附录表格仍然宽出 \\textwidth（最宽的一条 "
                        f"{_max_overfull(log):.2f}pt，门是 20pt）：{wide}")
    # 表在 PDF 里真的印出来了（不是"编过但附录没进去"）：
    printed = _pdf_text(pdf)
    assert "Appendix: Output Mapping" in printed, printed[:400]
    assert not CJK.search(printed), f"PDF 里混进了中文：{CJK.findall(printed)[:8]}"
    # 真机现场（只读）：把新附录放进 cube2 那份 `main.tex` 再编一遍，只看附录那一段的
    # 日志 —— 业主看到的正是这一份 PDF。正文自己的 Overfull（长 `\texttt` 路径）不在这
    # 一条的射程里，所以按 `(mapping-appendix.tex` 那一段切。
    live = CUBE2_PACKAGE / "main.tex"
    if not live.is_file():
        return
    replay = tmp_path / "cube2"
    replay.mkdir()
    (replay / "main.tex").write_text(live.read_text(encoding="utf-8"), encoding="utf-8")
    (replay / PM.APPENDIX_FILE_NAME).write_text(text + "\n", encoding="utf-8")
    code2, log2, pdf2 = _compile(replay)
    assert pdf2.is_file(), f"真机那份 main.tex 换上新附录之后编不出来（退出码 {code2}）：\n{log2[-1500:]}"
    segment = _log_segment(log2, PM.APPENDIX_FILE_NAME)
    assert segment, "日志里读不到 `mapping-appendix.tex` 那一段 ⇒ 附录没被编进去"
    wide_live = _wide_overfulls(segment)
    assert wide_live == [], (f"真机那份 PDF 的附录仍然宽出 \\textwidth（最宽一条 "
                             f"{_max_overfull(segment):.2f}pt）：{wide_live}")


# ============================================================ 4 反真空
def test_4_stubbing_the_language_or_dropping_the_width_control_turns_it_red(
        english_paper: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """④ 反真空：语言打桩成恒中文 ⇒ ① 必红；列宽控制去掉 ⇒ ② 必红。

    改之前为什么红：这一条要打桩的那个口（`papermapping.paper_language`）改之前不存在。
    它守的是"① / ② 不是碰巧绿的"：打桩之后 ① 真的红、拆掉 `APPENDIX_COLUMN_WIDTHS`
    之后 ② 真的红 —— 两条判据才各自有它在守的那件事。
    """
    monkeypatch.setattr(PM, "paper_language", lambda *_a, **_k: PM.PAPER_LANGUAGE_ZH)
    stubbed = _render(english_paper)
    assert _cjk_problems(stubbed, where="打桩成中文之后") != [], \
        "语言判定打桩成恒中文，附录却仍然是英文 ⇒ 第 1 条没有真的在读语言判定"
    monkeypatch.setattr(PM, "APPENDIX_COLUMN_WIDTHS", ())
    dropped = _render(english_paper)
    assert _width_problems(dropped) != [], \
        "把列宽控制去掉，第 2 条却仍然通过 ⇒ 那一格没有在判列宽"


# ============================================================ 5 提示词
def test_5_the_g_prompt_says_headings_speak_the_paper_language() -> None:
    """⑤ G 的渲染提示词里读得到"标题/页眉与正文同语言"这一层意思。

    改之前为什么红：G 的 policy 里只有「硬线只有一条：语言必须是英文」那一句，它列的
    是正文、定理、图表标题、参考文献，既没有说"标题与页眉也是同一种语言"，也没有说
    附录那一段说明是谁写的 —— 于是模型照推荐配方用 `ctexart`，抬头就成了中文。

    技能正文（`agent_skills.py` 里 G 的那一段）那一半不在本判据的射程内：那份文件这一
    轮由 D-40 支线改（未提交），本支线按并发纪律整份不碰；这里锁的是提示词侧。
    """
    text = AP.system_prompt("G", registry=build_registry().registry, task=_PROMPT_TASK,
                            workspace_root=_PROMPT_ROOT, toolchain_facts=_PROMPT_FACTS,
                            toolchain_formal=_PROMPT_FORMAL)
    assert len(text) > 3000, f"渲染出来的提示词只有 {len(text)} 字 ⇒ 这一条没有落脚点"
    flat = _flat(text)
    missing = [f"读不到「{needle}」（{why}）" for needle, why in PROMPT_NEEDLES
               if _flat(needle) not in flat]
    assert missing == [], "\n".join(missing)
    # 那段的真身是 `specs/g.py` 的 policy（提示词只是把它渲染出来）：两处都要有，
    # 否则"提示词里有"可能只是别的一段碰巧写着同样的话。
    from agentflow.specs import g as GS

    policy = "\n".join(GS.SPEC.brief.policy)
    absent = [needle for needle, _why in PROMPT_NEEDLES if needle not in policy]
    assert absent == [], f"specs/g.py 的 policy 里缺 {absent}"


# ============================================================ 6 抬头
def test_6_the_english_paper_prints_proof_and_keeps_english_headings(tmp_path: Path) -> None:
    """⑥ 英文论文档里证明的抬头是 `Proof.`，导言区没有把抬头换成中文的重定义。

    改之前为什么红：`paper_heading_problems` 还不存在（这一格压根没人判）。而真机现场
    正是它该拦的那种：cube2 的 `main.tex` 第 1 行是 `\\documentclass[11pt]{ctexart}`，
    ctex 的默认方案把 `\\proofname` 印成「证明」—— 实测那一条编出来的 PDF 文本是
    `证明. By inspection.`（每条证明都中招）；`\\abstractname` / `\\refname` 同理，
    于是第 1 页的摘要标题与第 6 页的页眉都成了中文。
    """
    good = _host_tex(_preamble_of(ENGLISH_BODY))
    assert PM.paper_heading_problems(good) == [], PM.paper_heading_problems(good)
    # 真机现场（只读）：ctex 的中文方案必须被判出来，否则这一条拦不住 D-45。
    live = CUBE2_PACKAGE / "main.tex"
    if live.is_file():
        problems = PM.paper_heading_problems(live.read_text(encoding="utf-8"))
        assert problems, ("cube2 的导言区是 ctexart（中文方案），"
                          "这一条却什么都没判出来 ⇒ 判据没有读到文档类")
    if not _pdflatex():
        # 静态降级：文档类是 article ⇒ 默认的抬头就是 Proof. / Abstract / References。
        assert "\\documentclass[11pt]{article}" in good
        pytest.skip("没有 pdflatex：第 6 条降级成静态检查（导言区无中文抬头重定义）")
    work = tmp_path / "proof"
    work.mkdir()
    (work / "main.tex").write_text(good, encoding="utf-8")
    code, log, pdf = _compile(work)
    assert pdf.is_file(), f"pdflatex 没产出 PDF（退出码 {code}）：\n{log[-2000:]}"
    printed = _pdf_text(pdf)
    assert re.search(r"Proof\.", printed), f"证明的抬头不是 Proof.：{printed[:400]}"
    assert not CJK.search(printed), f"PDF 里混进了中文：{CJK.findall(printed)[:8]}"


# ============================================================ 7 反真空（抬头）
def test_7_putting_a_chinese_proofname_back_turns_the_sixth_red(tmp_path: Path) -> None:
    """⑦ 把 `\\renewcommand{\\proofname}{证明}` 塞回导言区 ⇒ 第 6 条必红。

    改之前为什么红：这一条要调的两个东西（`paper_heading_problems` 与
    `HEADING_MACROS`）改之前都不存在。它守的是第 6 条真的在读导言区：塞回去之后静态
    判定必须点名 `proofname`；有 TeX 时再编一遍 ctex 那一版，证明的抬头必须真的变成
    「证明」—— 那是业主截图里的那两个字。
    """
    evil = _host_tex(_preamble_of(ENGLISH_BODY) + "\\renewcommand{\\proofname}{证明}")
    problems = PM.paper_heading_problems(evil)
    assert problems, "导言区把 proofname 改成了中文，这一格却什么都没判出来"
    assert any("proofname" in line for line in problems), problems
    if not _pdflatex():
        pytest.skip("没有 pdflatex：第 7 条只核静态判定（proofname 那一条被点名）")
    # 负控：ctex 的中文方案编出来的抬头真的是「证明」—— 说明这一族判据量的是产物。
    ctex = _host_tex(_preamble_of(ENGLISH_BODY).replace(
        "\\documentclass[11pt]{article}", "\\documentclass[11pt]{ctexart}"))
    work = tmp_path / "ctex"
    work.mkdir()
    (work / "main.tex").write_text(ctex, encoding="utf-8")
    code, log, pdf = _compile(work)
    assert pdf.is_file(), f"pdflatex 没产出 PDF（退出码 {code}）：\n{log[-2000:]}"
    printed = _pdf_text(pdf)
    assert CJK.search(printed), ("ctex 的中文方案应当把 proofname 印成「证明」，"
                                 f"PDF 里却一个中文字都没有：{printed[:400]}")
