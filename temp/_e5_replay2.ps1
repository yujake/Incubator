# E5 真机回放（R1 的验收）：D 的 `research` 里那次模型精修**真的发生**了吗
#
# 与离线证据的区别：A 的离线证据到"真 LlmSeam + 假 backend"为止；这一趟**真出网**。
# 走的是 `Conductor.summon("D","research")` ⇒ 经过 `LocalBackend.call`（召唤号 ContextVar 在那里 set）
#   ⇒ 于是三样一起被验：① 缝被真的问了一次 ② 读数三态 ③ 花销挂在**当次召唤的 task_id** 上。
#
# 纪律：① **复制**源工作区到 temp 下再跑（`research` 会写 evidence/落库 ⇒ 绝不碰真机数据）；
#       ② 预算 $0.20 上限；③ 三个读数都只读盘。
#
# 用法：pwsh -NoProfile -File D:\Incubator\temp\_e5_replay2.ps1 [-Src projects\p6c-research-from-zero] [-Qid 0000]

param([string]$Src = "projects\p6c-research-from-zero", [string]$Qid = "0000", [double]$Budget = 0.20)

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "D:\Incubator\agentflow\src"

cd D:\Incubator\agentflow

$cred = Get-Content "$env:USERPROFILE\.dsh\.credentials.yaml" -Raw
$m = [regex]::Match($cred, '(?m)^\s*DEEPSEEK_API_KEY:\s*["'']?([A-Za-z0-9\-_\.]+)')
if (-not $m.Success) { "拿不到 key ⇒ 停手"; exit 2 }
$env:AGENTFLOW_MODEL_API_KEY = $m.Groups[1].Value

$dst = "D:\Incubator\temp\zz-e5-replay"
if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
New-Item -ItemType Directory -Path $dst | Out-Null
Copy-Item -Recurse -Force "$Src\*" $dst
"源 = $Src （复制，不动源）"
"副本 = $dst"

python -B -c @"
import json, pathlib, sys
sys.stdout.reconfigure(encoding='utf-8')
from agentflow.store import Store
from agentflow import host

root = pathlib.Path(r'$dst')
st = Store(root)
built = host.wired_llm_conductor(st, config={}, workspace_root=root, session_root=root,
                                sid='e5r', usd_budget=$Budget)
cond = built['conductor']
res = cond.summon('D', 'research', {'qid': '$Qid'}, by='M')
payload = getattr(res, 'payload', None) or {}
print('  summon 结局 =', getattr(res, 'outcome', None), '| ok =', getattr(res, 'ok', None))
rd = payload.get('llm_reading') if isinstance(payload, dict) else None
print('  读数一（summon 返回值里的 llm_reading）=', json.dumps(rd, ensure_ascii=False)[:600] if rd else None)

p = root / 'data' / 'tasks.json'
rows = (json.loads(p.read_text(encoding='utf-8')).get('rows') or []) if p.is_file() else []
d = [r for r in rows if str(r.get('role')) == 'D']
print(f'  读数二（tasks 里 role=D 的行 {len(d)} 条）:')
for r in d[-3:]:
    pay = r.get('payload') or {}
    print('    ', r.get('task_id'), r.get('action'), r.get('status'),
          json.dumps((pay or {}).get('llm_reading'), ensure_ascii=False)[:300] if isinstance(pay, dict) else '')
    tp = root / 'out' / 'tasks' / (str(r.get('task_id')) + '.json')
    if tp.is_file():
        doc = json.loads(tp.read_text(encoding='utf-8'))
        print('        out/tasks 的 readings =', json.dumps(doc.get('readings'), ensure_ascii=False)[:400])
        print('        out/tasks 的 payload_keys 含 llm_reading =', 'llm_reading' in (doc.get('payload_keys') or []))

lp = root / 'data' / 'usage_ledger.json'
lrows = (json.loads(lp.read_text(encoding='utf-8')).get('rows') or []) if lp.is_file() else []
import collections
by = collections.Counter(str(r.get('task_id') or '(空)') for r in lrows)
usd = collections.defaultdict(float)
for r in lrows:
    try: usd[str(r.get('task_id') or '(空)')] += float(r.get('usd') or 0)
    except Exception: pass
print('  读数三（usage_ledger 按 task_id）：')
for k, c in by.items():
    print(f'    {k}: {c} 行, usd 合计={usd[k]:.6f}')
"@

"（完）源工作区一个字节没动；副本在 $dst"
