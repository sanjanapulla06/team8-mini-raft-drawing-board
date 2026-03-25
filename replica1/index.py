# index.py — Main entry point for replica node
# Wires together: Sharon's election (r1.py) + Shrivadhu's log replication
# Shrivadhu — Week 2 + Week 3

import os
import threading
import time
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

from log import Log
from replication import replicate_entry, send_heartbeats
from rpc import create_rpc_blueprint
from sync import request_catch_up

# ── Import Sharon's RaftNode (election logic) ─────────────────────────────────
from r1 import RaftNode

# ── Config from environment variables ─────────────────────────────────────────
REPLICA_ID  = os.environ.get("REPLICA_ID", "replica1")
PORT        = int(os.environ.get("PORT", 5001))
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")

REPLICA1_URL = os.environ.get("REPLICA1_URL", "http://replica1:5001")
REPLICA2_URL = os.environ.get("REPLICA2_URL", "http://replica2:5002")
REPLICA3_URL = os.environ.get("REPLICA3_URL", "http://replica3:5003")

# ── Map REPLICA_ID string to integer node id for Sharon's RaftNode ────────────
REPLICA_ID_MAP = {
    "replica1": 1,
    "replica2": 2,
    "replica3": 3,
}
NODE_ID = REPLICA_ID_MAP.get(REPLICA_ID, 1)

# ── Peers (everyone except self) ──────────────────────────────────────────────
ALL_REPLICAS = [
    {"id": "replica1", "url": REPLICA1_URL},
    {"id": "replica2", "url": REPLICA2_URL},
    {"id": "replica3", "url": REPLICA3_URL},
]
PEERS = [r for r in ALL_REPLICAS if r["id"] != REPLICA_ID]

# ── Adapter: wraps Sharon's RaftNode to match Shrivadhu's state interface ─────
# Sharon's RaftNode uses: node.state, node.current_term, node.voted_for, node.leader_id
# Shrivadhu's code uses:  state.role,  state.current_term, state.voted_for, state.leader_id

class SharonStateAdapter:
    """
    Wraps Sharon's RaftNode so Shrivadhu's replication/rpc code
    can call state.role, state.is_leader() etc. without changes.
    """
    def __init__(self, raft_node):
        self._node = raft_node

    @property
    def replica_id(self):
        return REPLICA_ID

    @property
    def role(self):
        return self._node.state  # Sharon uses "follower"/"candidate"/"leader"

    @role.setter
    def role(self, value):
        self._node.state = value

    @property
    def current_term(self):
        return self._node.current_term

    @current_term.setter
    def current_term(self, value):
        self._node.current_term = value

    @property
    def voted_for(self):
        return self._node.voted_for

    @voted_for.setter
    def voted_for(self, value):
        self._node.voted_for = value

    @property
    def leader_id(self):
        return self._node.leader_id

    @leader_id.setter
    def leader_id(self, value):
        self._node.leader_id = value

    def is_leader(self):
        return self._node.state == "leader"

    def is_follower(self):
        return self._node.state == "follower"

    def is_candidate(self):
        return self._node.state == "candidate"

    def become_follower(self, term):
        self._node._step_down(term)

    def become_leader(self):
        self._node.state     = "leader"
        self._node.leader_id = self._node.id


# ── Adapter: wraps Sharon's RaftNode as ElectionManager ──────────────────────
class SharonElectionAdapter:
    """
    Wraps Sharon's RaftNode so Shrivadhu's rpc code
    can call election_mgr.reset_election_timer() without changes.
    """
    def __init__(self, raft_node, peers):
        self._node = raft_node
        self.peers = peers

    def reset_election_timer(self):
        # Reset Sharon's election timer by updating last_heartbeat
        self._node.last_heartbeat = time.time()


# ── Flask app setup ───────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

# Start Sharon's RaftNode (handles all election logic)
raft_node    = RaftNode(NODE_ID)

# Wrap Sharon's node with adapters for Shrivadhu's code
state        = SharonStateAdapter(raft_node)
election_mgr = SharonElectionAdapter(raft_node, PEERS)

# Shrivadhu's stroke log
log = Log()

# ── Notify gateway when a stroke is committed ─────────────────────────────────
def on_stroke_committed(stroke):
    try:
        requests.post(
            f"{GATEWAY_URL}/committed",
            json={"stroke": stroke},
            timeout=0.3
        )
        print(f"[REPLICA] Notified gateway of committed stroke")
    except Exception as e:
        print(f"[REPLICA] Could not notify gateway: {e}")

# ── Register Shrivadhu's RPC routes ───────────────────────────────────────────
blueprint = create_rpc_blueprint(state, log, election_mgr, on_stroke_committed)
app.register_blueprint(blueprint)

# ── Also register Sharon's existing routes from r1.py ────────────────────────
# Sharon's routes: /request_vote, /append_entries, /status, /stroke, /get_strokes
from r1 import create_app as sharon_create_app
sharon_app = sharon_create_app(raft_node)

# Copy Sharon's routes into our app (avoid duplicate /stroke and /status)
SHARON_ROUTES_TO_SKIP = {"/stroke", "/status", "/append_entries"}
for rule in sharon_app.url_map.iter_rules():
    if rule.rule in SHARON_ROUTES_TO_SKIP:
        continue
    view_func = sharon_app.view_functions[rule.endpoint]
    app.add_url_rule(rule.rule, endpoint=f"sharon_{rule.endpoint}",
                     view_func=view_func, methods=rule.methods)

# ── Heartbeat sender — runs in background when leader ─────────────────────────
def heartbeat_loop():
    while True:
        if state.is_leader():
            send_heartbeats(state, log, PEERS)
        time.sleep(0.15)  # 150ms heartbeat interval

# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[REPLICA] {REPLICA_ID} (node {NODE_ID}) starting on port {PORT}")
    print(f"[REPLICA] Peers: {[p['id'] for p in PEERS]}")
    print(f"[REPLICA] Sharon's election engine: ACTIVE ✓")
    print(f"[REPLICA] Shrivadhu's log replication: ACTIVE ✓")

    # Start heartbeat thread
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    app.run(host="0.0.0.0", port=PORT, debug=False)