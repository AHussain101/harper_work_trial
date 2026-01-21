#!/usr/bin/env python3
"""
FastAPI server for the Exploration Agent.

Exposes a /query endpoint for the evaluation script.

Usage:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from orchestrator import Orchestrator

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
    title="Harper Exploration Agent API",
    description="API for querying the filesystem memory exploration agent",
    version="1.0.0"
)

# Initialize orchestrator (singleton)
_orchestrator: Optional[Orchestrator] = None


def get_orchestrator() -> Orchestrator:
    """Get or create the orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _orchestrator = Orchestrator(mem_path="mem", api_key=api_key)
        logger.info("Orchestrator initialized")
    return _orchestrator


class QueryRequest(BaseModel):
    """Request body for /query endpoint."""
    query: str


class QueryResponse(BaseModel):
    """Response body for /query endpoint."""
    answer: str
    citations: list[str]
    notes: str
    trace_summary: list[str]
    from_cache: bool = False


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """
    Process a query through the exploration agent.
    
    Args:
        request: QueryRequest with the query string
        
    Returns:
        QueryResponse with answer, citations, notes, and trace summary
    """
    try:
        logger.info(f"Received query: {request.query}")
        orchestrator = get_orchestrator()
        result = orchestrator.run(request.query)
        
        return QueryResponse(
            answer=result.get("answer", ""),
            citations=result.get("citations", []),
            notes=result.get("notes", ""),
            trace_summary=result.get("trace_summary", []),
            from_cache=result.get("from_cache", False)
        )
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
