[CmdletBinding()]
param(
    [string]$ResourceGroup = "rg-aks-netobs-demo",
    [string]$Location = "swedencentral",
    [string]$ClusterName = "aks-overlay-netobs-demo",
    [string]$AzureMonitorWorkspaceName = "amw-overlay-netobs-demo",
    [string]$GrafanaName = ""
)

$ErrorActionPreference = "Stop"

function Invoke-Az {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Azure CLI failed: az $($Arguments -join ' ')"
    }
}

$subscriptionName = az account show --query name -o tsv
$subscriptionId = az account show --query id -o tsv
if (-not $GrafanaName) {
    $GrafanaName = "amg-netobs-$($subscriptionId.Substring(0, 8))"
}

Write-Host "Using subscription: $subscriptionName"
Write-Host "Grafana name: $GrafanaName"
Invoke-Az group create --name $ResourceGroup --location $Location --output none

$monitorWorkspaceId = az resource list --resource-group $ResourceGroup --resource-type Microsoft.Monitor/accounts --query "[?name=='$AzureMonitorWorkspaceName'].id | [0]" -o tsv
if (-not $monitorWorkspaceId) {
    Invoke-Az resource create --resource-group $ResourceGroup --namespace Microsoft.Monitor --resource-type accounts --name $AzureMonitorWorkspaceName --location $Location --properties '{}' --output none
    $monitorWorkspaceId = az resource show --resource-group $ResourceGroup --name $AzureMonitorWorkspaceName --resource-type Microsoft.Monitor/accounts --query id -o tsv
}

$grafanaApiVersion = "2023-09-01"
$grafanaUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Dashboard/grafana/$GrafanaName`?api-version=$grafanaApiVersion"
$accessToken = az account get-access-token --resource https://management.azure.com/ --query accessToken -o tsv
if ($LASTEXITCODE -ne 0 -or -not $accessToken) { throw "Unable to acquire an Azure management access token" }

$grafanaId = az resource list --resource-group $ResourceGroup --resource-type Microsoft.Dashboard/grafana --query "[?name=='$GrafanaName'].id | [0]" -o tsv
if (-not $grafanaId) {
    $grafanaBody = @{
        location = $Location
        sku = @{ name = "Standard" }
        identity = @{ type = "SystemAssigned" }
        properties = @{
            apiKey = "Disabled"
            deterministicOutboundIP = "Disabled"
            publicNetworkAccess = "Enabled"
            zoneRedundancy = "Disabled"
        }
    } | ConvertTo-Json -Depth 4 -Compress
    Invoke-RestMethod -Method Put -Uri $grafanaUrl -Headers @{ Authorization = "Bearer $accessToken" } -ContentType "application/json" -Body $grafanaBody | Out-Null
    $grafanaId = az resource show --resource-group $ResourceGroup --name $GrafanaName --resource-type Microsoft.Dashboard/grafana --query id -o tsv
}

$grafanaIdentityBody = @{ identity = @{ type = "SystemAssigned" } } | ConvertTo-Json -Depth 2 -Compress
Invoke-RestMethod -Method Patch -Uri $grafanaUrl -Headers @{ Authorization = "Bearer $accessToken" } -ContentType "application/json" -Body $grafanaIdentityBody | Out-Null

$clusterId = az resource list --resource-group $ResourceGroup --resource-type Microsoft.ContainerService/managedClusters --query "[?name=='$ClusterName'].id | [0]" -o tsv
if (-not $clusterId) {
    Invoke-Az aks create --resource-group $ResourceGroup --name $ClusterName --location $Location --node-count 2 --node-vm-size Standard_D2s_v5 --enable-managed-identity --network-plugin azure --network-plugin-mode overlay --network-policy azure --pod-cidr 192.168.0.0/16 --generate-ssh-keys --output none
    $clusterId = az resource show --resource-group $ResourceGroup --name $ClusterName --resource-type Microsoft.ContainerService/managedClusters --query id -o tsv
}

$clusterPowerState = az resource show --ids $clusterId --query properties.powerState.code -o tsv
if ($clusterPowerState -eq "Stopped") {
    Invoke-Az aks start --resource-group $ResourceGroup --name $ClusterName --output none
}

Invoke-Az aks update --resource-group $ResourceGroup --name $ClusterName --enable-managed-identity --output none
Invoke-Az aks update --resource-group $ResourceGroup --name $ClusterName --network-policy azure --output none
Invoke-Az aks update --resource-group $ResourceGroup --name $ClusterName --enable-acns --output none
Invoke-Az aks update --resource-group $ResourceGroup --name $ClusterName --enable-azure-monitor-metrics --azure-monitor-workspace-resource-id $monitorWorkspaceId --grafana-resource-id $grafanaId --output none

Invoke-Az aks get-credentials --resource-group $ResourceGroup --name $ClusterName --overwrite-existing
& kubectl apply -f "$PSScriptRoot\pod-drop-demo.yaml"
if ($LASTEXITCODE -ne 0) { throw "kubectl apply failed" }

& kubectl rollout status deployment/healthy-server -n netobs-demo --timeout=180s
if ($LASTEXITCODE -ne 0) { throw "healthy-server rollout failed" }
& kubectl rollout status deployment/healthy-client -n netobs-demo --timeout=180s
if ($LASTEXITCODE -ne 0) { throw "healthy-client rollout failed" }
& kubectl rollout status deployment/drop-client -n netobs-demo --timeout=180s
if ($LASTEXITCODE -ne 0) { throw "drop-client rollout failed" }

$grafanaEndpoint = az resource show --resource-group $ResourceGroup --name $GrafanaName --resource-type Microsoft.Dashboard/grafana --query properties.endpoint -o tsv
Write-Host ""
Write-Host "Demo deployed."
Write-Host "Grafana: $grafanaEndpoint"
Write-Host "Dashboard: Dashboards > Azure Managed Prometheus > Kubernetes / Networking / Drops (Workload)"
Write-Host "Namespace: netobs-demo"
Write-Host "Workload: drop-client"
Write-Host "Allow 5-10 minutes for initial metric ingestion."