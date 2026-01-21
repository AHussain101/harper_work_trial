#!/usr/bin/env python3
"""
Updater Agent: Handles updates to account state and maintains history chain.

Responsibilities:
1. Parse update requests to extract field changes
2. Update state.md with new values
3. Append to history.md with linked entries (history chain)
4. Regenerate and update description vector in Qdrant
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import anthropic
from dotenv import load_dotenv

from name_registry import NameRegistry

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class StateChange:
    """Represents a single field change."""
    field: str
    old_value: Any
    new_value: Any


@dataclass
class UpdateResult:
    """Result of an update operation."""
    success: bool
    message: str
    changes: list[StateChange] = field(default_factory=list)
    history_entry_id: Optional[str] = None
    error: Optional[str] = None
    # Rich details for UI
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    files_modified: list[str] = field(default_factory=list)
    qdrant_updated: bool = False
    new_description: Optional[str] = None
    state_file_path: Optional[str] = None
    history_file_path: Optional[str] = None
    previous_history_entry: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "message": self.message,
            "changes": [
                {"field": c.field, "old_value": str(c.old_value), "new_value": str(c.new_value)}
                for c in self.changes
            ],
            "history_entry_id": self.history_entry_id,
            "error": self.error,
            # Rich details
            "account_id": self.account_id,
            "account_name": self.account_name,
            "files_modified": self.files_modified,
            "qdrant_updated": self.qdrant_updated,
            "new_description": self.new_description,
            "state_file_path": self.state_file_path,
            "history_file_path": self.history_file_path,
            "previous_history_entry": self.previous_history_entry,
        }


class UpdaterAgent:
    """
    Handles updates to account state and maintains history chain.
    
    Workflow:
    1. Parse update request using Claude to extract intent
    2. Read current state.md
    3. Apply changes to state.md
    4. Append linked entry to history.md
    5. Regenerate description in Qdrant
    """
    
    def __init__(
        self,
        mem_path: str = "mem",
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001"
    ):
        self.mem_path = Path(mem_path)
        self.model = model
        
        # Initialize Anthropic client
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found")
        self.client = anthropic.Anthropic(api_key=api_key)
        
        # Initialize name registry for Qdrant updates
        self._name_registry: Optional[NameRegistry] = None
        try:
            self._name_registry = NameRegistry()
            logger.info("Updater Agent connected to Qdrant")
        except Exception as e:
            logger.warning(f"Could not connect to Qdrant: {e}")
    
    def parse_update_request(self, query: str, current_state: dict) -> dict:
        """
        Use Claude to parse the update request and extract field changes.
        
        Args:
            query: User's update command
            current_state: Current state.md parsed as dict
            
        Returns:
            dict with fields to update and their new values
        """
        current_state_str = json.dumps(current_state, indent=2)
        
        prompt = f"""Parse this update command for an insurance account.

Update Command: "{query}"

Current Account State:
{current_state_str}

Extract the updates to apply. Respond with a JSON object containing:
1. "updates": Object mapping field names to new values
2. "summary": Brief summary of what's being changed
3. "note": Any additional note to add (if the command includes a note)

Available fields to update:
- stage: The pipeline stage (e.g., "New Lead", "Application Received", "Quoted", "Bound", "Closed Lost")
- insurance_types: List of insurance types
- primary_email: Contact email
- primary_phone: Contact phone
- next_steps: List of next action items
- pending_actions: List of pending items
- custom_note: Free-form note to append

Examples:
- "Mark as Quoted" → {{"updates": {{"stage": "Quoted"}}, "summary": "Stage updated to Quoted", "note": null}}
- "Add note: Client prefers email contact" → {{"updates": {{}}, "summary": "Note added", "note": "Client prefers email contact"}}
- "Stage is Application Received, add Workers Comp" → {{"updates": {{"stage": "Application Received", "insurance_types": ["Workers' Compensation"]}}, "summary": "Updated stage and insurance types", "note": null}}

Respond with ONLY the JSON object, no other text."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text.strip()
            
            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
                
        except Exception as e:
            logger.error(f"Failed to parse update request: {e}")
        
        return {"updates": {}, "summary": "Could not parse update", "note": None}
    
    def parse_state_md(self, state_path: Path) -> dict:
        """
        Parse state.md into a structured dictionary.
        
        Args:
            state_path: Path to state.md
            
        Returns:
            dict with parsed state values
        """
        if not state_path.exists():
            return {}
        
        content = state_path.read_text(encoding='utf-8')
        state = {"raw_content": content}
        
        # Parse title/account name
        title_match = re.search(r'^# (.+?) \(Account (\d+)\)', content, re.MULTILINE)
        if title_match:
            state["account_name"] = title_match.group(1)
            state["account_id"] = title_match.group(2)
        
        # Parse stage
        stage_match = re.search(r'\*\*Stage\*\*:\s*(.+)', content)
        if stage_match:
            state["stage"] = stage_match.group(1).strip()
        
        # Parse insurance types
        insurance_match = re.search(r'\*\*Insurance Types\*\*:\s*(.+)', content)
        if insurance_match:
            types_str = insurance_match.group(1).strip()
            if types_str and types_str != "None":
                state["insurance_types"] = [t.strip() for t in types_str.split(",")]
            else:
                state["insurance_types"] = []
        
        # Parse contacts
        email_match = re.search(r'\*\*Primary Email\*\*:\s*(.+)', content)
        if email_match:
            state["primary_email"] = email_match.group(1).strip()
        
        phone_match = re.search(r'\*\*Primary Phone\*\*:\s*(.+)', content)
        if phone_match:
            state["primary_phone"] = phone_match.group(1).strip()
        
        # Parse next steps
        next_steps_section = re.search(r'## Next Steps\n((?:- .+\n?)+)', content)
        if next_steps_section:
            steps = re.findall(r'- (.+)', next_steps_section.group(1))
            state["next_steps"] = steps
        
        # Parse pending actions
        pending_section = re.search(r'## Pending Actions\n((?:- .+\n?)+)', content)
        if pending_section:
            pending = re.findall(r'- (.+)', pending_section.group(1))
            state["pending_actions"] = pending
        
        # Parse last contact
        date_match = re.search(r'\*\*Date\*\*:\s*(.+)', content)
        if date_match:
            state["last_contact_date"] = date_match.group(1).strip()
        
        type_match = re.search(r'\*\*Type\*\*:\s*(.+)', content)
        if type_match:
            state["last_contact_type"] = type_match.group(1).strip()
        
        return state
    
    def write_state_md(self, state_path: Path, state: dict) -> None:
        """
        Write updated state back to state.md.
        
        Args:
            state_path: Path to state.md
            state: Updated state dictionary
        """
        account_name = state.get("account_name", "Unknown")
        account_id = state.get("account_id", "0")
        stage = state.get("stage", "Unknown")
        insurance_types = state.get("insurance_types", [])
        primary_email = state.get("primary_email", "")
        primary_phone = state.get("primary_phone", "")
        next_steps = state.get("next_steps", ["None identified"])
        pending_actions = state.get("pending_actions", ["None identified"])
        last_contact_date = state.get("last_contact_date", "Unknown")
        last_contact_type = state.get("last_contact_type", "Unknown")
        
        insurance_str = ", ".join(insurance_types) if insurance_types else "None"
        next_steps_str = "\n".join([f"- {s}" for s in next_steps]) if next_steps else "- None identified"
        pending_str = "\n".join([f"- {p}" for p in pending_actions]) if pending_actions else "- None identified"
        
        content = f"""# {account_name} (Account {account_id})

## Status
- **Stage**: {stage}
- **Insurance Types**: {insurance_str}

## Contacts
- **Primary Email**: {primary_email}
- **Primary Phone**: {primary_phone}

## Next Steps
{next_steps_str}

## Pending Actions
{pending_str}

## Last Contact
- **Date**: {last_contact_date}
- **Type**: {last_contact_type}
"""
        
        state_path.write_text(content, encoding='utf-8')
        logger.info(f"Updated state.md for account {account_id}")
    
    def get_last_history_entry_id(self, history_path: Path) -> Optional[str]:
        """
        Get the ID (timestamp) of the last history entry for linking.
        
        Args:
            history_path: Path to history.md
            
        Returns:
            Timestamp string of last entry, or None if no entries
        """
        if not history_path.exists():
            return None
        
        content = history_path.read_text(encoding='utf-8')
        
        # Find all timestamp headers
        timestamps = re.findall(r'^## (\d{4}-\d{2}-\d{2}T[\d:]+(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)', content, re.MULTILINE)
        
        if timestamps:
            return timestamps[-1]  # Return the last one
        
        return None
    
    def append_history_entry(
        self,
        history_path: Path,
        changes: list[StateChange],
        summary: str,
        evidence: str,
        note: Optional[str] = None
    ) -> str:
        """
        Append a new entry to history.md with link to previous entry.
        
        Args:
            history_path: Path to history.md
            changes: List of field changes
            summary: LLM-generated or provided summary
            evidence: What triggered this change (user command, etc.)
            note: Optional additional note
            
        Returns:
            Timestamp ID of the new entry
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        # Get previous entry for linking
        previous_id = self.get_last_history_entry_id(history_path)
        
        # Build changes list
        changes_text = ""
        for change in changes:
            changes_text += f"- **{change.field}**: {change.old_value} → {change.new_value}\n"
        
        if note:
            changes_text += f"- **Note**: {note}\n"
        
        # Build previous link
        previous_link = ""
        if previous_id:
            # Create anchor-compatible ID (lowercase, replace special chars)
            anchor_id = previous_id.lower().replace(":", "").replace(".", "").replace("+", "")
            previous_link = f"- **Previous**: [{previous_id}](#{anchor_id})\n"
        
        entry = f"""## {timestamp}

{summary}

{changes_text}- **Evidence**: {evidence}
{previous_link}
---

"""
        
        # Create file with header if doesn't exist
        if not history_path.exists():
            history_path.write_text("# Change History\n\n", encoding='utf-8')
        
        # Append entry
        with open(history_path, 'a', encoding='utf-8') as f:
            f.write(entry)
        
        logger.info(f"Appended history entry at {timestamp}")
        return timestamp
    
    def generate_description(self, state: dict) -> str:
        """
        Generate a searchable description from account state.
        
        Args:
            state: Current account state dict
            
        Returns:
            Description string for Qdrant indexing
        """
        account_name = state.get("account_name", "Unknown")
        stage = state.get("stage", "Unknown")
        insurance_types = state.get("insurance_types", [])
        next_steps = state.get("next_steps", [])
        pending_actions = state.get("pending_actions", [])
        
        insurance_str = ", ".join(insurance_types) if insurance_types else "None"
        
        # Build description
        parts = [
            account_name,
            f"Stage: {stage}",
            f"Insurance: {insurance_str}"
        ]
        
        if next_steps and next_steps[0] != "None identified":
            parts.append(f"Next: {next_steps[0]}")
        
        if pending_actions and pending_actions[0] != "None identified":
            parts.append(f"Pending: {pending_actions[0]}")
        
        return " | ".join(parts)
    
    def update_qdrant_description(
        self,
        account_id: str,
        account_name: str,
        description: str,
        directory_path: str
    ) -> bool:
        """
        Update the account description in Qdrant.
        
        Args:
            account_id: Account ID
            account_name: Account name
            description: New description
            directory_path: Path to account directory
            
        Returns:
            True if successful
        """
        if not self._name_registry:
            logger.warning("Qdrant not available, skipping description update")
            return False
        
        try:
            self._name_registry.upsert_description(
                account_id=account_id,
                name=account_name,
                description=description,
                directory_path=directory_path
            )
            logger.info(f"Updated Qdrant description for account {account_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update Qdrant description: {e}")
            return False
    
    def process_update(
        self,
        query: str,
        account_id: str,
        account_name: str,
        account_path: str
    ) -> dict:
        """
        Main entry point: process an update request.
        
        Args:
            query: User's update command
            account_id: Target account ID
            account_name: Target account name
            account_path: Path to account directory
            
        Returns:
            UpdateResult as dict
        """
        logger.info(f"Updater Agent processing: {query} for account {account_id}")
        
        account_dir = Path(account_path)
        state_path = account_dir / "state.md"
        history_path = account_dir / "history.md"
        
        # Step 1: Read current state
        if not state_path.exists():
            return UpdateResult(
                success=False,
                message=f"Account state not found at {state_path}",
                error="state_not_found"
            ).to_dict()
        
        current_state = self.parse_state_md(state_path)
        
        # Step 2: Parse update request
        parsed = self.parse_update_request(query, current_state)
        updates = parsed.get("updates", {})
        summary = parsed.get("summary", "Update applied")
        note = parsed.get("note")
        
        if not updates and not note:
            return UpdateResult(
                success=False,
                message="Could not understand the update request. Please specify what to change.",
                error="no_updates_parsed"
            ).to_dict()
        
        # Step 3: Apply updates and track changes
        changes: list[StateChange] = []
        new_state = current_state.copy()
        
        for field_name, new_value in updates.items():
            old_value = current_state.get(field_name, "Not set")
            
            # Handle list fields
            if field_name == "insurance_types":
                if isinstance(new_value, str):
                    new_value = [new_value]
                # Merge with existing
                existing = current_state.get("insurance_types", [])
                if isinstance(existing, list):
                    # Add new types, avoid duplicates
                    merged = list(existing)
                    for t in new_value:
                        if t not in merged:
                            merged.append(t)
                    new_value = merged
            
            new_state[field_name] = new_value
            changes.append(StateChange(
                field=field_name,
                old_value=old_value,
                new_value=new_value
            ))
        
        # Handle note as a special update
        if note:
            changes.append(StateChange(
                field="note",
                old_value="",
                new_value=note
            ))
        
        # Step 4: Write updated state.md
        try:
            self.write_state_md(state_path, new_state)
        except Exception as e:
            return UpdateResult(
                success=False,
                message=f"Failed to write state: {e}",
                error="write_failed"
            ).to_dict()
        
        # Track files modified
        files_modified = [str(state_path)]
        
        # Step 5: Get previous history entry before appending
        previous_history_entry = self.get_last_history_entry_id(history_path)
        
        # Step 6: Append to history.md
        history_entry_id = None
        try:
            history_entry_id = self.append_history_entry(
                history_path=history_path,
                changes=changes,
                summary=summary,
                evidence=f"User command: \"{query}\"",
                note=note
            )
            files_modified.append(str(history_path))
        except Exception as e:
            logger.warning(f"Failed to write history: {e}")
        
        # Step 7: Update Qdrant description
        description = self.generate_description(new_state)
        directory_path = f"{self.mem_path}/accounts/{account_id}"
        qdrant_updated = self.update_qdrant_description(
            account_id=account_id,
            account_name=account_name,
            description=description,
            directory_path=directory_path
        )
        
        # Build success message
        changes_summary = ", ".join([f"{c.field}: {c.new_value}" for c in changes])
        
        return UpdateResult(
            success=True,
            message=f"Updated {account_name}: {changes_summary}",
            changes=changes,
            history_entry_id=history_entry_id,
            # Rich details
            account_id=account_id,
            account_name=account_name,
            files_modified=files_modified,
            qdrant_updated=qdrant_updated,
            new_description=description,
            state_file_path=str(state_path),
            history_file_path=str(history_path),
            previous_history_entry=previous_history_entry,
        ).to_dict()


def main():
    """CLI for testing the updater agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test the Updater Agent")
    parser.add_argument("query", help="Update command to process")
    parser.add_argument("--account-id", required=True, help="Account ID to update")
    parser.add_argument("--account-name", default="Test Account", help="Account name")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    agent = UpdaterAgent()
    
    account_path = f"mem/accounts/{args.account_id}"
    
    result = agent.process_update(
        query=args.query,
        account_id=args.account_id,
        account_name=args.account_name,
        account_path=account_path
    )
    
    print(f"\nResult: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
