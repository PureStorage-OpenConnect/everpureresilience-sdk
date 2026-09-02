# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Invoke-ErsGroupRun {
    <#
    .SYNOPSIS Triggers a protection run for one or more groups.
    .EXAMPLE Invoke-ErsGroupRun -ErsInstance $Ers -Name G1, G2 -WithMonitor
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name,
        [switch]$WithMonitor,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )

    $resolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) { Write-Warning "Groups not found: $($resolved.NotFound -join ', ')" }
    if ($resolved.Matched.Count -eq 0) { Write-Host 'No matching groups — nothing to run.'; return @{} }

    Write-Host "`nTriggering protection run for $($resolved.Matched.Count) group(s):`n"
    Write-Host ("  {0,-40} {1,-38} {2,-12} {3}" -f 'Group', 'Op ID', 'Status', 'Type')
    Write-Host ('  ' + ('-' * 104))

    $opMap = @{}
    foreach ($group in $resolved.Matched) {
        $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST `
            -Path (Get-ErsProtectPath) `
            -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; application_group_id = $group.id } -Body @{}
        $items = @($result.items)
        $item = if ($items.Count -gt 0) { $items[0] } else { $result }
        $opMap[$group.name] = $item.id
        Write-Host ("  {0,-40} {1,-38} {2,-12} {3}" -f $group.name, $item.id, $item.status, $item.type)
    }

    ($opMap | ConvertTo-Json -Depth 5) | Set-Content -Path (Get-ErsStatePath -FileName (Get-ErsLastRunOpsFileName))

    if ($WithMonitor) {
        foreach ($groupName in $opMap.Keys) {
            $opId = $opMap[$groupName]
            Wait-ErsOperation -ErsInstance $ErsInstance `
                -Path (Get-ErsProtectPath) -OpId $opId -Label "protection: $groupName" `
                -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls | Out-Null
        }
    }

    return $opMap
}
