"""Record read-only ACNS configuration evidence into docs\\evidence."""
import json
import os
import shlex

from demo_config import CLUSTER, GRAFANA_NAME, MONITOR, RESOURCE_GROUP, run_command

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE = os.path.join(HERE, "..", "docs", "evidence")
os.makedirs(EVIDENCE, exist_ok=True)

RG = RESOURCE_GROUP
GRAFANA = GRAFANA_NAME
if not GRAFANA:
    raise ValueError("Set ACNS_GRAFANA_NAME before collecting evidence.")


def run(cmd, timeout=300):
    return run_command(shlex.split(cmd), timeout=timeout), ""


def save(name, title, command, stdout):
    with open(os.path.join(EVIDENCE, name), "w", encoding="utf-8") as f:
        f.write("$ %s\n\n%s" % (command, stdout))
    print("saved", name)


def az_json(name, command, query):
    full = 'az %s --query "%s" -o json --only-show-errors' % (command, query)
    out, _ = run(full)
    out = json.dumps(json.loads(out), indent=2)
    save(name, name, "az " + command + " --query \"" + query + "\" -o json", out)


out = run_command(["az", "version", "-o", "json", "--only-show-errors"])
save("10-az-version.txt", "az version", "az version -o json", json.dumps(json.loads(out), indent=2))

az_json("11-aks-network-acns.txt",
        "aks show -g %s -n %s" % (RG, CLUSTER),
        "{kubernetesVersion:kubernetesVersion,location:location,networkPlugin:networkProfile.networkPlugin,"
        "networkPluginMode:networkProfile.networkPluginMode,networkDataplane:networkProfile.networkDataplane,"
        "networkPolicy:networkProfile.networkPolicy,podCidr:networkProfile.podCidr,serviceCidr:networkProfile.serviceCidr,"
        "advancedNetworking:networkProfile.advancedNetworking,managedPrometheus:azureMonitorProfile.metrics.enabled,"
        "nodePools:agentPoolProfiles[].{name:name,count:count,vmSize:vmSize,osSKU:osSku}}")

az_json("12-grafana-integration.txt",
        "grafana show -g %s -n %s" % (RG, GRAFANA),
        "{name:name,sku:sku.name,version:properties.grafanaVersion,integrations:properties.grafanaIntegrations,"
        "state:properties.provisioningState}")

az_json("13-azure-monitor-workspace.txt",
        "resource show -g %s -n %s --resource-type Microsoft.Monitor/accounts" % (RG, MONITOR),
        "{name:name,state:properties.provisioningState,prometheusQueryEndpoint:properties.metrics.prometheusQueryEndpoint}")

az_json("14-resource-group-inventory.txt",
        "resource list -g %s" % RG,
        "[?!contains(type,'prometheusRuleGroups')].{name:name,type:type}")

for name, args in (
    ("15-kube-system-acns-pods.txt", "get pods -n kube-system -o wide"),
    ("16-nodes.txt", "get nodes -o wide"),
    ("17-all-demo-namespaces.txt", "get pods -A -o wide"),
    ("18-podmonitor.txt", "get podmonitors.azmonitoring.coreos.com -n checkout-demo"),
):
    out, err = run("kubectl --context %s --request-timeout=60s %s" % (CLUSTER, args))
    if name.startswith("15"):
        out = "\n".join(l for l in out.splitlines() if l.startswith("NAME") or "retina" in l or "ama-metrics" in l or "hubble" in l)
    if name.startswith("17"):
        out = "\n".join(l for l in out.splitlines() if l.startswith("NAMESPACE") or "checkout-demo" in l or "netobs-demo" in l)
    save(name, name, "kubectl " + args, out + err)
