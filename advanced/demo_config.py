"""Shared local configuration and checked CLI execution for evidence helpers."""
import os
import shutil
import subprocess
from urllib.parse import urlsplit

RESOURCE_GROUP = os.environ.get("ACNS_RESOURCE_GROUP", "rg-aks-netobs-demo")
CLUSTER = os.environ.get("ACNS_CLUSTER_NAME", "aks-overlay-netobs-demo")
MONITOR = os.environ.get("ACNS_MONITOR_WORKSPACE", "amw-overlay-netobs-demo")
GRAFANA_NAME = os.environ.get("ACNS_GRAFANA_NAME", "")


def endpoint_from_env(name, suffix):
    value = os.environ.get(name, "").rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(suffix)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path
    ):
        raise ValueError(f"Set {name} to the HTTPS workspace base endpoint (no credentials or query).")
    return value


def run_command(args, timeout=300):
    executable = shutil.which(args[0])
    if not executable:
        raise RuntimeError(f"Required command not found: {args[0]}")
    try:
        result = subprocess.run(
            [executable, *args[1:]], capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{args[0]} timed out; no command output was logged.") from None
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode}); no command output was logged.")
    return result.stdout
