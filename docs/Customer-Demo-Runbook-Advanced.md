# ACNS Advanced Demo Runbook: "Checkout is failing, but every pod is Running"

> **Public version:** environment identifiers are placeholders. Screenshots, exports, and raw evidence remain local and are excluded from GitHub. Configure your environment using the [README](../README.md#advanced-demo-configuration) in the same terminal before the commands below.

**Audience:** Platform, networking, SRE and security teams evaluating Advanced Container Networking Services (ACNS) Container Network Observability on AKS.
**Duration:** ~30 minutes. **Environment:** `aks-overlay-netobs-demo` (Azure CNI Overlay, Azure dataplane, Azure Network Policy), Managed Prometheus, Azure Managed Grafana.

All commands run from `podleveldropsaks\advanced`. All demo workloads live in the `checkout-demo` namespace. The original `netobs-demo` namespace and every other namespace are never touched.

## 1. The story (say this first)

> "Kubernetes tells you pods are Running. It does not tell you whether they can reach each other, whether DNS works, or why a request is slow. ACNS adds that pod-level network evidence, so you can separate *policy denial*, *DNS failure* and *slow dependency* in seconds."

Application setup:

```text
checkout-api  ─┐
               ├─►  inventory (2 pods)       catalog-client = healthy control
catalog-client ┘
```

- Demo clients automatically generate traffic with two workers, each waiting 0.25 seconds after a request. Healthy traffic is roughly 7-8 requests/second per client; timeouts and delays lower the rate. Application metrics (`demo_requests_total`, `demo_request_duration_seconds`) show **user impact**.
- ACNS/Retina exposes **network evidence** (`hubble_drop_total`, `hubble_dns_*`, `hubble_tcp_flags_total`). These show **cause**.

## 2. Before the customer joins (T-30 min)

| # | Action | Command / check |
|---|---|---|
| 1 | Sign in and select subscription | `az login`; `az account set --subscription "<subscription-id>"` |
| 2 | Start cluster if stopped | `az aks start -g $env:ACNS_RESOURCE_GROUP -n $env:ACNS_CLUSTER_NAME` |
| 3 | Get credentials | `az aks get-credentials -g $env:ACNS_RESOURCE_GROUP -n $env:ACNS_CLUSTER_NAME --overwrite-existing` |
| 4 | Preflight | `.\demo.ps1 Preflight` - expect `acnsObservability: True`, `prometheus: True`, `retina-agent` on each node, `ama-metrics` Running |
| 5 | Deploy / refresh demo | `.\demo.ps1 Deploy` (idempotent) |
| 6 | Publish dashboard (first time) | `.\demo.ps1 Dashboard` |
| 7 | Reset to baseline | `.\demo.ps1 Reset` |
| 8 | Open Grafana dashboard | Open `$env:ACNS_GRAFANA_ENDPOINT`, find **ACNS Incident Investigation**, and set range **Last 30 minutes**, refresh **15s** |

**Baseline check (must pass):** success ratio ~100%, drops 0, Ready inventory pods 2. Allow **5 minutes** after `Deploy` for metrics. Do not start the customer session on an empty dashboard.

Rights needed in Grafana: **Grafana Editor** (to publish the dashboard and annotations). Presenting only needs Viewer.

## 3. Run of show

Keep two windows: Grafana (**ACNS Incident Investigation**) and a terminal. Orange vertical markers are requested automatically by `demo.ps1` when `ACNS_GRAFANA_ENDPOINT` is configured. Check the local `advanced\.local\annotation-status.log` for upload failures.

### Act 0: Healthy baseline (3 min)

- Show the four tiles: success ratio ~100%, low p95 latency, ACNS drops 0, 2 inventory pods Ready.
- Point out panel 5: both workloads show a TCP SYN rate of about 7.7/s. This is the healthy connection-attempt level; watch how it changes, not the absolute value.

### Act 1: Policy regression and surgical fix (9 min)

**Scenario:** a security change restricts access to `inventory` and forgets `checkout-api`. Every pod stays Running.

```powershell
.\demo.ps1 PolicyBreak
```

Wait ~60-90 seconds, then walk the dashboard top-down:

| Step | Dashboard | What to say |
|---|---|---|
| 1. Symptom | Panel 1 | "checkout-api success ratio falls. catalog-client is fine - same backend, so the backend is not down." |
| 2. Failure type | Panel 2 | "Failures are `timeout`: connections not answered, not HTTP errors." |
| 3. Evidence | Panel 4 | "ACNS attributes drops to the `checkout-api` workload with reason `policy_denied`." |
| 4. Mechanism | Panel 5 | "checkout-api's connection attempts fall from ~7.7/s to ~1.8/s: each call now waits out a timeout instead of completing." |
| 5. Inspect | Terminal | `kubectl get networkpolicy -n checkout-demo` and `kubectl describe networkpolicy inventory-restrict -n checkout-demo` |

Fix with a narrow, additive rule (isolation stays in place):

```powershell
.\demo.ps1 PolicyFix
```

Within ~1-2 minutes: success ratio returns to ~100%, drops flatten, connection attempts return to ~7.7/s. Show **catalog-client was never affected**.

**Key message:** "Without ACNS you would suspect the app, the node and the service. With ACNS you go straight to *which workload, which direction, which reason*."

### Act 2: DNS - wrong name versus blocked DNS (8 min)

**Scenario:** two clients fail the same way at application level (`dns_error`).

```powershell
.\demo.ps1 DnsStart
```

Wait ~90 seconds.

| Client | What it does |
|---|---|
| `dns-typo-client` | Calls `inventory-v2`, a name that does not exist |
| `dns-blocked-client` | Calls a valid name, but a policy denies all egress including DNS |

- Panel 2: both show `dns_error`. "To the application these are identical."
- Panel 6 (return codes): `dns-typo-client` receives `non-existent domain` (NXDOMAIN). "DNS is healthy; the **name** is wrong."
- Panel 7 (queries vs responses): `dns-blocked-client` sends queries and gets **no responses**.
- Panel 4: drops from `dns-blocked-client` with `policy_denied`. "DNS is **blocked**; the name is fine."

```powershell
.\demo.ps1 DnsStop
```

**Key message:** same symptom, opposite fixes. ACNS tells you which one before you touch anything.

### Act 3: Slow dependency is not packet loss (5 min)

```powershell
.\demo.ps1 SlowOn          # 800 ms delay inside the inventory application
```

Wait ~90 seconds.

- Panel 3: p95 latency rises for **both** callers (~1 s).
- Panel 4 and panel 2: no new drops, no failures. Success ratio stays ~100%.
- "Latency alone is not a network fault. ACNS lets you rule the network in or out quickly, so the right team investigates."

```powershell
.\demo.ps1 SlowOff
```

### Act 4 (optional): Self-healing (3 min)

```powershell
.\demo.ps1 KillPod
```

- Output shows the deleted pod and a **new** Ready pod name.
- Panel 8: one pod line ends, a new pod line starts; success ratio stays high.
- "A pod deletion is a lifecycle event, not a packet drop. That is why ACNS drops stay flat."

### Close (2 min)

- Drill-down: open **Dashboards > Azure Managed Prometheus > Kubernetes / Networking / Drops (Workload)** and **DNS (Workload)** (links on the dashboard).
- Customer takeaways: pod-level attribution, no app changes needed for network evidence, managed Prometheus + Grafana, enable on existing Azure CNI / Overlay clusters.

## 4. Reset between sessions

```powershell
.\demo.ps1 Reset      # removes scenario policies, stops DNS clients, clears delay
```

`Reset` is safe to run at any time. Re-running `Deploy` also resets scenario state.

## 5. If something looks wrong

| Symptom | Likely cause | Action |
|---|---|---|
| All panels empty | Metrics not yet ingested, or cluster just started | Wait 5 min; run `.\demo.ps1 Preflight`; confirm `ama-metrics` and `retina-agent` Running |
| Only application panels populate | ACNS agents not ready | `kubectl get pods -n kube-system \| Select-String retina`; wait for Running |
| Fault applied but no drops yet | Ingestion lag (30-120 s) | Keep talking through the story; set range to **Last 15 minutes** |
| DNS clients not visible | They run only between `DnsStart` and `DnsStop` | Run `.\demo.ps1 DnsStart` and wait ~90 s |
| Dashboard publish returns 403 | No Grafana Editor role | Assign **Grafana Editor** on the Grafana resource, wait a few minutes |
| `kubectl` cannot connect | Cluster stopped or stale credentials | `az aks start`, then `az aks get-credentials --overwrite-existing` |
| Node CPU pressure / Pending pods | Shared cluster is busy | Pods request 10m CPU; stop other demo namespaces if needed |

## 6. Rehearsal results (19 Oct 2026, this cluster)

Every scenario was run end to end and checked against Managed Prometheus.

| Phase | Observed result |
|---|---|
| Baseline | success 100%, p95 ≈ 0.02 s, drops 0 |
| Act 1 break | `checkout-api` success fell to 0%, then ~95% as probes retried; ACNS `policy_denied` drops 0.6-1.8/s attributed to `checkout-api`; `catalog-client` stayed at 100%; timeouts visible within ~20 s |
| Act 1 fix | `checkout-api` back to 100% within seconds; drops 0 |
| Act 2 | `dns-typo-client` received `non-existent domain` (~19-28 queries/s); `dns-blocked-client` sent queries (~1/s) with no responses and `policy_denied` drops |
| Act 3 | p95 rose from 0.02 s to ~0.97 s for both callers; success 100%; no drops; DNS and drop signals unchanged |
| Act 4 | deleted inventory pod replaced by a differently named Ready pod; success stayed 100% |

Notes from rehearsal:

- Scenario commands take 3-25 seconds. Scenario effects appear in Grafana after ~60-120 seconds of ingestion.
- Drop and DNS counters from ACNS were visible within the same 2-minute window as the application impact.
- During the rehearsal the presenter laptop had intermittent slow Azure CLI/API connectivity. The runner retries `kubectl` automatically and posts Grafana markers in the background, so a slow link does not stall the demo. Run `Preflight` on the same network you will present from.

## 7. Honest scope statements (use with the customer)

- This cluster uses the **Azure dataplane**. Container network metrics (drops, DNS, TCP) are available. **Cilium-only** capabilities (for example source-level metric filtering, FQDN policy DNS metrics) are not part of this demo.
- Application metrics (`demo_*`) come from the demo clients, not from ACNS. ACNS provides the network evidence beside them.
- A failed request is not automatically a dropped packet. Only observed datapath drops appear in drop metrics; Act 3 demonstrates this explicitly.
- DNS metrics are per workload and per return code as exported by Retina; names of queried domains are not shown on this dataplane.

## 8. Cleanup

```powershell
.\demo.ps1 Cleanup        # deletes only the checkout-demo namespace
```

Optionally remove the Grafana role assignment added for demo setup:

```powershell
az role assignment delete --assignee <your-object-id> --role "Grafana Editor" `
  --scope (az grafana show -g $env:ACNS_RESOURCE_GROUP -n $env:ACNS_GRAFANA_NAME --query id -o tsv)
```

Stop the cluster to save cost: `az aks stop -g rg-aks-netobs-demo -n aks-overlay-netobs-demo`.

## 9. Quick reference: PromQL used

```promql
# Drops by workload and reason
sum by (source, reason) (rate(hubble_drop_total{source=~"checkout-demo/.*"}[2m]))

# DNS responses by return code
sum by (destination, rcode) (rate(hubble_dns_responses_total{destination=~"checkout-demo/.*"}[2m]))

# Handshake health
sum by (source) (rate(hubble_tcp_flags_total{source=~"checkout-demo/checkout-api.*", flag="syn"}[2m]))

# Application success ratio and p95 latency
sum by (app) (rate(demo_requests_total{result="ok"}[2m])) / sum by (app) (rate(demo_requests_total[2m]))
histogram_quantile(0.95, sum by (le, app) (rate(demo_request_duration_seconds_bucket[2m])))
```

Metric labels used here (`source`, `destination`, `reason`, `rcode`, `flag`) were verified against this cluster's Managed Prometheus data. Source: [Container network metrics](https://learn.microsoft.com/azure/aks/container-network-observability-metrics).
