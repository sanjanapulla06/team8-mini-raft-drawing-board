strokes = []

def add_stroke(stroke):
    strokes.append(stroke)


def handle_undo(client_id):
    global strokes
    # remove own last stroke only
    for i in range(len(strokes) - 1, -1, -1):
        if strokes[i].get("clientId") == client_id:
            strokes.pop(i)
            return


def handle_erase(stroke):
    global strokes
    x = stroke.get("x")
    y = stroke.get("y")
    client_id = stroke.get("clientId")

    new_strokes = []
    for s in strokes:

        if not (
            s.get("clientId") == client_id and
            abs(s.get("x", 0) - x) < 5 and
            abs(s.get("y", 0) - y) < 5
        ):
            new_strokes.append(s)

    strokes = new_strokes


def get_strokes():
    return strokes
