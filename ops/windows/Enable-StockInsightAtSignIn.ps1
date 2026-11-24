$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$venvPython = (Resolve-Path (Join-Path $project '.venv\Scripts\python.exe')).Path
$oldTarget = (Resolve-Path (Join-Path $project '.venv\Scripts\pythonw.exe')).Path
$runtime = & $venvPython -I -c "import sys; print(sys.base_prefix)"
if ($LASTEXITCODE -ne 0 -or -not $runtime) { throw 'Cannot locate the project Python runtime.' }
$python = (Resolve-Path (Join-Path $runtime 'pythonw.exe')).Path
$entry = (Resolve-Path (Join-Path $PSScriptRoot 'start-tray.pyw')).Path
$arguments = '-I -B "' + $entry + '"'
$startup = [Environment]::GetFolderPath('Startup')
$linkPath = Join-Path $startup 'Stock Insight.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
if (Test-Path -LiteralPath $linkPath) {
    $old = $link.TargetPath -eq $oldTarget -and $link.Arguments -eq '-B -m stockinsight.launcher --background'
    $ours = $link.Arguments -eq $arguments -and $link.WorkingDirectory -eq $project
    if (-not ($old -or $ours)) { throw 'A different Stock Insight startup shortcut already exists.' }
}
$link.TargetPath = $python
$link.Arguments = $arguments
$link.WorkingDirectory = $project
$link.Description = 'Monitor the personal Stock Insight watchlist after Windows sign-in.'
$link.Save()
$saved = $shell.CreateShortcut($linkPath)
if ($saved.TargetPath -ne $python -or $saved.Arguments -ne $arguments -or $saved.WorkingDirectory -ne $project) {
    throw 'Windows did not save the requested startup shortcut.'
}
Start-Process -FilePath $linkPath -WindowStyle Hidden
Write-Output "Stock Insight sign-in shortcut: $linkPath"
