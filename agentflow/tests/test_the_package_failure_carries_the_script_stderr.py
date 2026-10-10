# -*- coding: utf-8 -*-
"""论文包那一步失败时，脚本自己的话必须跟着回来（T3 第 5 趟 `t3e` 的真机读数）。

## 守的是什么

`t3e` 那一趟：`G.paper_package` 在 render 阶段失败，M 看到的只有一句
「脚本没打印 `REPRO_RESULT:` 结论行 ⇒ 结论读不到」，于是它把原因猜成
"本工作区没有 `source/` 基线"（渲染器 docstring 里那句"`out/paper/main.tex` 从
`source/main.tex` 逐字复制"），并据此改了交付形式（从论文包改成研究手稿）。
真原因藏在脚本 stderr 里：`out/paper/` 目录不存在 ⇒ 写锚时 `FileNotFoundError`。
读数当时就在 `paperbuild.build` 的 `steps[0]` 里（`exit_code` / `stderr_tail`），
是 `paper_package` 这一层把它抹掉的。

判据：
* 正控：渲染脚本崩了 ⇒ `render.stderr_tail` 里能看到脚本自己吐的那句话、
  `exit_code` 非 0、`script_path` 指向盘上那个脚本；
* 负控：渲染成功 ⇒ `render` 里没有那几格（不成功时不加、成功时也不许堆装饰）；
* 反真空：三个字段（`exit_code` / `stderr_tail` / `script_path`）都要在 ——
  只报一句 `error` 的那种形态在这条判据下过不去。
"""
from __future__ import annotations

import pathlib

from agentflow.agent_g import AgentG
from agentflow.store import Store

FAILING = """import sys
raise RuntimeError("out/paper 目录不存在：写锚时 FileNotFoundError")
"""

OK_RENDER = """import json
print("REPRO_RESULT: " + json.dumps({"anchor": "written"}))
"""

OK_COMPILE = """import json
print("REPRO_RESULT: " + json.dumps({"ok": True, "pages": 1}))
"""


def _ws(tmp_path: pathlib.Path, *, render: str, compile_: str | None) -> Store:
    # 先 `init()` 再放 `code/`（`Store.init` 对"外来目录"是 fail-closed 的，
    # 与那条"不可逆"的守卫一致 —— 夹具不绕它）。
    store = Store(tmp_path)
    store.init()
    code = tmp_path / "code"
    code.mkdir(parents=True, exist_ok=True)
    (code / "make_paper.py").write_text(render, encoding="utf-8")
    if compile_ is not None:
        (code / "compile_paper.py").write_text(compile_, encoding="utf-8")
    return store


def test_positive_a_crashed_render_brings_the_scripts_own_words_back(tmp_path: pathlib.Path) -> None:
    """正控：渲染脚本崩了 ⇒ 它的 stderr / 退出码 / 脚本路径都跟着回来。"""
    store = _ws(tmp_path, render=FAILING, compile_=OK_COMPILE)
    out = AgentG(store, config={}).paper_package()

    assert out["ok"] is False, out
    render = out["render"]
    assert render["ok"] is False, render
    assert render["exit_code"] not in (0, None), render
    assert "out/paper 目录不存在" in render["stderr_tail"], render
    assert render["script_path"].endswith("make_paper.py"), render
    assert render["script"] == "code/make_paper.py", render
    assert render["repro_found"] is False, render
    # 原来的那一句也要在（"没打印结论行"是事实，脚本的话是原因 —— 两件都要）
    assert "REPRO_RESULT" in render["error"], render


def test_negative_a_successful_render_carries_no_failure_decoration(tmp_path: pathlib.Path) -> None:
    """负控：渲染成功 ⇒ `render` 里不许出现失败才有的那几格。"""
    store = _ws(tmp_path, render=OK_RENDER, compile_=OK_COMPILE)
    out = AgentG(store, config={}).paper_package()

    render = out["render"]
    assert render["ok"] is True, render
    assert set(render) == {"ok", "kind", "error"}, render
