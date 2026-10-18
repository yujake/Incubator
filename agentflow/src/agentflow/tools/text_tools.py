# -*- coding: utf-8 -*-
"""文字层抽取的工具面（`text.extract`）：把盘上已有的 PDF/文本抽成 `out/texts/<名>.txt`。

## 为什么有这一件（2026-10-17 真机读数驱动，`draft/136`）

T5 那趟（`projects/t5pdfs`）**最大的卡点**就是这一格：

- A 侧：`extract.run` → `unknown_tool`（并列候选只有 `ocr.run`）；`ocr.run` → **`role_denied`**
  （"角色 'A' 拿不到工具 'ocr.run'"）；
- B 侧：`fs.read(library/*.pdf)` → `binary`（"需要它的内容请走抽取链（extract/OCR）"）；
  B 能调 `ocr.run` 但 `any_ocr_backend_available=false`（easyocr 的 torch/numpy ABI 断裂、
  tesseract 不在 PATH）。

⇒ **"把 PDF 变成正文"没有任何角色的可达能力**，最后是 **M 自己写脚本 ＋ 派 E 跑**才解开
（`out/texts/extract_pdfs.py`）—— 也就是说：**知识的入口靠主控越权动手**，这与
"M 只派活、不指定能力"的口径直接冲突。

⇒ 这一件把它接成 **A/B 可达的能力**。要点：**四份 PDF 全都 `has_text_layer=true`** ——
缺的从来不是 OCR，而是**抽取链本身**；扫描件才需要 `ocr.run`（分工见两边说明）。

## 与 `ocr.run` 的分工（别混）

| 工具 | 用什么 | 什么时候 |
|---|---|---|
| `text.extract`（本模块） | PDF **自带的文字层**（`extract.extract_text`） | 电子排版 PDF（绝大多数）—— **不联网、不需要后端** |
| `ocr.run`（`ocr_tools`） | 真 OCR 后端（easyocr/pytesseract） | **扫描件/图片**：没有文字层，只能识别 |
"""
from __future__ import annotations

import hashlib
import re
import json
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..extract import extract_text
from ..store import Store
from . import ToolResult, ToolSpec, fail, ok, tool
# 复用 OCR 那件**第一猜**归一器（`path` 或**文献编号**都收，三态齐全）
from .ocr_tools import _Ctx as _OcrCtx, _pick_workspace, _target_path

PAGE_MARKER = "===== page {n} ====="
DEFAULT_OUT_DIR = ""          # 空 = 落在 library/（"入库"）


def _safe_stem(raw: str, fallback: str = "text") -> str:
    """把 `lit_id`/文件名净化成**能当文件名**的形态。

    ⚠️ **2026-10-17 真机读数驱动（T5 第 2 趟）**：A 传的是 `lit_id="lit:000000"`，
    而原实现写 `f"{lit_id}.txt"` ⇒ 文件名里带**冒号** ⇒ 在 Windows 上
    `lit:000000.txt` 被解释成 **NTFS 备用数据流**，结果盘上留下一个 **0 字节的 `library/lit`**
    （一个看不出所以然的幽灵文件）。这里统一：取冒号后的**裸编号**、再把
    Windows 非法字符替换成 `_`；空则用 fallback。
    """
    body = str(raw or "").strip()
    if body:
        body = body.split(":")[-1].strip() or body
    body = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", body).strip(" .")
    return body or fallback


@dataclass
class _Ctx:
    workspace: Path
    store: Store | None = None
    actor: str = "agent-A"


def _pages_of(doc: Any) -> list[Any]:
    """从 `extract_text` 的返回里取"逐页文本"（对方是 dataclass 还是 mapping 都收）。"""
    for attr in ("pages", "texts", "per_page"):
        val = getattr(doc, attr, None)
        if val is None and isinstance(doc, Mapping):
            val = doc.get(attr)
        if val:
            return list(val)
    return []


def _text_of(doc: Any) -> str:
    for attr in ("text", "full_text", "raw"):
        val = getattr(doc, attr, None)
        if val is None and isinstance(doc, Mapping):
            val = doc.get(attr)
        if isinstance(val, str) and val.strip():
            return val
    if isinstance(doc, str):
        return doc
    return ""


def _h_extract(ctx: _Ctx, path: str = "", lit_id: str = "", out_dir: str = "",
               pages: Sequence[int] | None = None, max_pages: int = 200) -> ToolResult:
    """``text.extract`` 的工具体：抽取 → 写 `out/texts/<名>.txt`。"""
    rel, bad = _target_path(_OcrCtx(workspace=ctx.workspace, store=ctx.store), path, lit_id)
    if bad is not None:
        return fail(str(bad.get("error") or "没有可抽的目标"),
                    **{k: v for k, v in bad.items() if k != "error"})
    p = Path(rel)
    if not p.is_absolute():
        cand = ctx.workspace / p
        p = cand if cand.exists() else p
    if not p.exists():
        return fail(f"文件不存在：{p}", kind="file_missing", path=str(p))
    if not p.is_file():
        return fail(f"不是普通文件：{p}", kind="not_a_file", path=str(p))

    # ⚠️ 2026-10-17：**纯文本文件直接当正文**（幂等）—— 对 `.txt` 来说"抽成纯文本"就是它自己；
    # 这也让声明判据的探针（夹具给的是一份 `.txt`）真跑得成，而不是靠"键名读自源码"打补丁。
    if p.suffix.casefold() in (".txt", ".md", ".text", ".rst"):
        try:
            plain = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return fail(f"读不了这份纯文本（{type(exc).__name__}）：{p}",
                        kind="extract_error", path=str(p))
        garbled0, q0 = _quality(plain)
        if garbled0:
            return fail("这一份本身就是乱码（NUL/替换字符/控制字符超标）⇒ 不写盘",
                        kind="garbled_text", path=str(p), lit_id=str(lit_id or ""), quality=q0)
        target_dir0 = (ctx.workspace / out_dir) if out_dir else (ctx.workspace / "library")
        target_dir0.mkdir(parents=True, exist_ok=True)
        name0 = f"{_safe_stem(lit_id, p.stem)}.txt"
        out0 = target_dir0 / name0
        out0.write_text(plain, encoding="utf-8")
        return ok({
            "path": str(out0.relative_to(ctx.workspace)).replace("\\", "/"),
            "abs_path": str(out0),
            "lit_id": str(lit_id or ""),
            "pages": 1,
            "chars": len(plain),
            "sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest(),
            "quality": q0,
            "max_pages": int(max_pages or 0),
            "truncated": False,
            "note": "本来就是纯文本 ⇒ 原样入库（幂等）",
        })

    try:
        doc = extract_text(p)
    except Exception as exc:                     # noqa: BLE001 - 缺依赖/损坏/权限
        return fail(f"抽取失败（extract_text 抛 {type(exc).__name__}）：{exc}",
                    kind="extract_error", path=str(p))

    per_page = _pages_of(doc)
    want = [int(x) for x in (pages or []) if isinstance(x, int) or str(x).isdigit()]
    if want:
        per_page = [t for i, t in enumerate(per_page, 1) if i in want]
    truncated = False
    if max_pages and len(per_page) > int(max_pages):
        per_page = per_page[: int(max_pages)]
        truncated = True

    body = _text_of(doc)
    if per_page:
        blocks = []
        for i, t in enumerate(per_page, 1):
            blocks.append(PAGE_MARKER.format(n=i))
            blocks.append(str(t or "").rstrip("\n"))
        body = "\n".join(blocks).strip("\n") + "\n"
    if not body.strip():
        return fail(
            "这一份**抽不出文字**（没有文本层）⇒ 不是「文件读不了」，是「它要 OCR」："
            "用 `ocr.detect_text_layer` 确认，再按扫描件走 `ocr.run`（本机无 OCR 后端时会如实说）",
            kind="no_text_layer", path=str(p), lit_id=str(lit_id or ""))

    # 口径：**转成纯文字稿入库** ⇒ 直接落在 `library/` 里（与那份 PDF 同处一层），
    # 下游角色 `fs.read library/<名>.txt` 就能读 —— 不必再碰 PDF（PDF 是二进制，读不了）。
    garbled, q = _quality(body)
    if garbled:
        return fail(
            "这一份转出来的文本**疑似乱码**（NUL/替换字符/控制字符占比超标）⇒ "
            "**不写盘**：往 library/ 里放一份乱码比不放更坏（下游会把它当正文读）。"
            "出路：换一份有文字层的原件、或按扫描件走 `ocr.run`；"
            "也可以先 `ocr.detect_text_layer` 看它到底有没有文字层。",
            kind="garbled_text", path=str(p), lit_id=str(lit_id or ""), quality=q)

    target_dir = (ctx.workspace / out_dir) if out_dir else (ctx.workspace / "library")
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{_safe_stem(lit_id, p.stem)}.txt"
    out_path = target_dir / name
    out_path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return ok({
        "path": str(out_path.relative_to(ctx.workspace)).replace("\\", "/"),
        "abs_path": str(out_path),
        "lit_id": str(lit_id or ""),
        "pages": len(per_page),
        "chars": len(body),
        "sha256": digest,
        "quality": q,
        "max_pages": int(max_pages or 0),
        "truncated": truncated,
        "note": ("纯文字稿已入库（与 PDF 同层）；页间插了 `===== page N =====`；`sha256` 是这次写下的**正文**的指纹"
                 "（下游可拿它核「读到的是不是同一份」）"),
    })



#: 判定"疑似乱码"的阈值（业主 2026-10-17 口径：**A 要保证转出来的纯文字稿不是乱码**）。
#: 三条独立信号，**任何一条**命中就拒（宁可说"这份转不出干净文本"，也不把乱码写进 library/）：
#:   · NUL 字节：PDF 文字层正常**不含** NUL；出现即错位解码；
#:   · 替换字符 U+FFFD：解码器自己都认不出那个字节 ⇒ 乱码；
#:   · 控制字符占比：正常正文里控制字符几乎为 0（换行/制表除外）。
GARBLED_REPLACEMENT_MAX = 0
GARBLED_CONTROL_RATIO_MAX = 0.02


def _quality(text: str) -> tuple[bool, dict[str, Any]]:
    """核一遍"这段文本能不能读"。返回 `(是否疑似乱码, 读数)`。"""
    body = str(text or "")
    total = max(1, len(body))
    nuls = body.count("\x00")
    replacement = body.count("\ufffd")
    control = sum(1 for ch in body
                  if ord(ch) < 32 and ch not in ("\n", "\r", "\t"))
    ratio = control / total
    garbled = (nuls > 0 or replacement > GARBLED_REPLACEMENT_MAX
               or ratio > GARBLED_CONTROL_RATIO_MAX)
    return garbled, {
        "chars": len(body),
        "nul_bytes": nuls,
        "replacement_chars": replacement,
        "control_chars": control,
        "control_ratio": round(ratio, 5),
    }

@tool(
    "text.extract",
    "**把一篇 PDF 转成纯文字稿**（A 的活；**原 PDF 原样保留**，只多出一份 `.txt`，不删不改原件）：读它**自带的文字层**，页间插 `===== page N =====`，"
    "写成同名的 `.txt` 放进 `library/`（**入库**；写盘前先核一遍质量，疑似乱码就不写、如实拒）—— 其它角色消费这篇文献时**直接读那份纯文字稿**，"
    "不要再去读 PDF（二进制，`fs.read` 会拒收）。**不需要 OCR 后端、不联网**。"
    "**读的是 PDF 自带的文字层**：不需要 OCR 后端、不联网 —— 扫描件才走 OCR。"
    "也可以直接给**已登记的文献编号**，不必自己拼路径。",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "maxLength": 1000},
            "lit_id": {"type": "string", "maxLength": 40},
            "out_dir": {"type": "string", "maxLength": 200},
            "pages": {"type": "array", "items": {"type": "integer", "minimum": 1}, "maxItems": 500},
            "max_pages": {"type": "integer", "minimum": 1, "maximum": 2000},
        },
        "required": [],
        "additionalProperties": False,
    },
    side_effect="write_local",
    # 业主口径（2026-10-17）：**A 负责**搜索/下载/**转成纯文字稿入库**；
    # 其它智能体消费这些文献时**直接读纯文字稿** ⇒ 这一件只给 A。
    roles=("A",),
    returns=(
        "{'path','abs_path','lit_id','pages','chars','sha256','quality','max_pages',"
        "'truncated','note'}；"
        "quality 是 {'chars','nul_bytes','replacement_chars','control_chars','control_ratio'}；"
        "失败：ok=False + kind(no_target/unknown_lit_id/lit_without_path/file_missing/not_a_file/"
        "extract_error/no_text_layer/garbled_text)"
    ),
    tags=("text", "extract", "offline"),
)
def _text_extract(ctx, path="", lit_id="", out_dir="", pages=None, max_pages=200):
    """`text.extract` 的工具体（注入值由装配期用 `partial` 绑定）。"""
    return _h_extract(ctx, path=path, lit_id=lit_id, out_dir=out_dir,
                      pages=pages, max_pages=max_pages)


_TOOL_FUNCTIONS: tuple[tuple[Callable[..., Any], tuple[str, ...]], ...] = (
    (_text_extract, ('ctx',)),
)


def register(
    registry: Any,
    *,
    store: Store | None = None,
    workspace: str | Path | None = None,
    workspace_root: str | Path | None = None,
    root: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    actor: str = "agent-A",
) -> list[ToolSpec]:
    """把文字层抽取注册进 ``registry``，返回注册的 ``ToolSpec`` 列表。

    `store` 只用来解析路径与把**文献编号**换成那一份全文（抽取本身不读也不写任何表）；
    `workspace` 的别名 `workspace_root` / `root` 也接受（装配器用这两个名字注入）。
    """
    ws = _pick_workspace(workspace, workspace_root, root, store)
    ctx = _Ctx(workspace=ws.resolve(), store=store, actor=actor)
    bound: dict[str, Any] = {"ctx": ctx}
    specs: list[ToolSpec] = []
    for fn, deps in _TOOL_FUNCTIONS:
        specs.append(replace(fn.__tool_spec__, handler=partial(fn, *[bound[k] for k in deps])))
    registry.register_all(specs)
    return specs


ALL_TOOLS = _TOOL_FUNCTIONS
