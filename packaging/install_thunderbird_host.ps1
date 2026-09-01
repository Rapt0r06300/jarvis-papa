param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$HostName = "fr.jarvis_papa.host"
$ManifestDir = Join-Path $env:APPDATA "Mozilla\NativeMessagingHosts"
$ManifestPath = Join-Path $ManifestDir "$HostName.json"
$RegistryPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\$HostName"

if ($Uninstall) {
    Remove-Item -Path $RegistryPath -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path $ManifestPath -Force -ErrorAction SilentlyContinue
    exit 0
}

$HostExe = Join-Path $InstallRoot "JarvisNativeHost.exe"
if (-not (Test-Path $HostExe)) {
    throw "JarvisNativeHost.exe est introuvable dans $InstallRoot"
}

New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null
$Manifest = [ordered]@{
    name = $HostName
    description = "Pont local entre Thunderbird et Jarvis Papa"
    path = $HostExe
    type = "stdio"
    allowed_extensions = @("jarvis-papa@local")
}
$Json = $Manifest | ConvertTo-Json -Depth 4
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ManifestPath, $Json, $Utf8NoBom)

New-Item -Path $RegistryPath -Force | Out-Null
Set-Item -Path $RegistryPath -Value $ManifestPath

Write-Host "Pont Thunderbird Jarvis enregistre : $ManifestPath"
