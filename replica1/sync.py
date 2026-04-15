# sync.py — Week 3: Catch-up protocol for restarted replica nodes
# Week 3 — Shrivadhu
#
# Flow:
# 1. Replica restarts → empty log
# 2. Leader sends AppendEntries → prevLogIndex check fails
# 3. Follower responds with its log length
# 4. Leader calls POST /sync-log with all missing committed entries
# 5. Follower applies all entries → back in sync

import requests

def request_catch_up(leader_url, from_index, log, on_stroke):
    """
    Follower calls this when it suspects it is behind.
    Requests all committed entries from from_index onward from the leader.

    Args:
        leader_url  - e.g. "http://replica1:3001"
        from_index  - follower's current log length (first missing index)
        log         - the follower's Log object (will be mutated)
        on_stroke   - called for each caught-up stroke to notify gateway
    """
    print(f"[CATCH-UP] Requesting sync from {leader_url} starting at index {from_index}")

    try:
        res = requests.post(
            f"{leader_url}/sync-log",
            json={"fromIndex": from_index},
            timeout=2.0
        )

        if not res.ok:
            print(f"[CATCH-UP] Leader responded {res.status_code}")
            return

        data          = res.json()
        entries       = data.get("entries", [])
        leader_commit = data.get("leaderCommit", -1)

        if not entries:
            print("[CATCH-UP] Already up to date")
            return

        print(f"[CATCH-UP] Received {len(entries)} missing entries from leader")

        # Apply all missing entries
        for entry in entries:
            if entry["index"] >= log.length:
                log.entries.append(entry)

        if leader_commit >= 0:
            log.advance_commit(leader_commit)

        # Replay committed strokes so replica is in sync
        for entry in entries:
            if entry["index"] <= log.commit_index:
                on_stroke(entry["stroke"])

        print(f"[CATCH-UP] Done. Log length={log.length} commit_index={log.commit_index}")

    except Exception as e:
        print(f"[CATCH-UP] Failed to reach leader at {leader_url}: {e}")
