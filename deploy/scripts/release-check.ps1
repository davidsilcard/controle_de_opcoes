[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repositoryRoot

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label falhou com código $LASTEXITCODE."
    }
}

$hasDatabaseUrl = -not [string]::IsNullOrWhiteSpace($env:DATABASE_URL)
$legacyRequired = @("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
$hasLegacyConfig = $legacyRequired | ForEach-Object {
    -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($_))
}
$hasLegacyHost = -not [string]::IsNullOrWhiteSpace($env:DB_HOST) `
    -or -not [string]::IsNullOrWhiteSpace($env:POSTGRES_HOST) `
    -or -not [string]::IsNullOrWhiteSpace($env:PGHOST)

if (-not $hasDatabaseUrl -and (-not ($hasLegacyConfig -notcontains $false) -or -not $hasLegacyHost)) {
    throw "Configure DATABASE_URL ou POSTGRES_DB/POSTGRES_USER/POSTGRES_PASSWORD com DB_HOST antes do release check. A suíte PostgreSQL não pode ser ignorada."
}

Invoke-CheckedCommand "Sincronizando dependências bloqueadas" { uv sync --frozen --all-groups }
Invoke-CheckedCommand "Compilando fontes Python" { uv run python -m compileall -q opcoes tests }
Invoke-CheckedCommand "Verificando whitespace não versionado" { git diff --check }
Invoke-CheckedCommand "Verificando whitespace preparado para commit" { git diff --cached --check }

Write-Host "==> Executando suíte completa no PostgreSQL"
$pytestOutput = @(& uv run pytest -q -ra 2>&1)
$pytestOutput | ForEach-Object { Write-Host $_ }
if ($LASTEXITCODE -ne 0) {
    throw "A suíte de testes falhou com código $LASTEXITCODE."
}
if ($pytestOutput -match "Teste requer PostgreSQL configurado") {
    throw "A suíte PostgreSQL foi ignorada. Corrija a configuração do banco antes de publicar."
}

Write-Host "Release check concluído. A CI ainda deve estar verde para o mesmo commit antes do deploy."
