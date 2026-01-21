#!/usr/bin/env python3
"""
Ingestion Pipeline for Experiment 1: Pure Exploration Workflow Agent

Reads accounts.jsonl and transforms it into the filesystem memory structure
required by the exploration agent.

Usage:
    python ingest.py [--input accounts.jsonl] [--output mem]
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import anthropic
from dotenv import load_dotenv

from name_registry import NameRegistry

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# System rules content (static config for the agent)
SYSTEM_RULES_CONTENT = '''# System Rules for Exploration Agent

You are an exploration agent that answers user questions by navigating a filesystem memory. You have access to file tools to explore the `mem/` directory structure.

## Directory Structure

```
mem/
  accounts/
    <account_id>/
      state.md            # Account summary in markdown (name, stage, contacts, etc.)
      history.md          # Change history with timestamps and evidence links (if changes occurred)
      sources/
        emails/
          email_<id>/
            summary.md    # LLM-generated summary of this email
            raw.txt       # Full email content
        calls/
          call_<id>/
            summary.md    # Call summary with key points
            raw.txt       # Full call transcript
        sms/
          sms_<id>/
            summary.md    # SMS summary
            raw.txt       # Full SMS content
```

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

## Exploration Strategy

1. **Identify query type**: Does the query mention a specific company name, or is it asking about accounts by attributes (stage, location, industry)?

2. **For specific company names**: Use `lookup_account` first. It returns the best matching accounts with their paths and similarity scores (0.9+ = strong match, 0.7-0.9 = related).

3. **For implicit references or attribute-based queries**: Use `search_descriptions` first. It searches account summaries that include stage, location, industry, and current situation.

4. **Read state.md**: Go directly to the matched account's `state.md` for key metadata (name, stage, contacts).

5. **Check history.md**: If you need to understand how an account changed over time, read `history.md` for a chronological log of changes with evidence links.

6. **Drill down as needed**: Explore `sources/` directories for detailed evidence (emails, calls, SMS).

7. **Search when appropriate**: Use `search_files` for content-based search within specific directories.

8. **Navigate freely**: You can go back up the directory tree if you hit a dead end. Each tool call is independent.

## Reading Source Files (IMPORTANT)

Each source (email, call, SMS) is stored in its own folder with two files:
- `summary.md` - LLM-generated summary with key points and action items
- `raw.txt` - Full original content

**Always read summary.md FIRST when exploring sources.** This is more efficient and often sufficient:

1. **Read `summary.md` first** - Get key points, action items, and relevant details quickly
2. **Only read `raw.txt` if needed** - When you need:
   - Exact quotes or wording
   - Full context the summary may have omitted
   - Verification of specific details
3. **Cite the file you read** - Use summary.md path if summary was sufficient, raw.txt if you needed full content

## Answer Formatting Guidelines

### For comprehensive account summaries:
When asked for a complete picture or summary of an account, always include:
- Current **stage** and **status** in the pipeline
- What's **pending** or outstanding (documents, decisions, approvals)
- **Next steps** for Harper to take
- Recent communication context

Example structure:
"[Account Name] is currently in the [stage] stage. Their status shows [details]. Pending items include [list]. Next steps: [actions needed]."

### For cross-account/list queries:
When asked about multiple accounts, format your answer as a list:
- Use numbered or bulleted list format
- Include account names in brackets: [Account Name]
- Show key status info for each

Example:
"Accounts in application phase needing follow-up:
1. [Sunny Days Childcare] - Application Received, waiting for loss runs
2. [Maple Stoneworks] - Application Received, pending COI
3. [Blue Sky Services] - Intake stage, needs initial contact"

## Response Format

You MUST respond with exactly one JSON object per turn.

### For tool calls:
```json
{
  "type": "tool_call",
  "tool": "list_files",
  "args": {"path": "mem/accounts"},
  "reason": "Find available account folders"
}
```

### For final answers:
```json
{
  "type": "final",
  "answer": "Your answer here...",
  "citations": ["mem/accounts/29119/state.md", "mem/accounts/29119/sources/emails/email_123/summary.md"],
  "notes": "Optional notes about confidence or caveats",
  "trace_summary": ["Listed accounts", "Read state.md for account 29119", "Found matching account"]
}
```

## Critical Rules

### Grounding & Citations
- **Only cite files you have opened** with `read_file`. Citations MUST be file paths.
- **Never invent information**. If you cannot find evidence, say so.
- **Do not guess**. If uncertain, state your uncertainty clearly.

### Safety
- **No file writes** - you are read-only
- **No path traversal** - all paths must stay within `mem/`
- **No external knowledge** - only answer from what you retrieve via tools

### Handling Ambiguity
- If a query matches multiple accounts (e.g., "Sunny" matches "Sunny Days Childcare" and "Sunny Days Childcare Center"), list the candidates and ask for clarification.
- If you cannot find relevant information after reasonable exploration, say so clearly.

### Budget Awareness
- You have limited tool calls. Be efficient.
- Prioritize `state.md` files for quick account identification.
- Use `search_files` to narrow down before reading many individual files.

## Example Exploration Flow

**Query**: "What is the status of Sunny Days Childcare?"

1. `lookup_account("Sunny Days Childcare")` → Returns matching accounts
2. `read_file("mem/accounts/29119/state.md")` → Get account details
3. Return final answer with citation to state.md

**Query**: "Which accounts need follow-up?" (cross-account query)

1. `search_descriptions("accounts needing follow-up")` → Returns accounts matching this description
2. Read `state.md` for top matches to confirm details
3. Return list of accounts with their status
'''


def create_system_rules(path: Path) -> None:
    """Create the system_rules.md file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(SYSTEM_RULES_CONTENT)
    logger.info(f"Created {path}")


def parse_accounts_jsonl(file_path: str) -> Iterator[dict]:
    """
    Generator that yields parsed account objects from a JSONL file.
    
    Args:
        file_path: Path to the accounts.jsonl file
        
    Yields:
        dict: Parsed account data for each line
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                account = json.loads(line)
                yield account
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping malformed JSON at line {line_num}: {e}")
                continue


def create_account_directory(account_id: str, base_path: str = "mem/accounts") -> Path:
    """
    Creates the directory structure for an account.
    
    Args:
        account_id: The account identifier
        base_path: Base path for accounts directory
        
    Returns:
        Path: The account directory path
    """
    account_dir = Path(base_path) / str(account_id)
    sources_dir = account_dir / "sources"
    
    # Create all required subdirectories
    for subdir in ["emails", "calls", "sms"]:
        (sources_dir / subdir).mkdir(parents=True, exist_ok=True)
    
    return account_dir


def generate_account_description(account_data: dict) -> str:
    """
    Generate a rich searchable description from account data using LLM.
    
    This description is used for semantic search to find accounts by attributes
    like stage, location, industry, insurance type, and current situation.
    
    Args:
        account_data: The full account data dictionary
        
    Returns:
        Searchable description string
    """
    structured = account_data.get("structured_data", {})
    
    # Extract key fields for context
    name = account_data.get("account_name", "Unknown")
    stage = structured.get("general_stage") or structured.get("company_stage_manual", "Unknown")
    
    # Location
    address = structured.get("address", {})
    city = address.get("city", "")
    state = address.get("state", "")
    location_parts = [p for p in [city, state] if p]
    location = ", ".join(location_parts) if location_parts else "Unknown"
    
    # Industry
    industry = structured.get("industry", "")
    sub_industry = structured.get("sub_industry", "")
    industry_str = sub_industry or industry or "Unknown"
    
    # Insurance types
    insurance_types = structured.get("insurance_types", [])
    insurance_str = ", ".join(insurance_types) if insurance_types else "None specified"
    
    # Company description
    company_desc = structured.get("description", "")
    
    # Gather recent communications for context
    recent_comms = []
    
    # Get most recent emails (up to 3)
    emails = account_data.get("emails", [])
    for email in emails[:3]:
        subject = email.get("subject", "")
        content = email.get("activity_content", "")[:300]
        if subject or content:
            recent_comms.append(f"Email: {subject}\n{content}")
    
    # Get most recent calls (up to 2)
    calls = account_data.get("phone_calls", [])
    for call in calls[:2]:
        transcript = call.get("source_text", "")[:300]
        if transcript:
            recent_comms.append(f"Call transcript: {transcript}")
    
    # Get most recent SMS (up to 2)
    sms_list = account_data.get("phone_messages", [])
    for sms in sms_list[:2]:
        content = sms.get("source_text", "")[:200]
        if content:
            recent_comms.append(f"SMS: {content}")
    
    comms_text = "\n---\n".join(recent_comms) if recent_comms else "No communications on file."
    
    # Try to generate LLM summary
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            
            prompt = f"""Generate a concise 1-2 sentence searchable description for this insurance account. Include:
- Company name and what they do
- Current stage in the pipeline
- Location (state)
- Key status (e.g., waiting for documents, quote received, needs follow-up)

Account: {name}
Stage: {stage}
Location: {location}
Industry: {industry_str}
Insurance Types: {insurance_str}
Company Description: {company_desc[:200] if company_desc else 'N/A'}

Recent Communications:
{comms_text[:1500]}

Write a concise description that would help find this account when searching for things like:
- "childcare center in Texas"
- "accounts needing follow-up"
- "quotes pending"
- "application received"

Keep it under 100 words. Focus on searchable attributes."""

            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return message.content[0].text.strip()
            
        except Exception as e:
            logger.warning(f"LLM description generation failed: {e}")
    
    # Fallback to template-based description
    parts = [
        name,
        f"Stage: {stage}",
        f"Location: {location}",
        f"Industry: {industry_str}",
        f"Insurance: {insurance_str}",
    ]
    
    if company_desc:
        desc_preview = company_desc[:150] + "..." if len(company_desc) > 150 else company_desc
        parts.append(desc_preview)
    
    return " | ".join(parts)


def extract_last_activity(account_data: dict) -> Optional[dict]:
    """
    Find the most recent activity across emails, calls, and SMS.
    
    Args:
        account_data: The full account data dictionary
        
    Returns:
        dict with 'timestamp' and 'source_ref', or None if no activities
    """
    activities = []
    
    # Collect email timestamps
    for email in account_data.get("emails", []):
        timestamp = email.get("activity_start_time")
        if timestamp:
            activities.append({
                "timestamp": timestamp,
                "source_ref": f"sources/emails/email_{email.get('id')}/raw.txt",
                "type": "email"
            })
    
    # Collect call timestamps (prefer completed_at, fallback to created_at)
    for call in account_data.get("phone_calls", []):
        timestamp = call.get("completed_at") or call.get("created_at")
        if timestamp:
            activities.append({
                "timestamp": timestamp,
                "source_ref": f"sources/calls/call_{call.get('id')}/raw.txt",
                "type": "call"
            })
    
    # Collect SMS timestamps
    for sms in account_data.get("phone_messages", []):
        timestamp = sms.get("created_at")
        if timestamp:
            activities.append({
                "timestamp": timestamp,
                "source_ref": f"sources/sms/sms_{sms.get('id')}/raw.txt",
                "type": "sms"
            })
    
    if not activities:
        return None
    
    # Sort by timestamp (ISO format strings sort correctly)
    activities.sort(key=lambda x: x["timestamp"], reverse=True)
    latest = activities[0]
    
    return {
        "timestamp": latest["timestamp"],
        "source_ref": latest["source_ref"]
    }


def parse_state_md(state_path: Path) -> Optional[dict]:
    """
    Parse an existing state.md file to extract current values.
    
    Args:
        state_path: Path to the state.md file
        
    Returns:
        dict with parsed values or None if file doesn't exist
    """
    if not state_path.exists():
        return None
    
    try:
        content = state_path.read_text(encoding='utf-8')
        state = {}
        
        # Parse stage
        if "**Stage**:" in content:
            stage_match = content.split("**Stage**:")[1].split("\n")[0].strip()
            state["stage"] = stage_match
        
        # Parse insurance types
        if "**Insurance Types**:" in content:
            types_match = content.split("**Insurance Types**:")[1].split("\n")[0].strip()
            state["insurance_types"] = [t.strip() for t in types_match.split(",")]
        
        # Parse primary email
        if "**Primary Email**:" in content:
            email_match = content.split("**Primary Email**:")[1].split("\n")[0].strip()
            state["primary_email"] = email_match
        
        # Parse primary phone
        if "**Primary Phone**:" in content:
            phone_match = content.split("**Primary Phone**:")[1].split("\n")[0].strip()
            state["primary_phone"] = phone_match
        
        return state
    except Exception as e:
        logger.warning(f"Could not parse existing state.md: {e}")
        return None


def generate_next_steps(account_data: dict) -> dict:
    """
    Analyze account communications to extract next steps and pending actions.
    
    Uses LLM to analyze recent emails, calls, and SMS to determine:
    - Action items for Harper (next steps)
    - Documents or info the client owes (pending)
    - Last meaningful contact date
    
    Args:
        account_data: The full account data dictionary
        
    Returns:
        {
            "next_steps": ["Follow up on quote", "Send reminder"],
            "pending": ["Waiting for loss runs", "COI requested"],
            "last_contact_date": "2025-12-15",
            "last_contact_type": "email"
        }
    """
    # Gather recent communications
    recent_comms = []
    last_contact_date = None
    last_contact_type = None
    
    # Get emails (most recent first based on timestamp)
    emails = account_data.get("emails", [])
    for email in emails[:5]:
        subject = email.get("subject", "")
        content = email.get("activity_content", "")[:500]
        timestamp = email.get("activity_start_time", "")
        direction = email.get("direction", "")
        if subject or content:
            recent_comms.append(f"Email ({direction}, {timestamp}): {subject}\n{content}")
            if timestamp and (not last_contact_date or timestamp > last_contact_date):
                last_contact_date = timestamp
                last_contact_type = "email"
    
    # Get calls
    calls = account_data.get("phone_calls", [])
    for call in calls[:3]:
        transcript = call.get("source_text", "")[:500]
        timestamp = call.get("completed_at") or call.get("created_at", "")
        if transcript:
            recent_comms.append(f"Call ({timestamp}):\n{transcript}")
            if timestamp and (not last_contact_date or timestamp > last_contact_date):
                last_contact_date = timestamp
                last_contact_type = "call"
    
    # Get SMS
    sms_list = account_data.get("phone_messages", [])
    for sms in sms_list[:3]:
        content = sms.get("source_text", "")[:200]
        timestamp = sms.get("created_at", "")
        if content:
            recent_comms.append(f"SMS ({timestamp}): {content}")
            if timestamp and (not last_contact_date or timestamp > last_contact_date):
                last_contact_date = timestamp
                last_contact_type = "sms"
    
    # Default result
    result = {
        "next_steps": [],
        "pending": [],
        "last_contact_date": last_contact_date[:10] if last_contact_date else "Unknown",
        "last_contact_type": last_contact_type or "Unknown"
    }
    
    if not recent_comms:
        result["next_steps"] = ["Initial outreach needed"]
        result["pending"] = ["No communications on file"]
        return result
    
    comms_text = "\n---\n".join(recent_comms)
    account_name = account_data.get("account_name", "Unknown")
    stage = account_data.get("structured_data", {}).get("general_stage", "Unknown")
    
    # Use LLM to extract next steps and pending actions
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        try:
            client = anthropic.Anthropic(api_key=api_key)
            
            prompt = f"""Analyze these insurance communications and extract action items.

Account: {account_name}
Current Stage: {stage}

Recent Communications:
{comms_text[:3000]}

Extract and return ONLY a JSON object with these fields:
1. "next_steps": List of 1-3 specific actions Harper (the broker) should take next
2. "pending": List of 1-3 things the client owes or that are pending (documents, decisions, info)

Focus on actionable, specific items. If nothing is pending, say "None identified".

Return ONLY valid JSON, no other text:
{{"next_steps": [...], "pending": [...]}}"""

            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            response_text = message.content[0].text.strip()
            # Parse JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                result["next_steps"] = parsed.get("next_steps", [])[:3]
                result["pending"] = parsed.get("pending", [])[:3]
            
        except Exception as e:
            logger.warning(f"LLM next steps generation failed: {e}")
            result["next_steps"] = ["Review account status"]
            result["pending"] = ["Check for outstanding items"]
    
    return result


def write_state_md(account_data: dict, account_dir: Path) -> dict:
    """
    Write state.md from account data in markdown format.
    
    Args:
        account_data: The full account data dictionary
        account_dir: Path to the account directory
        
    Returns:
        dict with new state values for change detection
    """
    structured = account_data.get("structured_data", {})
    
    account_id = str(account_data.get("account_id", ""))
    account_name = account_data.get("account_name", "")
    stage = structured.get("general_stage") or structured.get("company_stage_manual", "")
    insurance_types = structured.get("insurance_types", [])
    primary_email = structured.get("primary_email", "")
    primary_phone = structured.get("primary_phone", "")
    
    # Format insurance types as comma-separated
    insurance_str = ", ".join(insurance_types) if insurance_types else "None"
    
    # Generate next steps and pending actions from communications
    next_steps_data = generate_next_steps(account_data)
    
    # Format next steps as bullet list
    next_steps_list = "\n".join([f"- {step}" for step in next_steps_data["next_steps"]]) if next_steps_data["next_steps"] else "- None identified"
    
    # Format pending actions as bullet list
    pending_list = "\n".join([f"- {item}" for item in next_steps_data["pending"]]) if next_steps_data["pending"] else "- None identified"
    
    # Build markdown content
    state_md = f"""# {account_name} (Account {account_id})

## Status
- **Stage**: {stage}
- **Insurance Types**: {insurance_str}

## Contacts
- **Primary Email**: {primary_email}
- **Primary Phone**: {primary_phone}

## Next Steps
{next_steps_list}

## Pending Actions
{pending_list}

## Last Contact
- **Date**: {next_steps_data["last_contact_date"]}
- **Type**: {next_steps_data["last_contact_type"]}
"""
    
    # Write to file
    state_path = account_dir / "state.md"
    with open(state_path, 'w', encoding='utf-8') as f:
        f.write(state_md)
    
    # Return new state for change detection
    return {
        "stage": stage,
        "insurance_types": insurance_types,
        "primary_email": primary_email,
        "primary_phone": primary_phone
    }


def generate_change_summary(changes: list[dict], source_content: str, account_name: str) -> str:
    """
    Use Claude API to generate a natural language summary of the changes.
    
    Args:
        changes: List of change dictionaries with field, old_value, new_value
        source_content: Content of the source file that triggered the changes
        account_name: Name of the account
        
    Returns:
        LLM-generated summary string
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not found, using simple summary")
        # Fallback to simple summary
        summaries = []
        for change in changes:
            summaries.append(f"{change['field']} changed from \"{change['old_value']}\" to \"{change['new_value']}\"")
        return ". ".join(summaries) + "."
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        # Build the prompt
        changes_text = "\n".join([
            f"- {c['field']}: \"{c['old_value']}\" → \"{c['new_value']}\""
            for c in changes
        ])
        
        prompt = f"""You are summarizing changes to an insurance account record. Write a brief 1-2 sentence summary explaining what changed and why, based on the source document.

Account: {account_name}

Changes detected:
{changes_text}

Source document that triggered these changes:
{source_content[:2000]}

Write a concise, natural language summary of what happened. Focus on the business meaning, not the technical field names."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text.strip()
        
    except Exception as e:
        logger.warning(f"LLM summary generation failed: {e}")
        # Fallback to simple summary
        summaries = []
        for change in changes:
            summaries.append(f"{change['field']} changed from \"{change['old_value']}\" to \"{change['new_value']}\"")
        return ". ".join(summaries) + "."


def append_history_md(account_dir: Path, timestamp: str, summary: str, 
                      changes: list[dict], source_ref: str) -> None:
    """
    Append a change entry to history.md.
    
    Args:
        account_dir: Path to the account directory
        timestamp: ISO timestamp of the change
        summary: LLM-generated summary of the changes
        changes: List of change dictionaries
        source_ref: Path to the source file that triggered the change
    """
    history_path = account_dir / "history.md"
    
    # Build the change entry
    changes_text = "\n".join([
        f"- **{c['field']}**: {c['old_value']} → {c['new_value']}"
        for c in changes
    ])
    
    entry = f"""## {timestamp}

{summary}

{changes_text}
- **Evidence**: [{source_ref.split('/')[-1]}]({source_ref})

---

"""
    
    # Check if history.md exists, create header if not
    if not history_path.exists():
        with open(history_path, 'w', encoding='utf-8') as f:
            f.write("# Change History\n\n")
    
    # Append the entry
    with open(history_path, 'a', encoding='utf-8') as f:
        f.write(entry)


def detect_and_record_changes(account_data: dict, account_dir: Path, 
                               old_state: Optional[dict], new_state: dict) -> None:
    """
    Detect changes between old and new state, generate summary, and record to history.
    
    Args:
        account_data: The full account data dictionary
        account_dir: Path to the account directory
        old_state: Previous state values (or None if first ingestion)
        new_state: New state values
    """
    if old_state is None:
        return  # No previous state, nothing to compare
    
    # Fields to compare
    fields_to_check = ["stage", "insurance_types", "primary_email", "primary_phone"]
    
    changes = []
    for field in fields_to_check:
        old_value = old_state.get(field)
        new_value = new_state.get(field)
        
        if old_value != new_value:
            changes.append({
                "field": field,
                "old_value": old_value,
                "new_value": new_value
            })
    
    if not changes:
        return  # No changes detected
    
    # Get the most recent activity for timestamp and source
    last_activity = extract_last_activity(account_data)
    if not last_activity:
        return  # No activity to attribute changes to
    
    timestamp = last_activity["timestamp"]
    source_ref = last_activity["source_ref"]
    
    # Load source content for LLM summary
    source_path = account_dir / source_ref
    source_content = ""
    if source_path.exists():
        try:
            source_content = source_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"Could not read source file {source_ref}: {e}")
    
    # Generate LLM summary
    account_name = account_data.get("account_name", "Unknown")
    summary = generate_change_summary(changes, source_content, account_name)
    
    # Append to history.md
    append_history_md(account_dir, timestamp, summary, changes, source_ref)
    
    logger.info(f"Recorded {len(changes)} change(s) to history.md")


def generate_source_summary(source_type: str, source_data: dict, raw_content: str) -> str:
    """
    Generate an LLM summary for a single source item (email, call, or SMS).
    
    Args:
        source_type: "email", "call", or "sms"
        source_data: The source data dictionary
        raw_content: The raw text content of the source
        
    Returns:
        Markdown-formatted summary
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Fallback to simple summary
        return f"# {source_type.title()} Summary\n\nNo summary available (API key not set).\n"
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        prompt = f"""Generate a comprehensive markdown summary for this {source_type} that will help Harper (an insurance broker) understand the full context. Extract ALL important details:

## Business Details (if mentioned)
- Company name, type of business, industry
- Number of employees, revenue, years in operation
- Coverage needs, policy types discussed
- Premium amounts, deductibles, limits
- Claims history or loss runs
- Renewal dates, effective dates
- Documents requested or provided
- Carrier names, quotes, or recommendations

## Personal Details (if mentioned)
- Contact name(s) and role/title
- Phone numbers, emails, preferred contact method
- Personality notes (communication style, concerns, preferences)
- Family or personal details shared
- Availability or scheduling preferences

## Conversation Context
- Main topic or purpose of this {source_type}
- Key questions asked or answered
- Decisions made or pending
- Action items for Harper
- Action items for the customer
- Follow-up timeline or next steps
- Tone/sentiment (happy, frustrated, urgent, etc.)

Use markdown with headers and bullet points. Include ALL relevant details - don't omit anything that could be useful later.

{source_type.upper()} CONTENT:
{raw_content[:3000]}

Generate the summary now:"""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast model for source summaries
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text.strip()
        
    except Exception as e:
        logger.warning(f"LLM source summary generation failed: {e}")
        return f"# {source_type.title()} Summary\n\nSummary generation failed.\n"


def write_email_file(email_data: dict, emails_dir: Path) -> None:
    """
    Write a single email to a folder with summary.md and raw.txt.
    
    Args:
        email_data: Email data dictionary
        emails_dir: Path to the emails directory
    """
    email_id = email_data.get("id")
    if not email_id:
        logger.warning("Email missing id, skipping")
        return
    
    # Create folder for this email
    email_folder = emails_dir / f"email_{email_id}"
    email_folder.mkdir(parents=True, exist_ok=True)
    
    # Extract email fields
    subject = email_data.get("subject", "(No subject)")
    from_field = email_data.get("from", {})
    if isinstance(from_field, dict):
        from_str = from_field.get("address", from_field.get("name", "Unknown"))
    else:
        from_str = str(from_field)
    
    to_field = email_data.get("to", [])
    if isinstance(to_field, list):
        to_str = ", ".join(
            t.get("address", t.get("name", "")) if isinstance(t, dict) else str(t) 
            for t in to_field
        )
    else:
        to_str = str(to_field)
    
    timestamp = email_data.get("activity_start_time", "")
    direction = email_data.get("direction", "")
    content = email_data.get("activity_content") or email_data.get("source_body", "")
    
    # Format the raw email file
    email_text = f"""Subject: {subject}
From: {from_str}
To: {to_str}
Date: {timestamp}
Direction: {direction}

{content}
"""
    
    # Write raw.txt
    raw_path = email_folder / "raw.txt"
    with open(raw_path, 'w', encoding='utf-8') as f:
        f.write(email_text)
    
    # Generate and write summary.md
    summary_header = f"""# Email Summary

**Date:** {timestamp}
**Direction:** {direction.title()}
**Subject:** {subject}
**From:** {from_str}
**To:** {to_str}

"""
    summary_content = generate_source_summary("email", email_data, email_text)
    
    summary_path = email_folder / "summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_header + summary_content)


def write_call_file(call_data: dict, calls_dir: Path) -> None:
    """
    Write a single call to a folder with summary.md and raw.txt.
    
    Args:
        call_data: Call data dictionary
        calls_dir: Path to the calls directory
    """
    call_id = call_data.get("id")
    if not call_id:
        logger.warning("Call missing id, skipping")
        return
    
    # Create folder for this call
    call_folder = calls_dir / f"call_{call_id}"
    call_folder.mkdir(parents=True, exist_ok=True)
    
    direction = call_data.get("direction", "")
    duration = call_data.get("duration_seconds", 0)
    created_at = call_data.get("created_at", "")
    completed_at = call_data.get("completed_at", "")
    source_text = call_data.get("source_text", "")
    
    # Format duration
    if duration:
        minutes = int(duration) // 60
        seconds = int(duration) % 60
        duration_str = f"{minutes}m {seconds}s"
    else:
        duration_str = "Unknown"
    
    # Format the raw call file
    call_text = f"""Direction: {direction}
Duration: {duration_str}
Started: {created_at}
Completed: {completed_at}

{source_text}
"""
    
    # Write raw.txt
    raw_path = call_folder / "raw.txt"
    with open(raw_path, 'w', encoding='utf-8') as f:
        f.write(call_text)
    
    # Generate and write summary.md
    summary_header = f"""# Call Summary

**Date:** {created_at}
**Duration:** {duration_str}
**Direction:** {direction.title()}

"""
    summary_content = generate_source_summary("call", call_data, call_text)
    
    summary_path = call_folder / "summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_header + summary_content)


def write_sms_file(sms_data: dict, sms_dir: Path) -> None:
    """
    Write a single SMS message to a folder with summary.md and raw.txt.
    
    Args:
        sms_data: SMS data dictionary
        sms_dir: Path to the sms directory
    """
    sms_id = sms_data.get("id")
    if not sms_id:
        logger.warning("SMS missing id, skipping")
        return
    
    # Create folder for this SMS
    sms_folder = sms_dir / f"sms_{sms_id}"
    sms_folder.mkdir(parents=True, exist_ok=True)
    
    direction = sms_data.get("direction", "")
    timestamp = sms_data.get("created_at", "")
    content = sms_data.get("source_text", "")
    
    # Format the raw SMS file
    sms_text = f"""Direction: {direction}
Date: {timestamp}

{content}
"""
    
    # Write raw.txt
    raw_path = sms_folder / "raw.txt"
    with open(raw_path, 'w', encoding='utf-8') as f:
        f.write(sms_text)
    
    # Generate and write summary.md
    summary_header = f"""# SMS Summary

**Date:** {timestamp}
**Direction:** {direction.title()}

"""
    summary_content = generate_source_summary("sms", sms_data, sms_text)
    
    summary_path = sms_folder / "summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_header + summary_content)


def write_source_files(account_data: dict, account_dir: Path) -> dict:
    """
    Write all source files (emails, calls, SMS) for an account.
    
    Args:
        account_data: The full account data dictionary
        account_dir: Path to the account directory
        
    Returns:
        dict with counts of files written
    """
    sources_dir = account_dir / "sources"
    counts = {"emails": 0, "calls": 0, "sms": 0}
    
    # Write emails
    emails_dir = sources_dir / "emails"
    for email in account_data.get("emails", []):
        try:
            write_email_file(email, emails_dir)
            counts["emails"] += 1
        except Exception as e:
            logger.warning(f"Failed to write email {email.get('id')}: {e}")
    
    # Write calls
    calls_dir = sources_dir / "calls"
    for call in account_data.get("phone_calls", []):
        try:
            write_call_file(call, calls_dir)
            counts["calls"] += 1
        except Exception as e:
            logger.warning(f"Failed to write call {call.get('id')}: {e}")
    
    # Write SMS
    sms_dir = sources_dir / "sms"
    for sms in account_data.get("phone_messages", []):
        try:
            write_sms_file(sms, sms_dir)
            counts["sms"] += 1
        except Exception as e:
            logger.warning(f"Failed to write SMS {sms.get('id')}: {e}")
    
    return counts


def ingest_accounts(input_file: str, output_base: str = "mem") -> dict:
    """
    Main orchestration function for the ingestion pipeline.
    
    Args:
        input_file: Path to the accounts.jsonl file
        output_base: Base output directory (default: "mem")
        
    Returns:
        dict with statistics about the ingestion
    """
    stats = {
        "accounts_processed": 0,
        "accounts_failed": 0,
        "total_emails": 0,
        "total_calls": 0,
        "total_sms": 0,
        "accounts_indexed": 0,
        "errors": []
    }
    
    accounts_base = Path(output_base) / "accounts"
    
    # Ensure system_rules.md exists (static config file for the agent)
    system_rules_path = Path(output_base) / "system_rules.md"
    if not system_rules_path.exists():
        logger.info("Creating system_rules.md...")
        create_system_rules(system_rules_path)
    
    # Initialize name registry for Qdrant indexing
    registry = None
    try:
        registry = NameRegistry()
        logger.info("Connected to Qdrant name registry")
    except Exception as e:
        logger.warning(f"Could not connect to Qdrant (run 'docker compose up -d'): {e}")
        logger.warning("Proceeding without name registry indexing")
    
    # Count total accounts first for progress reporting
    logger.info(f"Reading accounts from {input_file}...")
    accounts_list = list(parse_accounts_jsonl(input_file))
    total_accounts = len(accounts_list)
    logger.info(f"Found {total_accounts} accounts to process")
    
    for idx, account_data in enumerate(accounts_list, start=1):
        account_id = account_data.get("account_id")
        account_name = account_data.get("account_name", "Unknown")
        
        if not account_id:
            logger.warning(f"Account at index {idx} missing account_id, skipping")
            stats["accounts_failed"] += 1
            stats["errors"].append(f"Missing account_id at index {idx}")
            continue
        
        try:
            # Progress indicator
            logger.info(f"Processing account {idx}/{total_accounts}: {account_name} (ID: {account_id})")
            
            # Create directory structure
            account_dir = create_account_directory(str(account_id), str(accounts_base))
            
            # Parse existing state.md for change detection
            state_path = account_dir / "state.md"
            old_state = parse_state_md(state_path)
            
            # Write source files first (needed for change summary)
            counts = write_source_files(account_data, account_dir)
            
            # Write state.md and get new state values
            new_state = write_state_md(account_data, account_dir)
            
            # Ensure history.md exists (create empty if needed)
            history_path = account_dir / "history.md"
            if not history_path.exists():
                with open(history_path, 'w', encoding='utf-8') as f:
                    f.write("# Change History\n\nNo changes recorded yet.\n")
            
            # Detect and record changes to history.md
            detect_and_record_changes(account_data, account_dir, old_state, new_state)
            
            # Index account name and description in Qdrant for fast lookup
            if registry is not None:
                try:
                    directory_path = f"{output_base}/accounts/{account_id}"
                    
                    # Index by name (for lookup_account)
                    registry.upsert_account(
                        account_id=str(account_id),
                        name=account_name,
                        directory_path=directory_path
                    )
                    
                    # Index by description (for search_descriptions)
                    description = generate_account_description(account_data)
                    registry.upsert_description(
                        account_id=str(account_id),
                        name=account_name,
                        description=description,
                        directory_path=directory_path
                    )
                    
                    stats["accounts_indexed"] += 1
                except Exception as e:
                    logger.warning(f"Failed to index account {account_id} in Qdrant: {e}")
            
            # Update stats
            stats["accounts_processed"] += 1
            stats["total_emails"] += counts["emails"]
            stats["total_calls"] += counts["calls"]
            stats["total_sms"] += counts["sms"]
            
        except Exception as e:
            logger.error(f"Failed to process account {account_id}: {e}")
            stats["accounts_failed"] += 1
            stats["errors"].append(f"Account {account_id}: {str(e)}")
    
    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ingest accounts.jsonl into mem/ directory structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python ingest.py --input accounts.jsonl --output mem
        """
    )
    parser.add_argument(
        "--input", "-i",
        default="accounts.jsonl",
        help="Path to input JSONL file (default: accounts.jsonl)"
    )
    parser.add_argument(
        "--output", "-o",
        default="mem",
        help="Base output directory (default: mem)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=" * 60)
    logger.info("Ingestion Pipeline for Experiment 1")
    logger.info("=" * 60)
    logger.info(f"Input: {args.input}")
    logger.info(f"Output: {args.output}")
    logger.info("")
    
    try:
        stats = ingest_accounts(args.input, args.output)
        
        # Print summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("Ingestion Complete")
        logger.info("=" * 60)
        logger.info(f"Accounts processed: {stats['accounts_processed']}")
        logger.info(f"Accounts failed: {stats['accounts_failed']}")
        logger.info(f"Total emails written: {stats['total_emails']}")
        logger.info(f"Total calls written: {stats['total_calls']}")
        logger.info(f"Total SMS written: {stats['total_sms']}")
        logger.info(f"Accounts indexed in Qdrant: {stats['accounts_indexed']}")
        
        if stats["errors"]:
            logger.warning(f"\nErrors encountered ({len(stats['errors'])}):")
            for error in stats["errors"][:10]:  # Show first 10 errors
                logger.warning(f"  - {error}")
            if len(stats["errors"]) > 10:
                logger.warning(f"  ... and {len(stats['errors']) - 10} more")
        
        # Exit with error code if any accounts failed
        if stats["accounts_failed"] > 0:
            sys.exit(1)
            
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
