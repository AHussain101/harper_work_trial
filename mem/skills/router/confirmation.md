# Confirmation Flow

## When to Request Confirmation

Request user confirmation when:
1. Account not found in Qdrant for an update request
2. Multiple accounts match with similar scores (ambiguous reference)
3. Destructive operations (future: delete, merge accounts)

## Confirmation Request Format

```json
{
  "type": "confirmation_required",
  "message": "I don't have an account for 'ABC Company'. Would you like me to create a new account?",
  "session_id": "uuid-here",
  "account_name": "ABC Company",
  "alternatives": [
    {"name": "ABC Corp", "score": 0.72, "account_id": "29050"},
    {"name": "ABC Services", "score": 0.65, "account_id": "29051"}
  ]
}
```

## Handling Confirmation Response

When user confirms:
1. Create new account folder structure
2. Initialize state.md with minimal info
3. Initialize history.md with creation entry
4. Index in Qdrant (both name and description collections)
5. Continue with original request

When user denies:
1. Return cancellation acknowledgment
2. Optionally suggest alternatives

## New Account Initialization

When creating a new account:

```
mem/accounts/{new_id}/
  state.md          # Minimal state: name, stage=New Lead
  history.md        # Initial entry: account created
  sources/
    emails/         # Empty
    calls/          # Empty
    sms/            # Empty
```

State.md template:
```markdown
# {Account Name} (Account {ID})

## Status
- **Stage**: New Lead
- **Insurance Types**: None

## Contacts
- **Primary Email**: 
- **Primary Phone**: 

## Next Steps
- Initial outreach needed

## Pending Actions
- None identified

## Last Contact
- **Date**: {creation_date}
- **Type**: Account created
```
