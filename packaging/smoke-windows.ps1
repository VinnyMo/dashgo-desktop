param([string]$Package = "$PSScriptRoot\..\dist\DashGo-0.1.0-windows-x64")
$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path "$Package\DashGo.exe").Path
$worker = (Resolve-Path "$Package\DashGoWorker.exe").Path
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class DashGoWindowCheck {
 [DllImport("user32.dll", CharSet=CharSet.Unicode)]
 public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
'@
$oldConnect = $env:DASHGO_NO_AUTO_CONNECT
$oldPath = $env:PATH
try {
 $env:DASHGO_NO_AUTO_CONNECT = '1'
 $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
 # This explicitly tests the visible application window and taskbar resources.
 $process = Start-Process -FilePath $exe -WorkingDirectory $env:TEMP -WindowStyle Normal -PassThru
 try {
  for ($i=0; $i -lt 40; $i++) {
   Start-Sleep -Milliseconds 250
   $process.Refresh()
   if ($process.HasExited) { throw 'Packaged GUI exited during startup' }
   if ($process.MainWindowHandle -ne 0) { break }
  }
  if ($process.MainWindowTitle -notlike '*Release Version 0.1*') { throw 'Missing release window' }
  $small = [DashGoWindowCheck]::SendMessage($process.MainWindowHandle,0x7f,[IntPtr]0,[IntPtr]0)
  $big = [DashGoWindowCheck]::SendMessage($process.MainWindowHandle,0x7f,[IntPtr]1,[IntPtr]0)
  if ($small -eq 0 -or $big -eq 0) { throw 'Missing native window icons' }
  Write-Output 'PASS: clean portable startup, release title, small and large native window icons'
  if (!$process.CloseMainWindow()) { throw 'Could not close test window' }
  if (!$process.WaitForExit(10000)) { throw 'Test window failed to close' }
  if ($process.ExitCode -ne 0) { throw "GUI exit code $($process.ExitCode)" }
 } finally {
  if (!$process.HasExited) { $process.Kill(); $process.WaitForExit() }
 }
 foreach($module in @('dashcam_downloader.py','dashcam_stitch.py')) {
  $result = & $worker -u -B $module --help
  if ($LASTEXITCODE -ne 0 -or ($result -join "`n") -notmatch 'usage:') { throw "Worker failed: $module" }
 }
 Write-Output 'PASS: packaged helpers without system Python on PATH'
 Get-AuthenticodeSignature -LiteralPath $exe | Select-Object Status
 (Get-Item -LiteralPath $exe).VersionInfo | Select-Object FileVersion,ProductVersion,FileDescription
} finally {
 $env:DASHGO_NO_AUTO_CONNECT = $oldConnect
 $env:PATH = $oldPath
}
