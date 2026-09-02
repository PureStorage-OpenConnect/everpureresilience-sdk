# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Invoke-ErsPlanFailback {
    <#
    .SYNOPSIS Runs failback (sync→cutover→promotion) for one or more plans.
    .EXAMPLE Invoke-ErsPlanFailback -ErsInstance $Ers -Name P1 -Site prod-site
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name,
        [Parameter(Mandatory)][string]$Site,
        [string[]]$SnapshotIds,
        [switch]$WithMonitor,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )
    return Invoke-ErsPlanAction -ErsInstance $ErsInstance -Action 'failback' -Name $Name `
        -SnapshotIds $SnapshotIds -Site $Site -WithMonitor:$WithMonitor `
        -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
}
