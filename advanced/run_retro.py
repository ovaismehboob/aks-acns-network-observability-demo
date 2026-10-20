"""Re-capture final Grafana screenshots using absolute time windows around each scenario.

Metric data persists in Managed Prometheus, so screenshots can be taken after the scenarios ran.
Times are local (UTC+4) for the 19 Oct 2026 rehearsal; edit WINDOWS for a new run.
"""
import os
from datetime import datetime, timedelta, timezone

from capture import capture, get_token
from demo_config import CLUSTER

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES = os.path.join(HERE, "..", "docs", "images", "advanced")
os.makedirs(IMAGES, exist_ok=True)
TZ = timezone(timedelta(hours=4))
DAY = os.environ.get("ACNS_REHEARSAL_DATE", "2026-10-19")


def ms(hhmm):
    return int(datetime.fromisoformat("%sT%s:00+04:00" % (DAY, hhmm)).timestamp() * 1000)


def rng(start, end):
    return "from=%d&to=%d" % (ms(start), ms(end))


DASH = "/d/acns-incident-investigation/acns-incident-investigation?orgId=1&kiosk&"
DROPS = ("/d/NetObsDropsWorkload6738/kubernetes-networking-drops-workload?orgId=1&kiosk"
         f"&var-cluster={CLUSTER}&var-namespace=checkout-demo&var-workload=checkout-api&")
DNS = ("/d/NetObsDNSWorkload6738/kubernetes-networking-dns-workload?orgId=1&kiosk"
       f"&var-cluster={CLUSTER}&var-namespace=checkout-demo&var-workload=%s&")

SHOTS = [
    ("00-baseline.png", DASH + rng("17:30", "17:46"), 1950),
    ("01-policy-break.png", DASH + rng("17:44", "17:56"), 1950),
    ("02-policy-fix.png", DASH + rng("17:46", "18:00"), 1950),
    ("03-dns-failures.png", DASH + rng("17:57", "18:08"), 1950),
    ("04-slow-dependency.png", DASH + rng("18:01", "18:12"), 1950),
    ("05-pod-replacement.png", DASH + rng("18:30", "18:44"), 1950),
    ("06-full-timeline.png", DASH + rng("17:40", "18:20"), 1950),
    ("01b-managed-drops-checkout-api.png", DROPS + rng("17:44", "18:02"), 1500),
    ("03b-managed-dns-typo-client.png", DNS % "dns-typo-client" + rng("17:57", "18:08"), 1700),
    ("03c-managed-dns-blocked-client.png", DNS % "dns-blocked-client" + rng("17:57", "18:08"), 1700),
]

if __name__ == "__main__":
    token = get_token()
    for name, path, height in SHOTS:
        capture([(os.path.join(IMAGES, name), path)], token=token, width=1700, height=height, settle=20)
