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

# LAST_RUN_OPS filename moved to Private/Constants.ps1's Get-ErsLastRunOpsFileName

function Invoke-ErsGroupRun {
    <#
    .SYNOPSIS
        Triggers a protection run for one or more application groups.
        Op IDs are recorded to ~/.ers/state for Wait-ErsGroup.
    .EXAMPLE
        Invoke-ErsGroupRun -ErsInstance $Ers -Name G1, G2
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Name)

    $resolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) {
        Write-Warning "Groups not found: $($resolved.NotFound -join ', ')"
    }
    if ($resolved.Matched.Count -eq 0) {
        Write-Host 'No matching groups found — nothing to update.'
        return @{}
    }

    Write-Host "`nTriggering protection run for $($resolved.Matched.Count) group(s):`n"
    Write-Host ("  {0,-40} {1,-38} {2,-12} {3}" -f 'Group', 'Op ID', 'Status', 'Type')
    Write-Host ('  ' + ('-' * 104))

    $opMap = @{}
    foreach ($group in $resolved.Matched) {
        $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST `
            -Path '/pure-protect/api/1.latest/application-groups/protection/operations' `
            -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; application_group_id = $group.id } `
            -Body @{}
        $items = @($result.items)
        $item = if ($items.Count -gt 0) { $items[0] } else { $result }
        $opId = $item.id; $status = $item.status; $type = $item.type

        $opMap[$group.name] = $opId
        Write-Host ("  {0,-40} {1,-38} {2,-12} {3}" -f $group.name, $opId, $status, $type)

        ($opMap | ConvertTo-Json -Depth 5) | Set-Content -Path (Get-ErsStatePath -FileName (Get-ErsLastRunOpsFileName))
    }

    return $opMap
}
