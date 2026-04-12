import requests

# ── RAFT Nodes ──
NODES = {
    1: "http://localhost:5001",
    2: "http://localhost:5002",
    3: "http://localhost:5003",
   
}

# ── Fetch statuses to determine column widths dynamically ──
statuses = {}
for node_id, url in NODES.items():
    try:
        r = requests.get(f"{url}/status", timeout=1.5)
        data = r.json()
        state  = data.get("state", "UNKNOWN").upper()
        term   = str(data.get("term", "-"))
        leader = str(data.get("leader", "-"))
        statuses[node_id] = (state, term, leader)
    except Exception:
        statuses[node_id] = ("OFFLINE", "-", "-")

# ── Determine column widths ──
node_col   = max(len(f"Node {nid}") for nid in NODES) + 2
state_col  = max(len(s[0]) for s in statuses.values()) + 2
term_col   = max(len(s[1]) for s in statuses.values()) + 2
leader_col = max(len(s[2]) for s in statuses.values()) + 2

# ── Print table header ──
total_width = node_col + state_col + term_col + leader_col + 10
print("\n" + "="*total_width)
print(f"{'NODE':<{node_col}}{'STATE':<{state_col}}{'TERM':<{term_col}}{'LEADER':<{leader_col}}")
print("="*total_width)

# ── Print node statuses ──
for node_id, (state, term, leader) in statuses.items():
    marker = "  ◀ LEADER" if state == "LEADER" else ""
    print(f"Node {node_id:<{node_col-5}}{state:<{state_col}}{term:<{term_col}}{leader:<{leader_col}}{marker}")

print("="*total_width + "\n")
