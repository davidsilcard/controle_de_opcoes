[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Comando obrigatorio nao encontrado: $Name. Consulte o README para a instalacao inicial."
    }
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    $result = & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha no Git: git $($Arguments -join ' ')"
    }
    return $result
}

function Get-WorkflowRun {
    param([Parameter(Mandatory = $true)][string]$CommitSha)

    $json = & gh run list --workflow tests.yml --commit $CommitSha --limit 1 --json databaseId,status,conclusion,headSha,url
    if ($LASTEXITCODE -ne 0) {
        throw "Nao foi possivel consultar o GitHub Actions. Execute 'gh auth status' e conclua a autenticacao, se necessario."
    }

    $runs = @($json | ConvertFrom-Json)
    if ($runs.Count -eq 0) {
        throw "Nenhuma execucao do workflow Testes PostgreSQL foi encontrada para o commit $CommitSha. O release foi interrompido."
    }
    return $runs[0]
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
Push-Location $repositoryRoot

try {
    Require-Command git
    Require-Command gh

    $sshExecutable = Join-Path $env:WINDIR "System32\\OpenSSH\\ssh.exe"
    if (-not (Test-Path $sshExecutable)) {
        Require-Command ssh
        $sshExecutable = "ssh"
    }

    Write-Host "[1/6] Conferindo alteracoes locais..."
    $changes = Invoke-Git status --porcelain
    if ($changes) {
        throw "Ha alteracoes locais nao versionadas. Revise, teste, faca commit e push antes do release."
    }

    $branch = (Invoke-Git branch --show-current).Trim()
    if ($branch -ne "main") {
        throw "O release so pode sair da branch main. Branch atual: $branch."
    }

    Write-Host "[2/6] Conferindo se main esta publicada..."
    Invoke-Git fetch origin main | Out-Null
    $localSha = (Invoke-Git rev-parse HEAD).Trim()
    $remoteSha = (Invoke-Git rev-parse origin/main).Trim()
    if ($localSha -ne $remoteSha) {
        throw "O commit local ($localSha) difere de origin/main ($remoteSha). Faca push ou atualize a main antes do release."
    }

    Write-Host "[3/6] Conferindo o CI do mesmo commit..."
    $run = Get-WorkflowRun -CommitSha $localSha
    if ($run.status -ne "completed") {
        Write-Host "O CI ainda esta em execucao; aguardando a conclusao: $($run.url)"
        & gh run watch $run.databaseId --exit-status
        if ($LASTEXITCODE -ne 0) {
            throw "O workflow Testes PostgreSQL falhou ou foi cancelado. A VPS nao foi alterada."
        }
        $run = Get-WorkflowRun -CommitSha $localSha
    }
    if ($run.conclusion -ne "success") {
        throw "O workflow Testes PostgreSQL terminou como '$($run.conclusion)'. A VPS nao foi alterada: $($run.url)"
    }

    Write-Host "[4/6] CI aprovado para $localSha. Atualizando a VPS pelo script oficial..."
    $deployCommand = "cd /home/david/apps/controle_de_opcoes && bash deploy/scripts/update-vps.sh"
    & $sshExecutable hostinger-opcoes $deployCommand
    if ($LASTEXITCODE -ne 0) {
        throw "O script oficial de deploy falhou. Veja o log acima; nenhum comando alternativo deve ser usado."
    }

    Write-Host "[5/6] Validando versao e servicos publicados..."
    $validationCommand = "cd /home/david/apps/controle_de_opcoes && git rev-parse --short HEAD && curl -fsSI --max-time 10 http://127.0.0.1:8000/login && curl -fsS --max-time 10 http://127.0.0.1:8011/health"
    $validation = & $sshExecutable hostinger-opcoes $validationCommand
    if ($LASTEXITCODE -ne 0) {
        throw "O deploy terminou, mas a validacao final da VPS falhou. Confira o resultado acima antes de registrar operacoes."
    }

    $shortSha = $localSha.Substring(0, 7)
    if (-not ($validation -match "(?m)^$([regex]::Escape($shortSha))$")) {
        throw "A VPS respondeu, mas esta em uma versao diferente da publicada ($shortSha). Registro interrompido."
    }

    Write-Host "[6/6] Release concluido: $shortSha, login e edge saudaveis."
}
finally {
    Pop-Location
}
