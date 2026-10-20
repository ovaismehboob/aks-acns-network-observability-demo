"""Query Managed Prometheus at fixed instants inside each scenario and save a measured-values table."""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from demo_config import endpoint_from_env, run_command

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "docs", "evidence", "20-measured-values.txt")
EP = endpoint_from_env("ACNS_PROMETHEUS_ENDPOINT", ".prometheus.monitor.azure.com") + "/api/v1/query"
DAY = os.environ.get("ACNS_REHEARSAL_DATE", "2026-10-19")

token = run_command(
    ["az", "account", "get-access-token", "--resource", "https://prometheus.monitor.azure.com", "--query", "accessToken", "-o", "tsv"],
).strip()
if not token:
    raise RuntimeError("Azure CLI returned no Prometheus token.")


def q(expr, hhmmss):
    t = int(datetime.fromisoformat("%sT%s+04:00" % (DAY, hhmmss)).timestamp())
    url = EP + "?" + urllib.parse.urlencode({"query": expr, "time": t})
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.load(r)
        if payload.get("status") != "success":
            raise RuntimeError("Prometheus query failed; response omitted.")
        return payload["data"]["result"]


def val(expr, t):
    res = q(expr, t)
    if not res:
        return "no series"
    return "; ".join("%s=%.3g" % ("/".join(v for k, v in sorted(s["metric"].items())) or "value", float(s["value"][1])) for s in res)


MOMENTS = [
    ("Baseline (before Scenario 1)", "17:45:00"),
    ("Scenario 1 fault, steady state", "17:55:30"),
    ("Scenario 1 after fix", "17:59:30"),
    ("Scenario 2 DNS failure, steady state", "18:03:30"),
    ("Scenario 3 slow dependency, steady state", "18:06:30"),
    ("Final baseline (after reset)", "18:16:30"),
]

METRICS = [
    ("Success ratio by app", 'sum by (app)(rate(demo_requests_total{result="ok",app=~"checkout-api|catalog-client"}[2m])) / sum by (app)(rate(demo_requests_total{app=~"checkout-api|catalog-client"}[2m]))'),
    ("p95 latency (s) by app", 'histogram_quantile(0.95, sum by (le,app)(rate(demo_request_duration_seconds_bucket{app=~"checkout-api|catalog-client"}[2m])))'),
    ("Failed requests/s by app and result", 'sum by (app,result)(rate(demo_requests_total{result!="ok"}[2m])) > 0'),
    ("ACNS drops/s by source workload and reason", 'sum by (reason,source)(label_replace(rate(hubble_drop_total{source=~"checkout-demo/.*"}[2m]),"source","$1","source","checkout-demo/(.*)-[a-z0-9]+-[a-z0-9]+")) > 0'),
    ("TCP flags/s for checkout-api", 'sum by (flag)(rate(hubble_tcp_flags_total{source=~"checkout-demo/checkout-api.*",flag=~"syn|syn-ack"}[2m]))'),
    ("DNS responses/s by rcode (dns clients)", 'sum by (rcode)(rate(hubble_dns_responses_total{destination=~"checkout-demo/dns.*"}[2m])) > 0'),
    ("DNS queries/s (dns clients)", 'sum by (source)(label_replace(rate(hubble_dns_queries_total{source=~"checkout-demo/dns.*"}[2m]),"source","$1","source","checkout-demo/(.*)-[a-z0-9]+-[a-z0-9]+")) > 0'),
]

lines = [f"Measured values from Azure Managed Prometheus, {DAY}, local time UTC+4.",
         "Each value is evaluated at the stated instant with a 2-minute rate window.", ""]
for title, t in MOMENTS:
    lines.append("=== %s @ %s" % (title, t))
    for name, expr in METRICS:
        lines.append("  %-42s %s" % (name, val(expr, t)))
    lines.append("")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("\n".join(lines))
