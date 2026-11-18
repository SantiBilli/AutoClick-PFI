$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.env.cloud')) { throw 'Primero ejecuta Start-AutoClick.ps1 -SetupOnly desde la raiz del repo.' }
$profileJson = & "$PSScriptRoot/.venv/Scripts/python.exe" "$PSScriptRoot/runtime_config.py"
if ($LASTEXITCODE -ne 0) { throw 'No se pudo leer el perfil de IA.' }
$runtimeProfile = $profileJson | ConvertFrom-Json
if (!$runtimeProfile.cloudEnabled) { throw 'El worker requiere AUTOCLICK_CLOUD_API_URL en .env.cloud.' }
Write-Host "Modelo: $($runtimeProfile.model); Ollama: $($runtimeProfile.ollamaBaseUrl)"
& "$PSScriptRoot/.venv/Scripts/python.exe" -m uvicorn app.main:app --env-file .env.cloud --host $runtimeProfile.backendHost --port $runtimeProfile.backendPort --reload --reload-dir app
exit $LASTEXITCODE
