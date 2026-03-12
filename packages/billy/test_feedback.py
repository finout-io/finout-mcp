from billy.db import Database

async def test_feedback_roundtrip():
    db = Database()
    await db.connect()
    try:
        feedback = await db.save_feedback(
            account_id="test-account",
            rating=5,
            query_type="cost_query",
            tools_used=["query_costs", "compare_costs"],
            friction_points=["slow response"],
            suggestion="Add caching",
            session_id="test-session",
        )

        assert feedback["account_id"] == "test-account"
        assert feedback["rating"] == 5
        assert feedback["query_type"] == "cost_query"

        all_feedback = await db.list_feedback(account_id="test-account")
        assert any(item["id"] == feedback["id"] for item in all_feedback)

        stats = await db.get_feedback_stats(account_id="test-account")
        assert stats["total_count"] >= 1
        assert stats["avg_rating"] >= 0
    finally:
        await db.disconnect()
