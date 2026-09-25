"""写作期探针：如实采集 OCR 链路的现场证据（供报告引用）。

打印四件事：
  1. `ocr.backends` 的探测结论（真实探测，不是假定）
  2. `ocr.run` 在 backend=auto 下的真实返回（应为结构化失败 + meta.kind=no_backend）
  3. `ocr.detect_text_layer` 对"有文本层 / 无文本层"两种 PDF 的结论
  4. `fitz` 栅格化：证明"除 OCR 后端外整条链路是通的"（分辨率、模式、灰度极值）

用法：python tools/probe_ocr_chain.py [工作区]
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402


def show(title: str, res) -> None:
    print(f"\n===== {title} =====")
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2)[:4000])


def main() -> int:
    root = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "pipelinedemo"
    st = Store(root)
    rb = build_registry(store=st)
    reg = rb.registry

    show("1. ocr.backends（真实探测）", reg.call("ocr.backends"))

    # 造两个 PDF：一个带文本层（fitz 直接写文字），一个纯图（只画线，无文字）
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # noqa: BLE001
        print(f"\n!! fitz 不可用：{type(e).__name__}: {e}")
        return 1

    ws = root / "downloads"
    ws.mkdir(parents=True, exist_ok=True)
    with_text = ws / "probe_with_text.pdf"
    no_text = ws / "probe_no_text.pdf"

    d = fitz.open()
    p = d.new_page(width=595, height=842)
    p.insert_text((72, 100), "An abelian group is a group.", fontsize=14)
    d.save(str(with_text))
    d.close()

    d = fitz.open()
    p = d.new_page(width=595, height=842)
    p.draw_rect(fitz.Rect(80, 80, 500, 300))
    p.draw_line(fitz.Point(80, 500), fitz.Point(500, 500))
    d.save(str(no_text))
    d.close()

    show("2a. ocr.detect_text_layer（带文本层）",
         reg.call("ocr.detect_text_layer", path="downloads/probe_with_text.pdf"))
    show("2b. ocr.detect_text_layer（纯图，无文本层）",
         reg.call("ocr.detect_text_layer", path="downloads/probe_no_text.pdf"))

    show("3a. ocr.run（auto，带文本层，无需 OCR）",
         reg.call("ocr.run", path="downloads/probe_with_text.pdf", backend="auto"))
    show("3b. ocr.run（auto，纯图 —— 无后端时的真实行为）",
         reg.call("ocr.run", path="downloads/probe_no_text.pdf", backend="auto"))
    show("3c. ocr.run（backend=none，显式'不做 OCR'）",
         reg.call("ocr.run", path="downloads/probe_no_text.pdf", backend="none"))

    # 4. 栅格化
    print("\n===== 4. fitz 栅格化（证明除 OCR 后端外链路是通的）=====")
    doc = fitz.open(str(no_text))
    page = doc.load_page(0)
    zoom = 200 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
    gray = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    print(f"RGB pixmap: {pix.width}x{pix.height} n={pix.n} alpha={pix.alpha} samples={len(pix.samples)}")
    print(f"GRAY pixmap: {gray.width}x{gray.height} n={gray.n}")
    print(f"灰度极值: min={min(gray.samples)} max={max(gray.samples)}")
    print(f"PNG 字节数（RGB）: {len(pix.tobytes('png'))}")
    for b in reg.call("ocr.backends").data["backends"]:
        print(f"  后端 {b['name']}: available={b['available']} produces_text={b['produces_text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
