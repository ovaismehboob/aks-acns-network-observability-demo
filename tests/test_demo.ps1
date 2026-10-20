$ErrorActionPreference = "Stop"
$demo = Join-Path (Split-Path $PSScriptRoot -Parent) "advanced\demo.ps1"
$global:acnsTestCommands = New-Object 'System.Collections.Generic.List[string]'
$global:acnsTestEmptyPods = $false

function kubectl {
    $global:LASTEXITCODE = 0
    $command = $args -join " "
    $global:acnsTestCommands.Add($command)
    if ($command -match "config get-contexts") { return "test-cluster" }
    if ($command -match "get pods.*jsonpath") {
        if (-not $global:acnsTestEmptyPods) { return "inventory-old-a inventory-old-b" }
        return
    }
    if ($command -match "create configmap") { return "apiVersion: v1`nkind: ConfigMap" }
    if ($command -match "get pods.*-o json$") {
        return '{"items":[{"metadata":{"name":"inventory-old-b"},"status":{"phase":"Running","containerStatuses":[{"ready":true}]}},{"metadata":{"name":"inventory-new-c"},"status":{"phase":"Running","containerStatuses":[{"ready":true}]}}]}'
    }
}

function Start-Sleep { param($Seconds) }
function Start-Process {
    param($WindowStyle, $FilePath, $ArgumentList)
    $global:acnsTestEncodedCommand = $ArgumentList[-1]
}

function Invoke-Demo([string]$Action) {
    & $demo $Action -ResourceGroup "test-group" -ClusterName "test-cluster" -GrafanaName "" -GrafanaEndpoint "" -WarningAction SilentlyContinue | Out-Null
}

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

Invoke-Demo "PolicyFix"
Invoke-Demo "PolicyBreak"
$deleteAllow = @($global:acnsTestCommands | Where-Object { $_ -match "delete networkpolicy inventory-allow-checkout .*--ignore-not-found" })
Assert-True ($deleteAllow.Count -eq 1) "PolicyBreak must remove the previous scenario allow policy."
Write-Output "PASS PolicyFix -> PolicyBreak removes the prior allow rule."

$global:acnsTestCommands.Clear()
Invoke-Demo "Deploy"
Assert-True (@($global:acnsTestCommands | Where-Object { $_ -match "delete networkpolicy inventory-restrict inventory-allow-checkout" }).Count -eq 1) "Deploy must remove scenario policies."
Assert-True (@($global:acnsTestCommands | Where-Object { $_ -match "rollout restart deployment/inventory deployment/checkout-api deployment/catalog-client" }).Count -eq 1) "Deploy must restart main workloads to clear application state."
Write-Output "PASS Deploy resets scenario policies and restarts the baseline."

$global:acnsTestCommands.Clear()
Invoke-Demo "DnsStop"
Assert-True (@($global:acnsTestCommands | Where-Object { $_ -match "scale deployment/dns-typo-client deployment/dns-blocked-client .*--replicas=0" }).Count -eq 1) "DnsStop must scale both diagnostic clients to zero."
Write-Output "PASS DnsStop stops both DNS clients."

$global:acnsTestCommands.Clear()
Invoke-Demo "KillPod"
Assert-True (@($global:acnsTestCommands | Where-Object { $_ -match "delete pod inventory-old-a " }).Count -eq 1) "KillPod must delete one inventory pod."
Write-Output "PASS KillPod accepts a differently named Ready replacement."

$global:acnsTestEmptyPods = $true
$failed = $false
try { Invoke-Demo "KillPod" } catch { $failed = $_.Exception.Message -like "No inventory pods found*" }
Assert-True $failed "KillPod must fail explicitly when no inventory pods exist."
Write-Output "PASS KillPod rejects an empty pod selection."

$failed = $false
try { Invoke-Demo "Dashboard" } catch { $failed = $_.Exception.Message -like "Set ACNS_GRAFANA_NAME*" }
Assert-True $failed "Dashboard must require a Grafana resource name."
Write-Output "PASS Dashboard requires explicit Grafana configuration."

$localDirectory = Join-Path (Split-Path $demo -Parent) ".local"
$hadLocalDirectory = Test-Path -LiteralPath $localDirectory
$global:acnsTestEmptyPods = $false
& $demo "Reset" -ResourceGroup "test-group" -ClusterName "test-cluster" -GrafanaEndpoint "https://example.grafana.azure.com" | Out-Null
$annotationScript = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($global:acnsTestEncodedCommand))
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseInput($annotationScript, [ref]$tokens, [ref]$errors) | Out-Null
Assert-True ($errors.Count -eq 0) "Generated annotation process must have valid PowerShell syntax."
Assert-True ($annotationScript.Contains("FAILED: annotation")) "Annotation failures must be reported in the local status log."
Assert-True ($annotationScript.Contains('Bearer $token')) "Annotation credentials must be acquired at runtime."
if (-not $hadLocalDirectory -and @(Get-ChildItem -LiteralPath $localDirectory -Force).Count -eq 0) {
    Remove-Item -LiteralPath $localDirectory
}
Write-Output "PASS Annotation child script parses and records explicit status without executing it."
Write-Output "All runner tests used mocked kubectl; no cloud or cluster commands executed."
