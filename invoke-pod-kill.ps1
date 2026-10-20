[CmdletBinding()]
param(
    [string]$Namespace = "netobs-demo",
    [string]$Deployment = "healthy-server"
)

$ErrorActionPreference = "Stop"

$kubectl = Get-Command kubectl -ErrorAction SilentlyContinue
if (-not $kubectl) {
    $kubectlPath = Join-Path $HOME ".azure-kubectl\kubectl.exe"
    if (-not (Test-Path $kubectlPath)) {
        throw "kubectl was not found. Run 'az aks install-cli' or add kubectl to PATH."
    }
    $kubectl = Get-Item $kubectlPath
}

$selector = "app=$Deployment"

$pod = & $kubectl.Source get pods -n $Namespace -l $selector -o jsonpath='{.items[0].metadata.name}'
if ($LASTEXITCODE -ne 0 -or -not $pod) {
    throw "No pod found for deployment/$Deployment."
}

$startedAt = Get-Date -Format o
Write-Host "Deleting pod/$pod from deployment/$Deployment at $startedAt"
& $kubectl.Source delete pod $pod -n $Namespace --wait=false
if ($LASTEXITCODE -ne 0) { throw "Pod deletion failed." }

& $kubectl.Source wait --for=delete pod/$pod -n $Namespace --timeout=180s
if ($LASTEXITCODE -ne 0) { throw "Deleted pod did not terminate within 180 seconds." }

$deadline = (Get-Date).AddSeconds(180)
do {
    $replacement = & $kubectl.Source get pods -n $Namespace -l $selector --field-selector=status.phase=Running -o jsonpath='{range .items[?(@.status.containerStatuses[0].ready==true)]}{.metadata.name}{"\n"}{end}'
    $replacement = @($replacement -split "`n" | Where-Object { $_ -and $_ -ne $pod })
    if ($replacement.Count -gt 0) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if ($replacement.Count -eq 0) { throw "No Ready replacement pod appeared within 180 seconds." }

Write-Host "Replacement ready: $($replacement -join ', ')"
Write-Host "Current pods:"
& $kubectl.Source get pods -n $Namespace -l $selector -o wide