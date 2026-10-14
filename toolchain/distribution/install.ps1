# Windows entry point: install the Linux toolchain in the default WSL distribution.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [string]$InstallRoot
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is required. Run wsl --install, restart Windows, then open the Linux distribution once to finish setup.'
}
function ConvertTo-WslPath([string]$Path) {
    $Resolved = (Resolve-Path -LiteralPath $Path).Path
    $Converted = & wsl.exe --exec wslpath -a -u $Resolved
    if ($LASTEXITCODE -ne 0) { throw "Cannot convert path for WSL: $Resolved" }
    return $Converted
}
$Script = ConvertTo-WslPath (Join-Path $PSScriptRoot 'install.sh')
$InputPath = ConvertTo-WslPath $Bundle
$Arguments = @('--exec', 'sh', $Script, $InputPath)
if ($InstallRoot) { $Arguments += $InstallRoot }
& wsl.exe @Arguments
if ($LASTEXITCODE -ne 0) { throw 'Maylang installation failed in WSL.' }
Write-Host 'Run Maylang commands inside WSL. InstallRoot, when supplied, is a Linux path.'
