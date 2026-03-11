param(
  [Parameter(Mandatory = $false)]
  [string]$RepoUrl,

  [Parameter(Mandatory = $false)]
  [string]$Branch
)

$ErrorActionPreference = "Stop"

function Invoke-Git {
  param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GitArgs
  )

  $pretty = ($GitArgs -join " ")
  Write-Host ">> git $pretty"

  & git @GitArgs
  if ($LASTEXITCODE -ne 0) { throw "git failed: $pretty" }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw "git is not installed or not in PATH. Please install Git first."
}

if (-not (Test-Path -LiteralPath ".git")) {
  throw "Not a Git repo (missing .git). Run this from the project root."
}

if (-not $Branch -or $Branch.Trim() -eq "") {
  $Branch = (& git rev-parse --abbrev-ref HEAD).Trim()
  if (-not $Branch) { $Branch = "master" }
}

if (-not $RepoUrl -or $RepoUrl.Trim() -eq "") {
  $RepoUrl = $env:GITHUB_REPO_URL
}

if ($RepoUrl -and $RepoUrl.Trim() -ne "") {
  $RepoUrl = $RepoUrl.Trim()
  # Accept GitHub web URLs like https://github.com/user/repo and convert to clone URL
  if ($RepoUrl -match '^https?://github\.com/[^/]+/[^/]+/?$') {
    $RepoUrl = $RepoUrl.TrimEnd('/') + '.git'
  }
}

$hasOrigin = $false
try {
  $originUrl = (& git remote get-url origin 2>$null).Trim()
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
  Invoke-Git remote add origin "$RepoUrl"
}

Invoke-Git add -A

$status = (& git status --porcelain)
if ($status -and $status.Trim().Length -gt 0) {
  $msg = "sync: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
  try {
    Invoke-Git commit -m "$msg"
  } catch {
    Write-Host "Commit failed (maybe nothing to commit, or user.name/user.email is not set)."
    throw
  }
} else {
  Write-Host "No working tree changes; skipping commit."
}

try {
  Invoke-Git fetch origin --prune
} catch {
  Write-Host "fetch failed (maybe first push or auth/network issue); continuing."
}

try {
  Invoke-Git pull --rebase origin $Branch
} catch {
  Write-Host "pull --rebase failed (remote branch may not exist yet); continuing."
}

Invoke-Git push -u origin $Branch
Write-Host "Done."
