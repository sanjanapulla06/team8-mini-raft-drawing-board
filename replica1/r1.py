import argparse
import threading
import time
import random
import json
import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Docker-compatible peer URLs (use service names from docker-compose) ────────
ALL_PEERS = {
    1: os.environ.get("REPLICA1_URL", "http://replica1:5001"),
    2: os.environ.get("REPLICA2_URL", "http://replica2:5002"),
    3: os.environ.get("REPLICA3_URL", "http://replica3:5003"),
}

HEARTBEAT_INTERVAL   = 1.0
ELECTION_TIMEOUT_MIN = 5.0
ELECTION_TIMEOUT_MAX = 10.0
LOGS_DIR             = os.environ.get("LOGS_DIR", "/logs")


class RaftNode:
    def __init__(self, node_id):
        self.id               = node_id
        self.peers            = {k: v for k, v in ALL_PEERS.items() if k != node_id}
        self.current_term     = 0
        self.voted_for        = None
        self.state            = "follower"
        self.leader_id        = None
        self.stroke_log       = []
        self.election_history = []
        self.last_heartbeat   = time.time()
        self.election_timeout = self._new_timeout()
        self.lock             = threading.Lock()
        self.missed_heartbeats = 0

        os.makedirs(LOGS_DIR, exist_ok=True)

        self._load_state()
        self._load_strokes()
        self._load_election_history()
        threading.Thread(target=self._election_loop, daemon=True).start()

    def _save_state(self):
        path = f"{LOGS_DIR}/state_node{self.id}.json"
        with open(path, "w") as f:
            json.dump({"term": self.current_term, "voted_for": self.voted_for}, f)

    def _load_state(self):
        path = f"{LOGS_DIR}/state_node{self.id}.json"
        try:
            with open(path, "r") as f:
                data = json.load(f)
                self.current_term = data.get("term", 0)
                self.voted_for    = data.get("voted_for", None)
                self._log(f"Loaded saved state – term={self.current_term}, voted_for={self.voted_for}")
        except FileNotFoundError:
            pass

    def _save_strokes(self):
        path = f"{LOGS_DIR}/strokes_node{self.id}.json"
        with open(path, "w") as f:
            json.dump(self.stroke_log, f)

    def _load_strokes(self):
        path = f"{LOGS_DIR}/strokes_node{self.id}.json"
        try:
            with open(path, "r") as f:
                self.stroke_log = json.load(f)
                self._log(f"Loaded {len(self.stroke_log)} strokes from disk")
        except FileNotFoundError:
            pass

    def _save_election_history(self, record):
        path = f"{LOGS_DIR}/election_history.json"
        try:
            with open(path, "r") as f:
                all_history = json.load(f)
        except FileNotFoundError:
            all_history = []
        all_history.append(record)
        with open(path, "w") as f:
            json.dump(all_history, f, indent=2)

    def _load_election_history(self):
        path = f"{LOGS_DIR}/election_history.json"
        try:
            with open(path, "r") as f:
                self.election_history = json.load(f)
                self._log(f"Loaded {len(self.election_history)} past elections from logs")
        except FileNotFoundError:
            pass

    def _new_timeout(self):
        return random.uniform(ELECTION_TIMEOUT_MIN, ELECTION_TIMEOUT_MAX)

    def _log(self, msg):
        print(f"[Node {self.id} | {self.state.upper():9s} | term {self.current_term}]  {msg}", flush=True)

    def _election_loop(self):
        while True:
            time.sleep(0.5)
            with self.lock:
                if self.state == "leader":
                    continue
                if time.time() - self.last_heartbeat >= self.election_timeout:
                    self._start_election()

    def _start_election(self):
        self.state        = "candidate"
        self.current_term += 1
        self.voted_for    = self.id
        self.last_heartbeat   = time.time()
        self.election_timeout = self._new_timeout()
        self._save_state()

        term     = self.current_term
        votes    = 1
        majority = (len(self.peers) + 1) // 2 + 1

        self._log(f"Starting election for term {term}")

        for peer_url in self.peers.values():
            try:
                resp = requests.post(f"{peer_url}/request_vote",
                    json={"term": term, "candidate_id": self.id}, timeout=1.5)
                data = resp.json()
                if data.get("term", 0) > self.current_term:
                    self._step_down(data["term"]); return
                if data.get("vote_granted"):
                    votes += 1
                    self._log(f"Got vote from {peer_url}  ({votes}/{majority} needed)")
            except Exception:
                pass

        if self.state == "candidate" and votes >= majority:
            self._become_leader(votes, majority)
        else:
            self._log(f"Lost election ({votes} votes, needed {majority}) – backing off")
            self.state = "follower"
            backoff = random.uniform(1.0, 4.0)
            self._log(f"Backing off for {backoff:.1f}s before next election")
            self.last_heartbeat   = time.time()
            self.election_timeout = self._new_timeout() + backoff

    def _become_leader(self, votes, majority):
        self.state     = "leader"
        self.leader_id = self.id
        self._log("*** BECAME LEADER ***")
        self.missed_heartbeats = 0

        record = {
            "term":      self.current_term,
            "winner":    self.id,
            "votes":     votes,
            "majority":  majority,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        self.election_history.append(record)
        self._save_election_history(record)
        self._log(f"Election recorded – term={self.current_term} votes={votes}/{majority}")

        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _heartbeat_loop(self):
        while True:
            with self.lock:
                if self.state != "leader":
                    return
                term, lid = self.current_term, self.id

            responses = 0
            for peer_url in self.peers.values():
                try:
                    r = requests.post(f"{peer_url}/append_entries",
                        json={"term": term, "leader_id": lid}, timeout=1.0)
                    if r.json().get("success"):
                        responses += 1
                except Exception:
                    pass

            with self.lock:
                if self.state != "leader":
                    return
                if responses == 0:
                    self.missed_heartbeats += 1
                    self._log(f"No followers responded ({self.missed_heartbeats}/3)")
                    if self.missed_heartbeats >= 3:
                        self._log("No followers for 3 rounds – stepping down!")
                        self.state        = "follower"
                        self.leader_id    = None
                        self.last_heartbeat   = time.time()
                        self.election_timeout = self._new_timeout()
                        return
                else:
                    self.missed_heartbeats = 0
                    self._log(f"Heartbeat OK – {responses} follower(s) responded ✓")

            time.sleep(HEARTBEAT_INTERVAL)

    def _step_down(self, new_term):
        self._log(f"Stepping down – saw higher term {new_term}")
        self.state, self.current_term = "follower", new_term
        self.voted_for    = None
        self.last_heartbeat   = time.time()
        self.election_timeout = self._new_timeout()
        self._save_state()

    def handle_request_vote(self, term, candidate_id):
        with self.lock:
            if term < self.current_term:
                return {"term": self.current_term, "vote_granted": False}
            if term > self.current_term:
                self._step_down(term)
            if self.voted_for is None or self.voted_for == candidate_id:
                self.voted_for      = candidate_id
                self.last_heartbeat = time.time()
                self._log(f"Voted YES for node {candidate_id} in term {term}")
                self._save_state()
                return {"term": self.current_term, "vote_granted": True}
            self._log(f"Voted NO for node {candidate_id} (already voted for {self.voted_for})")
            return {"term": self.current_term, "vote_granted": False}

    def handle_append_entries(self, term, leader_id, stroke=None):
        with self.lock:
            if term < self.current_term:
                return {"term": self.current_term, "success": False}
            if term > self.current_term:
                self._step_down(term)
            self.state, self.leader_id = "follower", leader_id
            self.last_heartbeat = time.time()

            if stroke:
                self.stroke_log.append(stroke)
                self._save_strokes()
                self._log(f"Stroke committed and replicated ✓  total={len(self.stroke_log)}")
            else:
                self._log(f"Heartbeat from Leader Node {leader_id} ✓")

            return {"term": self.current_term, "success": True, "stroke": stroke}

    def status(self):
        with self.lock:
            return {"id": self.id, "state": self.state,
                    "term": self.current_term, "leader": self.leader_id}


def create_app(node):
    app = Flask(__name__)
    CORS(app)

    @app.route("/request_vote", methods=["POST"])
    def request_vote():
        d = request.json
        return jsonify(node.handle_request_vote(d["term"], d["candidate_id"]))

    @app.route("/append_entries", methods=["POST"])
    def append_entries():
        d = request.json
        return jsonify(node.handle_append_entries(d["term"], d["leader_id"], d.get("stroke")))

    @app.route("/get_strokes", methods=["GET"])
    def get_strokes():
        with node.lock:
            return jsonify({"strokes": node.stroke_log})

    @app.route("/election_history", methods=["GET"])
    def election_history():
        with node.lock:
            return jsonify({"elections": node.election_history})

    @app.route("/shutdown", methods=["POST"])
    def shutdown():
        import signal
        node._log("Shutting down via visualiser...")
        threading.Thread(
            target=lambda: (time.sleep(0.5), os.kill(os.getpid(), signal.SIGTERM))
        ).start()
        return jsonify({"success": True, "message": f"Node {node.id} shutting down"})

    @app.route("/visualiser")
    def visualiser():
        html_path = os.path.join(os.path.dirname(__file__), "visualiser.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return "<h1>visualiser.html not found</h1>", 404

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id",   type=int, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    node = RaftNode(args.id)
    app  = create_app(node)

    print(f"\n{'='*50}")
    print(f"  RAFT Node {args.id} starting on port {args.port}")
    print(f"{'='*50}\n")

    app.run(host="0.0.0.0", port=args.port, threaded=True)