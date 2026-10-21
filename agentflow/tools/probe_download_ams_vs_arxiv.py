"""探针：用真实 downloader 对 AMS（病态：.pdf 链接返回 HTML）与 arXiv（正常）各下一次。

这份脚本是缺陷 #8 的证据来源 —— 它证明了"下载成功（HTTP 200）"与"拿到的是论文"是两件不同的事：AMS 那个以 `.pdf` 结尾的 URL 返回的其实是 ≈12 MB 的 `text/html` 落地页。
保留它（而不是用完即删）是为了让后来者能一条命令复现该结论。用法：`python tools/probe_download_ams_vs_arxiv.py`（会联网）⏱预期耗时数分钟：AMS 那个链接会老实传完 ≈12 MB 的
HTML 落地页，再加 arXiv 的一个正常 PDF 与 1.2s 限速间隔。请给足超时（建议 ≥ 10 分钟），不要因为"跑太久"就以为它挂了 —— 这个"慢"本身就是证据的一部分。

## 退出码（三档）

- ``0`` —— 现象成立：AMS 那条拿到非 PDF 内容（由 `.ok` 与魔数共同判定），
而 arXiv 那条拿到真 PDF。
- ``1`` —— 现象不成立 / 结论矛盾：例如 AMS 也拿到了真 PDF（上游改了行为、
或本项目给了一份可直接下载的镜像），或 arXiv 那条反而失败了。这是结论变了，不是探针坏了：`fetch.py` / `agent_a.py` / README §7 的相关记述必须有人重新走查。
- ``2`` —— 没查成：两条都失败（网络问题）⇒ 没有结论。
"连不上"与"连上了但现象没了"是两件不同的事，必须分开。

与 `probe_ams_content_type.py` 的分工：那一份只测 HTTP 层的响应头与字节；这一份测的是真实 downloader 的判定（`fetch.default_downloader`）。两份都要有退出码，
因为它们都曾被当"看一眼输出"的手工脚本用，于是"没输出"与"输出说没问题"在自动化里长得一模一样。
"""

import sys
import tempfile
from pathlib import Path

# tools/ 的兄弟目录是 src/，agentflow 包在它下面
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentflow.fetch import default_downloader  # noqa: E402

AMS = (
    "https://www.ams.org/mcom/1987-48-177/S0025-5718-1987-0866109-5/"
    "S0025-5718-1987-0866109-5.pdf"
)
ARXIV = "https://arxiv.org/pdf/0807.3917"

#: PDF 魔数。用内容判而不是用 `Content-Type`：本探针要证的正是
#: "声明与内容不是一回事"，拿声明去判声明是循环论证。
PDF_MAGIC = b"%PDF"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dl = default_downloader({"min_interval": 1.2, "retries": 2, "read_timeout": 90})
    heads: dict[str, bytes | None] = {}

    with tempfile.TemporaryDirectory() as td:
        for label, url in (("AMS-html", AMS), ("arXiv-pdf", ARXIV)):
            print(f"--- {label}: {url}")
            res = dl.download(url, Path(td), label)
            print(f"    ok={res.ok} http={res.http_status} bytes={res.bytes} "
                  f"sha={(res.sha256 or '')[:16]}")
            print(f"    error={res.error}")
            head: bytes | None = None
            if res.path and Path(res.path).exists():
                head = Path(res.path).read_bytes()[:8]
                print(f"    path={Path(res.path).name} "
                      f"size={Path(res.path).stat().st_size} head={head!r}")
            heads[label] = head
            # 每次重试都要重新建连，间隔已由限速器保证
    print("stats =", dl.stats)

    print("=" * 72)
    ams_is_pdf = bool(heads.get("AMS-html") and heads["AMS-html"].startswith(PDF_MAGIC))
    arxiv_is_pdf = bool(heads.get("arXiv-pdf") and heads["arXiv-pdf"].startswith(PDF_MAGIC))

    if heads.get("AMS-html") is None and heads.get("arXiv-pdf") is None:
        print("[unknown] 两条都没拿到字节 ⇒ **没有结论**（不是'没问题'）")
        return 2
    if not ams_is_pdf and arxiv_is_pdf:
        print("[0] 现象成立：AMS 那条拿到**非 PDF**，arXiv 那条拿到真 PDF。")
        print("    ⇒ 支撑 fetch.py 的 content_type_mismatch 与 A 的 content_mismatch 降级。")
        return 0
    print("[1] 结论与记录不符：")
    print(f"    AMS 是 PDF ? {ams_is_pdf}（记录里应当是 False）")
    print(f"    arXiv 是 PDF ? {arxiv_is_pdf}（记录里应当是 True）")
    print("    ⇒ **不是探针坏了，是结论变了**。请重新走查 fetch.py / agent_a.py / README §7 第 3 条。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
