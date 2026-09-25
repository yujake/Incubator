"""探针：测量 AMS 直链的真实响应行为与耗时（不依赖 abflow，纯 urllib）。

用途：确认"以 `.pdf` 结尾的 URL 实际返回 `Content-Type: text/html`"这一现象，
并测出它需要多久才把 12 MB 的落地页传完 —— 这解释了为什么下载器会认为"下载成功"。

用法：`python tools/probe_ams_content_type.py`（**会联网**，且会下 ≈12 MB）
"""

import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = (
    "https://www.ams.org/mcom/1987-48-177/S0025-5718-1987-0866109-5/"
    "S0025-5718-1987-0866109-5.pdf"
)
UA = "abflow/0.1 (research prototype; contact: local)"

for label, timeout in (("60s", 60), ("180s", 180)):
    start = time.monotonic()
    total = 0
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type")
            first = resp.read(16)
            print(f"[{label}] status={resp.status} ctype={ctype} first={first!r} t={time.monotonic()-start:.1f}s")
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if time.monotonic() - start > timeout:
                    print(f"  超过 {timeout}s 仍未读完，已收 {total} 字节")
                    break
        print(f"[{label}] 读完 {total} 字节，耗时 {time.monotonic()-start:.1f}s")
    except Exception as exc:
        print(f"[{label}] 失败于 {total} 字节 / {time.monotonic()-start:.1f}s：{type(exc).__name__}: {exc}")
    time.sleep(1.5)
