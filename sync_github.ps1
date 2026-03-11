param(
  [Parameter(Mandatory = $false)]
  [string]$RepoUrl,

  [Parameter(Mandatory = $false)]
  [string]$Branch
)

$ErrorActionPreference = "Stop"

function Exec([string]$cmd) {
  Write-Host ">> $cmd"
  & powershell -NoProfile -ExecutionPolicy Bypass -Command $cmd
  if ($LASTEXITCODE -ne 0) { throw "Command failed: $cmd" }
}

function Git([string]$args) {
  Write-Host ">> git $args"
  & git $args
  if ($LASTEXITCODE -ne 0) { throw "git failed: $args" }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "git 未安装或未加入 PATH。请先安装 Git。"
}

if (-not (Test-Path -LiteralPath ".git")) {
  throw "当前目录不是 Git 仓库（找不到 .git）。请在项目根目录运行。"
}

if (-not $Branch -or $Branch.Trim() -eq "") {
  $Branch = (git rev-parse --abbrev-ref HEAD).Trim()
  if (-not $Branch) { $Branch = "master" }
}

if (-not $RepoUrl -or $RepoUrl.Trim() -eq "") {
  $RepoUrl = $env:GITHUB_REPO_URL
}

$hasOrigin = $false
try {
  $originUrl = (git remote get-url origin 2>$null).Trim()
  if ($originUrl) { $hasOrigin = $true }
} catch { }

if (-not $hasOrigin) {
  if (-not $RepoUrl -or $RepoUrl.Trim() -eq "") {
    Write-Host ""
    Write-Host "未检测到 remote 'origin'。请提供仓库地址，例如："
    Write-Host "  https://github.com/icenorthe/zhongwangchong.git"
    Write-Host ""
    throw "用法：./sync_github.ps1 -RepoUrl <url>   或设置环境变量 GITHUB_REPO_URL"
  }
  Git "remote add origin `"$RepoUrl`""
}

Git "add -A"

$status = (git status --porcelain)
if ($status -and $status.Trim().Length -gt 0) {
  $msg = "sync: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
  try {
    Git "commit -m `"$msg`""
  } catch {
    Write-Host "提交失败（可能没有可提交内容或需要配置 user.name/user.email）。"
    throw
  }
} else {
  Write-Host "工作区无变更，跳过 commit。"
}

try {
  Git "fetch origin --prune"
} catch {
  Write-Host "fetch 失败（可能是首次推送或网络/权限问题），继续尝试 push。"
}

try {
  Git "pull --rebase origin $Branch"
} catch {
  Write-Host "pull --rebase 失败（可能远端还没有分支），继续尝试 push。"
}

Git "push -u origin $Branch"
Write-Host "完成。"

