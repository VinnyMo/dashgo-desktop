param(
    [string]$Camera,
    [string]$OutputRoot,
    [double]$GapMinutes = 5,
    [int]$SkipNewest = 2,
    [string]$TargetSize = 'original'
)

$ErrorActionPreference = 'Stop'
$dataRoot = if (Test-Path -LiteralPath "$PSScriptRoot\.installed-layout") { Split-Path -Parent $PSScriptRoot } else { $PSScriptRoot }
if (-not $OutputRoot) { $OutputRoot = Join-Path $dataRoot 'Transfers' }
$python = (Get-Command python.exe -ErrorAction Stop).Source
$downloader = Join-Path $PSScriptRoot 'dashcam_downloader.py'
$stitcher = Join-Path $PSScriptRoot 'dashcam_stitch.py'

if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python.exe -ErrorAction Stop).Source
}

$downloadArgs = @(
    '-B', $downloader, '--download', '--output', $OutputRoot,
    '--skip-newest', $SkipNewest
)
if ($Camera) {
    $downloadArgs += @('--camera', $Camera)
}

& $python @downloadArgs
if ($LASTEXITCODE -ne 0) {
    throw "Dash-cam download failed with exit code $LASTEXITCODE"
}

$driveOutput = Join-Path $OutputRoot 'Drives'
& $python -B $stitcher --source $OutputRoot --output $driveOutput `
    --gap-minutes $GapMinutes --target-size $TargetSize --stitch
if ($LASTEXITCODE -ne 0) {
    throw "Dash-cam stitching failed with exit code $LASTEXITCODE"
}

Write-Host "Finished. Drive MP4 files are in $driveOutput"
