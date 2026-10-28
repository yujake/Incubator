# -*- coding: utf-8 -*-
"""判据：坏回复的落盘文件名必须带角色（否则两个角色同一步号会互相覆盖）。

## 真机（2026-10-28，`projects/paper-rewrite-78c`）

14 个坏步、13 个文件名（全仓一个 sid `20261028`，而 `out/invalid/<sid>-step<N>.txt`
只带步号、不带角色）：

```
B 与 V 都在第 7 步坏过      → 20261028-step7.txt 只能留一份
D 与 B 都在第 9 步坏过      → 20261028-step9.txt 只能留一份
```

这次的 13 份恰好没撞（各角色步号错开了），但那是运气：一旦撞上，事后要归因只能靠事件里
被 `_clip(..., 600)` 剪过的前 200 字猜 —— 而这正是 D40 落盘要治的那个形态。
"""
from __future__ import annotations

import pathlib

from agentflow.agent_loop import _dump_invalid_reply


def _root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True)
    return root


def test_two_roles_failing_the_same_step_keep_two_files(tmp_path: pathlib.Path):
    """正题：同一 sid、同一个步号、两个角色 ⇒ 两份文件，后写的不覆盖前一份。"""
    root = _root(tmp_path)
    a = _dump_invalid_reply(root, "20261028", 7, "B 的坏回复", "B")
    b = _dump_invalid_reply(root, "20261028", 7, "V 的坏回复", "V")
    assert a and b and a != b, (a, b)
    assert (root / a).read_text(encoding="utf-8") == "B 的坏回复"
    assert (root / b).read_text(encoding="utf-8") == "V 的坏回复"


def test_the_filename_says_which_role_and_which_step(tmp_path: pathlib.Path):
    """文件名要能直接读出角色与步号（事后归因不再靠猜）。"""
    root = _root(tmp_path)
    rel = _dump_invalid_reply(root, "20261028", 41, "{}", "F")
    name = pathlib.Path(rel).name
    assert "F" in name and "step41" in name, name
    assert name.startswith("20261028-"), name


def test_the_role_is_sanitized_and_empty_is_allowed(tmp_path: pathlib.Path):
    """角色名要过文件名清洗；没给角色时仍落得下（老调用方不炸）。"""
    root = _root(tmp_path)
    rel = _dump_invalid_reply(root, "s", 3, "x", "a/b")
    assert "/" not in pathlib.Path(rel).name, rel
    plain = _dump_invalid_reply(root, "s", 4, "y")
    assert (root / plain).read_text(encoding="utf-8") == "y"
