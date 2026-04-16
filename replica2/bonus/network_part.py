# simulate network partition (split brain)

import threading
import time
from typing import Callable, Optional
import requests

# lock because Flask and Raft threads access shared state at the same time
# core partition state
_partitioned: bool = False
_lock = threading.Lock()

# Callbacks reg by - RaftNode 
# when the partition toggled every entry -> zero-arg callable.
_on_partition_callbacks: list[Callable[[], None]] = []
_on_heal_callbacks:      list[Callable[[], None]] = []

# visible history
partition_history: list[dict] = []
# ---------------------------------------------
# api 
def is_partitioned() -> bool:
    """Return True if this node is currently in a network partition."""
    with _lock:
        return _partitioned

# from polling-based detection to an event-driven model 
# nodes will reg callbacks so they can react immediately to partition state

def toggle_partition() -> bool:
    """
    Flip the partition switch and send the callbacks.
    Return the new state [true = partioned].
    """
    global _partitioned
    with _lock:
        _partitioned = not _partitioned
        new_state = _partitioned
        partition_history.append({
            "state":     "partitioned" if new_state else "healed",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    # send callbacks outside the lock to avoid deadlock
    callbacks = _on_partition_callbacks if new_state else _on_heal_callbacks
    for cb in callbacks:
        try:
            cb()
        except Exception as exc:
            print(f"[PARTITION] Callback error: {exc}")

    print(f"[PARTITION] Node is now {'partioned' if new_state else 'healed'}")
    return new_state

# added api
# ----------------------------------------------

def register_on_partition(cb: Callable[[], None]) -> None:
    """Register callback sent when the node enteres the partition."""
    _on_partition_callbacks.append(cb)


def register_on_heal(cb: Callable[[], None]) -> None:
    """Register callback sent when the node has left the partition."""
    _on_heal_callbacks.append(cb)

# ------------------------------------------------
# helper block for rcp - outgoing 
# tell rcp about partitions

def safe_post(url: str, json_body: dict, timeout: float = 1.5) -> Optional[requests.Response]:
    """
    Replacement for requests.post() for all Raft outgoing RPCs.
    Returns None if the node is partitioned, so callers already
    treating a None / exception response as a missed peer will work correctly
    without any other changes.
    """
    if is_partitioned():
        # full network isolation, no tcp either
        return None
    try:
        return requests.post(url, json=json_body, timeout=timeout)
    except Exception:
        return None