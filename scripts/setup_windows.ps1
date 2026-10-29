param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$appDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$venv = Join-Path $appDir '.venv'
if (-not (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe'))) {
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed; use a Python distribution with venv and Tk.' }
}
$pythonExe = Join-Path $venv 'Scripts\python.exe'
& $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $appDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
$shell = New-Object -ComObject WScript.Shell
$destinations = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs')
)
foreach ($destination in $destinations) {
    $link = $shell.CreateShortcut((Join-Path $destination 'Weekly Schedule (Public).lnk'))
    $link.TargetPath = Join-Path $venv 'Scripts\pythonw.exe'
    $link.Arguments = '"' + (Join-Path $appDir 'widget.py') + '"'
    $link.WorkingDirectory = $appDir
    $link.IconLocation = Join-Path $appDir 'widget.ico'
    $link.Save()
}
Write-Output 'Installed shortcuts. Open the widget and configure your own calendar in Settings.'
Write-Output 'SHAD background synchronization is optional; see README.md.'
