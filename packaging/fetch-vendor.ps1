$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
function Get-VerifiedArchive($url, $destination, $sha256) {
 if (!(Test-Path -LiteralPath $destination)) {
  Invoke-WebRequest -Uri $url -OutFile "$destination.download" -TimeoutSec 180
  if ((Get-FileHash -LiteralPath "$destination.download" -Algorithm SHA256).Hash -ne $sha256) {
   throw "Checksum mismatch: $url"
  }
  Move-Item -LiteralPath "$destination.download" -Destination $destination
 }
 if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $sha256) {
  throw "Unexpected cached archive: $destination"
 }
}
$vendor = Join-Path $repo 'vendor'
$sources = Join-Path $repo 'vendor-sources'
New-Item -ItemType Directory -Path $vendor,$sources -Force | Out-Null
$ffmpeg = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'FFMPEG-MANIFEST.json') -Raw | ConvertFrom-Json
$archive = Join-Path $vendor $ffmpeg.archive
Get-VerifiedArchive $ffmpeg.url $archive $ffmpeg.sha256
$expanded = Join-Path $vendor 'ffmpeg-9.0.2'
if (!(Test-Path -LiteralPath $expanded)) {
 Expand-Archive -LiteralPath $archive -DestinationPath $expanded
}
$sourceManifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'SOURCE-MANIFEST.json') -Raw | ConvertFrom-Json
foreach($source in $sourceManifest) {
 Get-VerifiedArchive $source.url (Join-Path $sources $source.file) $source.sha256
}
Write-Output 'Pinned vendor binary and source archives verified. Licensing gates still apply.'
