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

function Invoke-ErsPlanCleanup {
    <#
    .SYNOPSIS
        Cleans up after a test failover. Requires test_failover to have
        run first for the plan (checked via ~/.ers/state).
    .EXAMPLE
        Invoke-ErsPlanCleanup -ErsInstance $Ers -Name P1
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )
    return Invoke-ErsPlanAction -ErsInstance $ErsInstance -Action 'cleanup' -Name $Name `
        -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
}
