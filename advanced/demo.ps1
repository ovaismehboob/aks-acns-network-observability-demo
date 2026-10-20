[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet(
        "Preflight", "Deploy", "Status", "Dashboard",
        "PolicyBreak", "PolicyFix",
        "DnsStart", "DnsStop",
        "SlowOn", "SlowOff",
        "KillPod", "Reset", "Cleanup")]
    [string]$Action,
    [string]$ResourceGroup = $env:ACNS_RESOURCE_GROUP,
    [string]$ClusterName = $env:ACNS_CLUSTER_NAME,
    [string]$GrafanaName = $env:ACNS_GRAFANA_NAME,
    [string]$GrafanaEndpoint = $env:ACNS_GRAFANA_ENDPOINT,
    [ValidateSet("checkout-demo")]
    [string]$Namespace = "checkout-demo",
    [ValidateRange(0, 10000)]
    [int]$DelayMs = 800
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $ResourceGroup) { $ResourceGroup = "rg-aks-netobs-demo" }
if (-not $ClusterName) { $ClusterName = "aks-overlay-netobs-demo" }
if ($GrafanaEndpoint) {
    $uri = $null
    if (-not [uri]::TryCreate($GrafanaEndpoint, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne "https" -or -not $uri.Host.EndsWith(".grafana.azure.com") -or
        $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne "/") {
        throw "GrafanaEndpoint must be the HTTPS Azure Managed Grafana base endpoint, without credentials or query."
    }
    $GrafanaEndpoint = $GrafanaEndpoint.TrimEnd("/")
}

function Invoke-Kubectl {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        & kubectl --context $ClusterName --request-timeout=60s @args
        if ($LASTEXITCODE -eq 0) { return }
        Write-Warning "kubectl $($args -join ' ') failed (attempt $attempt/3)"
        Start-Sleep -Seconds 5
    }
    throw "kubectl $($args -join ' ') failed after 3 attempts"
}

function Assert-Context {
    $contexts = & kubectl config get-contexts -o name
    if ($LASTEXITCODE -ne 0) { throw "Unable to read kubectl contexts" }
    if ($contexts -notcontains $ClusterName) {
        throw "kubectl context '$ClusterName' not found. Run: az aks get-credentials -g $ResourceGroup -n $ClusterName"
    }
}

function Write-Step([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message) -ForegroundColor Cyan
}

# A background process posts annotations and records status without tokens or API responses.
function Add-Annotation([string]$Text, [string[]]$Tags = @("acns-demo")) {
    if (-not $GrafanaEndpoint) {
        Write-Warning "Annotation not posted: set ACNS_GRAFANA_ENDPOINT. Workload action completed without a marker."
        return
    }
    $logDirectory = Join-Path $root ".local"
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    $logPath = (Join-Path $logDirectory "annotation-status.log").Replace("'", "''")
    $annotationEndpoint = $GrafanaEndpoint.Replace("'", "''")
    $time = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    $payload = @{ time = $time; text = $Text; tags = $Tags } | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
    $command = @"
`$ErrorActionPreference = 'Stop'
`$endpoint = '$annotationEndpoint'
`$logPath = '$logPath'
try {
  `$token = az account get-access-token --resource ce34e7e5-485f-4d76-964f-b3d2b16d1e4f --query accessToken -o tsv 2>`$null
  if (`$LASTEXITCODE -ne 0 -or -not `$token) { throw 'Token acquisition failed' }
  `$body = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('$encoded'))
  Invoke-RestMethod -Method Post -Uri "`$endpoint/api/annotations" -Headers @{ Authorization = "Bearer `$token" } -ContentType 'application/json' -Body `$body -TimeoutSec 60 | Out-Null
  Add-Content -Path `$logPath -Value ("{0:o} OK: annotation posted" -f (Get-Date))
} catch {
  Add-Content -Path `$logPath -Value ("{0:o} FAILED: annotation; check Azure authentication, Grafana Editor access and connectivity. Response omitted." -f (Get-Date))
  exit 1
}
"@
    $encodedCommand = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    Start-Process -WindowStyle Hidden -FilePath (Get-Process -Id $PID).Path -ArgumentList @("-NoProfile", "-EncodedCommand", $encodedCommand) | Out-Null
    Write-Host "Annotation queued; check advanced\.local\annotation-status.log for OK or FAILED."
}

function Wait-Rollout([string]$Deployment) {
    Invoke-Kubectl rollout status "deployment/$Deployment" -n $Namespace --timeout=180s
}

function Set-InventoryDelay([int]$Ms) {
    $pods = (Invoke-Kubectl get pods -n $Namespace -l app=inventory -o jsonpath='{.items[*].metadata.name}') -split "\s+" | Where-Object { $_ }
    if (-not $pods) { throw "No inventory pods found; deploy the demo before setting delay" }
    foreach ($pod in $pods) {
        & kubectl --context $ClusterName exec -n $Namespace $pod -- wget -qO- --post-data=1 "http://127.0.0.1:8080/admin/delay?ms=$Ms"
        if ($LASTEXITCODE -ne 0) { throw "Unable to set delay on $pod" }
    }
}

Assert-Context

switch ($Action) {
    "Preflight" {
        Write-Step "Cluster and monitoring configuration"
        az aks show -g $ResourceGroup -n $ClusterName --query "{power:powerState.code,state:provisioningState,plugin:networkProfile.networkPlugin,mode:networkProfile.networkPluginMode,dataplane:networkProfile.networkDataplane,policy:networkProfile.networkPolicy,acnsObservability:networkProfile.advancedNetworking.observability.enabled,prometheus:azureMonitorProfile.metrics.enabled}" -o table --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw "Unable to read AKS configuration" }
        Write-Step "Nodes"
        Invoke-Kubectl get nodes
        Write-Step "ACNS and Managed Prometheus collectors"
        Invoke-Kubectl get pods -n kube-system | Select-String "retina|ama-metrics"
        Write-Step "Checkout demo namespace"
        $existingNamespace = Invoke-Kubectl get namespace $Namespace --ignore-not-found -o name
        if ($existingNamespace) {
            Invoke-Kubectl get pods -n $Namespace
        } else {
            Write-Warning "checkout-demo is not deployed yet; run Deploy after checking cluster readiness."
        }
    }

    "Deploy" {
        Write-Step "Applying namespace, probe script, workloads, PodMonitor"
        Invoke-Kubectl apply -f "$root\checkout-demo.yaml"
        Invoke-Kubectl delete networkpolicy inventory-restrict inventory-allow-checkout -n $Namespace --ignore-not-found
        $configMap = Invoke-Kubectl create configmap probe-app -n $Namespace --from-file="$root\app\probe.py" --dry-run=client -o yaml
        $configMap | & kubectl --context $ClusterName --request-timeout=60s apply -f -
        if ($LASTEXITCODE -ne 0) { throw "ConfigMap apply failed" }
        Invoke-Kubectl rollout restart deployment/inventory deployment/checkout-api deployment/catalog-client -n $Namespace
        foreach ($d in "inventory", "checkout-api", "catalog-client") { Wait-Rollout $d }
        Invoke-Kubectl get pods -n $Namespace -o wide
        Add-Annotation "checkout-demo deployed (baseline)" @("acns-demo", "baseline")
        Write-Host "Allow 3-5 minutes for first Prometheus samples before presenting." -ForegroundColor Yellow
    }

    "Status" {
        Invoke-Kubectl get pods -n $Namespace -o wide
        Invoke-Kubectl get networkpolicy -n $Namespace
        Write-Step "Live client logs are intentionally absent; use Grafana for request health."
    }

    "Dashboard" {
        if (-not $GrafanaName) { throw "Set ACNS_GRAFANA_NAME or pass -GrafanaName before publishing" }
        Write-Step "Publishing 'ACNS Incident Investigation' dashboard to $GrafanaName"
        az grafana dashboard create -g $ResourceGroup -n $GrafanaName --definition "$root\grafana\acns-incident-dashboard.json" --overwrite true --only-show-errors -o none
        if ($LASTEXITCODE -ne 0) { throw "Dashboard publish failed" }
        if ($GrafanaEndpoint) {
            Write-Host "Dashboard: $GrafanaEndpoint/d/acns-incident-investigation" -ForegroundColor Green
        } else {
            Write-Host "Published. Open 'ACNS Incident Investigation' in your Grafana workspace." -ForegroundColor Green
        }
    }

    "PolicyBreak" {
        Write-Step "SCENARIO 1: applying restrictive inventory policy (checkout-api not allowed)"
        Invoke-Kubectl apply -f "$root\scenarios\inventory-restrict.yaml"
        Invoke-Kubectl delete networkpolicy inventory-allow-checkout -n $Namespace --ignore-not-found
        Add-Annotation "S1: restrictive policy applied - checkout-api blocked" @("acns-demo", "scenario1", "fault")
        Write-Host "Expect: checkout-api timeouts + policy_denied drops; catalog-client stays healthy." -ForegroundColor Yellow
    }

    "PolicyFix" {
        Write-Step "SCENARIO 1: adding narrow allow rule for checkout-api"
        Invoke-Kubectl apply -f "$root\scenarios\inventory-allow-checkout.yaml"
        Add-Annotation "S1: allow rule for checkout-api applied - fix" @("acns-demo", "scenario1", "fix")
        Write-Host "Expect: success ratio returns to ~100% and drops stop within about 1-2 minutes." -ForegroundColor Yellow
    }

    "DnsStart" {
        Write-Step "SCENARIO 2: starting dns-typo-client (NXDOMAIN) and dns-blocked-client (DNS egress denied)"
        Invoke-Kubectl scale deployment/dns-typo-client deployment/dns-blocked-client -n $Namespace --replicas=1
        Wait-Rollout "dns-typo-client"
        Wait-Rollout "dns-blocked-client"
        Add-Annotation "S2: DNS failure clients started" @("acns-demo", "scenario2", "fault")
    }

    "DnsStop" {
        Write-Step "SCENARIO 2: stopping DNS failure clients"
        Invoke-Kubectl scale deployment/dns-typo-client deployment/dns-blocked-client -n $Namespace --replicas=0
        Add-Annotation "S2: DNS failure clients stopped" @("acns-demo", "scenario2", "fix")
    }

    "SlowOn" {
        Write-Step "SCENARIO 3: adding $DelayMs ms delay to inventory (application slowness, no network fault)"
        Set-InventoryDelay $DelayMs
        Add-Annotation "S3: inventory delay ${DelayMs}ms injected" @("acns-demo", "scenario3", "fault")
        Write-Host "Expect: p95 latency rises for BOTH callers; drops and TCP resets do not." -ForegroundColor Yellow
    }

    "SlowOff" {
        Write-Step "SCENARIO 3: removing inventory delay"
        Set-InventoryDelay 0
        Add-Annotation "S3: inventory delay removed" @("acns-demo", "scenario3", "fix")
    }

    "KillPod" {
        Write-Step "SCENARIO 4: deleting one inventory pod"
        $before = @((Invoke-Kubectl get pods -n $Namespace -l app=inventory -o jsonpath='{.items[*].metadata.name}') -split "\s+" | Where-Object { $_ })
        if ($before.Count -eq 0) { throw "No inventory pods found; deploy the demo before KillPod" }
        $victim = $before[0]
        Add-Annotation "S4: deleting pod $victim" @("acns-demo", "scenario4", "fault")
        Invoke-Kubectl delete pod $victim -n $Namespace --wait=false
        Invoke-Kubectl wait --for=delete "pod/$victim" -n $Namespace --timeout=120s
        $deadline = (Get-Date).AddSeconds(180)
        do {
            Start-Sleep -Seconds 3
            $podList = (Invoke-Kubectl get pods -n $Namespace -l app=inventory -o json | ConvertFrom-Json).items
            $ready = @($podList | Where-Object { $_.status.phase -eq "Running" -and $_.status.containerStatuses -and $_.status.containerStatuses[0].ready } | ForEach-Object { $_.metadata.name })
            $replacement = @($ready | Where-Object { $before -notcontains $_ })
        } while ($replacement.Count -eq 0 -and (Get-Date) -lt $deadline)
        if ($replacement.Count -eq 0) { throw "No new Ready inventory pod appeared within 180 seconds" }
        Write-Host "Deleted: $victim  Replacement Ready: $($replacement -join ', ')" -ForegroundColor Green
        Invoke-Kubectl get endpoints inventory -n $Namespace
        Add-Annotation "S4: replacement $($replacement -join ',') Ready" @("acns-demo", "scenario4", "fix")
    }

    "Reset" {
        Write-Step "Returning checkout-demo to healthy baseline"
        Invoke-Kubectl delete networkpolicy inventory-restrict inventory-allow-checkout -n $Namespace --ignore-not-found
        Invoke-Kubectl scale deployment/dns-typo-client deployment/dns-blocked-client -n $Namespace --replicas=0
        Set-InventoryDelay 0
        Add-Annotation "Reset to baseline" @("acns-demo", "baseline")
        Invoke-Kubectl get networkpolicy -n $Namespace
    }

    "Cleanup" {
        Write-Step "Deleting namespace $Namespace (original netobs-demo and other namespaces are untouched)"
        Invoke-Kubectl delete namespace $Namespace --wait=false
    }
}
