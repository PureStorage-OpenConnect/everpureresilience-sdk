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

function Wait-ErsGroup {
    <#
    .SYNOPSIS
        Polls the most recent Invoke-ErsGroupRun operation(s) until they
        reach a terminal state. Returns a hashtable of group name -> status.
    .EXAMPLE
        Wait-ErsGroup -ErsInstance $Ers -Name G1, G2 -IntervalSeconds 10 -MaxPolls 30
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [string[]]$Name,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )

    $stateFile = Get-ErsStatePath -FileName (Get-ErsLastRunOpsFileName)
    if (-not (Test-Path $stateFile)) {
        throw 'No recent run found. Run Invoke-ErsGroupRun first to generate op IDs.'
    }
    $opMap = Get-Content -Path $stateFile -Raw | ConvertFrom-Json -AsHashtable

    if ($Name) {
        $lower = $Name | ForEach-Object { $_.ToLower() }
        $filtered = @{}
        foreach ($k in $opMap.Keys) { if ($k.ToLower() -in $lower) { $filtered[$k] = $opMap[$k] } }
        $opMap = $filtered
        if ($opMap.Count -eq 0) {
            throw 'None of the specified group names found in last run output.'
        }
    }

    $states = @{}
    foreach ($k in $opMap.Keys) { $states[$k] = @{ OpId = $opMap[$k]; Status = 'UNKNOWN'; Type = '-' } }

    Write-Host "`nMonitoring $($states.Count) operation(s). Polling every ${IntervalSeconds}s (max $MaxPolls). Ctrl+C to stop.`n"

    for ($poll = 1; $poll -le $MaxPolls; $poll++) {
        Write-Host "[Poll $poll/$MaxPolls]  $(Get-Date -Format 'HH:mm:ss')"
        Write-Host ("  {0,-40} {1,-38} {2,-16} {3}" -f 'Group', 'Op ID', 'Status', 'Type')
        Write-Host ('  ' + ('-' * 100))

        $allDone = $true
        foreach ($gname in @($states.Keys)) {
            $state = $states[$gname]
            if ($state.Status -in (Get-ErsTerminalStates)) {
                $icon = if ($state.Status -in @('SUCCEEDED', 'COMPLETED')) { '✓' } else { '✗' }
                Write-Host ("  {0,-40} {1,-38} {2} {3,-14} {4}" -f $gname, $state.OpId, $icon, $state.Status, $state.Type)
                continue
            }
            $allDone = $false

            $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET `
                -Path '/pure-protect/api/1.latest/application-groups/protection/operations' `
                -QueryParams @{ offset = 0; limit = 25; deployment_id = $ErsInstance.DeploymentId; ids = $state.OpId }
            $items = @($result.items)
            $op = if ($items.Count -gt 0) { $items[0] } else { $null }
            $status = if ($op) { $op.status } else { 'UNKNOWN' }
            $type   = if ($op) { $op.type } else { '-' }
            $state.Status = $status; $state.Type = $type
            Write-Host ("  {0,-40} {1,-38} {2,-16} {3}" -f $gname, $state.OpId, $status, $type)
        }

        Write-Host ''
        if ($allDone) {
            Write-Host 'All operations reached a terminal state.'
            break
        }
        if ($poll -lt $MaxPolls) { Start-Sleep -Seconds $IntervalSeconds }
    }

    $out = @{}
    foreach ($k in $states.Keys) { $out[$k] = $states[$k].Status }
    return $out
}
