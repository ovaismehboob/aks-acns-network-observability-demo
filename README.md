# AKS Container Network Observability demo

This follows the Microsoft Learn non-Cilium setup and creates a fresh Azure CNI Overlay AKS cluster with Advanced Container Networking Services (ACNS), Managed Prometheus, Azure Managed Grafana, and sample healthy/drop traffic.

Source: [Set up Container Network Observability for AKS](https://learn.microsoft.com/azure/aks/container-network-observability-how-to?tabs=non-cilium)

> **Advanced customer demo:** for the incident-style demo (policy regression, DNS wrong-name vs blocked, slow dependency, self-healing) with a custom Grafana dashboard, use [`advanced\demo.ps1`](./advanced/demo.ps1) and follow [Customer-Demo-Runbook-Advanced.md](./docs/Customer-Demo-Runbook-Advanced.md). The full step-by-step implementation, use case description and executed scenarios with recorded measurements and dashboard viewing instructions are in [ACNS-Detailed-Implementation-and-Demo-Guide.md](./docs/ACNS-Detailed-Implementation-and-Demo-Guide.md). The sections below describe the original basic demo.

## Deploy

Prerequisites: Azure CLI 2.56 or newer, `kubectl`, PowerShell 5.1 or 7, `az login`, and resource provisioning permissions. Linking Grafana to Prometheus may also require role-assignment permissions; Contributor alone cannot create role assignments. Publishing dashboards and annotations requires Grafana Editor.

Use an approved disposable environment. Deployment incurs Azure charges, and the scenarios deliberately deny traffic or delete a demo pod.

```powershell
.\deploy-demo.ps1
```

Deployment normally takes 8-15 minutes. The script prints the Grafana URL.

The default Managed Grafana name is `amg-netobs-<subscription-prefix>`.

## Advanced demo configuration

The advanced demo uses a fixed `checkout-demo` namespace. Resource-group and cluster defaults match the examples below; set these process-local variables to target your own environment:

```powershell
$env:ACNS_RESOURCE_GROUP = "rg-aks-netobs-demo"
$env:ACNS_CLUSTER_NAME = "aks-overlay-netobs-demo"
$env:ACNS_MONITOR_WORKSPACE = "amw-overlay-netobs-demo"
$env:ACNS_GRAFANA_NAME = "<your-grafana-resource-name>"

az login
az account set --subscription "<your-subscription-id>"
az aks get-credentials -g $env:ACNS_RESOURCE_GROUP -n $env:ACNS_CLUSTER_NAME --overwrite-existing
if ($LASTEXITCODE -ne 0) { throw "Unable to get AKS credentials" }

$env:ACNS_GRAFANA_ENDPOINT = az grafana show -g $env:ACNS_RESOURCE_GROUP -n $env:ACNS_GRAFANA_NAME --query properties.endpoint -o tsv
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve Grafana endpoint" }
$env:ACNS_PROMETHEUS_ENDPOINT = az resource show -g $env:ACNS_RESOURCE_GROUP -n $env:ACNS_MONITOR_WORKSPACE --resource-type Microsoft.Monitor/accounts --query properties.metrics.prometheusQueryEndpoint -o tsv
if ($LASTEXITCODE -ne 0) { throw "Unable to resolve Prometheus endpoint" }

Set-Location .\advanced
.\demo.ps1 Preflight
.\demo.ps1 Deploy
.\demo.ps1 Dashboard
.\demo.ps1 Reset
```

Keep the same terminal for later scenario commands. Explicit `-ResourceGroup`, `-ClusterName`, `-GrafanaName` and `-GrafanaEndpoint` arguments override the corresponding environment variables in the runner. Python evidence helpers use the environment variables.

Open **ACNS Incident Investigation** in your Grafana workspace. Use **Last 30 minutes**, refresh **15s**, and select the correct Prometheus data source. Detailed per-command viewing instructions are in [section 4.6 of the detailed guide](./docs/ACNS-Detailed-Implementation-and-Demo-Guide.md#46-which-grafana-dashboard-to-open-for-each-command).

`PolicyBreak` removes a previous scenario allow rule so it can be repeated after `PolicyFix`. `Deploy` removes scenario policies and restarts the main workloads to restore baseline. Without `ACNS_GRAFANA_ENDPOINT`, workload actions issue a warning and skip annotations. With it configured, annotation upload status is recorded in the ignored `advanced\.local\annotation-status.log`; a queued annotation is not confirmation that it was uploaded.

## Publication and local evidence

Credentials are acquired through Azure CLI and are not configuration-file values. Do not save tokens, kubeconfig, passwords, or real environment configuration in the repository.

Screenshots, raw command evidence, exported PDF/DOCX/HTML guides, local configuration, logs, and Python caches are excluded by [.gitignore](./.gitignore). Original guides are retained locally under `.local\original-guides` when preparing this publication. Public Markdown is self-contained; historical measurements are illustrative rehearsal results, not a guarantee for a new environment.

Do not force-add ignored files. Review the staged file list and run an approved secret scanner before pushing. No license is selected here; the owner should choose appropriate reuse terms before distributing this as an open-source project.

Optional evidence capture requires Python 3.10+, Google Chrome, and:

```powershell
# Run from advanced; this is not needed for normal deployment or presentation.
python -m pip install -r .\requirements-capture.txt
```

Capture is restricted to your configured Azure Managed Grafana origin; third-party requests and redirects are blocked rather than forwarding a bearer token. Use canonical dashboard paths if a redirect is reported. Evidence outputs remain local and may still contain environment identifiers. The historical screenshot/measurement helpers default to 19 October 2026 UTC+4; set `ACNS_REHEARSAL_DATE` and edit their time windows for a new rehearsal.

## Offline validation

From the repository root:

```powershell
python -m unittest discover -s tests -p "test_*.py"
powershell -NoProfile -File .\tests\test_demo.ps1
```

These checks require Git, use mocks, and do not call Azure, access a cluster, or inject faults. Publication checks evaluate ignore rules in a temporary Git repository; they do not initialize or modify this folder's Git state. They do not replace live validation in an approved demo environment.

## Demo flow

```powershell
kubectl get pods -n netobs-demo
```

### Scenario 1: pod packet drops

The two `drop-client` pods repeatedly connect to `healthy-server`, while the `deny-drop-client-egress` NetworkPolicy allows DNS but rejects application egress. This produces deterministic policy-drop events for ACNS/Retina. `healthy-client` calls the same service without the deny policy and provides a successful comparison.

In Grafana, open **Dashboards > Azure Managed Prometheus > Kubernetes / Networking / Drops (Workload)**. Select:

- Cluster: `aks-overlay-netobs-demo`
- Namespace: `netobs-demo`
- Workload: `drop-client`
- Time range: **Last 15 minutes**

Compare the result with workload `healthy-client`. Initial metrics can take 5-10 minutes.

Useful PromQL in Explore:

```promql
sum by (cluster, instance, source, reason) (
  rate(hubble_drop_total{source=~"netobs-demo/.*"}[5m])
)
```

To list available drop labels before narrowing the query:

```promql
sum by (source, destination, reason) (
  increase(hubble_drop_total{source=~"netobs-demo/.*"}[10m])
)
```

### Scenario 2: pod deletion and replacement

Run a controlled deletion of one healthy server pod:

```powershell
.\invoke-pod-kill.ps1
```

The Deployment immediately creates a replacement. This tests workload resilience and pod lifecycle monitoring. A Kubernetes pod deletion is not necessarily a network packet drop, so monitor it separately in Grafana:

1. Open **Dashboards > Azure Managed Prometheus > Kubernetes / Compute Resources / Namespace (Pods)**.
2. Select cluster `aks-overlay-netobs-demo` and namespace `netobs-demo`.
3. Set the time range to **Last 15 minutes** and watch the pod count and pod status panels during the deletion.
4. Open **Explore**, select the Azure Monitor workspace data source, and run:

```promql
sum(kube_pod_status_phase{namespace="netobs-demo", pod=~"healthy-server-.*", phase="Running"})
```

To see pod start-time changes after replacement:

```promql
max by (pod) (
  kube_pod_start_time{namespace="netobs-demo", pod=~"healthy-server-.*"}
)
```

Container restart counters do not increase when Kubernetes replaces a deleted pod; the old pod disappears and a new pod name/start time appears.

## Customer enablement checklist

Before enabling the scenario in a customer environment:

1. Confirm the cluster uses Azure CNI or Azure CNI Overlay and that Kubernetes NetworkPolicy enforcement is supported and enabled for the selected dataplane.
2. Confirm the region and Kubernetes version support ACNS Container Network Observability.
3. Enable ACNS with `az aks update --enable-acns`.
4. Create or select an Azure Monitor workspace and Azure Managed Grafana instance.
5. Enable Managed Prometheus with `--enable-azure-monitor-metrics`, passing both resource IDs.
6. Verify `retina-agent`, `retina-operator`, `ama-metrics`, and `ama-metrics-node` are Running on the expected nodes.
7. Apply `pod-drop-demo.yaml` only in an approved test namespace. The drop clients generate continuous failed connection attempts until removed.
8. Wait 5-10 minutes, then validate `hubble_drop_total` in Grafana Explore before presenting the dashboard.
9. Run `invoke-pod-kill.ps1` only against a disposable Deployment and correlate its timestamp with the pod dashboards.
10. Remove the namespace after testing and retain ACNS/Prometheus only if they are part of the customer's approved monitoring design.

## Existing Azure CNI or Azure CNI Overlay cluster

Both classic Azure CNI and Azure CNI Overlay are supported. For a non-Cilium cluster:

```powershell
$resourceGroup = "<resource-group>"
$clusterName = "<aks-cluster>"
$location = "<location>"
$monitorName = "<azure-monitor-workspace>"
$grafanaName = "<globally-unique-grafana-name>"

az aks update -g $resourceGroup -n $clusterName --enable-acns
az aks update -g $resourceGroup -n $clusterName --network-policy azure
az resource create -g $resourceGroup --namespace Microsoft.Monitor --resource-type accounts -n $monitorName -l $location --properties '{}'
az grafana create -g $resourceGroup -n $grafanaName -l $location

$monitorId = az resource show -g $resourceGroup -n $monitorName --resource-type Microsoft.Monitor/accounts --query id -o tsv
$grafanaId = az grafana show -g $resourceGroup -n $grafanaName --query id -o tsv

az aks update -g $resourceGroup -n $clusterName --enable-managed-identity
az aks update -g $resourceGroup -n $clusterName --enable-azure-monitor-metrics --azure-monitor-workspace-resource-id $monitorId --grafana-resource-id $grafanaId
```

Verify collectors:

```powershell
kubectl get pods -n kube-system | Select-String "ama-metrics|retina"
```

## Cleanup

Only delete a resource group if it contains exclusively disposable demo resources. Otherwise remove the demo namespaces and retain the shared monitoring resources.

```powershell
kubectl delete namespace netobs-demo
az group delete --name rg-aks-netobs-demo --yes --no-wait
```