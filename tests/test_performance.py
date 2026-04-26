def test_monthly_performance_carries_forward_missing_account_snapshots(app, make_user):
    """A partial month should not make untouched accounts look like £0.

    This matches the real-world flow where a user updates one new/manual account
    in the current month before completing a full monthly review.
    """
    uid, _, _ = make_user()

    with app.app_context():
        from app.calculations import compute_performance_series
        from app.models import fetch_monthly_performance_data, get_connection

        with get_connection() as conn:
            isa = conn.execute(
                "INSERT INTO accounts (user_id, name, current_value, is_active) VALUES (?, 'ISA', 58811, 1)",
                (uid,),
            ).lastrowid
            cash = conn.execute(
                "INSERT INTO accounts (user_id, name, current_value, is_active) VALUES (?, 'Cash ISA', 3200, 1)",
                (uid,),
            ).lastrowid
            conn.execute(
                "INSERT INTO monthly_snapshots (snapshot_date, account_id, month_key, balance) VALUES ('2026-03-01', ?, '2026-03', 58811)",
                (isa,),
            )
            conn.execute(
                "INSERT INTO monthly_snapshots (snapshot_date, account_id, month_key, balance) VALUES ('2026-03-01', ?, '2026-03', 3200)",
                (cash,),
            )
            conn.execute(
                "INSERT INTO monthly_snapshots (snapshot_date, account_id, month_key, balance) VALUES ('2026-04-01', ?, '2026-04', 3200)",
                (cash,),
            )
            conn.commit()

        monthly_data = fetch_monthly_performance_data(uid)
        assert monthly_data == [
            ("2026-03", 62011.0, 0.0, 0),
            ("2026-04", 62011.0, 0.0, 1),
        ]

        perf = compute_performance_series(monthly_data, 0.07, 0)
        assert perf["total_return"] == 0.0
        assert perf["total_market_gain"] == 0.0
        assert perf["carried_forward_months"] == 1
