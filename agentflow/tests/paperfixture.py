# -*- coding: utf-8 -*-
"""正文编译那一格的共享夹具（`doc.paper_compile` / 收工门 `paper` 那一格 / 各条判据）。

为什么要有它（三条，每条都是本仓栽过的形态）：

1. **判据不该依赖"这台机器恰好在 PATH 上装了 LaTeX"**：要判的是"回执与盘上这份正文
   对不对得上"，不是"TeX 发行版装没装"。所以假引擎（一个写 PDF 的脚本）经
   `papercompile.ENGINE_ENV`（`AGENTFLOW_LATEX_ENGINE`）注入 —— 那条通路本身也是产品的
   一部分（换发行版、换引擎时要它；名字不存在时如实落 `unknown`，见 `compile_paper`）。
2. **只留一份造法**：旧路里 `test_paperbuild` / `test_renderanchor` 与各条收工门判据
   各造一份假论文包 —— 三份口径必然漂（旧路退场时正是这个形态：四个模块一个落点）。
3. 假引擎**只写 `main.pdf`**，绝不碰 `main.tex`：真机血案是"生成器把正文整份重写、
   G 改的那一段被抹掉"（`draft/37` §1.1）。这条纪律写在夹具里，用它的判据自然继承。
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import sys
from collections.abc import Iterator

from agentflow import papercompile as PC

#: 假 PDF 的内容（判据只拿它做"产物在不在 / 字节数多少"两栏；页数那栏由
#: `extract.page_count` 决定，读不出就是 `None` —— 没有判据拿页数当通过）。
FAKE_PDF_LITERAL = "b'\\x25PDF-1.4\\n% fixture\\n\\x25\\x25EOF\\n'"

#: 假引擎的正文（写成 `.cmd` / `.sh`，里面只调 python —— 不让 `%` 之类的
#: 批处理元字符出现在脚本里）。
_FAKE_ENGINE_PY = (
    "import pathlib,sys\n"
    f"pathlib.Path('main.pdf').write_bytes({FAKE_PDF_LITERAL})\n"
    "sys.stdout.write({stdout!r})\n"
    "sys.stderr.write({stderr!r})\n"
    "sys.exit({exit_code})\n"
)


def fake_engine(dirpath: str | pathlib.Path, *, exit_code: int = 0, writes_pdf: bool = True,
                stdout: str = "fake-engine: wrote main.pdf\n",
                stderr: str = "") -> pathlib.Path:
    """造一个假 LaTeX 引擎（可执行脚本），返回它的路径。

    - `exit_code`：引擎的退出码（**非 0 但写出 PDF 是本机 MiKTeX 的真实形态**，
      用它验"产物与退出码两栏不互相冒充"）；
    - `writes_pdf=False`：什么都不产（用它验 `unknown` 与 stderr 尾巴那一栏）。
    """
    d = pathlib.Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    body = _FAKE_ENGINE_PY.format(stdout=stdout, stderr=stderr, exit_code=int(exit_code))
    if not writes_pdf:
        body = body.replace(f"pathlib.Path('main.pdf').write_bytes({FAKE_PDF_LITERAL})\n", "")
    py = d / "_fake_engine_body.py"
    py.write_text(body, encoding="utf-8", newline="\n")
    if os.name == "nt":
        script = d / "fake_latex.cmd"
        script.write_text(f'@echo off\r\n"{sys.executable}" "{py}"\r\n',
                          encoding="ascii", newline="")
    else:
        script = d / "fake_latex.sh"
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}"\n',
                          encoding="utf-8", newline="\n")
        script.chmod(0o755)
    return script


@contextlib.contextmanager
def use_engine(path: str | pathlib.Path) -> Iterator[None]:
    """临时把 `papercompile` 的引擎指到 `path`（退出时原样还回去）。"""
    key = PC.ENGINE_ENV
    old = os.environ.get(key)
    os.environ[key] = str(path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old


#: 一份最小可编的正文字面量（不是 `%` 开头的注释行就够；真引擎与假引擎都吃它）。
MINIMAL_TEX = ("\\documentclass{article}\n"
               "\\begin{document}\n"
               "Theorem 1.5 states that the walk converges.\n"
               "\\end{document}\n")


def write_paper(project_root: str | pathlib.Path, text: str = MINIMAL_TEX) -> pathlib.Path:
    """把正文写到 `<项目根>/out/paper/main.tex`（返回那个路径）。"""
    tex = PC.package_dir(project_root) / PC.TEX_NAME
    tex.parent.mkdir(parents=True, exist_ok=True)
    tex.write_text(text, encoding="utf-8", newline="\n")
    return tex


def compiled_project(project_root: str | pathlib.Path, *, text: str = MINIMAL_TEX,
                     engine: str | pathlib.Path | None = None) -> dict:
    """造一个"正文已写、并已由假引擎编过一遍"的项目根。

    返回 `compile_paper` 的那份读数（判据要什么读什么，不另算一份）。
    """
    root = pathlib.Path(project_root)
    write_paper(root, text)
    script = pathlib.Path(engine) if engine else fake_engine(root / "_engine")
    with use_engine(script):
        return PC.compile_paper(root)
