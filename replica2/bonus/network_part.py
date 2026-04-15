# simulate network partition (split brain)

import threading
import time

_partitioned: bool = False
_lock = threading.Lock()

# visible history
partition_history: list[dict] = []

def is_partitioned():
    return _partitioned

def toggle_partition() -> bool:
    global _partitioned
    with _lock:
        _partitioned = not _partitioned
        partition_history.append({
            "state":     "partitioned" if _partitioned else "healed",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
    print(f"[PARTITION] {'ON' if _partitioned else 'OFF'}")
    return _partitioned
