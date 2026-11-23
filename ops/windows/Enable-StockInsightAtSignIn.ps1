$ErrorActionPreference = 'Stop'
$project = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = (Resolve-Path (Join-Path $project '.venv\Scripts\pythonw.exe')).Path
$startup = [Environment]::GetFolderPath('Startup')
$linkPath = Join-Path $startup 'Stock Insight.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($linkPath)
if ((Test-Path -LiteralPath $linkPath) -and $link.TargetPath -ne $python) {
    throw 'A different Stock Insight startup shortcut already exists.'
}
$arguments = '-B -m stockinsight.launcher --background'
$link.TargetPath = $python
$link.Arguments = $arguments
$link.WorkingDirectory = $project
$link.Description = 'Monitor the personal Stock Insight watchlist after Windows sign-in.'
$link.Save()
$saved = $shell.CreateShortcut($linkPath)
if ($saved.TargetPath -ne $python -or $saved.Arguments -ne $arguments -or $saved.WorkingDirectory -ne $project) {
    throw 'Windows did not save the requested startup shortcut.'
}
Start-Process -FilePath $saved.TargetPath -ArgumentList $saved.Arguments -WorkingDirectory $saved.WorkingDirectory -WindowStyle Hidden
Write-Output "Stock Insight sign-in shortcut: $linkPath"
