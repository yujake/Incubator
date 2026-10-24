"""D-47 的判据：正文里的长路径 / 长哈希必须可断行（typewriter 串不许整串撑出页宽）。

现场（cube2 真机，2026-10-24 清点日志时发现）：`out/paper/main.log` 里 5 条超过 20pt 的
`Overfull \\hbox`，全在正文与手写附录的散文里，成因是同一件事 —— 正文把
`out/experiments/000001/…`、`code/…`、64 位 sha256 这类长串整串排进了 `\\texttt`：

    125.28pt  in paragraph at lines 262--274   （五个 Lean 声明名连排）
    185.70pt  in paragraph at lines 359--363   （一个 64 位 sha256）
     61.81pt  in paragraph at lines 365--366   （整行 ttfamily 的检查器输出）
     41.43pt  in paragraph at lines 391--403   （code/formal/sum_cubes.lean）
     68.80pt  in paragraph at lines 391--403   （code/sum_cubes_numeric.py）

附录那张由 `papermapping.render_appendix` 渲染的表（234.37pt）归 D-46；本文件判的是
另一件事：正文自己写的那些串能不能断行。

三条判据（每条 docstring 写明改之前为什么红）：

1. 静态：正文里一段「连续」的 typewriter 串合计到 40 字以上时，其中每一处不能断行的
   `\\texttt` / `\\url` 都要被判红并点名行号。断行手段认 `\\allowbreak` / `\\-` /
   `\\linebreak` / `\\seqsplit`，以及 `\\url` / `\\path` 自带的按标点断行。
   连续 = 相邻两个 typewriter 之间只有标点与空白（`\\texttt{a}, \\texttt{b}`）；
   中间夹了散文词（`\\texttt{a} and \\texttt{b}`、`\\texttt{a}, sha256 \\texttt{b}`）就断开。
   为什么按「连续」合计、而不只看单串：cube2 那 125.28pt 的整行是五个声明名连排 ——
   单看每个都只有 22 到 29 字，连排之后可用的断点太少，TeX 挑不出一行放得下的断法，
   于是整行溢出。业主给的口径是 40 字，本条把它用在这一段串上。
2. 编译：把正文那一段（附录之前）拷到临时目录用 `pdflatex` 编一遍，`Overfull \\hbox`
   超过 20pt 的条数为 0。没有 TeX 引擎时这一条降级成第 1 条（降级口径写在用例里）。
3. 反真空：把断行手段去掉（`\\path{x}` 退回 `\\texttt{x\\_…}`）⇒ 第 1、2 条必红。

口径与边界：本文件只读 tex 源码、跑本机的 `pdflatex`，不调模型、不连网、不写工作区。
真机现场（`projects/cube2/out/paper`，旧路径 `D:\\Incubator\\cube2\\out\\paper`）只读；
读不到时那几条按 P16 显式 skip 并写明原因，不是「没找到就不判」。

已知盲区（登记在此，不装作它被覆盖了）：第 1 条只认 `\\texttt` / `\\url` / `\\path` 三种宏。
真机第 3 条 61.81pt 是 `\\begin{quote}\\ttfamily …\\end{quote}` 里的整行检查器输出 —— 那是
`\\ttfamily` 区域，不是这三个宏，静态判据看不见它；它落在附录（`\\appendix` 之后），也
不在第 2 条的「正文段」射程里。要判它得另加一条「`\\ttfamily` 区域里超长行」的判据。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as AS
from agentflow.specs import g as GS
from agentflow.tools import build_registry

#: 业主给的口径：一段连续的 typewriter 串合计到这么多字，就必须能断行。
LONG_RUN_CHARS = 40

#: 正文段的那道门（pt）：超过它的 `Overfull \\hbox` 就算撑出页宽（与 D-46 同一个门）。
OVERFULL_GATE_PT = 20.0

#: 一个 typewriter 出现：`\\texttt{…}` / `\\url{…}` / `\\path{…}`（可带可选参数；
#: 内容里允许一层花括号 —— `\\allowbreak{}` 就在那一层里）。
_OCCURRENCE = re.compile(
    r"\\(?P<macro>texttt|url|path)\s*(?:\[[^\]]*\])?\s*"
    r"\{(?P<content>(?:[^{}\\]|\\.|\{[^{}]*\})*)\}")

#: 两个出现之间只允许标点与空白，否则断开成两段（散文词把串切断）。
_RUN_GLUE = re.compile(r"^[\s,;:、，。]*$")

#: 串里已有的断行手段（出现任意一个就算这一串能断）。
_BREAK_MEANS = re.compile(r"\\allowbreak|\\-|\\linebreak|\\break\b|\\seqsplit")

#: 断行宏在版面里不占位置：算「印出来多少字」时要连同它的空花括号一起去掉。
_BREAK_NOISE = re.compile(r"\\(?:allowbreak|linebreak)(?:\{\})?|\\-")

#: `\\url` / `\\path` 自带按标点断行；但只在这些字符上断 —— 纯字母数字串照样不可断。
_URL_MACROS = frozenset({"url", "path"})
_URL_BREAK_CHARS = frozenset("/._-:=?,&")

#: 日志里的宽盒：段落形态（正文最常见的形态）与「detected at line」形态。
_OVERFULL_PARAGRAPH = re.compile(
    r"Overfull \\hbox \(([0-9.]+)pt too wide\) in paragraph at lines (\d+)--(\d+)")
_OVERFULL_DETECTED = re.compile(
    r"Overfull \\hbox \(([0-9.]+)pt too wide\) detected at line (\d+)")

#: 正文附录被 `\\input` 进来的那个文件（在日志里以 `(mapping-appendix.tex` 开头）。
_APPENDIX_INPUT = re.compile(r"\((?:\./)?mapping-appendix\b")

#: 本机 TeX 引擎的候选（`shutil.which` 找不到时退回这个绝对路径）。
_PDFLATEX_CANDIDATES = ("pdflatex", r"C:\CTEX\MiKTeX\miktex\bin\x64\pdflatex.exe")

#: cube2 正文「Formal verification」那一段（逐字，含那个 125.28pt 的连排）。
#: 这是改前红的样本本身：五个 Lean 声明名相邻，单串都不到 40 字。
CUBE2_BODY_PARAGRAPH = r"""The statements of Lemmas~\ref{lem:base}, \ref{lem:twodvd}, \ref{lem:clear}, \ref{lem:alg},
\ref{lem:step} and of Theorem~\ref{thm:nicomachus} have been formalized in Lean~4
(version 4.7.0) over Mathlib, as the declarations \texttt{LCubeSum.sum\_cubes\_one},
\texttt{LCubeSum.two\_dvd\_mul\_succ}, \texttt{LCubeSum.four\_mul\_div\_two\_sq},
\texttt{LCubeSum.induct\_algebra}, \texttt{LCubeSum.sum\_cubes\_succ\_step} and
\texttt{LCubeSum.sum\_cubes} respectively. The checker accepted the file; it reported
the axiom footprint of the main declaration as
\texttt{propext}, \texttt{Quot.sound}, \texttt{Classical.choice}, and the file contains
no \texttt{sorry}. This is a machine check of the statements listed above and of
nothing else: it does not certify the historical attribution, the telescoping
argument, or any numerical statement. The file, its digest, the checker output verbatim
and the ledger entries are collected in Appendix~\ref{app:evidence}."""

#: 那五个声明名（判据点名用：它们就是 125.28pt 那一行的全部内容）。
CUBE2_DECLARATIONS = (
    "LCubeSum.sum_cubes_one",
    "LCubeSum.two_dvd_mul_succ",
    "LCubeSum.four_mul_div_two_sq",
    "LCubeSum.induct_algebra",
    "LCubeSum.sum_cubes_succ_step",
)

#: 真机论文包的候选落点（新的在前；两条都不在就跳过只读那几条）。
CUBE2_PACKAGES = (
    Path(__file__).resolve().parents[1] / "projects" / "cube2" / "out" / "paper",
    Path("D:/Incubator/cube2/out/paper"),
)

#: 政策里必须读到的意思（去掉强调符号与空白之后逐条核；与 D-45 那套判据同一口径）。
POLICY_NEEDLES: tuple[tuple[str, str], ...] = (
    ("长路径", "点名「长路径」这一类串"),
    ("可断行", "点名「必须可断行」这个要求"),
    ("\\path{", "点名 url 宏包的 `\\path{}` 这条路"),
    ("\\allowbreak", "点名 `\\allowbreak{}` 这条路"),
    ("整串", "点名「整串不可断」这个禁形"),
    ("20pt", "点名那道 20pt 的读数门"),
)

_EMPHASIS = re.compile(r"[\s*`]+")

_PROMPT_TASK = "整理成论文"
_PROMPT_ROOT = "D:/x"
_PROMPT_FACTS = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
                 "- 检查器：（判据夹具，与机器无关）")
_PROMPT_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
                  "- （判据夹具：这一次按自足文件写）")


# ---------------------------------------------------------------- 静态检查

def _flat(text: str) -> str:
    """去掉强调符号与所有空白（判「读到的意思」，不判排版）。"""
    return _EMPHASIS.sub("", str(text))


def _display(content: str) -> str:
    """串「印出来是什么」：去掉断行宏（它们不占版面），再把 `\\_` 还原成一个字。"""
    plain = _BREAK_NOISE.sub("", content)
    return (plain.replace("\\_", "_").replace("\\%", "%")
            .replace("\\&", "&").replace("\\#", "#"))


def _unescape(content: str) -> str:
    """串的内容（判据点名时给人看的那一份；`\\_` 算一个字）。"""
    return _display(content)


def _lineno(text: str, pos: int) -> int:
    """第 pos 个字符在第几行（1 起；判据要「点名行号」）。"""
    return text.count("\n", 0, pos) + 1


def _breakable(content: str, macro: str) -> bool:
    """这一串自己能不能断行（False = 不能 ⇒ 判红）。"""
    if _BREAK_MEANS.search(content):
        return True
    return macro in _URL_MACROS and bool(_URL_BREAK_CHARS & set(_display(content)))


def long_typewriter_findings(text: str, *, limit: int = LONG_RUN_CHARS
                             ) -> list[tuple[int, str, str, int]]:
    """正文里「连续且合计到 limit 字」的 typewriter 串里，每一处不能断行的出现。

    返回 `(行号, 宏名, 串的内容, 这一段连续的合计字数)`；空清单 = 都过。
    """
    occurrences = [(m.start(), m.end(), m.group("macro"), m.group("content"))
                   for m in _OCCURRENCE.finditer(text)]
    runs: list[list[tuple[int, int, str, str]]] = []
    current: list[tuple[int, int, str, str]] = []
    for start, end, macro, content in occurrences:
        if current:
            gap = text[current[-1][1]:start]
            if not _RUN_GLUE.match(gap):
                runs.append(current)
                current = []
        current.append((start, end, macro, content))
    if current:
        runs.append(current)

    findings: list[tuple[int, str, str, int]] = []
    for run in runs:
        total = sum(len(_display(content)) for _start, _end, _macro, content in run)
        if total < limit:
            continue
        for start, _end, macro, content in run:
            if _breakable(content, macro):
                continue
            findings.append((_lineno(text, start), macro, _display(content), total))
    return findings


def _body_only(tex: str) -> str:
    """正文那一段（`\\appendix` 之前）；没有 `\\appendix` 就是整份。"""
    match = re.search(r"(?m)^\\appendix\b", tex)
    return tex[:match.start()] if match else tex


def _appendix_line(tex: str) -> int:
    """`\\appendix` 在第几行（没有就当成无穷远）。"""
    match = re.search(r"(?m)^\\appendix\b", tex)
    return _lineno(tex, match.start()) if match else 10 ** 9


# ---------------------------------------------------------------- 断行手段

_TT_BODY = re.compile(r"\\texttt\{((?:[^{}\\]|\\.)*)\}")
_PATH_BODY = re.compile(r"\\path\{((?:[^{}\\]|\\.)*)\}")


def _with_path(paragraph: str) -> str:
    """按政策第一条路改一遍：`\\texttt{x\\_y}` → `\\path{x_y}`（url 宏包，可断行）。"""
    return _TT_BODY.sub(lambda m: "\\path{" + m.group(1).replace("\\_", "_") + "}", paragraph)


def _with_allowbreak(paragraph: str) -> str:
    """按政策第二条路改一遍：在 `/ . _ -` 之后插 `\\allowbreak{}`。"""
    return _TT_BODY.sub(
        lambda m: "\\texttt{" + re.sub(r"([/._-])", r"\1\\allowbreak{}", m.group(1)) + "}",
        paragraph)


def _strip_breaks(paragraph: str) -> str:
    """把两条断行手段都拆掉（反真空：拆完必须又红）。"""
    back = _PATH_BODY.sub(lambda m: "\\texttt{" + m.group(1).replace("_", "\\_") + "}",
                          paragraph)
    return back.replace("\\allowbreak{}", "")


# ---------------------------------------------------------------- 编译

def _pdflatex() -> str:
    """本机有没有 TeX 引擎（没有时第 2 条降级成第 1 条）。"""
    for candidate in _PDFLATEX_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).is_file():
            return candidate
    return ""


def _engine_env(work: Path) -> dict[str, str]:
    """引擎的环境：MiKTeX 的用户目录挪进临时目录（与 `papercompile._engine_env` 同口径）。"""
    env = dict(os.environ)
    env.setdefault("MIKTEX_USERDATA", str(work / ".miktex" / "data"))
    env.setdefault("MIKTEX_USERCONFIG", str(work / ".miktex" / "config"))
    env.setdefault("MIKTEX_AUTOINSTALL", "0")
    return env


def _host(body: str) -> str:
    """一段正文 + 一个最小导言区（ctexart + geometry + url，与真机那份同宽）。"""
    return "\n".join([
        r"\documentclass[11pt]{ctexart}",
        r"\usepackage{amsmath,amssymb,amsthm}",
        r"\usepackage[margin=2.5cm]{geometry}",
        r"\usepackage{url}",
        r"\newtheorem{theorem}{Theorem}[section]",
        r"\newtheorem{claim}[theorem]{Lemma}",
        r"\begin{document}",
        r"\section{Main results}\label{sec:main}",
        r"\paragraph{Formal verification.}\label{sec:formal}",
        body,
        r"\end{document}",
        "",
    ])


def _compile(work: Path, *, runs: int = 2) -> tuple[int, str]:
    """编一遍 `work/main.tex`（与 `papercompile` 一样两遍），返回（最后一遍退出码、日志）。"""
    code = 0
    for _ in range(max(1, int(runs))):
        proc = subprocess.run([_pdflatex(), "-interaction=nonstopmode", "-halt-on-error",
                               "main.tex"],
                              cwd=str(work), capture_output=True, text=True,
                              env=_engine_env(work), timeout=300)
        code = int(proc.returncode)
    log_path = work / "main.log"
    log = (log_path.read_text(encoding="utf-8", errors="replace")
           if log_path.is_file() else proc.stdout)
    return code, log


def body_overfulls(tex: str, log: str, *, gate: float = OVERFULL_GATE_PT
                   ) -> list[tuple[int, float]]:
    """正文段（`\\appendix` 之前）宽度超过 gate 的 `Overfull \\hbox`：`(起始行, pt)`。

    为什么要切两刀：附录那张表由 `\\input{mapping-appendix}` 进来，它在日志里的行号是
    `mapping-appendix.tex` 自己的行号（6--13 落在 `\\appendix` 之前），只按行号判会把它
    误算成正文；反过来，main.tex 自己的附录散文（359--403 行）只按文件切也会漏判。
    """
    gate_line = _appendix_line(tex)
    cut_match = _APPENDIX_INPUT.search(log)
    cut = cut_match.start() if cut_match else len(log)
    out: list[tuple[int, float]] = []
    for match in _OVERFULL_PARAGRAPH.finditer(log):
        if match.start() >= cut:
            continue
        line = int(match.group(2))
        if line < gate_line and float(match.group(1)) > gate:
            out.append((line, float(match.group(1))))
    for match in _OVERFULL_DETECTED.finditer(log):
        if match.start() >= cut:
            continue
        line = int(match.group(2))
        if line < gate_line and float(match.group(1)) > gate:
            out.append((line, float(match.group(1))))
    return out


@pytest.fixture(scope="module")
def compiled(tmp_path_factory: pytest.TempPathFactory):
    """按 tex 源码缓存编译结果（同一份源码只编一次：本文件一共起四次引擎）。"""
    root = tmp_path_factory.mktemp("d47-tex")
    cache: dict[str, tuple[int, str]] = {}

    def _get(source: str, assets: dict[str, str] | None = None) -> tuple[int, str]:
        if source not in cache:
            work = root / f"case-{len(cache)}"
            work.mkdir()
            (work / "main.tex").write_text(source, encoding="utf-8")
            for name, text in (assets or {}).items():
                (work / name).write_text(text, encoding="utf-8")
            cache[source] = _compile(work)
        return cache[source]

    return _get


# ---------------------------------------------------------------- 现场

def _live_package() -> Path | None:
    """真机论文包（只读；本机找不到就返回 None）。"""
    for candidate in CUBE2_PACKAGES:
        if (candidate / "main.tex").is_file():
            return candidate
    return None


def _live_tex() -> str:
    package = _live_package()
    if package is None:
        pytest.skip("本机没有真机论文包（projects/cube2/out/paper 与 D:/Incubator/cube2 都不在）"
                    "⇒ 这一条只核静态夹具，不判现场（P16：未查不等于通过）")
    return (package / "main.tex").read_text(encoding="utf-8")


# ============================================================ 1 静态
def test_1_the_live_body_names_every_unbreakable_run_of_long_typewriter() -> None:
    """① cube2 正文里那段连排的声明名被逐条点名（行号 + 串）。

    改之前为什么红：这一格压根没有判据 —— 提示词只写「正文是你写的」，没写长串能不能断；
    于是正文把 `\\texttt{LCubeSum.…}` 五个声明名连排，日志里那一行撑出 125.28pt。
    本条要的是：检查器在这种样本上报出至少 5 处，且点名那五个声明名与它们的行号。

    现场那条 125.28pt 的整行是五个声明名（四个在同一行、第五个在下一行开头），单看每个
    都不到 40 字；判据按「连续串合计」算，正是为了抓住这种形态。
    """
    findings = long_typewriter_findings(_body_only(_live_tex()))
    assert len(findings) >= 5, (
        f"正文里只报出 {len(findings)} 处不可断的长串（至少要 5 处）⇒ 判据没有读到真机那段："
        f"{findings}")
    lines = [line for line, _macro, _content, _total in findings]
    assert all(isinstance(line, int) and line > 0 for line in lines), findings
    assert 264 in lines, f"没有点名第 264 行（那一段的起点）：{findings}"
    named = {content for _line, _macro, content, _total in findings}
    missing = [name for name in CUBE2_DECLARATIONS if name not in named]
    assert missing == [], f"这五个声明名里有没被点名的：{missing}"
    totals = {total for _line, _macro, _content, total in findings}
    want = sum(len(name) for name in CUBE2_DECLARATIONS)
    assert totals == {want}, f"那一段的合计字数应为 {want}（五个声明名），实际 {sorted(totals)}"


def test_2_the_live_appendix_sha256_is_named_too() -> None:
    """① 续：整份 main.tex 里那个 64 位 sha256 也被点名（附录散文里的 185.70pt）。

    改之前为什么红：同一个成因 —— 附录散文里 `\\texttt{37e3517…}` 是 64 个十六进制字符，
    一个断点也没有，日志里那一条 185.70pt。它不在 D-46 的射程里（D-46 管的是渲染出来的
    那张表），所以同一条静态判据要能把它也点名。

    边界：这一条只判「静态能点名」，不判它被修好 —— 真机工作区是只读的冻结记录。
    """
    tex = _live_tex()
    findings = long_typewriter_findings(tex)
    hashes = [(line, content) for line, _macro, content, _total in findings
              if re.fullmatch(r"[0-9a-f]{64}", content)]
    assert hashes, f"整份 tex 里没有点名任何 64 位十六进制串：{findings}"
    line, content = hashes[0]
    assert line > _appendix_line(tex), (
        f"那个 sha256 应当落在附录（第 {_appendix_line(tex)} 行之后），实际点名第 {line} 行")
    assert content.startswith("37e351749ef9"), content


def test_3_a_body_whose_long_strings_can_break_has_no_finding() -> None:
    """① 正控：同一段正文按政策的任意一条路改完，检查器一处都不报。

    改之前为什么红：改之前没有「可断行」这个要求，也就没有这个检查器。这一条守的是
    「报红不是碰巧」—— 两段改后的正文都不该有长串，否则第 1 条只是「恒红」。

    两条路都在政策里点名：`\\path{}`（url 宏包）与在 `/ . _ -` 之后插 `\\allowbreak{}`。
    """
    by_path = _with_path(CUBE2_BODY_PARAGRAPH)
    by_allowbreak = _with_allowbreak(CUBE2_BODY_PARAGRAPH)
    assert long_typewriter_findings(by_path) == [], long_typewriter_findings(by_path)
    assert long_typewriter_findings(by_allowbreak) == [], long_typewriter_findings(by_allowbreak)
    # 两条路都得留着那五个名字（改完还是同一份论文，不是把串删了）。
    for label, text in (("path", by_path), ("allowbreak", by_allowbreak)):
        readable = _display(text)
        for name in CUBE2_DECLARATIONS:
            assert name in readable, f"{label} 改完之后连 {name} 都没了：不是断行，是删串"


# ============================================================ 2 编译
def test_4_the_fixed_body_compiles_without_a_wide_body_overfull(compiled) -> None:
    """② 改后的正文段编一遍：`Overfull \\hbox` 超过 20pt 的条数为 0。

    改之前为什么红：改前那一段编出来是 125.28pt（`in paragraph at lines 262--274`），
    门是 20pt。按政策第二条路（在 `/ . _ -` 之后插 `\\allowbreak{}`）改完，0 条。

    为什么正控只用第二条路编：这条实测过 —— 同一个段落改用 `\\path{}` 之后仍然剩一条
    33.76pt 的宽盒（url 宏包在 `/ . _ -` 处给的断点，对「一串宽声明名 + 逗号空格」这种
    排法还是排不出一行放得下的断法；`\\path{}` 把 125.28pt 降到 33.76pt，但不归零）。
    所以政策里那两条路不是等价的：串与串连排时，断点要落在每一串内部。第 3 条仍把
    `\\path{}` 认作断行手段（它确实给了断点，单串场景够用），这里只把「编出来 0 条」
    钉在真正归零的那条路上。

    没有 TeX 引擎时降级成静态检查：只断言同一段正文的静态检查通过（第 1 / 3 条已经
    把「串不能断」判红，所以降级之后仍然不是空判）。
    """
    source = _host(_with_allowbreak(CUBE2_BODY_PARAGRAPH))
    if not _pdflatex():
        assert long_typewriter_findings(_body_only(source)) == [], \
            "没有 pdflatex 时的降级检查：改后的正文里仍然有不可断的长串"
        pytest.skip("没有 pdflatex：第 2 条降级成静态检查（改后的正文里不再有长串）")
    code, log = compiled(source)
    wide = body_overfulls(source, log)
    assert wide == [], (f"改完仍然撑出页宽（门 {OVERFULL_GATE_PT}pt）："
                        f"{wide}；引擎退出码 {code}")
    # 反真空的一半：这份日志真的编完了那一段（不是「什么都没读出来」）。
    assert "Formal verification" in log or code == 0, (code, log[-800:])


def test_5_the_live_body_really_overflows_before_the_fix(compiled) -> None:
    """② 改前读数：真机那份 main.tex 原样编一遍，正文段有一条超过 100pt 的 Overfull。

    改之前为什么红：这一条量的是缺陷本身 —— 改之前它当然成立（这正是 D-47 的读数），
    改之后真机工作区没有被动过（只读纪律），所以它仍然成立；一旦有人把现场那份正文
    改成可断行，这一条会红，提示把样本移进夹具、并删掉这一条「改前读数」。

    同时钉住 D-46 的边界：附录那张表（`mapping-appendix.tex`）的宽盒不算进正文这一段，
    否则这一条会把 D-46 的缺陷算到 D-47 头上（那张表的 234.37pt 与正文无关）。
    """
    package = _live_package()
    tex = _live_tex()
    if not _pdflatex():
        pytest.skip("没有 pdflatex：第 2 条的改前读数判不了（本机没有 TeX 引擎）")
    assets: dict[str, str] = {}
    appendix = package / "mapping-appendix.tex"
    if appendix.is_file():
        assets[appendix.name] = appendix.read_text(encoding="utf-8")
    code, log = compiled(tex, assets)
    wide = body_overfulls(tex, log)
    assert wide, ("真机正文段应当至少有一条超过 20pt 的 Overfull（D-47 的现场），"
                  f"实际一条都没有；引擎退出码 {code}")
    assert max(pt for _line, pt in wide) > 100.0, (
        f"最宽的一条应当超过 100pt（现场是 125.28pt），实际 {wide}")
    # 反真空的一半：同一份日志里确实有 `mapping-appendix` 那一段（不是「什么都没看见」）。
    if appendix.is_file():
        assert "mapping-appendix" in log, (
            "日志里没有 `mapping-appendix` 那一段 ⇒ 这条判据没读到附录，切片规则无从验证")


# ============================================================ 3 反真空
def test_6_stripping_the_break_macros_turns_both_checks_red(compiled) -> None:
    """③ 反真空：把断行手段拆掉 ⇒ 静态检查与编译检查都必红。

    改之前为什么红：这一条要拆的那个东西（断行手段）改之前根本不在正文里，于是
    「拆掉之后变红」这件事无从谈起 —— 而现在它守的是第 1、2 条不是碰巧绿的：
    拆完之后静态检查又报回那 5 处，编译又出那条 125pt 的宽盒。

    顺带一条不变量：`_with_path` 与 `_strip_breaks` 互逆（改前样本 = 拆完的样本），
    否则这一条的「拆掉」测的是别的东西。
    """
    fixed = _with_path(CUBE2_BODY_PARAGRAPH)
    stripped = _strip_breaks(fixed)
    assert stripped == CUBE2_BODY_PARAGRAPH, "改前样本与拆行后的样本不是同一份 ⇒ 这一条测错了对象"
    red = long_typewriter_findings(stripped)
    assert len(red) >= 5, f"拆掉断行手段之后静态检查只报出 {len(red)} 处：{red}"
    if not _pdflatex():
        pytest.skip("没有 pdflatex：第 3 条只核静态那一半（拆完又报回 5 处）")
    source = _host(stripped)
    code, log = compiled(source)
    wide = body_overfulls(source, log)
    assert wide, f"拆掉断行手段之后编出来却没有宽盒（引擎退出码 {code}）⇒ 第 2 条在空判"
    assert max(pt for _line, pt in wide) > 100.0, wide


# ============================================================ 4 政策
def test_7_the_policy_and_the_skills_section_say_it() -> None:
    """④ 政策落点：G 的 policy（进提示词）与「成稿-正文自己写」那份手册都写着这条口径。

    改之前为什么红：两处都只有「正文是你写的」与「硬线只有一条：语言必须是英文」，
    没有一处说长串能不能断行 —— 于是模型把它整串排进 `\\texttt`，日志里 5 条 Overfull。

    `specs/g.py` 在 FC-27 禁改区（auth-audit）：这一条只读它的内容，改动本身按
    「先改后签」登记（报告里给逐行列清单与 `noai_gate --paths` 原文）。
    """
    policy = "\n".join(GS.SPEC.brief.policy)
    missing = [f"policy 里读不到「{needle}」（{why}）"
               for needle, why in POLICY_NEEDLES if _flat(needle) not in _flat(policy)]
    assert missing == [], "\n".join(missing)

    text = AP.system_prompt("G", registry=build_registry().registry, task=_PROMPT_TASK,
                            workspace_root=_PROMPT_ROOT, toolchain_facts=_PROMPT_FACTS,
                            toolchain_formal=_PROMPT_FORMAL)
    assert len(text) > 3000, f"渲染出来的提示词只有 {len(text)} 字 ⇒ 这一条没有落脚点"
    absent = [needle for needle, _why in POLICY_NEEDLES if _flat(needle) not in _flat(text)]
    assert absent == [], f"渲染出来的提示词里缺 {absent}（policy 没进前置提示词）"

    skill = next(s for s in AS.CATALOG["G"] if s.slug == "成稿-正文自己写")
    body = skill.body
    for needle, why in POLICY_NEEDLES:
        assert _flat(needle) in _flat(body), f"「成稿-正文自己写」里读不到「{needle}」（{why}）"
    # 那一节是 `fs.read` 读的盘上文件：路径与正文要能对上（名字里带中文，直接比）。
    assert AS.skill_path("G", skill.slug) == "skills/G/成稿-正文自己写.md"
