# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Get-ErsVm {
    <#
    .SYNOPSIS Lists VMs in a site's inventory (with full pagination).
    .EXAMPLE Get-ErsVm -ErsInstance $Ers -WithSite prod-site
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$WithSite
    )

    $siteId = Resolve-ErsSiteId -ErsInstance $ErsInstance -SiteName $WithSite
    if (-not $siteId) { throw "Site '$WithSite' not found" }

    $items = Get-ErsVmInventory -ErsInstance $ErsInstance -SiteId $siteId
    if ($items.Count -eq 0) { Write-Host 'No VMs found.'; return @() }

    $items | Select-Object id, name | Format-Table -AutoSize
    Write-Host "`nShowing $($items.Count) VM(s) from site '$WithSite'."
    return $items
}
