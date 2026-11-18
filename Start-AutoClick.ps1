<#
.SYNOPSIS
Inicia AutoClick con un servidor Ollama local o remoto.
.DESCRIPTION
Requiere Windows 10/11, uv, Node.js 20.19+ o 22.12+ y WebView2.
El uso completo requiere Ollama con los modelos de Autoclick-IA/.env,
la identidad AWS del worker y una cuenta AutoClick.
OLLAMA_BASE_URL selecciona el servidor; este iniciador no administra Ollama.
SetupOnly instala dependencias y prepara la configuracion sin verificar accesos.
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-AutoClick.ps1 -SetupOnly
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-AutoClick.ps1
#>
[CmdletBinding()]
param(
    [switch]$NoApp,
    [switch]$SetupOnly
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'AutoClick Desktop requiere Windows 10/11.' }
$root = $PSScriptRoot
$runtime = Join-Path $root '.autoclick'
$helpers = Join-Path $root 'Autoclick-IA/dev'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
. (Join-Path $helpers 'processes.ps1')
$statePath = Join-Path $runtime 'processes.json'
$lock = $null
$launched = @()
$state = @{}
$stateLoaded = $false
$originalLocation = Get-Location

function Require-Command([string]$Name, [string]$Help) {
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (!$command) { throw "Falta $Name. $Help" }
    return $command.Source
}
function Fingerprint([string[]]$Paths) {
    return (($Paths | ForEach-Object { (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash }) -join ':')
}
function Sync-Python([string]$Project, [string[]]$Inputs) {
    $stamp = Join-Path $runtime "$Project.dependencies"
    $fingerprint = Fingerprint $Inputs
    $python = Join-Path $root "$Project/.venv/Scripts/python.exe"
    $versionOk = $false
    if (Test-Path -LiteralPath $python) {
        $null = & $python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)'
        $versionOk = $LASTEXITCODE -eq 0
    }
    if (!$versionOk -or !(Test-Path -LiteralPath $stamp) -or
        (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $fingerprint) {
        Write-Host "Instalando dependencias de $Project (Python 3.11)..."
        & $uv sync --project (Join-Path $root $Project) --python 3.11 --frozen --no-dev --inexact
        if ($LASTEXITCODE -ne 0) { throw "Fallo la instalacion de $Project." }
        [IO.File]::WriteAllText($stamp, $fingerprint)
    }
}
function Listening([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}
function Ensure-Service([string]$Name, [int]$Port, [string]$Exe, [string]$Arguments, [string]$Directory) {
    $existing = Get-AutoClickProcess $state[$Name]
    if ($existing) { return }
    if (Listening $Port) {
        throw "Puerto $Port ocupado por otro proceso. Cerralo antes de iniciar; no se detuvo ese proceso."
    }
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $Directory `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime "$Name.out.log") `
        -RedirectStandardError (Join-Path $runtime "$Name.err.log")
    $state[$Name] = @{ pid = $process.Id; started = $process.StartTime.ToUniversalTime().Ticks.ToString(); profile = 'ollama' }
    Save-AutoClickState $state $statePath
    $script:launched += $Name
}
function Wait-Ready([string]$Name, [string]$Url, [int]$Seconds, [switch]$Html) {
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        if (!(Get-AutoClickProcess $state[$Name])) {
            throw "$Name termino antes de estar listo. Revisa $runtime/$Name.err.log"
        }
        try {
            if ($Html) {
                $page = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
                if ($page.StatusCode -eq 200) { return $page }
            } else { return Invoke-RestMethod -Uri $Url -TimeoutSec 10 }
        } catch { Start-Sleep -Seconds 1 }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "No responde $Url. Revisa $runtime/$Name.err.log."
}

function Confirm-OllamaModels($Profile) {
    $tagsUrl = $Profile.ollamaBaseUrl.TrimEnd('/') + '/api/tags'
    try { $tags = Invoke-RestMethod -Uri $tagsUrl -TimeoutSec 15 }
    catch { throw "No se pudo consultar Ollama. Verifica OLLAMA_BASE_URL, el servidor y el acceso de red." }
    $required = @($Profile.model, $Profile.fallbackModel) | Where-Object { $_ }
    foreach ($model in $required) {
        if (!($tags.models | Where-Object { $_.name -ceq $model })) {
            throw "Ollama no tiene instalado '$model'. Revisa ollama list y el paso 5 del README."
        }
    }
}

try {
    try { $lock = [IO.File]::Open((Join-Path $runtime 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'Otro iniciador o Stop-AutoClick ya esta trabajando en este repo.' }
    $state = Read-AutoClickState $statePath
    $stateLoaded = $true
    if (!$SetupOnly) { Reset-AutoClickProfile $state 'ollama' $statePath }
    Set-Location -LiteralPath $root
    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    $uv = if ($uvCommand) { $uvCommand.Source } else { Join-Path $env:USERPROFILE '.local/bin/uv.exe' }
    if (!(Test-Path -LiteralPath $uv)) {
        throw 'Falta uv. Instala uv siguiendo https://docs.astral.sh/uv/getting-started/installation/ y abre otra terminal.'
    }
    $node = Require-Command 'node.exe' 'Instala Node.js LTS desde https://nodejs.org y abre otra terminal.'
    $npm = Require-Command 'npm.cmd' 'Instala Node.js LTS.'
    $nodeVersion = [version]((& $node --version).Trim().TrimStart('v'))
    if (!(($nodeVersion.Major -eq 20 -and $nodeVersion -ge [version]'20.19.0') -or
          ($nodeVersion.Major -ge 22 -and $nodeVersion -ge [version]'22.12.0'))) {
        throw 'Vite requiere Node 20.19+ o 22.12+; se recomienda la version LTS actual.'
    }
    Sync-Python 'Autoclick-IA' @(
        (Join-Path $root 'Autoclick-IA/uv.lock'), (Join-Path $root 'Autoclick-IA/pyproject.toml'),
        (Join-Path $root 'Autoclick-MCP/pyproject.toml'))
    Sync-Python 'Autoclick-App' @(
        (Join-Path $root 'Autoclick-App/uv.lock'), (Join-Path $root 'Autoclick-App/pyproject.toml'))
    $pythonAi = Join-Path $root 'Autoclick-IA/.venv/Scripts/python.exe'
    $pythonApp = Join-Path $root 'Autoclick-App/.venv/Scripts/pythonw.exe'
    $frontend = Join-Path $root 'Autoclick-App/frontend'
    $npmStamp = Join-Path $runtime 'frontend.dependencies'
    $npmFingerprint = Fingerprint @((Join-Path $frontend 'package.json'), (Join-Path $frontend 'package-lock.json'))
    if (!(Test-Path -LiteralPath (Join-Path $frontend 'node_modules/vite/bin/vite.js')) -or
        !(Test-Path -LiteralPath $npmStamp) -or (Get-Content -LiteralPath $npmStamp -Raw).Trim() -ne $npmFingerprint) {
        Write-Host 'Instalando dependencias de la interfaz...'
        Set-Location -LiteralPath $frontend
        & $npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Fallo npm ci.' }
        [IO.File]::WriteAllText($npmStamp, $npmFingerprint)
        Set-Location -LiteralPath $root
    }
    & $pythonAi (Join-Path $helpers 'setup_local.py')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la configuracion local.' }
    if ($SetupOnly) {
        Write-Host 'Dependencias y configuracion preparadas. Para iniciar se requieren Ollama con ambos modelos, la identidad AWS del worker y una cuenta AutoClick habilitada.'
        return
    }
    Write-Host 'Verificando autorizacion del worker...'
    & $pythonAi (Join-Path $helpers 'setup_local.py') --check
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo autorizar el worker; revisa el mensaje anterior.' }
    $profileJson = & $pythonAi (Join-Path $root 'Autoclick-IA/runtime_config.py')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el perfil de IA.' }
    $profile = $profileJson | ConvertFrom-Json
    Write-Host 'Comprobando los modelos en el servidor Ollama configurado...'
    Confirm-OllamaModels $profile
    $shell = Require-Command 'powershell.exe' 'Se requiere Windows PowerShell.'
    Ensure-Service 'backend' 8001 $shell `
        ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f (Join-Path $root 'Autoclick-IA/start-cloud.ps1')) `
        (Join-Path $root 'Autoclick-IA')
    $health = Wait-Ready 'backend' 'http://127.0.0.1:8001/health' 90
    if ($health.status -ne 'ready' -or !$health.modelInstalled -or $health.model -ne $profile.model) {
        throw 'El backend no confirma que el modelo configurado este listo.'
    }
    Ensure-Service 'frontend' 5173 $node `
        ('"{0}" --host 127.0.0.1 --port 5173 --strictPort' -f (Join-Path $frontend 'node_modules/vite/bin/vite.js')) $frontend
    $null = Wait-Ready 'frontend' 'http://127.0.0.1:5173' 45 -Html
    if (!$NoApp -and !(Get-AutoClickProcess $state['desktop'])) {
        $previousDevUrl = $env:AUTOCLICK_DEV_URL
        try {
            $env:AUTOCLICK_DEV_URL = 'http://127.0.0.1:5173'
            $desktop = Start-Process -FilePath $pythonApp -ArgumentList '-m autoclick_desktop.main' `
                -WorkingDirectory (Join-Path $root 'Autoclick-App') -PassThru `
                -RedirectStandardOutput (Join-Path $runtime 'desktop.out.log') `
                -RedirectStandardError (Join-Path $runtime 'desktop.err.log')
            $state['desktop'] = @{ pid = $desktop.Id; started = $desktop.StartTime.ToUniversalTime().Ticks.ToString(); profile = 'ollama' }
            Save-AutoClickState $state $statePath
            $script:launched += 'desktop'
            Start-Sleep -Seconds 3
            if (!(Get-AutoClickProcess $state['desktop'])) { throw "La app termino. Revisa $runtime/desktop.err.log; verifica WebView2." }
        } finally { $env:AUTOCLICK_DEV_URL = $previousDevUrl }
    }
    Write-Host 'AutoClick listo. Ollama configurado por OLLAMA_BASE_URL; backend local: http://127.0.0.1:8001'
    Write-Host "Logs: $runtime"
    Write-Host 'Para cerrar los servicios locales: powershell -ExecutionPolicy Bypass -File .\Stop-AutoClick.ps1'
    Write-Host 'Ollama se administra por separado; Stop-AutoClick solo detiene los procesos de esta aplicacion.'
} catch {
    $startupError = $_
    foreach ($name in @('desktop', 'frontend', 'backend')) {
        if ($name -in $launched) {
            try { Stop-AutoClickProcess $state[$name]; $state.Remove($name) }
            catch { Write-Warning "No se pudo cerrar $name; usa Stop-AutoClick.ps1." }
        }
    }
    if ($lock -and $stateLoaded) { Save-AutoClickState $state $statePath }
    throw $startupError
} finally {
    Set-Location -LiteralPath $originalLocation
    if ($lock) { $lock.Dispose() }
}
