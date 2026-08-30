<#
  run.ps1 - enchaine le pipeline IGN -> Sweet Home 3D dans l'env conda `sitegeo`.

    .\run.ps1                     # pipeline complet :
                                  #   phase1_cadastre -> terrain -> bati -> vegetation -> courbes -> build_home
    .\run.ps1 verif               # juste le controle (lecture seule)
    .\run.ps1 terrain bati        # seulement ces etapes (dans l'ordre donne)
    .\run.ps1 -Fresh              # force la (re)creation de l'env depuis config\environment.yml
    .\run.ps1 -Site mon-site.toml # utilise cette config au lieu de config\site.local.toml
    .\run.ps1 -CondaEnv autrenom  # utilise un env conda deja existant sous un autre nom

  Cree l'env `sitegeo` depuis config\environment.yml s'il est absent.
  La parcelle cible se configure dans config\site.local.toml (git-ignored).
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0, ValueFromRemainingArguments = $true)] [string[]] $Steps,
  [switch] $Fresh,
  [string] $Site,
  [string] $CondaEnv = 'sitegeo'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# --- config de site (parcelle) ---
if ($Site) {
  if (-not (Test-Path $Site)) { throw "config -Site introuvable : $Site" }
  $env:SITEGEO_CONFIG = (Resolve-Path $Site).Path
  Write-Host ">> config site : $env:SITEGEO_CONFIG" -ForegroundColor Cyan
}
$localCfg = Join-Path $PSScriptRoot 'config\site.local.toml'
if (-not $env:SITEGEO_CONFIG -and -not (Test-Path $localCfg)) {
  Copy-Item (Join-Path $PSScriptRoot 'config\site.example.toml') $localCfg
  Write-Host ""
  Write-Host ">> 'config\site.local.toml' vient d'etre cree depuis le gabarit." -ForegroundColor Yellow
  Write-Host ">> Renseignez votre parcelle (insee / section / parcels) puis relancez." -ForegroundColor Yellow
  exit 1
}

# --- localiser conda ---
$condaRoots = @($env:CONDA_PREFIX_1, $env:CONDA_PREFIX,
                "$env:USERPROFILE\anaconda3", "$env:USERPROFILE\miniconda3",
                "$env:USERPROFILE\miniforge3", "$env:ProgramData\anaconda3",
                "$env:ProgramData\miniconda3") |
              Where-Object { $_ -and (Test-Path (Join-Path $_ 'Scripts\conda.exe')) }
$condaRoot = $condaRoots | Select-Object -First 1
if (-not $condaRoot) { throw "conda introuvable - installe Anaconda ou Miniconda." }
$conda = Join-Path $condaRoot 'Scripts\conda.exe'

$envPy = Join-Path $condaRoot "envs\$CondaEnv\python.exe"
if ($Fresh -and $CondaEnv -eq 'sitegeo' -and (Test-Path (Split-Path $envPy))) {
  Write-Host ">> suppression de l'env sitegeo" -ForegroundColor Yellow
  & $conda env remove -n sitegeo -y | Out-Null
}
if (-not (Test-Path $envPy)) {
  if ($CondaEnv -ne 'sitegeo') { throw "env conda '$CondaEnv' introuvable : $envPy" }
  Write-Host ">> creation de l'env sitegeo depuis config\environment.yml (long...)" -ForegroundColor Cyan
  & $conda env create -f (Join-Path $PSScriptRoot 'config\environment.yml')
  if (-not (Test-Path $envPy)) { throw "echec de la creation de l'env." }
}

# --- etapes ---
$all = 'phase1_cadastre', 'terrain', 'bati', 'vegetation', 'courbes', 'build_home'
if (-not $Steps -or $Steps.Count -eq 0) {
  $run = $all
} elseif ($Steps.Count -eq 1 -and $Steps[0] -eq 'verif') {
  $run = @('verif')
} else {
  $run = $Steps | ForEach-Object { ($_ -replace '\.py$', '') }
}

foreach ($s in $run) {
  $script = Join-Path $PSScriptRoot "src\$s.py"
  if (-not (Test-Path $script)) { throw "script inconnu : src\$s.py" }
  Write-Host "`n=== $s.py ===" -ForegroundColor Green
  & $envPy $script
  if ($LASTEXITCODE -ne 0) { throw "$s.py a echoue (code $LASTEXITCODE)" }
}
Write-Host "`n>> termine." -ForegroundColor Green
