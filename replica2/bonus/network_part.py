# simulate network partition (split brain)
_partitioned = False

def is_partitioned():
    return _partitioned

def toggle_partition():
    global _partitioned
    _partitioned = not _partitioned
    return _partitioned