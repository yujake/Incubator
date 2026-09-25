"""探针：用真实 downloader 对 AMS（病态：.pdf 链接返回 HTML）与 arXiv（正常）各下一次。

**这份脚本是缺陷 #8 的证据来源** —— 它证明了"下载成功（HTTP 200）"与"拿到的是论文"
是两件不同的事：AMS 那个以 `.pdf` 结尾的 URL 返回的其实是 12.4 MB 的 `text/html` 落地页。
保留它（而不是用完即删）是为了让后来者能一条命令复现该结论。

用法：`python tools/probe_download_ams_vs_arxiv.py`（**会联网**）

⏱️ **预期耗时数分钟**：AMS 那个链接会老实传完 ≈12 MB 的 HTML 落地页，
再加 arXiv 的一个正常 PDF 与 1.2s 限速间隔。请给足超时（建议 ≥ 10 分钟），
不要因为"跑太久"就以为它挂了 —— 这个"慢"本身就是证据的一部分。
"""

import sys
import tempfile
from pathlib import Path

# tools/ 的兄弟目录是 src/，abflow 包在它下面
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from abflow.fetch import default_downloader  # noqa: E402

AMS = (
    "https://www.ams.org/mcom/1987-48-177/S0025-5718-1987-0866109-5/"
    "S0025-5718-1987-0866109-5.pdf"
)
ARXIV = "https://arxiv.org/pdf/0807.3917"

dl = default_downloader({"min_interval": 1.2, "retries": 2, "read_timeout": 90})

with tempfile.TemporaryDirectory() as td:
    for label, url in (("AMS-html", AMS), ("arXiv-pdf", ARXIV)):
        print(f"--- {label}: {url}")
        res = dl.download(url, Path(td), label)
        print(f"    ok={res.ok} http={res.http_status} bytes={res.bytes} sha={(res.sha256 or '')[:16]}")
        print(f"    error={res.error}")
        if res.path and Path(res.path).exists():
            head = Path(res.path).read_bytes()[:8]
            print(f"    path={Path(res.path).name} size={Path(res.path).stat().st_size} head={head!r}")
        # 每次重试都要重新建连，间隔已由限速器保证
print("stats =", dl.stats)
