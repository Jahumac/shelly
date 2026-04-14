from app.services.csv_parsers import count_csv_rows, diagnose_parsed_holdings


def test_diagnose_clean_result():
    holdings = [{"ticker": "VUSA", "name": "Vanguard S&P", "units": 10, "value": 900}]
    assert diagnose_parsed_holdings(holdings, raw_row_count=1) == []


def test_diagnose_flags_zero_unit_rows():
    holdings = [
        {"ticker": "VUSA", "name": "Vanguard S&P", "units": 10, "value": 900},
        {"ticker": "BROKEN", "name": "Broken", "units": 0, "value": 0},
    ]
    warnings = diagnose_parsed_holdings(holdings, raw_row_count=2)
    assert any("zero units" in w for w in warnings)
    assert any("Broken" in w for w in warnings)


def test_diagnose_flags_large_discrepancy():
    # 100 rows in file, only 2 parsed → suspicious
    holdings = [{"ticker": "A", "name": "A", "units": 1, "value": 10}] * 2
    warnings = diagnose_parsed_holdings(holdings, raw_row_count=100)
    assert any("100 rows" in w for w in warnings)


def test_diagnose_flags_everything_skipped():
    warnings = diagnose_parsed_holdings([], raw_row_count=50)
    assert any("none were recognised" in w for w in warnings)


def test_diagnose_no_false_alarm_on_small_files():
    # 5-row file, 1 holding parsed — that's fine (not "most skipped")
    holdings = [{"ticker": "A", "name": "A", "units": 1, "value": 10}]
    assert diagnose_parsed_holdings(holdings, raw_row_count=5) == []


def test_count_csv_rows_basic():
    csv_bytes = b"header1,header2\na,1\nb,2\nc,3\n"
    assert count_csv_rows(csv_bytes) == 3


def test_count_csv_rows_empty():
    assert count_csv_rows(b"") == 0


def test_count_csv_rows_with_bom():
    csv_bytes = "\ufeffheader1,header2\na,1\n".encode("utf-8")
    assert count_csv_rows(csv_bytes) == 1
