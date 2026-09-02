# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Invoke-ErsPlanFailover {
    <#
    .SYNOPSIS Runs test or production failover for one or more recovery plans (parallel).
    .EXAMPLE Invoke-ErsPlanFailover -ErsInstance $Ers -Kind Test -Name P1, P2 -WithMonitor
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][ValidateSet('Test', 'Prod')][string]$Kind,
        [Parameter(Mandatory)][string[]]$Name,
        [string[]]$SnapshotIds,
        [switch]$WithMonitor,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )
    $action = if ($Kind -eq 'Test') { 'test_failover' } else { 'prod_failover' }
    return Invoke-ErsPlanAction -ErsInstance $ErsInstance -Action $action -Name $Name `
        -SnapshotIds $SnapshotIds -WithMonitor:$WithMonitor -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
}
