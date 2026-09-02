# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Get-ErsSiteNetwork {
    <#
    .SYNOPSIS Lists available networks on a registered vCenter site.
    .EXAMPLE Get-ErsSiteNetwork -ErsInstance $Ers -SiteName prod-site
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$SiteName
    )

    $site = $ErsInstance.Sites[$SiteName]
    if (-not $site) { throw "Site '$SiteName' not registered." }

    $networks = Get-VirtualPortGroup -Server $site.VIServer | Select-Object Name, VLanId, @{N='Type';E={$_.GetType().Name}}
    $networks | Format-Table -AutoSize
    return $networks
}
