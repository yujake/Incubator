# -*- coding: utf-8 -*-
"""规范 JSON 字节串 —— 唯一实现（依据 `draft/28` §143.6 的 R-33）。

## 这一层解决什么

"把一份结构化的东西序列化成规范字节串再取 sha256"这件事在本仓有多处需要：

- `signatures`：稿件内容的规范哈希（`content_sha256_of`）与 `claims_hash_of`；
- `scripts/noai_gate.py`：批准台账回执的自身哈希（`_receipt_digest`，回执链就钉在它上面）。

R-33 记的正是"两处各写一份"：口径只要差一个字符（分隔符、是否 `ensure_ascii`、
键序），同一份内容就会算出两个哈希 —— 而那种偏差不会报错：两个地方各自自洽，
只有跨过去比对（"这条回执钉的哈希对不对得上 `signatures` 算的那一版"）才会暴露。

## 为什么门最终没有改成 import 本模块（第一版方案被负控推翻）

`R-33` 的第一版是"让门按文件路径加载本模块"，理由是"门必须能在本包 import 不了时也能跑"。
它当场被负控推翻：`tests/test_noai_gate_record_audit_cli.py` 的两条负控把门脚本单独复制
到一个临时目录、注入一处缺陷，证明回执链核对会红 —— 而副本旁边没有本模块 ⇒ 门跑不起来、
那两条判据无处安放。门要的是"能被单独复制并在任何位置运行"，比"不 import 本包"更强。

所以最终口径是：包里这一份是唯一的实现（`signatures` 用它）；门保留自己的字节，
并由 `noai_gate.py --check-canonical` 把两者钉在一起（同一载荷两侧哈希必须逐字相等，
否则 `divergent(1)`）。真正被禁掉的是"没人看着的第二份口径"，不是第二份字节。

## 为什么单开一个模块，而不是放进 `signatures`

`scripts/noai_gate.py` 是门，它有一条硬约束（见该文件与 `vocab_census` 的同类注释）：
必须在本包 import 不了时也能跑 —— 门不能依赖被它审计的那棵树的 import 图。
所以它不能 `import agentflow.signatures`；它按文件路径加载本模块
（纯标准库、无包内依赖），从而"同一份实现"与"门可独立运行"两件事同时成立。

## 口径（改动它 = 改动所有已落盘的哈希）

```python
json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
```

`sort_keys` 让键序不参与哈希；`ensure_ascii=False` 让中文原样进字节（本仓的台账与
稿件里大量中文，转义与否必须定死一处）；`separators` 去掉所有可省的空白。
这三项一个都不能改：改了就等于说"盘上所有历史哈希都不再成立"。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: 规范化参数（见模块 docstring 的"口径"一节）。放在这里是为了让"改口径"这件事
#: 至少要动到本模块，而不是散落在某个调用点的字面量里。
CANONICAL_SEPARATORS: tuple[str, str] = (",", ":")


def canonical_json_text(obj: Any) -> str:
    """规范 JSON 文本（键排序、无多余空白、非 ASCII 原样）。

    ⚠️ 2026-10-17（真机 `t1r`：`TypeError: Object of type TopicalityReport is not
    JSON serializable`）：**加 `default=str` 当最后的兜底**。它**不改变任何已有哈希** ——
    带非 JSON 值的载荷此前**根本算不出哈希**（直接抛），所以盘上不存在"用别的字节算出来的"历史。
    这一档正是 `conductor._structured_payload` 的 docstring 里承诺过的那条兜底。
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=CANONICAL_SEPARATORS, default=str)


def canonical_json_bytes(obj: Any) -> bytes:
    """规范 JSON 的 UTF-8 字节串（哈希的输入就是它）。"""
    return canonical_json_text(obj).encode("utf-8")


def canonical_sha256(obj: Any) -> str:
    """规范字节串的 sha256（小写十六进制，64 位）。"""
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


#: 用于一致性自检的探针载荷：覆盖中文、嵌套、列表、数字与布尔 ——
#: 这几样正是"转义/键序/空白"三种偏差会露出来的地方。
PROBE_PAYLOAD: dict[str, Any] = {
    "b": [1, 2, {"nested": True}],
    "a": "中文与 ASCII 混排",
    "c": 3.5,
}


def selftest() -> int:
    """就地自检：探针哈希稳定 + 参数确实是那一组。"""
    ok = True

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" —— {detail}" if detail else ""))
        ok = ok and cond

    text = canonical_json_text(PROBE_PAYLOAD)
    check("键排序生效", text.startswith('{"a":'), text[:40])
    # 只查分隔符后没有空白：探针的取值里就有空格（"中文与 ASCII 混排"），
    # 第一版写成 `" " not in text` ⇒ 把取值里的空格当成了格式问题（夹具不干净）。
    check("分隔符后无多余空白", ", " not in text and ": " not in text and "\n" not in text, text)
    check("中文未转义", "中文" in text, text[:60])
    check("哈希稳定（同输入同输出）",
          canonical_sha256(PROBE_PAYLOAD) == canonical_sha256(dict(PROBE_PAYLOAD)),
          canonical_sha256(PROBE_PAYLOAD)[:16])
    check("键序不参与哈希", canonical_sha256({"x": 1, "y": 2}) == canonical_sha256({"y": 2, "x": 1}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
