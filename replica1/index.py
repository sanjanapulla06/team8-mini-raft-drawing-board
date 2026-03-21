# index.py — Main entry point for replica node
# Wires together: log, replication, rpc, sync
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

# ── Config from environment variables ─────────────────────────────────────────
REPLICA_ID  = os.environ.get("REPLICA_ID", "replica1")
PORT        = int(os.environ.get("PORT", 3001))
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8080")

REPLICA1_URL = os.environ.get("REPLICA1_URL", "http://localhost:3001")
REPLICA2_URL = os.environ.get("REPLICA2_URL", "http://localhost:3002")
REPLICA3_URL = os.environ.get("REPLICA3_URL", "http://localhost:3003")

# ── Peers (everyone except self) ──────────────────────────────────────────────
ALL_REPLICAS = [
    {"id": "replica1", "url": REPLICA1_URL},
    {"id": "replica2", "url": REPLICA2_URL},
    {"id": "replica3", "url": REPLICA3_URL},
]
PEERS = [r for r in ALL_REPLICAS if r["id"] != REPLICA_ID]

# ── Minimal state object (Sharon will replace this with her full state) ────────
class SimpleState:
    def __init__(self, replica_id):
        self.replica_id   = replica_id
        self.role         = "follower"   # follower / candidate / leader
        self.current_term = 0
        self.voted_for    = None
        self.leader_id    = None
        self.votes_received = 0

    def is_leader(self):    return self.role == "leader"
    def is_follower(self):  return self.role == "follower"
    def is_candidate(self): return self.role == "candidate"

    def become_follower(self, term):
        print(f"[STATE] {self.replica_id} → FOLLOWER (term {self.current_term} → {term})")
        self.current_term  = term
        self.role          = "follower"
        self.voted_for     = None
        self.votes_received = 0

    def become_leader(self):
        print(f"[STATE] {self.replica_id} → LEADER (term {self.current_term}) 🏆")
        self.role      = "leader"
        self.leader_id = self.replica_id

# ── Minimal election manager stub ─────────────────────────────────────────────
# Sharon replaces this with her full ElectionManager
class SimpleElectionManager:
    def __init__(self, peers):
        self.peers = peers

    def reset_election_timer(self):
        pass  # Sharon's code handles this

# ── Flask app setup ───────────────────────────────────────────────────────────
app  = Flask(__name__)
CORS(app)

state       = SimpleState(REPLICA_ID)
log         = Log()
election_mgr = SimpleElectionManager(PEERS)

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

# ── Register all RPC routes (your Week 2 work) ────────────────────────────────
blueprint = create_rpc_blueprint(state, log, election_mgr, on_stroke_committed)
app.register_blueprint(blueprint)

# ── Heartbeat sender — runs in background when leader ─────────────────────────
def heartbeat_loop():
    while True:
        if state.is_leader():
            send_heartbeats(state, log, PEERS)
        time.sleep(0.15)  # 150ms heartbeat interval

# ── Start ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[REPLICA] {REPLICA_ID} starting on port {PORT}")
    print(f"[REPLICA] Peers: {[p['id'] for p in PEERS]}")

    # Start heartbeat thread
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    app.run(host="0.0.0.0", port=PORT, debug=False)
