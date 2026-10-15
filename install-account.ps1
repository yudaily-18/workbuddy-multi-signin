# install-account.ps1 - install (or repoint) the two scheduled tasks for ONE account
# snapshot, staggered so multiple accounts never fire at the same minute.
#
# Usage (run in the project root):
#   powershell -ExecutionPolicy Bypass -File .\install-account.ps1 -Label account-b -Slot 1
#   powershell -ExecutionPolicy Bypass -File .\install-account.ps1 -Label account-a -Slot 0
#   powershell -ExecutionPolicy Bypass -File .\install-account.ps1 -Label account-b -Slot 1 -Uninstall
#
# Slots (staggered times; slot 0 = the original WorkBuddyAutoSignin/GrowthPoll names):
#   slot 0 : signin 00:05, polls at :00 of 01/05/09/13/17/21  -> WorkBuddyAutoSignin / WorkBuddyGrowthPoll
#   slot 1 : signin 00:35, polls at :35                       -> WorkBuddyAutoSignin_<Label> / WorkBuddyGrowthPoll_<Label>
#   slot 2 : signin 00:50, polls at :50                       -> same naming as slot 1
#
# The task action is pythonw.exe + run-account.py (NOT the old .bat): pythonw is a
# GUI-subsystem binary, so no console window ever flashes. run-account.py pins
# WORKBUDDY_AUTH_FILE / WORKBUDDY_SIGNIN_LOG to creds\<Label>.info / .log.

param(
    [Parameter(Mandatory = $true)][string]$Label,
    [ValidateSet(0, 1, 2)][int]$Slot = 1,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$Creds = Join-Path $Root "creds"
$Snapshot = Join-Path $Creds "$Label.info"
$Runner = Join-Path $Root "run-account.py"

# Slot 0 keeps the upstream schedule exactly (signin 00:05, polls at :00);
# slots 1/2 shift both by their offset so accounts never fire in the same minute.
$signinMinutes = @{ 0 = "05"; 1 = "35"; 2 = "50" }[$Slot]
$pollMinutes = @{ 0 = "00"; 1 = "35"; 2 = "50" }[$Slot]
$signinTime = "00:$signinMinutes"
$pollHours = @("01", "05", "09", "13", "17", "21") | ForEach-Object { "$($_):$pollMinutes" }
# Slot 0 keeps the upstream task names (WorkBuddyAutoSignin / WorkBuddyGrowthPoll);
# slots 1/2 get per-label suffixed names so each account has its own pair.
$signinTask = "WorkBuddyAutoSignin"
$pollTask = "WorkBuddyGrowthPoll"
if ($Slot -ne 0) {
    $signinTask = "WorkBuddyAutoSignin_$Label"
    $pollTask = "WorkBuddyGrowthPoll_$Label"
}

function Resolve-Pythonw {
    $known = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\pythonw.exe"
    if (Test-Path $known) { return $known }
    $c = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
    if ($c -and (Test-Path $c)) { return $c }
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($py) {
        $c = Join-Path (Split-Path $py) "pythonw.exe"
        if (Test-Path $c) { return $c }
    }
    foreach ($pat in @("C:\Python3*\pythonw.exe", "$env:LOCALAPPDATA\Programs\Python\Python3*\pythonw.exe")) {
        $hit = Get-ChildItem $pat -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

if ($Uninstall) {
    foreach ($t in @($signinTask, $pollTask)) {
        $existing = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false
            Write-Host "  removed $t" -ForegroundColor Yellow
        } else {
            Write-Host "  $t not found" -ForegroundColor DarkGray
        }
    }
    Write-Host "snapshot kept: $Snapshot" -ForegroundColor DarkGray
    exit 0
}

# --- preflight ---
if (-not (Test-Path $Snapshot)) {
    Write-Host "  FAILED" -ForegroundColor Red
    Write-Host "snapshot not found: $Snapshot" -ForegroundColor Red
    Write-Host "log into that account in the WorkBuddy desktop client first, then run:" -ForegroundColor Yellow
    Write-Host "  python capture-account.py $Label --expect-phone <phone>" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path $Runner)) {
    Write-Host "  FAILED: launcher not found: $Runner" -ForegroundColor Red
    exit 1
}

$pythonw = Resolve-Pythonw
if (-not $pythonw) {
    Write-Host "  FAILED: pythonw.exe not found" -ForegroundColor Red
    exit 1
}
# wrapper reads this file so the .bat stays path-agnostic
Set-Content -Path (Join-Path $Root "pythonw.path") -Value $pythonw -Encoding ASCII
Write-Host "[1/3] pythonw: $pythonw" -ForegroundColor Green

# --- register ---
Write-Host "[2/3] registering tasks (slot $Slot) ..." -NoNewline
try {
    # S4U：任务不依赖用户登录即可运行 —— 电脑重启后停在登录界面也照样领积分。
    # 2026-10-16 实测通过（脚本能正常解密凭证并调 API）。
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

    $act1 = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$Runner`" `"$Label`" silent"
    $tri1 = New-ScheduledTaskTrigger -Daily -At $signinTime
    $set1 = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $signinTask `
        -Action $act1 -Trigger $tri1 -Settings $set1 -Principal $principal `
        -Description "WorkBuddy daily auto signin for account snapshot '$Label' (silent, zero token)" -Force | Out-Null

    $tri2 = @()
    foreach ($hh in $pollHours) { $tri2 += New-ScheduledTaskTrigger -Daily -At $hh }
    $act2 = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$Runner`" `"$Label`" silent-poll"
    $set2 = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden `
        -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $pollTask `
        -Action $act2 -Trigger $tri2 -Settings $set2 -Principal $principal `
        -Description "WorkBuddy poll (catch-up signin + growth center) for account snapshot '$Label'" -Force | Out-Null
} catch {
    Write-Host "  FAILED" -ForegroundColor Red
    Write-Host "error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host "  done" -ForegroundColor Green

# --- summary ---
Write-Host "[3/3] tasks in place:" -ForegroundColor Green
foreach ($row in @(
    @{ Name = $signinTask; When = "daily $signinTime"; What = "signin + growth" },
    @{ Name = $pollTask; When = "daily $($pollHours -join ', ')"; What = "catch-up + growth" }
)) {
    $t = Get-ScheduledTask -TaskName $row.Name
    $i = Get-ScheduledTaskInfo -TaskName $row.Name
    Write-Host ("  {0,-34} {1,-7} {2,-32} {3}" -f $row.Name, $t.State, $row.When, $row.What)
    Write-Host ("  {0,-34} next run {1}" -f "", $i.NextRunTime) -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "log: $(Join-Path $Creds "$Label.log")" -ForegroundColor Cyan
if ($Slot -eq 0) {
    Write-Host "NOTE: slot 0 repointed the original task names to the '$Label' snapshot." -ForegroundColor Yellow
    Write-Host "The client's live login state no longer affects which account gets claimed." -ForegroundColor Yellow
}
