"""真实网络冒烟测试：只做搜索，不下载。

之所以单独放一个脚本（而不是测试用例）：它依赖网络，因此不适合进 pytest 套件。
它的作用是回答一个 pytest 回答不了的问题 —— "线上那条路真的通吗"。

用法：
    cd test/test1/src
    python ../tools/smoke_real_provider.py [--download]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentflow.providers import CrossrefProvider, OpenAlexProvider  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="abelian group")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("--download", action="store_true", help="额外尝试下载第一个 OA PDF")
    args = ap.parse_args()

    failures = 0
    for provider in (OpenAlexProvider(), CrossrefProvider()):
        print(f"\n{'=' * 70}\nprovider = {provider.name}\n{'=' * 70}")
        for mode in ("broad", "topical", "precise"):
            desc = "definition of abelian group and its relation to group" if mode == "precise" else ""
            try:
                got = provider.search(args.topic, mode, desc, args.limit)
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  [{mode:8}] 失败：{type(e).__name__}: {str(e)[:160]}")
                continue
            print(f"  [{mode:8}] {len(got)} 条")
            for c in got[: args.limit]:
                pdf = "有PDF" if c.pdf_url else "无PDF"
                print(f"      [{c.type_code}] {c.title[:58]}")
                print(f"            year={c.year} doi={c.doi} {pdf} venue={(c.venue or '')[:40]}")

    if args.download:
        print(f"\n{'=' * 70}\n下载测试\n{'=' * 70}")
        from agentflow.fetch import default_downloader

        dl = default_downloader({"min_interval_seconds": 1.0, "retries": 2})
        got = OpenAlexProvider().search(args.topic, "topical", "", 8)
        target = next((c for c in got if c.pdf_url), None)
        if target is None:
            print("  本次搜索结果里没有可直接下载的 OA PDF —— 这是数据情况，不是故障")
        else:
            import tempfile

            with tempfile.TemporaryDirectory() as td:
                print(f"  尝试下载：{target.pdf_url[:100]}")
                res = dl.download(target.pdf_url, Path(td), "smoke")
                print(f"  ok={res.ok} http={res.http_status} bytes={res.bytes} sha256={(res.sha256 or '')[:16]} err={res.error}")
                if not res.ok:
                    failures += 1

    print(f"\n结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}（网络相关失败可能是环境/限流，请人工判断）")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
