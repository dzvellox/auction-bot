$ErrorActionPreference = "Stop"

$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$profile = Join-Path $projectRoot ".interencheres-browser-profile"
$port = 9222
$endpoint = "http://127.0.0.1:$port/json/version"

$candidates = @(
  @{ Name = "Google Chrome"; Path = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" },
  @{ Name = "Google Chrome"; Path = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe" },
  @{ Name = "Google Chrome"; Path = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe" },
  @{ Name = "Microsoft Edge"; Path = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe" },
  @{ Name = "Microsoft Edge"; Path = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" }
) | Where-Object { $_.Path -and (Test-Path $_.Path) }

if (-not $candidates -or $candidates.Count -eq 0) {
  Write-Host "Chrome/Edge introuvable." -ForegroundColor Red
  exit 1
}

function Test-CdpEndpoint {
  param([int]$WaitSeconds = 1)
  try {
    $response = Invoke-RestMethod -Uri $endpoint -TimeoutSec $WaitSeconds
    return ($null -ne $response.webSocketDebuggerUrl)
  }
  catch {
    return $false
  }
}

function Stop-DedicatedBrowser {
  # Ferme uniquement les processus Chrome/Edge lancés avec NOTRE profil dédié.
  # C'est important : un ancien processus utilisant déjà ce profil peut absorber
  # le nouvel appel et ignorer --remote-debugging-port.
  try {
    $processes = Get-CimInstance Win32_Process | Where-Object {
      ($_.Name -in @("chrome.exe", "msedge.exe")) -and
      $_.CommandLine -and
      ($_.CommandLine -like "*$profile*")
    }
    foreach ($proc in $processes) {
      try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
    if ($processes) { Start-Sleep -Milliseconds 800 }
  }
  catch {
    Write-Host "Impossible d'inspecter les anciens processus dédiés : $($_.Exception.Message)" -ForegroundColor DarkYellow
  }
}

if (Test-CdpEndpoint) {
  Write-Host "Le navigateur Interencheres est déjà prêt." -ForegroundColor Green
  Write-Host "CDP OK : $endpoint" -ForegroundColor Green
  exit 0
}

New-Item -ItemType Directory -Force -Path $profile | Out-Null
Stop-DedicatedBrowser

Write-Host "Démarrage du navigateur Interencheres..." -ForegroundColor Cyan
Write-Host "Profil : $profile"
Write-Host "Port CDP attendu : $port"
Write-Host "Le script va maintenant VERIFIER le port avant d'annoncer qu'il fonctionne." -ForegroundColor Cyan

$started = $false
foreach ($candidate in $candidates) {
  $browser = $candidate.Path
  $name = $candidate.Name

  Write-Host "Essai avec $name : $browser" -ForegroundColor Cyan

  $args = @(
    "--remote-debugging-port=$port",
    "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=$profile",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-mode",
    "--new-window",
    "https://www.interencheres.com/"
  )

  try {
    $proc = Start-Process -FilePath $browser -ArgumentList $args -PassThru
  }
  catch {
    Write-Host "Echec du lancement de $name : $($_.Exception.Message)" -ForegroundColor Yellow
    continue
  }

  $deadline = (Get-Date).AddSeconds(15)
  while ((Get-Date) -lt $deadline) {
    if (Test-CdpEndpoint) {
      $started = $true
      break
    }
    Start-Sleep -Milliseconds 500
  }

  if ($started) {
    Write-Host "" 
    Write-Host "CDP OK : $endpoint" -ForegroundColor Green
    Write-Host "Le navigateur est prêt pour le probe et le bot." -ForegroundColor Green
    Write-Host "Si Interencheres affiche une vérification humaine, termine-la MANUELLEMENT et laisse cette fenêtre ouverte." -ForegroundColor Yellow
    exit 0
  }

  Write-Host "$name s'est ouvert mais le port $port n'est pas accessible." -ForegroundColor Yellow
  try {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
  } catch {}
  Stop-DedicatedBrowser
}

Write-Host "" 
Write-Host "ECHEC : aucun navigateur n'a exposé le port CDP $port." -ForegroundColor Red
Write-Host "La page Interencheres peut s'ouvrir visuellement tout en n'ayant AUCUN port de débogage." -ForegroundColor Yellow
Write-Host "" 
Write-Host "Diagnostic à lancer :" -ForegroundColor Cyan
Write-Host "  Test-NetConnection 127.0.0.1 -Port $port"
Write-Host "  Invoke-WebRequest $endpoint"
Write-Host "" 
Write-Host "Si le PC applique une politique Chrome/Edge qui interdit le débogage distant, ouvre chrome://policy ou edge://policy et cherche RemoteDebuggingAllowed." -ForegroundColor Yellow
exit 2
