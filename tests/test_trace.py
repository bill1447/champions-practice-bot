import json

from champions_practice.trace import DecisionTrace


def test_decision_trace_appends_jsonl(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    trace = DecisionTrace(path)

    trace.append({"event": "preview", "chosen": [1, 2, 3, 4]})
    trace.append({"event": "turn", "turn": 1, "chosen": "/choose move protect"})

    lines = path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]

    assert records == [
        {"chosen": [1, 2, 3, 4], "event": "preview"},
        {"chosen": "/choose move protect", "event": "turn", "turn": 1},
    ]
