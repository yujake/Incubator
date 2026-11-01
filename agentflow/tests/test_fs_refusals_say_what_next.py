# -*- coding: utf-8 -*-
"""fs 的拒信必须给一条真的走得通的下一步（不是「先读一次」这种对不存在文件的空话）。

业主 2026-11-02 的硬要求：每条建议都要能回答「照着它做，真的能走通吗」。
这一份对六处逐条做两件事：① 断言拒信里有 `建议：` 与它点名的真工具/字段；
② 真的照那句做一步，断言它到达了下一步（成功或另一条受控拒绝）。

零模型调用；tmp 工作区。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow.conductor import calling_as          # noqa: E402
from agentflow.store import Store                   # noqa: E402
from agentflow.tools import build_registry          # noqa: E402


def _ws(path: pathlib.Path):
    root = path / "ws"
    store = Store(root)
    store.init()
    reg = build_registry(store=store, workspace_root=root).registry
    return root, reg


def _call(reg, tool: str, **params):
    with calling_as("t-probe", "G"):
        return reg.call(tool, role="G", **params)


def _advice(res) -> str:
    """拒信里 `建议：` 之后那一句（断言它是非空的、而不是只写了个词头）。"""
    text = str(getattr(res, "error", "") or "")
    assert "建议：" in text, f"拒信没有「建议：」：{text}"
    tail = text.split("建议：", 1)[1].strip()
    assert tail, f"「建议：」后面是空的：{text}"
    return tail


# ---------------------------------------------------------------- 1. sha 不符

def test_sha_mismatch_says_reread_and_the_new_sha_works(tmp_path: pathlib.Path) -> None:
    root, reg = _ws(tmp_path)
    assert _call(reg, "fs.write", path="notes/a.txt", content="第一版\n").ok is True
    read = _call(reg, "fs.read", path="notes/a.txt")
    real = str(read.meta.get("sha256") or "")
    assert real, "fs.read 没给 meta.sha256 —— 建议里点名的那一格不存在"

    bad = _call(reg, "fs.edit", path="notes/a.txt", old_string="第一版",
                new_string="第二版", sha256="0" * 64)
    assert bad.ok is False and bad.meta.get("kind") == "sha_mismatch", bad.to_dict()
    advice = _advice(bad)
    assert "fs.read" in advice and "meta.sha256" in advice, advice

    good = _call(reg, "fs.edit", path="notes/a.txt", old_string="第一版",
                 new_string="第二版", sha256=real)
    assert good.ok is True, good.to_dict()
    assert (root / "notes/a.txt").read_text(encoding="utf-8") == "第二版\n"


# ---------------------------------------------------------------- 2. old_string 找不到

def test_missing_old_string_says_read_first_and_the_exact_copy_works(
        tmp_path: pathlib.Path) -> None:
    root, reg = _ws(tmp_path)
    assert _call(reg, "fs.write", path="notes/b.txt", content="第一版\n").ok is True
    assert _call(reg, "fs.read", path="notes/b.txt").ok is True

    bad = _call(reg, "fs.edit", path="notes/b.txt", old_string="不存在的串", new_string="x")
    assert bad.ok is False and bad.meta.get("kind") == "not_found_old_string", bad.to_dict()
    advice = _advice(bad)
    assert "fs.read" in advice and "fs.write" in advice, advice

    good = _call(reg, "fs.edit", path="notes/b.txt", old_string="第一版", new_string="第二版")
    assert good.ok is True, good.to_dict()


# ---------------------------------------------------------------- 3. 不是干净 UTF-8

def test_not_utf8_says_read_the_encoding_and_rewrite_works(tmp_path: pathlib.Path) -> None:
    root, reg = _ws(tmp_path)
    (root / "notes").mkdir()
    (root / "notes/bad.txt").write_bytes(b"\xff\xff\xff\xff")
    read = _call(reg, "fs.read", path="notes/bad.txt")
    assert read.ok is True and read.meta.get("had_errors") is True, read.to_dict()

    bad = _call(reg, "fs.edit", path="notes/bad.txt", old_string="x", new_string="y")
    assert bad.ok is False and bad.meta.get("kind") == "not_utf8", bad.to_dict()
    advice = _advice(bad)
    assert "fs.read" in advice and "fs.write" in advice, advice

    good = _call(reg, "fs.write", path="notes/bad.txt", content="干净正文\n", overwrite=True)
    assert good.ok is True, good.to_dict()
    assert _call(reg, "fs.read", path="notes/bad.txt").data == "干净正文\n"


# ---------------------------------------------------------------- 4. 改一个不存在的文件

def test_editing_a_missing_file_says_create_it_with_fs_write(tmp_path: pathlib.Path) -> None:
    root, reg = _ws(tmp_path)

    bad = _call(reg, "fs.edit", path="notes/missing.txt", old_string="x", new_string="y")
    assert bad.ok is False and bad.meta.get("kind") == "not_found", bad.to_dict()
    advice = _advice(bad)
    assert "fs.list" in advice and "fs.write" in advice, advice
    # 反真空：对不存在的文件说「先读一次」是一条走不通的话（读它只会再撞「不存在」）。
    assert "先读一次" not in str(bad.error or ""), bad.error

    created = _call(reg, "fs.write", path="notes/missing.txt", content="新建\n")
    assert created.ok is True, created.to_dict()
    assert _call(reg, "fs.read", path="notes/missing.txt").ok is True
    good = _call(reg, "fs.edit", path="notes/missing.txt", old_string="新建", new_string="改好")
    assert good.ok is True, good.to_dict()


# ---------------------------------------------------------------- 5. 把目录当文件写

def test_writing_to_a_directory_says_use_a_filename(tmp_path: pathlib.Path) -> None:
    root, reg = _ws(tmp_path)
    (root / "notes" / "d").mkdir(parents=True)

    bad = _call(reg, "fs.write", path="notes/d", content="x")
    assert bad.ok is False and bad.meta.get("kind") == "path_denied", bad.to_dict()
    advice = _advice(bad)
    assert "fs.write" in advice and "fs.list" in advice, advice

    good = _call(reg, "fs.write", path="notes/d/f.txt", content="x")
    assert good.ok is True, good.to_dict()


# ---------------------------------------------------------------- 6. 读一个不存在的文件

def test_reading_a_missing_file_says_list_or_write(tmp_path: pathlib.Path) -> None:
    root, reg = _ws(tmp_path)

    bad = _call(reg, "fs.read", path="notes/nope.txt")
    assert bad.ok is False and bad.meta.get("kind") == "path_denied", bad.to_dict()
    advice = _advice(bad)
    assert "fs.list" in advice and "fs.write" in advice, advice

    created = _call(reg, "fs.write", path="notes/nope.txt", content="有内容\n")
    assert created.ok is True, created.to_dict()
    assert _call(reg, "fs.read", path="notes/nope.txt").data == "有内容\n"
