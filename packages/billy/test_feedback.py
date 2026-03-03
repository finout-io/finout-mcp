import asyncio
from vectiqor.db import Database

async def test():
    db = Database()
    await db.connect()
    
    # Test saving feedback
    feedback = await db.save_feedback(
        account_id="test-account",
        rating=5,
        query_type="cost_query",
        tools_used=["query_costs", "compare_costs"],
        friction_points=["slow response"],
        suggestion="Add caching",
        session_id="test-session"
    )
    print(f"Saved feedback: {feedback}")
    
    # Test listing feedback
    all_feedback = await db.list_feedback(account_id="test-account")
    print(f"Found {len(all_feedback)} feedback entries")
    
    # Test stats
    stats = await db.get_feedback_stats(account_id="test-account")
    print(f"Stats: {stats}")
    
    await db.disconnect()

asyncio.run(test())
