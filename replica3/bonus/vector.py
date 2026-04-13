def _stroke_id(stroke):
    return stroke.get("id")

def _is_draw_like(op):
    return op.get("type") in {"draw", "shape", "erase"}

def _is_undo_comp(op):
    return op.get("type") == "undo_comp"

def _is_redo_comp(op):
    return op.get("type") == "redo_comp"

def materialize_visible_strokes(committed_strokes):
    ordered_ids = []
    by_id = {}
    hidden = set()

    for op in committed_strokes:
        if not isinstance(op, dict):
            continue

        if _is_draw_like(op):
            sid = _stroke_id(op)
            if not sid:
                continue
            if sid not in by_id:
                ordered_ids.append(sid)
            by_id[sid] = op
            hidden.discard(sid)

        elif _is_undo_comp(op):
            target = op.get("targetId")
            if target in by_id:
                hidden.add(target)

        elif _is_redo_comp(op):
            target = op.get("targetId")
            if target in by_id:
                hidden.discard(target)

    return [by_id[sid] for sid in ordered_ids if sid in by_id and sid not in hidden]

def resolve_undo_target(committed_strokes, client_id):
    if not client_id:
        return None
    visible = materialize_visible_strokes(committed_strokes)
    for s in reversed(visible):
        if s.get("clientId") == client_id:
            sid = s.get("id")
            if sid:
                return sid
    return None

def resolve_redo_target(committed_strokes, client_id):
    if not client_id:
        return None

    visible_ids = {s.get("id") for s in materialize_visible_strokes(committed_strokes) if s.get("id")}
    owner = {}
    hidden = set()

    for op in committed_strokes:
        if not isinstance(op, dict):
            continue
        t = op.get("type")
        if t in {"draw", "shape", "erase"} and op.get("id"):
            owner[op["id"]] = op.get("clientId")
        elif t == "undo_comp" and op.get("targetId"):
            hidden.add(op["targetId"])
        elif t == "redo_comp" and op.get("targetId"):
            hidden.discard(op["targetId"])

    for op in reversed(committed_strokes):
        if not isinstance(op, dict) or op.get("type") != "undo_comp":
            continue
        tid = op.get("targetId")
        if not tid:
            continue
        if tid in visible_ids:
            continue
        if tid in hidden and owner.get(tid) == client_id:
            return tid
    return None
