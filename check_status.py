import requests

NODES = {
    1: "http://localhost:5001",
    2: "http://localhost:5002",
    3: "http://localhost:5003",
}

print("\n" + "="*50)
print(f"  {'NODE':<8} {'STATE':<12} {'TERM':<8} {'LEADER'}")
print("="*50)

for node_id, url in NODES.items():
    try:
        r = requests.get(f"{url}/status", timeout=1.5)
        d = r.json()
        marker = "  ◀ LEADER" if d["state"] == "leader" else ""
        print(f"  Node {node_id:<3}  {d['state'].upper():<12} {d['term']:<8} {d['leader']}{marker}")
    except Exception:
        print(f"  Node {node_id:<3}  {'OFFLINE':<12} -        -")

print("="*50 + "\n")
