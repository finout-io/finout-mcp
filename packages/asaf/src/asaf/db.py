"""Database module for conversation persistence"""
import asyncpg
import os
from typing import Optional, List, Dict, Any
from datetime import datetime
import secrets

# Database connection URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://fobo:fobo@localhost:5432/asaf")


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

    async def save_conversation(
        self,
        name: str,
        account_id: str,
        model: str,
        messages: List[Dict[str, Any]],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Save a conversation and return the record"""
        share_token = secrets.token_urlsafe(32)

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversations (name, account_id, model, messages, tool_calls, share_token)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, name, account_id, model, created_at, share_token
                """,
                name,
                account_id,
                model,
                messages,  # asyncpg handles JSONB conversion automatically
                tool_calls,  # asyncpg handles JSONB conversion automatically
                share_token,
            )

            return dict(row)

    async def list_conversations(
        self, account_id: Optional[str] = None, search: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List conversations with optional filtering"""
        async with self.pool.acquire() as conn:
            query = """
                SELECT id, name, account_id, model, created_at, updated_at,
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
                SELECT id, name, account_id, model, messages, tool_calls, user_note,
                       created_at, updated_at, share_token
                FROM conversations
                WHERE id = $1
                """,
                conversation_id,
            )

            return dict(row) if row else None

    async def get_conversation_by_token(self, share_token: str) -> Optional[Dict[str, Any]]:
        """Get a conversation by share token"""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, account_id, model, messages, tool_calls, user_note,
                       created_at, updated_at, share_token
                FROM conversations
                WHERE share_token = $1
                """,
                share_token,
            )

            return dict(row) if row else None

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


# Global database instance
db = Database()
