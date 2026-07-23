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

# Private: thin Pure1 REST client (Invoke-RestMethod-backed) and a
# generic poll-until-terminal-state helper — mirrors ers/http.py.
# Failures throw terminating errors (PowerShell's natural equivalent of
# Python's ApiError) rather than printing-and-continuing, so callers can
# use normal try/catch.

# TERMINAL_STATES moved to Private/Constants.ps1's Get-ErsTerminalStates

function Invoke-ErsApiRequest {
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][ValidateSet('GET', 'POST', 'PATCH')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [hashtable]$QueryParams,
        [hashtable]$Body
    )

    $uri = "$($ErsInstance.BaseUrl)$Path"
    if ($QueryParams -and $QueryParams.Count -gt 0) {
        $pairs = foreach ($key in $QueryParams.Keys) {
            "$([uri]::EscapeDataString($key))=$([uri]::EscapeDataString([string]$QueryParams[$key]))"
        }
        $uri += '?' + ($pairs -join '&')
    }

    $headers = @{
        'Authorization' = "Bearer $($ErsInstance.BearerToken)"
        'accept'        = 'application/json'
    }

    $invokeArgs = @{
        Uri     = $uri
        Method  = $Method
        Headers = $headers
    }
    if ($Body) {
        $invokeArgs.ContentType = 'application/json'
        $invokeArgs.Body        = ($Body | ConvertTo-Json -Depth 10 -Compress)
    }

    try {
        return Invoke-RestMethod @invokeArgs
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $respBody   = $null
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $respBody = $_.ErrorDetails.Message
        }
        throw "HTTP error $statusCode calling $Method $Path`: $respBody"
    }
}

function Wait-ErsOperation {
    <#
    .SYNOPSIS
        Polls an operation endpoint until it reaches a terminal state.
        Returns the final status string.
    #>
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$OpId,
        [Parameter(Mandatory)][string]$Label,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30,
        [hashtable]$ExtraParams
    )

    $params = @{ offset = 0; limit = 1; deployment_id = $ErsInstance.DeploymentId; ids = $OpId }
    if ($ExtraParams) {
        foreach ($k in $ExtraParams.Keys) { $params[$k] = $ExtraParams[$k] }
    }

    Write-Host "`n  Polling [$Label] op_id: $OpId"
    Write-Host ("  {0,-6} {1,-16} {2}" -f 'Poll', 'Status', 'Finished')
    Write-Host ('  ' + ('-' * 50))

    for ($poll = 1; $poll -le $MaxPolls; $poll++) {
        $result  = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET -Path $Path -QueryParams $params
        $items   = @($result.items)
        $op      = if ($items.Count -gt 0) { $items[0] } else { $null }
        $status  = if ($op) { $op.status } else { 'UNKNOWN' }
        $finished = '-'
        if ($op -and $op.finished_at) {
            $finished = [DateTimeOffset]::FromUnixTimeMilliseconds($op.finished_at).UtcDateTime.ToString('HH:mm:ss "UTC"')
        }

        if ($status -in (Get-ErsTerminalStates)) {
            $icon = if ($status -in @('SUCCEEDED', 'COMPLETED')) { '✓' } else { '✗' }
            Write-Host ("  {0,-6} {1} {2,-14} {3}" -f $poll, $icon, $status, $finished)
            return $status
        }

        Write-Host ("  {0,-6} … {1,-14} {2}" -f $poll, $status, $finished)

        if ($poll -lt $MaxPolls) {
            Start-Sleep -Seconds $IntervalSeconds
        }
    }

    Write-Host "  Max polls ($MaxPolls) reached without terminal state."
    return 'TIMEOUT'
}
