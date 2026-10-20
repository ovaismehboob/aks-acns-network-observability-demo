"""Re-run the pod replacement scenario, save evidence and capture the dashboard."""
import os
import time
from datetime import datetime, timedelta

from capture import capture, get_token
from demo_config import CLUSTER, endpoint_from_env, run_command

HERE = os.path.dirname(os.path.abspath(__file__))
EVIDENCE = os.path.join(HERE, "..", "docs", "evidence")
IMAGES = os.path.join(HERE, "..", "docs", "images", "advanced")
os.makedirs(EVIDENCE, exist_ok=True)
os.makedirs(IMAGES, exist_ok=True)


def save(name, text):
    with open(os.path.join(EVIDENCE, name), "w", encoding="utf-8") as f:
        f.write(text)


def kubectl(name, *args):
    output = run_command(["kubectl", "--context", CLUSTER, "--request-timeout=60s", *args], timeout=180)
    save(name, "$ kubectl " + " ".join(args) + "\n\n" + output)


endpoint_from_env("ACNS_GRAFANA_ENDPOINT", ".grafana.azure.com")
get_token()
kubectl("05-pods-before-kill.txt", "get", "pods", "-n", "checkout-demo", "-l", "app=inventory", "-o", "wide")
start = datetime.now()
output = run_command(["powershell", "-NoProfile", "-File", os.path.join(HERE, "demo.ps1"), "-Action", "KillPod"],
                     timeout=900)
save("action-killpod.txt", "demo.ps1 -Action KillPod (Windows PowerShell 5.1, started %s)\n\n%s" % (start.strftime("%H:%M:%S"), output))
print("Replacement command completed successfully.")
kubectl("05-pods-after-kill.txt", "get", "pods,endpoints", "-n", "checkout-demo", "-l", "app=inventory")
time.sleep(240)
end = datetime.now()
frm = int((start - timedelta(minutes=4)).timestamp() * 1000)
to = int((end + timedelta(minutes=1)).timestamp() * 1000)
path = "/d/acns-incident-investigation/acns-incident-investigation?orgId=1&kiosk&from=%d&to=%d" % (frm, to)
capture([(os.path.join(IMAGES, "05-pod-replacement.png"), path)], token=get_token(), width=1700, height=1950, settle=20)
print("window", (start - timedelta(minutes=4)).strftime("%H:%M"), "->", (end + timedelta(minutes=1)).strftime("%H:%M"))
