# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

# Private: shared name-resolution helpers for group/plan/site/policy cmdlets.
# Uses limit=300 (confirmed API max) and names= filter where supported.

function Resolve-ErsGroups {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Names)
    $params = @{ deployment_id = $ErsInstance.DeploymentId; names = ($Names -join ',') }
    $all = @(Invoke-ErsApiGetAll -ErsInstance $ErsInstance -Path (Get-ErsGroupsPath) -BaseParams $params)
    $lower = $Names | ForEach-Object { $_.ToLower() }
    $matched  = $all | Where-Object { $_.name.ToLower() -in $lower }
    $foundLower = @($matched | ForEach-Object { $_.name.ToLower() })
    $notFound = $Names | Where-Object { $_.ToLower() -notin $foundLower }
    return @{ Matched = @($matched); NotFound = @($notFound) }
}

function Resolve-ErsPlans {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Names)
    $params = @{ deployment_id = $ErsInstance.DeploymentId; names = ($Names -join ',') }
    $all = @(Invoke-ErsApiGetAll -ErsInstance $ErsInstance -Path (Get-ErsPlansPath) -BaseParams $params)
    $lower = $Names | ForEach-Object { $_.ToLower() }
    $matched  = $all | Where-Object { $_.name.ToLower() -in $lower }
    $foundLower = @($matched | ForEach-Object { $_.name.ToLower() })
    $notFound = $Names | Where-Object { $_.ToLower() -notin $foundLower }
    return @{ Matched = @($matched); NotFound = @($notFound) }
}

function Resolve-ErsPolicies {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Names)
    $params = @{ deployment_id = $ErsInstance.DeploymentId }
    $all = @(Invoke-ErsApiGetAll -ErsInstance $ErsInstance -Path (Get-ErsPoliciesPath) -BaseParams $params)
    $lower = $Names | ForEach-Object { $_.ToLower() }
    $matched  = $all | Where-Object { $_.name.ToLower() -in $lower }
    $foundLower = @($matched | ForEach-Object { $_.name.ToLower() })
    $notFound = $Names | Where-Object { $_.ToLower() -notin $foundLower }
    return @{ Matched = @($matched); NotFound = @($notFound) }
}

function Resolve-ErsSiteId {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string]$SiteName)
    $params = @{ deployment_id = $ErsInstance.DeploymentId }
    $all = @(Invoke-ErsApiGetAll -ErsInstance $ErsInstance -Path (Get-ErsSitesPath) -BaseParams $params)
    $match = $all | Where-Object { $_.name.ToLower() -eq $SiteName.ToLower() } | Select-Object -First 1
    if ($match) { return $match.id }
    return $null
}

function Get-ErsVmInventory {
    <#
    .SYNOPSIS
        Fetches the full VM inventory for a site, with offset-based pagination.
    #>
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$SiteId,
        [string]$TargetSiteType = 'VSPHERE'
    )
    $params = @{
        deployment_id   = $ErsInstance.DeploymentId
        tag_ids         = ''
        site_ids        = $SiteId
        target_site_type = $TargetSiteType
    }
    return @(Invoke-ErsApiGetAll -ErsInstance $ErsInstance -Path (Get-ErsVmInventoryPath) -BaseParams $params)
}

function Get-ErsEnrolledVms {
    <#
    .SYNOPSIS
        Fetches all enrolled VMs for a group, with offset-based pagination.
        Uses names= for exact name lookup, search= for wildcard.
    #>
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$GroupId,
        [string[]]$VmNames,
        [string]$WildcardPattern
    )
    $params = @{
        deployment_id       = $ErsInstance.DeploymentId
        application_group_ids = $GroupId
    }
    if ($WildcardPattern) {
        $params['search'] = $WildcardPattern.Replace('*', '')
    } elseif ($VmNames) {
        $params['names'] = ($VmNames -join ',')
    }
    return @(Invoke-ErsApiGetAll -ErsInstance $ErsInstance -Path (Get-ErsEnrolledVmsPath) -BaseParams $params)
}

function Get-ErsLatestSnapshotIds {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string]$PlanId)
    $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET `
        -Path (Get-ErsSnapshotsPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $PlanId }
    $latest = @{}
    foreach ($snap in @($data.items)) {
        $groupId = $snap.application_group.id
        $createdAt = $snap.created_at
        if (-not $latest.ContainsKey($groupId) -or $createdAt -gt $latest[$groupId].CreatedAt) {
            $latest[$groupId] = @{ SnapId = $snap.id; CreatedAt = $createdAt; GroupName = $snap.application_group.name }
        }
    }
    return $latest
}

function ConvertTo-ErsUnixMillisDateString {
    param([long]$MillisSinceEpoch)
    if (-not $MillisSinceEpoch) { return '-' }
    return [DateTimeOffset]::FromUnixTimeMilliseconds($MillisSinceEpoch).UtcDateTime.ToString('yyyy-MM-dd HH:mm:ss "UTC"')
}
