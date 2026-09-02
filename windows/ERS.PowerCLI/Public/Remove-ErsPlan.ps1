# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Remove-ErsPlan {
    <#
    .SYNOPSIS Deletes one or more plans by name.
    .EXAMPLE Remove-ErsPlan -ErsInstance $Ers -Name plan1, plan2
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name
    )

    $resolved = Resolve-ErsPlans -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) { Write-Warning "Plans not found: $($resolved.NotFound -join ', ')" }
    if ($resolved.Matched.Count -eq 0) { Write-Host 'No matching plans — nothing to delete.'; return @() }

    $ids = ($resolved.Matched | ForEach-Object { $_.id }) -join ','
    Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method DELETE `
        -Path (Get-ErsPlansPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; ids = $ids } | Out-Null

    foreach ($p in $resolved.Matched) { Write-Host "Deleted plan '$($p.name)'" }
    return @($resolved.Matched | ForEach-Object { $_.name })
}
