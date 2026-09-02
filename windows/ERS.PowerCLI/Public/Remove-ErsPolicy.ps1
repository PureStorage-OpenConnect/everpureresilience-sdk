# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Remove-ErsPolicy {
    <#
    .SYNOPSIS Deletes one or more policies by name.
    .EXAMPLE Remove-ErsPolicy -ErsInstance $Ers -Name policy1, policy2
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name
    )

    $resolved = Resolve-ErsPolicies -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) { Write-Warning "Policies not found: $($resolved.NotFound -join ', ')" }
    if ($resolved.Matched.Count -eq 0) { Write-Host 'No matching policies — nothing to delete.'; return @() }

    $ids = ($resolved.Matched | ForEach-Object { $_.id }) -join ','
    Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method DELETE `
        -Path (Get-ErsPoliciesPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; ids = $ids } | Out-Null

    foreach ($p in $resolved.Matched) { Write-Host "Deleted policy '$($p.name)'" }
    return @($resolved.Matched | ForEach-Object { $_.name })
}
