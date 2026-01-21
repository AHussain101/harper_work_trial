# Reading Source Files

Each source (email, call, SMS) is stored in its own folder with two files:
- `summary.md` - LLM-generated summary with key points and action items
- `raw.txt` - Full original content

## Strategy: Summary First

**Always read summary.md FIRST when exploring sources.** This is more efficient and often sufficient:

1. **Read `summary.md` first** - Get key points, action items, and relevant details quickly
2. **Only read `raw.txt` if needed** - When you need:
   - Exact quotes or wording
   - Full context the summary may have omitted
   - Verification of specific details
3. **Cite the file you read** - Use summary.md path if summary was sufficient, raw.txt if you needed full content

## Source Directory Structure

```
sources/
  emails/
    email_<id>/
      summary.md    # Read this first
      raw.txt       # Full email content (if needed)
  calls/
    call_<id>/
      summary.md    # Call summary with key points
      raw.txt       # Full call transcript (if needed)
  sms/
    sms_<id>/
      summary.md    # SMS summary
      raw.txt       # Full SMS content (if needed)
```

## Efficiency Tips

- If listing sources/ shows many items, consider using `search_files` to narrow down
- Recent communications are often more relevant - source IDs are roughly chronological
- For "summarize all communications" queries, reading summaries is usually sufficient
