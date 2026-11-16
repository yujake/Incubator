# -*- coding: utf-8 -*-
"""文字层抽取的工具面（`text.extract`）：把盘上已有的 PDF/文本抽成 `out/texts/<名>.txt`。

## 为什么有这一件（2026-10-17 真机读数驱动，`draft/136`）
T5 那趟（`projects/t5pdfs`）的卡点是「"把 PDF 变成正文"没有任何角色的可达能力」：A 侧
`extract.run` 不在面上、`ocr.run` 被 `role_denied`，B 侧 `fs.read(library/*.pdf)` 只回
`binary` 且 OCR 后端不可用（easyocr 的 torch/numpy ABI 断裂、tesseract 不在 PATH）。
最后靠「M 自己写脚本 ＋ 派 E 跑」才解开 —— 「知识的入口靠主控越权动手」，与"M 只派活、
不指定能力"的口径冲突。这一件把它接成「A/B 可达的能力」：那四份 PDF 全都
`has_text_layer=true`，缺的从来不是 OCR，而是「抽取链本身」。

## 与 `ocr.run` 的分工（别混）
| 工具 | 用什么 | 什么时候 |
|---|---|---|
| `text.extract`（本模块） | PDF 自带的文字层（`extract.extract_text`） | 电子排版 PDF（绝大多数）—— 不联网、不需要后端 |
| `ocr.run`（`ocr_tools`） | 真 OCR 后端（easyocr / pytesseract） | 扫描件/图片：没有文字层，只能识别 |
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
from .. import litread as _LR
from ..store import Store
from . import ToolResult, ToolSpec, fail, ok, tool
# 复用 OCR 那件「第一猜」归一器（`path` 或「文献编号」都收，三态齐全）
from .ocr_tools import _Ctx as _OcrCtx, _pick_workspace, _target_path

PAGE_MARKER = "===== page {n} ====="
DEFAULT_OUT_DIR = ""          # 空 = 落在 library/（"入库"）


def _safe_stem(raw: str, fallback: str = "text") -> str:
    """把 `lit_id`/文件名净化成「能当文件名」的形态。

    T5 第 2 趟的真机读数：A 传 `lit_id="lit:000000"`，而原实现写 `f"{lit_id}.txt"` ——
    冒号让 Windows 把 `lit:000000.txt` 当成 NTFS 备用数据流，盘上留下一个 0 字节的幽灵
    文件 `library/lit`。这里统一：取冒号后的裸编号、把 Windows 非法字符换成 `_`，空则用
    fallback。
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


def _mark_literature_tier(ctx: _Ctx, lit_id: str, tier: str, *, note: str = "") -> str:
    """把这一档写进 `literature` 行的 `download.fulltext`（给了 `lit_id` 才有落点）。

    为什么要这一步（业主 2026-11-16 裁定 16：抽过但失败要有落点）：AH6 实测里
    `text.extract` 对两份 PDF 都判了 `garbled_text`，但那句话只活在一次工具返回里 ——
    盘上的行仍写着 `status=ok`，随后被洗成 `download.error=""`。于是"抽过但失败"在
    文献库里没有任何痕迹，B 下一轮还会再抽一遍、再烧一次调用。

    写点只有 `litread.with_fulltext`（与 B 那一侧同一处）：三档之外新增的第四档
    `extract_failed` 由它落盘，别处不许自己 `dl["fulltext"] = ...`。
    三态：没有 store / 没给 lit_id / 行上找不到 ⇒ 不写（如实说"没落点"），不是写一个猜的档。
    """
    lid = str(lit_id or "").split(":")[-1].strip()
    if ctx.store is None or not lid:
        return ""
    from .. import litread as _LR

    try:
        with ctx.store.tx("literature", actor=ctx.actor,
                          note=f"text.extract.{tier}") as tx:
            row = tx.find("literature", lit_id=lid)
            if row is None:
                return ""
            payload = dict(row)
            payload["download"] = _LR.with_fulltext(
                dict(payload.get("download") or {}), tier)
            if note:
                payload["download"] = {**payload["download"], "note": note}
            tx.upsert("literature", payload, note=f"text.extract.{tier}")
        return lid
    except Exception:  # noqa: BLE001 - 落点失败不许把抽取结论带坏（读数仍返回给调用方）
        return ""


def _extract_impl(ctx: _Ctx, path: str = "", lit_id: str = "", out_dir: str = "",
                  pages: Sequence[int] | None = None, max_pages: int = 200,
                  name_hint: str = "") -> ToolResult:
    """``text.extract`` 的实现主体：抽取 → 写 `out/texts`（或 `out_dir`）下的 `.txt`。

    这一层不认识"候选槽位"：`lit_id` 只当 literature 行的编号用（`cand:` 前缀由
    :func:`_h_extract` 剥掉，理由见那里）。拆开是为了让"候选期抽读"的记账只写在
    包装层一处 —— 抽读回执的写点不许散进每一条 return 分支。

    `name_hint` 只影响写下的 `.txt` 的文件名：候选期两篇下载件同名时，若都按源文件名
    落盘会互相覆盖，而那会把"两条候选"变成"同一份正文"（`check_read` 的版本核对
    只能看见"后来那一份"，前一条会落 `text_changed`）。候选期传槽位号即可。
    """
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

    # 2026-10-17：「纯文本文件直接当正文」（幂等）—— 对 `.txt` 来说"抽成纯文本"就是它自己；
    # 这也让声明判据的探针（夹具给的是一份 `.txt`）真跑得成，而不是靠"键名读自源码"打补丁。
    if p.suffix.casefold() in (".txt", ".md", ".text", ".rst"):
        try:
            plain = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return fail(f"读不了这份纯文本（{type(exc).__name__}）：{p}",
                        kind="extract_error", path=str(p))
        garbled0, q0 = _quality(plain)
        if garbled0:
            landed = _mark_literature_tier(ctx, lit_id, "extract_failed",
                                           note="text.extract: 这一份本身就是乱码")
            return fail("这一份本身就是乱码（NUL/替换字符/控制字符超标）⇒ 不写盘"
                        + (f"；可读性已记成 `extract_failed`（lit:{landed}）" if landed else ""),
                        kind="garbled_text", path=str(p), lit_id=str(lit_id or ""),
                        quality=q0, availability="extract_failed", landed_on=landed or None)
        target_dir0 = (ctx.workspace / out_dir) if out_dir else (ctx.workspace / "library")
        target_dir0.mkdir(parents=True, exist_ok=True)
        name0 = f"{_safe_stem(name_hint or lit_id, p.stem)}.txt"
        out0 = target_dir0 / name0
        out0.write_text(plain, encoding="utf-8")
        _mark_literature_tier(ctx, lit_id, "ok", note="text.extract: 纯文本原样入库")
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
        landed = _mark_literature_tier(ctx, lit_id, "extract_failed",
                                       note="text.extract: 有字节但没有文本层")
        return fail(
            "这一份**抽不出文字**（没有文本层）⇒ 不是「文件读不了」，是「它要 OCR」："
            "先确认它是不是扫描件（你面上有 OCR 工具就用它；没有就把这一份交 B 转文本 —— 本机无 OCR 后端时那一侧也会如实说）"
            + (f"；可读性已记成 `extract_failed`（lit:{landed}），B 不会再来空抽一次" if landed else ""),
            kind="no_text_layer", path=str(p), lit_id=str(lit_id or ""),
            availability="extract_failed", landed_on=landed or None)

    # 口径「转成纯文字稿入库」⇒ 直接落在 `library/`（与那份 PDF 同层）：下游 `fs.read
    # library/<名>.txt` 就能读，不必再碰二进制的 PDF。
    garbled, q = _quality(body)
    if garbled:
        landed = _mark_literature_tier(ctx, lit_id, "extract_failed",
                                       note=f"text.extract: 乱码（{q}）")
        return fail(
            "这一份转出来的文本**疑似乱码**（NUL/替换字符/控制字符占比超标）⇒ "
            "**不写盘**：往 library/ 里放一份乱码比不放更坏（下游会把它当正文读）。"
            "出路：换一份有文字层的原件，或按扫描件走 OCR（你面上有 OCR 工具就用它；没有就交 B 转文本）。",
            kind="garbled_text", path=str(p), lit_id=str(lit_id or ""), quality=q,
            availability="extract_failed", landed_on=landed or None)

    target_dir = (ctx.workspace / out_dir) if out_dir else (ctx.workspace / "library")
    target_dir.mkdir(parents=True, exist_ok=True)
    name = f"{_safe_stem(name_hint or lit_id, p.stem)}.txt"
    out_path = target_dir / name
    out_path.write_text(body, encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    _mark_literature_tier(ctx, lit_id, "ok", note="text.extract: 抽出的文本可读")
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



#: 候选期抽读的编号前缀：`cand:000012` / `slot:000012` / `candidate:000012`。
#:
#: ## 为什么用前缀，而不是给 `text.extract` 加一个 `slot` 参数
#:
#: `text.extract` 的参数面是冻结面（`tests/golden/tool_surface_snapshot.json`，FC-27）：
#: 加一格参数要人重冻快照。而"这一条候选"的绑定本来就可以由调用方说出来 ——
#: `lit_id` 这一格收的就是"给哪个编号抽"，候选期给候选的槽位号是同一个问题。
#: 所以这里只认前缀，不改声明：`lit_id="cand:000012"` ⇒ 抽读记在槽位 `000012` 上，
#: 并写一条 `data/lit_reads.jsonl` 回执（`litavail.record_read`）。
#:
#: 前缀剥掉之后 `lit_id` 不传给实现主体：候选还没进 literature，任何
#: `_mark_literature_tier` 的落点都不该被碰（传一个不存在的 lit_id 只会静默不写，
#: 而"静默不写"正是这一格要看出来的事）。
_CANDIDATE_PREFIXES: tuple[str, ...] = ("cand:", "candidate:", "slot:")


def _candidate_slot(lit_id: str) -> str:
    """`lit_id` 如果是"候选槽位"的写法，返回裸槽位号；否则空串。"""
    text = str(lit_id or "").strip()
    low = text.lower()
    for prefix in _CANDIDATE_PREFIXES:
        if low.startswith(prefix):
            return text[len(prefix):].strip()
    return ""


def _candidate_row(ctx: _Ctx, slot: str) -> tuple[dict | None, ToolResult | None]:
    """按槽位取候选行；取不到 ⇒ `unknown_slot`（不许把回执写到一个不存在的候选上）。"""
    if ctx.store is None:
        return None, fail("未配置 store：认不出候选槽位（不是「这一条没抽过」）",
                          kind="no_store")
    try:
        rows = list(ctx.store.rows("lit_candidates"))
    except Exception as exc:  # noqa: BLE001 - 表读不出来是"判不了"，不是"没有这一条"
        return None, fail(f"候选表读不出来（{type(exc).__name__}: {exc}）⇒ 抽读这一格判不了",
                          kind="store_error")
    row = next((r for r in rows if str(r.get("slot") or "") == str(slot)), None)
    if row is None:
        known = [str(r.get("slot") or "") for r in rows][:8]
        return None, fail(
            f"待新增列表里没有槽位 {slot!r}（序号不复用；候选期抽读要指向一条真的候选）",
            kind="unknown_slot", slot=str(slot), known=known)
    return dict(row), None


def _record_candidate_read(ctx: _Ctx, slot: str, request_id: str, source: str,
                           res: ToolResult, row: dict | None = None) -> None:
    """把这一次抽读记进回执台账（成功/抽过但失败两档；文件没找到不算抽过）。

    为什么这里只认三个失败档（`garbled_text` / `no_text_layer` / `extract_error`）：
    `file_missing` / `not_a_file` / `no_target` 是"这一份根本没抽" —— 把它们记成
    `extract_failed` 会让"我连文件都没找到"冒充"抽过但正文坏了"，两者下一步相反
    （前者换路径/换源，后者按 quality 判拒）。这同时挡住了"随便给一个不存在的路径，
    就凑出一条'尝试过'的回执"那条假路。

    `row` 是这一条候选行：回执要把它的身份三格一起记下（`litavail.candidate_digest`），
    于是 `readable` 的闸能核"读的是不是这一条候选"（业主裁定 3 的 P1-4）。
    """
    from .. import litavail as _LAV
    from .. import fs_observation as _OBS

    if ctx.store is None:
        return
    root = ctx.store.root
    base = {
        "source": str(source or "").strip(),
        "actor": ctx.actor,
        "candidate": row,
    }
    if res.ok:
        data = dict(res.data or {})
        text_abs = str(data.get("abs_path") or "")
        version = _OBS.version_of_path(Path(text_abs)) if text_abs else ""
        _LAV.record_read(
            root, request_id, slot, _LR.FULLTEXT_OK,
            text=str(data.get("path") or ""), text_abs=text_abs,
            text_version=version, chars=int(data.get("chars") or 0),
            sha256=str(data.get("sha256") or ""), quality=data.get("quality") or {},
            note="text.extract", **base)
        return
    kind = str((res.meta or {}).get("kind") or "")
    if kind not in ("garbled_text", "no_text_layer", "extract_error"):
        return
    _LAV.record_read(
        root, request_id, slot, _LR.FULLTEXT_EXTRACT_FAILED,
        note=f"text.extract.{kind}", quality=(res.meta or {}).get("quality") or {},
        **base)


def _h_extract(ctx: _Ctx, path: str = "", lit_id: str = "", out_dir: str = "",
               pages: Sequence[int] | None = None, max_pages: int = 200) -> ToolResult:
    """``text.extract`` 的工具体：两种编号、两条落点。

    - 普通 `lit_id`（已登记的文献）⇒ 原样走 :func:`_extract_impl`，`.txt` 落 `library/`；
    - 候选期 `lit_id="cand:<槽位>"` ⇒ 抽读 `.txt` 落 `out/texts/`（候选还没入库，
      不该往 `library/` 写正文），并写一条抽读回执 —— 提交闸读的就是它。
      句柄从"候选行"取，取不到当场受控拒（不记回执）。
    """
    slot = _candidate_slot(lit_id)
    if not slot:
        return _extract_impl(ctx, path=path, lit_id=lit_id, out_dir=out_dir,
                             pages=pages, max_pages=max_pages)
    row, bad = _candidate_row(ctx, slot)
    if bad is not None:
        return bad
    if not str(path or "").strip():
        return fail(
            "候选期抽读要给 `path`：候选行上没有本地路径，先 `search.download` 拿到 "
            "`rel_path`（或直接给盘上那份文件的路径），再 `text.extract(path=…, "
            f"lit_id=\"cand:{slot}\")`",
            kind="no_target", slot=slot)
    res = _extract_impl(ctx, path=path, lit_id="", out_dir=(out_dir or "out/texts"),
                        pages=pages, max_pages=max_pages, name_hint=f"cand-{slot}")
    _record_candidate_read(ctx, slot, str(row.get("request_id") or ""), str(path), res,
                           row=row)
    if res.ok and isinstance(res.data, dict):
        # 把"这一抽是给哪一条候选的"带回去（键 `lit_id` 本来就在声明里，不新增键）。
        res.data["lit_id"] = f"cand:{slot}"
    return res


#: 判定"疑似乱码"的阈值（业主 2026-10-17 口径：「A 要保证转出来的纯文字稿不是乱码」）。
#: 2026-11-16 起只有一份实现：`litread.garbled_text`。改前这里是 `_quality` 自己一份、
#: `litread.fulltext_tier` 另一份，两边互不相认 —— 于是 `text.extract` 判"乱码"、
#: 而文献行照样写着 `fulltext` 没有这一档（现场那两份 PDF 就是这样无声消失的）。
#: 三条独立信号、「任何一条」命中就拒（宁可说"这份转不出干净文本"，也不把乱码写进 library/）：
#:   · NUL 字符：PDF 文字层正常「不含」 NUL；出现即错位解码；
#:   · 替换字符 U+FFFD：解码器自己都认不出那个字节 ⇒ 乱码；
#:   · 控制字符占比：正常正文里控制字符几乎为 0（换行/制表除外）。
GARBLED_REPLACEMENT_MAX = _LR.GARBLED_REPLACEMENT_MAX
GARBLED_CONTROL_RATIO_MAX = _LR.GARBLED_CONTROL_RATIO_MAX


def _quality(text: str) -> tuple[bool, dict[str, Any]]:
    """核一遍"这段文本能不能读"。返回 `(是否疑似乱码, 读数)`。

    实现只有一处（`litread.garbled_text`）：这是"乱码"与 `extract_failed` 互认的落点。
    """
    return _LR.garbled_text(text)

@tool(
    "text.extract",
    "把 PDF 文字层转成同名 `.txt` 写进 `library/`（原 PDF 不动；页间插 `===== page N =====`，疑似乱码不写）。扫描件走 OCR（没有就交 B）；别人只读那份 `.txt`。",
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
    # 业主口径（2026-10-17）：「A 负责」搜索/下载/「转成纯文字稿入库」；
    # 其它智能体消费这些文献时「直接读纯文字稿」 ⇒ 这一件只给 A。
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

    `store` 只用来解析路径与把「文献编号」换成那一份全文（抽取本身不读也不写任何表）；
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
