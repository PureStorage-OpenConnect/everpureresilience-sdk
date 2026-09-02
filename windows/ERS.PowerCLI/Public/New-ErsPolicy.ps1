# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function New-ErsPolicy {
    <#
    .SYNOPSIS Creates a service level policy. RPO is in minutes; retention and RTO are in hours.
    .EXAMPLE New-ErsPolicy -ErsInstance $Ers -Name policy1 -RpoMinutes 15 -TargetType vmw -LocalRetentionHours 24 -RemoteRetentionHours 72 -EstimatedRtoHours 1
    .EXAMPLE New-ErsPolicy -ErsInstance $Ers -Name policy1 -RpoMinutes 60 -SourceType vmw -TargetType aws -LocalRetentionHours 24 -RemoteRetentionHours 24 -EstimatedRtoHours 1
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$RpoMinutes,
        [Parameter(Mandatory)][ValidateSet('vmw','aws')][string]$TargetType,
        [ValidateSet('vmw','aws')][string]$SourceType = 'vmw',
        [Parameter(Mandatory)][int]$LocalRetentionHours,
        [Parameter(Mandatory)][int]$RemoteRetentionHours,
        [Parameter(Mandatory)][int]$EstimatedRtoHours,
        [string]$Description = ''
    )

    $typeMap = @{ vmw = 'VSPHERE'; aws = 'AWS' }
    $srcSiteType = $typeMap[$SourceType]
    $tgtSiteType = $typeMap[$TargetType]
    $body = @{
        name = $Name; description = $Description
        rpo = $RpoMinutes * 60000
        replication_strategy = @{
            ordinal = 0; site_type = $srcSiteType
            retention = $LocalRetentionHours * 3600000
            replication_targets = @(@{
                ordinal = 1; site_type = $tgtSiteType
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
