# Multi-Account Support for VECTIQOR

## Overview

VECTIQOR now supports querying multiple Finout accounts! Users can switch between accounts using a dropdown selector in the header.

## How It Works

### Account Discovery
1. **Fetch Accounts:** `GET /account-service/account`
   - Headers: `authorized-user-roles: sysAdmin`
   - **No** `authorized-account-id` header (this is key!)
   - Returns list of all accessible accounts

2. **Account List:**
   - Shows account `name` in dropdown
   - Uses `accountId` (not `id` or `_id`) for identification

### Account Switching
1. **User selects account** from dropdown
2. **Backend restarts MCP server** with new account ID
3. **Environment variable** `FINOUT_ACCOUNT_ID` is updated
4. **Conversation history cleared** (new account, fresh start)
5. **User can immediately query** new account

## UI Components

### Account Selector (Header)
```
🤖 VECTIQOR                                      Account: [Production ▼]
   Ask the Smart AI of Finout
```

**Features:**
- Located in header (top-right)
- Shows all accessible accounts
- Current account pre-selected
- Smooth switching with loading state

### Switching Flow
```
1. User clicks dropdown
2. Selects "Development"
3. Sees: "Switching to Development..."
4. MCP server restarts (1-2 seconds)
5. Chat cleared with welcome message
6. Ready to query Development account
```

## API Endpoints

### `GET /api/accounts`
Fetches available accounts for current user.

**Response:**
```json
{
  "accounts": [
    {
      "name": "Production",
      "accountId": "e12498cc-594a-4740-94a5-8324e7399bb2"
    },
    {
      "name": "Development",
      "accountId": "a1b2c3d4-1234-5678-90ab-cdef12345678"
    }
  ],
  "current_account_id": "e12498cc-594a-4740-94a5-8324e7399bb2"
}
```

### `POST /api/switch-account`
Switches to a different account.

**Request:**
```json
{
  "account_id": "a1b2c3d4-1234-5678-90ab-cdef12345678"
}
```

**Response:**
```json
{
  "success": true,
  "account_id": "a1b2c3d4-1234-5678-90ab-cdef12345678",
  "message": "Switched to account a1b2c3d4-1234-5678-90ab-cdef12345678"
}
```

## Implementation Details

### Backend (vectiqor_server.py)

**MCPBridge Changes:**
```python
class MCPBridge:
    def __init__(self):
        self.current_account_id = None

    async def start(self, account_id=None):
        # Set FINOUT_ACCOUNT_ID in environment
        env = os.environ.copy()
        if account_id:
            env["FINOUT_ACCOUNT_ID"] = account_id

        # Start MCP server with custom environment
        self.process = subprocess.Popen(..., env=env)

    async def restart_with_account(self, account_id):
        # Stop current server
        await self.stop()
        # Start with new account
        await self.start(account_id)
```

**Why Restart?**
- MCP server reads `FINOUT_ACCOUNT_ID` from environment on startup
- Cannot change dynamically without restart
- Restart is fast (~1-2 seconds)
- Ensures clean state for new account

### Frontend (index.html)

**Account Loading:**
```javascript
async function loadAccounts() {
    const response = await fetch('/api/accounts');
    const data = await response.json();

    // Populate dropdown
    data.accounts.forEach(account => {
        const option = document.createElement('option');
        option.value = account.accountId;
        option.textContent = account.name;
        selector.appendChild(option);
    });
}
```

**Account Switching:**
```javascript
async function switchAccount() {
    // Show loading state
    selector.innerHTML = '<option>Switching...</option>';

    // Call API
    await fetch('/api/switch-account', {
        method: 'POST',
        body: JSON.stringify({ account_id: newAccountId })
    });

    // Clear conversation and refresh UI
    conversationHistory = [];
    showWelcomeMessage();
}
```

## User Experience

### Before (Single Account)
```
User: "What were my costs last month?"
VECTIQOR: [Shows Production account costs]
```

### After (Multi-Account)
```
User: [Selects "Development" from dropdown]
VECTIQOR: "Account switched! Now querying Development."

User: "What were my costs last month?"
VECTIQOR: [Shows Development account costs]

User: [Switches back to "Production"]
VECTIQOR: "Account switched! Now querying Production."
```

## Benefits

✅ **Multi-Tenant** - One VECTIQOR instance for all accounts
✅ **No Confusion** - Clear which account you're querying
✅ **Fast Switching** - 1-2 second switch time
✅ **Clean Context** - Each account starts fresh
✅ **Same MCP Code** - No MCP changes needed

## Security Notes

### Account Access Control
- Uses same auth token for all accounts
- User must have `sysAdmin` role
- API filters accounts based on user permissions
- Only shows accounts user can access

### Environment Isolation
- Each account query uses its own MCP server instance
- No data leakage between accounts
- Conversation history cleared on switch

## Testing

### 1. Check Account List
```bash
# Start VECTIQOR
./start.sh

# Open browser: http://localhost:8000
# Look at dropdown in header
# Should show all your accessible accounts
```

### 2. Test Switching
```
1. Select "Development" from dropdown
2. Wait for "Account switched!" message
3. Ask: "What were my costs last month?"
4. Verify it shows Development costs
5. Switch to "Production"
6. Ask same question
7. Verify it shows Production costs
```

### 3. Verify Isolation
```
1. Select Account A
2. Ask: "What were my AWS costs?"
3. Note the response
4. Switch to Account B
5. Ask same question
6. Response should be different (Account B data)
```

## Troubleshooting

### "No accounts found"
- Check `FINOUT_CLIENT_ID` and `FINOUT_SECRET_KEY` in `.env`
- Verify user has `sysAdmin` role
- Check browser console for errors

### "Error switching account"
- Check MCP server logs
- Verify account ID is valid
- Ensure `FINOUT_API_URL` is correct

### Account dropdown shows "Loading..."
- Check `/api/accounts` endpoint
- Verify internal API is accessible
- Check network tab in browser dev tools

## Future Enhancements

Potential improvements:
- [ ] Remember last selected account per user
- [ ] Show account info (region, plan, etc.)
- [ ] Favorite accounts
- [ ] Search/filter accounts (if many)
- [ ] Account-specific settings

## Architecture Diagram

```
User selects account
        ↓
Frontend calls /api/switch-account
        ↓
Backend restarts MCP server
        ↓
Sets FINOUT_ACCOUNT_ID in environment
        ↓
MCP server uses new account ID in headers
        ↓
All queries go to new account
        ↓
User sees new account's data
```

---

**Multi-account support is ready!** 🎉

Now your whole team can use VECTIQOR to query any account they have access to, all from one interface.
