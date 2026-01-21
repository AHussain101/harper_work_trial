#!/usr/bin/env python3
"""
Starter Agent: Routes queries to appropriate agents based on intent.

Responsibilities:
1. Intent classification (search vs update vs unclear)
2. Account resolution (lookup in Qdrant)
3. New account creation flow (with user confirmation)
4. Routing to Search Agent or Updater Agent
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal

import anthropic
from dotenv import load_dotenv

from name_registry import NameRegistry
from orchestrator import Orchestrator

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Intent types
IntentType = Literal["search", "update", "unclear"]


@dataclass
class ClassifiedIntent:
    """Result of intent classification."""
    intent: IntentType
    account_name: Optional[str] = None
    action_summary: Optional[str] = None
    confidence: float = 0.0
    raw_response: dict = field(default_factory=dict)


@dataclass
class AccountResolution:
    """Result of account lookup."""
    found: bool
    account_id: Optional[str] = None
    account_name: Optional[str] = None
    account_path: Optional[str] = None
    score: float = 0.0
    alternatives: list = field(default_factory=list)


@dataclass
class StarterAgentResponse:
    """Response from the Starter Agent."""
    type: Literal["success", "confirmation_required", "clarification_needed", "error"]
    message: str
    data: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "message": self.message,
            **self.data
        }


class StarterAgent:
    """
    Routes queries to appropriate agents based on intent classification.
    
    Flow:
    1. Classify intent (search/update/unclear)
    2. Extract account reference
    3. Resolve account in Qdrant
    4. If not found: prompt for confirmation to create
    5. Route to appropriate agent
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
        
        # Initialize name registry for account lookup
        self._name_registry: Optional[NameRegistry] = None
        try:
            self._name_registry = NameRegistry()
            logger.info("Starter Agent connected to Qdrant")
        except Exception as e:
            logger.warning(f"Could not connect to Qdrant: {e}")
        
        # Initialize Search Agent (Orchestrator)
        self._search_agent: Optional[Orchestrator] = None
        
        # Lazy import to avoid circular dependency
        self._updater_agent = None
        
        # Session state for multi-turn confirmations
        self._pending_confirmations: dict[str, dict] = {}
    
    def _get_search_agent(self) -> Orchestrator:
        """Get or create Search Agent instance."""
        if self._search_agent is None:
            self._search_agent = Orchestrator(mem_path=str(self.mem_path))
        return self._search_agent
    
    def _get_updater_agent(self):
        """Get or create Updater Agent instance."""
        if self._updater_agent is None:
            from updater_agent import UpdaterAgent
            self._updater_agent = UpdaterAgent(mem_path=str(self.mem_path))
        return self._updater_agent
    
    def classify_intent(self, query: str) -> ClassifiedIntent:
        """
        Use Claude to classify the intent of a query.
        
        Returns:
            ClassifiedIntent with intent type and extracted account reference
        """
        prompt = f"""Classify this user query for an insurance account management system.

Query: "{query}"

Respond with a JSON object containing:
1. "intent": One of "search", "update", or "unclear"
   - "search": User wants to look up info, ask a question, check status (read-only)
   - "update": User wants to change something, add a note, update status, mark as something
   - "unclear": Cannot determine intent, need clarification

2. "account_name": The company/account name mentioned (or null if none)

3. "action_summary": Brief summary of what user wants to do (for updates)

4. "confidence": 0.0 to 1.0 confidence in classification

Examples:
- "What is the status of Sunny Days Childcare?" → {{"intent": "search", "account_name": "Sunny Days Childcare", "action_summary": null, "confidence": 0.95}}
- "Mark ABC Corp as Quoted" → {{"intent": "update", "account_name": "ABC Corp", "action_summary": "Change stage to Quoted", "confidence": 0.9}}
- "Which accounts need follow-up?" → {{"intent": "search", "account_name": null, "action_summary": null, "confidence": 0.85}}
- "Sunny Days" → {{"intent": "unclear", "account_name": "Sunny Days", "action_summary": null, "confidence": 0.4}}

Respond with ONLY the JSON object, no other text."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            
            content = response.content[0].text.strip()
            
            # Parse JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return ClassifiedIntent(
                    intent=data.get("intent", "unclear"),
                    account_name=data.get("account_name"),
                    action_summary=data.get("action_summary"),
                    confidence=data.get("confidence", 0.0),
                    raw_response=data
                )
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
        
        return ClassifiedIntent(intent="unclear", confidence=0.0)
    
    def resolve_account(self, account_name: str, threshold: float = 0.75) -> AccountResolution:
        """
        Look up account in Qdrant by name.
        
        Args:
            account_name: Company name to search for
            threshold: Minimum similarity score to consider a match
            
        Returns:
            AccountResolution with match details
        """
        if not self._name_registry:
            return AccountResolution(found=False)
        
        try:
            results = self._name_registry.search(account_name, top_k=5)
            
            if not results:
                return AccountResolution(found=False)
            
            top_match = results[0]
            
            if top_match["score"] >= threshold:
                return AccountResolution(
                    found=True,
                    account_id=top_match["account_id"],
                    account_name=top_match["name"],
                    account_path=top_match["path"],
                    score=top_match["score"],
                    alternatives=results[1:3] if len(results) > 1 else []
                )
            else:
                # Below threshold - might be a new account
                return AccountResolution(
                    found=False,
                    alternatives=results[:3]
                )
                
        except Exception as e:
            logger.error(f"Account resolution failed: {e}")
            return AccountResolution(found=False)
    
    def create_new_account(
        self,
        account_name: str,
        account_id: Optional[str] = None
    ) -> dict:
        """
        Create a new account folder structure.
        
        Args:
            account_name: Company name for the new account
            account_id: Optional specific ID, otherwise auto-generated
            
        Returns:
            dict with account_id, path, and success status
        """
        # Generate account ID if not provided
        if account_id is None:
            account_id = self._generate_account_id()
        
        account_dir = self.mem_path / "accounts" / str(account_id)
        sources_dir = account_dir / "sources"
        
        try:
            # Create directory structure
            for subdir in ["emails", "calls", "sms"]:
                (sources_dir / subdir).mkdir(parents=True, exist_ok=True)
            
            # Create minimal state.md
            timestamp = datetime.now().isoformat()
            state_content = f"""# {account_name} (Account {account_id})

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
- **Date**: {timestamp[:10]}
- **Type**: Account created
"""
            state_path = account_dir / "state.md"
            state_path.write_text(state_content, encoding='utf-8')
            
            # Create initial history.md
            history_content = f"""# Change History

## {timestamp}

Account created for {account_name}.

- **action**: Account initialized
- **Evidence**: User request

---

"""
            history_path = account_dir / "history.md"
            history_path.write_text(history_content, encoding='utf-8')
            
            # Index in Qdrant
            if self._name_registry:
                directory_path = f"{self.mem_path}/accounts/{account_id}"
                
                # Index by name
                self._name_registry.upsert_account(
                    account_id=str(account_id),
                    name=account_name,
                    directory_path=directory_path
                )
                
                # Index by description
                description = f"{account_name} | Stage: New Lead | New account, initial outreach needed."
                self._name_registry.upsert_description(
                    account_id=str(account_id),
                    name=account_name,
                    description=description,
                    directory_path=directory_path
                )
                
                logger.info(f"Indexed new account {account_id} in Qdrant")
            
            logger.info(f"Created new account: {account_id} - {account_name}")
            
            return {
                "success": True,
                "account_id": str(account_id),
                "account_name": account_name,
                "path": str(account_dir)
            }
            
        except Exception as e:
            logger.error(f"Failed to create account: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
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
    
    def handle_confirmation(
        self,
        session_id: str,
        confirmed: bool
    ) -> StarterAgentResponse:
        """
        Handle user confirmation for pending actions (like creating new account).
        
        Args:
            session_id: Session identifier for the pending confirmation
            confirmed: Whether user confirmed the action
            
        Returns:
            StarterAgentResponse with result
        """
        if session_id not in self._pending_confirmations:
            return StarterAgentResponse(
                type="error",
                message="No pending confirmation found for this session."
            )
        
        pending = self._pending_confirmations.pop(session_id)
        
        if not confirmed:
            return StarterAgentResponse(
                type="success",
                message="Action cancelled.",
                data={"cancelled": True}
            )
        
        action = pending.get("action")
        
        if action == "create_account":
            # Create the new account
            result = self.create_new_account(
                account_name=pending["account_name"]
            )
            
            if result["success"]:
                # Continue with original query if it was an update
                original_query = pending.get("original_query")
                original_intent = pending.get("original_intent")
                
                if original_intent == "update" and original_query:
                    # Route to updater agent with the new account
                    return self._route_to_updater(
                        query=original_query,
                        account_id=result["account_id"],
                        account_name=result["account_name"],
                        account_path=result["path"]
                    )
                
                return StarterAgentResponse(
                    type="success",
                    message=f"Created new account: {result['account_name']} (ID: {result['account_id']})",
                    data=result
                )
            else:
                return StarterAgentResponse(
                    type="error",
                    message=f"Failed to create account: {result.get('error', 'Unknown error')}"
                )
        
        return StarterAgentResponse(
            type="error",
            message=f"Unknown pending action: {action}"
        )
    
    def _route_to_search(self, query: str) -> StarterAgentResponse:
        """Route query to Search Agent (Orchestrator)."""
        try:
            search_agent = self._get_search_agent()
            result = search_agent.run(query)
            
            return StarterAgentResponse(
                type="success",
                message=result.get("answer", ""),
                data={
                    "citations": result.get("citations", []),
                    "notes": result.get("notes", ""),
                    "trace_summary": result.get("trace_summary", []),
                    "from_cache": result.get("from_cache", False),
                    "routed_to": "search_agent"
                }
            )
        except Exception as e:
            logger.error(f"Search agent failed: {e}")
            return StarterAgentResponse(
                type="error",
                message=f"Search failed: {e}"
            )
    
    def _route_to_updater(
        self,
        query: str,
        account_id: str,
        account_name: str,
        account_path: str
    ) -> StarterAgentResponse:
        """Route query to Updater Agent."""
        try:
            updater_agent = self._get_updater_agent()
            result = updater_agent.process_update(
                query=query,
                account_id=account_id,
                account_name=account_name,
                account_path=account_path
            )
            
            # Pass through all rich details from updater agent
            return StarterAgentResponse(
                type="success" if result.get("success") else "error",
                message=result.get("message", "Update processed"),
                data={
                    "routed_to": "updater_agent",
                    # Core update info
                    "changes": result.get("changes", []),
                    "history_entry_id": result.get("history_entry_id"),
                    # Rich details for proof
                    "account_id": result.get("account_id", account_id),
                    "account_name": result.get("account_name", account_name),
                    "files_modified": result.get("files_modified", []),
                    "qdrant_updated": result.get("qdrant_updated", False),
                    "new_description": result.get("new_description"),
                    "state_file_path": result.get("state_file_path"),
                    "history_file_path": result.get("history_file_path"),
                    "previous_history_entry": result.get("previous_history_entry"),
                }
            )
        except Exception as e:
            logger.error(f"Updater agent failed: {e}")
            return StarterAgentResponse(
                type="error",
                message=f"Update failed: {e}"
            )
    
    def run(self, query: str, session_id: Optional[str] = None) -> StarterAgentResponse:
        """
        Main entry point: process a query and route appropriately.
        
        Args:
            query: User's query/command
            session_id: Optional session ID for multi-turn conversations
            
        Returns:
            StarterAgentResponse with result or confirmation request
        """
        logger.info(f"Starter Agent received: {query}")
        
        # Step 1: Classify intent
        classification = self.classify_intent(query)
        logger.info(f"Classified as: {classification.intent} (confidence: {classification.confidence})")
        
        # Step 2: Handle unclear intent
        if classification.intent == "unclear":
            return StarterAgentResponse(
                type="clarification_needed",
                message="I'm not sure what you'd like to do. Are you looking up information or making an update?",
                data={
                    "extracted_account": classification.account_name,
                    "suggestions": [
                        f"To look up: 'What is the status of {classification.account_name}?'" if classification.account_name else "To look up: 'What is the status of [company name]?'",
                        f"To update: 'Mark {classification.account_name} as Quoted'" if classification.account_name else "To update: 'Mark [company name] as [status]'"
                    ]
                }
            )
        
        # Step 3: Handle queries without specific account (cross-account searches)
        if not classification.account_name:
            if classification.intent == "search":
                return self._route_to_search(query)
            else:
                return StarterAgentResponse(
                    type="clarification_needed",
                    message="Which account would you like to update?",
                    data={"original_intent": classification.intent}
                )
        
        # Step 4: Resolve account
        resolution = self.resolve_account(classification.account_name)
        
        # Step 5: Handle account not found
        if not resolution.found:
            # Generate session ID for confirmation flow
            import uuid
            new_session_id = session_id or str(uuid.uuid4())
            
            # Store pending confirmation
            self._pending_confirmations[new_session_id] = {
                "action": "create_account",
                "account_name": classification.account_name,
                "original_query": query,
                "original_intent": classification.intent
            }
            
            alternatives_msg = ""
            if resolution.alternatives:
                alt_names = [a["name"] for a in resolution.alternatives[:3]]
                alternatives_msg = f"\n\nDid you mean one of these? {', '.join(alt_names)}"
            
            return StarterAgentResponse(
                type="confirmation_required",
                message=f"I don't have an account for '{classification.account_name}'. Would you like me to create a new account?{alternatives_msg}",
                data={
                    "action": "create_account",
                    "account_name": classification.account_name,
                    "session_id": new_session_id,
                    "alternatives": resolution.alternatives
                }
            )
        
        # Step 6: Route to appropriate agent
        if classification.intent == "search":
            return self._route_to_search(query)
        elif classification.intent == "update":
            return self._route_to_updater(
                query=query,
                account_id=resolution.account_id,
                account_name=resolution.account_name,
                account_path=resolution.account_path
            )
        
        return StarterAgentResponse(
            type="error",
            message="Unexpected state in query routing"
        )
    
    def run_streaming(self, query: str):
        """
        Streaming version that yields events during processing.
        Yields routing events to show Starter Agent thinking, then delegates.
        """
        classification = self.classify_intent(query)
        search_agent = self._get_search_agent()
        
        # Build routing event to show Starter Agent thinking
        routed_to = "search_agent" if classification.intent == "search" else "updater_agent"
        routing_event = {
            "type": "routing",
            "intent": classification.intent,
            "confidence": classification.confidence,
            "account_name": classification.account_name,
            "routed_to": routed_to,
        }
        
        # Add skill info if available
        try:
            skill_meta = search_agent.get_skill_metadata("search" if classification.intent == "search" else "update")
            if skill_meta and skill_meta.get("name"):
                desc = skill_meta.get("description", "")
                routing_event["skill_loaded"] = {
                    "name": skill_meta.get("name", "Agent"),
                    "description": desc[:120] + "..." if len(desc) > 120 else desc,
                    "path": f"mem/skills/{'search' if classification.intent == 'search' else 'update'}/SKILL.md"
                }
        except Exception:
            pass  # Skill info is optional
        
        # Yield routing event first (except for unclear intent)
        if classification.intent != "unclear":
            yield routing_event
        
        # Handle cross-account searches that don't need account resolution
        if classification.intent == "search" and not classification.account_name:
            yield from search_agent.run_streaming(query)
            return
        
        # Handle unclear intent
        if classification.intent == "unclear":
            result = self.run(query)
            yield {
                "type": "clarification_needed",
                "message": result.message,
                **(result.data or {})
            }
            return
        
        # If account name provided, resolve it
        if classification.account_name:
            resolution = self.resolve_account(classification.account_name)
            
            # Account not found - yield confirmation_required
            if not resolution.found:
                result = self.run(query)
                yield {
                    "type": result.type,
                    "message": result.message,
                    **(result.data or {})
                }
                return
            
            # Route based on intent
            if classification.intent == "search":
                yield from search_agent.run_streaming(query)
            else:
                # Update operation - yield final result with all details
                result = self.run(query)
                yield {
                    "type": "final" if result.type == "success" else result.type,
                    "answer": result.message,
                    **(result.data or {})
                }
        else:
            # Fallback - run and yield result
            result = self.run(query)
            yield {
                "type": "final" if result.type == "success" else result.type,
                "answer": result.message,
                **(result.data or {})
            }


def main():
    """CLI for testing the starter agent."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test the Starter Agent")
    parser.add_argument("query", help="Query to process")
    parser.add_argument("--confirm", action="store_true", help="Auto-confirm new account creation")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    agent = StarterAgent()
    result = agent.run(args.query)
    
    print(f"\nType: {result.type}")
    print(f"Message: {result.message}")
    
    if result.data:
        print(f"Data: {json.dumps(result.data, indent=2)}")
    
    # Handle confirmation if needed
    if result.type == "confirmation_required" and args.confirm:
        session_id = result.data.get("session_id")
        if session_id:
            print("\n--- Auto-confirming ---")
            confirm_result = agent.handle_confirmation(session_id, confirmed=True)
            print(f"Type: {confirm_result.type}")
            print(f"Message: {confirm_result.message}")


if __name__ == "__main__":
    main()
