# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Add-ErsPlanGroup {
    <#
    .SYNOPSIS Adds groups to an existing plan.
    .EXAMPLE Add-ErsPlanGroup -ErsInstance $Ers -PlanName plan1 -GroupName group3, group4
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$PlanName,
        [Parameter(Mandatory)][string[]]$GroupName
    )

    $planResolved = Resolve-ErsPlans -ErsInstance $ErsInstance -Names @($PlanName)
    if ($planResolved.Matched.Count -eq 0) { throw "Plan '$PlanName' not found" }
    $plan = $planResolved.Matched[0]

    $groupResolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names $GroupName
    if ($groupResolved.NotFound.Count -gt 0) { throw "Groups not found: $($groupResolved.NotFound -join ', ')" }

    $existingIds = @($plan.groups | ForEach-Object { $_.id })
    $newIds = @($groupResolved.Matched | ForEach-Object { $_.id })
    $allIds = @($existingIds + $newIds | Select-Object -Unique)

    $body = @{ name = $plan.name; description = ($plan.description ?? ''); group_ids = $allIds }
    Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method PATCH `
        -Path (Get-ErsPlansPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; ids = $plan.id } -Body $body | Out-Null

    Write-Host "Added group(s) $($GroupName -join ', ') to plan '$PlanName'"
}
