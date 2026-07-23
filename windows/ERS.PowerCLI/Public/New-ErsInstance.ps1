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

function New-ErsInstance {
    <#
    .SYNOPSIS
        Creates an ERS session object — reads ~/.ers/config + credentials
        and resolves a Pure1 bearer token automatically.

    .EXAMPLE
        $Ers = New-ErsInstance
    .EXAMPLE
        $Ers = New-ErsInstance -ProfileName staging
    #>
    [CmdletBinding()]
    param(
        [string]$ProfileName = 'default',
        [string]$BaseUrl,
        [string]$DeploymentId,
        [ValidateSet('txt', 'json')][string]$OutputFormat,
        [string]$BearerToken,
        [string]$JwtFile,
        [string]$AppId,
        [string]$PrivateKeyPath,
        [string]$ConfigPath,
        [string]$CredentialsPath
    )

    $cfgArgs = @{ ProfileName = $ProfileName }
    if ($ConfigPath) { $cfgArgs.Path = $ConfigPath }
    $cfg = Get-ErsConfig @cfgArgs

    $credArgs = @{}
    if ($CredentialsPath) { $credArgs.Path = $CredentialsPath }
    $credsIni  = Get-ErsCredentialsIni @credArgs
    $ersCreds  = Get-ErsCredentialsSection -Credentials $credsIni

    $resolvedBaseUrl      = if ($BaseUrl) { $BaseUrl } else { $cfg.base_url }
    $resolvedDeploymentId = if ($DeploymentId) { $DeploymentId } else { $cfg.deployment_id }
    $resolvedOutput       = if ($OutputFormat) { $OutputFormat } elseif ($cfg.output) { $cfg.output } else { 'txt' }

    if (-not $resolvedBaseUrl -or -not $resolvedDeploymentId) {
        throw "base_url and deployment_id are required (pass explicitly or set in ~/.ers/config)."
    }

    # explicit params override the credentials file, same priority as the Python SDK
    if ($BearerToken)    { $ersCreds.bearer_token     = $BearerToken }
    if ($JwtFile)        { $ersCreds.jwt_file         = $JwtFile }
    if ($AppId)          { $ersCreds.app_id           = $AppId }
    if ($PrivateKeyPath) { $ersCreds.private_key_path = $PrivateKeyPath }

    $token = Resolve-ErsBearerToken -BaseUrl $resolvedBaseUrl -ErsCredentials $ersCreds

    $instance = [ErsInstance]::new($resolvedBaseUrl, $resolvedDeploymentId, $token, $resolvedOutput)

    # stash the raw credentials INI on the instance so Register-ErsSite can
    # look up [site ...] sections without re-reading disk
    $instance.CredentialsIni = $credsIni

    return $instance
}
