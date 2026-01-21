# History Chain Format

## Entry Structure

Each entry in `history.md` follows this format:

```markdown
## {ISO_TIMESTAMP}

{Summary of what changed}

- **{field}**: {old_value} → {new_value}
- **Evidence**: {what triggered this change}
- **Previous**: [{previous_timestamp}](#{anchor_id})

---
```

## Example Entry

```markdown
## 2026-01-21T14:30:00Z

Stage updated from "Application Received" to "Quoted" based on premium quote of $2,600.

- **stage**: Application Received → Quoted
- **Note**: Premium quoted at $2,600 annual
- **Evidence**: User command: "Mark as Quoted, $2,600 premium"
- **Previous**: [2026-01-15T10:00:00Z](#2026-01-15t100000z)

---
```

## Chain Integrity

- Each entry MUST link to the previous entry
- Anchor IDs are lowercase timestamps with special chars removed
- First entry has no Previous link
- Never break the chain by editing in the middle

## Querying History

The history chain supports:
- "What changed?" → Read history.md
- "When did X happen?" → Search for field name in history.md
- "Timeline of account" → Walk the chain from newest to oldest

## Evidence Types

- `User command: "{query}"` - Direct user request
- `Email: {path}` - Change triggered by email content
- `Call: {path}` - Change triggered by call transcript
- `System: {action}` - Automated system action
