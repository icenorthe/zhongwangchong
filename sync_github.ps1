param(
  [Parameter(Mandatory = $false)]
  [string]$RepoUrl,

  [Parameter(Mandatory = $false)]
  [string]$Branch
)

$ErrorActionPreference = "Stop"

function Test-GitHubConnectivity {
  param(
    [string]$HostName = "github.com",
    [int]$Port = 443
  )

  try {
    $result = Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue
    return [bool]$result.TcpTestSucceeded
  } catch {
    return $false
  }
}

function Get-GitPushErrorHint {
  param([string]$Message)

  $text = ""
  if ($null -ne $Message) {
    $text = [string]$Message
  }
  if ($text -match "Could not connect to server" -or $text -match "Connection was reset" -or $text -match "Failed to connect to github.com port 443") {
    return "Network to github.com:443 is unavailable. Check proxy, VPN, firewall, or local network first."
  }
  if ($text -match "Authentication failed" -or $text -match "Repository not found") {
    return "Authentication or repository permission failed. Check GitHub login/token and repo access."
  }
  return ""
}

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

if (-not (Test-GitHubConnectivity)) {
  throw "Cannot reach github.com:443. Fix network/proxy/VPN first, then retry sync."
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
  $hint = Get-GitPushErrorHint $_.Exception.Message
  if ($hint) {
    throw $hint
  }
  Write-Host "fetch failed; continuing."
}

try {
  Invoke-Git pull --rebase origin $Branch
} catch {
  $hint = Get-GitPushErrorHint $_.Exception.Message
  if ($hint) {
    throw $hint
  }
  Write-Host "pull --rebase failed (remote branch may not exist yet); continuing."
}

try {
  Invoke-Git push -u origin $Branch
} catch {
  $hint = Get-GitPushErrorHint $_.Exception.Message
  if ($hint) {
    throw $hint
  }
  throw
}
Write-Host "Done."
