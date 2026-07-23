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

function Import-ErsTag {
    <#
    .SYNOPSIS
        Applies tags captured by Export-ErsTag on another registered
        site, via VCF.PowerCLI's native tagging cmdlets. -Source is that
        site's name — checked against the site name recorded inside
        .last_tags_export.json before applying anything.

        By default, skips (and warns about) any tag category or tag that
        doesn't already exist on this site — pass -CreateMissing to have
        them created automatically instead.
    .EXAMPLE
        Import-ErsTag -ErsSite $Ers.Sites['dr-dc'] -VmsFile vm-list.json -Source prod-dc -CreateMissing
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsSite]$ErsSite,
        [string[]]$Name,
        [string]$VmsFile,
        [Parameter(Mandatory)][string]$Source,
        [switch]$CreateMissing
    )

    $stateFile = Get-ErsStatePath -FileName $(Get-ErsTagExportFileName)
    if (-not (Test-Path $stateFile)) {
        throw "No tag export found ($(Get-ErsTagExportFileName)). Run Export-ErsTag on '$Source' first."
    }
    $payload = Get-Content -Path $stateFile -Raw | ConvertFrom-Json -AsHashtable
    if ($payload.site -ne $Source) {
        throw "$(Get-ErsTagExportFileName) was captured from site '$($payload.site)', not '$Source'. " +
              "Re-run Export-ErsTag on '$Source' first."
    }
    $state = $payload.vms

    $names = if ($Name) { $Name } elseif ($VmsFile) { (Get-ErsVmListFile -Path $VmsFile).name } else { @($state.Keys) }

    $applied = 0; $skipped = 0; $categoriesCreated = 0; $tagsCreated = 0
    $categoryCache = @{}  # name -> TagCategory object
    $tagCache = @{}       # "categoryName/tagName" -> Tag object

    foreach ($vmName in $names) {
        $entries = @($state[$vmName])
        if ($entries.Count -eq 0) { continue }

        $vm = Get-VM -Server $ErsSite.VIServer -Name $vmName -ErrorAction SilentlyContinue
        if (-not $vm) {
            Write-Warning "VM not found: $vmName"
            continue
        }

        foreach ($entry in $entries) {
            $catName = $entry.category; $tagName = $entry.tag; $cardinality = $entry.cardinality
            if (-not $cardinality) { $cardinality = 'Multiple' }

            if (-not $categoryCache.ContainsKey($catName)) {
                $categoryCache[$catName] = Get-TagCategory -Name $catName -Server $ErsSite.VIServer -ErrorAction SilentlyContinue
            }
            $category = $categoryCache[$catName]

            if (-not $category) {
                if ($CreateMissing) {
                    try {
                        $category = New-TagCategory -Name $catName -Cardinality $cardinality `
                            -EntityType VirtualMachine -Server $ErsSite.VIServer -Confirm:$false
                        $categoryCache[$catName] = $category
                        $categoriesCreated++
                        Write-Host "  Created missing category: $catName"
                    } catch {
                        Write-Warning "could not create category '$catName': $($_.Exception.Message)"
                        $skipped++
                        continue
                    }
                } else {
                    Write-Warning "category '$catName' not found on '$($ErsSite.Name)' — skipping tag " +
                        "'$tagName' for $vmName (-CreateMissing to auto-create)"
                    $skipped++
                    continue
                }
            }

            $tagKey = "$catName/$tagName"
            if (-not $tagCache.ContainsKey($tagKey)) {
                $tagCache[$tagKey] = Get-Tag -Category $category -Name $tagName -Server $ErsSite.VIServer -ErrorAction SilentlyContinue
            }
            $tag = $tagCache[$tagKey]

            if (-not $tag) {
                if ($CreateMissing) {
                    try {
                        $tag = New-Tag -Name $tagName -Category $category -Server $ErsSite.VIServer -Confirm:$false
                        $tagCache[$tagKey] = $tag
                        $tagsCreated++
                        Write-Host "  Created missing tag: $catName/$tagName"
                    } catch {
                        Write-Warning "could not create tag '$catName/$tagName': $($_.Exception.Message)"
                        $skipped++
                        continue
                    }
                } else {
                    Write-Warning "tag '$catName/$tagName' not found on '$($ErsSite.Name)' — skipping " +
                        "for $vmName (-CreateMissing to auto-create)"
                    $skipped++
                    continue
                }
            }

            try {
                New-TagAssignment -Entity $vm -Tag $tag -Server $ErsSite.VIServer -Confirm:$false -ErrorAction Stop | Out-Null
                $applied++
            } catch {
                if ($_.Exception.Message -match 'already') {
                    $applied++  # idempotent — already assigned, not an error
                } else {
                    Write-Warning "failed to attach '$catName/$tagName' to ${vmName}: $($_.Exception.Message)"
                    $skipped++
                }
            }
        }
    }

    Write-Host "`nTags applied: $applied, skipped: $skipped, categories created: $categoriesCreated, tags created: $tagsCreated"
    return @{ applied = $applied; skipped = $skipped; categories_created = $categoriesCreated; tags_created = $tagsCreated }
}
