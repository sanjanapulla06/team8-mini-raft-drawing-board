def is_partitioned():
    return partitioned

def toggle_partition():
    global partitioned
    partitioned = not partitioned
    print(f"[PARTITION] {partitioned}")
    return partitioned
