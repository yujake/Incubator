"""G3 补充量法（二）：校验剩下几个数。"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "agentflow"
OUT = Path(__file__).resolve().parent / "G3-measure2.txt"
lines: list[str] = []


def say(s: str = "") -> None:
    lines.append(s)


def run(args, cwd=REPO, timeout=300):
    p = subprocess.run([sys.executable, *args], cwd=str(cwd), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, p.stdout + p.stderr


say(f"scripts_star_py      = {len(list((REPO / 'scripts').glob('*.py')))}  {sorted(p.name for p in (REPO / 'scripts').glob('*.py'))}")
say(f"docs_all_files       = {len([p for p in (REPO / 'docs').iterdir() if p.is_file()])}")

rs = (REPO / "docs" / "ROLE-SPECS.md").read_text(encoding="utf-8")
sec = re.findall(r"^####\s+([A-Z])\.(\d+)", rs, re.M)
say(f"role_specs_X_N_rows  = {len(sec)}  (角色节 {sorted({a for a, _ in sec})})")

rc, out = run([str(REPO / "tools" / "verify_role_specs.py")])
say(f"verify_role_specs    exit={rc}")
say("  " + out.strip().replace("\n", "\n  ")[:1500])

# 台账 vs 清单：哪些清单路径没有台账条目
led = json.loads((REPO / ".noai-approvals.json").read_text(encoding="utf-8"))
entries = led["entries"] if isinstance(led, dict) else led
led_paths = {e.get("path") for e in entries}
man = (REPO / ".noai-paths").read_text(encoding="utf-8")
man_paths = {l.split()[0] for l in man.splitlines() if re.match(r"^\S+\s+\[category:", l)}
say(f"manifest_unique={len(man_paths)} ledger_entries={len(entries)} ledger_paths_unique={len(led_paths)}")
say(f"manifest_not_in_ledger = {sorted(man_paths - led_paths)}")
say(f"ledger_not_in_manifest = {sorted(led_paths - man_paths)}")
say(f"ledger entry keys sample = {sorted(entries[0].keys())}")
say(f"ledger reviewers per entry = {Counter(len(e.get('reviewers', [])) for e in entries)}")

# 55 口径（含 store）的分布
sys.path.insert(0, str(REPO / "src"))
import tempfile  # noqa: E402
import agentflow.store as ST  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="g3store-"))
try:
    st = ST.Store(tmp)
    reg = build_registry(store=st, workspace_root=REPO).registry
    names = reg.names()
    se = Counter(reg.get(n).side_effect for n in names)
    ex = Counter(reg.get(n).declared_external for n in names)
    ne = sum(1 for n in names if reg.get(n).needs_approval)
    say(f"registry[store] total={len(names)} side_effect={dict(se)} external={dict(ex)} needs_approval={ne}")
except Exception as e:  # noqa: BLE001
    say(f"registry[store] FAILED: {type(e).__name__}: {e}")

# cancellation.py 的"4 条规则"来源
canc = (REPO / "src" / "agentflow" / "cancellation.py").read_text(encoding="utf-8")
m = re.search(r"CANCEL_CODES\s*=\s*\(([^)]*)\)", canc, re.S)
say(f"CANCEL_CODES = {m.group(1).strip() if m else '?'}")
_cc = len(re.findall(r'"[a-z_]+"', m.group(1))) if m else "?"
say(f"CANCEL_CODES count = {_cc}")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
