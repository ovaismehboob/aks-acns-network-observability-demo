import json

DS = {"type": "prometheus", "uid": "${ds}"}
WL_SRC = 'label_replace({expr},"workload","$1","{label}","checkout-demo/(.*)-[a-z0-9]+-[a-z0-9]+")'
_id = [0]


def nid():
    _id[0] += 1
    return _id[0]


def stat(title, expr, x, unit="short", thresholds=None, decimals=None):
    steps = thresholds or [{"color": "green", "value": None}]
    defaults = {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps}}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {
        "id": nid(), "type": "stat", "title": title, "datasource": DS,
        "gridPos": {"h": 4, "w": 6, "x": x, "y": 0},
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background", "graphMode": "area"},
        "targets": [{"refId": "A", "expr": expr, "instant": False}],
    }


def ts(title, targets, x, y, w=12, unit="short", desc="", ymin=0, ymax=None):
    defaults = {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 10}}
    if ymin is not None:
        defaults["min"] = ymin
    if ymax is not None:
        defaults["max"] = ymax
    return {
        "id": nid(), "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"h": 9, "w": w, "x": x, "y": y},
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l} for i, (e, l) in enumerate(targets)],
    }


def wl(expr, label):
    return WL_SRC.format(expr=expr, label=label)


panels = [
    stat("checkout-api success ratio",
         'sum(rate(demo_requests_total{app="checkout-api",result="ok"}[2m])) / sum(rate(demo_requests_total{app="checkout-api"}[2m]))',
         0, "percentunit",
         [{"color": "red", "value": None}, {"color": "orange", "value": 0.9}, {"color": "green", "value": 0.99}], 1),
    stat("checkout-api p95 latency",
         'histogram_quantile(0.95, sum by (le)(rate(demo_request_duration_seconds_bucket{app="checkout-api"}[2m])))',
         6, "s", [{"color": "green", "value": None}, {"color": "orange", "value": 0.5}, {"color": "red", "value": 1.5}], 2),
    stat("ACNS drops in checkout-demo (/s)",
         'sum(rate(hubble_drop_total{source=~"checkout-demo/.*"}[2m])) or vector(0)',
         12, "ops", [{"color": "green", "value": None}, {"color": "red", "value": 0.1}], 2),
    stat("Ready inventory pods",
         'sum(kube_pod_status_ready{namespace="checkout-demo",pod=~"inventory-.*",condition="true"})',
         18, "short", [{"color": "red", "value": None}, {"color": "orange", "value": 1}, {"color": "green", "value": 2}], 0),

    ts("1. Application impact: success ratio by workload",
       [('sum by (app)(rate(demo_requests_total{result="ok"}[2m])) / sum by (app)(rate(demo_requests_total[2m]))', "{{app}}")],
       0, 4, unit="percentunit", ymin=0, ymax=1,
       desc="Application-side view (demo clients). Shows user impact, not the cause."),
    ts("2. Application impact: failed requests by result",
       [('sum by (app,result)(rate(demo_requests_total{result!="ok"}[2m])) > 0', "{{app}} / {{result}}")],
       12, 4, unit="reqps",
       desc="timeout = packets not answered; dns_error = name resolution failed. Both look like failures to the app."),
    ts("3. Latency: p95 request duration by workload",
       [('histogram_quantile(0.95, sum by (le,app)(rate(demo_request_duration_seconds_bucket{app=~"checkout-api|catalog-client"}[2m])))', "{{app}}")],
       0, 13, unit="s",
       desc="Slow dependency: latency rises for every caller while ACNS drops stay at zero."),
    ts("4. ACNS: packet drops by workload and reason",
       [(wl('rate(hubble_drop_total{source=~"checkout-demo/.*"}[2m])', "source").join(['sum by (workload,reason)(', ')']), "from {{workload}} / {{reason}}"),
        (wl('rate(hubble_drop_total{destination=~"checkout-demo/.*"}[2m])', "destination").join(['sum by (workload,reason)(', ')']), "to {{workload}} / {{reason}}")],
       12, 13, unit="pps",
       desc="Source: Retina/Hubble drop counters attributed to Kubernetes workloads. policy_denied = NetworkPolicy."),
    ts("5. ACNS: TCP SYN rate (connection attempts) by workload",
       [(wl('rate(hubble_tcp_flags_total{source=~"checkout-demo/(checkout-api|catalog-client).*",flag="syn"}[2m])', "source").join(['sum by (workload)(', ')']), "{{workload}} SYN/s")],
       0, 22, unit="pps",
       desc="Observed TCP connection attempts per workload. A blocked caller spends its time waiting for timeouts, so its attempt rate collapses. Use together with drops (4); the syn-ack counter is too sparse on this dataplane to use as a signal."),
    ts("6. ACNS DNS: responses by return code",
       [(wl('rate(hubble_dns_responses_total{destination=~"checkout-demo/.*"}[2m])', "destination").join(['sum by (workload,rcode)(', ')']), "{{workload}} / {{rcode}}")],
       12, 22, unit="ops",
       desc="NXDOMAIN ('non-existent domain') = the name is wrong. DNS server answered."),
    ts("7. ACNS DNS: queries sent vs responses received",
       [(wl('rate(hubble_dns_queries_total{source=~"checkout-demo/.*"}[2m])', "source").join(['sum by (workload)(', ')']), "queries {{workload}}"),
        (wl('rate(hubble_dns_responses_total{destination=~"checkout-demo/.*"}[2m])', "destination").join(['sum by (workload)(', ')']), "responses {{workload}}")],
       0, 31, unit="ops",
       desc="Queries with no matching responses = DNS traffic is being blocked (not a bad name)."),
    ts("8. Resilience: inventory pods Ready",
       [('kube_pod_status_ready{namespace="checkout-demo",pod=~"inventory-.*",condition="true"}', "{{pod}}")],
       12, 31, unit="short", ymin=0, ymax=1,
       desc="One line per pod name. A deleted pod disappears and a new pod name appears."),
    {
        "id": nid(), "type": "text", "title": "How to read this dashboard",
        "gridPos": {"h": 8, "w": 24, "x": 0, "y": 40},
        "options": {"mode": "markdown", "content":
            "**Vertical markers** are scenario steps posted by `demo.ps1`.\n\n"
            "| Symptom | Where to look | Meaning |\n|---|---|---|\n"
            "| Success ratio falls, drops (4) rise, connection attempts fall (5) | panels 1, 4, 5 | NetworkPolicy denial (`policy_denied`) |\n"
            "| Failures are `dns_error`, rcode NXDOMAIN (6) | panels 2, 6 | Wrong hostname; DNS is healthy |\n"
            "| Failures are `dns_error`, queries without responses (7), drops from the client | panels 2, 7, 4 | DNS traffic is blocked |\n"
            "| Latency rises (3) for all callers, drops flat (4) | panels 3, 4 | Slow dependency, **not** a network drop |\n"
            "| Pod count dips (8), success stays high | panels 8, 1 | Self-healing worked |\n\n"
            "Managed dashboards for drill-down: "
            "[Drops (Workload)](/d/NetObsDropsWorkload6738) | [DNS (Workload)](/d/NetObsDNSWorkload6738)"},
    },
]

dashboard = {
    "uid": "acns-incident-investigation",
    "title": "ACNS Incident Investigation",
    "tags": ["acns", "demo", "aks"],
    "timezone": "browser",
    "schemaVersion": 39,
    "version": 1,
    "refresh": "15s",
    "time": {"from": "now-30m", "to": "now"},
    "templating": {"list": [{
        "name": "ds", "label": "Prometheus", "type": "datasource", "query": "prometheus",
        "current": {}, "hide": 0,
    }]},
    "annotations": {"list": [{
        "name": "Demo steps", "enable": True, "iconColor": "orange",
        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
        "target": {"type": "tags", "tags": ["acns-demo"], "limit": 200, "matchAny": False},
    }]},
    "panels": panels,
}

with open("acns-incident-dashboard.json", "w", encoding="utf-8") as f:
    json.dump(dashboard, f, indent=2)
