# Push only from this repo (new_dqt), never from Desktop\new_dq or $HOME.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$branch = (git branch --show-current).Trim()
if (-not $branch) {
    Write-Error 'Not on a branch (detached HEAD?).'
}

$remote = git remote get-url origin 2>$null
if (-not $remote) {
    Write-Error 'No remote "origin". Add it first: git remote add origin git@github.com:k1tit/new_dqt.git'
}

Write-Host "Repo:   $PSScriptRoot"
Write-Host "Remote: $remote"
Write-Host "Branch: $branch"
Write-Host ''
git status -sb
Write-Host ''

git push -u origin $branch
if ($LASTEXITCODE -ne 0) {
    Write-Error "git push failed (exit $LASTEXITCODE)"
}
Write-Host ''
Write-Host "OK: pushed $branch -> origin"
