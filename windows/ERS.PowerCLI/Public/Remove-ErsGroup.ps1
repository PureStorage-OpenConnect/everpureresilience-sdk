# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Remove-ErsGroup {
    <#
    .SYNOPSIS Deletes one or more groups by name.
    .EXAMPLE Remove-ErsGroup -ErsInstance $Ers -Name group1, group2
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name
    )

    $resolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) { Write-Warning "Groups not found: $($resolved.NotFound -join ', ')" }
    if ($resolved.Matched.Count -eq 0) { Write-Host 'No matching groups — nothing to delete.'; return @() }

    $ids = ($resolved.Matched | ForEach-Object { $_.id }) -join ','
    Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method DELETE `
        -Path (Get-ErsGroupsPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; ids = $ids } | Out-Null

    foreach ($g in $resolved.Matched) { Write-Host "Deleted group '$($g.name)'" }
    return @($resolved.Matched | ForEach-Object { $_.name })
}
