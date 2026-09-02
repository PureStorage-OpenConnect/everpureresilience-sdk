# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

# ERS.PowerCLI — root module.
# Loads classes first, then private helpers, then public cmdlets.

$moduleRoot = $PSScriptRoot

foreach ($folder in @('Classes', 'Private', 'Public')) {
    $path = Join-Path $moduleRoot $folder
    if (Test-Path $path) {
        $files = Get-ChildItem -Path $path -Filter '*.ps1' | Sort-Object Name
        foreach ($file in $files) {
            . $file.FullName
        }
    }
}

Export-ModuleMember -Function @(
    # Session
    'New-ErsInstance', 'Register-ErsSite',
    # Policy CRUD
    'Get-ErsPolicy', 'New-ErsPolicy', 'Remove-ErsPolicy',
    # Group CRUD + actions
    'Get-ErsGroup', 'New-ErsGroup', 'Remove-ErsGroup',
    'Enable-ErsGroup', 'Disable-ErsGroup',
    'Invoke-ErsGroupRun', 'Wait-ErsGroup',
    # Plan CRUD + actions
    'Get-ErsPlan', 'New-ErsPlan', 'Remove-ErsPlan',
    'Add-ErsPlanGroup', 'Remove-ErsPlanGroup',
    'Invoke-ErsPlanFailover', 'Invoke-ErsPlanCleanup', 'Invoke-ErsPlanFailback',
    'Wait-ErsPlan', 'Get-ErsPlanSnapshot',
    # VM enrollment
    'Get-ErsVm', 'Add-ErsGroupVm', 'Remove-ErsGroupVm',
    # vCenter site operations
    'Get-ErsSite',
    'New-ErsSiteVM', 'Remove-ErsSiteVM', 'Test-ErsSiteVM',
    'Get-ErsSiteNetwork', 'Get-ErsSiteFolder',
    'Start-ErsVM', 'Stop-ErsVM', 'Connect-ErsVMNetwork',
    'Export-ErsTag', 'Import-ErsTag',
    # Workflows
    'Invoke-ErsManagedFailover', 'Invoke-ErsManagedFailback',
    'Invoke-ErsSystemTest'
)
