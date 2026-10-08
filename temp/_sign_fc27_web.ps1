# =============================================================================
# temp/_sign_fc27_web.ps1 —— FC-27 批量签（Web 批那 3 条）
#
# 给**人**用的脚本（所有者）。它做三件事，顺序不能换：
#   ① 登记：`--baseline --paths <路径> --note ...`（刷新 sha256；**永远不写 reviewers**）
#   ② 批准：`--approve <路径> --reviewer <名字> --scope ... --note ...`（每条 ×2 名**不同**的 reviewer）
#   ③ 复核：`--git --since <基线> --check-approvals`（**必须带基线**，否则门看不见已提交的改动）
#
# 用法（在 D:\Incubator 下）：
#   pwsh -File temp\_sign_fc27_web.ps1 -ReviewerA "张三" -ReviewerB "李四"
#   pwsh -File temp\_sign_fc27_web.ps1 -ReviewerA "张三" -ReviewerB "李四" -WhatIfOnly
#
# 参数：
#   -ReviewerA / -ReviewerB  两名**互相独立**的走查人姓名（必填；两者必须不同 —— 门按"不同姓名"计）
#   -Since                   复核基线（默认 5c6e441，= 本轮 Web 批的起点；换了起点就换它）
#   -WhatIfOnly              只打印将要执行的命令，**一条都不跑**（先看一遍再决定）
#
# 这个脚本**不会**替你走查：每一条的 `--scope` 写的是"该看哪几行/哪几个符号"，
# 跑之前请对着 `draft/67 §3b` 与 `draft/77 §2` 真的看过（门只保证"有人签了"，不保证"签得对"）。
#
# 它写的是 `agentflow/.noai-approvals.json` —— 那个文件**本身就在禁改区清单里**
# （`[category: auth-audit]`），所以这一步必须由人跑；AI 不代跑（见 `draft/67 §4b` 末段）。
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ReviewerA,
    [Parameter(Mandatory = $true)][string]$ReviewerB,
    [string]$Since = "5c6e441",
    [switch]$WhatIfOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PYTHONDONTWRITEBYTECODE = "1"

# 仓库根：本脚本在 temp/ 下 ⇒ 上一级就是根
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not (Test-Path (Join-Path $Root "agentflow\scripts\noai_gate.py"))) {
    throw "找不到 agentflow\scripts\noai_gate.py —— 本脚本要在仓库根的 temp\ 下（当前推到 $Root）"
}
$Gate = Join-Path $Root "agentflow\scripts\noai_gate.py"

if ([string]::IsNullOrWhiteSpace($ReviewerA) -or [string]::IsNullOrWhiteSpace($ReviewerB)) {
    throw "两个 reviewer 姓名都要给（门按'不同姓名'计批准数）"
}
if ($ReviewerA -eq $ReviewerB) {
    throw "两名 reviewer 不能同名（$ReviewerA）—— 1 名 reviewer 与'作者自己再看一遍'在结构上无法区分"
}

# 三条待签项：路径 + 登记说明 + 两条走查 scope/note
# （逐条与 `draft/67 §3b` 的表一一对应；改这里等于改走查口径，请同步那一页）
$Items = @(
    @{
        Path  = "pyproject.toml"
        Note  = "Web 批 W1：browser 可选依赖 + marker + addopts 默认排除（draft/77 2.2 / draft/79 T1）"
        Scope = "optional-dependencies.browser / markers 的 browser 行 / addopts 三处"
        Says  = @(
            "逐行走查：三条都在 draft/77 2.2 的范围内；addopts 动既有行是 T1 裁定的直接后果",
            "独立复核：运行期依赖仍只有 filelock；marker 描述里'未装就是 unknown 不是 pass'仍在"
        )
    },
    @{
        Path  = "tools/release_all.py"
        Note  = "Web 批 W2：第 7 步 frontend（exit_map=TRI_STATE_EXIT）；既有 6 步与 overall() 语义未动"
        Scope = "build_steps() 第 7 个 Step 与它的 exit_map；overall() 未改"
        Says  = @(
            "逐行走查：新步的 2 必须记 unknown 而不是 fail（漏了 exit_map 就会把没查成读成发现问题）",
            "独立复核：跳过的步骤仍记 unknown；既有 6 步一个字没动"
        )
    },
    @{
        Path  = "tools/run_each_test_file.py"
        Note  = "Web 批 W3：EXEMPT_ALL_SKIPPED 加 tests/test_webui_browser.py + 上限 1->2（同构于 test_providers_online.py）"
        Scope = "EXEMPT_ALL_SKIPPED 的新增条目、MAX_EXEMPT_ALL_SKIPPED、audit_exemptions() 的实现"
        Says  = @(
            "逐行走查：与 test_providers_online.py 同构（整文件被默认筛掉 + 未装依赖即 skip），audit_exemptions() 三道机器判据仍过",
            "独立复核：抬上限不放松判定语义 —— 名单外一律 unknown，3 条仍然红"
        )
    }
)

function Invoke-Gate {
    param([string[]]$GateArgs, [string]$What)
    $shown = "python -B `"$Gate`" " + ($GateArgs -join " ")
    if ($WhatIfOnly) {
        Write-Host "  [WhatIf] $shown" -ForegroundColor DarkGray
        return $true
    }
    Write-Host "  -> $shown" -ForegroundColor DarkGray
    & python -B $Gate @GateArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  !! $What 失败（退出码 $LASTEXITCODE）—— 停下来，后面的不跑了" -ForegroundColor Red
        return $false
    }
    return $true
}

Write-Host "=== FC-27 批量签（Web 批 3 条）===" -ForegroundColor Cyan
Write-Host "  仓库根 : $Root"
Write-Host "  reviewer: $ReviewerA / $ReviewerB"
Write-Host "  复核基线: $Since"
if ($WhatIfOnly) { Write-Host "  （-WhatIfOnly：只打印，不执行）" -ForegroundColor Yellow }

Write-Host "`n[①] 登记（刷新 sha；不写 reviewers）" -ForegroundColor Cyan
foreach ($it in $Items) {
    $ok = Invoke-Gate -What "登记 $($it.Path)" -GateArgs @(
        "--baseline", "--paths", $it.Path, "--note", $it.Note)
    if (-not $ok) { exit 1 }
}

Write-Host "`n[②] 批准（每条 ×2 名不同 reviewer）" -ForegroundColor Cyan
foreach ($it in $Items) {
    $names = @($ReviewerA, $ReviewerB)
    for ($i = 0; $i -lt 2; $i++) {
        $ok = Invoke-Gate -What "批准 $($it.Path)（$($names[$i])）" -GateArgs @(
            "--approve", $it.Path, "--reviewer", $names[$i],
            "--scope", $it.Scope, "--note", $it.Says[$i])
        if (-not $ok) { exit 1 }
    }
}

Write-Host "`n[③] 复核（必须带基线）" -ForegroundColor Cyan
if ($WhatIfOnly) {
    Write-Host "  [WhatIf] python -B `"$Gate`" --git --since $Since --check-approvals" -ForegroundColor DarkGray
    Write-Host "`n（-WhatIfOnly 结束；确认无误后去掉它再跑一次）" -ForegroundColor Yellow
    exit 0
}
& python -B $Gate --git --since $Since --check-approvals | Tee-Object -Variable verifyOut
$verifyText = ($verifyOut | Out-String)

Write-Host "`n=== 结论 ===" -ForegroundColor Cyan
foreach ($it in $Items) {
    $line = ($verifyText -split "`n" | Where-Object { $_ -match [regex]::Escape($it.Path) -and $_ -match "\[approved\]|\[unapproved\]" } | Select-Object -First 1)
    if ($line) { Write-Host ("  {0,-32} {1}" -f $it.Path, $line.Trim()) }
    else { Write-Host ("  {0,-32} （复核输出里没读到它的状态，请人眼过一遍上面那段）" -f $it.Path) -ForegroundColor Yellow }
}
if ($verifyText -match "命中 (\d+) 条禁改区路径，其中 \*\*(\d+) 条未获批准") {
    Write-Host ("`n  仍待处理：{0} 条（其中 `temp/tools/coverage_zero_test.py` 是刻意不入库的演示物假阳性、不用审）" -f $Matches[2])
}
Write-Host "`n签完把这一段回给主控（AI），它按 draft/81 11 跑推送前普查并放行。" -ForegroundColor Green
