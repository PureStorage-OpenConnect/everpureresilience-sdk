# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function New-ErsPolicy {
    <#
    .SYNOPSIS Creates a service level policy.
    .EXAMPLE New-ErsPolicy -ErsInstance $Ers -Name policy1 -RpoMinutes 15 -TargetType vmw -LocalRetentionHours 24 -RemoteRetentionHours 72
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$RpoMinutes,
        [Parameter(Mandatory)][ValidateSet('vmw','aws')][string]$TargetType,
        [Parameter(Mandatory)][int]$LocalRetentionHours,
        [Parameter(Mandatory)][int]$RemoteRetentionHours,
        [int]$EstimatedRtoHours = 0,
        [string]$Description = ''
    )

    $siteType = if ($TargetType -eq 'vmw') { 'VSPHERE' } else { 'AWS' }
    $body = @{
        name = $Name; description = $Description
        rpo = $RpoMinutes * 60000
        replication_strategy = @{
            ordinal = 0; site_type = $siteType
            retention = $LocalRetentionHours * 3600000
            replication_targets = @(@{
                ordinal = 1; site_type = $siteType
                retention = $RemoteRetentionHours * 3600000
                estimated_rto = $EstimatedRtoHours * 3600000
                replication_targets = @()
            })
        }
    }

    $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST `
        -Path (Get-ErsPoliciesPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId } -Body $body
    $item = @($result.items)[0]
    Write-Host "Created policy '$Name' (id: $($item.id))"
    return $item
}
