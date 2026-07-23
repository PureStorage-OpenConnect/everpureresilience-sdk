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

function Register-ErsSite {
    <#
    .SYNOPSIS
        Registers a vCenter site on an ErsInstance — either by connecting
        fresh using [site vsphere <name>] credentials from
        ~/.ers/credentials, or by wrapping a VIServer connection you
        already made yourself with Connect-VIServer.

    .EXAMPLE
        Register-ErsSite -ErsInstance $Ers -Name prod-dc
    .EXAMPLE
        $conn = Connect-VIServer -Server vcenter.example.com -User me -Password pw
        Register-ErsSite -ErsInstance $Ers -Name prod-dc -VIServer $conn
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$Name,
        [object]$VIServer
    )

    if ($VIServer) {
        $site = [ErsSite]::new($Name, $VIServer)
        $ErsInstance.Sites[$Name] = $site
        return $site
    }

    $siteCreds = Get-ErsSiteCredentials -Credentials $ErsInstance.CredentialsIni -Name $Name
    if (-not $siteCreds) {
        throw "No [site vsphere $Name] section found in ~/.ers/credentials, and no -VIServer was passed."
    }
    if ($siteCreds.Type -ne 'vsphere') {
        throw "Site '$Name' has type '$($siteCreds.Type)' — only 'vsphere' is supported today."
    }

    $c = $siteCreds.Credentials
    if (-not $c.host -or -not $c.user -or -not $c.pass) {
        throw "Site '$Name' is missing host/user/pass in ~/.ers/credentials."
    }

    # Suppress every PowerCLI first-run interactive prompt (multiple-default-servers,
    # CEIP participation) so this never blocks waiting for input in a script/CI run —
    # every cmdlet we call passes -Server explicitly, so DefaultServerMode doesn't
    # affect correctness either way.
    Set-PowerCLIConfiguration -Scope Session -Confirm:$false `
        -ParticipateInCeip:$false -DefaultVIServerMode 'Multiple' | Out-Null

    $insecure = if ($c.ContainsKey('insecure')) { $c.insecure -eq 'true' } else { $true }
    if ($insecure) {
        # allow self-signed certs, matching the Linux/macOS SDK's `insecure = true`
        Set-PowerCLIConfiguration -InvalidCertificateAction Ignore -Scope Session -Confirm:$false | Out-Null
    }

    $securePass = ConvertTo-SecureString -String $c.pass -AsPlainText -Force
    $credential = New-Object System.Management.Automation.PSCredential($c.user, $securePass)

    try {
        $conn = Connect-VIServer -Server $c.host -Credential $credential -ErrorAction Stop
    } catch {
        throw "Could not connect to vCenter '$($c.host)' for site '$Name': $($_.Exception.Message)"
    }

    $site = [ErsSite]::new($Name, $conn)
    $ErsInstance.Sites[$Name] = $site
    return $site
}
