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
$sources = Join-Path $repo 'vendor-sources'
New-Item -ItemType Directory -Path $sources -Force | Out-Null
$sourceManifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'SOURCE-MANIFEST.json') -Raw | ConvertFrom-Json
foreach($source in $sourceManifest) {
 Get-VerifiedArchive $source.url (Join-Path $sources $source.file) $source.sha256
}
Write-Output 'Pinned source archives verified. FFmpeg is an external user prerequisite.'
