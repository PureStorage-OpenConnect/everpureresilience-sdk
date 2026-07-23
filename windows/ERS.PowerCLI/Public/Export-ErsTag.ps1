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

# Tag export filename moved to Private/Constants.ps1's Get-ErsTagExportFileName

function Export-ErsTag {
    <#
    .SYNOPSIS
        Captures vSphere tag assignments from VMs on this site, via
        VCF.PowerCLI's native Get-TagAssignment — no manual REST calls
        needed (unlike the Python/pyVmomi SDK, which has to hand-roll the
        vSphere Automation API for tagging since pyVmomi doesn't support
        it). State is transparent: written to
        ~/.ers/state/.last_tags_export.json — like the other .last_*.json
        state files, only the most recent export is kept, and the site it
        came from is recorded inside the file (not the filename).
    .EXAMPLE
        Export-ErsTag -ErsSite $Ers.Sites['prod-dc'] -VmsFile vm-list.json
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsSite]$ErsSite, [string[]]$Name, [string]$VmsFile)

    $names = if ($Name) { $Name } elseif ($VmsFile) { (Get-ErsVmListFile -Path $VmsFile).name } else { @() }
    if ($names.Count -eq 0) {
        throw 'No VM names given (pass -Name or -VmsFile).'
    }

    $result = @{}
    foreach ($vmName in $names) {
        $vm = Get-VM -Server $ErsSite.VIServer -Name $vmName -ErrorAction SilentlyContinue
        if (-not $vm) {
            Write-Warning "VM not found: $vmName"
            continue
        }
        $assignments = Get-TagAssignment -Entity $vm -Server $ErsSite.VIServer -ErrorAction SilentlyContinue
        $entries = @()
        foreach ($a in @($assignments)) {
            $entries += @{
                category    = $a.Tag.Category.Name
                tag         = $a.Tag.Name
                cardinality = [string]$a.Tag.Category.Cardinality
            }
        }
        $result[$vmName] = $entries
        Write-Host "  ${vmName}: $($entries.Count) tag(s) captured"
    }

    $payload = @{
        site         = $ErsSite.Name
        captured_at  = (Get-Date).ToUniversalTime().ToString('o')
        vms          = $result
    }
    ($payload | ConvertTo-Json -Depth 10) | Set-Content -Path (Get-ErsStatePath -FileName $(Get-ErsTagExportFileName))

    $total = ($result.Values | ForEach-Object { $_.Count } | Measure-Object -Sum).Sum
    Write-Host "`nCaptured $total tag assignment(s) across $($result.Count) VM(s) -> $(Get-ErsTagExportFileName) (site: '$($ErsSite.Name)')"
    return $result
}
