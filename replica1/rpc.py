# rpc.py — All 4 RAFT RPC endpoints as a Flask Blueprint
# Week 2 — Shrivadhu

from flask import Blueprint, request, jsonify

def create_rpc_blueprint(state, log, election_mgr, on_stroke_committed):
    """
    Returns a Flask Blueprint with all RAFT RPC routes.
    Register this in the main Flask app.
    """
    rpc = Blueprint("rpc", __name__)

    # ── POST /request-vote ────────────────────────────────────────────────────
    @rpc.route("/request-vote", methods=["POST"])
    def request_vote():
        data           = request.get_json()
        term           = data["term"]
        candidate_id   = data["candidateId"]
        last_log_index = data["lastLogIndex"]
        last_log_term  = data["lastLogTerm"]

        print(f"[RPC] /request-vote from {candidate_id} term={term}")

        # Step down if we see higher term
        if term > state.current_term:
            state.become_follower(term)
            election_mgr.reset_election_timer()

        vote_granted = False

        if term < state.current_term:
            # Stale term — reject
            vote_granted = False

        elif state.voted_for is None or state.voted_for == candidate_id:
            # Grant vote only if candidate log is at least as up to date
            candidate_log_ok = (
                last_log_term > log.last_term or
                (last_log_term == log.last_term and last_log_index >= log.last_index)
            )
            if candidate_log_ok:
                vote_granted       = True
                state.voted_for    = candidate_id
                election_mgr.reset_election_timer()
                print(f"[RPC] Vote GRANTED to {candidate_id}")
            else:
                print(f"[RPC] Vote DENIED to {candidate_id} — log not up to date")
        else:
            print(f"[RPC] Vote DENIED to {candidate_id} — already voted for {state.voted_for}")

        return jsonify({"term": state.current_term, "voteGranted": vote_granted})


    # ── POST /append-entries ──────────────────────────────────────────────────
    @rpc.route("/append-entries", methods=["POST"])
    def append_entries():
        data           = request.get_json()
        term           = data["term"]
        leader_id      = data["leaderId"]
        prev_log_index = data["prevLogIndex"]
        prev_log_term  = data["prevLogTerm"]
        entries        = data.get("entries", [])
        leader_commit  = data["leaderCommit"]

        # Reject stale leaders
        if term < state.current_term:
            return jsonify({"term": state.current_term, "success": False, "logLength": log.length})

        if term > state.current_term or state.is_candidate():
            state.become_follower(term)

        state.leader_id = leader_id
        election_mgr.reset_election_timer()

        # Try to append entries — fails if prevLog check fails
        ok = log.append_entries(prev_log_index, prev_log_term, entries)

        if not ok:
            print(f"[RPC] /append-entries: log mismatch — returning logLength={log.length}")
            return jsonify({"term": state.current_term, "success": False, "logLength": log.length})

        # Advance commit and notify gateway of newly committed strokes
        if leader_commit > log.commit_index:
            old_commit = log.commit_index
            log.advance_commit(leader_commit)
            for entry in log.entries[old_commit + 1: log.commit_index + 1]:
                on_stroke_committed(entry["stroke"])

        return jsonify({"term": state.current_term, "success": True, "logLength": log.length})


    # ── POST /heartbeat ───────────────────────────────────────────────────────
    @rpc.route("/heartbeat", methods=["POST"])
    def heartbeat():
        data          = request.get_json()
        term          = data["term"]
        leader_id     = data["leaderId"]
        leader_commit = data.get("leaderCommit", -1)

        if term < state.current_term:
            return jsonify({"term": state.current_term, "success": False})

        if term > state.current_term or state.is_candidate():
            state.become_follower(term)

        state.leader_id = leader_id
        election_mgr.reset_election_timer()

        if leader_commit > log.commit_index:
            log.advance_commit(leader_commit)

        return jsonify({"term": state.current_term, "success": True})


    # ── POST /sync-log ────────────────────────────────────────────────────────
    # Week 3: catch-up endpoint — leader pushes missing entries to restarted follower
    @rpc.route("/sync-log", methods=["POST"])
    def sync_log():
        data          = request.get_json()
        entries       = data.get("entries", [])
        leader_commit = data.get("leaderCommit", -1)

        print(f"[RPC] /sync-log received {len(entries)} entries")

        for entry in entries:
            if entry["index"] >= log.length:
                log.entries.append(entry)
                print(f"[SYNC] Applied index={entry['index']} term={entry['term']}")

        if leader_commit >= 0:
            log.advance_commit(leader_commit)

        # Notify gateway of all re-applied strokes
        for entry in entries:
            if entry["index"] <= log.commit_index:
                on_stroke_committed(entry["stroke"])

        print(f"[SYNC] Done. Log length={log.length} commit_index={log.commit_index}")
        return jsonify({"success": True})


    # ── GET /status ───────────────────────────────────────────────────────────
    @rpc.route("/status", methods=["GET"])
    def status():
        return jsonify({
            "replicaId":   state.replica_id,
            "role":        state.role,
            "term":        state.current_term,
            "leaderId":    state.leader_id,
            "logLength":   log.length,
            "commitIndex": log.commit_index,
        })


    # ── POST /stroke ──────────────────────────────────────────────────────────
    # Gateway sends new strokes here — only leader handles it
    @rpc.route("/stroke", methods=["POST"])
    def stroke():
        if not state.is_leader():
            return jsonify({"error": "not leader", "leaderId": state.leader_id}), 302

        from replication import replicate_entry
        stroke_data = request.get_json().get("stroke")
        entry       = log.append(state.current_term, stroke_data)
        replicate_entry(state, log, election_mgr.peers, entry, on_stroke_committed)
        return jsonify({"success": True, "index": entry["index"]})

    return rpc
