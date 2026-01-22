#!/usr/bin/env python3
"""
Follow-Up Agent: Identifies accounts needing follow-up and automates communications.

Responsibilities:
1. Scan accounts to find those needing follow-up based on stage and history
2. Determine appropriate follow-up action and channel
3. Draft contextual communications using Claude
4. Execute (mock) communications and record actions
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Literal

import anthropic
from dotenv import load_dotenv

from name_registry import NameRegistry

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Channel types
ChannelType = Literal["email", "call_script", "sms"]

# Stage-based follow-up thresholds (days)
STAGE_THRESHOLDS = {
    "New Lead": {"days": 2, "urgent_days": 4, "primary_channel": "email"},
    "Intake": {"days": 2, "urgent_days": 4, "primary_channel": "email"},
    "Application": {"days": 3, "urgent_days": 5, "primary_channel": "email"},
    "Application Received": {"days": 3, "urgent_days": 5, "primary_channel": "email"},
    "Submission": {"days": 5, "urgent_days": 7, "primary_channel": "email"},
    "Quote Pitched": {"days": 2, "urgent_days": 3, "primary_channel": "call_script"},
    "Quoted": {"days": 2, "urgent_days": 3, "primary_channel": "call_script"},
}

# Stages that don't need follow-up
NO_FOLLOWUP_STAGES = {"Bound", "Closed Won", "Closed Lost", "Closed"}


@dataclass
class DraftedCommunication:
    """Represents a drafted follow-up communication."""
    channel: ChannelType
    subject: Optional[str]  # For email only
    body: str
    context_used: list[str] = field(default_factory=list)
    rationale: str = ""
    
    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "subject": self.subject,
            "body": self.body,
            "context_used": self.context_used,
            "rationale": self.rationale
        }


@dataclass
class FollowUpAction:
    """Represents a recommended follow-up action."""
    account_id: str
    account_name: str
    stage: str
    days_since_contact: int
    urgency: Literal["normal", "high", "critical"]
    recommended_channel: ChannelType
    next_steps: list[str]
    pending_actions: list[str]
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "stage": self.stage,
            "days_since_contact": self.days_since_contact,
            "urgency": self.urgency,
            "recommended_channel": self.recommended_channel,
            "next_steps": self.next_steps,
            "pending_actions": self.pending_actions,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
        }


@dataclass
class ExecutionResult:
    """Result of executing a follow-up action."""
    success: bool
    message: str
    account_id: str
    account_name: str
    channel: ChannelType
    draft: DraftedCommunication
    sent: bool = False
    recorded: bool = False
    history_entry_id: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "message": self.message,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "channel": self.channel,
            "draft": self.draft.to_dict(),
            "sent": self.sent,
            "recorded": self.recorded,
            "history_entry_id": self.history_entry_id,
            "error": self.error,
        }


class FollowUpAgent:
    """
    Automates follow-up workflows for insurance accounts.
    
    Workflow:
    1. Scan accounts to find those needing follow-up
    2. Determine channel and draft communication
    3. Execute (mock send) and record in history
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
        
        # Initialize name registry for account lookup
        self._name_registry: Optional[NameRegistry] = None
        try:
            self._name_registry = NameRegistry()
            logger.info("Follow-Up Agent connected to Qdrant")
        except Exception as e:
            logger.warning(f"Could not connect to Qdrant: {e}")
        
        # Lazy load updater agent for recording actions
        self._updater_agent = None
        
        # Cache for discovered skills and skill content
        self._available_skills: Optional[list[dict]] = None
        self._skill_content: Optional[str] = None
    
    def _get_updater_agent(self):
        """Get or create Updater Agent instance."""
        if self._updater_agent is None:
            from updater_agent import UpdaterAgent
            self._updater_agent = UpdaterAgent(mem_path=str(self.mem_path))
        return self._updater_agent
    
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
    
    def _discover_skills(self, category: str = "followup") -> list[dict]:
        """
        Discover available skills in a category (Level 1 - metadata only).
        
        Args:
            category: Skill category folder (e.g., "followup")
            
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
        skill_path = self.skills_path / "followup" / skill_name / "SKILL.md"
        
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
        skills = self._discover_skills("followup")
        return self._build_skills_xml(skills)
    
    def _load_skill(self) -> str:
        """Load the follow-up skill content (for backward compatibility)."""
        if self._skill_content is None:
            skill_path = self.skills_path / "followup" / "SKILL.md"
            if skill_path.exists():
                content = skill_path.read_text(encoding='utf-8')
                _, body = self._parse_skill_frontmatter(content)
                self._skill_content = body
            else:
                self._skill_content = "You are a follow-up agent for an insurance brokerage."
        return self._skill_content
    
    def _parse_state_md(self, state_path: Path) -> dict:
        """Parse state.md into a structured dictionary."""
        if not state_path.exists():
            return {}
        
        content = state_path.read_text(encoding='utf-8')
        state = {
            "raw": content,
            "name": "",
            "stage": "",
            "insurance_types": [],
            "primary_email": "",
            "primary_phone": "",
            "next_steps": [],
            "pending_actions": [],
            "last_contact_date": None,
            "last_contact_type": None,
        }
        
        # Extract name from header
        name_match = re.search(r'^#\s*(.+?)\s*\(Account', content, re.MULTILINE)
        if name_match:
            state["name"] = name_match.group(1).strip()
        
        # Extract stage
        stage_match = re.search(r'\*\*Stage\*\*:\s*(.+?)(?:\n|$)', content)
        if stage_match:
            state["stage"] = stage_match.group(1).strip()
        
        # Extract insurance types
        insurance_match = re.search(r'\*\*Insurance Types\*\*:\s*(.+?)(?:\n|$)', content)
        if insurance_match:
            types_str = insurance_match.group(1).strip()
            if types_str and types_str.lower() != "none":
                state["insurance_types"] = [t.strip() for t in types_str.split(",")]
        
        # Extract contacts
        email_match = re.search(r'\*\*Primary Email\*\*:\s*(.+?)(?:\n|$)', content)
        if email_match:
            state["primary_email"] = email_match.group(1).strip()
        
        phone_match = re.search(r'\*\*Primary Phone\*\*:\s*(.+?)(?:\n|$)', content)
        if phone_match:
            state["primary_phone"] = phone_match.group(1).strip()
        
        # Extract last contact
        last_contact_match = re.search(r'\*\*Date\*\*:\s*(.+?)(?:\n|$)', content)
        if last_contact_match:
            date_str = last_contact_match.group(1).strip()
            try:
                state["last_contact_date"] = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                # Try parsing common date formats
                for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"]:
                    try:
                        state["last_contact_date"] = datetime.strptime(date_str, fmt)
                        break
                    except:
                        continue
        
        last_type_match = re.search(r'\*\*Type\*\*:\s*(.+?)(?:\n|$)', content)
        if last_type_match:
            state["last_contact_type"] = last_type_match.group(1).strip()
        
        # Extract next steps
        next_steps_section = re.search(r'## Next Steps\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if next_steps_section:
            steps = re.findall(r'^-\s*(.+)$', next_steps_section.group(1), re.MULTILINE)
            state["next_steps"] = [s.strip() for s in steps if s.strip()]
        
        # Extract pending actions
        pending_section = re.search(r'## Pending Actions\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if pending_section:
            actions = re.findall(r'^-\s*(.+)$', pending_section.group(1), re.MULTILINE)
            state["pending_actions"] = [a.strip() for a in actions if a.strip()]
        
        return state
    
    def _calculate_days_since_contact(self, last_contact: Optional[datetime]) -> int:
        """Calculate days since last contact."""
        if not last_contact:
            return 999  # Very high number if no contact recorded
        
        now = datetime.now()
        if last_contact.tzinfo:
            now = datetime.now(last_contact.tzinfo)
        
        delta = now - last_contact
        return delta.days
    
    def _determine_urgency(self, stage: str, days_since: int) -> Literal["normal", "high", "critical"]:
        """Determine urgency level based on stage and days since contact."""
        thresholds = STAGE_THRESHOLDS.get(stage, {"days": 3, "urgent_days": 5})
        
        if days_since >= thresholds["urgent_days"] * 2:
            return "critical"
        elif days_since >= thresholds["urgent_days"]:
            return "high"
        elif days_since >= thresholds["days"]:
            return "normal"
        else:
            return "normal"  # Within threshold but might still need follow-up
    
    def find_accounts_needing_followup(
        self,
        stage_filter: Optional[str] = None,
        min_days: Optional[int] = None,
        limit: int = 20
    ) -> list[FollowUpAction]:
        """
        Scan accounts to find those needing follow-up.
        
        Args:
            stage_filter: Only include accounts at this stage
            min_days: Only include accounts with at least this many days since contact
            limit: Maximum number of accounts to return
            
        Returns:
            List of FollowUpAction objects sorted by urgency
        """
        accounts_path = self.mem_path / "accounts"
        if not accounts_path.exists():
            return []
        
        actions = []
        
        for account_dir in accounts_path.iterdir():
            if not account_dir.is_dir():
                continue
            
            state_path = account_dir / "state.md"
            if not state_path.exists():
                continue
            
            state = self._parse_state_md(state_path)
            
            # Skip closed stages
            if state.get("stage") in NO_FOLLOWUP_STAGES:
                continue
            
            # Apply stage filter
            if stage_filter and state.get("stage") != stage_filter:
                continue
            
            # Calculate days since contact
            days_since = self._calculate_days_since_contact(state.get("last_contact_date"))
            
            # Apply min_days filter
            if min_days and days_since < min_days:
                continue
            
            # Check if follow-up is needed
            stage = state.get("stage", "Unknown")
            thresholds = STAGE_THRESHOLDS.get(stage, {"days": 3, "primary_channel": "email"})
            
            if days_since >= thresholds["days"]:
                urgency = self._determine_urgency(stage, days_since)
                
                actions.append(FollowUpAction(
                    account_id=account_dir.name,
                    account_name=state.get("name", account_dir.name),
                    stage=stage,
                    days_since_contact=days_since,
                    urgency=urgency,
                    recommended_channel=thresholds.get("primary_channel", "email"),
                    next_steps=state.get("next_steps", []),
                    pending_actions=state.get("pending_actions", []),
                    contact_email=state.get("primary_email"),
                    contact_phone=state.get("primary_phone"),
                ))
        
        # Sort by urgency (critical > high > normal) then by days
        urgency_order = {"critical": 0, "high": 1, "normal": 2}
        actions.sort(key=lambda a: (urgency_order[a.urgency], -a.days_since_contact))
        
        return actions[:limit]
    
    def _get_recent_sources(self, account_path: Path, limit: int = 3) -> list[tuple[str, str]]:
        """Get recent source summaries for context."""
        sources = []
        sources_path = account_path / "sources"
        
        if not sources_path.exists():
            return sources
        
        # Collect all source summaries with timestamps
        all_sources = []
        
        for channel in ["emails", "calls", "sms"]:
            channel_path = sources_path / channel
            if not channel_path.exists():
                continue
            
            for item_dir in channel_path.iterdir():
                if not item_dir.is_dir():
                    continue
                
                summary_path = item_dir / "summary.md"
                if summary_path.exists():
                    content = summary_path.read_text(encoding='utf-8')
                    mtime = summary_path.stat().st_mtime
                    rel_path = str(summary_path.relative_to(account_path))
                    all_sources.append((mtime, rel_path, content))
        
        # Sort by modification time (newest first) and take top N
        all_sources.sort(key=lambda x: x[0], reverse=True)
        
        for _, path, content in all_sources[:limit]:
            sources.append((path, content))
        
        return sources
    
    def draft_communication(
        self,
        account_id: str,
        channel: Optional[ChannelType] = None,
        purpose: Optional[str] = None
    ) -> Optional[DraftedCommunication]:
        """
        Draft a follow-up communication for an account.
        
        Args:
            account_id: The account ID to draft for
            channel: Preferred channel (email, call_script, sms). Auto-detected if not provided.
            purpose: Optional purpose/context for the follow-up
            
        Returns:
            DraftedCommunication or None if drafting failed
        """
        account_path = self.mem_path / "accounts" / account_id
        state_path = account_path / "state.md"
        
        if not state_path.exists():
            logger.error(f"Account not found: {account_id}")
            return None
        
        # Parse account state
        state = self._parse_state_md(state_path)
        account_name = state.get("name", account_id)
        account_stage = state.get("stage", "Unknown")
        
        # Determine channel if not specified
        if not channel:
            thresholds = STAGE_THRESHOLDS.get(account_stage, {"primary_channel": "email"})
            channel = thresholds.get("primary_channel", "email")
        
        # Gather context
        context_used = ["state.md"]
        context_str = f"## Account State\n{state.get('raw', '')}\n\n"
        
        # Add recent sources
        recent_sources = self._get_recent_sources(account_path, limit=3)
        for source_path, content in recent_sources:
            context_used.append(source_path)
            context_str += f"## Recent Communication: {source_path}\n{content}\n\n"
        
        # Determine purpose if not provided
        if not purpose:
            purpose_map = {
                "New Lead": "initial outreach and qualification",
                "Intake": "document collection",
                "Application": "application completion",
                "Application Received": "application follow-up",
                "Submission": "underwriter status update",
                "Quote Pitched": "quote decision follow-up",
                "Quoted": "quote decision follow-up",
            }
            purpose = purpose_map.get(account_stage, "general follow-up")
        
        # Load skill
        skill_content = self._load_skill()
        
        # Build prompt for Claude
        prompt = f"""Draft a follow-up {channel} for this insurance account.

Purpose: {purpose}

{context_str}

Requirements:
- Channel: {channel}
- Be personalized and reference specific details from the account
- Keep it professional but warm
- For email: include subject line
- For call_script: include key talking points
- For sms: keep under 160 characters if possible

Respond with ONLY a JSON object:
{{
  "channel": "{channel}",
  "subject": "Email subject (null for call/sms)",
  "body": "The communication content",
  "rationale": "Brief explanation of why this message"
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=skill_content,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text.strip()
            
            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return DraftedCommunication(
                    channel=data.get("channel", channel),
                    subject=data.get("subject"),
                    body=data.get("body", ""),
                    context_used=context_used,
                    rationale=data.get("rationale", "")
                )
        except Exception as e:
            logger.error(f"Failed to draft communication: {e}")
        
        return None
    
    def execute_followup(
        self,
        account_id: str,
        draft: DraftedCommunication,
        dry_run: bool = True
    ) -> ExecutionResult:
        """
        Execute a follow-up action (send communication and record).
        
        Args:
            account_id: The account ID
            draft: The drafted communication to send
            dry_run: If True, only record but don't "send"
            
        Returns:
            ExecutionResult with details of what was done
        """
        account_path = self.mem_path / "accounts" / account_id
        state_path = account_path / "state.md"
        
        if not state_path.exists():
            return ExecutionResult(
                success=False,
                message=f"Account not found: {account_id}",
                account_id=account_id,
                account_name=account_id,
                channel=draft.channel,
                draft=draft,
                error="Account not found"
            )
        
        state = self._parse_state_md(state_path)
        account_name = state.get("name", account_id)
        
        # Mock sending (in production, would integrate with email/SMS/phone APIs)
        sent = False
        if not dry_run:
            sent = self._log_sent_communication(account_id, draft)
        
        # Record in history
        recorded = False
        history_entry_id = None
        
        try:
            history_entry_id = self._record_followup_action(account_id, account_name, draft)
            recorded = True
        except Exception as e:
            logger.error(f"Failed to record follow-up: {e}")
        
        # Update last contact in state
        if recorded:
            try:
                self._update_last_contact(account_id, draft.channel)
            except Exception as e:
                logger.warning(f"Failed to update last contact: {e}")
        
        return ExecutionResult(
            success=True,
            message=f"Follow-up {'sent and ' if sent else ''}recorded for {account_name}",
            account_id=account_id,
            account_name=account_name,
            channel=draft.channel,
            draft=draft,
            sent=sent,
            recorded=recorded,
            history_entry_id=history_entry_id,
        )
    
    def _log_sent_communication(self, account_id: str, draft: DraftedCommunication) -> bool:
        """Mock sending a communication (would integrate with real APIs in production)."""
        logger.info(f"[MOCK SEND] {draft.channel} to account {account_id}")
        logger.info(f"Subject: {draft.subject}")
        logger.info(f"Body: {draft.body[:200]}...")
        
        # In production, this would call email/SMS/phone APIs
        # For now, just log to a file
        sent_path = self.mem_path / "sent_communications"
        sent_path.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{account_id}_{draft.channel}_{timestamp}.json"
        
        with open(sent_path / filename, 'w') as f:
            json.dump({
                "account_id": account_id,
                "channel": draft.channel,
                "subject": draft.subject,
                "body": draft.body,
                "sent_at": datetime.now().isoformat(),
            }, f, indent=2)
        
        return True
    
    def _record_followup_action(
        self,
        account_id: str,
        account_name: str,
        draft: DraftedCommunication
    ) -> str:
        """Record the follow-up action in account history."""
        history_path = self.mem_path / "accounts" / account_id / "history.md"
        
        timestamp = datetime.now().isoformat() + "Z"
        
        # Build history entry
        channel_label = {
            "email": "Email sent",
            "call_script": "Call made (script prepared)",
            "sms": "SMS sent"
        }.get(draft.channel, "Follow-up sent")
        
        entry = f"""## {timestamp}

{channel_label} for follow-up.

- **Channel**: {draft.channel}
- **Subject**: {draft.subject or 'N/A'}
- **Summary**: {draft.body[:200]}{'...' if len(draft.body) > 200 else ''}
- **Rationale**: {draft.rationale}

---

"""
        
        # Read existing history and prepend new entry
        existing = ""
        if history_path.exists():
            existing = history_path.read_text(encoding='utf-8')
        
        # Find where to insert (after the header)
        if existing.startswith("# History"):
            header_end = existing.find("\n\n") + 2
            new_content = existing[:header_end] + entry + existing[header_end:]
        else:
            new_content = f"# History for {account_name}\n\n{entry}{existing}"
        
        history_path.write_text(new_content, encoding='utf-8')
        
        return timestamp
    
    def _update_last_contact(self, account_id: str, channel: ChannelType):
        """Update the last contact date/type in state.md."""
        state_path = self.mem_path / "accounts" / account_id / "state.md"
        
        if not state_path.exists():
            return
        
        content = state_path.read_text(encoding='utf-8')
        
        # Update last contact section
        today = datetime.now().strftime("%Y-%m-%d")
        channel_type = {
            "email": "Email",
            "call_script": "Phone Call",
            "sms": "SMS"
        }.get(channel, "Follow-up")
        
        # Replace or add last contact info
        date_pattern = r'\*\*Date\*\*:\s*.+?(?=\n)'
        type_pattern = r'\*\*Type\*\*:\s*.+?(?=\n)'
        
        if re.search(date_pattern, content):
            content = re.sub(date_pattern, f'**Date**: {today}', content)
        
        if re.search(type_pattern, content):
            content = re.sub(type_pattern, f'**Type**: {channel_type}', content)
        
        state_path.write_text(content, encoding='utf-8')


# =============================================================================
# AGENTIC LOOP IMPLEMENTATION
# =============================================================================

from agent_base import (
    BaseToolExecutor, BaseOrchestrator, Trace, ToolCall,
    discover_skills, build_skills_xml
)


class FollowUpToolExecutor(BaseToolExecutor):
    """
    Tool executor for Follow-up Agent.
    
    Provides tools for:
    - Reading files (skills, state, sources)
    - Looking up accounts by name
    - Scanning accounts needing follow-up
    - Getting recent communications
    - Drafting and sending communications
    """
    
    def __init__(self, repo_root: str, mem_path: str = "mem"):
        super().__init__(repo_root)
        self.mem_path = Path(mem_path)
        self._followup_agent: Optional[FollowUpAgent] = None
    
    def _get_agent(self) -> FollowUpAgent:
        """Get or create the underlying FollowUpAgent."""
        if self._followup_agent is None:
            self._followup_agent = FollowUpAgent(mem_path=str(self.mem_path))
        return self._followup_agent
    
    def lookup_account(self, query: str, top_k: int = 5) -> list[dict]:
        """Look up account by name using semantic search."""
        agent = self._get_agent()
        if agent._name_registry is None:
            return [{"error": "Name registry not available"}]
        return agent._name_registry.search(query, top_k)
    
    def scan_accounts(
        self,
        stage_filter: Optional[str] = None,
        min_days: Optional[int] = None,
        limit: int = 10
    ) -> list[dict]:
        """Find accounts needing follow-up."""
        agent = self._get_agent()
        actions = agent.find_accounts_needing_followup(
            stage_filter=stage_filter,
            min_days=min_days,
            limit=limit
        )
        return [a.to_dict() for a in actions]
    
    def get_recent_sources(self, account_id: str, limit: int = 3) -> list[dict]:
        """Get recent source summaries for an account."""
        agent = self._get_agent()
        account_path = self.mem_path / "accounts" / account_id
        sources = agent._get_recent_sources(account_path, limit=limit)
        return [{"path": path, "content": content} for path, content in sources]
    
    def draft_communication(
        self,
        account_id: str,
        channel: str,
        purpose: Optional[str] = None
    ) -> dict:
        """Draft a follow-up communication."""
        agent = self._get_agent()
        draft = agent.draft_communication(
            account_id=account_id,
            channel=channel,
            purpose=purpose
        )
        if draft:
            return draft.to_dict()
        return {"error": "Failed to draft communication"}
    
    def send_communication(
        self,
        account_id: str,
        channel: str,
        subject: Optional[str],
        body: str,
        rationale: str = ""
    ) -> dict:
        """Send a communication and record in history."""
        agent = self._get_agent()
        
        # Create draft object
        draft = DraftedCommunication(
            channel=channel,
            subject=subject,
            body=body,
            rationale=rationale
        )
        
        # Execute (always dry_run=False in agentic mode - agent decided to send)
        result = agent.execute_followup(account_id, draft, dry_run=False)
        return result.to_dict()
    
    def update_contact(self, account_id: str, channel: str) -> dict:
        """Update last contact date in state.md."""
        agent = self._get_agent()
        try:
            agent._update_last_contact(account_id, channel)
            return {"success": True, "message": f"Updated last contact for {account_id}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def execute(self, tool: str, args: dict) -> str:
        """Execute a tool and return result."""
        # Handle base tools (read_file, list_files)
        if tool in ("read_file", "list_files"):
            return super().execute(tool, args)
        
        # Follow-up specific tools
        if tool == "lookup_account":
            result = self.lookup_account(
                query=args.get("query", ""),
                top_k=args.get("top_k", 5)
            )
            return json.dumps(result, indent=2)
        
        elif tool == "scan_accounts":
            result = self.scan_accounts(
                stage_filter=args.get("stage_filter"),
                min_days=args.get("min_days"),
                limit=args.get("limit", 10)
            )
            return json.dumps(result, indent=2)
        
        elif tool == "get_recent_sources":
            result = self.get_recent_sources(
                account_id=args.get("account_id", ""),
                limit=args.get("limit", 3)
            )
            return json.dumps(result, indent=2)
        
        elif tool == "draft_communication":
            result = self.draft_communication(
                account_id=args.get("account_id", ""),
                channel=args.get("channel", "email"),
                purpose=args.get("purpose")
            )
            return json.dumps(result, indent=2)
        
        elif tool == "send_communication":
            result = self.send_communication(
                account_id=args.get("account_id", ""),
                channel=args.get("channel", "email"),
                subject=args.get("subject"),
                body=args.get("body", ""),
                rationale=args.get("rationale", "")
            )
            return json.dumps(result, indent=2)
        
        elif tool == "update_contact":
            result = self.update_contact(
                account_id=args.get("account_id", ""),
                channel=args.get("channel", "email")
            )
            return json.dumps(result, indent=2)
        
        else:
            raise ValueError(f"Unknown tool: {tool}")


class FollowUpOrchestrator(BaseOrchestrator):
    """
    Agentic orchestrator for Follow-up workflows.
    
    Claude decides:
    - Which accounts to follow up with
    - What channel to use
    - What to say
    - When to stop
    """
    
    # Budget limits for follow-up agent
    MAX_TOOL_CALLS = 20
    MAX_READ_FILE = 10
    MAX_WRITES = 5  # Limit sends per run
    
    def __init__(
        self,
        mem_path: str = "mem",
        skills_path: str = "skills",
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001"
    ):
        super().__init__(mem_path, skills_path, api_key, model)
        self.tool_executor = FollowUpToolExecutor(
            repo_root=str(self.repo_root),
            mem_path=mem_path
        )
    
    def get_agent_name(self) -> str:
        """Return agent name for streaming events."""
        return "followup"
    
    def create_trace(self) -> Trace:
        """Create trace with follow-up specific budget limits."""
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
        skills = self._discover_skills("followup")
        skills_xml = self._build_skills_xml(skills)
        
        self._system_prompt = f"""# Follow-up Agent

You automate follow-up workflows for insurance accounts. You decide which accounts need attention, draft appropriate communications, and execute follow-ups.

## Available Skills

{skills_xml}

When you need specialized guidance (e.g., stage-specific rules, email templates), use read_file to load a skill's SKILL.md.

## Tools

- `lookup_account(query, top_k?)` - Find account by company name. Returns `state_file` (ready to use) and `directory_path`
- `read_file(path)` - Read any file - **must be a FILE path, not a directory**
- `list_files(path)` - List directory contents
- `scan_accounts(stage_filter?, min_days?, limit?)` - Find accounts needing follow-up
- `get_recent_sources(account_id, limit?)` - Get recent emails/calls/SMS for context
- `draft_communication(account_id, channel, purpose?)` - Generate a draft (email, call_script, sms)
- `send_communication(account_id, channel, subject?, body, rationale?)` - Send and record in history
- `update_contact(account_id, channel)` - Update last contact date in state

## lookup_account Return Format

`lookup_account` returns:
```json
{{
  "account_id": "29041",
  "name": "Maple Avenue Dental", 
  "directory_path": "mem/accounts/29041",  // This is a DIRECTORY - don't read_file on this!
  "state_file": "mem/accounts/29041/state.md"  // Use THIS for read_file
}}
```

**CRITICAL**: Use `state_file` directly with `read_file`. Do NOT try to read `directory_path` - it's a folder, not a file!

## Workflow

### When given a specific account name:
1. Use `lookup_account(query)` to find the account
2. Use `read_file(state_file)` with the returned `state_file` path
3. Use `get_recent_sources(account_id)` for context
4. Determine what follow-up is needed and draft/send

### When asked to find accounts needing follow-up:
1. Use `scan_accounts` to find accounts needing follow-up
2. For each account, read state and recent sources for context
3. Draft appropriate communication based on stage and history
4. Send the communication (this also records in history)

## Response Format

You MUST respond with exactly one JSON object per turn.

### For tool calls:
```json
{{
  "type": "tool_call",
  "tool": "lookup_account",
  "args": {{"query": "Maple Avenue Dental"}},
  "reason": "Find account ID to check follow-up needs"
}}
```

### For asking clarification (when you need more info from user):
```json
{{
  "type": "clarification",
  "question": "Which account would you like me to send the follow-up SMS to?",
  "suggestions": ["Use scan_accounts to find accounts needing follow-up", "Specify an account name"]
}}
```

### For final answer:
```json
{{
  "type": "final",
  "answer": "Summary of what was done",
  "actions_taken": [
    {{"account": "Company Name", "action": "Sent email", "channel": "email"}}
  ]
}}
```

## Handling Ambiguous Requests

When the user doesn't specify an account:
1. **If they ask to "find" or "scan" accounts** → use `scan_accounts` to find accounts needing follow-up
2. **If they give a general task like "write a follow-up SMS"** → ask which account using the `clarification` response type
3. **If they mention pending documents** → use `scan_accounts` to find accounts with pending document requests, then ask to confirm

## Important Rules

- **When given an account name, ALWAYS use lookup_account first** to get the account_id
- **When no account specified, ask for clarification** - don't guess
- Always read account state before drafting
- Use recent sources for personalization
- Record all actions (send_communication handles this)
- Stop when task is complete or budget is exhausted
"""
        return self._system_prompt
    
    def run(self, query: str, use_cache: bool = False) -> dict:
        """
        Main entry point: run the follow-up agent loop.
        
        Args:
            query: User's request (e.g., "Follow up on overdue accounts")
            use_cache: Whether to use cached results
            
        Returns:
            Response dict with answer, actions_taken, and trace
        """
        # Check cache
        if use_cache:
            cached = self._get_cached_result(query)
            if cached:
                cached["from_cache"] = True
                return cached
        
        # Create trace with follow-up budget limits
        trace = Trace(
            question=query,
            max_tool_calls=self.MAX_TOOL_CALLS,
            max_read_file=self.MAX_READ_FILE,
            max_writes=self.MAX_WRITES
        )
        
        logger.info(f"Starting follow-up agent for: {query}")
        
        while not trace.is_budget_exhausted():
            try:
                response = self.call_claude(query, trace)
            except Exception as e:
                logger.error(f"Claude API error: {e}")
                trace.stop_reason = "error"
                return {
                    "answer": f"Error: {e}",
                    "actions_taken": [],
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
            
            elif response_type == "clarification":
                logger.info("Agent needs clarification from user")
                trace.stop_reason = "clarification_needed"
                
                return {
                    "answer": response.get("question", "I need more information to proceed."),
                    "needs_clarification": True,
                    "suggestions": response.get("suggestions", []),
                    "actions_taken": [],
                    "trace": trace.to_dict()
                }
            
            elif response_type == "final":
                logger.info("Received final answer")
                trace.stop_reason = "final_answer"
                
                result = {
                    "answer": response.get("answer", ""),
                    "actions_taken": response.get("actions_taken", []),
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
            "answer": f"Follow-up limit reached. {trace.get_budget_status()}",
            "actions_taken": [],
            "trace": trace.to_dict()
        }


# CLI for testing
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Follow-Up Agent CLI")
    parser.add_argument("command", choices=["scan", "draft", "execute", "run"],
                        help="Command to run")
    parser.add_argument("--account", "-a", help="Account ID for draft/execute")
    parser.add_argument("--channel", "-c", choices=["email", "call_script", "sms"],
                        help="Communication channel")
    parser.add_argument("--stage", "-s", help="Filter by stage (for scan)")
    parser.add_argument("--days", "-d", type=int, help="Min days since contact (for scan)")
    parser.add_argument("--send", action="store_true", help="Actually send (not dry run)")
    parser.add_argument("--query", "-q", help="Query for agentic run mode")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    # New agentic mode
    if args.command == "run":
        query = args.query or "Find and follow up on accounts that are overdue"
        orchestrator = FollowUpOrchestrator()
        result = orchestrator.run(query)
        
        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)
        print(result["answer"])
        
        if result.get("actions_taken"):
            print("\nActions Taken:")
            for action in result["actions_taken"]:
                print(f"  - {action}")
        
        print(f"\nTrace: {result['trace']['budget_status']}")
        return
    
    # Legacy commands
    agent = FollowUpAgent()
    
    if args.command == "scan":
        actions = agent.find_accounts_needing_followup(
            stage_filter=args.stage,
            min_days=args.days
        )
        print(f"\nFound {len(actions)} accounts needing follow-up:\n")
        for action in actions:
            print(f"  [{action.urgency.upper()}] {action.account_name}")
            print(f"    Stage: {action.stage}, Days since contact: {action.days_since_contact}")
            print(f"    Recommended: {action.recommended_channel}")
            print()
    
    elif args.command == "draft":
        if not args.account:
            print("Error: --account required for draft command")
            return
        
        draft = agent.draft_communication(args.account, channel=args.channel)
        if draft:
            print(f"\nDrafted {draft.channel}:")
            if draft.subject:
                print(f"Subject: {draft.subject}")
            print(f"\n{draft.body}")
            print(f"\nRationale: {draft.rationale}")
        else:
            print("Failed to draft communication")
    
    elif args.command == "execute":
        if not args.account:
            print("Error: --account required for execute command")
            return
        
        draft = agent.draft_communication(args.account, channel=args.channel)
        if draft:
            result = agent.execute_followup(args.account, draft, dry_run=not args.send)
            print(f"\n{result.message}")
            print(f"Sent: {result.sent}, Recorded: {result.recorded}")
            if result.history_entry_id:
                print(f"History entry: {result.history_entry_id}")
        else:
            print("Failed to draft communication")


if __name__ == "__main__":
    main()
