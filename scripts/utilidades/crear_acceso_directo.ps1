$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop 'MEFI - Asesor Clinico.lnk'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = 'C:\MVP - MEFI\MEFI.bat'
$sc.WorkingDirectory = 'C:\MVP - MEFI'
$sc.Description = 'Asesor Clinico MEFI - digitalizacion y analisis de CTG'
$sc.Save()
Write-Output "Creado: $lnkPath"
