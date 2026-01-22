#!/usr/bin/env python3
"""
FastAPI server for Harper Agent System.

Routes queries through the Starter Agent which classifies intent and routes to:
- Search Agent (Orchestrator) for read-only queries
- Updater Agent for state changes and updates

Includes SSE streaming for real-time exploration visualization.

Usage:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from search_agent import Orchestrator
from starter_agent import StarterAgent
from followup_agent import FollowUpAgent

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Harper Agent System API",
    description="API for the Harper multi-agent system with intent routing, search, and updates",
    version="3.4.0"
)

# Add CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize agents (singletons)
_starter_agent: Optional[StarterAgent] = None
_orchestrator: Optional[Orchestrator] = None
_followup_agent: Optional[FollowUpAgent] = None


def get_starter_agent() -> StarterAgent:
    """Get or create the Starter Agent instance."""
    global _starter_agent
    if _starter_agent is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _starter_agent = StarterAgent(mem_path="mem", api_key=api_key)
        logger.info("Starter Agent initialized")
    return _starter_agent


def get_orchestrator() -> Orchestrator:
    """Get or create the orchestrator (Search Agent) instance."""
    global _orchestrator
    if _orchestrator is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _orchestrator = Orchestrator(mem_path="mem", api_key=api_key)
        logger.info("Search Agent (Orchestrator) initialized")
    return _orchestrator


def get_followup_agent() -> FollowUpAgent:
    """Get or create the Follow-Up Agent instance."""
    global _followup_agent
    if _followup_agent is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _followup_agent = FollowUpAgent(mem_path="mem", api_key=api_key)
        logger.info("Follow-Up Agent initialized")
    return _followup_agent


class QueryRequest(BaseModel):
    """Request body for /query endpoint."""
    query: str
    session_id: Optional[str] = None


class ConfirmRequest(BaseModel):
    """Request body for /confirm endpoint."""
    session_id: str
    confirmed: bool
    # Optional account details for new account creation
    industry: Optional[str] = None
    location: Optional[str] = None
    primary_email: Optional[str] = None
    primary_phone: Optional[str] = None
    insurance_types: Optional[list[str]] = None
    notes: Optional[str] = None
    # Clarification data for vague updates
    clarification_data: Optional[dict] = None


class QueryResponse(BaseModel):
    """Response body for /query endpoint."""
    type: str  # "success", "confirmation_required", "clarification_needed", "error"
    message: str
    answer: Optional[str] = None
    citations: list[str] = []
    notes: str = ""
    trace_summary: list[str] = []
    from_cache: bool = False
    session_id: Optional[str] = None
    routed_to: Optional[str] = None
    # For confirmation_required
    action: Optional[str] = None
    account_name: Optional[str] = None
    alternatives: list[dict] = []
    # For update operations - rich details
    account_id: Optional[str] = None
    changes: list[dict] = []
    history_entry_id: Optional[str] = None
    files_modified: list[str] = []
    qdrant_updated: bool = False
    new_description: Optional[str] = None
    state_file_path: Optional[str] = None
    history_file_path: Optional[str] = None
    previous_history_entry: Optional[str] = None


# Follow-Up Agent Request/Response Models
class FollowUpDraftRequest(BaseModel):
    """Request body for /followup/draft endpoint."""
    account_id: str
    channel: Optional[str] = None  # "email", "call_script", "sms"
    purpose: Optional[str] = None


class FollowUpExecuteRequest(BaseModel):
    """Request body for /followup/execute endpoint."""
    account_id: str
    channel: Optional[str] = None
    purpose: Optional[str] = None
    dry_run: bool = True  # Default to dry run (don't actually send)


class FollowUpBatchRequest(BaseModel):
    """Request body for /followup/batch endpoint."""
    stage: Optional[str] = None
    days_threshold: Optional[int] = None
    limit: int = 10
    dry_run: bool = True


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """
    Process a query through the Starter Agent.
    
    The Starter Agent classifies intent and routes to:
    - Search Agent for read-only queries
    - Updater Agent for state changes
    
    May return confirmation_required if account doesn't exist.
    
    Args:
        request: QueryRequest with query and optional session_id
        
    Returns:
        QueryResponse with result or confirmation request
    """
    try:
        logger.info(f"Received query: {request.query}")
        starter = get_starter_agent()
        result = starter.run(request.query, session_id=request.session_id)
        
        # Build response based on result type
        response_data = {
            "type": result.type,
            "message": result.message,
        }
        
        # Add data from result
        if result.data:
            response_data["citations"] = result.data.get("citations", [])
            response_data["notes"] = result.data.get("notes", "")
            response_data["trace_summary"] = result.data.get("trace_summary", [])
            response_data["from_cache"] = result.data.get("from_cache", False)
            response_data["routed_to"] = result.data.get("routed_to")
            response_data["session_id"] = result.data.get("session_id")
            response_data["action"] = result.data.get("action")
            response_data["account_name"] = result.data.get("account_name")
            response_data["alternatives"] = result.data.get("alternatives", [])
            
            # Rich update details for proof
            response_data["account_id"] = result.data.get("account_id")
            response_data["changes"] = result.data.get("changes", [])
            response_data["history_entry_id"] = result.data.get("history_entry_id")
            response_data["files_modified"] = result.data.get("files_modified", [])
            response_data["qdrant_updated"] = result.data.get("qdrant_updated", False)
            response_data["new_description"] = result.data.get("new_description")
            response_data["state_file_path"] = result.data.get("state_file_path")
            response_data["history_file_path"] = result.data.get("history_file_path")
            response_data["previous_history_entry"] = result.data.get("previous_history_entry")
        
        # For search results, set answer to message
        if result.type == "success":
            response_data["answer"] = result.message
        
        return QueryResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/confirm", response_model=QueryResponse)
async def confirm(request: ConfirmRequest):
    """
    Handle confirmation for pending actions (like creating new accounts).
    
    Args:
        request: ConfirmRequest with session_id, confirmed boolean, and optional account details
        
    Returns:
        QueryResponse with result of confirmed action
    """
    try:
        logger.info(f"Received confirmation: session={request.session_id}, confirmed={request.confirmed}")
        starter = get_starter_agent()
        
        # Build account details dict if any were provided
        account_details = None
        if request.confirmed:
            details = {}
            if request.industry:
                details["industry"] = request.industry
            if request.location:
                details["location"] = request.location
            if request.primary_email:
                details["primary_email"] = request.primary_email
            if request.primary_phone:
                details["primary_phone"] = request.primary_phone
            if request.insurance_types:
                details["insurance_types"] = request.insurance_types
            if request.notes:
                details["notes"] = request.notes
            if details:
                account_details = details
        
        result = starter.handle_confirmation(
            request.session_id, 
            request.confirmed, 
            account_details,
            clarification_data=request.clarification_data
        )
        
        response_data = {
            "type": result.type,
            "message": result.message,
        }
        
        if result.data:
            response_data["citations"] = result.data.get("citations", [])
            response_data["routed_to"] = result.data.get("routed_to")
            response_data["account_name"] = result.data.get("account_name")
            response_data["account_id"] = result.data.get("account_id")
        
        if result.type == "success":
            response_data["answer"] = result.message
        
        return QueryResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Confirmation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search")
async def search_direct(request: QueryRequest):
    """
    Direct access to Search Agent (bypasses Starter Agent routing).
    
    Use this when you know the query is a search/lookup.
    """
    try:
        logger.info(f"Direct search: {request.query}")
        orchestrator = get_orchestrator()
        result = orchestrator.run(request.query)
        
        return {
            "type": "success",
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "notes": result.get("notes", ""),
            "trace_summary": result.get("trace_summary", []),
            "from_cache": result.get("from_cache", False)
        }
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Follow-Up Agent Endpoints
# =============================================================================

@app.get("/followup/pending")
async def get_pending_followups(stage: Optional[str] = None, days: Optional[int] = None):
    """
    Get accounts that need follow-up.
    
    Args:
        stage: Optional filter by pipeline stage (e.g., "Quoted", "Application")
        days: Optional override for days-since-contact threshold
        
    Returns:
        List of accounts needing follow-up, sorted by urgency
    """
    try:
        logger.info(f"Getting pending follow-ups (stage={stage}, days={days})")
        followup_agent = get_followup_agent()
        
        accounts = followup_agent.find_accounts_needing_followup(
            stage=stage,
            days_threshold=days
        )
        
        return {
            "accounts": [a.to_dict() for a in accounts],
            "total": len(accounts),
            "filters": {
                "stage": stage,
                "days_threshold": days
            }
        }
    except Exception as e:
        logger.error(f"Failed to get pending follow-ups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/followup/draft")
async def draft_followup(request: FollowUpDraftRequest):
    """
    Draft a follow-up communication for an account.
    
    Args:
        request: FollowUpDraftRequest with account_id and optional channel/purpose
        
    Returns:
        Drafted communication with context used
    """
    try:
        logger.info(f"Drafting follow-up for account {request.account_id}")
        followup_agent = get_followup_agent()
        
        draft = followup_agent.draft_communication(
            account_id=request.account_id,
            channel=request.channel,
            purpose=request.purpose
        )
        
        return {
            "draft": draft.to_dict(),
            "account_id": request.account_id
        }
    except Exception as e:
        logger.error(f"Failed to draft follow-up: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/followup/execute")
async def execute_followup(request: FollowUpExecuteRequest):
    """
    Execute a follow-up action (draft and optionally send).
    
    Args:
        request: FollowUpExecuteRequest with account_id and dry_run flag
        
    Returns:
        Execution result with draft and status
    """
    try:
        logger.info(f"Executing follow-up for account {request.account_id} (dry_run={request.dry_run})")
        followup_agent = get_followup_agent()
        
        # First draft the communication
        draft = followup_agent.draft_communication(
            account_id=request.account_id,
            channel=request.channel,
            purpose=request.purpose
        )
        
        # Then execute (send or just record)
        result = followup_agent.execute_followup(
            account_id=request.account_id,
            draft=draft,
            dry_run=request.dry_run
        )
        
        return {
            "result": result.to_dict(),
            "draft": draft.to_dict(),
            "account_id": request.account_id
        }
    except Exception as e:
        logger.error(f"Failed to execute follow-up: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/followup/batch")
async def batch_followup(request: FollowUpBatchRequest):
    """
    Process follow-ups for multiple accounts in batch.
    
    Args:
        request: FollowUpBatchRequest with filters and dry_run flag
        
    Returns:
        Results for each processed account
    """
    try:
        logger.info(f"Processing batch follow-ups (stage={request.stage}, limit={request.limit})")
        followup_agent = get_followup_agent()
        
        # Find accounts needing follow-up
        accounts = followup_agent.find_accounts_needing_followup(
            stage=request.stage,
            days_threshold=request.days_threshold
        )
        
        # Limit the number of accounts to process
        accounts = accounts[:request.limit]
        
        results = []
        for action in accounts:
            try:
                # Draft communication
                draft = followup_agent.draft_communication(
                    account_id=action.account_id,
                    channel=action.recommended_channel
                )
                
                # Execute
                result = followup_agent.execute_followup(
                    account_id=action.account_id,
                    draft=draft,
                    dry_run=request.dry_run
                )
                
                results.append({
                    "account_id": action.account_id,
                    "account_name": action.account_name,
                    "result": result.to_dict(),
                    "draft": draft.to_dict()
                })
            except Exception as e:
                results.append({
                    "account_id": action.account_id,
                    "account_name": action.account_name,
                    "error": str(e)
                })
        
        return {
            "processed": len(results),
            "total_pending": len(accounts),
            "dry_run": request.dry_run,
            "results": results
        }
    except Exception as e:
        logger.error(f"Failed to process batch follow-ups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "3.5.0",
        "agents": ["starter", "search", "updater", "followup"],
        "features": ["agent_skills", "progressive_disclosure", "followup_automation"]
    }


@app.post("/cache/clear")
async def clear_cache():
    """Clear the query result cache."""
    try:
        orchestrator = get_orchestrator()
        orchestrator.clear_cache()
        logger.info("Cache cleared via API")
        return {"status": "ok", "message": "Cache cleared"}
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def generate_sse_events(query: str):
    """Generate SSE events for streaming exploration via Starter Agent."""
    starter = get_starter_agent()
    
    for event in starter.run_streaming(query):
        # Format as SSE event
        event_data = json.dumps(event)
        logger.info(f"SSE event: type={event.get('type')}")
        yield f"data: {event_data}\n\n"
    
    # Send done event
    logger.info("SSE sending done event")
    yield "data: {\"type\": \"done\"}\n\n"


@app.post("/query/stream")
async def query_stream(request: QueryRequest):
    """
    Stream exploration events via Server-Sent Events (SSE).
    
    Routes through Starter Agent which streams search results.
    For update queries, returns a single final event.
    
    Each event contains a step of the exploration process:
    - start: Query started
    - thinking: Agent is about to execute a tool
    - tool_result: Tool execution completed
    - final: Exploration complete with answer
    - error: An error occurred
    - done: Stream complete
    """
    logger.info(f"Received streaming query: {request.query}")
    
    return StreamingResponse(
        generate_sse_events(request.query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


def build_tree_node(path: Path, base_path: Path, max_depth: int = 4, current_depth: int = 0) -> dict:
    """
    Recursively build a tree node for visualization.
    
    Args:
        path: Current path to process
        base_path: Base path for relative paths
        max_depth: Maximum recursion depth
        current_depth: Current recursion level
        
    Returns:
        Tree node dictionary
    """
    try:
        rel_path = str(path.relative_to(base_path))
    except ValueError:
        rel_path = str(path)
    
    node = {
        "name": path.name or str(path),
        "path": rel_path,
        "type": "directory" if path.is_dir() else "file",
    }
    
    if path.is_dir() and current_depth < max_depth:
        children = []
        try:
            for child in sorted(path.iterdir()):
                # Skip hidden files
                if child.name.startswith('.'):
                    continue
                children.append(build_tree_node(child, base_path, max_depth, current_depth + 1))
        except PermissionError:
            pass
        node["children"] = children
    
    return node


@app.get("/tree")
async def get_tree(max_depth: int = 4):
    """
    Get the filesystem tree structure for visualization.
    
    Args:
        max_depth: Maximum depth to traverse (default 4)
        
    Returns:
        Tree structure starting from mem/ directory
    """
    try:
        mem_path = Path("mem").resolve()
        
        if not mem_path.exists():
            raise HTTPException(status_code=404, detail="mem directory not found")
        
        tree = build_tree_node(mem_path, mem_path.parent, max_depth)
        
        return {"tree": tree}
    except Exception as e:
        logger.error(f"Failed to build tree: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file")
async def read_file(path: str):
    """
    Read a file's contents for preview.
    
    Args:
        path: Relative path to file within mem/
        
    Returns:
        File contents and metadata
    """
    try:
        # Ensure path is within mem directory
        mem_path = Path("mem").resolve()
        file_path = (mem_path.parent / path).resolve()
        
        # Security check
        try:
            file_path.relative_to(mem_path.parent)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path outside allowed directory")
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        if not file_path.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
        
        # Check file size (max 200KB)
        size = file_path.stat().st_size
        if size > 200 * 1024:
            raise HTTPException(status_code=400, detail="File too large")
        
        content = file_path.read_text(encoding='utf-8')
        
        return {
            "path": path,
            "name": file_path.name,
            "content": content,
            "size": size,
            "extension": file_path.suffix
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
