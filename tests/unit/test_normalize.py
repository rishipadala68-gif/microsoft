from app.core.normalize import normalize_text


def test_normalize_ips_and_numbers():
    s1 = "Connection refused to 10.0.3.7:5432 after 30001ms"
    s2 = "Connection refused to 10.0.9.2:5432 after 29877ms"
    assert normalize_text(s1) == normalize_text(s2)
    assert normalize_text(s1) == "Connection refused to <ip>:<n> after <n>ms"


def test_normalize_preserve_http_status():
    text1 = "Service returned HTTP 503 error code 500"
    text2 = "Request took 503 ms to complete"
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)

    assert "503" in norm1
    assert "500" in norm1
    assert "503" not in norm2
    assert "took <n> ms" in norm2


def test_normalize_uuids_and_hex():
    text = "Transaction 123e4567-e89b-12d3-a456-426614174000 failed with commit 0xdeadbeef12345"
    norm = normalize_text(text)
    assert "<uuid>" in norm
    assert "<hex>" in norm
    assert "123e4567" not in norm


def test_normalize_timestamps():
    text = "2026-09-28T12:00:00.123Z [ERROR] Failed operation at Sep 28 12:00:00"
    norm = normalize_text(text)
    assert norm == "<ts> [ERROR] Failed operation at <ts>"
