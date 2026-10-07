"""打印十格摘要（临时，用完即删）。口径与 tests/test_agent_prompts.py 的 registry fixture 相同。"""

from __future__ import annotations

import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")
sys.path.insert(0, r"D:\Incubator\agentflow\tests")

from agentflow.tools import build_registry  # noqa: E402
from test_agent_prompts import ALL_ROLES, _surface_digest  # noqa: E402

registry = build_registry().registry
live = {role: _surface_digest(role, registry) for role in ALL_ROLES}
print("===BEGIN===")
for role in ALL_ROLES:
    print(f'    "{role}": "{live[role]}",')
print("===END===")
