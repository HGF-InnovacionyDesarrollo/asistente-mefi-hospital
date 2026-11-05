param([string]$RutaRaiz = "")
if (-not $RutaRaiz) {
    $candidata = Join-Path $PSScriptRoot "..\.."
    if (Test-Path (Join-Path $candidata "MEFI.bat")) {
        $RutaRaiz = (Resolve-Path $candidata).Path
    } else {
        $RutaRaiz = "C:\MVP - MEFI"
    }
}
$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop 'MEFI - Asesor Clinico.lnk'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = Join-Path $RutaRaiz 'MEFI.bat'
$sc.WorkingDirectory = $RutaRaiz
$sc.Description = 'Asesor Clinico MEFI - digitalizacion y analisis de CTG'
$sc.Save()
Write-Output "Creado: $lnkPath -> $RutaRaiz\MEFI.bat"
