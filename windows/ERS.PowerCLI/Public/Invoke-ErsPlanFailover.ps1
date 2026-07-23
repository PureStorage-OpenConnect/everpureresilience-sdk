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

function Invoke-ErsPlanFailover {
    <#
    .SYNOPSIS
        Runs test or production failover for one or more recovery plans.
        Auto-picks the latest snapshot per group unless -SnapshotIds is given.
    .EXAMPLE
        Invoke-ErsPlanFailover -ErsInstance $Ers -Kind Test -Name P1, P2
    .EXAMPLE
        Invoke-ErsPlanFailover -ErsInstance $Ers -Kind Prod -Name P1
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][ValidateSet('Test', 'Prod')][string]$Kind,
        [Parameter(Mandatory)][string[]]$Name,
        [string[]]$SnapshotIds,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )
    $action = if ($Kind -eq 'Test') { 'test_failover' } else { 'prod_failover' }
    return Invoke-ErsPlanAction -ErsInstance $ErsInstance -Action $action -Name $Name `
        -SnapshotIds $SnapshotIds -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
}
