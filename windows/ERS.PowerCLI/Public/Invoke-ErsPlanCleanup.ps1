# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Invoke-ErsPlanCleanup {
    <#
    .SYNOPSIS Runs plan cleanup (reverts test failover) for one or more plans (parallel).
    .EXAMPLE Invoke-ErsPlanCleanup -ErsInstance $Ers -Name P1, P2 -WithMonitor
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name,
        [switch]$WithMonitor,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )
    return Invoke-ErsPlanAction -ErsInstance $ErsInstance -Action 'cleanup' -Name $Name `
        -WithMonitor:$WithMonitor -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
}
