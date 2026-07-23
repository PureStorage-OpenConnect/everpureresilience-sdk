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

function Get-ErsPlan {
    <#
    .SYNOPSIS
        Lists recovery plans.
    .EXAMPLE
        Get-ErsPlan -ErsInstance $Ers -Name P1, P2 -Details
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [string[]]$Name,
        [switch]$Details,
        [int]$Limit = 25
    )

    $params = @{ offset = 0; limit = $Limit; deployment_id = $ErsInstance.DeploymentId }
    if ($Name) { $params.names = ($Name -join ',') }

    $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET `
        -Path '/pure-protect/api/1.latest/recovery-plans' -QueryParams $params

    $items = @($data.items)
    if ($items.Count -eq 0) {
        Write-Host 'No recovery plans found.'
        return @()
    }

    if ($Details) {
        $items | Format-List *
    } else {
        $items | Select-Object id, name, plan_state, recovery_state, is_failback_triggerable | Format-Table -AutoSize
    }
    Write-Host "`nShowing $($items.Count) of $($data.total_item_count) recovery plans."
    return $items
}
