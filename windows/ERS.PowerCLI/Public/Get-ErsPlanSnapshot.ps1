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

function Get-ErsPlanSnapshot {
    <#
    .SYNOPSIS
        Lists snapshot sets for one or more recovery plans.
    .EXAMPLE
        Get-ErsPlanSnapshot -ErsInstance $Ers -Name P1, P2
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name
    )

    $resolved = Resolve-ErsPlans -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) {
        Write-Warning "Plans not found: $($resolved.NotFound -join ', ')"
    }
    if ($resolved.Matched.Count -eq 0) {
        Write-Host 'No matching plans found.'
        return @()
    }

    $allResults = @()
    foreach ($plan in $resolved.Matched) {
        $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET -Path (Get-ErsSnapshotsPath) `
            -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; recovery_plan_id = $plan.id }
        $items = @($data.items)
        $total = $data.total_item_count

        Write-Host "`n$('=' * 70)"
        Write-Host "  Plan : $($plan.name)  (id: $($plan.id))"
        Write-Host "  Total snapshots: $total"
        Write-Host ('=' * 70)

        if ($items.Count -eq 0) {
            Write-Host '  No snapshots found.'
        } else {
            Write-Host ("`n  {0,-38} {1,-28} {2,-22} {3}" -f 'Snapshot ID', 'Group', 'Created', 'VMs (protected/total)')
            Write-Host ('  ' + ('-' * 100))
            foreach ($snap in $items) {
                $created = ConvertTo-ErsUnixMillisDateString -MillisSinceEpoch $snap.created_at
                Write-Host ("  {0,-38} {1,-28} {2,-22} {3}/{4}" -f $snap.id, $snap.application_group.name, $created, `
                    $snap.protected_vm_count, $snap.total_vm_count)
            }
        }
        $allResults += [pscustomobject]@{ plan_id = $plan.id; plan_name = $plan.name; total_item_count = $total; items = $items }
    }
    return $allResults
}
