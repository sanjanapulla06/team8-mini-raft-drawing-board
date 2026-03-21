import argparse
import threading
import time
import random
import json
import requests
from flask import Flask, request, jsonify

ALL_PEERS = {
    1: "http://localhost:5001",
    2: "http://localhost:5002",
    3: "http://localhost:5003",
}

HEARTBEAT_INTERVAL   = 1.0
ELECTION_TIMEOUT_MIN = 5.0
ELECTION_TIMEOUT_MAX = 10.0


class RaftNode:
    def __init__(self, node_id):
        self.id           = node_id
        self.peers        = {k: v for k, v in ALL_PEERS.items() if k != node_id}
        self.current_term = 0
        self.voted_for    = None
        self.state        = "follower"
        self.leader_id    = None
        self.stroke_log   = []
        self.last_heartbeat   = time.time()
        self.election_timeout = self._new_timeout()
        self.lock = threading.Lock()
        self._load_state()
        self._load_strokes()    # ← load strokes on startup
        threading.Thread(target=self._election_loop, daemon=True).start()

    def _save_state(self):
        with open(f"state_node{self.id}.json", "w") as f:
            json.dump({"term": self.current_term, "voted_for": self.voted_for}, f)

    def _load_state(self):
        try:
            with open(f"state_node{self.id}.json", "r") as f:
                data = json.load(f)
                self.current_term = data.get("term", 0)
                self.voted_for    = data.get("voted_for", None)
                self._log(f"Loaded saved state – term={self.current_term}, voted_for={self.voted_for}")
        except FileNotFoundError:
            pass

    def _save_strokes(self):
        with open(f"strokes_node{self.id}.json", "w") as f:
            json.dump(self.stroke_log, f)

    def _load_strokes(self):
        try:
            with open(f"strokes_node{self.id}.json", "r") as f:
                self.stroke_log = json.load(f)
                self._log(f"Loaded {len(self.stroke_log)} strokes from disk")
        except FileNotFoundError:
            pass  # first time, no strokes yet

    def _new_timeout(self):
        base = ELECTION_TIMEOUT_MIN + (self.id * 1.5)
        return base + random.uniform(0, 3.0)

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
            self._become_leader()
        else:
            self._log(f"Lost election ({votes} votes, needed {majority})")
            self.state = "follower"

    def _become_leader(self):
        self.state     = "leader"
        self.leader_id = self.id
        self._log("*** BECAME LEADER ***")
        self.missed_heartbeats = 0
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
                self._save_strokes()    # ← save strokes to disk
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

    @app.route("/request_vote", methods=["POST"])
    def request_vote():
        d = request.json
        return jsonify(node.handle_request_vote(d["term"], d["candidate_id"]))

    @app.route("/append_entries", methods=["POST"])
    def append_entries():
        d = request.json
        return jsonify(node.handle_append_entries(d["term"], d["leader_id"], d.get("stroke")))

    @app.route("/stroke", methods=["POST"])
    def stroke():
        d = request.json
        with node.lock:
            if node.state != "leader":
                return jsonify({"success": False, "error": "not leader"})
            stroke_data = d.get("stroke")
            term        = node.current_term
            leader_id   = node.id

        # replicate to all followers
        committed = 0
        for peer_url in node.peers.values():
            try:
                r = requests.post(f"{peer_url}/append_entries",
                    json={"term": term, "leader_id": leader_id, "stroke": stroke_data},
                    timeout=1.0)
                if r.json().get("success"):
                    committed += 1
            except Exception:
                pass

        # store on leader too
        with node.lock:
            node.stroke_log.append(stroke_data)
            node._save_strokes()    # ← save strokes to disk
            node._log(f"Stroke accepted and replicated to {committed} nodes ✓")

        return jsonify({"success": True, "stroke": stroke_data, "replicated_to": committed})

    @app.route("/get_strokes", methods=["GET"])
    def get_strokes():
        with node.lock:
            return jsonify({"strokes": node.stroke_log})

    @app.route("/status", methods=["GET"])
    def status():
        return jsonify(node.status())

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

    app.run(port=args.port, threaded=True)
