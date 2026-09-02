# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

# Private: thin Pure1 REST client and poll-until-terminal helper.
# ERS_DEBUG=1 env var prints every request/response (same as Python's http.py).

function Invoke-ErsApiRequest {
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][ValidateSet('GET', 'POST', 'PATCH', 'DELETE')][string]$Method,
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
    $jsonBody = $null
    if ($Body) {
        $invokeArgs.ContentType = 'application/json'
        $jsonBody = ($Body | ConvertTo-Json -Depth 10 -Compress)
        $invokeArgs.Body = $jsonBody
    }

    $debug = $env:ERS_DEBUG -eq '1'
    if ($debug) {
        Write-Host "[ERS_DEBUG] --> $Method $($ErsInstance.BaseUrl)$Path" -ForegroundColor DarkGray
        if ($QueryParams) { Write-Host "[ERS_DEBUG] params: $($QueryParams | ConvertTo-Json -Compress)" -ForegroundColor DarkGray }
        if ($jsonBody)    { Write-Host "[ERS_DEBUG] body: $jsonBody" -ForegroundColor DarkGray }
    }

    try {
        $response = Invoke-RestMethod @invokeArgs
        if ($debug) {
            Write-Host "[ERS_DEBUG] <-- 200" -ForegroundColor DarkGray
        }
        return $response
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        $respBody   = $null
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $respBody = $_.ErrorDetails.Message
        }
        if ($debug) {
            Write-Host "[ERS_DEBUG] <-- $statusCode" -ForegroundColor DarkGray
            Write-Host "[ERS_DEBUG] response body: $respBody" -ForegroundColor DarkGray
        }
        throw "HTTP error $statusCode calling $Method $Path`: $respBody"
    }
}

function Wait-ErsOperation {
    <#
    .SYNOPSIS
        Polls an operation endpoint until it reaches a terminal state.
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

function Invoke-ErsApiGetAll {
    <#
    .SYNOPSIS
        Fetches all pages from a Pure1 GET endpoint using offset-based
        pagination. Returns all items combined. Needed because the API
        ignores continuation_token and returns small default page sizes.
    #>
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$BaseParams
    )

    $allItems = @()
    $offset = 0
    $pageSize = 300
    $total = $null

    do {
        $params = $BaseParams.Clone()
        $params['offset'] = $offset
        $params['limit']  = $pageSize

        $data = Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method GET -Path $Path -QueryParams $params
        $items = @($data.items)
        $allItems += $items

        if ($null -eq $total) { $total = $data.total_item_count }
        if ($items.Count -eq 0) { break }

        $offset += $items.Count
    } while ($null -ne $total -and $offset -lt $total)

    return $allItems
}
