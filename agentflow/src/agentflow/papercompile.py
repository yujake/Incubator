# -*- coding: utf-8 -*-
"""论文包只剩一件事：把智能体写好的正文编成 PDF（业主裁定）。

## 为什么这一层是现在这样（旧的一整条退场了）

旧的一路要求项目里自带一对脚本（`code/make_paper.py` + `code/compile_paper.py`），
用它们"从台账机械地渲染出 LaTeX、再编译、再核锚"。业主裁定那些是古早废案：正文由
智能体（G）自己写进 `out/package/main.tex`（散文体、章节自排），框架不要求任何"渲染
脚本"，也不再核锚。

要求"项目自带渲染脚本"这件事本身就是病灶：从零研究的工作区没有那对脚本，于是模型
只好在会话里现写生成器，排版就被固化成脚本模板（一节一整段、摘要硬编码、非 ASCII
静默变空格、没有 fontenc ⇒ `>=` 印成 `¿=`）。所以它整条退场。

## 现在这一层管什么（只此一件）

`compile_paper(project_root)`：找 `out/package/main.tex` → 起 LaTeX 引擎（两遍）→
写 `main.pdf`、框架自己写的 `COMPILE-RECEIPT.json`（这份 PDF 是从哪一份 tex 编出来的）
与「这一次」的编译日志 `compile-<YYYYmmdd-HHMMSS>.log`（引擎 stdout；stderr 另落
`compile-<…>.stderr.log`）。日志一次编译一份、不追加，最后一行是机器可读的
`result: {…}`，它说的与盘上产物必须一致。

四条刻意的口径：

1. 不跑项目脚本：引擎由框架直接起（`subprocess.run([engine, ...])`），项目里有没有
   `code/*.py` 与本层无关；
2. 回执由框架写：`tex_sha256` / `pdf_sha256` / `engine` / `runs` / `exit_codes` /
   `pages` / `pdf_bytes` / `compiled_at`。它是"这份 PDF 不是旧 tex 编的"唯一读数
   （人改完正文不重编，这一格说得出来）；
3. 退出码与产物分开报：本机 MiKTeX 在收尾时可能以 `0xC0000409` 退出却已经写出 PDF ——
   所以"拿到 PDF"与"引擎退出码是 0"是两栏，谁也不冒充谁。用户目录挪进项目
   （`MIKTEX_USERDATA` / `MIKTEX_USERCONFIG`）就是为这一档加的环境适配；
4. 三态：
   `not_applicable`（`main.tex` 不在盘上 = 还没写正文，合法初态）；
   `unknown`（引擎不在 PATH / 超时 / 没编出 PDF）；
   `computed`（拿到 PDF —— 页数与退出码如实带上）。
   回执与盘上 `main.tex` 对不上时，另由 `receipt_matches_tex()` 回 `False`
   （那读数的意思是"这份 PDF 是旧 tex 编的"，不是"没编过"）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

__all__ = ["ENGINE_ENV", "ENGINES", "LOG_PREFIX", "LOG_SUFFIX", "LOG_WARNING_KINDS",
           "PDF_NAME", "RECEIPT_NAME", "STDERR_LOG_SUFFIX", "TEX_NAME", "compile_log_path",
           "compile_paper", "file_digest", "package_dir", "read_receipt",
           "read_tex_warnings", "receipt_matches_tex"]

#: 论文包在项目根下的落点（与旧路的落点一致，习惯不变）。
PACKAGE_REL = ("out", "package")
TEX_NAME = "main.tex"
PDF_NAME = "main.pdf"
#: 编译回执：框架写（旧路里它由项目脚本写，那是退场的一部分）。
RECEIPT_NAME = "COMPILE-RECEIPT.json"
#: 单次编译日志的名字（一次编译一份，不追加、不拼接）。
#:
#: 旧路（已退场的项目脚本 `code/compile_paper.py`）写 `compile.log`：`open("a")` 追加、
#: `stderr=STDOUT` 混流，最多 46 个 `pass` 标记 = 23 次编译拼在一个文件里，且末 6 行是
#: 「pdflatex did not succeed」而同一目录躺着 21 页 PDF。名字说「这次编译的日志」，内容
#: 是「历次编译的流水账」—— 读的人只能读错（`temp/paperpkg/REPORT.md` M10）。
#: 现在日志名带时间戳：读一份就是读一次编译；`compile.log` 这个旧名不再产生、也不被读。
LOG_PREFIX = "compile-"
LOG_SUFFIX = ".log"
#: 引擎 stderr 的落点（与 stdout 日志分开：混在一个文件里就分不清哪一行是引擎的
#: 错误、哪一行是 LaTeX 自己转录的 `.log` 输出）。
STDERR_LOG_SUFFIX = ".stderr.log"

#: 引擎候选（按这个顺序取第一个在 PATH 上的）。
ENGINES: tuple[str, ...] = ("pdflatex", "xelatex", "lualatex")

#: 指定引擎的环境变量（覆盖上面那条探测顺序）。给它一个绝对路径就按它起 ——
#: 判据（`tests/test_papercompile.py`）与"本机装了别的 TeX 发行版"这两种场合都要它。
#: 给的名字不存在时不编造读数：`subprocess` 抛 `FileNotFoundError` ⇒ 如实
#: 落 `tri="unknown"` + `reason`。
ENGINE_ENV = "AGENTFLOW_LATEX_ENGINE"

#: 单次引擎调用的默认超时（秒）。编译两遍 ⇒ 最坏 2×这个数。
DEFAULT_TIMEOUT_SEC = 900.0

#: 会被折成读数的 TeX 日志警告（`read_tex_warnings` 的唯一词表）。
#:
#: 2026-11-26（GTOOL-HARD）：真论文的 `main.log` 里有 21 处 Overfull（正文 1 处 7.47pt、
#: 渲染出来的附录表 20 处、最宽 18.93pt），而 `compile_paper` 的 `problems` 是空的 ——
#: 它只记"框架自己的故障"，一个字都没读过 `main.log`。读者看得见的问题不许只躺在日志里。
LOG_WARNING_KINDS: tuple[str, ...] = (
    "overfull", "underfull", "undefined_reference", "undefined_citation",
    "multiply_defined", "missing_file",
)

_OVERFULL_RE = re.compile(
    r"(?P<kind>Overfull|Underfull) \\[hv]box \((?P<detail>[^)]*)\).*?"
    r"at lines? (?P<line>\d+)")
_UNDEFINED_RE = re.compile(
    r"LaTeX Warning: (?P<what>Reference|Citation) `(?P<key>[^']*)' on page \S+ undefined"
    r" on input line (?P<line>\d+)")
_MULTI_LABEL_RE = re.compile(r"LaTeX Warning: Label `(?P<key>[^']*)' multiply defined")
_MISSING_FILE_RE = re.compile(r"^! LaTeX Error: File `(?P<name>[^']*)' not found")
#: 日志里"当前正在读哪一份 .tex"：TeX 用 `(./main.tex` / `(mapping-appendix.tex` 打开文件。
_CURRENT_TEX_RE = re.compile(r"\((?P<path>\.?/?[^()\s]*\.tex)")


def _width_of(detail: str) -> float:
    """一条 overfull 的宽度（pt；读不出算 0 —— 只用于"哪一条最宽"的读数）。"""
    m = re.search(r"([0-9.]+)pt", str(detail or ""))
    try:
        return float(m.group(1)) if m else 0.0
    except ValueError:  # pragma: no cover —— 正则已经限定成数字
        return 0.0


def read_tex_warnings(package: str | Path) -> tuple[list[dict[str, Any]], str]:
    """读 `<package>/main.log`，折成 `[{kind, file, line, detail}]`；读不成给理由。

    只认 `LOG_WARNING_KINDS` 这六类。`file` 是包内相对名（`main.tex` /
    `mapping-appendix.tex`），`line` 是日志自己说的那个行号 —— 两者都进 `why`，
    调用方（`compile_paper`）把它拼成 `out/package/<file>:<line>` 给 G。
    三态：读不成 ⇒ `([], 理由)`，不是"没有警告"（调用方必须把那句话带回去）。
    """
    log = Path(package) / "main.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], f"{log} 读不出来（{type(exc).__name__}: {exc}）⇒ 编译警告这一档没查成"
    found: list[dict[str, Any]] = []
    current = TEX_NAME
    stack: list[str] = []
    for raw in text.splitlines():
        if raw.strip() == ")" and stack:
            stack.pop()  # 一份 `\input` 进来的正文读完了：TeX 用一行 `)` 收尾
            current = stack[-1] if stack else TEX_NAME
        for m in _CURRENT_TEX_RE.finditer(raw):
            current = m.group("path").lstrip("./")
            if current != TEX_NAME:
                stack.append(current)
        item: dict[str, Any] | None = None
        m = _OVERFULL_RE.search(raw)
        if m is not None:
            item = {"kind": m.group("kind").lower(), "file": current,
                    "line": int(m.group("line")), "detail": m.group("detail")}
        else:
            m = _UNDEFINED_RE.search(raw)
            if m is not None:
                kind = "undefined_reference" if m.group("what") == "Reference" else "undefined_citation"
                item = {"kind": kind, "file": current, "line": int(m.group("line")),
                        "detail": f"键 {m.group('key')!r}"}
            else:
                m = _MULTI_LABEL_RE.search(raw)
                if m is not None:
                    item = {"kind": "multiply_defined", "file": current, "line": 0,
                            "detail": f"键 {m.group('key')!r}"}
                else:
                    m = _MISSING_FILE_RE.search(raw)
                    if m is not None:
                        item = {"kind": "missing_file", "file": current, "line": 0,
                                "detail": m.group("name")}
        if item is not None and item["kind"] in LOG_WARNING_KINDS:
            found.append(item)
    return found, ""


#: 每一类警告"为什么要改"（`read_tex_warnings` 的消费者 `compile_paper` 用它拼 problems）。
WARNING_WHY: dict[str, str] = {
    "overfull": "版心外溢：不可断行的长串 / 表格列宽 —— 渲染出来的文件（如 "
                "mapping-appendix.tex）要改渲染器，别手改",
    "undefined_reference": "交叉引用悬空：PDF 里印的是 ??",
    "undefined_citation": "文献键没有对应的 \\bibitem：PDF 里印的是 [?]",
    "multiply_defined": "同一个 \\label 定义了两次：\\ref 会指到后一处",
    "missing_file": "引擎找不到文件：那一支的正文/宏包没进稿",
}


def file_digest(path: str | Path) -> str:
    """文件内容 sha256（读不到返回空串 —— 调用方按"读不到"处理，不编哈希）。"""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def package_dir(project_root: str | Path) -> Path:
    """论文包目录（`<项目根>/out/package`）。"""
    return Path(project_root).joinpath(*PACKAGE_REL)


def _snapshot(pdf: Path) -> tuple[float, str] | None:
    """盘上那份 PDF 的 (修改时间, 摘要)：不在 ⇒ `None`。"""
    try:
        if not pdf.is_file():
            return None
        return (pdf.stat().st_mtime, file_digest(pdf))
    except OSError:
        return None


def _fresh(pdf: Path, before: tuple[float, str] | None) -> bool:
    """盘上那份 PDF 是不是这一趟写出来的。

    判据是"编译前后的快照变了"（修改时间变新，或内容换了）—— 不是"文件在不在"：
    上一次编的 PDF 会一直躺在那里，把它当成本次读数就等于说"这一次编成功了"。

    为什么不删掉旧的再编：旧 PDF 是用户上一次的产物，编译失败时删掉它等于让一次失败的
    编译顺手毁掉上一份能看的稿子。所以不删，只把"这份是不是本次的"如实记成 `pdf_fresh`
    （`False` 就是"这一次没编出 PDF，盘上那份是旧的"）。
    """
    now = _snapshot(pdf)
    if now is None:
        return False
    if before is None:
        return True
    return now[0] > before[0] or now[1] != before[1]


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def read_receipt(project_root: str | Path) -> tuple[dict[str, Any] | None, str]:
    """读回执：`(回执 或 None, 一句话原因)`。"""
    path = package_dir(project_root) / RECEIPT_NAME
    if not path.is_file():
        return None, f"{RECEIPT_NAME} 不在盘上（{path}）⇒ 这份 PDF 的来路判不了"
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{RECEIPT_NAME} 读不出来（{type(exc).__name__}: {exc}）"
    if not isinstance(got, dict):
        return None, f"{RECEIPT_NAME} 必须是对象（收到 {type(got).__name__}）"
    return got, ""


def receipt_matches_tex(project_root: str | Path) -> tuple[bool | None, str]:
    """回执里那份 tex 与盘上现在这份是不是同一份：`(True/False/None, 原因)`。

    三态：回执不在 / `tex_sha256` 读不到 ⇒ `None`（判不了，不是"对得上"）。
    """
    receipt, why = read_receipt(project_root)
    if receipt is None:
        return None, why
    was = str(receipt.get("tex_sha256") or "")
    now = file_digest(package_dir(project_root) / TEX_NAME)
    if not was or not now:
        return None, "回执里的 tex_sha256 或盘上那一份读不到 ⇒ 判不了"
    if was != now:
        return False, (f"回执记的 tex 是 {was[:12]}…，盘上现在是 {now[:12]}… "
                       "⇒ 这份 PDF 是从旧 tex 编的（改完正文要重编一次）")
    return True, ""


def _page_count(pdf: Path) -> int | None:
    """PDF 页数（读不到 ⇒ `None`，不编一个数）。"""
    try:
        from .extract import page_count

        got = page_count(pdf)
    except Exception:  # noqa: BLE001 —— 页数是读数，读不到不影响"编出来没有"
        return None
    return int(got) if got else None


def _engine_env(project_root: Path) -> dict[str, str]:
    """引擎的环境：把 MiKTeX 的用户目录挪进项目内（见模块 docstring 的退出码那一节）。

    只 `setdefault`（本机已经配好的那一套优先），并且不改 `PATH`。
    """
    env = dict(os.environ)
    root = project_root / ".miktex"
    env.setdefault("MIKTEX_USERDATA", str(root / "data"))
    env.setdefault("MIKTEX_USERCONFIG", str(root / "config"))
    # 首次用到某个包时 MiKTeX 会现场联网装它 —— 那既慢又不可复现；缺包就如实报错。
    env.setdefault("MIKTEX_AUTOINSTALL", "0")
    return env


def _tail(raw: bytes | str | None, limit: int = 1500) -> str:
    """引擎输出的尾巴（解码 + 截尾）。留它是为了"失败时看得见为什么" —— 只回一句
    "脚本不在盘上"是不够的，脚本 / 引擎的 stderr 其实就在手边。"""
    if raw is None:
        return ""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


def _decode_any(raw: bytes | str | None) -> str:
    """原始输出解码（日志正文用：保留全文，不截尾）。"""
    if raw is None:
        return ""
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)


def compile_log_path(out: str | Path, *,
                     now: _dt.datetime | None = None) -> Path:
    """这一次编译的日志落点：`compile-<YYYYmmdd-HHMMSS>.log`（本次唯一，不追加）。

    同一秒内连编两次时加 `-2` / `-3` 后缀，仍然"一次编译一份"—— 不许退回追加。
    """
    stamp = (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = Path(out)
    path = base / f"{LOG_PREFIX}{stamp}{LOG_SUFFIX}"
    n = 1
    while path.exists():
        n += 1
        path = base / f"{LOG_PREFIX}{stamp}-{n}{LOG_SUFFIX}"
    return path


def _write_compile_log(out: Path, *, engine: str, tex_digest: str,
                       passes: list[dict[str, Any]],
                       result: dict[str, Any]) -> tuple[Path, Path]:
    """写这一次编译的日志；返回 `(stdout 日志, stderr 日志或空 Path)`。

    stdout 与 stderr 分两个文件：合流正是旧 `compile.log` 让人读错的第二半
    （引擎的「did not succeed」与 LaTeX 自己的 `.log` 转录长得一样）。主日志的
    最后一行是机器可读的结论（`result: {...}`），它说的与盘上产物必须一致：
    `pdf_fresh=false` 就是"这一次没编出 PDF"。
    """
    log = compile_log_path(out)
    lines = [
        "# agentflow.papercompile 单次编译日志（一次编译一份；不追加、不拼接）",
        f"# engine: {engine or '（没有可用引擎）'}",
        f"# tex_sha256: {tex_digest}",
    ]
    for item in passes:
        lines.append(f"===== {item['engine'] or engine} pass {item['pass']} =====")
        body = str(item.get("stdout") or "").rstrip()
        lines.append(body if body else "（stdout 为空）")
    if not passes:
        lines.append("===== 没有起引擎 =====")
    lines.append("result: " + json.dumps(result, ensure_ascii=False, sort_keys=True,
                                           default=str))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    err_text = "\n".join(
        f"===== {item['engine'] or engine} pass {item['pass']} stderr =====\n"
        f"{str(item.get('stderr') or '').rstrip()}"
        for item in passes if str(item.get("stderr") or "").strip())
    if not err_text.strip():
        return log, Path()
    err = log.with_name(log.stem + STDERR_LOG_SUFFIX)
    err.write_text(err_text + "\n", encoding="utf-8", newline="\n")
    return log, err


def compile_paper(project_root: str | Path, *, timeout_sec: float = DEFAULT_TIMEOUT_SEC,
                  engine: str = "", runs: int = 2) -> dict[str, Any]:
    """把 `<项目根>/out/package/main.tex` 编成 `main.pdf`，并写回执。返回三态读数。

    返回 `{tri, ok, reason, tex, pdf, engine, exit_codes, runs, pages, pdf_bytes,
    receipt_path, pdf_fresh, engine_stderr_tail, engine_stdout_tail, problems}`。

    - `tri="not_applicable"`：`main.tex` 不在盘上（还没写正文）；
    - `tri="unknown"`：没引擎 / 超时 / 这一次没编出 PDF（`reason` 说清是哪一档）——
      盘上可能还躺着上一次编的 `main.pdf`（`pdf_fresh=False` 就是这一档：产物不是这一趟的，
      不许当成本次读数）；
    - `tri="computed"`：这一趟拿到 PDF（`exit_codes` 与 `pages` 如实带上 —— 引擎非 0
      退出但写出 PDF 的形态在本机真实存在，两栏分开报）。
    """
    root = Path(project_root)
    out = package_dir(root)
    tex = out / TEX_NAME
    pdf = out / PDF_NAME
    problems: list[str] = []
    stderr_tail = ""
    stdout_tail = ""
    if not tex.is_file():
        return {"tri": "not_applicable", "ok": False,
                "reason": (f"{tex} 不在盘上 ⇒ 还没有可编的正文（正文由智能体自己写到那个落点）"),
                "tex": str(tex), "pdf": str(pdf), "engine": "", "exit_codes": [],
                "runs": 0, "pages": None, "pdf_bytes": None, "pdf_fresh": False,
                "receipt_path": str(out / RECEIPT_NAME),
                "compile_log": "", "compile_stderr_log": "",
                "engine_stderr_tail": "", "engine_stdout_tail": "", "problems": problems}

    #: 编译前的产物快照：用来回答"盘上那份 PDF 是这一趟编出来的，还是上一次留下的"。
    before_pdf = _snapshot(pdf)

    chosen = (engine or os.environ.get(ENGINE_ENV, "").strip()
              or next((e for e in ENGINES if shutil.which(e)), ""))
    out.mkdir(parents=True, exist_ok=True)
    codes: list[int] = []
    note = ""
    #: 本次每一遍引擎调用的原始输出（单次日志的正文；stderr 另落一个文件）。
    passes: list[dict[str, Any]] = []
    if not chosen:
        note = "没找到 LaTeX 引擎（" + "/".join(ENGINES) + " 都不在 PATH 上）"
        problems.append(note)
    else:
        env = _engine_env(root)
        from . import clock as _CLK

        for _ in range(max(1, int(runs))):
            argv = [chosen, "-interaction=nonstopmode", "-halt-on-error", tex.name]
            # 起程序就登记一条程序计时器，程序结束它返回（业主裁定）。
            with _CLK.program_span(program=chosen, argv=argv, workspace=root,
                                   where="papercompile.compile_paper",
                                   purpose=f"编 LaTeX 正文（{tex.name}）") as prog:
                try:
                    got = subprocess.run(argv,
                                         cwd=str(out), capture_output=True,
                                         timeout=timeout_sec,
                                         env=env)
                    codes.append(int(got.returncode))
                    stderr_tail = _tail(got.stderr)
                    stdout_tail = _tail(got.stdout)
                    passes.append({"pass": len(codes), "engine": Path(chosen).stem,
                                   "exit_code": int(got.returncode),
                                   "stdout": got.stdout.decode("utf-8", "replace"),
                                   "stderr": got.stderr.decode("utf-8", "replace")})
                    prog.finish(outcome="exited", exit_code=int(got.returncode))
                except subprocess.TimeoutExpired as exc:
                    codes.append(-1)
                    stderr_tail = _tail(getattr(exc, "stderr", None)) or stderr_tail
                    stdout_tail = _tail(getattr(exc, "stdout", None)) or stdout_tail
                    passes.append({"pass": len(codes), "engine": Path(chosen).stem,
                                   "exit_code": -1,
                                   "stdout": _decode_any(getattr(exc, "stdout", None)),
                                   "stderr": _decode_any(getattr(exc, "stderr", None))})
                    note = f"引擎超过 {timeout_sec}s 没返回（这一步没编完）"
                    prog.finish(outcome="timed_out", note=note)
                    break
                except (OSError, subprocess.SubprocessError) as exc:
                    codes.append(-1)
                    note = f"{type(exc).__name__}: {exc}"
                    passes.append({"pass": len(codes), "engine": Path(chosen).stem,
                                   "exit_code": -1, "stdout": "", "stderr": note})
                    prog.finish(outcome="failed", note=note)
                    break

    # "这一趟编出来没有"与"盘上有没有 PDF"是两件事：上一次编的 PDF 会一直躺在那里
    # （引擎什么都没产而那份旧 PDF 还在时，把它当成本次读数就等于说"编成功了"）。
    fresh = _fresh(pdf, before_pdf)
    if not note and codes and codes[-1] != 0:
        note = (f"引擎退出码 {codes[-1]} —— "
                + ("PDF 仍然写出来了（本机 MiKTeX 收尾失败的已知形态），"
                   "产物与退出码两栏都如实记" if fresh else "没有编出 PDF"))
    pages = _page_count(pdf) if fresh else None
    size = pdf.stat().st_size if fresh else None
    if not fresh and pdf.is_file() and not note:
        note = (f"{pdf.name} 在盘上但**不是这一趟写的**（它的修改时间早于这次编译开始）"
                "⇒ 这一次没编出 PDF，别把旧的那一份当成本次读数")
    tri = "computed" if fresh else "unknown"
    reason = note or (f"由本次源码编出（{chosen}，{pages} 页）" if fresh
                      else "没编出 PDF（引擎没给出任何产物）")
    # ---- 单次编译日志（一次编译一份）：末行 `result:` 的每一格都必须与盘上产物一致。
    # 写不进去不改变三态（日志是读数，不是产物闸）：如实记进 `problems`。
    result_payload = {"tri": tri, "engine": chosen or "", "runs": len(codes),
                      "exit_codes": codes, "pdf": str(pdf.name),
                      "pdf_fresh": fresh, "pages": pages, "pdf_bytes": size,
                      "reason": reason}
    try:
        log_path, stderr_log_path = _write_compile_log(
            out, engine=chosen, tex_digest=file_digest(tex),
            passes=passes, result=result_payload)
    except OSError as exc:
        log_path, stderr_log_path = Path(), Path()
        problems.append(f"编译日志没写成：{type(exc).__name__}: {exc}")
    receipt = {
        "tex_sha256": file_digest(tex),
        "pdf_sha256": file_digest(pdf) if fresh else "",
        "engine": chosen,
        "runs": len(codes),
        "exit_codes": codes,
        "pages": pages,
        "pdf_bytes": size,
        "pdf_fresh": fresh,
        "compiled_at": _now_iso(),
        "written_by": "agentflow.papercompile（框架内置编译）",
        # 引擎自己说的话（截尾）：产物与退出码之外，第三份"为什么"的读数。
        "stderr_tail": stderr_tail,
        # 这一次编译的日志（不是历史拼接）：读一份就是读一次；stderr 另落一个文件。
        "compile_log": log_path.name if log_path else "",
        "compile_stderr_log": stderr_log_path.name if stderr_log_path else "",
    }
    receipt_path = out / RECEIPT_NAME
    try:
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, default=str) + "\n",
                                encoding="utf-8", newline="\n")
    except OSError as exc:
        problems.append(f"回执没写成：{type(exc).__name__}: {exc}")

    # ---- 产物归属（`ARTIFACTS.jsonl`）：这一趟真的编出了 PDF ⇒ 登记它。
    #
    # 只登记 `fresh` 那一档：盘上那份旧 PDF 不是这一趟写的，把它登记成"我的产出"
    # 就是假归属（与上面 `pdf_fresh` 同一条纪律）。
    # `main.tex` 不在这里登记：它不是本函数写的（正文由智能体自己落盘），
    # 那个写口是 `fs.write`（FC-27，登记补丁在 `temp/AR-fs-write-draft.patch`）。
    # sha256 由 `artifacts.record` 从盘上现算 —— 与回执里的 `pdf_sha256` 同一个文件。
    if fresh:
        from . import artifacts as A

        _entry, _reg_problem = A.record_or_problem(
            root, path=f"out/package/{PDF_NAME}", producer="agentflow.papercompile",
            kind="paper-pdf",
            note=f"由 {chosen} 编出（exit_codes={codes}，{pages} 页）")
        if _reg_problem:
            problems.append(f"{_reg_problem}；PDF 本身已在盘上（out/package/{PDF_NAME}）")

    # ---- TeX 日志里读者看得见的那几类（GTOOL-HARD：`problems` 原先只记框架自己的故障，
    # 21 处 Overfull 一个都没进过读数面）。只读这一次真的起过引擎的那一份 `main.log`。
    if passes:
        warnings, warn_why = read_tex_warnings(out)
        if warn_why:
            problems.append(warn_why)
        else:
            for w in warnings:
                if w["kind"] in ("overfull", "underfull"):
                    continue  # 这两类按文件聚合（同一张表能出 20 条一模一样的读数）
                where = f"out/package/{w['file']}:{w['line']}" if w["line"] else (
                    f"out/package/{w['file']}")
                problems.append(f"{where} {w['kind']}（{w['detail']}）—— "
                                f"{WARNING_WHY.get(w['kind'], '')}")
            by_file: dict[str, list[dict[str, Any]]] = {}
            for w in warnings:
                if w["kind"] == "overfull":
                    by_file.setdefault(w["file"], []).append(w)
            for rel, items in sorted(by_file.items()):
                lines = ",".join(str(n) for n in sorted({x["line"] for x in items}))
                widest = _width_of(max(items, key=lambda x: _width_of(x["detail"]))["detail"])
                problems.append(
                    f"out/package/{rel}:{min(x['line'] for x in items)} 起共 {len(items)} 处 "
                    f"overfull（行 {lines}；最宽 {widest:.2f}pt）—— {WARNING_WHY['overfull']}")
            underfull = sum(1 for w in warnings if w["kind"] == "underfull")
            if underfull:
                problems.append(
                    f"另有 {underfull} 处 underfull（松排，盒子没出版心；只作读数，不逐条列）")
    base = {"tex": str(tex), "pdf": str(pdf), "engine": chosen,
            "exit_codes": codes, "runs": len(codes), "pdf_fresh": fresh,
            "receipt_path": str(receipt_path),
            "compile_log": str(log_path), "compile_stderr_log": str(stderr_log_path),
            "engine_stderr_tail": stderr_tail, "engine_stdout_tail": stdout_tail,
            "problems": problems}
    if fresh:
        return {"tri": "computed", "ok": True,
                "reason": reason,
                "pages": pages, "pdf_bytes": size, **base}
    return {"tri": "unknown", "ok": False,
            "reason": reason,
            "pages": None, "pdf_bytes": None, **base}

