$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$HostExe = Join-Path $Root ".venv\Scripts\jarvis-native-host.exe"
$ExtensionDir = Join-Path $Root "thunderbird-extension"
$DistDir = Join-Path $Root "dist"

if (-not (Test-Path $HostExe)) {
    throw "Le programme jarvis-native-host.exe est introuvable. Lance d'abord INSTALLER_JARVIS.bat."
}

$ManifestDir = Join-Path $env:APPDATA "Mozilla\NativeMessagingHosts"
New-Item -ItemType Directory -Force -Path $ManifestDir | Out-Null

$ManifestPath = Join-Path $ManifestDir "fr.jarvis_papa.host.json"
$Manifest = [ordered]@{
    name = "fr.jarvis_papa.host"
    description = "Pont local entre Thunderbird et Jarvis Papa"
    path = $HostExe
    type = "stdio"
    allowed_extensions = @("jarvis-papa@local")
}
$Manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $ManifestPath -Encoding UTF8

$RegistryPath = "HKCU:\Software\Mozilla\NativeMessagingHosts\fr.jarvis_papa.host"
New-Item -Path $RegistryPath -Force | Out-Null
Set-Item -Path $RegistryPath -Value $ManifestPath

New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
$ZipPath = Join-Path $DistDir "jarvis-papa-thunderbird.zip"
$XpiPath = Join-Path $DistDir "jarvis-papa-thunderbird.xpi"
Remove-Item $ZipPath, $XpiPath -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $ExtensionDir "*") -DestinationPath $ZipPath -Force
Move-Item -Path $ZipPath -Destination $XpiPath -Force

Write-Host ""
Write-Host "Pont Thunderbird installe cote Windows." -ForegroundColor Green
Write-Host "Extension preparee : $XpiPath"
Write-Host "Dans Thunderbird : Modules complementaires > roue dentee > Installer un module depuis un fichier."
Write-Host "Selectionne ensuite le fichier XPI ci-dessus."
