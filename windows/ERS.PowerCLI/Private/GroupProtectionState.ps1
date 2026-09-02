# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

# Private: shared implementation for Enable-ErsGroup/Disable-ErsGroup.
# Uses batch PATCH at ?ids=id1,id2 (confirmed API pattern) instead of
# per-group PATCH at /{id}.

function Set-ErsGroupProtectionState {
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name,
        [Parameter(Mandatory)][bool]$Enable
    )
    $resolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) { Write-Warning "Groups not found: $($resolved.NotFound -join ', ')" }
    if ($resolved.Matched.Count -eq 0) { Write-Host 'No matching groups — nothing to update.'; return @() }

    $ids = ($resolved.Matched | ForEach-Object { $_.id }) -join ','
    $body = @{ protection_state = if ($Enable) { 'ENABLED' } else { 'DISABLED' } }
    Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method PATCH `
        -Path (Get-ErsGroupsPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; ids = $ids } -Body $body | Out-Null

    $state = if ($Enable) { 'enabled' } else { 'disabled' }
    foreach ($g in $resolved.Matched) { Write-Host "  $($g.name): $state" }
    return @($resolved.Matched | ForEach-Object { $_.name })
}
