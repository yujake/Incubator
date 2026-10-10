"""T3 的工作区夹具之二：**真的跑一次 LaTeX**，并把数字照实数记（`code/compile_paper.py`）。

`paperbuild.DEFAULT_COMPILE_SCRIPT` 就是它。放到 `agentflow/demo/paper_from_results/code/`
是为了让它进版本库（`projects/` 是 gitignore 的）。

## 与 T1 那份的两处不同（同一批真机读数，见 `make_paper.py` 的 docstring）

1. **先 `mkdir(parents=True)`**：`out/paper/` 还不存在时，回执那一句也会
   `FileNotFoundError`；
2. **主稿不在时给一句人话、退出码 2**（"没查成"），不编一份空回执。

## 契约（与 T1 夹具逐字相同的那几条）

- 权威产物是 `out/paper/main.tex`（主稿就是论文本体）；
- 回执里的 `pages` / `pdf_bytes` **不参与任何通过判据**（不许拿页数当通过）；
- 真有工具链就真编，编不过就**如实记**退出码与 stderr 摘要，不许写成"编过了"；
- MiKTeX 的用户目录挪进工作区（`MIKTEX_USERDATA` / `MIKTEX_USERCONFIG`），
  否则它收尾时写 `C:\\CTEX\\UserData\\...` 被拒，明明编出了 PDF 却以 `0xC0000409` 退出。

退出码：0 = 拿到 PDF；1 = 没编出 PDF（回执里写明为什么）；2 = 主稿不在盘上（没查成）。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

_miktex_root = pathlib.Path.cwd() / ".miktex"
os.environ.setdefault("MIKTEX_USERDATA", str(_miktex_root / "data"))
os.environ.setdefault("MIKTEX_USERCONFIG", str(_miktex_root / "config"))
os.environ.setdefault("MIKTEX_AUTOINSTALL", "0")

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow import extract as EX  # noqa: E402
from agentflow import renderanchor as RA  # noqa: E402

out = pathlib.Path("out/paper")
tex = out / "main.tex"
pdf = out / "main.pdf"

if not tex.is_file():
    why = "out/paper/main.tex 不在盘上 ⇒ 没有可编的正文（先把正文落到那个落点）"
    print("REPRO_RESULT: " + json.dumps({"ok": False, "pages": None, "reason": why},
                                        ensure_ascii=False))
    print(why, file=sys.stderr)
    sys.exit(2)

out.mkdir(parents=True, exist_ok=True)
engine = shutil.which("pdflatex") or shutil.which("xelatex") or ""
codes: list[int] = []
note = ""
if engine:
    for _ in range(2):
        try:
            got = subprocess.run([engine, "-interaction=nonstopmode", "-halt-on-error",
                                  tex.name],
                                 cwd=str(out), capture_output=True, timeout=600)
            codes.append(int(got.returncode))
        except (OSError, subprocess.SubprocessError) as exc:
            codes.append(-1)
            note = f"{type(exc).__name__}: {exc}"
            break
    if codes and codes[-1] != 0:
        log = out / "main.log"
        tail = ""
        if log.is_file():
            tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:])
        note = note or f"编译失败（exit={codes[-1]}）：{tail[:600]}"
else:
    note = "没找到 LaTeX 引擎（pdflatex/xelatex 都不在 PATH 上）"

pages = EX.page_count(pdf) if pdf.is_file() else None
rec = RA.build_receipt(
    out,
    tex_sha256=RA.file_digest(tex),
    pages=pages,
    markers_missing=[],
    pdf_bytes=pdf.stat().st_size if pdf.is_file() else None,
    compiler_exit_codes=codes,
)
(out / RA.RECEIPT_NAME).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
ok = bool(pages)
print("REPRO_RESULT: " + json.dumps(
    {"ok": ok, "pages": pages, "pdf_bytes": rec.get("pdf_bytes"),
     "engine": engine, "exit_codes": codes,
     "note": note or f"由本轮源码编出（{engine}）"}, ensure_ascii=False))
sys.exit(0 if ok else 1)
