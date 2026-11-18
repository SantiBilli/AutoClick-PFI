$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.autoclick'
$statePath = Join-Path $runtime 'processes.json'
if (!(Test-Path -LiteralPath $statePath)) { Write-Host 'No hay servicios registrados por este iniciador.'; return }
. (Join-Path $PSScriptRoot 'Autoclick-IA/dev/processes.ps1')
$lock = $null
try {
    try { $lock = [IO.File]::Open((Join-Path $runtime 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'Otro iniciador o Stop-AutoClick esta trabajando; espera que termine.' }
    $state = Read-AutoClickState $statePath
    foreach ($name in @('desktop', 'frontend', 'backend')) {
        Stop-AutoClickProcess $state[$name]
        $state.Remove($name)
        Save-AutoClickState $state $statePath
    }
    Write-Host 'Servicios locales de AutoClick cerrados. Ollama se administra por separado.'
} finally { if ($lock) { $lock.Dispose() } }
