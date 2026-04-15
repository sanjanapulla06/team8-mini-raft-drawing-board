# replication.py — AppendEntries fan-out and majority acknowledgement
# Week 2 — Shrivadhu

import requests
import threading

def replicate_entry(state, log, peers, entry, on_commit):
    """
    Leader fans out AppendEntries to all followers in parallel.
    Commits when majority (including self) acknowledges.
    Triggers sync-log catch-up if a follower is behind.
    """
    if not state.is_leader():
        print("[REPLICATION] Not leader — ignoring")
        return

    prev_log_index = entry["index"] - 1
    prev_entry     = log.get_entry(prev_log_index)
    prev_log_term  = prev_entry["term"] if prev_entry else -1

    body = {
        "term":            state.current_term,
        "leaderId":        state.replica_id,
        "prevLogIndex":    prev_log_index,
        "prevLogTerm":     prev_log_term,
        "entries":         [entry],
        "leaderCommit":    log.commit_index,
    }

    # Leader already has the entry — start ACK count at 1
    acks      = [1]
    majority  = (len(peers) + 1) // 2 + 1
    committed = [False]
    lock      = threading.Lock()

    print(f"[REPLICATION] Sending AppendEntries index={entry['index']} to {len(peers)} peers (need {majority} ACKs)")

    def send_to_peer(peer):
        try:
            res  = requests.post(f"{peer['url']}/append_entries", json=body, timeout=0.3)
            data = res.json()

            # Peer has higher term — step down
            if data.get("term", 0) > state.current_term:
                print(f"[REPLICATION] {peer['id']} has higher term — stepping down")
                state.become_follower(data["term"])
                return

            if data.get("success"):
                with lock:
                    acks[0] += 1
                    print(f"[REPLICATION] ACK from {peer['id']} (acks={acks[0]})")
                    if not committed[0] and acks[0] >= majority:
                        committed[0] = True
                        log.advance_commit(entry["index"])
                        print(f"[REPLICATION] ✅ Majority reached — committing index={entry['index']}")
                        on_commit(entry)
            else:
                # Follower log is behind — trigger catch-up
                from_index = data.get("logLength", 0)
                print(f"[REPLICATION] {peer['id']} rejected — triggering catch-up from index {from_index}")
                send_sync_log(peer, from_index, log, state)

        except Exception as e:
            print(f"[REPLICATION] Could not reach {peer['id']}: {e}")

    # Fan out in parallel
    threads = [threading.Thread(target=send_to_peer, args=(peer,)) for peer in peers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if not committed[0]:
        print(f"[REPLICATION] ⚠️ index={entry['index']} not committed — only {acks[0]}/{majority} ACKs")


def send_sync_log(peer, from_index, log, state):
    """
    Leader pushes all committed entries from from_index onward to a lagging follower.
    This is the leader-side of the catch-up protocol.
    """
    missing = log.get_from(from_index)
    if not missing:
        print(f"[SYNC_LOG] {peer['id']} already up to date")
        return

    print(f"[SYNC_LOG] Sending {len(missing)} entries to {peer['id']} from index {from_index}")
    try:
        requests.post(
            f"{peer['url']}/sync_log",
            json={"entries": missing, "leaderCommit": log.commit_index},
            timeout=1.0
        )
    except Exception as e:
        print(f"[SYNC_LOG] Could not reach {peer['id']}: {e}")


def send_heartbeats(state, log, peers):
    """
    Leader sends heartbeat to all followers every 150ms.
    Resets follower election timers — no log entries carried.
    """
    if not state.is_leader():
        return

    body = {
        "term":         state.current_term,
        "leaderId":     state.replica_id,
        "leaderCommit": log.commit_index,
    }

    def beat(peer):
        try:
            res  = requests.post(f"{peer['url']}/heartbeat", json=body, timeout=0.2)
            data = res.json()
            if data.get("term", 0) > state.current_term:
                print(f"[HEARTBEAT] {peer['id']} has higher term — stepping down")
                state.become_follower(data["term"])
        except:
            pass  # Peer unreachable — election will handle it

    threads = [threading.Thread(target=beat, args=(peer,)) for peer in peers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
