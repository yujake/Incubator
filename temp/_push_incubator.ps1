# =============================================================================
# temp/_push_incubator.ps1 —— 把本仓库推到 GitHub（**请在你的终端里跑**）
#
# 为什么必须你来跑：`git push` 需要 GitHub 认证，而本机用的是
# Git Credential Manager（`credential.helper = manager`）—— 它会弹一个浏览器/对话框让你登录。
# AI 所在的受限环境里那个助手起不来（实测 `sh.exe: couldn't create signal pipe`），
# 所以这一步只能由有交互会话的人跑。
#
# 用法（先建好仓库，再跑；仓库名与工作区同名 = Incubator）：
#   1) 浏览器打开  https://github.com/new?name=Incubator   建一个空仓库（建议先 Private，别勾 README/.gitignore）
#   2) 在你的 PowerShell 里跑：
#        pwsh -NoProfile -File "D:\Incubator\temp\_push_incubator.ps1" -User <你的GitHub用户名>
#      只体检+探远端（**不动 remote**）：加 -ProbeOnly
#      只检查不推送（会配好 remote）：加 -NoPush
#      仓库不是空的时候（例如你建仓时勾了 README）：加 -Pull 先合并远端初始提交
#
# 它做四件事：① 体检（工作树/分支/规模）② 探远端（仓库在不在、通不通）
#             ③ 配 remote 并 push ④ 推完对账（远端 sha == 本地 HEAD）
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$User,
    [string]$Repo = "Incubator",
    [switch]$NoPush,
    [switch]$Pull,
    [switch]$ProbeOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Say([string]$m, [string]$color = "Gray") { Write-Host $m -ForegroundColor $color }

if (-not (Test-Path (Join-Path $Root ".git"))) { throw "这里不是仓库根：$Root" }
if ($Repo -ne "Incubator") { Say "  注意：仓库名不是 Incubator（当前 '$Repo'）—— 你说过要跟工作区同名。" "Yellow" }

Say "=== ① 体检 ===" "Cyan"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
$head = (git rev-parse HEAD).Trim()
$count = (git rev-list --count HEAD).Trim()
$files = git ls-files
$sum = ($files | ForEach-Object { if (Test-Path $_) { (Get-Item $_).Length } } | Measure-Object -Sum).Sum
Say "  分支      : $branch"
Say "  HEAD      : $head（$count 个提交）"
Say "  受跟踪面  : $($files.Count) 文件 / $([math]::Round($sum/1MB,2)) MB"
$dirty = git status --porcelain
$expect = @("?? agentflow/temp/c-oldrun.py", "?? agentflow/temp/c-r04-old-probe.py", "?? agentflow/temp/tools/")
$extra = $dirty | Where-Object { $_ -and ($expect -notcontains $_) }
if ($dirty) { Say "  未跟踪/未提交："; $dirty | ForEach-Object { Say "    $_" } }
if ($extra) { Say "  !! 除了那 3 条刻意不入库的登记物之外还有别的改动 —— 先确认再推。" "Yellow" }

$url = "https://github.com/$User/$Repo.git"
Say "`n=== ② 探远端（$url）===" "Cyan"
Say "  说明：仓库不存在或没权限时，git 会要你输用户名/密码（在**你的**终端里能看到并输入）。" "DarkGray"
$probe = git ls-remote --heads $url 2>&1
$probeCode = $LASTEXITCODE
if ($probeCode -ne 0) {
    Say "  探不到（退出码 $probeCode）：$($probe -join ' | ')" "Red"
    Say "  两种可能，都要在你自己的终端里排除：" "Yellow"
    Say "    ① **仓库还没建** ⇒ 浏览器打开 https://github.com/new?name=$Repo 建一个空仓库（建议先 Private）"
    Say "    ② **没登录/没权限** ⇒ 在你的终端里跑一次 `git ls-remote $url`："
    Say "       它会弹出 Git Credential Manager 让你登录 GitHub；登录成功后重跑本脚本。"
    Say "  （注：AI 所在的受限环境里凭据助手起不来 —— 实测报 `sh.exe: couldn't create signal pipe`，"
    Say "   所以这一步只能由有交互会话的人跑。）" "DarkGray"
    exit 1
}
$remoteHeads = @($probe | Where-Object { $_ -match '\S' })
if ($remoteHeads.Count -eq 0) {
    Say "  远端是**空仓库**（没有分支）⇒ 直接推 master 即可。"
} else {
    Say "  远端已有 $($remoteHeads.Count) 个分支："
    $remoteHeads | Select-Object -First 5 | ForEach-Object { Say "    $_" }
    if (-not $Pull) {
        Say "  !! 远端不是空的。若那是建仓时自动生成的 README/初始提交，请加 -Pull 先合并；" "Yellow"
        Say "     否则直接 push 可能被拒（non-fast-forward）。" "Yellow"
    }
}

if ($ProbeOnly) {
    Say "`n（-ProbeOnly：只体检 + 探远端，**不改 remote、不推送**）" "Yellow"
    exit 0
}

Say "`n=== ③ 配 remote 并推送 ===" "Cyan"
$existing = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $existing) {
    if ($existing.Trim() -ne $url) {
        Say "  origin 原本是 $($existing.Trim()) ⇒ 改成 $url"
        git remote set-url origin $url
    } else { Say "  origin 已是 $url" }
} else {
    git remote add origin $url
    Say "  已添加 origin = $url"
}

if ($Pull) {
    Say "  git pull --rebase origin $branch ..."
    git pull --rebase origin $branch
    if ($LASTEXITCODE -ne 0) { Say "  !! pull --rebase 失败，先手工解决冲突再推。" "Red"; exit 1 }
}

if ($NoPush) {
    Say "  （-NoPush：只配好 remote，不推）" "Yellow"
} else {
    Say "  git push -u origin $branch ...（若弹出登录窗口，请在浏览器里授权）"
    git push -u origin $branch
    if ($LASTEXITCODE -ne 0) { Say "  !! push 失败（退出码 $LASTEXITCODE）—— 把上面的原文发给 AI。" "Red"; exit 1 }
}

Say "`n=== ④ 推完对账 ===" "Cyan"
$after = git ls-remote --heads $url 2>&1
$localHead = (git rev-parse HEAD).Trim()
$match = $after | Where-Object { $_ -match "$localHead\s+refs/heads/$branch$" }
if ($match) {
    Say "  ✓ 远端 refs/heads/$branch == 本地 HEAD（$localHead）"
    Say "  仓库地址：https://github.com/$User/$Repo"
} else {
    Say "  ? 没在远端读到与本地 HEAD 相同的 sha："
    $after | Select-Object -First 5 | ForEach-Object { Say "    $_" }
    Say "  （-NoPush 时这是正常的）" "DarkGray"
}
