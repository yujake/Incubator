"""B 专用 OCR 工具：后端探测 / 文本层判断 / 按页 OCR。

基于 ``tools/base.py`` 的 ``ToolSpec`` / ``ToolResult`` 写（见 ``DESIGN-TOOLS.md`` §7）。

## 本机已勘察的环境事实（实测复核，不要再假设）

| 后端 | 状态 | 实测证据 |
|---|---|---|
| ``easyocr`` | 装了但跑不了 | ``import easyocr`` 成功（3.4s，1.7.2）；但 ① ``torch 2.0.1+cpu`` 与 ``numpy 2.4.6`` ABI 不匹配，``torch.from_numpy(...)`` 抛 ``RuntimeError: Numpy is not available``（easyocr 的检测/识别路径里确实有 ``torch.from_numpy``，见 ``detection.py`` / ``recognition.py``）；② ``~/.EasyOCR`` 建不出来，构造 ``Reader`` 直接 ``PermissionError [WinError 5]``。模型也未缓存（``~/.EasyOCR/model`` 不存在）。 |
| ``pytesseract`` | 装了但缺二进制 | ``import pytesseract`` 成功（0.3.13），``get_tesseract_version()`` 抛 ``TesseractNotFoundError``：``tesseract`` 不在 PATH。 |
| ``fitz`` / ``PIL`` / ``numpy`` / ``cv2`` | 可用 | 栅格化用 ``fitz``（PyMuPDF），不依赖 MiKTeX 带来的 ``pdftoppm``，少一个外部依赖。 |

结论：本机没有任何可用的 OCR 后端。所以本模块最重要的产出不是"识别出文字"，
而是如实报告"没做成"，并给出可执行的修复建议。

## 三条不可让步的原则

1. ``available()`` 必须真探测。``pytesseract`` 要真的调 ``get_tesseract_version()``
   并捕获异常（"装了 pytesseract" ≠ "装了 tesseract"）；``easyocr`` 只检查
   ``import``、``Reader`` 可调用性、torch↔numpy 桥、模型目录可写性 ——
   绝不在探测阶段真去构造 Reader（那会下 ~100MB 模型，让 ``ocr.backends``
   卡上几分钟，探测本身就成了故障）。

2. 绝不允许"假装 OCR 成功返回空文本"。这与 ``DESIGN.md`` §6.3
   "无文本层返回 ``None`` 而不是 ``False``"同源："没做"和"做了但没结果"是两件事。
   于是：
   - 没有可用后端 ⇒ ``fail("无可用 OCR 后端…")``，一个字符都不返回；
   - 后端抛异常的那一页 ⇒ 记 ``error``，不算成功；
   - 后端真的跑了但结果是空串 ⇒ ``ok`` + 逐页 ``empty=True`` + ``warnings``
     里明说"做了但没结果"，不把它包装成识别成功。
   自检里用一个"返回空串的测试桩后端"把这条语义钉死。

3. ``max_pages`` 是硬保护。OCR 慢得离谱（一页数秒到数十秒），必须限量，
   并且必须在 ``warnings`` 里说明截断了多少页 —— 静默截断会让"我没看到那几页"
   伪装成"那几页没有内容"。

## 副作用等级：这三个工具不都是 ``read``

曾经三个工具一律声明 ``read``（"OCR 不改盘，模型缓存是后端自己的事"），
这是权限面在说假话 —— ``base.SIDE_EFFECTS`` 的 ``read`` 意味着不需要审批：

- ``ocr.run`` ⇒ ``network``：``EasyOcrBackend._reader``（``:252``）会构造
  ``easyocr.Reader``，首次构造要下载约 100MB 模型。这是联网行为，
  与"某一次调用恰好命中了本地缓存"无关（副作用声明的是能力）。
- ``ocr.backends`` ⇒ ``write_local``：``EasyOcrBackend.available``（``:220``）
  会对 easyocr 的真实模型目录 ``mkdir(parents=True, exist_ok=True)``
  —— 该目录在 ``~/.EasyOCR/model``，在工作区之外；``PytesseractBackend``
  还会起一个 ``tesseract --version`` 子进程。这里刻意保留这次 mkdir
  （它是"模型目录到底可不可写"的唯一可靠判据，``os.access`` 在沙箱里会说谎），
  因此如实声明 ``write_local`` 而不是偷偷写盘。
- ``ocr.detect_text_layer`` ⇒ ``read``：只读文件、不写盘、不起进程。
"""

from __future__ import annotations

import importlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .base import ToolRegistry, ToolSpec, fail, ok
from ..extract import ExtractError, extract_text, page_count
from ..store import Store

__all__ = [
    "OcrBackend",
    "OcrError",
    "EasyOcrBackend",
    "PytesseractBackend",
    "NullBackend",
    "INSTALL_HINTS",
    "AUTO_CHAIN",
    "register",
]

#: ``ocr.run(backend="auto")`` 的选择顺序。easyocr 排在前面是因为它不需要系统二进制
#: （只要模型能下、依赖 ABI 对得上就能跑），pytesseract 需要额外的 tesseract。
AUTO_CHAIN: tuple[str, ...] = ("easyocr", "pytesseract")

#: 可直接当图片读的扩展名（非 PDF 的单页文档）。
IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
)

#: 各后端的修复建议。写在这里而不是散落在错误里，是为了让 ``ocr.backends``
#: 能一次性把"接下来该装什么"给全 —— B 在无人值守场景下没法上网查文档。
INSTALL_HINTS: dict[str, str] = {
    "easyocr": (
        "① 先修 torch 与 numpy 的 ABI 不匹配（本机实测 torch 2.0.1+cpu / numpy 2.4.6，"
        'torch.from_numpy 抛 RuntimeError: Numpy is not available）→ 降级 numpy（pip install "numpy<2"）'
        "或升级 torch/torchvision 到与 numpy 2.x 匹配的版本；"
        "② 首次构造 Reader 会下载模型（约 100MB）到 ~/.EasyOCR/model，该目录必须可写；"
        "③ 纯 CPU 可跑（gpu=False），但每页耗时远高于文本层抽取。"
    ),
    "pytesseract": (
        "pytesseract 只是包装器：必须另有 tesseract 可执行文件。Windows 可用 "
        "`winget install UB-Mannheim.TesseractOCR`（或 `choco install tesseract`），"
        "装完确认 `tesseract --version` 能在 PATH 里跑通；中文需另装 chi_sim 语言包。"
    ),
    "none": "不是安装项：它代表「不做 OCR」，是明确的退路而不是能力。",
}


class OcrError(RuntimeError):
    """OCR 运行期失败（没做成）。

    与"OCR 成功但结果为空"严格区分：后者不抛异常，由调用方记 warning。
    只有"根本没跑起来"（无后端、打不开文件、后端抛异常）才走这个类型。
    """


# --------------------------------------------------------------------------- 后端协议


@runtime_checkable
class OcrBackend(Protocol):
    """OCR 后端协议。

    ``available()`` 返回 ``(是否可用, 理由)`` 而不是单个布尔：工具层要把
    "为什么不可用"原样传给 B 与人，一个 False 解释不了任何事。
    多加的 ``refresh`` 是关键字可选参数（默认 False），
    因此 ``available()`` 这个调用形态依然成立；它只是为了绕过进程内探测缓存。

    ``ocr_image(image, languages)`` 接受 numpy 数组或 PIL Image，返回识别文本。
    返回空串是合法结果（"做了但没结果"），抛异常才是"没做成"。
    """

    name: str

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:  # pragma: no cover - 协议声明
        ...

    def ocr_image(self, image: Any, languages: Sequence[str]) -> str:  # pragma: no cover - 协议声明
        ...


def _to_numpy(image: Any) -> Any:
    """把 PIL Image / numpy 数组统一成 numpy 数组（easyocr 两种都收，但统一更省心）。"""
    import numpy as np  # 惰性：避免 import 本模块就拖入 numpy

    if isinstance(image, np.ndarray):
        return image
    return np.array(image)


# --------------------------------------------------------------------------- 后端实现


class EasyOcrBackend:
    """easyocr 后端（PyTorch，不需要系统二进制，但依赖 ABI 与模型目录）。"""

    name = "easyocr"
    produces_text = True

    def __init__(self) -> None:
        self._cached: tuple[bool, str] | None = None
        self._readers: dict[tuple[str, ...], Any] = {}
        #: 探测明细（给 ``ocr.backends`` 看的过程证据，不只给结论）。
        self.checks: dict[str, Any] = {}

    # ---- 探测
    @staticmethod
    def _model_dir() -> Path:
        """easyocr 实际会用的模型目录（与 ``easyocr.Reader`` 的解析顺序一致）。"""
        for env in ("EASYOCR_MODULE_PATH", "MODULE_PATH"):
            value = os.environ.get(env)
            if value:
                return Path(value) / "model"
        return Path.home() / ".EasyOCR" / "model"

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:
        if self._cached is not None and not refresh:
            return self._cached

        checks: dict[str, Any] = {}
        blockers: list[str] = []

        # ① import（这一步会连带 import torch，约 3~5 秒；结果缓存，不重复付代价）
        reader_cls: Any = None
        try:
            easyocr = importlib.import_module("easyocr")
            version = (
                getattr(easyocr, "__version__", None)
                or getattr(easyocr, "version", None)
                or "unknown"
            )
            reader_cls = getattr(easyocr, "Reader", None)
            checks["import"] = f"OK（easyocr {version}）"
            if not callable(reader_cls):
                blockers.append("easyocr.Reader 不存在或不可调用")
                checks["reader"] = "FAILED：easyocr.Reader 不可调用"
            else:
                checks["reader"] = "OK（easyocr.Reader 可调用）"
        except Exception as exc:  # noqa: BLE001 - 导入期异常类型不可预期
            checks["import"] = f"FAILED：{type(exc).__name__}: {exc}"
            checks["reader"] = "SKIPPED（导入失败）"
            blockers.append(f"import easyocr 失败：{type(exc).__name__}: {exc}")

        # ② torch ↔ numpy 的桥。这一步是实测换来的检查：easyocr 的
        #    detection/recognition 路径里有 torch.from_numpy / .numpy()，
        #    ABI 不匹配时导入能成功、推理必炸。不查这一项就会把
        #    "能 import" 当成 "能跑"，而 ocr.run 会在真正识别时才崩。
        import_ok = not blockers
        if import_ok:
            try:
                import numpy as np
                import torch

                torch.from_numpy(np.zeros(1, dtype=np.float32))
                checks["torch_numpy_bridge"] = (
                    f"OK（torch {torch.__version__} / numpy {np.__version__}）"
                )
            except Exception as exc:  # noqa: BLE001
                checks["torch_numpy_bridge"] = f"FAILED：{type(exc).__name__}: {exc}"
                blockers.append(
                    f"torch 与 numpy 不兼容（{type(exc).__name__}: {exc}）：easyocr 的推理路径里有 "
                    "torch.from_numpy/.numpy()，即使模型就绪也会在张量转换处失败"
                )
        else:
            checks["torch_numpy_bridge"] = "SKIPPED（导入失败）"

        # ③ 模型目录：既要能写（首次要下 ~100MB），也要如实报告"是否已缓存"。
        #    这里真的 mkdir 一次 —— 那是权限的唯一可靠判据（os.access 走 ACL，
        #    在沙箱里会说"可写"却实际拒绝），而且这个目录本来就是 easyocr 要建的。
        #
        #    ③ 与 ② 互相独立，所以用 import_ok 而不是 not blockers 作守卫：
        #    ② 失败不该掩盖"模型目录不可写"这个独立故障 —— 两个原因都要报出来，
        #    否则修好 ABI 之后又撞上权限问题，等于白跑一轮。
        model_dir = self._model_dir()
        if import_ok:
            cached = sorted(p.name for p in model_dir.glob("*.pth")) if model_dir.is_dir() else []
            checks["model_cached"] = cached or "无（首次构造 Reader 需下载约 100MB 模型）"
            try:
                model_dir.mkdir(parents=True, exist_ok=True)
                checks["model_dir"] = f"OK（{model_dir} 可写）"
            except OSError as exc:
                checks["model_dir"] = f"FAILED：{type(exc).__name__}: {exc}"
                blockers.append(
                    f"模型目录不可写（{model_dir}）：{type(exc).__name__}: {exc}"
                    "；构造 Reader 时会在此处直接失败"
                )
        else:
            checks["model_cached"] = "SKIPPED（前置检查已失败）"
            checks["model_dir"] = "SKIPPED（前置检查已失败）"

        if blockers:
            reason = "easyocr 不可用：" + "；".join(blockers) + f"。修复建议：{INSTALL_HINTS['easyocr']}"
            result = (False, reason)
        else:
            cached_note = checks.get("model_cached")
            result = (
                True,
                f"easyocr 可用（{checks['import']}，{checks['torch_numpy_bridge']}，模型缓存：{cached_note}）",
            )
        self.checks = checks
        self._cached = result
        return result

    # ---- 识别
    def _reader(self, languages: Sequence[str]) -> Any:
        key = tuple(languages)
        reader = self._readers.get(key)
        if reader is None:
            easyocr = importlib.import_module("easyocr")
            # gpu=False：本机只有 CPU torch；verbose=False：避免每次识别都刷一堆日志。
            reader = easyocr.Reader(list(languages), gpu=False, verbose=False)
            self._readers[key] = reader
        return reader

    def ocr_image(self, image: Any, languages: Sequence[str]) -> str:
        try:
            reader = self._reader(list(languages) or ["en"])
            # detail=0：只要文本，不要坐标框；paragraph=False：按行返回，
            # 与 extract 的逐页文本形态更接近，便于后续做引文定位。
            pieces = reader.readtext(_to_numpy(image), detail=0, paragraph=False)
        except Exception as exc:  # noqa: BLE001 - OCR 后端的异常类型五花八门
            raise OcrError(f"easyocr 识别失败：{type(exc).__name__}: {exc}") from exc
        return "\n".join(str(p) for p in (pieces or []))


class PytesseractBackend:
    """pytesseract 后端。

    它只是 tesseract 的包装器：``pip install pytesseract`` 成功不代表能跑，
    必须有 ``tesseract`` 可执行文件在 PATH 上。所以 ``available()`` 必须真的去
    调一次 ``get_tesseract_version()`` 并捕获 ``TesseractNotFoundError``。
    """

    name = "pytesseract"
    produces_text = True

    def __init__(self) -> None:
        self._cached: tuple[bool, str] | None = None
        self.checks: dict[str, Any] = {}

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:
        if self._cached is not None and not refresh:
            return self._cached
        checks: dict[str, Any] = {}
        try:
            pytesseract = importlib.import_module("pytesseract")
            checks["import"] = f"OK（pytesseract {getattr(pytesseract, '__version__', 'unknown')}）"
        except Exception as exc:  # noqa: BLE001
            checks["import"] = f"FAILED：{type(exc).__name__}: {exc}"
            checks["binary"] = "SKIPPED（导入失败）"
            result = (
                False,
                f"pytesseract 不可用：import 失败（{type(exc).__name__}: {exc}）。"
                f"修复建议：{INSTALL_HINTS['pytesseract']}",
            )
            self.checks = checks
            self._cached = result
            return result

        try:
            version = pytesseract.get_tesseract_version()
        except Exception as exc:  # noqa: BLE001 - TesseractNotFoundError 等
            checks["binary"] = f"FAILED：{type(exc).__name__}: {exc}"
            result = (
                False,
                "pytesseract 不可用：pytesseract 已安装，但 tesseract 可执行文件不可用"
                f"（{type(exc).__name__}: {exc}）。"
                f"修复建议：{INSTALL_HINTS['pytesseract']}",
            )
        else:
            checks["binary"] = f"OK（tesseract {version}）"
            result = (True, f"pytesseract 可用（{checks['import']}，{checks['binary']}）")
        self.checks = checks
        self._cached = result
        return result

    def ocr_image(self, image: Any, languages: Sequence[str]) -> str:
        try:
            pytesseract = importlib.import_module("pytesseract")
            lang = "+".join(list(languages) or ["en"])
            return pytesseract.image_to_string(image, lang=lang)
        except Exception as exc:  # noqa: BLE001
            raise OcrError(f"pytesseract 识别失败：{type(exc).__name__}: {exc}") from exc


class NullBackend:
    """``name="none"``：不是 OCR 后端，而是"明确的退路"。

    它永远可用，却产不出任何文本。把它列进 ``ocr.backends`` 是为了让输出能回答
    "如果没有 OCR 后端系统会怎样"：答案是"什么都不做"，而不是"假装识别成功"。
    ``produces_text=False`` 使 ``backend="auto"`` 永远不会选中它
    （``ocr.run`` 的 enum 里也没有 "none" —— 不做 OCR 就不该走这个工具）。
    """

    name = "none"
    produces_text = False

    def __init__(self) -> None:
        self.checks: dict[str, Any] = {"role": "退路：表示「不做 OCR」，不产出文本"}

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:
        return (
            True,
            "总是可用：它表示「不做 OCR」。选它等于放弃文本获取，返回空串而不是假装识别出内容。",
        )

    def ocr_image(self, image: Any, languages: Sequence[str]) -> str:
        # 返回空串在这里是诚实的：调用方本来就知道它不做 OCR。
        # 关键是不能有任何一个"真后端"走这条路 —— 那才是"假装成功"。
        return ""


# --------------------------------------------------------------------------- 上下文与栅格化


@dataclass
class _Ctx:
    workspace: Path
    store: Store | None = None
    backends: list[Any] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    actor: str = "agent-B"

    def backend_named(self, name: str) -> Any | None:
        for b in self.backends:
            if getattr(b, "name", "") == name:
                return b
        return None

    def real_backends(self) -> list[Any]:
        """会产出文本的后端（按优先级顺序）。"""
        return [b for b in self.backends if getattr(b, "produces_text", True)]


def _resolve(ctx: _Ctx, raw: str) -> Path:
    """把工具收到的路径解析成绝对路径。

    相对路径按"工作区 → library/"两级解释：B 手里的 ``literature.path`` 是
    library/ 下的相对路径，而 A 手里的下载路径是工作区相对的。两级都认，
    调用方就不必自己拼路径（少一次出错的机会）。
    """
    p = Path(raw)
    if p.is_absolute():
        return p
    candidates = [ctx.workspace / p]
    if ctx.store is not None:
        candidates.append(ctx.store.library / p)
    for cand in candidates:
        if cand.exists():
            return cand
    return candidates[0]


def _rasterize(page: Any, dpi: int) -> Any:
    """fitz 页面 → PIL Image。

    用 ``fitz`` 而不是 ``pdftoppm``：后者虽然在本机（随 MiKTeX）存在，
    但多一个外部进程 + 临时文件 + 平台差异，而 PyMuPDF 已经在抽取层被依赖了。
    """
    import fitz
    from PIL import Image

    try:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    except TypeError:  # pragma: no cover - 老版本 PyMuPDF 不接受 dpi 关键字
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _normalize_pages(pages: Sequence[int] | None, total: int, warnings: list[str]) -> list[int]:
    """把 1-based 页号列表规范化成"升序去重且都在范围内"的列表。"""
    if not pages:
        return list(range(1, total + 1))
    out: list[int] = []
    seen: set[int] = set()
    for raw in pages:
        # params 的 schema 已限制为 integer，这里再挡一次是为了 handler 被直接调用时也安全
        if isinstance(raw, bool) or not isinstance(raw, int):
            warnings.append(f"忽略非法页号（非整数）：{raw!r}")
            continue
        if raw < 1 or raw > total:
            warnings.append(f"忽略越界页号 {raw}（文档共 {total} 页，页号从 1 开始）")
            continue
        if raw in seen:
            continue
        seen.add(raw)
        out.append(raw)
    out.sort()
    if not out:
        raise OcrError(f"请求的页号全部无效（文档共 {total} 页）：{list(pages)}")
    return out


def _probe_rows(ctx: _Ctx, refresh: bool = False) -> list[dict]:
    """探测全部后端，返回结构化行（``ocr.backends`` 与 ``ocr.run`` 共用）。"""
    rows: list[dict] = []
    for backend in ctx.backends:
        try:
            available, reason = backend.available(refresh=refresh)
        except Exception as exc:  # noqa: BLE001 - 探测本身失败也要如实上报，不能崩
            available, reason = False, f"探测过程抛异常：{type(exc).__name__}: {exc}"
        rows.append(
            {
                "name": getattr(backend, "name", type(backend).__name__),
                "available": bool(available),
                "reason": reason,
                "produces_text": bool(getattr(backend, "produces_text", True)),
                "checks": dict(getattr(backend, "checks", {}) or {}),
                "install_hint": INSTALL_HINTS.get(getattr(backend, "name", ""), ""),
            }
        )
    return rows


# --------------------------------------------------------------------------- 工具 handler


def _h_backends(ctx: _Ctx, refresh: bool = False) -> Any:
    """``ocr.backends``：真实探测三种后端（easyocr / pytesseract / none）。"""
    rows = _probe_rows(ctx, refresh=refresh)
    real = [r for r in rows if r["produces_text"]]
    available = [r["name"] for r in real if r["available"]]
    selected = available[0] if available else None
    if selected:
        verdict = (
            f"auto 会选中 {selected}（顺序：{' → '.join(AUTO_CHAIN)}）。"
            f"其余后端：{ {r['name']: r['available'] for r in real} }"
        )
    else:
        verdict = (
            "无任何可用 OCR 后端：easyocr 与 pytesseract 都不可用（逐条原因见 backends[].reason）。"
            "此时 ocr.run 会 fail 并给出安装建议 —— 它**不会**返回空文本假装识别成功。"
        )
    return ok(
        {
            "backends": rows,
            "any_ocr_backend_available": bool(available),
            "available": available,
            "selected_for_auto": selected,
            "auto_chain": list(AUTO_CHAIN),
            "verdict": verdict,
            "install_hints": dict(INSTALL_HINTS),
            "note": (
                "easyocr 的探测**不会**下载模型（只查 import / Reader 可调用性 / torch↔numpy 桥 / "
                "模型目录可写性）；模型要等 ocr.run 真正构造 Reader 时才会下载。"
            ),
        }
    )


def _h_detect_text_layer(ctx: _Ctx, path: str) -> Any:
    """``ocr.detect_text_layer``：判断 PDF 有没有文本层（复用 ``extract.extract_text``）。"""
    p = _resolve(ctx, path)
    if not p.exists():
        return fail(f"文件不存在：{p}", kind="file_missing", path=str(p))
    if not p.is_file():
        return fail(f"不是普通文件：{p}", kind="not_a_file", path=str(p))

    try:
        doc = extract_text(p)
    except ExtractError as exc:
        return fail(f"文本层探测失败（extract_text 抛 {type(exc).__name__}）：{exc}", kind="extract_error")
    except Exception as exc:  # noqa: BLE001 - 抽取器之外的运行期故障（缺依赖/权限/损坏）
        return fail(
            f"文本层探测失败（extract_text 抛 {type(exc).__name__}）：{exc}",
            kind="extract_error",
            path=str(p),
        )

    # `page_count` 此前在 try 之外（本函数曾经的缺陷）：它同样会抛
    # （缺 fitz、文件损坏、权限），于是"文本层探测"会以一个没有类型信息的
    # `kind="unexpected"` 失败，而"为什么探测不了"这个信息彻底消失。
    try:
        total = page_count(p)
    except Exception as exc:  # noqa: BLE001
        return fail(
            f"页数探测失败（page_count 抛 {type(exc).__name__}）：{exc}。"
            "注意这与「无文本层」是两件事：前者是**没做成**，后者是**做了、但没有文本**。",
            kind="page_count_failed",
            path=str(p),
        )
    # 唯一判据是 `pages == []`（extract.py 的契约）：扫描版 PDF 能正常打开、
    # 页数正常，但每页抽出来都是空白，此时 pages 被置空。调用方据此把
    # quote_verified 置 null 而不是 false（DESIGN.md §6.3）。
    has_layer = bool(doc.pages)
    pages_with_text = [i + 1 for i, t in enumerate(doc.pages) if t.strip()]

    if has_layer:
        reason = (
            f"有文本层：{len(doc.pages)} 页可定位文本，共 {len(doc.text)} 字符"
            f"（有文字的页：{len(pages_with_text)} 页）。引文校验可以正常判定 true/false。"
        )
        suggestion = "无需 OCR：优先用文本层（快且可定位页码）。"
    elif total:
        reason = (
            f"**无文本层**：文件共 {total} 页，但每页抽出的文本去空白后都为空（疑似扫描件/纯图片页）。"
            "这**不是**「引文校验失败」，而是「无法校验」—— 按 DESIGN.md §6.3，"
            "引文校验必须置 quote_verified=null，并且这份文献需要走 OCR。"
        )
        suggestion = "建议下一步：ocr.backends 看有没有可用后端，再 ocr.run 逐页识别。"
    else:
        reason = (
            "没有可定位文本：文件页数为未知且抽取结果为空（空文件，或 HTML/文本剥标签后为空）。"
            "这不是 PDF 扫描件，走 OCR 大概率也没有内容。"
        )
        suggestion = "先确认文件本身是否为空/格式是否正确。"

    return ok(
        {
            "path": str(p),
            "source_kind": doc.source_kind,
            "has_text_layer": has_layer,
            "pages": len(doc.pages),
            "page_count": total,
            "pages_with_text": len(pages_with_text),
            "chars": len(doc.text),
            "encoding": doc.encoding,
            "reason": reason,
            "suggested_next": suggestion,
            "rule": "has_text_layer := (extract_text(...).pages != [])，与 extract.py / §6.3 的判据完全一致。",
        }
    )


def _select_backend(ctx: _Ctx, requested: str) -> tuple[Any, str]:
    """按 ``backend`` 参数选后端；无可用后端时抛 ``OcrError``（内含安装建议）。"""
    name = (requested or "auto").strip().lower()
    valid = ("auto",) + AUTO_CHAIN
    if name not in valid:
        raise OcrError(f"backend 必须是 {list(valid)} 之一，收到 {requested!r}")

    rows = _probe_rows(ctx)

    def describe() -> str:
        lines = []
        for r in rows:
            if not r["produces_text"]:
                continue
            lines.append(f"  - {r['name']}: {'可用' if r['available'] else '不可用'} —— {r['reason']}")
        hints = "\n".join(f"  - {r['name']}：{r['install_hint']}" for r in rows if r["produces_text"] and r["install_hint"])
        return "各后端探测结论：\n" + "\n".join(lines) + "\n安装/修复建议：\n" + hints

    if name == "auto":
        for candidate in ctx.real_backends():
            available, _reason = candidate.available()
            if available:
                return candidate, f"auto：按 {' → '.join(AUTO_CHAIN)} 顺序选中第一个可用者 {candidate.name}"
        raise OcrError(
            "无可用 OCR 后端（backend=auto 时按 " + " → ".join(AUTO_CHAIN) + " 挑第一个可用者，两个都不可用）。\n"
            + describe()
            + "\n本次**没有**产出任何 OCR 文本 —— '没做'就是'没做'，不会假装成功返回空文本。"
        )

    target = ctx.backend_named(name)
    if target is None:
        raise OcrError(f"没有名为 {name!r} 的后端（已注册：{[getattr(b, 'name', '?') for b in ctx.backends]}）")
    available, reason = target.available()
    if not available:
        raise OcrError(
            f"无可用 OCR 后端：显式指定的 backend={name} 不可用。\n"
            + f"  - {name}: {reason}\n"
            + "安装/修复建议：\n"
            + f"  - {name}：{INSTALL_HINTS.get(name, '')}"
        )
    return target, f"显式指定 {name}"


def _h_run(
    ctx: _Ctx,
    path: str,
    pages: Sequence[int] | None = None,
    backend: str = "auto",
    languages: Sequence[str] | None = None,
    dpi: int = 200,
    max_pages: int = 20,
) -> Any:
    """``ocr.run``：对指定页（或缺省全部页）做 OCR。"""
    p = _resolve(ctx, path)
    if not p.exists():
        return fail(f"文件不存在：{p}", kind="file_missing", path=str(p))

    langs = [str(x) for x in (languages or ["en"])] or ["en"]
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        kind = "pdf"
    elif suffix in IMAGE_SUFFIXES:
        kind = "image"
    else:
        return fail(
            f"不支持的文件类型 {suffix!r}：ocr.run 只处理 PDF（用 fitz 栅格化）与图片"
            f"（{sorted(IMAGE_SUFFIXES)}）。文本类文件请直接用 extract_text。",
            kind="unsupported_format",
        )

    # 后端选择放在打开文件之前：没有后端就什么都别做，
    # 免得先花几十秒栅格化再发现根本没人能识别。
    try:
        chosen, selection = _select_backend(ctx, backend)
    except OcrError as exc:
        return fail(str(exc), kind="no_backend", requested_backend=backend, backends=_probe_rows(ctx))

    warnings: list[str] = []
    truncated = 0
    per_page: list[dict[str, Any]] = []
    requested_all: list[int] = []  # 截断之前的页号，用于让"请求了哪些页"可复核
    t_all = time.monotonic()

    if kind == "pdf":
        try:
            import fitz
        except Exception as exc:  # noqa: BLE001
            return fail(f"缺少 fitz(PyMuPDF)，无法栅格化 PDF：{type(exc).__name__}: {exc}", kind="no_rasterizer")
        try:
            doc = fitz.open(str(p))
        except Exception as exc:  # noqa: BLE001
            return fail(f"无法用 fitz 打开 PDF：{type(exc).__name__}: {exc}", kind="open_failed")
        with doc:
            total = int(doc.page_count)
            try:
                targets = _normalize_pages(pages, total, warnings)
            except OcrError as exc:
                return fail(str(exc), kind="bad_pages", page_count=total)
            requested_all = list(targets)
            if len(targets) > max_pages:
                # 截断必须留痕：静默截断会让"我没看到那几页"伪装成"那几页没有内容"。
                truncated = len(targets) - max_pages
                warnings.append(
                    f"max_pages={max_pages} 保护生效：只处理前 {max_pages} 页，**截断了 {truncated} 页**"
                    f"（本次请求 {len(targets)} 页）。OCR 很慢，请分批再调。"
                )
                targets = targets[:max_pages]
            for n in targets:
                # 这一段此前没有 try：`load_page`/`get_text` 会抛（页号越界、
                # PDF 损坏、缺 fitz 的运行期故障），而这里在工具 handler 内 ——
                # 异常会逃出工具层，被 `base.py:381-382` 兜成没有类型信息的
                # `kind="unexpected"`。逐页失败必须记在这一页上（与栅格化同一范式），
                # 这样"哪一页出的问题"不会消失。
                try:
                    page = doc.load_page(n - 1)
                    layer = page.get_text("text") or ""
                except Exception as exc:  # noqa: BLE001
                    per_page.append(
                        {
                            "page": n,
                            "text_layer_chars": 0,
                            "ok": False,
                            "error": f"读取第 {n} 页失败：{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                item: dict[str, Any] = {"page": n, "text_layer_chars": len(layer.strip())}
                per_page.append(item)
                _ocr_one_page(item, page, chosen, langs, dpi, warnings)
    else:
        total = 1
        try:
            targets = _normalize_pages(pages, total, warnings)
        except OcrError as exc:
            return fail(str(exc), kind="bad_pages", page_count=total)
        requested_all = list(targets)
        from PIL import Image

        item = {"page": 1, "text_layer_chars": 0}
        per_page.append(item)
        try:
            image = Image.open(p)
            image.load()
        except Exception as exc:  # noqa: BLE001
            return fail(f"无法读取图片：{type(exc).__name__}: {exc}", kind="open_failed")
        item["image_size"] = f"{image.width}x{image.height}"
        _ocr_text_into(item, image, chosen, langs, warnings)

    ran = [i for i in per_page if i.get("ok")]
    failed_pages = [i["page"] for i in per_page if not i.get("ok")]
    total_chars = sum(int(i.get("chars") or 0) for i in per_page)

    if not ran:
        # 一页都没跑成 ⇒ 这是"没做成"，必须是 fail，不能返回空文本列表冒充结果。
        return fail(
            f"所有目标页都失败（backend={chosen.name}）："
            + "；".join(f"p{i['page']}: {i.get('error')}" for i in per_page),
            kind="all_pages_failed",
            backend=chosen.name,
            pages=per_page,
            warnings=warnings,
        )

    if total_chars == 0:
        warnings.append(
            "OCR 后端**真实执行过**，但所有目标页都返回空文本：这是「做了但没结果」"
            "（空白页/纯图片页/字体异常），**不是**「没做」，也**不是**识别成功。"
        )

    data: dict[str, Any] = {
        "path": str(p),
        "kind": kind,
        "backend": chosen.name,
        "backend_selection": selection,
        "languages": langs,
        "dpi": dpi,
        "page_count": total,
        "pages_requested": requested_all,
        "pages_attempted": [i["page"] for i in per_page],
        "pages_processed": [i["page"] for i in ran],
        "pages_failed": failed_pages,
        "truncated_pages": truncated,
        "max_pages": max_pages,
        "total_chars": total_chars,
        "pages": per_page,
        "text": "\n".join(i.get("text") or "" for i in ran),
        "elapsed_s": round(time.monotonic() - t_all, 3),
        "warnings": warnings,
        "note": (
            f"backend={chosen.name} 真实执行，产出 {total_chars} 字符。"
            if total_chars
            else f"backend={chosen.name} 真实执行，但产出为空（做了但没结果）。"
        ),
    }
    if failed_pages:
        warnings.append(
            f"有 {len(failed_pages)} 页失败（{failed_pages}），它们**没有**结果，"
            "不要把它们当作「该页无文字」——去看 pages[] 里各自的 error。"
        )
    return ok(data)


def _ocr_one_page(
    item: dict[str, Any], page: Any, backend: Any, langs: list[str], dpi: int, warnings: list[str]
) -> None:
    """栅格化并识别一页（PDF 路径）。失败只记在本页上，不中断其它页。"""
    t0 = time.monotonic()
    try:
        image = _rasterize(page, dpi)
    except Exception as exc:  # noqa: BLE001
        item.update(ok=False, error=f"栅格化失败：{type(exc).__name__}: {exc}")
        return
    item["image_size"] = f"{image.width}x{image.height}"
    _ocr_text_into(item, image, backend, langs, warnings, started=t0)


def _ocr_text_into(
    item: dict[str, Any],
    image: Any,
    backend: Any,
    langs: list[str],
    warnings: list[str],
    *,
    started: float | None = None,
) -> None:
    """对一张图跑 OCR，把结果写进 ``item``。

    这里把三类结局分开记录（这是本模块的核心语义）：
    - 抛异常 ⇒ ``ok=False`` + ``error``（没做成，调用方不得当成本页无文字）；
    - 返回非空 ⇒ ``ok=True`` + ``text``；
    - 返回空串 ⇒ ``ok=True`` + ``empty=True`` + warning（做了但没结果）。
    """
    t0 = started if started is not None else time.monotonic()
    try:
        text = backend.ocr_image(image, langs)
    except Exception as exc:  # noqa: BLE001 - OcrError 及后端原生异常都归为"没做成"
        item.update(ok=False, error=f"{type(exc).__name__}: {exc}", elapsed_s=round(time.monotonic() - t0, 3))
        return
    text = text or ""
    item.update(
        ok=True,
        chars=len(text),
        empty=not text.strip(),
        text=text,
        elapsed_s=round(time.monotonic() - t0, 3),
        error=None,
    )
    if not text.strip():
        page_no = item.get("page", "?")
        warnings.append(
            f"第 {page_no} 页 OCR 返回空文本（做了但没结果）：可能是空白页/纯图片页/字体异常。"
            "请勿把这一页当作「已识别出内容」。"
        )
        if item.get("text_layer_chars"):
            warnings.append(
                f"第 {page_no} 页其实**有文本层**（{item['text_layer_chars']} 字符）而 OCR 为空："
                "优先使用文本层，不要依赖 OCR。"
            )


# --------------------------------------------------------------------------- 注册


def _pick_workspace(
    workspace: str | Path | None,
    workspace_root: str | Path | None,
    root: str | Path | None,
    store: Store | None,
) -> Path:
    """确定工作区根目录。

    接受三个别名是因为 ``tools/__init__.py`` 的装配器按固定依赖名
    （``store`` / ``root`` / ``workspace_root``）反射注入：只认 ``workspace`` 的话，
    调用方显式指定的沙箱根会静默失效（退回到 store.root 或 cwd），
    于是"相对路径按哪个根解释"就悄悄变了 —— 这类静默失效最难排查。
    """
    for cand in (workspace, workspace_root, root):
        if cand is not None:
            return Path(cand)
    return Path(store.root) if store is not None else Path.cwd()


def register(
    registry: ToolRegistry,
    *,
    store: Store | None = None,
    workspace: str | Path | None = None,
    workspace_root: str | Path | None = None,
    root: str | Path | None = None,
    backends: Sequence[Any] | None = None,
    config: Mapping[str, Any] | None = None,
    actor: str = "agent-B",
) -> list[ToolSpec]:
    """把 B 的 OCR 工具注册进 ``registry``，返回注册的 ``ToolSpec`` 列表。

    - ``backends``：后端列表。顺序即 ``auto`` 的优先级；不传时用默认的
      ``[EasyOcrBackend(), PytesseractBackend(), NullBackend()]``。
      注入是给离线测试与将来换后端（如 RapidOCR）用的。
    - ``store``：只用于解析路径（相对路径会依次按工作区、``library/`` 试）与
      推导默认工作区；OCR 本身不读也不写任何表。
    - ``workspace``：工作区根目录；别名 ``workspace_root`` / ``root`` 也接受
      （装配器用这两个名字注入）。
    - 副作用等级逐个如实声明（不要用一句"三个都是 read"概括，见模块 docstring
      最后一节）：``ocr.backends`` 是 ``write_local``（会在 ``~/.EasyOCR/model``
      建目录、会起 ``tesseract --version``），``ocr.run`` 是 ``network``
      （easyocr 首次构造 Reader 会下载模型），只有 ``ocr.detect_text_layer`` 是 ``read``。
      这三者都需要/不需要审批的差异是真实的：把它们压成同一个 ``read``
      就等于对审批说"这些都不用管"。
    """
    if backends is None:
        backend_list: list[Any] = [EasyOcrBackend(), PytesseractBackend(), NullBackend()]
    else:
        backend_list = list(backends)
    ws = _pick_workspace(workspace, workspace_root, root, store)
    ctx = _Ctx(
        workspace=ws.resolve(),
        store=store,
        backends=backend_list,
        config=dict(config or {}),
        actor=actor,
    )

    specs = [
        ToolSpec(
            name="ocr.backends",
            summary="**真实探测** OCR 后端（easyocr / pytesseract / none）各自是否可用，"
            "并逐条给出理由与修复建议；探测阶段**不会**下载 easyocr 模型。",
            params={
                "type": "object",
                "properties": {"refresh": {"type": "boolean"}},
                "additionalProperties": False,
            },
            handler=lambda refresh=False: _h_backends(ctx, refresh),
            # write_local：探测会真的 mkdir easyocr 的真实模型目录（在 ~/.EasyOCR，
            # 工作区之外），并起 `tesseract --version` 子进程。声明成 read 会让
            # "它到底动不动盘"这个问题在权限面上得到错误答案。
            side_effect="write_local",
            roles=("B",),
            # 键名从一个真实调用读出（`_h_backends`）：8 个键；backends[] 每项是
            # {'name','available','reason','produces_text','checks','install_hint'}。
            returns=(
                "{'backends','any_ocr_backend_available','available','selected_for_auto',"
                "'auto_chain','verdict','install_hints','note'}；"
                "backends[] 每项是 {'name','available','reason','produces_text','checks','install_hint'}"
            ),
            tags=("ocr", "probe"),
        ),
        ToolSpec(
            name="ocr.detect_text_layer",
            summary="判断 PDF 有没有文本层（复用 extract.extract_text，pages==[] 即无文本层）；"
            "无文本层时说明这是「无法校验」而不是「校验失败」。",
            params={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1000}},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda path: _h_detect_text_layer(ctx, path),
            side_effect="read",
            roles=("B",),
            # 键名从一个真实调用读出（`_h_detect_text_layer`）。
            returns="{'path','source_kind','has_text_layer','pages','page_count','pages_with_text','chars','encoding','reason','suggested_next','rule'}",
            tags=("ocr", "detect"),
        ),
        ToolSpec(
            name="ocr.run",
            summary="对指定页（缺省全部页）做 OCR；auto 按 easyocr→pytesseract 选第一个可用者，"
            "都不可用时 fail 并给出安装建议（绝不返回空文本假装成功）。",
            params={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "pages": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1},
                        "maxItems": 500,
                    },
                    "backend": {"type": "string", "enum": ["auto", *AUTO_CHAIN]},
                    "languages": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "maxItems": 8,
                    },
                    "dpi": {"type": "integer", "minimum": 72, "maximum": 600},
                    "max_pages": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda path, pages=None, backend="auto", languages=None, dpi=200, max_pages=20: _h_run(
                ctx, path, pages, backend, languages, dpi, max_pages
            ),
            # network：easyocr 首次构造 Reader 会下载约 100MB 模型（`_reader` :252）。
            # "本机没有可用后端"只是当前环境的结论，不能用来把能力声明成只读。
            side_effect="network",
            roles=("B",),
            # 键名逐个从 `_h_run` 的 ok(data) 读出（不是在真实调用里数出来的：
            # 走通它需要 PyMuPDF / Pillow / 一个真后端，本轮没有真跑过 —— 如实留痕）。
            returns=(
                "{'path','kind','backend','backend_selection','languages','dpi','page_count',"
                "'pages_requested','pages_attempted','pages_processed','pages_failed',"
                "'truncated_pages','max_pages','total_chars','pages','text','elapsed_s',"
                "'warnings','note'}；"
                "pages[] 每项是 {'page','text_layer_chars','ok','text','chars','empty','error','image_size','elapsed_s'}"
            ),
            tags=("ocr", "run"),
        ),
    ]
    registry.register_all(specs)
    return specs


# --------------------------------------------------------------------------- 自检


class _StubBackend:
    """自检专用的测试桩（名字里带 stub，任何输出都会标明它不是真 OCR）。

    它的存在是为了把"工具层语义"与"本机没有 OCR 后端"这两件事解耦：
    即使一个真后端都没有，也能验证栅格化、逐页循环、max_pages 截断、
    以及最关键的 —— 空文本必须被记成"做了但没结果"而不是识别成功。
    """

    produces_text = True

    def __init__(self, name: str, text: str = "", *, available: bool = True, reason: str = "测试桩") -> None:
        self.name = name
        self.checks: dict[str, Any] = {"role": "自检测试桩（不是真 OCR）"}
        self._text = text
        self._available = available
        self._reason = reason
        self.calls: list[Any] = []

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:
        return self._available, self._reason

    def ocr_image(self, image: Any, languages: Sequence[str]) -> str:
        self.calls.append((getattr(image, "size", None), tuple(languages)))
        return self._text


def _selftest() -> int:
    """自检：真实探测后端 + 文本层判断 + （有后端才跑的）真实 OCR。"""
    import sys
    import tempfile

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

    # 本文件在 src/agentflow/tools/ 下，比 providers.py 深一层：
    # parents = [tools, agentflow, src, test1]，故 demo/ 在 parents[3]。
    demo = Path(__file__).resolve().parents[3] / "demo" / "selftest"
    sample = demo / "sample.pdf"
    blank = demo / "blank.pdf"

    registry = ToolRegistry(name="selftest-B")
    register(registry, workspace=Path(tempfile.gettempdir()))

    print("=" * 78)
    print("agentflow.tools.ocr_tools 自检")
    print(f"素材：{sample}（应有文本层） / {blank}（应无文本层）")
    print("=" * 78)
    print(registry.text_catalog(role="B"))

    failed = 0

    # ---- [1] 后端真实探测（最重要的一条）
    print("-" * 78)
    print("[1] ocr.backends —— 真实探测（每个后端都要有「可用/不可用 + 原因」）")
    res = registry.call("ocr.backends")
    if not res.ok:
        print(f"    [失败] {res.error}")
        failed += 1
    else:
        data = res.unwrap()
        for row in data["backends"]:
            print(
                f"    - {row['name']:<12} available={row['available']!s:<5} "
                f"produces_text={row['produces_text']!s:<5}\n        reason: {row['reason']}"
            )
            for key, value in row["checks"].items():
                print(f"        check.{key} = {value}")
        print(f"    auto 会选中的后端：{data['selected_for_auto']}")
        print(f"    verdict: {data['verdict']}")

    # ---- [2] 文本层判断
    print("-" * 78)
    print("[2] ocr.detect_text_layer —— sample.pdf（有文本层）/ blank.pdf（无文本层）")
    for p in (sample, blank):
        res = registry.call("ocr.detect_text_layer", path=str(p))
        if not res.ok:
            print(f"    [失败] {p.name}: {res.error}")
            failed += 1
            continue
        d = res.unwrap()
        print(
            f"    {p.name}: has_text_layer={d['has_text_layer']} pages={d['pages']} "
            f"page_count={d['page_count']} pages_with_text={d['pages_with_text']} chars={d['chars']} "
            f"source_kind={d['source_kind']}"
        )
        print(f"        reason: {d['reason']}")
        print(f"        next:   {d['suggested_next']}")

    # ---- [3] 真实后端链：本机现况（预期 fail，且必须说清"没有产出"）
    print("-" * 78)
    print("[3] ocr.run backend=auto（用真实后端链：本机预期无可用后端）")
    res = registry.call("ocr.run", path=str(sample), pages=[1])
    print(f"    ok={res.ok}")
    if res.ok:
        print("    [意外] 本机居然有可用后端，结果如下：")
        d = res.unwrap()
        print(f"        backend={d['backend']} total_chars={d['total_chars']} elapsed={d['elapsed_s']}s")
        for i in d["pages"]:
            print(f"        p{i['page']}: chars={i.get('chars')} empty={i.get('empty')} text={ (i.get('text') or '')[:120]!r}")
        print(f"        warnings={d['warnings']}")
    else:
        print("    [如预期·如实报告] 工具 fail，且明确说明没有产出任何文本：")
        print(f"    error=\n{res.error}")
        print(f"    meta.kind={res.meta.get('kind')}")

    # ---- [4] 显式指定 easyocr：理由必须来自真实探测
    print("-" * 78)
    print("[4] ocr.run backend=easyocr（显式指定不可用的后端）")
    res = registry.call("ocr.run", path=str(sample), backend="easyocr", pages=[1])
    print(f"    ok={res.ok}")
    print(f"    error={res.error}")

    # ---- [5] 栅格化自检（后端之外的环节必须证明是好的）
    print("-" * 78)
    print("[5] fitz 栅格化自检（证明「除了没有 OCR 后端，其它环节都通」）")
    try:
        import fitz

        with fitz.open(str(sample)) as doc:
            page = doc.load_page(0)
            img = _rasterize(page, 150)
        gray = img.convert("L").getextrema()
        print(
            f"    第 1 页 @150dpi → PIL {img.mode} {img.width}x{img.height}，"
            f"灰度极值={gray}（含 0 与 255 说明文字像素被真实渲染出来了）"
        )
        if img.width < 100 or gray[0] == gray[1]:
            print("    [失败] 栅格化结果可疑（尺寸过小或全同色）")
            failed += 1
    except Exception as exc:  # noqa: BLE001
        print(f"    [失败] 栅格化异常：{type(exc).__name__}: {exc}")
        failed += 1

    # ---- [6] 用测试桩把「空文本 ≠ 成功」与 max_pages 截断钉死
    print("-" * 78)
    print("[6] 测试桩后端（**不是真 OCR**）：验证空文本语义 / 逐页循环 / max_pages 截断")
    stub_reg = ToolRegistry(name="selftest-B-stub")
    stub_empty = _StubBackend("stub-empty", "")
    register(stub_reg, workspace=Path(tempfile.gettempdir()), backends=[stub_empty])
    res = stub_reg.call("ocr.run", path=str(sample), pages=[1])
    if res.ok:
        d = res.unwrap()
        print(f"    桩返回空串 → ok={res.ok} backend={d['backend']} total_chars={d['total_chars']}")
        print(f"        pages={[{'page': i['page'], 'ok': i['ok'], 'empty': i.get('empty'), 'chars': i.get('chars')} for i in d['pages']]}")
        for w in d["warnings"]:
            print(f"        [warning] {w}")
        print(f"        note={d['note']}")
        if d["total_chars"] != 0 or not any("做了但没结果" in w for w in d["warnings"]):
            print("        [失败] 空文本没有被显式标注为「做了但没结果」")
            failed += 1
    else:
        print(f"    [失败] 桩后端应当能跑通，却 fail 了：{res.error}")
        failed += 1

    stub_text = _StubBackend("stub-text", "STUB-RECOGNIZED-TEXT")
    stub_reg2 = ToolRegistry(name="selftest-B-stub2")
    register(stub_reg2, workspace=Path(tempfile.gettempdir()), backends=[stub_text])
    res = stub_reg2.call("ocr.run", path=str(sample), max_pages=1, dpi=120)
    if res.ok:
        d = res.unwrap()
        print(
            f"    桩返回文本 + max_pages=1（sample.pdf 有 3 页）→ ok={res.ok} backend={d['backend']} "
            f"processed={d['pages_processed']} truncated={d['truncated_pages']} total_chars={d['total_chars']}"
        )
        print(f"        text={d['text']!r}")
        for w in d["warnings"]:
            print(f"        [warning] {w}")
        if d["truncated_pages"] != 2:
            print(f"        [失败] max_pages 截断页数应为 2，实际 {d['truncated_pages']}")
            failed += 1
        if not any("截断" in w for w in d["warnings"]):
            print("        [失败] 截断没有写进 warnings")
            failed += 1
    else:
        print(f"    [失败] 桩后端应当能跑通，却 fail 了：{res.error}")
        failed += 1

    # 越界页号
    res = stub_reg2.call("ocr.run", path=str(sample), pages=[99])
    print(f"    越界页号 pages=[99] → ok={res.ok} error={res.error!r}")
    if res.ok:
        print("        [失败] 全部越界应当 fail")
        failed += 1

    print("=" * 78)
    print(f"SELF-CHECK {'DONE' if failed == 0 else f'FAILED({failed})'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover - 手工自检入口
    raise SystemExit(_selftest())
