# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Remove-ErsPlanGroup {
    <#
    .SYNOPSIS Removes groups from a plan.
    .EXAMPLE Remove-ErsPlanGroup -ErsInstance $Ers -PlanName plan1 -GroupName group1
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
    $removeIds = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($g in $groupResolved.Matched) { [void]$removeIds.Add($g.id) }

    $remainingIds = @($plan.groups | ForEach-Object { $_.id } | Where-Object { -not $removeIds.Contains($_) })

    $body = @{ name = $plan.name; description = ($plan.description ?? ''); group_ids = $remainingIds }
    Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method PATCH `
        -Path (Get-ErsPlansPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; ids = $plan.id } -Body $body | Out-Null

    Write-Host "Removed group(s) $($GroupName -join ', ') from plan '$PlanName'"
}
