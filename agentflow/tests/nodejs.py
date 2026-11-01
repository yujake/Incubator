# -*- coding: utf-8 -*-
"""`node` + `ui/node_modules/typescript` 的共用帮手（唯一一份）。

## 为什么有它

判据里「把前端那个纯函数 / 那一列 render 真跑一遍」这件事现在有五处（三态读数、根叫 M、
名册树画哪些行、pid 那一列，加上它们的负控）。每处各写一份
`shutil.which("node")` + `transpileModule` + `subprocess.run` 的话，口径会漂：
skip 的条件、transpile 的编译选项、以及下面那条编码坑，任何一处漏掉都会让同一种机器上
红得与被测代码无关。这一份把它们收成一处；改口径只改这里。

## 三档口径（与 `tests/test_webui_three_state_reading.py` 等三份判据的既有口径逐字一致）

1. 没装 node ⇒ `skip`，reason 写明「记 unknown（不记 pass）」；
2. 前端依赖没装（`ui/node_modules/typescript` 不在）⇒ `skip`，reason 同上；
3. 转译 / 跑不起来 ⇒ 断言红（那是判据自己的装置坏了，不是环境）。

`skip` 也是一条读数：pytest 的汇总行把它记成 `skipped`（`-rs` 还带 reason），
所以「没查成」不会被读成「通过了」。

## `encoding="utf-8"` 不是装饰

node 按 UTF-8 往 stdout 写，而 `subprocess.run(..., text=True)` 不给编码时 Python 用本机
locale（中文 Windows = GBK）去解它 ⇒ 读线程抛 `UnicodeDecodeError`、`proc.stdout` 变成
空串，于是整个文件在那种机器上红得与被测代码毫无关系。三份旧判据各自踩过这一格，
收在这里之后只需要记住一次。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from typing import Any

import pytest

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
#: 前端骨架根（`ui/`）。
UI = REPO / "ui"
#: 前端依赖里那一份 TypeScript（判据用它把 .ts/.tsx 即时转成 ESM）。
TYPESCRIPT_LIB = UI / "node_modules" / "typescript" / "lib" / "typescript.js"

#: 环境缺一档的两句 reason（写清「记 unknown（不记 pass）」，汇总行里读得出来）。
SKIP_NO_NODE = "没装 node ⇒ 前端渲染函数这一层记 unknown（不记 pass）"
SKIP_NO_TYPESCRIPT = "前端依赖没装（ui/node_modules/typescript 不在）⇒ 记 unknown（不记 pass）"


#: 用 `ts.transpileModule` 把一份 .ts/.tsx 转成 ESM。
#:
#: `node -e "<本段>" lib src dst [jsxFactory]`：`-e` 下 `process.argv` 是
#: `[node, lib, src, dst, factory]`（argv[1] 起就是参数），所以下面从 `[1]` 取。
_TRANSPILE_JS = r"""
const ts = require(process.argv[1]);
const fs = require("node:fs");
const path = require("node:path");
const src = fs.readFileSync(process.argv[2], "utf8");
const factory = process.argv[4] || "";
const options = {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.ESNext,
  isolatedModules: true,
};
if (factory !== "") {
  // JSX 转成 `h(...)` 调用：判据自己注入一个 h（不引 preact、不碰 DOM）。
  options.jsx = ts.JsxEmit.React;
  options.jsxFactory = factory;
  options.jsxFragmentFactory = "Fragment";
}
const out = ts.transpileModule(src, {
  compilerOptions: options,
  fileName: path.basename(process.argv[2]),
}).outputText;
fs.writeFileSync(process.argv[3], out, "utf8");
"""


def node_exe() -> str:
    """`node` 的可执行路径；没装就 skip（reason 见 :data:`SKIP_NO_NODE`）。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip(SKIP_NO_NODE)
    return node


def typescript_lib() -> pathlib.Path:
    """`ui/node_modules/typescript` 那一份；没装就 skip（reason 见 :data:`SKIP_NO_TYPESCRIPT`）。"""
    if not TYPESCRIPT_LIB.is_file():
        pytest.skip(SKIP_NO_TYPESCRIPT)
    return TYPESCRIPT_LIB


def transpile(source: pathlib.Path, dest: pathlib.Path, *,
              jsx_factory: str = "") -> pathlib.Path:
    """把 `source`（.ts/.tsx）转成 ESM 写到 `dest`；返回 `dest`。

    `jsx_factory` 非空时把 JSX 转成 `<jsx_factory>(...)` 调用（例如 `"h"`）：转出来的
    模块自己 import 一个 `h` 就能在 node 里跑，不需要 preact / DOM。
    """
    node = node_exe()
    lib = typescript_lib()
    proc = subprocess.run([node, "-e", _TRANSPILE_JS, str(lib), str(source), str(dest),
                           jsx_factory],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        f"把 {source.name} 转成 ESM 失败（exit {proc.returncode}）："
        f"{((proc.stderr or '') + (proc.stdout or ''))[:800]}")
    return dest


def run_json(script: pathlib.Path, *args: str, what: str,
             timeout: float = 180.0) -> Any:
    """跑一个判据自带的 `.mjs` 转轮（它往 stdout 打一份 JSON），返回解析后的对象。

    `what` 是失败信息的前缀（说清"哪一步没跑起来"）；转轮非零退出 ⇒ 断言红 ——
    那是装置坏了，不是被跳过。
    """
    node = node_exe()
    proc = subprocess.run([node, str(script), *args],
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    assert proc.returncode == 0, (
        f"{what}（exit {proc.returncode}）："
        f"{((proc.stderr or '') + (proc.stdout or ''))[:1200]}")
    return json.loads(proc.stdout)


def write_module(path: pathlib.Path, text: str) -> pathlib.Path:
    """把一个临时 `.mjs` / `.tsx` 写进判据自己的临时目录（顺手返回路径）。"""
    path.write_text(text, encoding="utf-8")
    return path
