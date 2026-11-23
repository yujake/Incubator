"""角色 D 的动作 `trace_l3`：按需下钻到文献（元数据 + 本地文件 + 正文是否可得）。

一动作一文件；判据 `tests/test_agent_split_is_one_action_one_file.py`。
"""
from __future__ import annotations

from collections.abc import Mapping

from ._support import Sequence


def _l3_found(data: Mapping) -> tuple[bool, str]:
    """这条 L3 下钻到底"找到了没有"：返回 ``(found, why)``。

    口径按 ``trace.literature`` 的实际返回键判，不给工具加未声明的 ``found``：

    * ``text`` 去掉首尾空白后非空 ⇒ ``found=True``、``why=""`` —— 这一条真的拿到了
      可核对的正文片段，而"正文片段"正是 L3 区别于 L1/L2（只给表述/元数据）的那一格。
    * ``text`` 为空 ⇒ ``found=False``，``why`` 说清是哪一档：优先抄工具自带的
      ``note``（``no_path`` / ``path_rejected`` / ``file_missing`` / ``not_a_file`` /
      ``extract_module_missing`` / ``extract_failed`` / ``no_text_layer`` 各有原话）；
      降级替身（``_local_literature``：只有元数据、``text_available=False``）与
      "文献表里没有这一条"也各自说清。

    为什么不用 ``file_exists`` 或 ``literature.in_table`` 判：那两格说的是"元数据查到了"，
    不是"正文读到了"。扫描版 PDF（``no_text_layer``）与文件丢失都满足前者，而它们
    恰恰是 D 不该在报告里写成"已核对引文语境"的那两档。
    """
    text = data.get("text")
    if isinstance(text, str) and text.strip():
        return True, ""
    note = str(data.get("note") or "").strip()
    if note:
        return False, note
    if isinstance(data.get("literature"), Mapping):
        return False, (
            f"status={data.get('status')!r}，本次没有正文片段"
            f"（chars_returned={data.get('chars_returned')!r}）"
        )
    if data.get("found") is False:
        return False, f"文献表里没有 {data.get('lit_id')}：trace.literature 与本地兜底都没查到"
    return False, "trace.literature 不可用，本地兜底只有元数据、没有正文（L3 未读到正文）"


class _TraceL3:
    def trace_l3(self, evidence: dict, lit_ids: Sequence[str] | None = None) -> dict:
        """按需 L3：下钻到文献（元数据 + 本地文件 + 正文是否可得）。

        刻意只取"事实"（文件是否存在、是否 processed），不在这里做 OCR 或
        正文抽取：那是 B/K 的职责，D 下钻正文的目的是"核对引文语境"，
        必须由专门的工具返回带页码的片段。``found`` 只按"这次真的拿到了正文片段"
        （``trace.literature`` 的 ``text`` 非空）算：工具缺失、正文没有文本层、文件丢失
        都如实写 ``found=False`` 并用 ``why`` 说清是哪一档 —— "没做"和"做了但没结果"
        是两件事。
        """
        want = list(lit_ids or [])
        if not want:
            # 只收 Mapping 元素（str 上 `.get` 会抛 AttributeError）。
            want = [str(c.get("lit_id")) for c in evidence.get("claims") or []
                    if isinstance(c, Mapping) and c.get("lit_id")]
        want = sorted(set(want))[: self.max_l3_lits]
        out: list[dict] = []
        for lid in want:
            data = self._trace_one("trace.literature", lit_id=lid)
            source = "external"
            if data is None:
                data = self._local_literature(lid)
                source = "fallback"
            if not data:
                data = {"found": False, "lit_id": lid}
            entry = dict(data)
            entry["lit_id"] = lid
            entry.setdefault("source", source)
            out.append(entry)
            found, why = _l3_found(data)
            evidence.setdefault("traces", []).append(
                {"level": "L3", "tool": "trace.literature", "lit_id": lid,
                 "found": found, "why": why}
            )
        evidence["l3"] = out
        return evidence
