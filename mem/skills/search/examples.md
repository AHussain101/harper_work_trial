# Example Exploration Flows

## Single Account Status Query

**Query**: "What is the status of Sunny Days Childcare?"

1. `lookup_account("Sunny Days Childcare")` → Returns matching accounts
2. `read_file("mem/accounts/29119/state.md")` → Get account details
3. Return final answer with citation to state.md

## Cross-Account Query

**Query**: "Which accounts need follow-up?" (cross-account query)

1. `search_descriptions("accounts needing follow-up")` → Returns accounts matching this description
2. Read `state.md` for top matches to confirm details
3. Return list of accounts with their status

## Communication Summary Query

**Query**: "Summarize the last call with Maple Stoneworks"

1. `lookup_account("Maple Stoneworks")` → Get account path
2. `list_files("mem/accounts/29042/sources/calls")` → Find available calls
3. `read_file("mem/accounts/29042/sources/calls/call_150246/summary.md")` → Read most recent call summary
4. Return summary with citation

## Finding Specific Information

**Query**: "What did we discuss about workers comp with ABC Corp?"

1. `lookup_account("ABC Corp")` → Get account path
2. `search_files("workers comp", "mem/accounts/29050/sources")` → Find relevant mentions
3. `read_file(...)` → Read the files containing matches
4. Return findings with citations

## History/Change Query

**Query**: "How has the Sunny Days account changed over time?"

1. `lookup_account("Sunny Days")` → Get account path
2. `read_file("mem/accounts/29119/history.md")` → Read change history
3. Return timeline of changes with citation

## Implicit Reference Query

**Query**: "What's happening with that security company in Texas?"

1. `search_descriptions("security company Texas")` → Find matching accounts
2. `read_file("mem/accounts/.../state.md")` → Get details for best match
3. Return answer or ask for clarification if multiple matches
