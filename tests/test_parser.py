from app.parser import parse_watch


def test_parser_full():
    w = parse_watch("RTX 4090 | max=1200 | min=400 | condition=used | interval=180")
    assert w.query == "RTX 4090"
    assert w.max_price == 1200
    assert w.min_price == 400
    assert w.condition == "USED"
    assert w.interval_seconds == 180
