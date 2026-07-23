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

function Set-ErsGroupProtectionState {
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$Name,
        [Parameter(Mandatory)][bool]$Enable
    )
    $resolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names $Name
    if ($resolved.NotFound.Count -gt 0) {
        Write-Warning "Groups not found: $($resolved.NotFound -join ', ')"
    }
    if ($resolved.Matched.Count -eq 0) {
        Write-Host 'No matching groups found — nothing to update.'
        return @()
    }

    $results = foreach ($group in $resolved.Matched) {
        $body = @{ protection_state = if ($Enable) { 'ENABLED' } else { 'DISABLED' } }
        Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method PATCH `
            -Path "/pure-protect/api/1.latest/application-groups/$($group.id)" `
            -QueryParams @{ deployment_id = $ErsInstance.DeploymentId } -Body $body | Out-Null
        Write-Host "  $($group.name): $(if ($Enable) { 'enabled' } else { 'disabled' })"
        $group.name
    }
    return $results
}

function Enable-ErsGroup {
    <#
    .SYNOPSIS
        Enables protection for one or more application groups.
    .EXAMPLE
        Enable-ErsGroup -ErsInstance $Ers -Name G1, G2
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Name)
    Set-ErsGroupProtectionState -ErsInstance $ErsInstance -Name $Name -Enable $true
}

function Disable-ErsGroup {
    <#
    .SYNOPSIS
        Disables protection for one or more application groups.
    .EXAMPLE
        Disable-ErsGroup -ErsInstance $Ers -Name G1, G2
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsInstance]$ErsInstance, [Parameter(Mandatory)][string[]]$Name)
    Set-ErsGroupProtectionState -ErsInstance $ErsInstance -Name $Name -Enable $false
}
