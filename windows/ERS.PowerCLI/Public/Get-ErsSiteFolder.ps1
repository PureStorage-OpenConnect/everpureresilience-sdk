# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Get-ErsSiteFolder {
    <#
    .SYNOPSIS Lists VM folders on a registered vCenter site.
    .EXAMPLE Get-ErsSiteFolder -ErsInstance $Ers -SiteName prod-site
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$SiteName
    )

    $site = $ErsInstance.Sites[$SiteName]
    if (-not $site) { throw "Site '$SiteName' not registered." }

    $folders = Get-Folder -Server $site.VIServer -Type VM | Select-Object Name, Id, @{N='Path';E={$_.ExtensionData.Parent}}
    $folders | Format-Table -AutoSize
    return $folders
}
