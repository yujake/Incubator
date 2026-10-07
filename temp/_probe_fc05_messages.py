"""量 `test_fc05_contract::test_eval_requires_every_scope_field` 那条失败该怎么修（只读）。

现状：测试对每个必填口径字段断言 `ValueError` 的消息里含「口径」二字；
而实现给的是**字段级**消息（例：`k 不能为空（pass@k 的 k 必填，见 EVAL_REQUIRED_FIELDS）`）。

**为什么不能直接把测试放宽**（那是"为迁就实现改判据"）：先量一件事 ——
**每个字段的消息是否都点名了它自己**。若都点名了，那么判据可以从"含口径二字"
**改成"必须点名缺的是哪个字段"**，这是**更强**的判据（它把消息与被测字段绑起来），
而且能同时满足两边。若有的字段没点名 ⇒ 那是实现的消息缺陷，如实报（不许改测试迁就）。

用法：`python D:\\Incubator\\temp\\_probe_fc05_messages.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"D:\Incubator\agentflow\src")))

from agentflow import schema as S     # noqa: E402

TS = "2026-01-01T00:00:00+00:00"


def main() -> int:
    named = 0
    unnamed = []
    print(f"EVAL_REQUIRED_FIELDS = {S.EVAL_REQUIRED_FIELDS}")
    for missing in S.EVAL_REQUIRED_FIELDS:
        kw = dict(eval_id="0000", claim_key="K", benchmark="b", benchmark_version="v",
                  split="test", k=1, value=0.5, decontamination="none", date="d",
                  source="s", created_at=TS)
        kw[missing] = ""
        try:
            S.EvalResult(**kw).validate()
        except ValueError as exc:
            msg = str(exc)
        except Exception as exc:                       # noqa: BLE001
            msg = f"（非 ValueError：{type(exc).__name__}: {exc}）"
        else:
            msg = "（**没有抛**）"
        has_field = str(missing) in msg
        has_kj = "口径" in msg
        named += bool(has_field)
        if not has_field:
            unnamed.append(missing)
        print(f"  缺 {missing:<16} 点名={'是' if has_field else '**否**'} "
              f"含口径={'是' if has_kj else '否'}  消息={msg[:80]}")

    print(f"\n点名了自己字段的：{named}/{len(S.EVAL_REQUIRED_FIELDS)}")
    print(f"**没点名**的：{unnamed or '无'}")
    if unnamed:
        print("⇒ 判定：实现的消息对被名字段不够，**不许**改测试迁就；这属于实现（`schema.py` 禁改区）的缺陷，"
              "要么如实登记，要么把它作为一条需要人签的改动。")
    else:
        print("⇒ 判定：可以把判据从「含『口径』二字」**改成「必须点名缺的是哪个字段」**——"
              "这是**更强**的判据（把消息与被测字段绑定），且两边都满足。"
              "**这不算放宽**：改前只要句子里有『口径』二字就能过，改后必须写对字段名。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
