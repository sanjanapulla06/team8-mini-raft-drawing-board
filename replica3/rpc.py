# rpc.py — All 4 RAFT RPC endpoints as a Flask Blueprint
# Week 2 — Shrivadhu

from flask import Blueprint, request, jsonify
# -------------------------------------------------------
# adding imports for bonus - shreya
from bonus.network_part import is_partitioned, toggle_partition
from bonus.vector import ( materialize_visible_strokes, resolve_undo_target, resolve_redo_target)
import uuid
# --------------------------------------------------------
def create_rpc_blueprint(state, log, election_mgr, on_stroke_committed):
    rpc = Blueprint("rpc", __name__)
# ---------------------------------------------------------
# edits - shreya
# block RPC calls when node is partitioned ; to simulates network failure by rejecting incoming requests
     def _partition_block():
        if is_partitioned():
            return jsonify({"success": False, "error": "partitioned"}), 503
        return None
# ---------------------------------------------------------
    # ── POST /request_vote ────────────────────────────────────────────────────
    @rpc.route("/request_vote", methods=["POST"])
    def request_vote():
# ----------------------------------------------------------------
#  simulated newtork failure, block if noe partitioned - shreya
        blocked = _partition_block()
        if blocked:
            return blocked
# ---------------------------------------------------------
        data           = request.get_json()
        term           = data["term"]
        candidate_id   = data.get("candidateId") or data.get("candidate_id")
        last_log_index = data.get("lastLogIndex", -1)
        last_log_term  = data.get("lastLogTerm", -1)

        print(f"[RPC] /request_vote from {candidate_id} term={term}")

        if term > state.current_term:
            state.become_follower(term)
            election_mgr.reset_election_timer()

        vote_granted = False

        if term < state.current_term:
            vote_granted = False

        elif state.voted_for is None or state.voted_for == candidate_id:
            candidate_log_ok = (
                last_log_term > log.last_term or
                (last_log_term == log.last_term and last_log_index >= log.last_index)
            )
            if candidate_log_ok:
                vote_granted    = True
                state.voted_for = candidate_id
                election_mgr.reset_election_timer()
                print(f"[RPC] Vote GRANTED to {candidate_id}")
            else:
                print(f"[RPC] Vote DENIED to {candidate_id} — log not up to date")
        else:
            print(f"[RPC] Vote DENIED to {candidate_id} — already voted for {state.voted_for}")

        return jsonify({"term": state.current_term, "voteGranted": vote_granted, "vote_granted": vote_granted})


    # ── POST /append_entries ──────────────────────────────────────────────────
    @rpc.route("/append_entries", methods=["POST"])
    def append_entries():
# ------------------------------------------------------------------
#  simulated newtork failure, block if noe partitioned - shreya
        blocked = _partition_block()
        if blocked:
            return blocked
# ---------------------------------------------------------
        data = request.get_json()
        term      = data["term"]
        leader_id = data.get("leaderId") or data.get("leader_id")

        # Support both Sharon's simple format and Shrivadhu's full format
        prev_log_index = data.get("prevLogIndex", -1)
        prev_log_term  = data.get("prevLogTerm", -1)
        entries        = data.get("entries", [])
        leader_commit  = data.get("leaderCommit", data.get("leader_commit", -1))
        stroke         = data.get("stroke")  # Sharon's simple stroke format

        if term < state.current_term:
            return jsonify({"term": state.current_term, "success": False, "logLength": log.length})

        if term > state.current_term or state.is_candidate():
            state.become_follower(term)

        state.leader_id = leader_id
        election_mgr.reset_election_timer()

        # Handle Sharon's simple stroke format
        if stroke:
            entry = log.append(state.current_term, stroke)
            on_stroke_committed(stroke)
            print(f"[RPC] Stroke appended via Sharon format ✓")
            return jsonify({"term": state.current_term, "success": True, "logLength": log.length, "stroke": stroke})

        # Handle Shrivadhu's full AppendEntries format
        if entries:
            ok = log.append_entries(prev_log_index, prev_log_term, entries)
            if not ok:
                return jsonify({"term": state.current_term, "success": False, "logLength": log.length})

            if leader_commit > log.commit_index:
                old_commit = log.commit_index
                log.advance_commit(leader_commit)
                for e in log.entries[old_commit + 1: log.commit_index + 1]:
                    on_stroke_committed(e["stroke"])

        else:
            # Heartbeat only
            print(f"[RPC] Heartbeat from Leader {leader_id} ✓")
            if leader_commit > log.commit_index:
                log.advance_commit(leader_commit)

        return jsonify({"term": state.current_term, "success": True, "logLength": log.length})


    # ── POST /heartbeat ───────────────────────────────────────────────────────
    @rpc.route("/heartbeat", methods=["POST"])
    def heartbeat():
# ------------------------------------------------------------------
#  simulated newtork failure, block if noe partitioned - shreya
        blocked = _partition_block()
        if blocked:
            return blocked
# ---------------------------------------------------------
        data          = request.get_json()
        term          = data["term"]
        leader_id     = data.get("leaderId") or data.get("leader_id")
        leader_commit = data.get("leaderCommit", data.get("leader_commit", -1))

        if term < state.current_term:
            return jsonify({"term": state.current_term, "success": False})

        if term > state.current_term or state.is_candidate():
            state.become_follower(term)

        state.leader_id = leader_id
        election_mgr.reset_election_timer()

        if leader_commit > log.commit_index:
            log.advance_commit(leader_commit)

        return jsonify({"term": state.current_term, "success": True})


    # ── POST /sync_log ────────────────────────────────────────────────────────
    @rpc.route("/sync_log", methods=["POST"])
    @rpc.route("/sync-log", methods=["POST"])
    def sync_log():
# ------------------------------------------------------------------
#  simulated newtork failure, block if noe partitioned - shreya
        blocked = _partition_block()
        if blocked:
            return blocked
# --------------------------------------------------------------
        data          = request.get_json()
        entries       = data.get("entries", [])
        leader_commit = data.get("leaderCommit", -1)

        print(f"[RPC] /sync_log received {len(entries)} entries")

        for entry in entries:
            if entry["index"] >= log.length:
                log.entries.append(entry)
                print(f"[SYNC] Applied index={entry['index']} term={entry['term']}")

        if leader_commit >= 0:
            log.advance_commit(leader_commit)

        for entry in entries:
            if entry["index"] <= log.commit_index:
                on_stroke_committed(entry["stroke"])

        print(f"[SYNC] Done. Log length={log.length} commit_index={log.commit_index}")
        return jsonify({"success": True})


    # ── GET /status ───────────────────────────────────────────────────────────
    @rpc.route("/status", methods=["GET"])
    def status():
# -----------------------------------------------------------------
#  edited status endpoint 
# change status endpoint to show partition state ; partitioned, node - unavailable
        if is_partitioned():
            return jsonify({
                "replicaId": state.replica_id,
                "role": "partitioned",
                "state": "partitioned",
                "term": state.current_term,
                "leaderId": None,
                "logLength": log.length,
                "commitIndex": log.commit_index,
            })
# ----------------------------------------------------------------------
        return jsonify({
            "replicaId":   state.replica_id,
            "role":        state.role,
            "state":       state.role,   # ← added for gateway compatibility
            "term":        state.current_term,
            "leaderId":    state.leader_id,
            "logLength":   log.length,
            "commitIndex": log.commit_index,
        })


    # ── POST /stroke ──────────────────────────────────────────────────────────
    @rpc.route("/stroke", methods=["POST"])
    def stroke():
# ------------------------------------------------------------------
#  simulated newtork failure, block if noe partitioned - shreya
        blocked = _partition_block()
        if blocked:
            return blocked
# --------------------------------------------------------------
        if not state.is_leader():
            return jsonify({"error": "not leader", "leaderId": state.leader_id}), 302

        from replication import replicate_entry
# --------------------------------------------------------------
#  editing stroke handling - shreya
# add partition awareness ; only leader cam write ; undo/redo ; unique ids
# convert undo intent to deterministic log operation ; redo resolved using log history
        
        stroke_data = request.get_json().get("stroke") or {}
        op_type = stroke_data.get("type")
        committed = [e["stroke"] for e in log.committed_entries()]
               if op_type == "undo":
            target_id = resolve_undo_target(committed, stroke_data.get("clientId"))
            if not target_id:
                return jsonify({"success": True, "noop": True, "action": "undo"})
            stroke_data = {
                "type": "undo_comp",
                "clientId": stroke_data.get("clientId"),
                "targetId": target_id,
            }
        elif op_type == "redo":
            target_id = resolve_redo_target(committed, stroke_data.get("clientId"))
            if not target_id:
                return jsonify({"success": True, "noop": True, "action": "redo"})
            stroke_data = {
                "type": "redo_comp",
                "clientId": stroke_data.get("clientId"),
                "targetId": target_id,
            }

        if stroke_data.get("type") in {"draw", "shape", "erase"} and not stroke_data.get("id"):
            stroke_data["id"] = f"{stroke_data.get('clientId', 'anon')}-{uuid.uuid4().hex[:12]}"

# --------------------------------------------------------------
        entry       = log.append(state.current_term, stroke_data)
        replicate_entry(state, log, election_mgr.peers, entry, on_stroke_committed)
        # return jsonify({"success": True, "index": entry["index"]})
# --------------------------------------------------------------
        return jsonify({"success": True, "index": entry["index"], "op": stroke_data.get("type")})
# --------------------------------------------------------------

    # ── GET /get_strokes ──────────────────────────────────────────────────────
    @rpc.route("/get_strokes", methods=["GET"])
    def get_strokes():
# --------------------------------------------------------------
# modifying stroke retrieval - shreya
# we find the visible state by applying undo/redo operations
        committed = [e["stroke"] for e in log.committed_entries()]
        visible = materialize_visible_strokes(committed)
        return jsonify({"strokes": visible})
# adding endpoint to toggle network partition ; testing fault tolerance, recovery
    @rpc.route("/toggle_partition", methods=["POST"])
    def toggle_partition_api():
        state_now = toggle_partition()
        return jsonify({"partitioned": state_now})
# --------------------------------------------------------------

    return rpc
