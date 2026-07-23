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

# Private: vm-list.json loader — same schema_version 2 as the Linux/macOS
# SDK (ers/sites/vsphere.py's _load_vms_file). `networks`, if present, is
# a dict keyed by registered site name, e.g.:
#   {"schema_version": 2, "vms": [
#     {"name": "vm-1", "networks": {"prod-dc": ["net1"], "dr-dc": ["net2"]}}
#   ]}
# Kept in perfect lockstep with the Python loader so the exact same
# vm-list.json works unmodified on either platform.
# (schema version list itself lives in Private/Constants.ps1's
# Get-ErsSupportedVmListSchemaVersions)

function Get-ErsVmListFile {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path $Path)) {
        throw "vm-list file not found: $Path"
    }
    $data = Get-Content -Path $Path -Raw | ConvertFrom-Json

    if ($data.schema_version -eq 1) {
        throw "$Path is schema_version 1 (networks as a flat list) — this is no longer " +
              "supported. Regenerate it as schema_version 2, with 'networks' as an object " +
              "keyed by registered site name, e.g. {`"prod-dc`": [...], `"dr-dc`": [...]}."
    }
    if ($data.schema_version -notin (Get-ErsSupportedVmListSchemaVersions)) {
        throw "$Path has unsupported schema_version '$($data.schema_version)' " +
              "(supported: $((Get-ErsSupportedVmListSchemaVersions) -join ', '))"
    }

    $vms = @($data.vms)
    if ($vms.Count -eq 0) {
        throw "$Path has no VMs listed under 'vms'"
    }

    $seen = @{}
    foreach ($record in $vms) {
        if (-not $record.name) { throw "$Path has a VM entry with no 'name'" }
        if ($seen.ContainsKey($record.name)) { throw "$Path lists VM '$($record.name)' more than once" }
        $seen[$record.name] = $true
    }

    return $vms
}

function Get-ErsVmNetworksForSite {
    <#
    .SYNOPSIS
        Extracts each VM's ordered networks list for a specific site name
        from a parsed vm-list. Returns @{ VmName -> [string[]] }. Warns
        (doesn't fail) when a VM has a 'networks' object but no entry for
        this site — likely a config gap, not intentional exclusion.
    #>
    param(
        [Parameter(Mandatory)][array]$VmRecords,
        [Parameter(Mandatory)][string]$SiteName
    )
    $result = @{}
    foreach ($record in $VmRecords) {
        if (-not $record.networks) {
            $result[$record.name] = @()
            continue
        }
        $networksObj = $record.networks
        if ($networksObj.PSObject.Properties.Name -notcontains $SiteName) {
            Write-Warning "'$($record.name)' has a 'networks' entry but none for site " +
                "'$SiteName' — NICs will be left on their current backing"
            $result[$record.name] = @()
            continue
        }
        $result[$record.name] = @($networksObj.$SiteName)
    }
    return $result
}
