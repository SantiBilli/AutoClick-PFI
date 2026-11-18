# Shared by Start/Stop. Every managed PID includes its start time to avoid PID reuse.
function Read-AutoClickState([string]$Path) {
    $state = @{}
    if (Test-Path -LiteralPath $Path) {
        $saved = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        foreach ($property in $saved.PSObject.Properties) { $state[$property.Name] = $property.Value }
    }
    return $state
}

function Save-AutoClickState([hashtable]$State, [string]$Path) {
    $temporary = "$Path.tmp"
    [IO.File]::WriteAllText($temporary, ($State | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Get-AutoClickProcess($Record) {
    if (!$Record) { return $null }
    $process = Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $Record.started) {
        return $process
    }
    return $null
}

function Stop-AutoClickProcess($Record) {
    $process = Get-AutoClickProcess $Record
    if ($process) {
        # Include the backend's reload worker in the managed process tree.
        & "$env:SystemRoot/System32/taskkill.exe" /PID $process.Id /T /F | Out-Null
        if ($LASTEXITCODE -ne 0 -and (Get-AutoClickProcess $Record)) {
            throw "No se pudo detener el proceso $($Record.pid)."
        }
    }
}

function Reset-AutoClickProfile([hashtable]$State, [string]$Profile, [string]$Path) {
    $names = @('desktop', 'frontend', 'backend')
    $restart = $false
    foreach ($name in $names) {
        if ((Get-AutoClickProcess $State[$name]) -and $State[$name].profile -ne $Profile) {
            $restart = $true
            break
        }
    }
    if (!$restart) { return }
    Write-Host 'Reiniciando los servicios de AutoClick para aplicar la version seleccionada...'
    foreach ($name in $names) {
        Stop-AutoClickProcess $State[$name]
        $State.Remove($name)
        Save-AutoClickState $State $Path
    }
}
