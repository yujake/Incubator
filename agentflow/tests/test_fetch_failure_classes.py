"""下载失败的分类与重试边界（2026-10-16，我亲自下一轮文献之后加的判据）。

现场读数：`projects/p8o` 那一趟跑到 72 分钟、模型调用只有 15 次 —— 时间全耗在 `URLError` 那一支的
无差别重试上。我亲自复现了那两个源：

repositories.lib.utexas.edu/... ⇒ 默认 122 s 后判死（Schannel CRYPT_E_REVOCATION_OFFLINE），
加客户端开关（curl --ssl-no-revoke）⇒ 0.55 s 就拿到状态码；
www.mdpi.com/.../pdf ⇒ 连续三次都是 _ssl.c:985: The handshake operation timed out

⇒ 证书/吊销类是"本机 TLS 栈"的事，重试修不好（记 `tls_cert`，不重试）；TLS 握手超时多半是对方
挡脚本（记 `tls_timeout`，至多再试一次）。这两档此前都折进 `network_error`，读账的人分不出
"该重试"与"重试无益"。

三组（含负控）：1. 证书/吊销类 ⇒ 只尝试一次，档位 `tls_cert`，且日志里没有重试字样；
2. TLS 握手超时 ⇒ 至多两次，档位 `tls_timeout`；3. 负控：普通 `URLError`（连接被重置）⇒
照旧重试满 `retries` 次（别把这一支改窄了：换一跳或换镜像真的能过）。"""

from __future__ import annotations

import ssl
import urllib.error

from agentflow import fetch as F


class _Boom(F.HttpDownloader):
    """把 `_open` 换成"一抛就死"的替身，并数尝试次数；`sleep` 注入成空操作（测试要快）。"""

    def __init__(self, exc: BaseException, **kw: object) -> None:
        kw.setdefault("sleep", lambda _seconds: None)
        super().__init__(**kw)  # type: ignore[arg-type]
        self._exc = exc
        self.calls = 0

    def _open(self, request: object, timeout: object) -> object:
        self.calls += 1
        raise self._exc


def _attempt(exc: BaseException, tmp_path, **kw: object) -> tuple[int, F.FetchResult]:
    d = _Boom(exc, **kw)
    res = d.download("https://example.invalid/paper.pdf", tmp_path)
    return d.calls, res


def test_a_certificate_failure_is_not_retried(tmp_path) -> None:
    """证书/吊销类 ⇒ 只尝试一次，档位 `tls_cert`（重试修不好本机信任链问题）。"""
    exc = urllib.error.URLError(
        ssl.SSLCertVerificationError("certificate verify failed: unable to get local issuer")
    )
    calls, res = _attempt(exc, tmp_path, retries=3)
    assert calls == 1, f"证书类竟然试了 {calls} 次（第 122 秒×3 就是这么来的）"
    assert res.ok is False, res
    # 外层档位是候选/镜像循环给的 `all_sources_failed`；内层分类落在 `error` 里
    # （`tls_cert:` 前缀）—— 读账的人据此知道"不是网络抖动"。
    assert "tls_cert" in str(res.error), res.error
    assert "certificate verify failed" in str(res.error), res.error


def test_a_revocation_failure_is_recognised_as_cert_class(tmp_path) -> None:
    """负控的正控面：Schannel 那句 `CRYPT_E_REVOCATION_OFFLINE` 也要落进 `tls_cert`。"""
    exc = urllib.error.URLError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] schannel: CRYPT_E_REVOCATION_OFFLINE (0x80092013)"
    )
    calls, res = _attempt(exc, tmp_path, retries=3)
    assert calls == 1, calls
    assert "tls_cert" in str(res.error), res.error


def test_a_tls_handshake_timeout_is_retried_at_most_once(tmp_path) -> None:
    """TLS 握手超时 ⇒ 至多两次（记 `tls_timeout`），不是 `retries` 次。"""
    exc = urllib.error.URLError(OSError("_ssl.c:985: The handshake operation timed out"))
    calls, res = _attempt(exc, tmp_path, retries=3)
    assert calls == 2, f"TLS 握手超时试了 {calls} 次（至多允许 2 次）"
    assert res.ok is False and "tls_timeout" in str(res.error), res


def test_an_ordinary_network_error_still_retries_the_configured_times(tmp_path) -> None:
    """负控：普通网络异常（连接被重置）照旧重试满 `retries` 次 —— 别把这一支改窄了。"""
    exc = urllib.error.URLError(ConnectionResetError("connection reset by peer"))
    calls, res = _attempt(exc, tmp_path, retries=3)
    assert calls == 4, f"普通网络异常应当试 1+3=4 次，实际 {calls}"
    assert res.ok is False and "network_error" in str(res.error), res
