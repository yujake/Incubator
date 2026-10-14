#!/usr/bin/env python
"""把剩下几处"4 位十进制"的**活措辞**改成随宽度走（含工具参数说明）。

工具参数说明会进工具面（`tests/golden/tool_surface_snapshot.json`）与动作面
（`specs/*.py` 的 description → 智能体面快照），所以这两份快照要跟着重冻。
"""
from __future__ import annotations

import pathlib

SRC = pathlib.Path(r"D:\Incubator\agentflow\src\agentflow")

EDITS = [
    ("tools/research_tools.py",
     'return fail(f"question_id 必须是 4 位十进制字符串，收到 {question_id!r}", kind="bad_id")',
     'return fail(f"question_id 必须是 {S.ID_DIGITS} 位十进制字符串'
     '（旧数据里的 4 位号仍可读），收到 {question_id!r}", kind="bad_id")'),
    ("tools/verify_tools.py",
     '"description": "命题号（4 位十进制，与 statements.stmt_id 同一套）",',
     '"description": f"命题号（{S.ID_DIGITS} 位十进制，与 statements.stmt_id 同一套；'
     '旧数据里的 4 位号仍可读）",'),
    ("tools/verify_tools.py",
     '"description": "命题号（4 位十进制）",',
     '"description": f"命题号（{S.ID_DIGITS} 位十进制）",'),
    ("tools/trace_tools.py",
     'hint="关系代号是 4 位十进制字符串；可用 graph.relations_between 先确认代号。",',
     'hint=f"关系代号是 {S.ID_DIGITS} 位十进制字符串'
     '（旧数据里的 4 位号仍可读）；可用 graph.relations_between 先确认代号。",'),
    ("tools/doc_tools.py",
     "#: 裸号（4 位十进制、没有前缀）在这张表里不认。",
     "#: 裸号（不带前缀的编号）在这张表里不认。"),
    ("agent_b/register_statement.py",
     "        # 定义（4 位十进制），这里在写库前用同一个谓词核，拒绝时带上 `kind` ——",
     "        # 定义（当前宽度六位；旧四位读侧兼容），这里在写库前用同一个谓词核，拒绝时带上 `kind` ——"),
    ("schema.py",
     '- 所有 ID 是 4 位十进制字符串（"0000"…"9999"），不用 int，避免前导零在序列化时丢失。',
     '- 所有 ID 是不带前导零丢失风险的十进制字符串（当前宽度六位 "000000"…"999999"；\n'
     '  旧数据里的四位号按读侧兼容照样读得进来），不用 int，避免前导零在序列化时丢失。'),
    ("schema.py",
     '    task_id: str  # "t-NNNN"（过程记录，不占 4 位编号空间）',
     '    task_id: str  # "t-NNNNNN"（过程记录，不占编号空间）'),
    ("schema.py",
     '#: 4 位 ID 分配器覆盖的表（search_requests 用 r-NNNN，reprocess_requests 用 p-NNNN，',
     '#: 编号空间计数器覆盖的表（search_requests 用 r-NNNNNN，reprocess_requests 用 p-NNNNNN，'),
    ("specs/b.py",
     '"**格式：4 位十进制字符串（如 \\"0000\\"）** —— 写成 \\"doc:0000\\" 会被拒"',
     'f"**格式：{S.ID_DIGITS} 位十进制字符串（如 \\"{S.format_id(0)}\\"；'
     '旧数据里的 4 位号仍可读）** —— 写成 \\"doc:0000\\" 会被拒"'),
    ("specs/b.py",
     '"+ `page_range`；own_result 要 `doc_id`（4 位十进制）或 `line_range`。"',
     '"+ `page_range`；own_result 要 `doc_id`（六位十进制编号）或 `line_range`。"'),
]


def main() -> int:
    misses: list[str] = []
    for rel, old, new in EDITS:
        p = SRC / rel
        text = p.read_text(encoding="utf-8")
        if old not in text:
            misses.append(f"{rel}: 找不到 {old[:60]!r}")
            continue
        p.write_text(text.replace(old, new), encoding="utf-8", newline="")
        print(f"[ok] {rel}: {old[:46]}…")
    for m in misses:
        print("[miss]", m)
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
