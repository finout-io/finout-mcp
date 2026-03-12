"""Database module for conversation persistence"""
import asyncpg
import os
import json
from typing import Optional, List, Dict, Any
import secrets
from uuid import UUID, uuid4

# Database connection URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fobo:fobo@localhost:5432/billy")


class Database:
    """Database connection and operations"""

    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        """Create database connection pool"""
        self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        await self._create_tables()

    async def disconnect(self):
        """Close database connection pool"""
        if self.pool:
            await self.pool.close()

    async def _create_tables(self):
        """Create tables if they don't exist"""
        async with self.pool.acquire() as conn:
            # Create conversations table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(255) NOT NULL,
                    account_id VARCHAR(255) NOT NULL,
                    model VARCHAR(100) NOT NULL,
                    messages JSONB NOT NULL,
                    tool_calls JSONB,
                    user_note TEXT,
                    user_email VARCHAR(255),
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    share_token VARCHAR(64) UNIQUE NOT NULL
                );
                """
            )

            # Create indexes
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_created_at
                ON conversations(created_at DESC);
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_account_id
                ON conversations(account_id);
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conversations_share_token
                ON conversations(share_token);
                """
            )

            # Create feedback table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
                    account_id VARCHAR(255) NOT NULL,
                    session_id VARCHAR(255),
                    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                    query_type VARCHAR(50) NOT NULL,
                    tools_used TEXT[],
                    friction_points TEXT[],
                    suggestion TEXT,
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )

            # Create feedback indexes
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_created_at
                ON feedback(created_at DESC);
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_account_id
                ON feedback(account_id);
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_rating
                ON feedback(rating);
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_query_type
                ON feedback(query_type);
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_conversation_id
                ON feedback(conversation_id);
                """
            )

            # Add user_email column if missing (migration for older DBs)
            await conn.execute(
                """
                ALTER TABLE conversations
                ADD COLUMN IF NOT EXISTS user_email VARCHAR(255);
                """
            )

            # Add account_name column if missing (migration for older DBs)
            await conn.execute(
                """
                ALTER TABLE conversations
                ADD COLUMN IF NOT EXISTS account_name VARCHAR(255);
                """
            )

            # Backward-compatible migration for older DBs that may lack defaults
            # or contain legacy null timestamps.
            await conn.execute(
                """
                ALTER TABLE feedback
                ALTER COLUMN created_at SET DEFAULT clock_timestamp();
                """
            )
            await conn.execute(
                """
                UPDATE feedback AS f
                SET created_at = COALESCE(c.updated_at, c.created_at, NOW())
                FROM conversations AS c
                WHERE f.created_at IS NULL AND f.conversation_id = c.id;
                """
            )
            await conn.execute(
                """
                UPDATE feedback
                SET created_at = clock_timestamp()
                WHERE created_at IS NULL;
                """
            )

            # Create user_memories table for personalized greetings
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_memories (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_email VARCHAR(255) NOT NULL,
                    account_id VARCHAR(255) NOT NULL,
                    fact TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT clock_timestamp()
                );
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_memories_lookup
                ON user_memories(user_email, account_id);
                """
            )

    async def save_conversation(
        self,
        name: str,
        account_id: str,
        model: str,
        messages: List[Dict[str, Any]],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        conversation_id: Optional[str] = None,
        user_email: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a new conversation or update an existing one by ID."""
        async with self.pool.acquire() as conn:
            if conversation_id:
                row = await conn.fetchrow(
                    """
                    UPDATE conversations
                    SET name = $1, model = $2, messages = $3::jsonb,
                        tool_calls = $4::jsonb, user_email = $5,
                        updated_at = NOW()
                    WHERE id = $6
                    RETURNING id, name, account_id, account_name, model, created_at, share_token
                    """,
                    name,
                    model,
                    json.dumps(messages),
                    json.dumps(tool_calls) if tool_calls else None,
                    user_email,
                    conversation_id,
                )
                if row:
                    return dict(row)
                # ID not found — fall through to insert a fresh record

            share_token = secrets.token_urlsafe(32)
            row = await conn.fetchrow(
                """
                INSERT INTO conversations
                    (id, name, account_id, account_name, model, messages, tool_calls, user_email, share_token)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9)
                RETURNING id, name, account_id, account_name, model, created_at, share_token
                """,
                UUID(conversation_id) if conversation_id else uuid4(),
                name,
                account_id,
                account_name,
                model,
                json.dumps(messages),
                json.dumps(tool_calls) if tool_calls else None,
                user_email,
                share_token,
            )
            return dict(row)

    async def list_conversations(
        self, account_id: Optional[str] = None, search: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List conversations with optional filtering"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT id, name, account_id, model, user_email,
                       created_at, updated_at,
                       jsonb_array_length(messages) as message_count
                FROM conversations
                WHERE 1=1
            """
            params = []
            param_idx = 1

            if account_id:
                query += f" AND account_id = ${param_idx}"
                params.append(account_id)
                param_idx += 1

            if search:
                query += f" AND name ILIKE ${param_idx}"
                params.append(f"%{search}%")
                param_idx += 1

            query += f" ORDER BY created_at DESC LIMIT ${param_idx}"
            params.append(limit)

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a conversation by ID"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, account_id, account_name, model, messages, tool_calls, user_note,
                       created_at, updated_at, share_token
                FROM conversations
                WHERE id = $1
                """,
                conversation_id,
            )

            if not row:
                return None

            result = dict(row)
            # Parse JSONB fields if they're strings (shouldn't happen with proper JSONB, but handle it)
            if isinstance(result.get("messages"), str):
                result["messages"] = json.loads(result["messages"])
            if result.get("tool_calls") and isinstance(result["tool_calls"], str):
                result["tool_calls"] = json.loads(result["tool_calls"])
            return result

    async def get_conversation_by_token(self, share_token: str) -> Optional[Dict[str, Any]]:
        """Get a conversation by share token"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, account_id, account_name, model, messages, tool_calls, user_note,
                       created_at, updated_at, share_token
                FROM conversations
                WHERE share_token = $1
                """,
                share_token,
            )

            if not row:
                return None

            result = dict(row)
            # Parse JSONB fields if they're strings (shouldn't happen with proper JSONB, but handle it)
            if isinstance(result.get("messages"), str):
                result["messages"] = json.loads(result["messages"])
            if result.get("tool_calls") and isinstance(result["tool_calls"], str):
                result["tool_calls"] = json.loads(result["tool_calls"])
            return result

    async def update_note(self, conversation_id: str, note: str) -> bool:
        """Update user note for a conversation"""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE conversations
                SET user_note = $1, updated_at = NOW()
                WHERE id = $2
                """,
                note,
                conversation_id,
            )

            return result == "UPDATE 1"

    async def save_memory(
        self,
        user_email: str,
        account_id: str,
        fact: str,
    ) -> Dict[str, Any]:
        """Save a personal fact about a user."""
        import uuid

        async with self.pool.acquire() as conn:
            # Cap at 20 memories per user+account to keep prompts lean
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM user_memories WHERE user_email = $1 AND account_id = $2",
                user_email,
                account_id,
            )
            if count >= 20:
                # Delete the oldest memory to make room
                await conn.execute(
                    """
                    DELETE FROM user_memories WHERE id = (
                        SELECT id FROM user_memories
                        WHERE user_email = $1 AND account_id = $2
                        ORDER BY created_at ASC LIMIT 1
                    )
                    """,
                    user_email,
                    account_id,
                )

            row = await conn.fetchrow(
                """
                INSERT INTO user_memories (id, user_email, account_id, fact)
                VALUES ($1, $2, $3, $4)
                RETURNING id, user_email, account_id, fact, created_at
                """,
                uuid.uuid4(),
                user_email,
                account_id,
                fact,
            )
            return dict(row)

    async def get_memories(
        self,
        user_email: str,
        account_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Get memories for a user+account pair, newest first."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, fact, created_at
                FROM user_memories
                WHERE user_email = $1 AND account_id = $2
                ORDER BY created_at DESC
                LIMIT $3
                """,
                user_email,
                account_id,
                limit,
            )
            return [dict(row) for row in rows]

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a specific memory."""
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM user_memories WHERE id = $1",
                memory_id,
            )
            return result == "DELETE 1"

    async def save_feedback(
        self,
        account_id: str,
        rating: int,
        query_type: str,
        tools_used: Optional[List[str]] = None,
        friction_points: Optional[List[str]] = None,
        suggestion: Optional[str] = None,
        conversation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save feedback and return the record"""
        import uuid
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO feedback (
                    id, conversation_id, account_id, session_id, rating, query_type,
                    tools_used, friction_points, suggestion, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, clock_timestamp())
                RETURNING id, account_id, rating, query_type, created_at
                """,
                uuid.uuid4(),
                conversation_id,
                account_id,
                session_id,
                rating,
                query_type,
                tools_used or [],
                friction_points or [],
                suggestion,
            )

            return dict(row)

    async def list_feedback(
        self,
        account_id: Optional[str] = None,
        min_rating: Optional[int] = None,
        max_rating: Optional[int] = None,
        query_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List feedback with optional filtering"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT
                    f.id,
                    f.conversation_id,
                    f.account_id,
                    f.session_id,
                    f.rating,
                    f.query_type,
                    f.tools_used,
                    f.friction_points,
                    f.suggestion,
                    COALESCE(f.created_at, c.updated_at, c.created_at) AS created_at
                FROM feedback f
                LEFT JOIN conversations c ON c.id = f.conversation_id
                WHERE 1=1
            """
            params = []
            param_idx = 1

            if account_id:
                query += f" AND f.account_id = ${param_idx}"
                params.append(account_id)
                param_idx += 1

            if min_rating:
                query += f" AND f.rating >= ${param_idx}"
                params.append(min_rating)
                param_idx += 1

            if max_rating:
                query += f" AND f.rating <= ${param_idx}"
                params.append(max_rating)
                param_idx += 1

            if query_type:
                query += f" AND f.query_type = ${param_idx}"
                params.append(query_type)
                param_idx += 1

            query += (
                " ORDER BY COALESCE(f.created_at, c.updated_at, c.created_at) DESC NULLS LAST,"
                " f.ctid DESC"
                f" LIMIT ${param_idx}"
            )
            params.append(limit)

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_feedback_stats(
        self, account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregate feedback statistics"""
        async with self.pool.acquire() as conn:
            # Get basic stats
            if account_id:
                basic_stats = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_count,
                        COALESCE(AVG(rating)::numeric(3,2), 0) as avg_rating,
                        COUNT(*) FILTER (WHERE rating >= 4) as positive_count,
                        COUNT(*) FILTER (WHERE rating <= 2) as negative_count
                    FROM feedback
                    WHERE account_id = $1
                    """,
                    account_id,
                )
                # Get breakdown by query type
                type_breakdown = await conn.fetch(
                    """
                    SELECT query_type, COUNT(*) as count
                    FROM feedback
                    WHERE account_id = $1
                    GROUP BY query_type
                    ORDER BY count DESC
                    """,
                    account_id,
                )
            else:
                basic_stats = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total_count,
                        COALESCE(AVG(rating)::numeric(3,2), 0) as avg_rating,
                        COUNT(*) FILTER (WHERE rating >= 4) as positive_count,
                        COUNT(*) FILTER (WHERE rating <= 2) as negative_count
                    FROM feedback
                    """
                )
                # Get breakdown by query type
                type_breakdown = await conn.fetch(
                    """
                    SELECT query_type, COUNT(*) as count
                    FROM feedback
                    GROUP BY query_type
                    ORDER BY count DESC
                    """
                )

            result = dict(basic_stats) if basic_stats else {}
            result["by_query_type"] = {row["query_type"]: row["count"] for row in type_breakdown}
            return result


# Global database instance
db = Database()
