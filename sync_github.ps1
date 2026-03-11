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
  throw "git is not installed or not in PATH. Please install Git first."
}

if (-not (Test-Path -LiteralPath ".git")) {
  throw "Not a Git repo (missing .git). Run this from the project root."
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
    Write-Host "No remote named 'origin'. Provide the repo URL, e.g.:"
    Write-Host "  https://github.com/icenorthe/zhongwangchong.git"
    Write-Host ""
    throw "Usage: ./sync_github.ps1 -RepoUrl <url>  or set env var GITHUB_REPO_URL"
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
  Write-Host "No working tree changes; skipping commit."
}

try {
  Git "fetch origin --prune"
} catch {
  Write-Host "fetch failed (maybe first push or auth/network issue); continuing."
}

try {
  Git "pull --rebase origin $Branch"
} catch {
  Write-Host "pull --rebase failed (remote branch may not exist yet); continuing."
}

Git "push -u origin $Branch"
Write-Host "Done."
