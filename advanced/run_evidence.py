"""Run every demo scenario and capture Grafana screenshots plus kubectl evidence.

Usage: python run_evidence.py
Output: ..\\docs\\images\\advanced\\*.png and ..\\docs\\evidence\\*.txt
"""
import os
import time
from datetime import datetime

from capture import capture, get_token
from demo_config import CLUSTER, endpoint_from_env, run_command

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES = os.path.join(HERE, "..", "docs", "images", "advanced")
EVIDENCE = os.path.join(HERE, "..", "docs", "evidence")
os.makedirs(IMAGES, exist_ok=True)
os.makedirs(EVIDENCE, exist_ok=True)

DASH = "/d/acns-incident-investigation/acns-incident-investigation?orgId=1&from=now-30m&to=now&kiosk"
DROPS = ("/d/NetObsDropsWorkload6738/kubernetes-networking-drops-workload?orgId=1&from=now-15m&to=now"
         f"&var-cluster={CLUSTER}&var-namespace=checkout-demo&var-workload=checkout-api&kiosk")
DNS = ("/d/NetObsDNSWorkload6738/kubernetes-networking-dns-workload?orgId=1&from=now-15m&to=now"
       f"&var-cluster={CLUSTER}&var-namespace=checkout-demo&var-workload=dns-typo-client&kiosk")

STAMP = lambda: datetime.now().strftime("%H:%M:%S")


def log(message):
    print("[%s] %s" % (STAMP(), message), flush=True)


def demo(action):
    log("demo.ps1 -Action " + action)
    started = STAMP()
    output = run_command(
        ["powershell", "-NoProfile", "-File", os.path.join(HERE, "demo.ps1"), "-Action", action],
        timeout=900,
    ).strip()
    save_text("action-" + action.lower() + ".txt", "demo.ps1 -Action %s (started %s)\n\n%s" % (action, started, output))
    return output


def kubectl(name, *args):
    output = run_command(["kubectl", "--context", CLUSTER, "--request-timeout=60s", *args], timeout=180)
    save_text(name, "$ kubectl " + " ".join(args) + "\n\n" + output)


def save_text(name, content):
    with open(os.path.join(EVIDENCE, name), "w", encoding="utf-8") as f:
        f.write(content)


def shot(name, path, height=1950, settle=20):
    log("capture " + name)
    capture([(os.path.join(IMAGES, name), path)], width=1700, height=height, settle=settle)


def main():
    endpoint_from_env("ACNS_GRAFANA_ENDPOINT", ".grafana.azure.com")
    get_token()
    try:
        demo("Reset")
        time.sleep(60)
        kubectl("00-baseline-pods.txt", "get", "pods,svc,networkpolicy", "-n", "checkout-demo", "-o", "wide")
        shot("00-baseline.png", DASH)

        demo("PolicyBreak")
        kubectl("01-policy-restrict.txt", "describe", "networkpolicy", "inventory-restrict", "-n", "checkout-demo")
        time.sleep(150)
        shot("01-policy-break.png", DASH)
        shot("01b-managed-drops-checkout-api.png", DROPS, height=1500)
        demo("PolicyFix")
        kubectl("02-policy-after-fix.txt", "get", "networkpolicy", "-n", "checkout-demo")
        time.sleep(120)
        shot("02-policy-fix.png", DASH)

        demo("DnsStart")
        time.sleep(150)
        shot("03-dns-failures.png", DASH)
        shot("03b-managed-dns-typo-client.png", DNS, height=1500)
        shot("03c-managed-dns-blocked-client.png", DNS.replace("dns-typo-client", "dns-blocked-client"), height=1500)
        demo("DnsStop")

        demo("SlowOn")
        time.sleep(150)
        shot("04-slow-dependency.png", DASH)
        demo("SlowOff")
        time.sleep(30)

        kubectl("05-pods-before-kill.txt", "get", "pods", "-n", "checkout-demo", "-l", "app=inventory", "-o", "wide")
        demo("KillPod")
        time.sleep(90)
        kubectl("05-pods-after-kill.txt", "get", "pods,endpoints", "-n", "checkout-demo", "-l", "app=inventory")
        shot("05-pod-replacement.png", DASH)
    finally:
        log("Restoring baseline; if this fails, run demo.ps1 Reset manually.")
        demo("Reset")
    log("DONE")


if __name__ == "__main__":
    main()
