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

function Wait-ErsPlan {
    <#
    .SYNOPSIS
        Resumes polling the most recent Invoke-ErsPlanFailover/Cleanup/
        Failback operation(s) until they reach a terminal state — useful
        after a Ctrl+C or in a separate session.
    .EXAMPLE
        Wait-ErsPlan -ErsInstance $Ers -Name P1
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [string[]]$Name,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )

    $opMap = Get-ErsPlanOps
    if ($opMap.Count -eq 0) {
        throw 'No recent plan run found. Run Invoke-ErsPlanFailover/Cleanup/Failback first.'
    }

    if ($Name) {
        $lower = $Name | ForEach-Object { $_.ToLower() }
        $filtered = @{}
        foreach ($k in $opMap.Keys) { if ($k.ToLower() -in $lower) { $filtered[$k] = $opMap[$k] } }
        $opMap = $filtered
    }
    if ($opMap.Count -eq 0) {
        throw 'No op IDs found to monitor.'
    }

    $pathMap = @{
        test_failover = (Get-ErsFailoverPath)
        prod_failover = (Get-ErsFailoverPath)
        failback      = (Get-ErsFbPromotePath)
        cleanup       = (Get-ErsCleanupPath)
    }

    $states = @{}
    foreach ($k in $opMap.Keys) {
        $states[$k] = @{
            OpId = $opMap[$k].op_id; PlanName = $opMap[$k].plan_name; LastAction = $opMap[$k].last_action
            Status = 'UNKNOWN'; Type = '-'
        }
    }

    Write-Host "`nMonitoring $($states.Count) plan operation(s). Polling every ${IntervalSeconds}s (max $MaxPolls). Ctrl+C to stop.`n"

    for ($poll = 1; $poll -le $MaxPolls; $poll++) {
        Write-Host "[Poll $poll/$MaxPolls]"
        $allDone = $true
        foreach ($key in @($states.Keys)) {
            $state = $states[$key]
            if ($state.Status -in (Get-ErsTerminalStates)) { continue }
            $allDone = $false

            $action = $state.LastAction
            $params = @{ offset = 0; limit = 25; deployment_id = $ErsInstance.DeploymentId; ids = $state.OpId }
            if ($action -in @('test_failover', 'prod_failover')) {
                $kind = $action.Split('_')[0]
                $params.failover_type = (Get-ErsFailoverQueryTypeMap)[$kind]
            }
            $path = if ($pathMap.ContainsKey($action)) { $pathMap[$action] } else { (Get-ErsFailoverPath) }
            $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET -Path $path -QueryParams $params
            $items = @($result.items)
            $op = if ($items.Count -gt 0) { $items[0] } else { $null }
            $status = if ($op) { $op.status } else { 'UNKNOWN' }
            $type   = if ($op) { $op.type } else { '-' }
            $state.Status = $status; $state.Type = $type
            Write-Host ("  {0,-40} {1,-38} {2,-16} {3}" -f $state.PlanName, $state.OpId, $status, $type)

            if ($status -in (Get-ErsTerminalStates)) {
                $planState = Get-ErsPlanState
                $planState[$key] = @{ last_action = $action; last_status = $status; op_id = $state.OpId }
                Set-ErsPlanState -State $planState
            }
        }
        Write-Host ''
        if ($allDone) { Write-Host 'All plan operations reached a terminal state.'; break }
        if ($poll -lt $MaxPolls) { Start-Sleep -Seconds $IntervalSeconds }
    }

    $out = @{}
    foreach ($k in $states.Keys) { $out[$states[$k].PlanName] = $states[$k].Status }
    return $out
}
