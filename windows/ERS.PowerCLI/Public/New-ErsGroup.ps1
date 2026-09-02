# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function New-ErsGroup {
    <#
    .SYNOPSIS Creates an application group.
    .EXAMPLE New-ErsGroup -ErsInstance $Ers -Name group1 -WithPolicy policy1 -SourceSite site1 -TargetSite site2
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$WithPolicy,
        [Parameter(Mandatory)][string]$SourceSite,
        [Parameter(Mandatory)][string]$TargetSite
    )

    $policyResolved = Resolve-ErsPolicies -ErsInstance $ErsInstance -Names @($WithPolicy)
    if ($policyResolved.Matched.Count -eq 0) { throw "Policy '$WithPolicy' not found" }
    $sourceSiteId = Resolve-ErsSiteId -ErsInstance $ErsInstance -SiteName $SourceSite
    if (-not $sourceSiteId) { throw "Source site '$SourceSite' not found" }
    $targetSiteId = Resolve-ErsSiteId -ErsInstance $ErsInstance -SiteName $TargetSite
    if (-not $targetSiteId) { throw "Target site '$TargetSite' not found" }

    $body = @{
        name = $Name; description = ''; backup_start_time = 0
        is_consistency_group = $false; has_cloud_pre_conversion = $false
        has_parallel_boot = $true; is_infrastructure_group = $false
        domain_name = $null
        service_level_policy_id = $policyResolved.Matched[0].id
        source_site_id = $sourceSiteId
        target_site_ids = @($targetSiteId)
    }

    $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST `
        -Path (Get-ErsGroupsPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId } -Body $body
    $item = @($result.items)[0]
    Write-Host "Created group '$Name' (id: $($item.id))"
    return $item
}
