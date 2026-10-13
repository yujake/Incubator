# -*- coding: utf-8 -*-
"""论文包只剩一件事：把智能体写好的正文编成 PDF（业主 2026-10-13 裁定）。

## 为什么这一层被换成现在这样（旧的一整条退场了）

旧的一路上有 `renderanchor`（渲染锚）、`paperbuild`（项目脚本通道）与角色动作
`G.paper_package`，它们要求**项目里自带一对脚本**（`code/make_paper.py` +
`code/compile_paper.py`）来"从台账机械地渲染出 LaTeX、再编译、再核锚"。
业主 2026-10-13 的裁定逐字是：「paper_package 里那些东西都是古早废案了，我们要智能体写文章」
—— 正文由智能体（G）自己写进 `out/paper/main.tex`（散文体、章节自排），框架不再要求
任何"渲染脚本"，也不再核锚。

旧路在第二次 T2 上的读数（`draft/116` §2）：从零研究工作区没有那对脚本 ⇒
`G.paper_package` 四次 `package_build_failed`（"脚本不在盘上"）⇒ 主控在会话里现写了一个
Python 生成器（`code/make_paper.py` 步 30/34、`code/compile_paper.py` 步 35…52 重写 5 次），
于是排版固化成脚本模板（一节一整段、摘要硬编码、非 ASCII 静默变空格、没有 fontenc
⇒ `>=` 印成 `¿=`）。**要求"项目自带渲染脚本"这件事本身就是病灶**，所以它整条退场。

## 现在这一层管什么（只此一件）

`compile_paper(project_root)`：找 `out/paper/main.tex` → 起 LaTeX 引擎（两遍）→
写 `main.pdf` 与**框架自己写的** `COMPILE-RECEIPT.json`（这份 PDF 是从哪一份 tex 编出来的）。

四条刻意的口径：

1. **不跑项目脚本**：引擎由框架直接起（`subprocess.run([engine, ...])`），项目里有没有
   `code/*.py` 与本层无关；
2. **回执由框架写**：`tex_sha256` / `pdf_sha256` / `engine` / `runs` / `exit_codes` /
   `pages` / `pdf_bytes` / `compiled_at`。它是"这份 PDF 不是旧 tex 编的"唯一读数
   （人改完正文不重编，这一格说得出来）；
3. **退出码与产物分开报**：本机 MiKTeX 在收尾时可能以 `0xC0000409` 退出却**已经写出 PDF**
   （第二次 T2 的实测：`exit_codes=[3221226505, 3221226505]`、`pages=3`）——
   所以"拿到 PDF"与"引擎退出码是 0"是两栏，谁也不冒充谁。用户目录挪进项目
   （`MIKTEX_USERDATA` / `MIKTEX_USERCONFIG`）正是按那次读数加的环境适配；
4. **三态**：
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
import shutil
import subprocess
from pathlib import Path
from typing import Any

__all__ = ["ENGINE_ENV", "ENGINES", "PDF_NAME", "RECEIPT_NAME", "TEX_NAME", "compile_paper",
           "file_digest", "package_dir", "read_receipt", "receipt_matches_tex"]

#: 论文包在项目根下的落点（与旧路的落点一致，习惯不变）。
PACKAGE_REL = ("out", "paper")
TEX_NAME = "main.tex"
PDF_NAME = "main.pdf"
#: 编译回执：**框架写**（旧路里它由项目脚本写，那是退场的一部分）。
RECEIPT_NAME = "COMPILE-RECEIPT.json"

#: 引擎候选（按这个顺序取第一个在 PATH 上的）。
ENGINES: tuple[str, ...] = ("pdflatex", "xelatex", "lualatex")

#: 指定引擎的环境变量（覆盖上面那条探测顺序）。给它一个绝对路径就按它起 ——
#: 判据（`tests/test_papercompile.py`）与"本机装了别的 TeX 发行版"这两种场合都要它。
#: 给的名字不存在时**不编造读数**：`subprocess` 抛 `FileNotFoundError` ⇒ 如实
#: 落 `tri="unknown"` + `reason`。
ENGINE_ENV = "AGENTFLOW_LATEX_ENGINE"

#: 单次引擎调用的默认超时（秒）。编译两遍 ⇒ 最坏 2×这个数。
DEFAULT_TIMEOUT_SEC = 900.0


def file_digest(path: str | Path) -> str:
    """文件内容 sha256（读不到返回空串 —— 调用方按"读不到"处理，不编哈希）。"""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def package_dir(project_root: str | Path) -> Path:
    """论文包目录（`<项目根>/out/paper`）。"""
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
    """盘上那份 PDF 是不是**这一趟**写出来的。

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
    """引擎的环境：把 MiKTeX 的用户目录挪进项目内（见模块 docstring 第 3 条）。

    只 `setdefault`（本机已经配好的那一套优先），并且**不**改 `PATH`。
    """
    env = dict(os.environ)
    root = project_root / ".miktex"
    env.setdefault("MIKTEX_USERDATA", str(root / "data"))
    env.setdefault("MIKTEX_USERCONFIG", str(root / "config"))
    # 首次用到某个包时 MiKTeX 会现场联网装它 —— 那既慢又不可复现；缺包就如实报错。
    env.setdefault("MIKTEX_AUTOINSTALL", "0")
    return env


def _tail(raw: bytes | str | None, limit: int = 1500) -> str:
    """引擎输出的尾巴（解码 + 截尾）。留它是为了"失败时看得见为什么" —— 旧路
    `G.paper_package` 失败时只回一句"脚本不在盘上"，脚本的 stderr 其实就在手边
    （`draft/116` §4 记着这一条；那一课不随旧路的退场而失效）。"""
    if raw is None:
        return ""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


def compile_paper(project_root: str | Path, *, timeout_sec: float = DEFAULT_TIMEOUT_SEC,
                  engine: str = "", runs: int = 2) -> dict[str, Any]:
    """把 `<项目根>/out/paper/main.tex` 编成 `main.pdf`，并写回执。返回三态读数。

    返回 `{tri, ok, reason, tex, pdf, engine, exit_codes, runs, pages, pdf_bytes,
    receipt_path, pdf_fresh, engine_stderr_tail, engine_stdout_tail, problems}`。

    - `tri="not_applicable"`：`main.tex` 不在盘上（还没写正文）；
    - `tri="unknown"`：没引擎 / 超时 / **这一次没编出 PDF**（`reason` 说清是哪一档）——
      盘上可能还躺着上一次编的 `main.pdf`（`pdf_fresh=False` 就是这一档：产物不是这一趟的，
      不许当成本次读数）；
    - `tri="computed"`：**这一趟**拿到 PDF（`exit_codes` 与 `pages` 如实带上 —— 引擎非 0
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
                "engine_stderr_tail": "", "engine_stdout_tail": "", "problems": problems}

    #: 编译前的产物快照：用来回答"盘上那份 PDF 是这一趟编出来的，还是上一次留下的"。
    before_pdf = _snapshot(pdf)

    chosen = (engine or os.environ.get(ENGINE_ENV, "").strip()
              or next((e for e in ENGINES if shutil.which(e)), ""))
    out.mkdir(parents=True, exist_ok=True)
    codes: list[int] = []
    note = ""
    if not chosen:
        note = "没找到 LaTeX 引擎（" + "/".join(ENGINES) + " 都不在 PATH 上）"
        problems.append(note)
    else:
        env = _engine_env(root)
        for _ in range(max(1, int(runs))):
            try:
                got = subprocess.run([chosen, "-interaction=nonstopmode",
                                      "-halt-on-error", tex.name],
                                     cwd=str(out), capture_output=True, timeout=timeout_sec,
                                     env=env)
                codes.append(int(got.returncode))
                stderr_tail = _tail(got.stderr)
                stdout_tail = _tail(got.stdout)
            except subprocess.TimeoutExpired as exc:
                codes.append(-1)
                stderr_tail = _tail(getattr(exc, "stderr", None)) or stderr_tail
                stdout_tail = _tail(getattr(exc, "stdout", None)) or stdout_tail
                note = f"引擎超过 {timeout_sec}s 没返回（这一步没编完）"
                break
            except (OSError, subprocess.SubprocessError) as exc:
                codes.append(-1)
                note = f"{type(exc).__name__}: {exc}"
                break
        if not note and codes and codes[-1] != 0:
            note = (f"引擎退出码 {codes[-1]} —— "
                    + ("PDF 仍然写出来了（本机 MiKTeX 收尾失败的已知形态），"
                       "产物与退出码两栏都如实记" if _fresh(pdf, before_pdf) else "没有编出 PDF"))

    # "这一趟编出来没有"与"盘上有没有 PDF"是两件事：上一次编的 PDF 会一直躺在那里
    # （第二次 T2 的读数逼出来的口径 —— 引擎什么都没产而那份旧 PDF 还在，
    #  把它当成本次读数就等于说"编成功了"）。
    fresh = _fresh(pdf, before_pdf)
    pages = _page_count(pdf) if fresh else None
    size = pdf.stat().st_size if fresh else None
    if not fresh and pdf.is_file() and not note:
        note = (f"{pdf.name} 在盘上但**不是这一趟写的**（它的修改时间早于这次编译开始）"
                "⇒ 这一次没编出 PDF，别把旧的那一份当成本次读数")
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
    }
    receipt_path = out / RECEIPT_NAME
    try:
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8", newline="\n")
    except OSError as exc:
        problems.append(f"回执没写成：{type(exc).__name__}: {exc}")

    base = {"tex": str(tex), "pdf": str(pdf), "engine": chosen,
            "exit_codes": codes, "runs": len(codes), "pdf_fresh": fresh,
            "receipt_path": str(receipt_path),
            "engine_stderr_tail": stderr_tail, "engine_stdout_tail": stdout_tail,
            "problems": problems}
    if fresh:
        return {"tri": "computed", "ok": True,
                "reason": note or f"由本次源码编出（{chosen}，{pages} 页）",
                "pages": pages, "pdf_bytes": size, **base}
    return {"tri": "unknown", "ok": False,
            "reason": note or "没编出 PDF（引擎没给出任何产物）",
            "pages": None, "pdf_bytes": None, **base}
