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
from search_agent import Orchestrator
from followup_agent import FollowUpOrchestrator
from updater_agent import UpdaterOrchestrator

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Intent types
IntentType = Literal["search", "update", "followup", "unclear"]


@dataclass
class ClassifiedIntent:
    """Result of intent classification."""
    intent: IntentType
    account_name: Optional[str] = None
    requires_specific_account: bool = False
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
        self._followup_agent = None
        
        # Agentic orchestrators for streaming
        self._followup_orchestrator: Optional[FollowUpOrchestrator] = None
        self._updater_orchestrator: Optional[UpdaterOrchestrator] = None
        
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
    
    def _get_followup_agent(self):
        """Get or create Follow-Up Agent instance."""
        if self._followup_agent is None:
            from followup_agent import FollowUpAgent
            self._followup_agent = FollowUpAgent(mem_path=str(self.mem_path))
        return self._followup_agent
    
    def _get_followup_orchestrator(self) -> FollowUpOrchestrator:
        """Get or create Follow-Up Orchestrator for streaming."""
        if self._followup_orchestrator is None:
            self._followup_orchestrator = FollowUpOrchestrator(mem_path=str(self.mem_path))
        return self._followup_orchestrator
    
    def _get_updater_orchestrator(self) -> UpdaterOrchestrator:
        """Get or create Updater Orchestrator for streaming."""
        if self._updater_orchestrator is None:
            self._updater_orchestrator = UpdaterOrchestrator(mem_path=str(self.mem_path))
        return self._updater_orchestrator
    
    def classify_intent(self, query: str) -> ClassifiedIntent:
        """
        Use Claude to classify the intent of a query.
        
        Returns:
            ClassifiedIntent with intent type and extracted account reference
        """
        prompt = f"""Classify this user query for an insurance account management system.

Query: "{query}"

Respond with a JSON object containing:
1. "intent": One of "search", "update", "followup", or "unclear"
   - "search": User wants to look up info, ask a question, check status (read-only)
   - "update": User wants to change something, add a note, update status, mark as something
   - "followup": User wants to send a follow-up, draft a communication, or execute a follow-up action for an account
   - "unclear": Cannot determine intent, need clarification

2. "account_name": The company/account name mentioned (or null if none)

3. "action_summary": Brief summary of what user wants to do (for updates/followups)

4. "confidence": 0.0 to 1.0 confidence in classification

5. "requires_specific_account": true/false - Whether this query is about a specific account
   - true: Query references "the customer", "their email", "the call", a specific person, or implies a single account context
   - false: Query is cross-account ("which accounts", "list all", "how many") or general

Examples:
- "What is the status of Sunny Days Childcare?" → {{"intent": "search", "account_name": "Sunny Days Childcare", "requires_specific_account": true, "action_summary": null, "confidence": 0.95}}
- "Mark ABC Corp as Quoted" → {{"intent": "update", "account_name": "ABC Corp", "requires_specific_account": true, "action_summary": "Change stage to Quoted", "confidence": 0.9}}
- "Which accounts need follow-up?" → {{"intent": "search", "account_name": null, "requires_specific_account": false, "action_summary": null, "confidence": 0.85}}
- "What did the customer say in the call?" → {{"intent": "search", "account_name": null, "requires_specific_account": true, "action_summary": null, "confidence": 0.8}}
- "Compare the emails to the call transcript" → {{"intent": "search", "account_name": null, "requires_specific_account": true, "action_summary": null, "confidence": 0.8}}
- "Follow up with Maple Avenue Dental" → {{"intent": "followup", "account_name": "Maple Avenue Dental", "requires_specific_account": true, "action_summary": "Send follow-up communication", "confidence": 0.9}}
- "Send a follow-up email to ABC Corp" → {{"intent": "followup", "account_name": "ABC Corp", "requires_specific_account": true, "action_summary": "Draft and send follow-up email", "confidence": 0.9}}
- "Draft a call script for Sunny Days" → {{"intent": "followup", "account_name": "Sunny Days", "requires_specific_account": true, "action_summary": "Draft call script for follow-up", "confidence": 0.85}}
- "Sunny Days" → {{"intent": "unclear", "account_name": "Sunny Days", "requires_specific_account": true, "action_summary": null, "confidence": 0.4}}

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
                    requires_specific_account=data.get("requires_specific_account", False),
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
    
    def _route_to_create_account(
        self,
        account_name: str,
        account_details: Optional[dict] = None
    ) -> StarterAgentResponse:
        """
        Route account creation to the Updater Agent (account-create skill).
        
        Args:
            account_name: Company name for the new account
            account_details: Optional dict with account info (industry, location, etc.)
            
        Returns:
            StarterAgentResponse with creation result
        """
        try:
            updater_agent = self._get_updater_agent()
            result = updater_agent.create_account(
                account_name=account_name,
                account_details=account_details
            )
            
            if result.get("success"):
                return StarterAgentResponse(
                    type="success",
                    message=result.get("message", f"Created new account: {account_name}"),
                    data={
                        "routed_to": "updater_agent",
                        "account_id": result.get("account_id"),
                        "account_name": result.get("account_name"),
                        "changes": result.get("changes", []),
                        "history_entry_id": result.get("history_entry_id"),
                        "files_modified": result.get("files_modified", []),
                        "qdrant_updated": result.get("qdrant_updated", False),
                        "new_description": result.get("new_description"),
                        "state_file_path": result.get("state_file_path"),
                        "history_file_path": result.get("history_file_path"),
                    }
                )
            else:
                return StarterAgentResponse(
                    type="error",
                    message=result.get("message", "Failed to create account")
                )
        except Exception as e:
            logger.error(f"Account creation failed: {e}")
            return StarterAgentResponse(
                type="error",
                message=f"Failed to create account: {e}"
            )
    
    def handle_confirmation(
        self,
        session_id: str,
        confirmed: bool,
        account_details: Optional[dict] = None,
        clarification_data: Optional[dict] = None
    ) -> StarterAgentResponse:
        """
        Handle user confirmation for pending actions (like creating new account or clarifying updates).
        
        Args:
            session_id: Session identifier for the pending confirmation
            confirmed: Whether user confirmed the action
            account_details: Optional dict with account details (industry, location, etc.)
            clarification_data: Optional dict with clarification data for vague updates
            
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
            # Route account creation to Updater Agent (account-create skill)
            create_result = self._route_to_create_account(
                account_name=pending["account_name"],
                account_details=account_details
            )
            
            if create_result.type == "success":
                # Continue with original query if it was an update
                original_query = pending.get("original_query")
                original_intent = pending.get("original_intent")
                
                if original_intent == "update" and original_query:
                    # Route to updater agent with the new account for the original update
                    account_id = create_result.data.get("account_id")
                    account_name = create_result.data.get("account_name")
                    account_path = f"{self.mem_path}/accounts/{account_id}"
                    return self._route_to_updater(
                        query=original_query,
                        account_id=account_id,
                        account_name=account_name,
                        account_path=account_path
                    )
                
                return create_result
            else:
                return create_result
        
        elif action == "clarify_update":
            # Handle clarified update submission
            if not clarification_data:
                return StarterAgentResponse(
                    type="error",
                    message="No clarification data provided."
                )
            
            try:
                updater_agent = self._get_updater_agent()
                result = updater_agent.process_clarified_update(
                    account_id=pending["account_id"],
                    account_name=pending["account_name"],
                    account_path=pending["account_path"],
                    clarification_data=clarification_data
                )
                
                return StarterAgentResponse(
                    type="success" if result.get("success") else "error",
                    message=result.get("message", "Update processed"),
                    data={
                        "routed_to": "updater_agent",
                        "changes": result.get("changes", []),
                        "history_entry_id": result.get("history_entry_id"),
                        "account_id": result.get("account_id"),
                        "account_name": result.get("account_name"),
                        "files_modified": result.get("files_modified", []),
                        "qdrant_updated": result.get("qdrant_updated", False),
                        "new_description": result.get("new_description"),
                        "state_file_path": result.get("state_file_path"),
                        "history_file_path": result.get("history_file_path"),
                        "previous_history_entry": result.get("previous_history_entry"),
                    }
                )
            except Exception as e:
                logger.error(f"Clarified update failed: {e}")
                return StarterAgentResponse(
                    type="error",
                    message=f"Update failed: {e}"
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
            
            # Check if this is a vague update that needs clarification
            if result.get("needs_clarification"):
                import uuid
                session_id = str(uuid.uuid4())
                
                # Store pending clarification
                self._pending_confirmations[session_id] = {
                    "action": "clarify_update",
                    "account_id": account_id,
                    "account_name": account_name,
                    "account_path": account_path,
                    "original_query": result.get("original_query", query),
                    "clarification_fields": result.get("clarification_fields", [])
                }
                
                return StarterAgentResponse(
                    type="clarification_needed",
                    message=result.get("message", "I need more details to complete this update."),
                    data={
                        "routed_to": "updater_agent",
                        "session_id": session_id,
                        "account_id": account_id,
                        "account_name": account_name,
                        "clarification_type": "vague_update",
                        "clarification_fields": result.get("clarification_fields", []),
                        "original_query": result.get("original_query", query)
                    }
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
    
    def _route_to_followup(
        self,
        query: str,
        account_id: str,
        account_name: str,
        account_path: str,
        action_summary: Optional[str] = None
    ) -> StarterAgentResponse:
        """Route query to Follow-Up Agent."""
        try:
            followup_agent = self._get_followup_agent()
            
            # Determine channel from query or use default
            channel = None
            query_lower = query.lower()
            if "email" in query_lower:
                channel = "email"
            elif "call" in query_lower:
                channel = "call_script"
            elif "sms" in query_lower or "text" in query_lower:
                channel = "sms"
            
            # Draft the communication
            draft = followup_agent.draft_communication(
                account_id=account_id,
                channel=channel,
                purpose=action_summary
            )
            
            # Determine if we should execute (send) or just draft
            # Look for action words that indicate sending
            should_send = any(word in query_lower for word in ["send", "execute", "do"])
            
            # Execute with dry_run based on intent
            result = followup_agent.execute_followup(
                account_id=account_id,
                draft=draft,
                dry_run=not should_send  # Dry run unless explicitly sending
            )
            
            return StarterAgentResponse(
                type="success" if result.success else "error",
                message=result.message,
                data={
                    "routed_to": "followup_agent",
                    "account_id": account_id,
                    "account_name": account_name,
                    "draft": draft.to_dict(),
                    "sent": result.sent,
                    "recorded": result.recorded,
                    "history_entry_id": result.history_entry_id
                }
            )
        except Exception as e:
            logger.error(f"Follow-up agent failed: {e}")
            return StarterAgentResponse(
                type="error",
                message=f"Follow-up failed: {e}"
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
        
        # Step 3: Handle queries without specific account
        if not classification.account_name:
            # Check if query needs a specific account but none was provided
            if classification.requires_specific_account:
                return StarterAgentResponse(
                    type="clarification_needed",
                    message="Which account are you asking about? You can provide the company name or describe them (e.g., 'the childcare center in Texas').",
                    data={
                        "original_query": query,
                        "original_intent": classification.intent,
                        "reason": "Query requires specific account"
                    }
                )
            
            # Cross-account search (no specific account needed)
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
        elif classification.intent == "followup":
            return self._route_to_followup(
                query=query,
                account_id=resolution.account_id,
                account_name=resolution.account_name,
                account_path=resolution.account_path,
                action_summary=classification.action_summary
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
        intent_to_agent = {
            "search": "search_agent",
            "update": "updater_agent",
            "followup": "followup_agent"
        }
        routed_to = intent_to_agent.get(classification.intent, "search_agent")
        routing_event = {
            "type": "routing",
            "intent": classification.intent,
            "confidence": classification.confidence,
            "account_name": classification.account_name,
            "routed_to": routed_to,
        }
        
        # Add available skills info for the routed agent
        intent_to_category = {
            "search": "search",
            "update": "update",
            "followup": "followup"
        }
        skill_category = intent_to_category.get(classification.intent, "search")
        try:
            available_skills = search_agent._discover_skills(skill_category)
            if available_skills:
                # Show first skill as representative, note that there are more
                first_skill = available_skills[0]
                skill_count = len(available_skills)
                routing_event["skill_loaded"] = {
                    "name": f"{skill_count} {skill_category.title()} Skills Available",
                    "description": f"Skills: {', '.join(s['name'] for s in available_skills[:4])}{'...' if skill_count > 4 else ''}",
                    "path": f"skills/{skill_category}/"
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
            elif classification.intent == "update":
                # Stream from Updater Orchestrator
                logger.info(f"Streaming update via UpdaterOrchestrator")
                updater_orchestrator = self._get_updater_orchestrator()
                yield from updater_orchestrator.run_streaming(query)
            elif classification.intent == "followup":
                # Stream from Follow-up Orchestrator
                logger.info(f"Streaming followup via FollowUpOrchestrator")
                followup_orchestrator = self._get_followup_orchestrator()
                yield from followup_orchestrator.run_streaming(query)
            else:
                # Fallback for other intents - use non-streaming run
                logger.info(f"Processing {classification.intent} via run()")
                result = self.run(query)
                
                # Handle vague update clarification
                if result.type == "clarification_needed" and result.data.get("clarification_type") == "vague_update":
                    logger.info("Yielding vague_update_clarification event")
                    yield {
                        "type": "vague_update_clarification",
                        "message": result.message,
                        "session_id": result.data.get("session_id"),
                        "account_id": result.data.get("account_id"),
                        "account_name": result.data.get("account_name"),
                        "clarification_fields": result.data.get("clarification_fields", []),
                        "original_query": result.data.get("original_query")
                    }
                else:
                    final_event = {
                        "type": "final" if result.type == "success" else result.type,
                        "answer": result.message,
                        **(result.data or {})
                    }
                    logger.info(f"Yielding final event for {classification.intent}: type={final_event.get('type')}, has_changes={bool(final_event.get('changes'))}")
                    yield final_event
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
