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

# Private: shared name-resolution helpers used by the group/plan cmdlets —
# mirrors the _resolve()/_resolve_site_id()/_latest_snapshot_ids() helpers
# in ers/resources/group.py and plan.py.

function Resolve-ErsGroups {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Names)
    $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET `
        -Path '/pure-protect/api/1.latest/application-groups' `
        -QueryParams @{ offset = 0; limit = 100; deployment_id = $ErsInstance.DeploymentId }
    $all = @($data.items)
    $lower = $Names | ForEach-Object { $_.ToLower() }
    $matched  = $all | Where-Object { $_.name.ToLower() -in $lower }
    $foundLower = $matched | ForEach-Object { $_.name.ToLower() }
    $notFound = $Names | Where-Object { $_.ToLower() -notin $foundLower }
    return @{ Matched = @($matched); NotFound = @($notFound) }
}

function Resolve-ErsPlans {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Names)
    $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET `
        -Path '/pure-protect/api/1.latest/recovery-plans' `
        -QueryParams @{ offset = 0; limit = 100; deployment_id = $ErsInstance.DeploymentId }
    $all = @($data.items)
    $lower = $Names | ForEach-Object { $_.ToLower() }
    $matched  = $all | Where-Object { $_.name.ToLower() -in $lower }
    $foundLower = $matched | ForEach-Object { $_.name.ToLower() }
    $notFound = $Names | Where-Object { $_.ToLower() -notin $foundLower }
    return @{ Matched = @($matched); NotFound = @($notFound) }
}

function Resolve-ErsSiteId {
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string]$SiteName)
    $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET `
        -Path '/pure-protect/api/1.latest/sites' `
        -QueryParams @{ offset = 0; limit = 100; deployment_id = $ErsInstance.DeploymentId }
    $match = @($data.items) | Where-Object { $_.name.ToLower() -eq $SiteName.ToLower() } | Select-Object -First 1
    if ($match) { return $match.id }
    return $null
}

function Get-ErsLatestSnapshotIds {
    <#
    .SYNOPSIS
        Returns the latest snapshot set ID per application group for a plan.
        Returns a hashtable: group_id -> @{ SnapId; CreatedAt; GroupName }
    #>
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string]$PlanId)
    $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET `
        -Path '/pure-protect/api/1.latest/recovery-plans/snapshot-sets' `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $PlanId }

    $latest = @{}
    foreach ($snap in @($data.items)) {
        $groupId = $snap.application_group.id
        $createdAt = $snap.created_at
        if (-not $latest.ContainsKey($groupId) -or $createdAt -gt $latest[$groupId].CreatedAt) {
            $latest[$groupId] = @{
                SnapId    = $snap.id
                CreatedAt = $createdAt
                GroupName = $snap.application_group.name
            }
        }
    }
    return $latest
}

function ConvertTo-ErsUnixMillisDateString {
    param([long]$MillisSinceEpoch)
    if (-not $MillisSinceEpoch) { return '-' }
    return [DateTimeOffset]::FromUnixTimeMilliseconds($MillisSinceEpoch).UtcDateTime.ToString('yyyy-MM-dd HH:mm:ss "UTC"')
}
