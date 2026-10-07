#!/usr/bin/env python
"""重算 `tests/test_agent_prompts.py` 那张冻结摘要表（改段之后同轮更新用）。

用法（工作目录 `agentflow/`）：

    python -B temp/recompute_prompt_digests.py

它逐字复用那个测试文件的口径（同一个归一化：把「提示词版本」那一行换成
`<PROMPT_VERSION>`；同一个工具链夹具），所以输出可以直接抄进
`_FROZEN_PROMPT_DIGESTS` 与 `_FROZEN_PROMPT_VERSION`。

这不是判据：它是维护那张表用的计算器（谁改段谁跑它）。
"""

from __future__ import annotations

import hashlib
import re
import sys

sys.path.insert(0, "tests")  # 复用测试文件里的口径，不另抄一份

from agentflow import agent_prompts as AP  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

FIXTURE_TOOLCHAIN = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
                     "- 检查器：（判据夹具，与机器无关）")
VERSION_LINE = re.compile(r"(?m)^- 提示词版本：.*$")


def main() -> int:
    registry = build_registry().registry
    roles = tuple(S.ROLES) + (S.CONDUCTOR_ROLE,)
    out: dict[str, str] = {}
    for role in roles:
        text = AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                                workspace_root="D:/x", toolchain_facts=FIXTURE_TOOLCHAIN)
        normalized, hits = VERSION_LINE.subn("- 提示词版本：<PROMPT_VERSION>", text)
        assert hits == 1, (role, hits)
        out[role] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    print(f'_FROZEN_PROMPT_VERSION = "{AP.PROMPT_VERSION}"')
    print("_FROZEN_PROMPT_DIGESTS: dict[str, str] = {")
    for role in sorted(out):
        print(f'    "{role}": "{out[role]}",')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
