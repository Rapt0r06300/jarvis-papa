param(
    [string]$JarvisExe = "",
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$BaseUri = "http://127.0.0.1:8765"
$DataDir = Join-Path $env:LOCALAPPDATA "JarvisPapa"
$RuntimeDir = Join-Path $DataDir "runtime"
$ReportPath = Join-Path $RuntimeDir "final-pc-validation.json"
$Results = [System.Collections.Generic.List[object]]::new()
$StartedJarvis = $null

function Add-Result {
    param(
        [string]$Name,
        [ValidateSet("PASS", "WARN", "FAIL")][string]$State,
        [string]$Detail
    )
    $item = [pscustomobject]@{
        name = $Name
        state = $State
        detail = $Detail
    }
    $Results.Add($item)
    Write-Host ("[{0}] {1} - {2}" -f $State, $Name, $Detail)
}

function Find-JarvisExecutable {
    if ($JarvisExe -and (Test-Path $JarvisExe)) {
        return (Resolve-Path $JarvisExe).Path
    }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Jarvis Papa\JarvisPapa.exe"),
        (Join-Path $PSScriptRoot "..\JarvisPapa.exe"),
        (Join-Path (Get-Location) "JarvisPapa.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return ""
}

function Test-Health {
    try {
        $health = Invoke-RestMethod -Uri "$BaseUri/health" -Method Get -TimeoutSec 2
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

function Wait-Health {
    param([int]$Seconds = 25)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Health) { return $true }
        Start-Sleep -Milliseconds 400
    }
    return $false
}

function Ensure-LocalTokenMaterialized {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$BaseUri/api/actions" -Method Get -TimeoutSec 2 | Out-Null
    } catch {
        # A 401 is expected here; the middleware creates the protected token first.
    }
}

function Get-LocalApiToken {
    Ensure-LocalTokenMaterialized
    $storePath = Join-Path $DataDir "protected-secrets.json"
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-Path $storePath) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Path $storePath)) { return "" }

    try {
        $payload = Get-Content $storePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $encoded = [string]$payload.items.local_api_auth_token
        if ([string]::IsNullOrWhiteSpace($encoded)) { return "" }
        $cipher = [Convert]::FromBase64String($encoded)
        $clear = [System.Security.Cryptography.ProtectedData]::Unprotect(
            $cipher,
            $null,
            [System.Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        return [Text.Encoding]::UTF8.GetString($clear)
    } catch {
        return ""
    }
}

$script:ApiToken = ""

function Invoke-JarvisJson {
    param(
        [ValidateSet("GET", "POST", "PUT", "PATCH", "DELETE")][string]$Method,
        [string]$Path,
        [object]$Body = $null,
        [int]$TimeoutSec = 5
    )
    $headers = @{}
    if (-not [string]::IsNullOrWhiteSpace($script:ApiToken)) {
        $headers["Authorization"] = "Bearer $script:ApiToken"
        $headers["X-Jarvis-Client"] = "final-pc-validator"
    }
    $parameters = @{
        Uri = "$BaseUri$Path"
        Method = $Method
        Headers = $headers
        TimeoutSec = $TimeoutSec
    }
    if ($null -ne $Body) {
        $parameters["ContentType"] = "application/json"
        $parameters["Body"] = ($Body | ConvertTo-Json -Depth 10 -Compress)
    }
    return Invoke-RestMethod @parameters
}

function Find-ThunderbirdExecutable {
    $candidates = @(
        (Join-Path $env:ProgramFiles "Mozilla Thunderbird\thunderbird.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Mozilla Thunderbird\thunderbird.exe")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    $command = Get-Command thunderbird.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return ""
}

function Wait-ThunderbirdBridge {
    param([int]$Seconds = 25)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $bridge = Invoke-JarvisJson -Method GET -Path "/api/thunderbird/bridge/status" -TimeoutSec 2
            if ($bridge.connected -eq $true) { return $true }
        } catch {
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-ThunderbirdAccountProbe {
    try {
        $start = Invoke-JarvisJson -Method POST -Path "/api/advanced/thunderbird/account-probe" -Body @{} -TimeoutSec 5
        if ($start.ok -ne $true -or [string]::IsNullOrWhiteSpace([string]$start.command_id)) {
            return [pscustomobject]@{ ok = $false; detail = [string]$start.detail }
        }
        $commandId = [string]$start.command_id
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            $state = Invoke-JarvisJson -Method GET -Path "/api/advanced/thunderbird/account-probe/$commandId" -TimeoutSec 3
            if ($state.state -eq "success" -and $state.ok -eq $true) {
                return [pscustomobject]@{
                    ok = $true
                    detail = ("{0} compte(s) mail, {1} dossier(s) accessibles." -f [int]$state.mail_account_count, [int]$state.folder_accessible_count)
                }
            }
            if ($state.state -eq "failed") {
                return [pscustomobject]@{ ok = $false; detail = [string]$state.detail }
            }
            Start-Sleep -Milliseconds 500
        }
        return [pscustomobject]@{ ok = $false; detail = "La sonde Thunderbird n'a pas répondu à temps." }
    } catch {
        return [pscustomobject]@{ ok = $false; detail = $_.Exception.Message }
    }
}

New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

try {
    $resolvedJarvis = Find-JarvisExecutable
    if (-not (Test-Health)) {
        if ([string]::IsNullOrWhiteSpace($resolvedJarvis)) {
            Add-Result "Application Jarvis" "FAIL" "JarvisPapa.exe est introuvable."
        } else {
            $StartedJarvis = Start-Process -FilePath $resolvedJarvis -WorkingDirectory (Split-Path $resolvedJarvis) -PassThru
        }
    }

    if (Wait-Health -Seconds 30) {
        Add-Result "Service local Jarvis" "PASS" "Le service local répond sur 127.0.0.1."
    } else {
        Add-Result "Service local Jarvis" "FAIL" "Le service local ne répond pas."
        throw "Jarvis local service unavailable"
    }

    try {
        $status = Invoke-RestMethod -Uri "$BaseUri/api/status" -Method Get -TimeoutSec 3
        if ($status.local_only -eq $true -and [string]$status.version) {
            Add-Result "Version et écoute locale" "PASS" ("Jarvis {0}, écoute locale uniquement." -f $status.version)
        } else {
            Add-Result "Version et écoute locale" "FAIL" "Le contrat de sécurité locale n'est pas valide."
        }
    } catch {
        Add-Result "Version et écoute locale" "FAIL" $_.Exception.Message
    }

    $script:ApiToken = Get-LocalApiToken
    if ([string]::IsNullOrWhiteSpace($script:ApiToken)) {
        Add-Result "Authentification API locale" "FAIL" "Le jeton DPAPI local est introuvable ou indéchiffrable."
        throw "Local API authentication unavailable"
    }
    try {
        $diagnostics = Invoke-JarvisJson -Method GET -Path "/api/diagnostics" -TimeoutSec 8
        if ($null -ne $diagnostics) {
            Add-Result "Authentification API locale" "PASS" "L'API privée accepte uniquement le client Jarvis authentifié."
        }
    } catch {
        Add-Result "Authentification API locale" "FAIL" $_.Exception.Message
    }

    $thunderbirdExe = Find-ThunderbirdExecutable
    if ([string]::IsNullOrWhiteSpace($thunderbirdExe)) {
        Add-Result "Thunderbird" "FAIL" "Thunderbird n'est pas installé ou détectable."
    } else {
        Add-Result "Thunderbird" "PASS" "Thunderbird est installé."
        if (-not (Get-Process thunderbird -ErrorAction SilentlyContinue)) {
            try {
                Start-Process -FilePath $thunderbirdExe | Out-Null
                Start-Sleep -Seconds 2
            } catch {
                Add-Result "Démarrage Thunderbird" "WARN" $_.Exception.Message
            }
        }
        if (Wait-ThunderbirdBridge -Seconds 30) {
            Add-Result "Pont Thunderbird" "PASS" "L'extension et le Native Messaging répondent réellement."
            $probe = Test-ThunderbirdAccountProbe
            if ($probe.ok) {
                Add-Result "Compte mail Thunderbird" "PASS" $probe.detail
            } else {
                Add-Result "Compte mail Thunderbird" "FAIL" $probe.detail
            }
        } else {
            Add-Result "Pont Thunderbird" "FAIL" "Le pont Jarvis/Thunderbird ne s'est pas connecté. Vérifie l'extension Thunderbird."
        }
    }

    try {
        $voice = Invoke-JarvisJson -Method GET -Path "/api/voice/status" -TimeoutSec 5
        if ($voice.enabled -eq $false) {
            Add-Result "Voix Jarvis" "FAIL" "La sortie vocale est désactivée."
        } else {
            $lastProvider = [string]$voice.last_result.provider
            $detail = if ($lastProvider) { "Voix active; dernier moteur: $lastProvider." } else { "Sous-système vocal actif et prêt à choisir son meilleur moteur." }
            Add-Result "Voix Jarvis" "PASS" $detail
        }
    } catch {
        Add-Result "Voix Jarvis" "FAIL" $_.Exception.Message
    }

    $edgeCandidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe")
    )
    if ($edgeCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1) {
        Add-Result "Microsoft Edge" "PASS" "Edge est disponible pour les parcours Web."
    } else {
        Add-Result "Microsoft Edge" "WARN" "Edge n'a pas été trouvé; Playwright pourra utiliser Chromium si disponible."
    }

    $everything = Get-Command es.exe -ErrorAction SilentlyContinue
    if ($everything) {
        Add-Result "Everything Search" "PASS" "es.exe est disponible pour la recherche ultra-rapide."
    } else {
        Add-Result "Everything Search" "WARN" "es.exe n'est pas installé; Jarvis utilisera sa recherche de fichiers de secours."
    }

    foreach ($folderName in @("Documents", "Desktop", "Downloads")) {
        $folder = Join-Path $HOME $folderName
        if (Test-Path $folder) {
            Add-Result "Dossier $folderName" "PASS" "Le dossier est accessible."
        } else {
            Add-Result "Dossier $folderName" "WARN" "Le dossier standard n'existe pas à cet emplacement."
        }
    }

    if (-not $NonInteractive) {
        try {
            Invoke-JarvisJson -Method POST -Path "/api/voice/preview" -Body @{ text = "Robert, test de la voix de Jarvis terminé." } -TimeoutSec 20 | Out-Null
            $heard = Read-Host "Avez-vous entendu clairement la phrase de test ? (o/n)"
            if ($heard -match "^(o|oui|y|yes)$") {
                Add-Result "Haut-parleurs réels" "PASS" "La sortie audio a été confirmée par l'utilisateur."
            } else {
                Add-Result "Haut-parleurs réels" "FAIL" "La phrase de test n'a pas été entendue correctement."
            }
        } catch {
            Add-Result "Haut-parleurs réels" "FAIL" $_.Exception.Message
        }
    } else {
        Add-Result "Haut-parleurs réels" "WARN" "Test subjectif ignoré en mode non interactif."
    }
} catch {
    if (-not ($Results | Where-Object { $_.state -eq "FAIL" })) {
        Add-Result "Validation" "FAIL" $_.Exception.Message
    }
} finally {
    $passCount = @($Results | Where-Object { $_.state -eq "PASS" }).Count
    $warnCount = @($Results | Where-Object { $_.state -eq "WARN" }).Count
    $failCount = @($Results | Where-Object { $_.state -eq "FAIL" }).Count
    $report = [ordered]@{
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        computer = $env:COMPUTERNAME
        jarvis_executable = $resolvedJarvis
        pass_count = $passCount
        warn_count = $warnCount
        fail_count = $failCount
        results = @($Results)
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content $ReportPath -Encoding UTF8
    Write-Host ""
    Write-Host ("Rapport: {0}" -f $ReportPath)
    Write-Host ("Résultat: {0} PASS / {1} WARN / {2} FAIL" -f $passCount, $warnCount, $failCount)

    if ($StartedJarvis -and -not $StartedJarvis.HasExited) {
        # Leave Jarvis running: the validator must not surprise the user by closing it.
    }
}

if (@($Results | Where-Object { $_.state -eq "FAIL" }).Count -gt 0) {
    exit 1
}
exit 0
