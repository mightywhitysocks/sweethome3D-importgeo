<#
  run.ps1 - enchaine le pipeline IGN -> Sweet Home 3D dans l'env conda `sitegeo`.

    .\run.ps1                     # sans argument : menus interactifs
                                  #   (choix du site si plusieurs configs, choix des etapes)
    .\run.ps1 verif               # juste le controle (lecture seule), sans menu
    .\run.ps1 terrain bati        # seulement ces etapes (dans l'ordre donne), sans menu
    .\run.ps1 -Fresh              # force la (re)creation de l'env depuis config\environment.yml
    .\run.ps1 -Site mon-site.toml # utilise cette config au lieu de choisir dans un menu
    .\run.ps1 -CondaEnv autrenom  # utilise un env conda deja existant sous un autre nom
    .\run.ps1 -NonInteractive     # jamais de prompt (comportement historique : toutes
                                  #   les etapes, config\site.local.toml, arret immediat
                                  #   si une etape echoue) - utile depuis un script/hook

  Cree l'env `sitegeo` depuis config\environment.yml s'il est absent.
  Si une etape echoue en mode interactif, propose de reessayer / sauter / arreter.
  La parcelle cible se configure dans config\site.local.toml (git-ignored).
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0, ValueFromRemainingArguments = $true)] [string[]] $Steps,
  [switch] $Fresh,
  [string] $Site,
  [string] $CondaEnv = 'sitegeo',
  [switch] $NonInteractive
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# interactif seulement si on n'a pas coupe le prompt et qu'une console est bien attachee
$Interactive = -not $NonInteractive -and -not [Console]::IsInputRedirected

# --- config de site (parcelle) ---
$configDir = Join-Path $PSScriptRoot 'config'
$localCfg = Join-Path $configDir 'site.local.toml'
if ($Site) {
  if (-not (Test-Path $Site)) { throw "config -Site introuvable : $Site" }
  $env:SITEGEO_CONFIG = (Resolve-Path $Site).Path
  Write-Host ">> config site : $env:SITEGEO_CONFIG" -ForegroundColor Cyan
} else {
  $sites = Get-ChildItem $configDir -Filter '*.toml' -File |
           Where-Object { $_.Name -ne 'site.example.toml' } |
           Sort-Object Name
  if (-not $sites) {
    Copy-Item (Join-Path $configDir 'site.example.toml') $localCfg
    Write-Host ""
    Write-Host ">> 'config\site.local.toml' vient d'etre cree depuis le gabarit." -ForegroundColor Yellow
    Write-Host ">> Renseignez votre parcelle (insee / section / parcels) puis relancez." -ForegroundColor Yellow
    exit 1
  } elseif ($sites.Count -eq 1) {
    $env:SITEGEO_CONFIG = $sites[0].FullName
  } elseif ($Interactive) {
    Write-Host ""
    Write-Host "Plusieurs configs de site trouvees :" -ForegroundColor Cyan
    for ($i = 0; $i -lt $sites.Count; $i++) {
      Write-Host ("  {0}. {1}" -f ($i + 1), $sites[$i].Name)
    }
    $defautIdx = [array]::IndexOf($sites.Name, 'site.local.toml')
    if ($defautIdx -lt 0) { $defautIdx = 0 }
    $reponse = (Read-Host "  -> numero (Entree = $($defautIdx + 1))").Trim()
    $idx = $defautIdx
    if ($reponse) {
      $n = 0
      if (-not [int]::TryParse($reponse, [ref]$n) -or $n -lt 1 -or $n -gt $sites.Count) {
        throw "choix de site invalide : $reponse"
      }
      $idx = $n - 1
    }
    $env:SITEGEO_CONFIG = $sites[$idx].FullName
    Write-Host ">> config site : $($sites[$idx].FullName)" -ForegroundColor Cyan
  } else {
    # non interactif, plusieurs configs, aucune precisee -> comportement historique
    $chosen = $sites | Where-Object { $_.Name -eq 'site.local.toml' } | Select-Object -First 1
    if (-not $chosen) { $chosen = $sites[0] }
    $env:SITEGEO_CONFIG = $chosen.FullName
  }
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
# sentinelle ecrite uniquement apres un `conda env create` reussi : sans elle,
# un env dont la creation a echoue en cours de route (coupure reseau) serait
# pris pour complet aux lancements suivants (python.exe present, paquets
# manquants/partiels -> ImportError confus loin dans src/*.py). Ne s'applique
# qu'a l'env 'sitegeo' auto-gere par ce script -- un env conda different,
# gere manuellement, n'est jamais recree ici.
$depsOk = Join-Path $condaRoot "envs\$CondaEnv\.deps-ok"
if ($Fresh -and $CondaEnv -eq 'sitegeo' -and (Test-Path (Split-Path $envPy))) {
  Write-Host ">> suppression de l'env sitegeo" -ForegroundColor Yellow
  & $conda env remove -n sitegeo -y | Out-Null
}
if ($CondaEnv -ne 'sitegeo') {
  if (-not (Test-Path $envPy)) { throw "env conda '$CondaEnv' introuvable : $envPy" }
} elseif (-not (Test-Path $envPy) -or -not (Test-Path $depsOk)) {
  if (Test-Path $envPy) {
    Write-Host ">> env sitegeo incomplet (creation precedente interrompue) -> recreation" -ForegroundColor Yellow
    & $conda env remove -n sitegeo -y | Out-Null
  }
  Write-Host ">> creation de l'env sitegeo depuis config\environment.yml (long...)" -ForegroundColor Cyan
  & $conda env create -f (Join-Path $PSScriptRoot 'config\environment.yml')
  if (-not (Test-Path $envPy)) { throw "echec de la creation de l'env." }
  New-Item -ItemType File -Path $depsOk -Force | Out-Null
}

# --- etapes ---
$all = 'phase1_cadastre', 'terrain', 'bati', 'vegetation', 'courbes', 'build_home'
if (-not $Steps -or $Steps.Count -eq 0) {
  if ($Interactive) {
    Write-Host ""
    Write-Host "Etapes disponibles :" -ForegroundColor Cyan
    for ($i = 0; $i -lt $all.Count; $i++) {
      Write-Host ("  {0}. {1}" -f ($i + 1), $all[$i])
    }
    $reponse = (Read-Host "  -> numeros separes par des virgules (Entree = toutes ; 'verif' = controle seul)").Trim()
    if (-not $reponse) {
      $run = $all
    } elseif ($reponse -eq 'verif') {
      $run = @('verif')
    } else {
      $run = $reponse -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | ForEach-Object {
        $n = 0
        if (-not [int]::TryParse($_, [ref]$n) -or $n -lt 1 -or $n -gt $all.Count) {
          throw "choix d'etape invalide : $_"
        }
        $all[$n - 1]
      }
      if (-not $run) { throw "aucune etape selectionnee" }
    }
  } else {
    $run = $all
  }
} elseif ($Steps.Count -eq 1 -and $Steps[0] -eq 'verif') {
  $run = @('verif')
} else {
  $run = $Steps | ForEach-Object { ($_ -replace '\.py$', '') }
}

foreach ($s in $run) {
  $script = Join-Path $PSScriptRoot "src\$s.py"
  if (-not (Test-Path $script)) { throw "script inconnu : src\$s.py" }
  $rejoue = $true
  while ($rejoue) {
    $rejoue = $false
    Write-Host "`n=== $s.py ===" -ForegroundColor Green
    & $envPy $script
    if ($LASTEXITCODE -eq 0) { break }
    if (-not $Interactive) { throw "$s.py a echoue (code $LASTEXITCODE)" }
    Write-Host "`n!! $s.py a echoue (code $LASTEXITCODE)" -ForegroundColor Red
    do {
      $choix = (Read-Host "  -> (r)eessayer / (s)auter / (a)rreter [r]").Trim().ToLower()
      if (-not $choix) { $choix = 'r' }
    } while ($choix -notin @('r', 's', 'a'))
    if ($choix -eq 'r') { $rejoue = $true }
    elseif ($choix -eq 'a') { throw "$s.py a echoue (code $LASTEXITCODE) - arret demande" }
    # 's' : on laisse $rejoue a $false, l'etape est sautee
  }
}
Write-Host "`n>> termine." -ForegroundColor Green
