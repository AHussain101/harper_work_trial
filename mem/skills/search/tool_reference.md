# Tool Reference

## Available Tools

You have five tools:

1. **lookup_account(query)** - Semantic search for accounts by **company name**. Returns matching accounts with similarity scores. **Use when query mentions a specific company name.**

2. **search_descriptions(query)** - Semantic search across account **descriptions** (stage, location, industry, insurance type, current situation). **Use for:**
   - Implicit references: "that childcare center in Texas"
   - Stage-based queries: "accounts in application phase", "quotes pending"
   - Location queries: "accounts in California"
   - Industry queries: "security companies", "healthcare accounts"
   - Status queries: "accounts needing follow-up", "waiting for documents"

3. **list_files(path)** - List files and directories at a path

4. **read_file(path)** - Read the full contents of a file

5. **search_files(query, path)** - Search for text patterns in files under a path

## Choosing Between lookup_account and search_descriptions

| Query Type | Tool | Example |
|------------|------|---------|
| Specific company name | `lookup_account` | "What is Sunny Days Childcare's status?" |
| Implicit/partial reference | `search_descriptions` | "That childcare center in Texas" |
| Stage-based query | `search_descriptions` | "Which accounts need follow-up?" |
| Industry query | `search_descriptions` | "Show me the security companies" |
| Location query | `search_descriptions` | "Accounts in California" |
| Brokerage-level | `search_descriptions` | "What's the oldest pending application?" |

## When to Use search_files

Use `search_files` when you need to:
- Find specific text across multiple files
- Locate mentions of a person, topic, or keyword in communications
- Search within a specific account's sources directory

Example: To find all mentions of "renewal" in an account's communications:
```json
{
  "type": "tool_call",
  "tool": "search_files",
  "args": {"query": "renewal", "path": "mem/accounts/29119/sources"},
  "reason": "Find renewal discussions in account communications"
}
```
