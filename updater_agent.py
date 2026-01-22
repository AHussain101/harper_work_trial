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
    # Clarification fields for vague updates
    needs_clarification: bool = False
    clarification_fields: list[dict] = field(default_factory=list)
    original_query: Optional[str] = None
    
    def to_dict(self) -> dict:
        result = {
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
        # Include clarification fields if needed
        if self.needs_clarification:
            result["needs_clarification"] = True
            result["clarification_fields"] = self.clarification_fields
            result["original_query"] = self.original_query
        return result


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
        skills_path: str = "skills",
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001"
    ):
        self.mem_path = Path(mem_path)
        self.skills_path = Path(skills_path)
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
        
        # Cache for discovered skills
        self._available_skills: Optional[list[dict]] = None
    
    def _parse_skill_frontmatter(self, content: str) -> tuple[dict, str]:
        """
        Parse YAML frontmatter from a SKILL.md file.
        
        Returns:
            Tuple of (metadata dict, body content)
        """
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                try:
                    # Simple parser for basic key: value pairs
                    metadata = {}
                    for line in parts[1].strip().split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            metadata[key.strip()] = value.strip()
                    body = parts[2].strip()
                    return metadata or {}, body
                except Exception as e:
                    logger.warning(f"Failed to parse YAML frontmatter: {e}")
        return {}, content
    
    def _discover_skills(self, category: str = "update") -> list[dict]:
        """
        Discover available skills in a category (Level 1 - metadata only).
        
        Args:
            category: Skill category folder (e.g., "update")
            
        Returns:
            List of skill metadata dicts with name, description, and path
        """
        if self._available_skills is not None:
            return self._available_skills
        
        skills = []
        skills_dir = self.skills_path / category
        
        if not skills_dir.exists():
            logger.warning(f"Skills directory not found: {skills_dir}")
            return skills
        
        for skill_folder in sorted(skills_dir.iterdir()):
            if not skill_folder.is_dir():
                continue
            
            skill_md = skill_folder / "SKILL.md"
            if skill_md.exists():
                try:
                    content = skill_md.read_text(encoding='utf-8')
                    metadata, _ = self._parse_skill_frontmatter(content)
                    
                    skills.append({
                        "name": metadata.get("name", skill_folder.name),
                        "description": metadata.get("description", ""),
                        "path": str(skill_md)
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse skill {skill_folder.name}: {e}")
        
        self._available_skills = skills
        logger.info(f"Discovered {len(skills)} skills in category '{category}'")
        return skills
    
    def _build_skills_xml(self, skills: list[dict]) -> str:
        """
        Build XML representation of available skills for prompt injection.
        
        Args:
            skills: List of skill metadata dicts
            
        Returns:
            XML string for available_skills
        """
        if not skills:
            return ""
        
        lines = ["<available_skills>"]
        for skill in skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{skill['name']}</name>")
            desc = skill.get('description', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{skill['path']}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        
        return "\n".join(lines)
    
    def activate_skill(self, skill_name: str) -> str:
        """
        Activate a skill by loading its full SKILL.md content.
        
        This is Level 2 of progressive disclosure - loading full instructions
        when needed.
        
        Args:
            skill_name: Name of the skill to activate
            
        Returns:
            Full SKILL.md content (body without frontmatter)
        """
        skill_path = self.skills_path / "update" / skill_name / "SKILL.md"
        
        if not skill_path.exists():
            return f"Skill not found: {skill_name}"
        
        content = skill_path.read_text(encoding='utf-8')
        _, body = self._parse_skill_frontmatter(content)
        
        logger.info(f"Activated skill: {skill_name}")
        return body
    
    def get_available_skills_info(self) -> str:
        """
        Get available skills as XML for context injection.
        
        Returns:
            XML string of available skills
        """
        skills = self._discover_skills("update")
        return self._build_skills_xml(skills)
    
    def parse_update_request(self, query: str, current_state: dict) -> dict:
        """
        Use Claude to parse the update request and extract field changes.
        
        Args:
            query: User's update command
            current_state: Current state.md parsed as dict
            
        Returns:
            dict with fields to update and their new values, or clarification request
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
4. "is_vague": Boolean - true if the command is too vague to execute (e.g., just "update", "change something", "make changes")
5. "missing_info": If is_vague is true, list what specific information is needed

Available fields to update:
- stage: The pipeline stage (e.g., "New Lead", "Application Received", "Quoted", "Bound", "Closed Lost")
- insurance_types: List of insurance types
- primary_email: Contact email
- primary_phone: Contact phone
- next_steps: List of next action items
- pending_actions: List of pending items
- custom_note: Free-form note to append

Examples:
- "Mark as Quoted" → {{"updates": {{"stage": "Quoted"}}, "summary": "Stage updated to Quoted", "note": null, "is_vague": false, "missing_info": null}}
- "Add note: Client prefers email contact" → {{"updates": {{}}, "summary": "Note added", "note": "Client prefers email contact", "is_vague": false, "missing_info": null}}
- "Stage is Application Received, add Workers Comp" → {{"updates": {{"stage": "Application Received", "insurance_types": ["Workers' Compensation"]}}, "summary": "Updated stage and insurance types", "note": null, "is_vague": false, "missing_info": null}}
- "Update this account" → {{"updates": {{}}, "summary": null, "note": null, "is_vague": true, "missing_info": ["What field do you want to update?", "What value should it be changed to?"]}}
- "Change the status" → {{"updates": {{}}, "summary": null, "note": null, "is_vague": true, "missing_info": ["What status should it be changed to? (e.g., Quoted, Bound, Application Received)"]}}
- "Make some updates" → {{"updates": {{}}, "summary": null, "note": null, "is_vague": true, "missing_info": ["What specific changes would you like to make?"]}}

Respond with ONLY the JSON object, no other text."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text.strip()
            logger.info(f"Parse update response: {content[:200]}")
            
            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                logger.info(f"Parsed updates: {parsed}")
                return parsed
            else:
                logger.warning(f"No JSON found in response: {content}")
                
        except Exception as e:
            logger.error(f"Failed to parse update request: {e}")
        
        return {"updates": {}, "summary": "Could not parse update", "note": None, "is_vague": True, "missing_info": ["Could not understand the update request. Please specify what you want to change."]}
    
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
        is_vague = parsed.get("is_vague", False)
        missing_info = parsed.get("missing_info", [])
        
        # Handle vague updates - request clarification
        if is_vague or (not updates and not note and missing_info):
            logger.info(f"Vague update detected, requesting clarification: {missing_info}")
            
            # Build clarification fields with form structure
            clarification_fields = [
                {
                    "id": "stage",
                    "label": "Pipeline Stage",
                    "type": "select",
                    "options": ["New Lead", "Application Received", "Quoted", "Bound", "Closed Won", "Closed Lost"],
                    "placeholder": "Select a stage...",
                    "current_value": current_state.get("stage", "")
                },
                {
                    "id": "insurance_types",
                    "label": "Insurance Types",
                    "type": "multi-select",
                    "options": ["Workers' Compensation", "General Liability", "Commercial Auto", "Property", "Professional Liability", "Cyber Liability"],
                    "placeholder": "Select insurance types...",
                    "current_value": current_state.get("insurance_types", [])
                },
                {
                    "id": "next_step",
                    "label": "Next Step",
                    "type": "text",
                    "placeholder": "What's the next action item?",
                    "current_value": current_state.get("next_steps", [""])[0] if current_state.get("next_steps") else ""
                },
                {
                    "id": "note",
                    "label": "Add a Note",
                    "type": "textarea",
                    "placeholder": "Add any notes about this account...",
                    "current_value": ""
                }
            ]
            
            return UpdateResult(
                success=False,
                message="I need more details to complete this update. Please specify what you'd like to change.",
                needs_clarification=True,
                clarification_fields=clarification_fields,
                original_query=query,
                account_id=account_id,
                account_name=account_name,
                error="vague_update"
            ).to_dict()
        
        if not updates and not note:
            # Check if requested update already matches current state
            # This is a success case - nothing to change
            return UpdateResult(
                success=True,
                message=f"Account already up to date. {summary}",
                account_id=account_id,
                account_name=account_name
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


    def process_clarified_update(
        self,
        account_id: str,
        account_name: str,
        account_path: str,
        clarification_data: dict
    ) -> dict:
        """
        Process an update with clarification data from the UI.
        
        Args:
            account_id: Target account ID
            account_name: Target account name
            account_path: Path to account directory
            clarification_data: Dict with field values from UI form:
                - stage: Pipeline stage
                - insurance_types: List of insurance types
                - next_step: Next action item
                - note: Additional note
            
        Returns:
            UpdateResult as dict
        """
        logger.info(f"Processing clarified update for account {account_id}: {clarification_data}")
        
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
        
        # Step 2: Build updates from clarification data
        updates = {}
        note = None
        
        if clarification_data.get("stage") and clarification_data["stage"] != current_state.get("stage"):
            updates["stage"] = clarification_data["stage"]
        
        if clarification_data.get("insurance_types"):
            new_types = clarification_data["insurance_types"]
            if isinstance(new_types, str):
                new_types = [new_types]
            if new_types != current_state.get("insurance_types", []):
                updates["insurance_types"] = new_types
        
        if clarification_data.get("next_step"):
            current_steps = current_state.get("next_steps", [])
            new_step = clarification_data["next_step"]
            if new_step and (not current_steps or new_step != current_steps[0]):
                updates["next_steps"] = [new_step] + [s for s in current_steps if s != new_step][:2]
        
        if clarification_data.get("note"):
            note = clarification_data["note"]
        
        if not updates and not note:
            return UpdateResult(
                success=True,
                message="No changes were specified.",
                account_id=account_id,
                account_name=account_name
            ).to_dict()
        
        # Step 3: Apply updates and track changes
        changes: list[StateChange] = []
        new_state = current_state.copy()
        
        for field_name, new_value in updates.items():
            old_value = current_state.get(field_name, "Not set")
            new_state[field_name] = new_value
            changes.append(StateChange(
                field=field_name,
                old_value=old_value,
                new_value=new_value
            ))
        
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
        
        files_modified = [str(state_path)]
        
        # Step 5: Get previous history entry before appending
        previous_history_entry = self.get_last_history_entry_id(history_path)
        
        # Step 6: Build summary
        summary_parts = []
        if "stage" in updates:
            summary_parts.append(f"Stage changed to {updates['stage']}")
        if "insurance_types" in updates:
            summary_parts.append(f"Insurance types updated")
        if "next_steps" in updates:
            summary_parts.append(f"Next step added")
        if note:
            summary_parts.append("Note added")
        summary = ". ".join(summary_parts) if summary_parts else "Account updated"
        
        # Step 7: Append to history.md
        history_entry_id = None
        try:
            history_entry_id = self.append_history_entry(
                history_path=history_path,
                changes=changes,
                summary=summary,
                evidence="User form submission (clarified update)",
                note=note
            )
            files_modified.append(str(history_path))
        except Exception as e:
            logger.warning(f"Failed to write history: {e}")
        
        # Step 8: Update Qdrant description
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
            account_id=account_id,
            account_name=account_name,
            files_modified=files_modified,
            qdrant_updated=qdrant_updated,
            new_description=description,
            state_file_path=str(state_path),
            history_file_path=str(history_path),
            previous_history_entry=previous_history_entry,
        ).to_dict()

    def _generate_account_id(self) -> str:
        """Generate a new unique account ID."""
        accounts_dir = self.mem_path / "accounts"
        
        if not accounts_dir.exists():
            accounts_dir.mkdir(parents=True)
            return "10001"
        
        # Find highest existing ID and increment
        existing_ids = []
        for path in accounts_dir.iterdir():
            if path.is_dir() and path.name.isdigit():
                existing_ids.append(int(path.name))
        
        if existing_ids:
            return str(max(existing_ids) + 1)
        else:
            return "10001"

    def create_account(
        self,
        account_name: str,
        account_id: Optional[str] = None,
        account_details: Optional[dict] = None
    ) -> dict:
        """
        Create a new account folder structure (account-create skill).
        
        Args:
            account_name: Company name for the new account
            account_id: Optional specific ID, otherwise auto-generated
            account_details: Optional dict with additional account info:
                - industry: Company's industry
                - location: Company location
                - primary_email: Primary contact email
                - primary_phone: Primary contact phone
                - insurance_types: List of insurance types interested in
                - notes: Additional notes about the account
            
        Returns:
            dict with account_id, path, success status, and rich details
        """
        logger.info(f"Creating new account: {account_name}")
        
        # Generate account ID if not provided
        if account_id is None:
            account_id = self._generate_account_id()
        
        account_dir = self.mem_path / "accounts" / str(account_id)
        sources_dir = account_dir / "sources"
        state_path = account_dir / "state.md"
        history_path = account_dir / "history.md"
        
        # Extract details with defaults
        details = account_details or {}
        industry = details.get("industry", "")
        location = details.get("location", "")
        primary_email = details.get("primary_email", "")
        primary_phone = details.get("primary_phone", "")
        insurance_types = details.get("insurance_types", [])
        notes = details.get("notes", "")
        
        # Format insurance types
        insurance_str = ", ".join(insurance_types) if insurance_types else "None"
        
        try:
            # Create directory structure
            for subdir in ["emails", "calls", "sms"]:
                (sources_dir / subdir).mkdir(parents=True, exist_ok=True)
            
            # Create state.md with provided details
            timestamp = datetime.now().isoformat()
            state_content = f"""# {account_name} (Account {account_id})

## Status
- **Stage**: New Lead
- **Insurance Types**: {insurance_str}
"""
            
            # Add industry if provided
            if industry:
                state_content += f"- **Industry**: {industry}\n"
            
            # Add location if provided
            if location:
                state_content += f"- **Location**: {location}\n"
            
            state_content += """
## Contacts
"""
            state_content += f"- **Primary Email**: {primary_email}\n"
            state_content += f"- **Primary Phone**: {primary_phone}\n"
            
            state_content += """
## Next Steps
- Initial outreach needed

## Pending Actions
- None identified

## Last Contact
"""
            state_content += f"- **Date**: {timestamp[:10]}\n"
            state_content += "- **Type**: Account created\n"
            
            # Add notes section if notes were provided
            if notes:
                state_content += f"""
## Notes
{notes}
"""
            
            state_path.write_text(state_content, encoding='utf-8')
            
            # Create initial history.md
            history_details = f"Account created for {account_name}."
            if industry:
                history_details += f" Industry: {industry}."
            if location:
                history_details += f" Location: {location}."
            if insurance_types:
                history_details += f" Insurance interests: {insurance_str}."
            
            history_content = f"""# Change History

## {timestamp}

{history_details}

- **action**: Account initialized
- **Evidence**: User request

---

"""
            history_path.write_text(history_content, encoding='utf-8')
            
            files_modified = [str(state_path), str(history_path)]
            
            # Index in Qdrant
            qdrant_updated = False
            description = ""
            if self._name_registry:
                directory_path = f"{self.mem_path}/accounts/{account_id}"
                
                # Index by name
                self._name_registry.upsert_account(
                    account_id=str(account_id),
                    name=account_name,
                    directory_path=directory_path
                )
                
                # Build description with available details
                desc_parts = [f"{account_name}", "Stage: New Lead"]
                if industry:
                    desc_parts.append(f"Industry: {industry}")
                if location:
                    desc_parts.append(f"Location: {location}")
                if insurance_types:
                    desc_parts.append(f"Insurance: {insurance_str}")
                desc_parts.append("New account, initial outreach needed.")
                
                description = " | ".join(desc_parts)
                self._name_registry.upsert_description(
                    account_id=str(account_id),
                    name=account_name,
                    description=description,
                    directory_path=directory_path
                )
                qdrant_updated = True
                
                logger.info(f"Indexed new account {account_id} in Qdrant")
            
            logger.info(f"Created new account: {account_id} - {account_name}")
            
            # Build changes list for UI
            changes = [
                StateChange(field="account", old_value="", new_value=account_name),
                StateChange(field="stage", old_value="", new_value="New Lead"),
            ]
            if industry:
                changes.append(StateChange(field="industry", old_value="", new_value=industry))
            if location:
                changes.append(StateChange(field="location", old_value="", new_value=location))
            if insurance_types:
                changes.append(StateChange(field="insurance_types", old_value="", new_value=insurance_str))
            
            return UpdateResult(
                success=True,
                message=f"Created new account: {account_name} (ID: {account_id})",
                changes=changes,
                history_entry_id=timestamp,
                account_id=str(account_id),
                account_name=account_name,
                files_modified=files_modified,
                qdrant_updated=qdrant_updated,
                new_description=description,
                state_file_path=str(state_path),
                history_file_path=str(history_path),
            ).to_dict()
            
        except Exception as e:
            logger.error(f"Failed to create account: {e}")
            return UpdateResult(
                success=False,
                message=f"Failed to create account: {e}",
                error="create_failed"
            ).to_dict()


# =============================================================================
# AGENTIC LOOP IMPLEMENTATION
# =============================================================================

from agent_base import (
    BaseToolExecutor, BaseOrchestrator, Trace, ToolCall,
    discover_skills, build_skills_xml
)


class UpdaterToolExecutor(BaseToolExecutor):
    """
    Tool executor for Updater Agent.
    
    Provides tools for:
    - Reading files (skills, state, history)
    - Looking up accounts
    - Updating state fields
    - Managing history chain
    - Syncing Qdrant
    """
    
    def __init__(self, repo_root: str, mem_path: str = "mem"):
        super().__init__(repo_root)
        self.mem_path = Path(mem_path)
        self._updater_agent: Optional[UpdaterAgent] = None
    
    def _get_agent(self) -> UpdaterAgent:
        """Get or create the underlying UpdaterAgent."""
        if self._updater_agent is None:
            self._updater_agent = UpdaterAgent(mem_path=str(self.mem_path))
        return self._updater_agent
    
    def lookup_account(self, query: str, top_k: int = 5) -> list[dict]:
        """Look up account by name using semantic search."""
        agent = self._get_agent()
        if agent._name_registry is None:
            return [{"error": "Name registry not available"}]
        return agent._name_registry.search(query, top_k)
    
    def update_field(self, account_id: str, field: str, value: Any) -> dict:
        """Update a single field in state.md."""
        agent = self._get_agent()
        account_path = self.mem_path / "accounts" / account_id
        state_path = account_path / "state.md"
        
        if not state_path.exists():
            return {"success": False, "error": f"Account {account_id} not found"}
        
        # Read current state
        current_state = agent.parse_state_md(state_path)
        old_value = current_state.get(field, "Not set")
        
        # Handle list fields
        if field == "insurance_types" and isinstance(value, str):
            value = [value]
        
        # Apply update
        current_state[field] = value
        
        try:
            agent.write_state_md(state_path, current_state)
            return {
                "success": True,
                "field": field,
                "old_value": str(old_value),
                "new_value": str(value),
                "account_id": account_id
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def add_note(self, account_id: str, note: str) -> dict:
        """Add a note to the account (recorded in history)."""
        agent = self._get_agent()
        account_path = self.mem_path / "accounts" / account_id
        history_path = account_path / "history.md"
        
        try:
            timestamp = agent.append_history_entry(
                history_path=history_path,
                changes=[StateChange(field="note", old_value="", new_value=note)],
                summary=f"Note added",
                evidence="User request",
                note=note
            )
            return {
                "success": True,
                "note": note,
                "history_entry_id": timestamp,
                "account_id": account_id
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def append_history(
        self,
        account_id: str,
        changes: list[dict],
        summary: str
    ) -> dict:
        """Append a history entry with linked chain."""
        agent = self._get_agent()
        account_path = self.mem_path / "accounts" / account_id
        history_path = account_path / "history.md"
        
        # Convert dict changes to StateChange objects
        state_changes = [
            StateChange(
                field=c.get("field", "unknown"),
                old_value=c.get("old_value", ""),
                new_value=c.get("new_value", "")
            )
            for c in changes
        ]
        
        try:
            timestamp = agent.append_history_entry(
                history_path=history_path,
                changes=state_changes,
                summary=summary,
                evidence="Agent action"
            )
            return {
                "success": True,
                "history_entry_id": timestamp,
                "account_id": account_id
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def update_search_index(self, account_id: str) -> dict:
        """Regenerate and update Qdrant description."""
        agent = self._get_agent()
        account_path = self.mem_path / "accounts" / account_id
        state_path = account_path / "state.md"
        
        if not state_path.exists():
            return {"success": False, "error": f"Account {account_id} not found"}
        
        state = agent.parse_state_md(state_path)
        description = agent.generate_description(state)
        
        success = agent.update_qdrant_description(
            account_id=account_id,
            account_name=state.get("account_name", "Unknown"),
            description=description,
            directory_path=f"{self.mem_path}/accounts/{account_id}"
        )
        
        return {
            "success": success,
            "description": description,
            "account_id": account_id
        }
    
    def create_account(
        self,
        account_name: str,
        account_details: Optional[dict] = None
    ) -> dict:
        """Create a new account."""
        agent = self._get_agent()
        return agent.create_account(
            account_name=account_name,
            account_details=account_details
        )
    
    def execute(self, tool: str, args: dict) -> str:
        """Execute a tool and return result."""
        # Handle base tools (read_file, list_files)
        if tool in ("read_file", "list_files"):
            return super().execute(tool, args)
        
        # Updater specific tools
        if tool == "lookup_account":
            result = self.lookup_account(
                query=args.get("query", ""),
                top_k=args.get("top_k", 5)
            )
            return json.dumps(result, indent=2)
        
        elif tool == "update_field":
            result = self.update_field(
                account_id=args.get("account_id", ""),
                field=args.get("field", ""),
                value=args.get("value")
            )
            return json.dumps(result, indent=2)
        
        elif tool == "add_note":
            result = self.add_note(
                account_id=args.get("account_id", ""),
                note=args.get("note", "")
            )
            return json.dumps(result, indent=2)
        
        elif tool == "append_history":
            result = self.append_history(
                account_id=args.get("account_id", ""),
                changes=args.get("changes", []),
                summary=args.get("summary", "Update")
            )
            return json.dumps(result, indent=2)
        
        elif tool == "update_search_index":
            result = self.update_search_index(
                account_id=args.get("account_id", "")
            )
            return json.dumps(result, indent=2)
        
        elif tool == "create_account":
            result = self.create_account(
                account_name=args.get("account_name", ""),
                account_details=args.get("account_details")
            )
            return json.dumps(result, indent=2)
        
        else:
            raise ValueError(f"Unknown tool: {tool}")


class UpdaterOrchestrator(BaseOrchestrator):
    """
    Agentic orchestrator for Update workflows.
    
    Claude decides:
    - Which account to update
    - What fields to change
    - When to record history
    - When to sync search index
    """
    
    # Budget limits for updater agent
    MAX_TOOL_CALLS = 15
    MAX_READ_FILE = 8
    MAX_WRITES = 5
    
    def __init__(
        self,
        mem_path: str = "mem",
        skills_path: str = "skills",
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001"
    ):
        super().__init__(mem_path, skills_path, api_key, model)
        self.tool_executor = UpdaterToolExecutor(
            repo_root=str(self.repo_root),
            mem_path=mem_path
        )
    
    def get_agent_name(self) -> str:
        """Return agent name for streaming events."""
        return "updater"
    
    def create_trace(self) -> Trace:
        """Create trace with updater specific budget limits."""
        return Trace(
            question="",
            max_tool_calls=self.MAX_TOOL_CALLS,
            max_read_file=self.MAX_READ_FILE,
            max_writes=self.MAX_WRITES
        )
    
    def build_system_prompt(self) -> str:
        """Build system prompt with skills and tools."""
        if self._system_prompt is not None:
            return self._system_prompt
        
        # Discover available skills
        skills = self._discover_skills("update")
        skills_xml = self._build_skills_xml(skills)
        
        self._system_prompt = f"""# Updater Agent

You handle updates to insurance account state and maintain history chain.

## Available Skills

{skills_xml}

When you need guidance on formats or rules, use read_file to load a skill's SKILL.md.

## Tools

- `lookup_account(query, top_k?)` - Find account by company name. Returns `state_file` (ready to use) and `directory_path`
- `read_file(path)` - Read any file - **must be a FILE path, not a directory**
- `list_files(path)` - List directory contents
- `update_field(account_id, field, value)` - Update a field in state.md
- `add_note(account_id, note)` - Add a note (recorded in history)
- `append_history(account_id, changes, summary)` - Add linked history entry
- `update_search_index(account_id)` - Regenerate Qdrant description
- `create_account(account_name, account_details?)` - Create new account

## lookup_account Return Format

`lookup_account` returns:
```json
{{
  "account_id": "29041",
  "name": "Maple Avenue Dental", 
  "directory_path": "mem/accounts/29041",  // DIRECTORY - don't read this!
  "state_file": "mem/accounts/29041/state.md"  // Use THIS for read_file
}}
```

**CRITICAL**: Use `state_file` directly with `read_file`. Do NOT read `directory_path` - it's a folder!

## Available Fields

- stage: Pipeline stage (New Lead, Application Received, Quoted, Bound, Closed Lost, etc.)
- insurance_types: List of insurance types
- primary_email: Contact email
- primary_phone: Contact phone
- next_steps: List of next action items
- pending_actions: List of pending items

## Workflow

1. Use `lookup_account` to find the target account (get `account_id` and `state_file`)
2. Use `read_file(state_file)` with the returned `state_file` path to understand current values
3. Apply updates with `update_field` (for state changes) or `add_note` (for notes only)
4. Record changes in history with `append_history`
5. **ALWAYS call update_search_index after ANY state.md change** - this keeps the vector database in sync

## When to Use Which Tool

- **update_field**: Use for ANY state change including:
  - Stage changes (e.g., "mark as quoted")
  - Status markers (e.g., "mark as needing follow-up" → update pending_actions)
  - Contact info updates
  - Next steps or pending actions changes
  
- **add_note**: Use ONLY for adding informational notes that don't change account status
  - Does NOT trigger Qdrant sync (no state change)
  
- **update_search_index**: Call after EVERY update_field call to sync Qdrant

## Response Format

You MUST respond with exactly one JSON object per turn.

### For tool calls:
```json
{{
  "type": "tool_call",
  "tool": "lookup_account",
  "args": {{"query": "Sunny Days Childcare"}},
  "reason": "Find the account to update"
}}
```

### For final answer:
```json
{{
  "type": "final",
  "answer": "Summary of changes made",
  "changes_made": [
    {{"account": "Account Name", "field": "stage", "old": "Application", "new": "Quoted"}}
  ]
}}
```

## Important Rules

- Always look up the account first to get the correct ID
- Read state.md before updating to know current values
- Record all field changes in history with append_history
- **ALWAYS call update_search_index after ANY update_field call** - never skip this step
- "Mark as needing follow-up" = update pending_actions field, then sync Qdrant
"""
        return self._system_prompt
    
    def run(self, query: str, use_cache: bool = False) -> dict:
        """
        Main entry point: run the updater agent loop.
        
        Args:
            query: User's update request
            use_cache: Whether to use cached results
            
        Returns:
            Response dict with answer, changes_made, and trace
        """
        # Check cache
        if use_cache:
            cached = self._get_cached_result(query)
            if cached:
                cached["from_cache"] = True
                return cached
        
        # Create trace with updater budget limits
        trace = Trace(
            question=query,
            max_tool_calls=self.MAX_TOOL_CALLS,
            max_read_file=self.MAX_READ_FILE,
            max_writes=self.MAX_WRITES
        )
        
        logger.info(f"Starting updater agent for: {query}")
        
        while not trace.is_budget_exhausted():
            try:
                response = self.call_claude(query, trace)
            except Exception as e:
                logger.error(f"Claude API error: {e}")
                trace.stop_reason = "error"
                return {
                    "answer": f"Error: {e}",
                    "changes_made": [],
                    "trace": trace.to_dict()
                }
            
            response_type = response.get("type")
            
            if response_type == "tool_call":
                tool = response.get("tool")
                args = response.get("args", {})
                reason = response.get("reason", "")
                
                logger.info(f"Tool call: {tool}({args}) - {reason}")
                
                tool_call = ToolCall(tool=tool, args=args, reason=reason)
                
                try:
                    result = self.tool_executor.execute(tool, args)
                    tool_call.result = result
                    logger.debug(f"Tool result: {result[:200]}...")
                except Exception as e:
                    tool_call.error = str(e)
                    logger.warning(f"Tool error: {e}")
                
                trace.add_tool_call(tool_call)
            
            elif response_type == "final":
                logger.info("Received final answer")
                trace.stop_reason = "final_answer"
                
                result = {
                    "answer": response.get("answer", ""),
                    "changes_made": response.get("changes_made", []),
                    "trace": trace.to_dict()
                }
                
                if use_cache:
                    self._cache_result(query, result)
                
                return result
            
            else:
                logger.warning(f"Unknown response type: {response_type}")
                continue
        
        # Budget exhausted
        logger.warning("Budget exhausted")
        trace.stop_reason = "budget_exhausted"
        
        return {
            "answer": f"Update limit reached. {trace.get_budget_status()}",
            "changes_made": [],
            "trace": trace.to_dict()
        }


def main():
    """CLI for testing the updater agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Updater Agent CLI")
    parser.add_argument("command", choices=["update", "run"],
                        help="Command to run")
    parser.add_argument("--query", "-q", help="Update query (for both modes)")
    parser.add_argument("--account-id", help="Account ID (for legacy update mode)")
    parser.add_argument("--account-name", default="Test Account", help="Account name")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # New agentic mode
    if args.command == "run":
        query = args.query or "Show me how to update an account"
        orchestrator = UpdaterOrchestrator()
        result = orchestrator.run(query)
        
        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)
        print(result["answer"])
        
        if result.get("changes_made"):
            print("\nChanges Made:")
            for change in result["changes_made"]:
                print(f"  - {change}")
        
        print(f"\nTrace: {result['trace']['budget_status']}")
        return
    
    # Legacy mode
    if args.command == "update":
        if not args.account_id or not args.query:
            print("Error: --account-id and --query required for update command")
            return
        
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
