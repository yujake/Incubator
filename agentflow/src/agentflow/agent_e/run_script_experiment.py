"""角色 E 的动作 `run_script_experiment`（`goal-7f5116c1` M6：从 `agent_e.py` 拆出来，逐字未改）。

拆出来的判据：这个方法的源码非空行与拆分前逐字相同（`temp/_m6_verify_verbatim.py`）。
"""
from __future__ import annotations

from ._support import Any

class _RunScriptExperiment:
    def run_script_experiment(self, claim: str, claim_key: str, script_path: str, **kw: Any) -> dict:
        """`run_experiment` 的别名（保留给"读起来更顺"的调用点）。"""
        return self.run_experiment(claim, claim_key, script_path, **kw)
