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

# Private: the shared engine behind Invoke-ErsPlanFailover/Cleanup/Failback
# — mirrors ers/resources/plan.py's _run_action(). Kept as one engine
# (rather than duplicated per-cmdlet) since the prerequisite-checking and
# state-file bookkeeping is identical across all four actions.
#
# IMPORTANT vocabulary note (this is exactly the bug we found and fixed in
# the Python SDK — replicate the distinction here too, don't collapse it):
#   - The failover POST body's "plan_type" field uses the FULL word
#     "PRODUCTION" for prod, "TEST" for test.
#   - The polling GET's "failover_type" query param uses the ABBREVIATED
#     "PROD" for prod, "TEST" for test.
# These are two different vocabularies for the same concept. Using "PROD"
# in the POST body gets a "Failed to read HTTP message" / unexpected-enum
# error from the API. See Private/Constants.ps1 for Get-ErsPlanTypeMap /
# Get-ErsFailoverQueryTypeMap / Get-ErsPlanPrerequisites / the path
# constants used throughout this file.

function Get-ErsPlanState {
    $path = Get-ErsStatePath -FileName (Get-ErsPlanStateFileName)
    if (Test-Path $path) { return (Get-Content $path -Raw | ConvertFrom-Json -AsHashtable) }
    return @{}
}

function Set-ErsPlanState {
    param([Parameter(Mandatory)][hashtable]$State)
    $path = Get-ErsStatePath -FileName (Get-ErsPlanStateFileName)
    ($State | ConvertTo-Json -Depth 5) | Set-Content -Path $path
}

function Get-ErsPlanOps {
    $path = Get-ErsStatePath -FileName (Get-ErsPlanOpsFileName)
    if (Test-Path $path) { return (Get-Content $path -Raw | ConvertFrom-Json -AsHashtable) }
    return @{}
}

function Set-ErsPlanOps {
    param([Parameter(Mandatory)][hashtable]$Ops)
    $path = Get-ErsStatePath -FileName (Get-ErsPlanOpsFileName)
    ($Ops | ConvertTo-Json -Depth 5) | Set-Content -Path $path
}

function Get-ErsOpResult {
    param($ApiResult)
    $items = @($ApiResult.items)
    $item = if ($items.Count -gt 0) { $items[0] } else { $ApiResult }
    return @{ Id = $item.id; Status = $item.status; Type = $item.type }
}

function Invoke-ErsPlanAction {
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][ValidateSet('test_failover', 'prod_failover', 'cleanup', 'failback')][string]$Action,
        [Parameter(Mandatory)][string[]]$Name,
        [string[]]$SnapshotIds,
        [string]$Site,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )

    $resolved = Resolve-ErsPlans -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) {
        Write-Warning "Plans not found: $($resolved.NotFound -join ', ')"
    }
    if ($resolved.Matched.Count -eq 0) {
        Write-Host 'No matching plans found.'
        return @()
    }

    $planState = Get-ErsPlanState
    $prereq    = (Get-ErsPlanPrerequisites)[$Action]
    $results   = @()

    Write-Host "`nRunning '$Action' for $($resolved.Matched.Count) plan(s):`n"

    foreach ($plan in $resolved.Matched) {
        $planId = $plan.id; $planName = $plan.name; $stateKey = $planName.ToLower()

        if ($prereq.Requires) {
            $prior = if ($planState.ContainsKey($stateKey)) { $planState[$stateKey] } else { $null }
            if (-not $prior -or $prior.last_action -ne $prereq.Requires) {
                Write-Host "  ${planName}: SKIPPED — '$Action' requires '$($prereq.Requires)' to have run first."
                continue
            }
            if ($prereq.MustSucceed -and $prior.last_status -ne 'SUCCEEDED') {
                Write-Host "  ${planName}: SKIPPED — '$Action' requires '$($prereq.Requires)' to have SUCCEEDED."
                continue
            }
        }

        $snaps = $SnapshotIds
        if ($Action -in @('test_failover', 'prod_failover', 'failback') -and -not $snaps) {
            $latest = Get-ErsLatestSnapshotIds -ErsInstance $ErsInstance -PlanId $planId
            if ($latest.Count -eq 0) {
                Write-Host "  ${planName}: SKIPPED — no snapshots found."
                continue
            }
            $snaps = @($latest.Values | ForEach-Object { $_.SnapId })
        }

        if ($Action -eq 'cleanup') {
            $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST -Path (Get-ErsCleanupPath) `
                -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $planId } -Body @{}
            $op = Get-ErsOpResult -ApiResult $result
            $status = Wait-ErsOperation -ErsInstance $ErsInstance -Path (Get-ErsCleanupPath) -OpId $op.Id `
                -Label $Action -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
            $planState[$stateKey] = @{ last_action = $Action; last_status = $status; op_id = $op.Id }
            $results += [pscustomobject]@{ plan = $planName; op_id = $op.Id; status = $status; type = $op.Type }
        }
        elseif ($Action -eq 'failback') {
            if (-not $Site) {
                Write-Host "  ${planName}: SKIPPED — Site is required for failback."
                continue
            }
            $targetSiteId = Resolve-ErsSiteId -ErsInstance $ErsInstance -SiteName $Site
            if (-not $targetSiteId) {
                Write-Host "  ${planName}: SKIPPED — site '$Site' not found."
                continue
            }
            $groupIds = @($plan.groups | ForEach-Object { $_.id })
            if ($groupIds.Count -eq 0) {
                Write-Host "  ${planName}: SKIPPED — no groups found in plan."
                continue
            }

            $syncResult = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST -Path (Get-ErsFbSyncPath) `
                -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $planId } `
                -Body @{ target_site_id = $targetSiteId; snapshot_set_ids = $snaps; active_sync_application_group_ids = $groupIds }
            $syncOp = Get-ErsOpResult -ApiResult $syncResult
            $syncStatus = Wait-ErsOperation -ErsInstance $ErsInstance -Path (Get-ErsFbSyncPath) -OpId $syncOp.Id `
                -Label 'synchronization' -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
            if ($syncStatus -ne 'SUCCEEDED') {
                $results += [pscustomobject]@{ plan = $planName; step = 'synchronization'; op_id = $syncOp.Id; status = $syncStatus }
                continue
            }

            $cutoverResult = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST -Path (Get-ErsFbCutoverPath) `
                -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $planId } -Body @{}
            $cutoverOp = Get-ErsOpResult -ApiResult $cutoverResult
            $cutoverStatus = Wait-ErsOperation -ErsInstance $ErsInstance -Path (Get-ErsFbCutoverPath) -OpId $cutoverOp.Id `
                -Label 'cutover' -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
            if ($cutoverStatus -ne 'SUCCEEDED') {
                $results += [pscustomobject]@{ plan = $planName; step = 'cutover'; op_id = $cutoverOp.Id; status = $cutoverStatus }
                continue
            }

            $promoteResult = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST -Path (Get-ErsFbPromotePath) `
                -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $planId } -Body @{}
            $promoteOp = Get-ErsOpResult -ApiResult $promoteResult
            $status = Wait-ErsOperation -ErsInstance $ErsInstance -Path (Get-ErsFbPromotePath) -OpId $promoteOp.Id `
                -Label 'promotion' -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls

            $results += [pscustomobject]@{
                plan = $planName; status = $status
                steps = @{
                    synchronization = @{ op_id = $syncOp.Id; status = $syncStatus }
                    cutover         = @{ op_id = $cutoverOp.Id; status = $cutoverStatus }
                    promotion       = @{ op_id = $promoteOp.Id; status = $status }
                }
            }

            $ops = Get-ErsPlanOps
            $ops[$stateKey] = @{ op_id = $promoteOp.Id; last_action = $Action; plan_id = $planId; plan_name = $planName }
            Set-ErsPlanOps -Ops $ops
            $planState[$stateKey] = @{ last_action = $Action; last_status = $status; op_id = $promoteOp.Id }
        }
        else {
            # test_failover / prod_failover
            $kind = $Action.Split('_')[0]
            $body = @{ plan_type = (Get-ErsPlanTypeMap)[$kind]; scale = 0; snapshot_set_ids = $snaps }
            $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST -Path (Get-ErsFailoverPath) `
                -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $planId } -Body $body
            $op = Get-ErsOpResult -ApiResult $result

            $ops = Get-ErsPlanOps
            $ops[$stateKey] = @{ op_id = $op.Id; last_action = $Action; plan_id = $planId; plan_name = $planName }
            Set-ErsPlanOps -Ops $ops

            $extra = @{ failover_type = (Get-ErsFailoverQueryTypeMap)[$kind] }
            $status = Wait-ErsOperation -ErsInstance $ErsInstance -Path (Get-ErsFailoverPath) -OpId $op.Id `
                -Label $Action -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls -ExtraParams $extra

            $planState[$stateKey] = @{ last_action = $Action; last_status = $status; op_id = $op.Id }
            $results += [pscustomobject]@{ plan = $planName; op_id = $op.Id; status = $status; type = $op.Type }
        }
    }

    Set-ErsPlanState -State $planState
    return $results
}
