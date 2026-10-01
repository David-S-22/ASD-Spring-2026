param(
    [string]$BudgetsBackendUrl = 'http://127.0.0.1:5006',
    [string]$RagServerUrl = 'http://127.0.0.1:5003',
    [int]$BudgetId = 0,
    [string]$OutputPath = 'C:\git\GitHub\Uni\ASD Bank\ethan\validation-output\budgets-release1-evidence.json'
)

$ErrorActionPreference = 'Stop'

function Invoke-JsonRequest {
    param(
        [ValidateSet('GET', 'POST')]
        [string]$Method,
        [string]$Url,
        [object]$Body = $null
    )

    $request = @{
        Method = $Method
        Uri = $Url
        Headers = @{ Accept = 'application/json' }
    }

    if ($null -ne $Body) {
        $request.ContentType = 'application/json'
        $request.Body = ($Body | ConvertTo-Json -Depth 10)
    }

    Invoke-RestMethod @request
}

$health = Invoke-JsonRequest -Method GET -Url ($BudgetsBackendUrl.TrimEnd('/') + '/health')
$budgets = Invoke-JsonRequest -Method GET -Url ($BudgetsBackendUrl.TrimEnd('/') + '/api/budgets')

if (-not ($budgets -is [System.Array]) -or $budgets.Count -eq 0) {
    throw 'No budgets were returned from the Budgets backend.'
}

$selectedBudget = if ($BudgetId -gt 0) {
    $budgets | Where-Object { $_.id -eq $BudgetId } | Select-Object -First 1
} else {
    $currentMonth = Get-Date -Format 'yyyy-MM'
    $candidates = $budgets | Where-Object { $_.id -is [int] -and $_.month -is [string] }
    $currentBudget = $candidates | Where-Object { $_.month -eq $currentMonth } | Select-Object -First 1
    if ($null -ne $currentBudget) {
        $currentBudget
    } else {
        $candidates | Sort-Object month -Descending | Select-Object -First 1
    }
}

if ($null -eq $selectedBudget) {
    throw "Budget id $BudgetId was not found."
}

$budgetIdText = [string]$selectedBudget.id
$summary = Invoke-JsonRequest -Method GET -Url ($BudgetsBackendUrl.TrimEnd('/') + "/api/budgets/$budgetIdText/summary")
$ragHealth = Invoke-JsonRequest -Method GET -Url ($RagServerUrl.TrimEnd('/') + '/health')
$mcpChat = Invoke-JsonRequest -Method POST -Url ($BudgetsBackendUrl.TrimEnd('/') + '/api/chat') -Body @{
    budget_id = [int]$selectedBudget.id
    message = "Show me the most relevant transactions for this month's budget pressure."
    integration_mode = 'mcp'
}
$ragChat = Invoke-JsonRequest -Method POST -Url ($BudgetsBackendUrl.TrimEnd('/') + '/api/chat') -Body @{
    budget_id = [int]$selectedBudget.id
    message = 'Using grounded budget guidance with sources, what should I focus on this month?'
    integration_mode = 'rag'
}

$evidence = [ordered]@{
    captured_at = (Get-Date).ToString('o')
    budgets_backend_url = $BudgetsBackendUrl
    rag_server_url = $RagServerUrl
    selected_budget = $selectedBudget
    budgets_health = $health
    summary = $summary
    rag_health = $ragHealth
    mcp_chat = $mcpChat
    rag_chat = $ragChat
}

$outputDirectory = Split-Path -Path $OutputPath -Parent
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}

$evidence | ConvertTo-Json -Depth 12 | Set-Content -Path $OutputPath -Encoding UTF8

Write-Host "Saved Budgets Release 1 evidence to $OutputPath"
Write-Host "Budget: $($selectedBudget.id) ($($selectedBudget.month))"
Write-Host "MCP source: $($mcpChat.response_source); tool count: $($mcpChat.tool_result.count)"
Write-Host "RAG source: $($ragChat.response_source); confidence: $($ragChat.grounding.confidence)"
