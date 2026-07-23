# Copyright 2026 [Your Organization]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

function Invoke-ErsPlanFailback {
    <#
    .SYNOPSIS
        Runs failback for one or more recovery plans: synchronization,
        cutover, and promotion, in sequence — stopping at the first step
        that doesn't succeed. Requires prod_failover to have SUCCEEDED
        first (checked via ~/.ers/state).
    .EXAMPLE
        Invoke-ErsPlanFailback -ErsInstance $Ers -Name P1 -Site DC.DEV
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name,
        [Parameter(Mandatory)][string]$Site,
        [string[]]$SnapshotIds,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )
    return Invoke-ErsPlanAction -ErsInstance $ErsInstance -Action 'failback' -Name $Name `
        -Site $Site -SnapshotIds $SnapshotIds -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
}
