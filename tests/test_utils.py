from datetime import datetime

from app.utils import price_text, valid_nick, utcnow


def test_price_text():
    assert price_text(18) == "18 алм. (2,0 аб.)"
    assert price_text(10) == "10 алм. (1,1 аб.)"


def test_valid_nick():
    assert valid_nick("Steve_01")
    assert not valid_nick("a")
    assert not valid_nick("Стив")
    assert not valid_nick("bad nick")
    assert not valid_nick("x" * 33)


def test_utcnow_is_naive():
    now = utcnow()
    assert isinstance(now, datetime) and now.tzinfo is None
