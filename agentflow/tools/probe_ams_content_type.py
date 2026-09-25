"""探针：测量 AMS 直链的真实响应行为与耗时（不依赖 agentflow，纯 urllib）。

用途：确认"以 `.pdf` 结尾的 URL 实际返回 `Content-Type: text/html`"这一现象，
并测出它需要多久才把 ≈12 MB 的落地页传完 —— 这解释了为什么下载器会认为"下载成功"。

用法：`python tools/probe_ams_content_type.py`（会联网，且会下 ≈12 MB）

## 退出码（三档，不许只有"没报错"）

自动化的判据必须是三档，否则"检查通过"与"脚本根本没跑成"分不开
（本项目 `DEVELOPMENT.md` §6 与 `scripts/lint_rules.py` R008 都要求这一点）：

- ``0`` —— 现象成立：以 `.pdf` 结尾的 URL 返回了非 PDF 的 `Content-Type`。
  这是本探针要证的结论（缺陷 #8 的前提）。
- ``1`` —— 现象不成立：确实收到了 `application/pdf`。
  这不是"探针坏了"，而是结论变了 —— 上游改了行为，于是
  "下载成功 ≠ 拿到论文"这条记录的证据来源失效，必须有人重新走查
  `fetch.py` 的 `content_type_mismatch` 分支还需要不需要留。
- ``2`` —— 没查成：网络失败 / 超时 / 被拦。这不是 1，也不是 0。
  "连不上"与"连上了发现现象没了"是两件完全不同的事。
"""

import sys
import time
import urllib.request

URL = (
    "https://www.ams.org/mcom/1987-48-177/S0025-5718-1987-0866109-5/"
    "S0025-5718-1987-0866109-5.pdf"
)
UA = "agentflow/0.1 (research prototype; contact: local)"

#: PDF 的魔数。判据用内容而不是 `Content-Type`：这个探针要证的恰恰是
#: "头里声明的类型与真实内容不是一回事"，所以拿头去判头是循环论证。
PDF_MAGIC = b"%PDF"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    observed: list[str] = []      # 观察到的 Content-Type
    bodies: list[bytes] = []      # 每个 label 的前 16 字节
    failures: list[str] = []      # 没查成的 label

    for label, timeout in (("60s", 60), ("180s", 180)):
        start = time.monotonic()
        total = 0
        try:
            req = urllib.request.Request(URL, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = resp.headers.get("Content-Type")
                first = resp.read(16)
                print(f"[{label}] status={resp.status} ctype={ctype} first={first!r} "
                      f"t={time.monotonic() - start:.1f}s")
                observed.append(str(ctype or ""))
                bodies.append(first)
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if time.monotonic() - start > timeout:
                        print(f"  超过 {timeout}s 仍未读完，已收 {total} 字节")
                        break
            print(f"[{label}] 读完 {total} 字节，耗时 {time.monotonic() - start:.1f}s")
        except Exception as exc:  # noqa: BLE001 —— 理由：探针必须把"哪一种失败"如实分类。
            # 网络类失败 ⇒ "没查成"（退出码 2），而不是"现象不成立"（退出码 1）。
            # 把两者混起来，等于用一个网络故障去否证一条上游行为结论。
            print(f"[{label}] 失败于 {total} 字节 / {time.monotonic() - start:.1f}s："
                  f"{type(exc).__name__}: {exc}")
            failures.append(f"{label}: {type(exc).__name__}")
        time.sleep(1.5)

    print("=" * 72)
    if not bodies:
        print(f"[unknown] 两次都没查成 ⇒ **没有结论**（失败：{failures}）")
        return 2

    is_pdf = [b.startswith(PDF_MAGIC) for b in bodies]
    print(f"观察到的 Content-Type：{observed}")
    print(f"前 16 字节是否以 %PDF 开头：{is_pdf}")
    if any(not v for v in is_pdf):
        print("[0] 现象成立：以 .pdf 结尾的 URL **不是** PDF 内容。")
        print("    ⇒ 支撑 `fetch.py` 的 `content_type_mismatch` 分支与 A 的 "
              "`status=content_mismatch` 降级。")
        return 0
    print("[1] 现象**不成立**：这次拿到的是真 PDF。")
    print("    ⇒ 上游行为可能已变。**请重新走查**：`fetch.py` 的 `content_type_mismatch` "
          "分支、A 的 `content_mismatch` 降级、以及 README §7 第 3 条是否仍然成立。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
