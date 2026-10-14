# Compatibility entry point for existing WSL installation instructions.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Bundle,
    [string]$InstallRoot
)
& (Join-Path $PSScriptRoot 'distribution/install.ps1') @PSBoundParameters
