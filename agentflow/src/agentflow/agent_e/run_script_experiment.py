"""角色 E 的动作 `run_script_experiment`。"""
from __future__ import annotations

from ._support import Any

class _RunScriptExperiment:
    def run_script_experiment(self, claim: str, claim_key: str, script_path: str, **kw: Any) -> dict:
        """`run_experiment` 的别名（保留给"读起来更顺"的调用点）。"""
        return self.run_experiment(claim, claim_key, script_path, **kw)
