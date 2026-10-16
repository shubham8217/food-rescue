"""Builds the FoodRescue ingest flow in Apache NiFi through its REST API (idempotent).

    ListFile (/data/inbox/*.csv)
      -> FetchFile (moves the file to /data/archive)
      -> InvokeHTTP  POST backend /ingest/batch  (text/csv, X-API-Key)
           Retry               -> InvokeHTTP again (penalised)
           Failure / No Retry  -> PutFile /data/failed

Uses only the standard library so it runs in a plain python image.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("NIFI_API", "http://localhost:8080/nifi-api").rstrip("/")
BACKEND = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/")
API_KEY = os.environ.get("INGEST_API_KEY", "dev-ingest-key-change-me")
GROUP_NAME = "FoodRescue ingest"


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def wait_ready(timeout=300):
    end = time.time() + timeout
    while time.time() < end:
        try:
            call("GET", "/flow/about")
            return
        except Exception:  # noqa: BLE001
            time.sleep(5)
    sys.exit("NiFi did not become ready in time")


def processor(group, ptype, name, x, y, props, auto_terminate=(), period="1 sec"):
    body = {"revision": {"version": 0}, "component": {
        "type": ptype, "name": name, "position": {"x": x, "y": y},
        "config": {"properties": props, "autoTerminatedRelationships": list(auto_terminate),
                   "schedulingPeriod": period}}}
    return call("POST", f"/process-groups/{group}/processors", body)


def connect(group, src, dst, relationships):
    body = {"revision": {"version": 0}, "component": {
        "source": {"id": src["id"], "groupId": group, "type": "PROCESSOR"},
        "destination": {"id": dst["id"], "groupId": group, "type": "PROCESSOR"},
        "selectedRelationships": relationships}}
    call("POST", f"/process-groups/{group}/connections", body)


def existing_group(root):
    groups = call("GET", f"/process-groups/{root}/process-groups").get("processGroups", [])
    return next((g for g in groups if g["component"]["name"] == GROUP_NAME), None)


def main():
    wait_ready()
    root = call("GET", "/flow/process-groups/root")["processGroupFlow"]["id"]
    g = existing_group(root)
    if g:
        gid = g["id"]
        print("flow already deployed; making sure it is running")
    else:
        gid = call("POST", f"/process-groups/{root}/process-groups", {
            "revision": {"version": 0}, "component": {"name": GROUP_NAME, "position": {"x": 100, "y": 100}}})["id"]
        std = "org.apache.nifi.processors.standard."
        lst = processor(gid, std + "ListFile", "Watch data/inbox", 100, 80,
                        {"Input Directory": "/data/inbox", "File Filter": r".*\.csv", "Minimum File Age": "1 sec",
                         "Recurse Subdirectories": "false"}, period="2 sec")
        fetch = processor(gid, std + "FetchFile", "Fetch and archive", 100, 280,
                          {"Completion Strategy": "Move File", "Move Destination Directory": "/data/archive",
                           "Move Conflict Strategy": "Rename"}, auto_terminate=["permission.denied", "not.found", "failure"])
        post = processor(gid, std + "InvokeHTTP", "POST /ingest/batch", 100, 480,
                         {"HTTP Method": "POST", "Remote URL": f"{BACKEND}/ingest/batch", "Content-Type": "text/csv",
                          "send-message-body": "true", "X-API-Key": API_KEY},
                         auto_terminate=["Original", "Response"])
        failed = processor(gid, std + "PutFile", "Save failed files", 500, 480,
                           {"Directory": "/data/failed", "Conflict Resolution Strategy": "replace"},
                           auto_terminate=["success", "failure"])
        connect(gid, lst, fetch, ["success"])
        connect(gid, fetch, post, ["success"])
        connect(gid, post, post, ["Retry"])
        connect(gid, post, failed, ["Failure", "No Retry"])
        print("flow created")

    call("PUT", f"/flow/process-groups/{gid}", {"id": gid, "state": "RUNNING"})
    time.sleep(3)
    procs = call("GET", f"/process-groups/{gid}/processors")["processors"]
    bad = False
    for p in procs:
        c = p["component"]
        print(f"  {c['name']:<22} state={c['state']:<8} validation={c['validationStatus']}")
        for err in c.get("validationErrors", []) or []:
            print("     !", err)
            bad = True
    if bad:
        sys.exit("some processors are invalid, see messages above")
    print("NiFi flow is running")


if __name__ == "__main__":
    main()
