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

# ErsInstance — the session/state object returned by New-ErsInstance and
# passed to every other cmdlet via -ErsInstance. Equivalent to Python's
# ErsInstance class, but data-only here: the actual behavior lives in the
# Public/*.ps1 cmdlets rather than as methods on this class, since
# verb-noun cmdlets (not method chaining) are the idiomatic PowerShell
# shape for this SDK.
class ErsInstance {
    [string]$BaseUrl
    [string]$DeploymentId
    [string]$OutputFormat
    [string]$BearerToken
    [hashtable]$Sites          # site name -> ErsSite
    [hashtable]$CredentialsIni # raw ~/.ers/credentials INI, for Register-ErsSite site lookups

    ErsInstance([string]$BaseUrl, [string]$DeploymentId, [string]$BearerToken, [string]$OutputFormat) {
        $this.BaseUrl        = $BaseUrl
        $this.DeploymentId   = $DeploymentId
        $this.BearerToken    = $BearerToken
        $this.OutputFormat   = $OutputFormat
        $this.Sites          = @{}
        $this.CredentialsIni = @{}
    }
}

# ErsSite — a registered vCenter connection. Wraps the VCF.PowerCLI
# connection object (from Connect-VIServer) plus the site's registered
# name, which doubles as the Pure1 site name for managed_failback (see
# Invoke-ErsManagedFailback).
class ErsSite {
    [string]$Name
    [object]$VIServer   # the VCF.PowerCLI connection object

    ErsSite([string]$Name, [object]$VIServer) {
        $this.Name     = $Name
        $this.VIServer = $VIServer
    }
}
