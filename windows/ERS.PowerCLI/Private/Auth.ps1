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

# Private: RS256 JWT generation and OAuth2 token-exchange for Pure1 bearer
# tokens — mirrors ers/auth.py. Uses only .NET's built-in RSA class
# (System.Security.Cryptography.RSA.ImportFromPem, available since .NET 5,
# which every PowerShell 7+ runtime has) — no third-party JWT module
# dependency.
#
# Per Pure1's documented format, the JWT payload is exactly
# {"iss": app_id, "iat": <ms since epoch>, "exp": <ms since epoch>} — no
# "sub" claim, and timestamps are milliseconds, not seconds. Getting
# either wrong produces a confusing "invalid issuer"/"On Demand
# Provisioning is not enabled" error from Pure1, not an obviously
# JWT-shaped one.

function ConvertTo-ErsBase64Url {
    param([Parameter(Mandatory)][byte[]]$Bytes)
    ([Convert]::ToBase64String($Bytes)).Replace('+', '-').Replace('/', '_').TrimEnd('=')
}

function New-ErsJwt {
    param(
        [Parameter(Mandatory)][string]$AppId,
        [Parameter(Mandatory)][string]$PrivateKeyPath,
        [int]$TtlSeconds = 3600
    )

    if (-not (Test-Path $PrivateKeyPath)) {
        throw "Private key not found: $PrivateKeyPath"
    }
    $pem = Get-Content -Path $PrivateKeyPath -Raw

    $rsa = [System.Security.Cryptography.RSA]::Create()
    try {
        $rsa.ImportFromPem($pem)
    } catch {
        throw "Could not load private key at ${PrivateKeyPath}: $($_.Exception.Message)"
    }

    $nowMs = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $expMs = $nowMs + ([long]$TtlSeconds * 1000)

    $header  = [ordered]@{ alg = 'RS256'; typ = 'JWT' } | ConvertTo-Json -Compress
    $payload = [ordered]@{ iss = $AppId; iat = $nowMs; exp = $expMs } | ConvertTo-Json -Compress

    $headerB64  = ConvertTo-ErsBase64Url -Bytes ([System.Text.Encoding]::UTF8.GetBytes($header))
    $payloadB64 = ConvertTo-ErsBase64Url -Bytes ([System.Text.Encoding]::UTF8.GetBytes($payload))
    $signingInput = "$headerB64.$payloadB64"

    try {
        $signatureBytes = $rsa.SignData(
            [System.Text.Encoding]::UTF8.GetBytes($signingInput),
            [System.Security.Cryptography.HashAlgorithmName]::SHA256,
            [System.Security.Cryptography.RSASignaturePadding]::Pkcs1
        )
    } finally {
        $rsa.Dispose()
    }

    $signatureB64 = ConvertTo-ErsBase64Url -Bytes $signatureBytes
    return "$signingInput.$signatureB64"
}

function Get-ErsBearerToken {
    param(
        [Parameter(Mandatory)][string]$BaseUrl,
        [Parameter(Mandatory)][string]$JwtToken
    )
    $uri  = "$BaseUrl/oauth2/1.0/token"
    $body = @{
        subject_token_type = 'urn:ietf:params:oauth:token-type:jwt'
        grant_type         = 'urn:ietf:params:oauth:grant-type:token-exchange'
        subject_token      = $JwtToken
    }
    try {
        $response = Invoke-RestMethod -Uri $uri -Method Post -Body $body `
            -ContentType 'application/x-www-form-urlencoded'
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $respBody = $null
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $respBody = $_.ErrorDetails.Message
        }
        throw "Token exchange failed against ${uri} (HTTP $statusCode): $respBody"
    }
    if (-not $response.access_token) {
        throw "No access_token in token exchange response: $($response | ConvertTo-Json -Compress)"
    }
    return $response.access_token
}

function Resolve-ErsBearerToken {
    <#
    .SYNOPSIS
        Resolves a Pure1 bearer token using, in priority order:
          1. an explicit bearer_token in credentials
          2. a jwt_file in credentials, exchanged for a bearer token
          3. app_id + private_key_path in credentials — generate the JWT,
             then exchange it
    #>
    param(
        [Parameter(Mandatory)][string]$BaseUrl,
        [Parameter(Mandatory)][hashtable]$ErsCredentials
    )

    if ($ErsCredentials.bearer_token) {
        return $ErsCredentials.bearer_token
    }

    if ($ErsCredentials.jwt_file) {
        if (-not (Test-Path $ErsCredentials.jwt_file)) {
            throw "JWT file not found: $($ErsCredentials.jwt_file)"
        }
        $jwt = (Get-Content -Path $ErsCredentials.jwt_file -Raw).Trim()
        return Get-ErsBearerToken -BaseUrl $BaseUrl -JwtToken $jwt
    }

    if ($ErsCredentials.app_id -and $ErsCredentials.private_key_path) {
        $jwt = New-ErsJwt -AppId $ErsCredentials.app_id -PrivateKeyPath $ErsCredentials.private_key_path
        return Get-ErsBearerToken -BaseUrl $BaseUrl -JwtToken $jwt
    }

    throw "No usable auth material in ~/.ers/credentials [ers] section. " +
          "Provide one of: bearer_token, jwt_file, or app_id + private_key_path."
}
