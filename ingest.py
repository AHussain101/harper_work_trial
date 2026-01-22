#!/usr/bin/env python3
"""
Ingestion Pipeline for Experiment 1: Pure Exploration Workflow Agent

Reads accounts.jsonl and transforms it into the filesystem memory structure
required by the exploration agent.

Usage:
    python ingest.py [--input accounts.jsonl] [--output mem]
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

import anthropic
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from tqdm import tqdm

from name_registry import NameRegistry

# Semaphore to limit concurrent LLM API calls (avoid rate limits)
MAX_CONCURRENT_LLM_CALLS = 10


class IngestionProgress:
    """Track and display ingestion progress with time estimation."""
    
    def __init__(self, total_accounts: int, total_sources: int = 0):
        self.total_accounts = total_accounts
        self.total_sources = total_sources
        self.start_time = time.time()
        self.accounts_done = 0
        self.sources_done = 0
        self.current_account = ""
        
        # Create progress bars
        self.account_pbar = tqdm(
            total=total_accounts,
            desc="Accounts",
            unit="acct",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
            position=0,
            leave=True
        )
        
        self.source_pbar = tqdm(
            total=total_sources if total_sources > 0 else 1,
            desc="Sources ",
            unit="src",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
            position=1,
            leave=True
        )
    
    def update_account(self, account_name: str, emails: int = 0, calls: int = 0, sms: int = 0):
        """Update progress after processing an account."""
        self.accounts_done += 1
        sources_processed = emails + calls + sms
        self.sources_done += sources_processed
        
        self.account_pbar.update(1)
        self.source_pbar.update(sources_processed)
        
        # Update description with current account
        elapsed = time.time() - self.start_time
        rate = self.accounts_done / elapsed if elapsed > 0 else 0
        self.account_pbar.set_postfix_str(f"last: {account_name[:25]}...")
    
    def set_total_sources(self, total: int):
        """Update total sources count (called after counting all sources)."""
        self.total_sources = total
        self.source_pbar.total = total
        self.source_pbar.refresh()
    
    def close(self):
        """Close progress bars and show summary."""
        self.account_pbar.close()
        self.source_pbar.close()
    
    def get_summary(self) -> dict:
        """Get timing summary."""
        elapsed = time.time() - self.start_time
        return {
            "elapsed_seconds": elapsed,
            "elapsed_formatted": str(timedelta(seconds=int(elapsed))),
            "accounts_per_second": self.accounts_done / elapsed if elapsed > 0 else 0,
            "sources_per_second": self.sources_done / elapsed if elapsed > 0 else 0,
        }


def count_sources(accounts_list: list[dict]) -> int:
    """Count total sources across all accounts."""
    total = 0
    for account in accounts_list:
        total += len(account.get("emails", []))
        total += len(account.get("phone_calls", []))
        total += len(account.get("phone_messages", []))
    return total

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


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
        
        prompt = f"""Summarize this {source_type} for an insurance broker.
Be concise - only include details that are actually present.
Keep the summary shorter than or equal in length to the source content.

{source_type.upper()}:
{raw_content[:3000]}"""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",  # Fast model for source summaries
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text.strip()
        
    except Exception as e:
        logger.warning(f"LLM source summary generation failed: {e}")
        return f"# {source_type.title()} Summary\n\nSummary generation failed.\n"


# ============================================================================
# ASYNC LLM FUNCTIONS - For parallel processing
# ============================================================================

async def generate_source_summary_async(
    source_type: str, 
    source_data: dict, 
    raw_content: str,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> str:
    """
    Async version of generate_source_summary for parallel processing.
    """
    async with semaphore:
        try:
            prompt = f"""Summarize this {source_type} for an insurance broker.
Be concise - only include details that are actually present.
Keep the summary shorter than or equal in length to the source content.

{source_type.upper()}:
{raw_content[:3000]}"""

            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return message.content[0].text.strip()
            
        except Exception as e:
            logger.warning(f"Async LLM source summary generation failed: {e}")
            return f"# {source_type.title()} Summary\n\nSummary generation failed.\n"


async def generate_next_steps_async(
    account_data: dict,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> dict:
    """
    Async version of generate_next_steps for parallel processing.
    """
    # Gather recent communications
    recent_comms = []
    last_contact_date = None
    last_contact_type = None
    
    # Get emails
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
    
    async with semaphore:
        try:
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

            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            response_text = message.content[0].text.strip()
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                result["next_steps"] = parsed.get("next_steps", [])[:3]
                result["pending"] = parsed.get("pending", [])[:3]
            
        except Exception as e:
            logger.warning(f"Async LLM next steps generation failed: {e}")
            result["next_steps"] = ["Review account status"]
            result["pending"] = ["Check for outstanding items"]
    
    return result


async def generate_account_description_async(
    account_data: dict,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> str:
    """
    Async version of generate_account_description for parallel processing.
    """
    structured = account_data.get("structured_data", {})
    
    name = account_data.get("account_name", "Unknown")
    stage = structured.get("general_stage") or structured.get("company_stage_manual", "Unknown")
    
    address = structured.get("address", {})
    city = address.get("city", "")
    state = address.get("state", "")
    location_parts = [p for p in [city, state] if p]
    location = ", ".join(location_parts) if location_parts else "Unknown"
    
    industry = structured.get("industry", "")
    sub_industry = structured.get("sub_industry", "")
    industry_str = sub_industry or industry or "Unknown"
    
    insurance_types = structured.get("insurance_types", [])
    insurance_str = ", ".join(insurance_types) if insurance_types else "None specified"
    
    company_desc = structured.get("description", "")
    
    # Gather recent communications
    recent_comms = []
    emails = account_data.get("emails", [])
    for email in emails[:3]:
        subject = email.get("subject", "")
        content = email.get("activity_content", "")[:300]
        if subject or content:
            recent_comms.append(f"Email: {subject}\n{content}")
    
    calls = account_data.get("phone_calls", [])
    for call in calls[:2]:
        transcript = call.get("source_text", "")[:300]
        if transcript:
            recent_comms.append(f"Call transcript: {transcript}")
    
    sms_list = account_data.get("phone_messages", [])
    for sms in sms_list[:2]:
        content = sms.get("source_text", "")[:200]
        if content:
            recent_comms.append(f"SMS: {content}")
    
    comms_text = "\n---\n".join(recent_comms) if recent_comms else "No communications on file."
    
    async with semaphore:
        try:
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

            message = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            return message.content[0].text.strip()
            
        except Exception as e:
            logger.warning(f"Async LLM description generation failed: {e}")
    
    # Fallback
    parts = [name, f"Stage: {stage}", f"Location: {location}", 
             f"Industry: {industry_str}", f"Insurance: {insurance_str}"]
    if company_desc:
        desc_preview = company_desc[:150] + "..." if len(company_desc) > 150 else company_desc
        parts.append(desc_preview)
    return " | ".join(parts)


async def write_email_file_async(
    email_data: dict, 
    emails_dir: Path,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> bool:
    """
    Async write a single email to a folder with summary.md and raw.txt.
    Returns True if successful.
    """
    email_id = email_data.get("id")
    if not email_id:
        return False
    
    email_folder = emails_dir / f"email_{email_id}"
    email_folder.mkdir(parents=True, exist_ok=True)
    
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
    
    email_text = f"""Subject: {subject}
From: {from_str}
To: {to_str}
Date: {timestamp}
Direction: {direction}

{content}
"""
    
    # Write raw.txt (sync - fast)
    raw_path = email_folder / "raw.txt"
    with open(raw_path, 'w', encoding='utf-8') as f:
        f.write(email_text)
    
    # Generate summary async
    summary_content = await generate_source_summary_async("email", email_data, email_text, semaphore, client)
    
    summary_header = f"""# Email Summary

**Date:** {timestamp}
**Direction:** {direction.title()}
**Subject:** {subject}
**From:** {from_str}
**To:** {to_str}

"""
    
    summary_path = email_folder / "summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_header + summary_content)
    
    return True


async def write_call_file_async(
    call_data: dict, 
    calls_dir: Path,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> bool:
    """
    Async write a single call to a folder with summary.md and raw.txt.
    """
    call_id = call_data.get("id")
    if not call_id:
        return False
    
    call_folder = calls_dir / f"call_{call_id}"
    call_folder.mkdir(parents=True, exist_ok=True)
    
    direction = call_data.get("direction", "")
    duration = call_data.get("duration_seconds", 0)
    created_at = call_data.get("created_at", "")
    completed_at = call_data.get("completed_at", "")
    source_text = call_data.get("source_text", "")
    
    if duration:
        minutes = int(duration) // 60
        seconds = int(duration) % 60
        duration_str = f"{minutes}m {seconds}s"
    else:
        duration_str = "Unknown"
    
    call_text = f"""Direction: {direction}
Duration: {duration_str}
Started: {created_at}
Completed: {completed_at}

{source_text}
"""
    
    raw_path = call_folder / "raw.txt"
    with open(raw_path, 'w', encoding='utf-8') as f:
        f.write(call_text)
    
    summary_content = await generate_source_summary_async("call", call_data, call_text, semaphore, client)
    
    summary_header = f"""# Call Summary

**Date:** {created_at}
**Duration:** {duration_str}
**Direction:** {direction.title()}

"""
    
    summary_path = call_folder / "summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_header + summary_content)
    
    return True


async def write_sms_file_async(
    sms_data: dict, 
    sms_dir: Path,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> bool:
    """
    Async write a single SMS to a folder with summary.md and raw.txt.
    """
    sms_id = sms_data.get("id")
    if not sms_id:
        return False
    
    sms_folder = sms_dir / f"sms_{sms_id}"
    sms_folder.mkdir(parents=True, exist_ok=True)
    
    direction = sms_data.get("direction", "")
    timestamp = sms_data.get("created_at", "")
    content = sms_data.get("source_text", "")
    
    sms_text = f"""Direction: {direction}
Date: {timestamp}

{content}
"""
    
    raw_path = sms_folder / "raw.txt"
    with open(raw_path, 'w', encoding='utf-8') as f:
        f.write(sms_text)
    
    summary_content = await generate_source_summary_async("sms", sms_data, sms_text, semaphore, client)
    
    summary_header = f"""# SMS Summary

**Date:** {timestamp}
**Direction:** {direction.title()}

"""
    
    summary_path = sms_folder / "summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary_header + summary_content)
    
    return True


async def write_source_files_async(
    account_data: dict, 
    account_dir: Path,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> dict:
    """
    Async write all source files for an account, processing in parallel.
    
    Returns:
        dict with counts of files written
    """
    sources_dir = account_dir / "sources"
    
    # Collect all async tasks
    tasks = []
    
    # Email tasks
    emails_dir = sources_dir / "emails"
    for email in account_data.get("emails", []):
        tasks.append(("email", write_email_file_async(email, emails_dir, semaphore, client)))
    
    # Call tasks
    calls_dir = sources_dir / "calls"
    for call in account_data.get("phone_calls", []):
        tasks.append(("call", write_call_file_async(call, calls_dir, semaphore, client)))
    
    # SMS tasks
    sms_dir = sources_dir / "sms"
    for sms in account_data.get("phone_messages", []):
        tasks.append(("sms", write_sms_file_async(sms, sms_dir, semaphore, client)))
    
    # Run all tasks in parallel
    counts = {"emails": 0, "calls": 0, "sms": 0}
    
    if tasks:
        results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        
        for (source_type, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                logger.warning(f"Failed to write {source_type}: {result}")
            elif result:
                if source_type == "email":
                    counts["emails"] += 1
                elif source_type == "call":
                    counts["calls"] += 1
                elif source_type == "sms":
                    counts["sms"] += 1
    
    return counts


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


async def process_account_async(
    account_data: dict,
    accounts_base: Path,
    output_base: str,
    semaphore: asyncio.Semaphore,
    client: AsyncAnthropic
) -> dict:
    """
    Process a single account asynchronously.
    
    Returns:
        dict with processing results for this account
    """
    account_id = account_data.get("account_id")
    account_name = account_data.get("account_name", "Unknown")
    
    result = {
        "account_id": account_id,
        "account_name": account_name,
        "success": False,
        "emails": 0,
        "calls": 0,
        "sms": 0,
        "error": None,
        "index_data": None  # For batch Qdrant indexing later
    }
    
    if not account_id:
        result["error"] = "Missing account_id"
        return result
    
    try:
        # Create directory structure
        account_dir = create_account_directory(str(account_id), str(accounts_base))
        
        # Parse existing state.md for change detection
        state_path = account_dir / "state.md"
        old_state = parse_state_md(state_path)
        
        # Write source files with async LLM calls (parallel within this account)
        counts = await write_source_files_async(account_data, account_dir, semaphore, client)
        
        # Generate next steps async for state.md
        next_steps_data = await generate_next_steps_async(account_data, semaphore, client)
        
        # Write state.md (mostly sync, uses pre-computed next_steps)
        new_state = write_state_md_with_next_steps(account_data, account_dir, next_steps_data)
        
        # Ensure history.md exists
        history_path = account_dir / "history.md"
        if not history_path.exists():
            with open(history_path, 'w', encoding='utf-8') as f:
                f.write("# Change History\n\nNo changes recorded yet.\n")
        
        # Detect and record changes
        detect_and_record_changes(account_data, account_dir, old_state, new_state)
        
        # Generate description async for Qdrant indexing
        description = await generate_account_description_async(account_data, semaphore, client)
        
        # Store data for batch Qdrant indexing (done later)
        result["index_data"] = {
            "account_id": str(account_id),
            "name": account_name,
            "description": description,
            "directory_path": f"{output_base}/accounts/{account_id}"
        }
        
        result["success"] = True
        result["emails"] = counts["emails"]
        result["calls"] = counts["calls"]
        result["sms"] = counts["sms"]
        
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Failed to process account {account_id}: {e}")
    
    return result


def write_state_md_with_next_steps(account_data: dict, account_dir: Path, next_steps_data: dict) -> dict:
    """
    Write state.md using pre-computed next_steps data (for async pipeline).
    """
    structured = account_data.get("structured_data", {})
    
    account_id = str(account_data.get("account_id", ""))
    account_name = account_data.get("account_name", "")
    stage = structured.get("general_stage") or structured.get("company_stage_manual", "")
    insurance_types = structured.get("insurance_types", [])
    primary_email = structured.get("primary_email", "")
    primary_phone = structured.get("primary_phone", "")
    
    insurance_str = ", ".join(insurance_types) if insurance_types else "None"
    
    next_steps_list = "\n".join([f"- {step}" for step in next_steps_data["next_steps"]]) if next_steps_data["next_steps"] else "- None identified"
    pending_list = "\n".join([f"- {item}" for item in next_steps_data["pending"]]) if next_steps_data["pending"] else "- None identified"
    
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
    
    state_path = account_dir / "state.md"
    with open(state_path, 'w', encoding='utf-8') as f:
        f.write(state_md)
    
    return {
        "stage": stage,
        "insurance_types": insurance_types,
        "primary_email": primary_email,
        "primary_phone": primary_phone
    }


async def ingest_accounts_async(
    accounts_list: list[dict],
    output_base: str,
    max_concurrent_accounts: int = 5,
    show_progress: bool = True
) -> dict:
    """
    Async ingestion of multiple accounts with parallel processing.
    
    Args:
        accounts_list: List of account data dictionaries
        output_base: Base output directory
        max_concurrent_accounts: Max accounts to process in parallel
        show_progress: Show progress bars and time estimation
        
    Returns:
        dict with aggregated statistics
    """
    stats = {
        "accounts_processed": 0,
        "accounts_failed": 0,
        "total_emails": 0,
        "total_calls": 0,
        "total_sms": 0,
        "accounts_indexed": 0,
        "errors": [],
        "timing": {}
    }
    
    accounts_base = Path(output_base) / "accounts"
    total_accounts = len(accounts_list)
    total_sources = count_sources(accounts_list)
    
    # Create async Anthropic client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not found")
        return stats
    
    client = AsyncAnthropic(api_key=api_key)
    
    # Semaphore to limit concurrent LLM API calls
    llm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
    
    # Initialize progress tracker
    progress = None
    if show_progress:
        print()  # New line before progress bars
        progress = IngestionProgress(total_accounts, total_sources)
    
    # Process accounts in batches for better progress reporting
    batch_size = max_concurrent_accounts
    all_index_data = []
    
    try:
        for batch_start in range(0, total_accounts, batch_size):
            batch_end = min(batch_start + batch_size, total_accounts)
            batch = accounts_list[batch_start:batch_end]
            
            # Create tasks for this batch
            tasks = [
                process_account_async(acc, accounts_base, output_base, llm_semaphore, client)
                for acc in batch
            ]
            
            # Run batch in parallel
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Aggregate results
            for result in results:
                if isinstance(result, Exception):
                    stats["accounts_failed"] += 1
                    stats["errors"].append(str(result))
                    if progress:
                        progress.update_account("ERROR", 0, 0, 0)
                elif result["success"]:
                    stats["accounts_processed"] += 1
                    stats["total_emails"] += result["emails"]
                    stats["total_calls"] += result["calls"]
                    stats["total_sms"] += result["sms"]
                    if result["index_data"]:
                        all_index_data.append(result["index_data"])
                    if progress:
                        progress.update_account(
                            result["account_name"],
                            result["emails"],
                            result["calls"],
                            result["sms"]
                        )
                else:
                    stats["accounts_failed"] += 1
                    if result["error"]:
                        stats["errors"].append(f"Account {result['account_id']}: {result['error']}")
                    if progress:
                        progress.update_account(result.get("account_name", "ERROR"), 0, 0, 0)
        
        # Batch index all accounts in Qdrant
        if all_index_data:
            if progress:
                tqdm.write("\nIndexing accounts in Qdrant...")
            try:
                registry = NameRegistry()
                
                # Batch upsert names
                name_data = [{"account_id": d["account_id"], "name": d["name"], "directory_path": d["directory_path"]} 
                             for d in all_index_data]
                registry.upsert_accounts_batch(name_data)
                
                # Batch upsert descriptions
                registry.upsert_descriptions_batch(all_index_data)
                
                stats["accounts_indexed"] = len(all_index_data)
                
            except Exception as e:
                if progress:
                    tqdm.write(f"Warning: Failed to batch index accounts in Qdrant: {e}")
                else:
                    logger.warning(f"Failed to batch index accounts in Qdrant: {e}")
    
    finally:
        if progress:
            stats["timing"] = progress.get_summary()
            progress.close()
    
    return stats


def ingest_accounts(
    input_file: str, 
    output_base: str = "mem", 
    parallel: bool = True, 
    max_workers: int = 5,
    show_progress: bool = True
) -> dict:
    """
    Main orchestration function for the ingestion pipeline.
    
    Args:
        input_file: Path to the accounts.jsonl file
        output_base: Base output directory (default: "mem")
        parallel: Use parallel async processing (default: True)
        max_workers: Max concurrent accounts when parallel=True
        show_progress: Show progress bars and time estimation
        
    Returns:
        dict with statistics about the ingestion
    """
    # Count total accounts first for progress reporting
    logger.info(f"Reading accounts from {input_file}...")
    accounts_list = list(parse_accounts_jsonl(input_file))
    total_accounts = len(accounts_list)
    total_sources = count_sources(accounts_list)
    logger.info(f"Found {total_accounts} accounts with {total_sources} total sources")
    
    if parallel and total_accounts > 1:
        logger.info(f"Using PARALLEL processing with {max_workers} concurrent accounts")
        logger.info(f"Max concurrent LLM calls: {MAX_CONCURRENT_LLM_CALLS}")
        return asyncio.run(ingest_accounts_async(accounts_list, output_base, max_workers, show_progress))
    
    # Fallback to sequential processing
    logger.info("Using SEQUENTIAL processing")
    return ingest_accounts_sequential(input_file, output_base, show_progress)


def ingest_accounts_sequential(input_file: str, output_base: str = "mem", show_progress: bool = True) -> dict:
    """
    Original sequential ingestion (kept for backwards compatibility).
    """
    stats = {
        "accounts_processed": 0,
        "accounts_failed": 0,
        "total_emails": 0,
        "total_calls": 0,
        "total_sms": 0,
        "accounts_indexed": 0,
        "errors": [],
        "timing": {}
    }
    
    accounts_base = Path(output_base) / "accounts"
    
    # Initialize name registry for Qdrant indexing
    registry = None
    try:
        registry = NameRegistry()
        logger.info("Connected to Qdrant name registry")
    except Exception as e:
        logger.warning(f"Could not connect to Qdrant (run 'docker compose up -d'): {e}")
        logger.warning("Proceeding without name registry indexing")
    
    accounts_list = list(parse_accounts_jsonl(input_file))
    total_accounts = len(accounts_list)
    total_sources = count_sources(accounts_list)
    
    # Initialize progress tracker
    progress = None
    if show_progress:
        print()  # New line before progress bars
        progress = IngestionProgress(total_accounts, total_sources)
    
    try:
        for idx, account_data in enumerate(accounts_list, start=1):
            account_id = account_data.get("account_id")
            account_name = account_data.get("account_name", "Unknown")
            
            if not account_id:
                if progress:
                    progress.update_account("SKIPPED", 0, 0, 0)
                stats["accounts_failed"] += 1
                stats["errors"].append(f"Missing account_id at index {idx}")
                continue
            
            try:
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
                        if progress:
                            tqdm.write(f"Warning: Failed to index account {account_id} in Qdrant: {e}")
                        else:
                            logger.warning(f"Failed to index account {account_id} in Qdrant: {e}")
                
                # Update stats
                stats["accounts_processed"] += 1
                stats["total_emails"] += counts["emails"]
                stats["total_calls"] += counts["calls"]
                stats["total_sms"] += counts["sms"]
                
                if progress:
                    progress.update_account(account_name, counts["emails"], counts["calls"], counts["sms"])
                
            except Exception as e:
                if progress:
                    tqdm.write(f"Error: Failed to process account {account_id}: {e}")
                    progress.update_account("ERROR", 0, 0, 0)
                else:
                    logger.error(f"Failed to process account {account_id}: {e}")
                stats["accounts_failed"] += 1
                stats["errors"].append(f"Account {account_id}: {str(e)}")
    
    finally:
        if progress:
            stats["timing"] = progress.get_summary()
            progress.close()
    
    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ingest accounts.jsonl into mem/ directory structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python ingest.py --input accounts.jsonl --output mem
    python ingest.py --input accounts.jsonl --parallel --workers 8
    python ingest.py --input accounts.jsonl --sequential
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
        "--parallel", "-p",
        action="store_true",
        default=True,
        help="Use parallel async processing (default: enabled)"
    )
    parser.add_argument(
        "--sequential", "-s",
        action="store_true",
        help="Use sequential processing (disables parallel)"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=5,
        help="Number of concurrent accounts to process (default: 5)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars (useful for CI/logging)"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clear Qdrant collections before ingesting (removes stale references)"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Sequential flag overrides parallel
    use_parallel = args.parallel and not args.sequential
    show_progress = not args.no_progress
    
    logger.info("=" * 60)
    logger.info("Ingestion Pipeline for Experiment 1")
    logger.info("=" * 60)
    logger.info(f"Input: {args.input}")
    logger.info(f"Output: {args.output}")
    logger.info(f"Mode: {'PARALLEL' if use_parallel else 'SEQUENTIAL'}")
    if use_parallel:
        logger.info(f"Workers: {args.workers}")
        logger.info(f"Max concurrent LLM calls: {MAX_CONCURRENT_LLM_CALLS}")
    if args.clean:
        logger.info("Clean mode: Will clear Qdrant before ingesting")
    logger.info("")
    
    # Clear Qdrant if --clean flag is set
    if args.clean:
        try:
            registry = NameRegistry()
            registry.clear_all()
            logger.info("Qdrant collections cleared successfully")
        except Exception as e:
            logger.warning(f"Could not clear Qdrant (run 'docker compose up -d'): {e}")
            logger.warning("Proceeding without clearing - stale references may remain")
    
    try:
        stats = ingest_accounts(args.input, args.output, parallel=use_parallel, max_workers=args.workers, show_progress=show_progress)
        
        # Print summary
        print()
        print("=" * 60)
        print("INGESTION COMPLETE")
        print("=" * 60)
        print()
        
        # Timing stats
        timing = stats.get("timing", {})
        if timing:
            print(f"  Total time:          {timing.get('elapsed_formatted', 'N/A')}")
            print(f"  Accounts/second:     {timing.get('accounts_per_second', 0):.2f}")
            print(f"  Sources/second:      {timing.get('sources_per_second', 0):.2f}")
            print()
        
        # Processing stats
        print(f"  Accounts processed:  {stats['accounts_processed']}")
        print(f"  Accounts failed:     {stats['accounts_failed']}")
        print()
        print(f"  Emails written:      {stats['total_emails']}")
        print(f"  Calls written:       {stats['total_calls']}")
        print(f"  SMS written:         {stats['total_sms']}")
        print(f"  Total sources:       {stats['total_emails'] + stats['total_calls'] + stats['total_sms']}")
        print()
        print(f"  Indexed in Qdrant:   {stats['accounts_indexed']}")
        print()
        print("=" * 60)
        
        if stats["errors"]:
            print(f"\nErrors encountered ({len(stats['errors'])}):")
            for error in stats["errors"][:10]:  # Show first 10 errors
                print(f"  - {error}")
            if len(stats["errors"]) > 10:
                print(f"  ... and {len(stats['errors']) - 10} more")
        
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
