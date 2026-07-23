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

# Private: config/credentials loading — mirrors ers/config.py.
# Same file paths and INI format as the Python/Linux/macOS SDK:
# ~/.ers/config (profiles) and ~/.ers/credentials ([ers] + [site ...]
# sections). PowerShell has no built-in INI parser, so this is a small
# hand-rolled one.

# Path constants moved to Private/Constants.ps1 (Get-ErsDir, Get-ErsConfigPath,
# Get-ErsCredentialsPath, Get-ErsStateDirPath)

function ConvertFrom-ErsIni {
    <#
    .SYNOPSIS
        Parses an INI-format file into an ordered hashtable of
        section name -> hashtable of key -> value.
    #>
    param([Parameter(Mandatory)][string]$Path)

    $result = [ordered]@{}
    if (-not (Test-Path $Path)) {
        return $result
    }

    $currentSection = $null
    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#') -or $line.StartsWith(';')) {
            continue
        }
        if ($line.StartsWith('[') -and $line.EndsWith(']')) {
            $currentSection = $line.Substring(1, $line.Length - 2).Trim()
            $result[$currentSection] = @{}
            continue
        }
        if ($null -eq $currentSection) {
            continue  # stray key before any section header — ignore
        }
        $eqIndex = $line.IndexOf('=')
        if ($eqIndex -lt 0) {
            continue
        }
        $key   = $line.Substring(0, $eqIndex).Trim()
        $value = $line.Substring($eqIndex + 1).Trim()
        $result[$currentSection][$key] = $value
    }

    return $result
}

function Test-ErsCredentialsPermission {
    <#
    .SYNOPSIS
        Warns (does not fail) if ~/.ers/credentials is readable by
        identities other than the current user — the closest
        cross-platform-in-spirit equivalent of the Linux/macOS SDK's
        chmod 600 check, using ACLs instead of POSIX mode bits.
    #>
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path $Path)) {
        return
    }

    try {
        $acl = Get-Acl -Path $Path
        $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        $broadAccess = $acl.Access | Where-Object {
            $_.IdentityReference -notin @($currentUser, 'BUILTIN\Administrators', 'NT AUTHORITY\SYSTEM') -and
            $_.FileSystemRights -match 'Read'
        }
        if ($broadAccess) {
            $names = ($broadAccess.IdentityReference | Select-Object -Unique) -join ', '
            Write-Warning "$Path is readable by: $names. Consider restricting this file to your own account only."
        }
    } catch {
        # ACL inspection can fail in some environments (e.g. non-NTFS) —
        # never let a permission *check* itself block normal operation.
    }
}

function Get-ErsConfig {
    <#
    .SYNOPSIS
        Loads a profile section from ~/.ers/config. Missing file/profile
        returns an empty hashtable, mirroring the Python SDK's behavior.
    #>
    param(
        [string]$ProfileName = 'default',
        [string]$Path = (Get-ErsConfigPath)
    )
    $ini = ConvertFrom-ErsIni -Path $Path
    if ($ini.Contains($ProfileName)) {
        return $ini[$ProfileName]
    }
    return @{}
}

function Get-ErsCredentialsIni {
    <#
    .SYNOPSIS
        Loads the raw ~/.ers/credentials INI (all sections), warning on
        loose permissions first.
    #>
    param([string]$Path = (Get-ErsCredentialsPath))
    Test-ErsCredentialsPermission -Path $Path
    return ConvertFrom-ErsIni -Path $Path
}

function Get-ErsCredentialsSection {
    <#
    .SYNOPSIS
        Returns the [ers] section (Pure1 auth material) as a hashtable.
    #>
    param([Parameter(Mandatory)][hashtable]$Credentials)
    if ($Credentials.Contains('ers')) {
        return $Credentials['ers']
    }
    return @{}
}

function Get-ErsSiteCredentials {
    <#
    .SYNOPSIS
        Finds a `[site <type> <name>]` section by site name.
        Returns @{ Type = <type>; Credentials = <hashtable> } or $null.
    #>
    param(
        [Parameter(Mandatory)][hashtable]$Credentials,
        [Parameter(Mandatory)][string]$Name
    )
    foreach ($section in $Credentials.Keys) {
        if ($section -notlike 'site *') { continue }
        $rest = $section.Substring(5).Trim()  # strip "site "
        $parts = $rest.Split(' ', 2)
        if ($parts.Count -ne 2) { continue }
        $type = $parts[0].Trim()
        $name = $parts[1].Trim()
        if ($name -eq $Name) {
            return @{ Type = $type; Credentials = $Credentials[$section] }
        }
    }
    return $null
}

function Get-ErsStatePath {
    <#
    .SYNOPSIS
        Returns a path under ~/.ers/state, creating the directory if needed.
    #>
    param([Parameter(Mandatory)][string]$FileName)
    if (-not (Test-Path (Get-ErsStateDirPath))) {
        New-Item -ItemType Directory -Path (Get-ErsStateDirPath) -Force | Out-Null
    }
    return Join-Path (Get-ErsStateDirPath) $FileName
}
