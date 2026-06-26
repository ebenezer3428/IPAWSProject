# Direct Firebase Hosting deploy via REST API using a gcloud user access token.
# Usage: pwsh scripts/deploy_hosting.ps1
$ErrorActionPreference = 'Stop'
$site = 'ipawsproject-live-202602252025'
$distRoot = (Resolve-Path "$PSScriptRoot/../web/dist").Path
$base = 'https://firebasehosting.googleapis.com/v1beta1'

$token = (gcloud auth print-access-token).Trim()
if (-not $token) { throw 'No gcloud access token' }
$authHeader = @{ Authorization = "Bearer $token"; 'X-Goog-User-Project' = $site }

function Get-GzipAndHash([string]$path) {
    $raw = [System.IO.File]::ReadAllBytes($path)
    $ms = New-Object System.IO.MemoryStream
    $gz = New-Object System.IO.Compression.GZipStream($ms, [System.IO.Compression.CompressionMode]::Compress)
    $gz.Write($raw, 0, $raw.Length)
    $gz.Close()
    $bytes = $ms.ToArray()
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hash = (($sha.ComputeHash($bytes)) | ForEach-Object { $_.ToString('x2') }) -join ''
    return @{ Bytes = $bytes; Hash = $hash }
}

# 1. Enumerate files -> gzip + hash
$files = Get-ChildItem -Recurse -File $distRoot
$fileMap = @{}        # site path -> hash
$hashBytes = @{}      # hash -> gzipped bytes
foreach ($f in $files) {
    $rel = '/' + $f.FullName.Substring($distRoot.Length).TrimStart('\', '/').Replace('\', '/')
    $g = Get-GzipAndHash $f.FullName
    $fileMap[$rel] = $g.Hash
    $hashBytes[$g.Hash] = $g.Bytes
    Write-Host "hashed $rel -> $($g.Hash)"
}

# 2. Create a new version
$ver = Invoke-RestMethod -Method Post -Uri "$base/sites/$site/versions" -Headers $authHeader -ContentType 'application/json' -Body '{}'
$versionName = $ver.name
Write-Host "version: $versionName"

# 3. Populate files
$popBody = @{ files = $fileMap } | ConvertTo-Json -Depth 5
$pop = Invoke-RestMethod -Method Post -Uri "$base/${versionName}:populateFiles" -Headers $authHeader -ContentType 'application/json' -Body $popBody
$required = @($pop.uploadRequiredHashes)
$uploadUrl = $pop.uploadUrl
Write-Host "upload required: $($required.Count) files; uploadUrl: $uploadUrl"

# 4. Upload each required hash
foreach ($h in $required) {
    if (-not $hashBytes.ContainsKey($h)) { throw "Missing bytes for hash $h" }
    Invoke-RestMethod -Method Put -Uri "$uploadUrl/$h" -Headers $authHeader -ContentType 'application/octet-stream' -Body $hashBytes[$h] | Out-Null
    Write-Host "uploaded $h"
}

# 5. Finalize version
Invoke-RestMethod -Method Patch -Uri "$base/${versionName}?update_mask=status" -Headers $authHeader -ContentType 'application/json' -Body '{"status":"FINALIZED"}' | Out-Null
Write-Host "finalized $versionName"

# 6. Release
$rel = Invoke-RestMethod -Method Post -Uri "$base/sites/$site/releases?versionName=$versionName" -Headers $authHeader -ContentType 'application/json' -Body '{}'
Write-Host "RELEASED: $($rel.name)"
Write-Host "Live at https://$site.web.app"
