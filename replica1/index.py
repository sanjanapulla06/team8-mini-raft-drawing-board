# index.py — Main entry point for replica node

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

from r1 import RaftNode

# ── Config from environment variables ─────────────────────────────────────────
REPLICA_ID  = os.environ.get("REPLICA_ID", "replica1")
PORT        = int(os.environ.get("PORT", 5001))
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")

REPLICA1_URL = os.environ.get("REPLICA1_URL", "http://replica1:5001")
REPLICA2_URL = os.environ.get("REPLICA2_URL", "http://replica2:5002")
REPLICA3_URL = os.environ.get("REPLICA3_URL", "http://replica3:5003")

# ── Map REPLICA_ID to node id ────────────────────────────────────────────────
REPLICA_ID_MAP = {
    "replica1": 1,
    "replica2": 2,
    "replica3": 3,
}
NODE_ID = REPLICA_ID_MAP.get(REPLICA_ID, 1)

# ── Peers (NO replica4 anymore) ──────────────────────────────────────────────
ALL_REPLICAS = [
    {"id": "replica1", "url": REPLICA1_URL},
    {"id": "replica2", "url": REPLICA2_URL},
    {"id": "replica3", "url": REPLICA3_URL},
]

PEERS = [r for r in ALL_REPLICAS if r["id"] != REPLICA_ID]

# ── Adapter: Sharon's RaftNode → Shrivadhu interface ─────────────────────────
class SharonStateAdapter:
    def __init__(self, raft_node):
        self._node = raft_node

    @property
    def replica_id(self):
        return REPLICA_ID

    @property
    def role(self):
        return self._node.state

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


# ── Election adapter ─────────────────────────────────────────────────────────
class SharonElectionAdapter:
    def __init__(self, raft_node, peers):
        self._node = raft_node
        self.peers = peers

    def reset_election_timer(self):
        self._node.last_heartbeat = time.time()


# ── Flask app setup ───────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

raft_node    = RaftNode(NODE_ID)
state        = SharonStateAdapter(raft_node)
election_mgr = SharonElectionAdapter(raft_node, PEERS)

log = Log()

# ── Notify gateway when committed ─────────────────────────────────────────────
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

# ── Register RPC routes ───────────────────────────────────────────────────────
blueprint = create_rpc_blueprint(state, log, election_mgr, on_stroke_committed)
app.register_blueprint(blueprint)

# ── Merge Sharon's routes ─────────────────────────────────────────────────────
from r1 import create_app as sharon_create_app
sharon_app = sharon_create_app(raft_node)

SKIP = {"/stroke", "/status", "/append_entries", "/get_strokes"}

for rule in sharon_app.url_map.iter_rules():
    if rule.rule in SKIP:
        continue
    view_func = sharon_app.view_functions[rule.endpoint]
    app.add_url_rule(rule.rule, endpoint=f"sharon_{rule.endpoint}",
                     view_func=view_func, methods=rule.methods)

# ── Heartbeat loop ────────────────────────────────────────────────────────────
def heartbeat_loop():
    while True:
        if state.is_leader():
            send_heartbeats(state, log, PEERS)
        time.sleep(0.15)

# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[REPLICA] {REPLICA_ID} (node {NODE_ID}) starting on port {PORT}")
    print(f"[REPLICA] Peers: {[p['id'] for p in PEERS]}")
    print(f"[REPLICA] Sharon's election engine: ACTIVE ✓")
    print(f"[REPLICA] Shrivadhu's log replication: ACTIVE ✓")

    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    app.run(host="0.0.0.0", port=PORT, debug=False)
