$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Date = Get-Date -Format "yyyy-MM-dd"
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "sector_fund_daily_$Date.log"

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

& $Python main.py --mode sector_fund --config config/personal_semiconductor.yaml --real-data --save-history *> $LogFile

if ($LASTEXITCODE -ne 0) {
    "real-data failed, fallback to mock" | Out-File -Append -Encoding utf8 $LogFile
    & $Python main.py --mode sector_fund --config config/personal_semiconductor.yaml --mock --save-history *>> $LogFile
}

$ReportLine = Select-String -Path $LogFile -Pattern "报告路径:" | Select-Object -Last 1
if ($ReportLine) {
    Write-Output $ReportLine.Line
} else {
    Write-Output "sector_fund daily run finished. Log: $LogFile"
}
