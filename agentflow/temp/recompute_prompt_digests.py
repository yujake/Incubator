#!/usr/bin/env python
"""重算 `tests/test_agent_prompts.py` 那张冻结摘要表（改段之后同轮更新用）。

用法（工作目录 `agentflow/`，`PYTHONPATH=src`）：

    python -B temp/recompute_prompt_digests.py

它不另写一份口径：三件夹具与归一化都从那个测试文件导入
（`_SURFACE_FIXTURE_TOOLCHAIN` / `_SURFACE_FIXTURE_FORMAL` / `_SURFACE_FIXTURE_LIMITS`
与 `_surface_digest`），所以输出可以直接抄进 `_FROZEN_PROMPT_DIGESTS` 与
`_FROZEN_PROMPT_VERSION`。

为什么改成"从测试文件导入"（2026-10-11，批 R1 的工具债）：这一版此前自己抄了一份夹具
（只有一个 `FIXTURE_TOOLCHAIN`，少了 `_SURFACE_FIXTURE_FORMAL` 与
`_SURFACE_FIXTURE_LIMITS`）⇒ 它打出来的十格里九格与判据对不上，只有不含那两段的 C
偶然一致。照它抄摘要就是编读数（本仓已经栽过一次同类：从一个截断的前缀里抄了一个
摘要）。口径只许有一处，抄一份必然漂。

这不是判据：它是维护那张表用的计算器（谁改段谁跑它）。
"""

from __future__ import annotations

import os
import sys

#: 先钉开关，再导入 agentflow（2026-10-13 实测踩到的坑）。
#:
#: `tests/conftest.py` 在导入期就把 `AGENTFLOW_LEAN_ENABLED` 钉成 "1"（它还要钉设置文件
#: 与几个 *_BIN 环境变量），而 D/E/F 三格的提示词摘要**对 Lean 开关敏感**。少了这一行，
#: 在开发壳里跑这个计算器会算出与判据不同的那一组 D/E/F（实测 da82… 对 814e…），
#: 而照着抄进冻结表就会让 `test_the_prompt_version_moves_with_the_sections` 红，
#: 读的人还会以为"段动了"。口径只许有一处：这里复现判据那一套环境，而不是另写一份。
os.environ.setdefault("AGENTFLOW_LEAN_ENABLED", "1")

sys.path.insert(0, "tests")  # 复用测试文件里的口径，不另抄一份

import test_agent_prompts as T  # noqa: E402

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402


def main() -> int:
    registry = build_registry().registry
    digests = {role: T._surface_digest(role, registry) for role in T.ALL_ROLES}
    print(f'_FROZEN_PROMPT_VERSION = "{AP.PROMPT_VERSION}"')
    print("_FROZEN_PROMPT_DIGESTS: dict[str, str] = {")
    for role in sorted(digests):
        print(f'    "{role}": "{digests[role]}",')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
