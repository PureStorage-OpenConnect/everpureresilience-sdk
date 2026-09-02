# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function New-ErsPlan {
    <#
    .SYNOPSIS Creates a recovery plan with the specified groups.
    .EXAMPLE New-ErsPlan -ErsInstance $Ers -Name plan1 -WithGroups group1,group2 -TargetSite site2
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$WithGroups,
        [Parameter(Mandatory)][string]$TargetSite
    )

    $groupResolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names $WithGroups
    if ($groupResolved.NotFound.Count -gt 0) { throw "Groups not found: $($groupResolved.NotFound -join ', ')" }
    $targetSiteId = Resolve-ErsSiteId -ErsInstance $ErsInstance -SiteName $TargetSite
    if (-not $targetSiteId) { throw "Target site '$TargetSite' not found" }

    $body = @{
        name = $Name; description = ''
        group_ids = @($groupResolved.Matched | ForEach-Object { $_.id })
        target_site_id = $targetSiteId
    }

    $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST `
        -Path (Get-ErsPlansPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId } -Body $body
    $item = @($result.items)[0]
    Write-Host "Created plan '$Name' (id: $($item.id))"
    return $item
}
