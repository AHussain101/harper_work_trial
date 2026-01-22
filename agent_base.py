#!/usr/bin/env python3
"""
Agent Base: Shared infrastructure for agentic loops.

Provides:
- Trace class for tracking tool calls and budget
- Response parsing utilities
- Skill discovery and XML building
- Common tool executor base class
"""

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Generator

import anthropic
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a single tool call."""
    tool: str
    args: dict
    reason: str
    result: Optional[str] = None
    error: Optional[str] = None


@dataclass
class Trace:
    """
    Tracks the exploration trace for a query.
    
    Provides budget tracking and tool call history for any agent.
    """
    question: str
    tool_calls: list = field(default_factory=list)
    files_opened: list = field(default_factory=list)
    stop_reason: str = ""
    
    # Budget limits (can be overridden per-agent)
    max_tool_calls: int = 15
    max_read_file: int = 8
    max_writes: int = 5
    
    # Budget tracking
    read_file_count: int = 0
    write_count: int = 0
    
    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)
    
    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the trace."""
        self.tool_calls.append(tool_call)
        
        # Track specific tool usage
        if tool_call.tool == "read_file":
            self.read_file_count += 1
            path = tool_call.args.get("path", "")
            if path and tool_call.error is None:
                self.files_opened.append(path)
        elif tool_call.tool in ("update_field", "append_history", "send_communication", "create_account"):
            self.write_count += 1
    
    def is_budget_exhausted(self) -> bool:
        """Check if any budget limit has been reached."""
        return (
            self.tool_call_count >= self.max_tool_calls or
            self.read_file_count >= self.max_read_file or
            self.write_count >= self.max_writes
        )
    
    def get_budget_status(self) -> str:
        """Get a human-readable budget status."""
        return (
            f"Tool calls: {self.tool_call_count}/{self.max_tool_calls}, "
            f"Read file: {self.read_file_count}/{self.max_read_file}, "
            f"Writes: {self.write_count}/{self.max_writes}"
        )
    
    def to_dict(self) -> dict:
        """Convert trace to dictionary for response."""
        return {
            "question": self.question,
            "tool_calls": [
                {"tool": tc.tool, "args": tc.args, "reason": tc.reason}
                for tc in self.tool_calls
            ],
            "files_opened": self.files_opened,
            "stop_reason": self.stop_reason,
            "budget_status": self.get_budget_status()
        }


def parse_response(content: str) -> dict:
    """
    Parse Claude's JSON response.
    
    Handles markdown code blocks and common LLM malformations.
    
    Args:
        content: Raw response content
        
    Returns:
        Parsed JSON object
        
    Raises:
        ValueError: If JSON cannot be parsed
    """
    content = content.strip()
    
    # Handle markdown code blocks
    if content.startswith("```"):
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
        if match:
            content = match.group(1).strip()
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # Try to find JSON object in the response
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            json_str = match.group()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # Try to fix common LLM malformations
                fixed_json = _fix_malformed_json(json_str)
                if fixed_json:
                    try:
                        return json.loads(fixed_json)
                    except json.JSONDecodeError:
                        pass
        raise ValueError(f"Failed to parse JSON response: {e}\nContent: {content[:500]}")


def _fix_malformed_json(json_str: str) -> Optional[str]:
    """
    Attempt to fix common JSON malformations from LLM output.
    
    Args:
        json_str: Potentially malformed JSON string
        
    Returns:
        Fixed JSON string or None if unfixable
    """
    # Fix duplicate key pattern: "key": "key": "value" -> "key": "value"
    fixed = re.sub(r'"(\w+)":\s*"\1":\s*', r'"\1": ', json_str)
    
    # Fix duplicate key pattern with different values
    fixed = re.sub(r'"(\w+)":\s*"(\w+)":\s*"', r'"\1": "', fixed)
    
    if fixed != json_str:
        logger.warning(f"Fixed malformed JSON: {json_str[:100]}... -> {fixed[:100]}...")
        return fixed
    
    return None


def parse_skill_frontmatter(content: str) -> tuple[dict, str]:
    """
    Parse YAML frontmatter from a SKILL.md file.
    
    Args:
        content: Full file content
        
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


def discover_skills(skills_path: Path, category: str) -> list[dict]:
    """
    Discover available skills in a category (Level 1 - metadata only).
    
    Scans the skills directory for skill folders and parses only
    the YAML frontmatter from each SKILL.md file.
    
    Args:
        skills_path: Base path to skills directory
        category: Skill category folder (e.g., "search", "update", "followup")
        
    Returns:
        List of skill metadata dicts with name, description, and path
    """
    skills = []
    skills_dir = skills_path / category
    
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
                metadata, _ = parse_skill_frontmatter(content)
                
                skills.append({
                    "name": metadata.get("name", skill_folder.name),
                    "description": metadata.get("description", ""),
                    "path": str(skill_md)
                })
            except Exception as e:
                logger.warning(f"Failed to parse skill {skill_folder.name}: {e}")
    
    logger.info(f"Discovered {len(skills)} skills in category '{category}'")
    return skills


def build_skills_xml(skills: list[dict]) -> str:
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
        # Escape any XML special characters in description
        desc = skill.get('description', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        lines.append(f"    <description>{desc}</description>")
        lines.append(f"    <location>{skill['path']}</location>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    
    return "\n".join(lines)


class BaseToolExecutor:
    """
    Base class for tool executors.
    
    Provides common file operations (read_file, list_files) that all agents need.
    Subclasses add agent-specific tools.
    """
    
    MAX_FILE_SIZE = 200 * 1024  # 200KB
    
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
    
    def validate_path(self, path: str) -> Path:
        """
        Validate that path stays within repo root.
        
        Args:
            path: The path to validate
            
        Returns:
            Resolved Path object
            
        Raises:
            ValueError: If path escapes repo root
        """
        if Path(path).is_absolute():
            resolved = Path(path).resolve()
        else:
            resolved = (self.repo_root / path).resolve()
        
        try:
            resolved.relative_to(self.repo_root)
        except ValueError:
            raise ValueError(f"Path escapes repo root: {path}")
        
        return resolved
    
    def read_file(self, path: str) -> str:
        """
        Read the full contents of a file.
        
        Args:
            path: File path to read
            
        Returns:
            File contents as string
        """
        resolved = self.validate_path(path)
        
        if not resolved.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        
        if not resolved.is_file():
            raise ValueError(f"Path is not a file: {path}")
        
        size = resolved.stat().st_size
        if size > self.MAX_FILE_SIZE:
            raise ValueError(f"File too large ({size} bytes > {self.MAX_FILE_SIZE} bytes): {path}")
        
        return resolved.read_text(encoding='utf-8')
    
    def list_files(self, path: str) -> list[str]:
        """
        List files and directories at the given path.
        
        Args:
            path: Directory path to list
            
        Returns:
            List of file/directory names
        """
        resolved = self.validate_path(path)
        
        if not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        
        if not resolved.is_dir():
            raise ValueError(f"Path is not a directory: {path}")
        
        items = []
        for item in sorted(resolved.iterdir()):
            name = item.name
            if item.is_dir():
                name += "/"
            items.append(name)
        
        return items
    
    def execute(self, tool: str, args: dict) -> str:
        """
        Execute a tool and return the result as a string.
        
        Base implementation handles read_file and list_files.
        Subclasses should override to add more tools.
        
        Args:
            tool: Tool name
            args: Tool arguments
            
        Returns:
            Result as string (JSON for structured data)
        """
        if tool == "read_file":
            return self.read_file(args.get("path", ""))
        
        elif tool == "list_files":
            result = self.list_files(args.get("path", ""))
            return json.dumps(result, indent=2)
        
        else:
            raise ValueError(f"Unknown tool: {tool}")


class BaseOrchestrator:
    """
    Base class for agent orchestrators.
    
    Provides common infrastructure:
    - Claude API calls with caching
    - Response parsing
    - Skill discovery
    - Main agent loop structure
    
    Subclasses implement:
    - build_system_prompt() with agent-specific tools and skills
    - Agent-specific response handling
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
        self.repo_root = self.mem_path.parent
        self.model = model
        
        # Initialize Anthropic client
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment or constructor")
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"Using Anthropic model: {model}")
        
        # Cache for skill discovery
        self._available_skills: Optional[list[dict]] = None
        self._system_prompt: Optional[str] = None
        
        # Query result cache
        self._query_cache: dict[str, tuple[dict, float]] = {}
        self._cache_ttl: float = 300.0  # 5 minute cache TTL
    
    def _discover_skills(self, category: str) -> list[dict]:
        """Discover skills in a category. Caches result."""
        if self._available_skills is None:
            self._available_skills = discover_skills(self.skills_path, category)
        return self._available_skills
    
    def _build_skills_xml(self, skills: list[dict]) -> str:
        """Build XML from skills list."""
        return build_skills_xml(skills)
    
    def build_system_prompt(self) -> str:
        """
        Build the system prompt for this agent.
        
        Must be implemented by subclasses.
        Should include:
        - Agent identity and purpose
        - Available skills XML
        - Tool definitions
        - Response format
        """
        raise NotImplementedError("Subclasses must implement build_system_prompt()")
    
    def build_messages(self, query: str, trace: Trace) -> list[dict]:
        """
        Build the message history for Claude.
        
        Args:
            query: User's question/command
            trace: Current exploration trace
            
        Returns:
            List of messages for Claude API
        """
        messages = []
        
        # Initial user message
        messages.append({
            "role": "user",
            "content": f"Request: {query}\n\nBegin. Respond with a single JSON object."
        })
        
        # Add tool call history
        for tc in trace.tool_calls:
            # Assistant's tool call
            messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "type": "tool_call",
                    "tool": tc.tool,
                    "args": tc.args,
                    "reason": tc.reason
                }, indent=2)
            })
            
            # Tool result
            if tc.error:
                result_content = f"Error: {tc.error}"
            else:
                result_content = f"Result:\n{tc.result}"
            
            messages.append({
                "role": "user",
                "content": result_content
            })
        
        # Budget reminder if getting close
        if trace.tool_call_count >= trace.max_tool_calls - 2:
            messages.append({
                "role": "user",
                "content": f"Note: Approaching tool call limit. {trace.get_budget_status()}. Finish soon."
            })
        
        return messages
    
    def call_claude(self, query: str, trace: Trace, max_retries: int = 2) -> dict:
        """
        Call Claude API and get response.
        
        Args:
            query: User's question/command
            trace: Current exploration trace
            max_retries: Number of retries on parse failure
            
        Returns:
            Parsed response dict
        """
        system_prompt = self.build_system_prompt()
        messages = self.build_messages(query, trace)
        
        logger.debug(f"Calling Claude with {len(messages)} messages")
        
        # Use prompt caching
        cached_system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]
        
        last_error = None
        for attempt in range(max_retries + 1):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=cached_system,
                messages=messages
            )
            
            content = response.content[0].text
            
            # Log cache usage
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
                cache_create = getattr(usage, 'cache_creation_input_tokens', 0) or 0
                if cache_read > 0:
                    logger.info(f"Prompt cache HIT: {cache_read} tokens")
                elif cache_create > 0:
                    logger.info(f"Prompt cache MISS: {cache_create} tokens cached")
            
            logger.debug(f"Claude response (attempt {attempt + 1}): {content[:200]}...")
            
            try:
                return parse_response(content)
            except ValueError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"JSON parse failed (attempt {attempt + 1}), retrying: {e}")
                    messages.append({
                        "role": "user",
                        "content": "Your response had invalid JSON. Respond with a valid JSON object only."
                    })
                else:
                    logger.error(f"JSON parse failed after {max_retries + 1} attempts")
        
        raise last_error
    
    def _get_query_hash(self, query: str) -> str:
        """Generate a hash for cache lookup."""
        normalized = query.strip().lower()
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def _get_cached_result(self, query: str) -> Optional[dict]:
        """Check cache for a recent result."""
        query_hash = self._get_query_hash(query)
        if query_hash in self._query_cache:
            result, timestamp = self._query_cache[query_hash]
            if time.time() - timestamp < self._cache_ttl:
                logger.info(f"Cache hit for query: {query[:50]}...")
                return result
            else:
                del self._query_cache[query_hash]
        return None
    
    def _cache_result(self, query: str, result: dict) -> None:
        """Cache a successful result."""
        query_hash = self._get_query_hash(query)
        self._query_cache[query_hash] = (result, time.time())
    
    def clear_cache(self) -> None:
        """Clear the query cache."""
        self._query_cache.clear()
        logger.info("Query cache cleared")
    
    def get_agent_name(self) -> str:
        """Return the agent name for streaming events. Override in subclasses."""
        return "agent"
    
    def create_trace(self) -> Trace:
        """Create a trace with appropriate budget limits. Override in subclasses."""
        return Trace(question="")
    
    def run_streaming(self, query: str) -> Generator[dict, None, None]:
        """
        Streaming version of run that yields events for real-time UI updates.
        
        Yields events:
        - {"type": "start", "query": str, "agent": str}
        - {"type": "thinking", "step": int, "tool": str, "args": dict, "reason": str}
        - {"type": "tool_result", "step": int, "tool": str, "result": str, "error": str|None}
        - {"type": "final", "answer": str, ...}
        - {"type": "error", "message": str}
        
        Args:
            query: User's question/command
            
        Yields:
            Event dictionaries for each step
        """
        # Create trace with agent-specific budget
        trace = self.create_trace()
        trace.question = query
        
        agent_name = self.get_agent_name()
        logger.info(f"Starting streaming {agent_name} for: {query}")
        
        # Emit start event
        yield {
            "type": "start",
            "query": query,
            "agent": agent_name,
            "budget": {
                "max_tool_calls": trace.max_tool_calls,
                "max_read_file": trace.max_read_file,
                "max_writes": trace.max_writes
            }
        }
        
        step = 0
        while not trace.is_budget_exhausted():
            try:
                response = self.call_claude(query, trace)
            except Exception as e:
                logger.error(f"Claude API error: {e}")
                trace.stop_reason = "error"
                yield {
                    "type": "error",
                    "message": str(e),
                    "trace": trace.to_dict()
                }
                return
            
            response_type = response.get("type")
            
            if response_type == "tool_call":
                tool = response.get("tool")
                args = response.get("args", {})
                reason = response.get("reason", "")
                step += 1
                
                logger.info(f"Tool call: {tool}({args}) - {reason}")
                
                # Emit thinking event (before execution)
                yield {
                    "type": "thinking",
                    "step": step,
                    "tool": tool,
                    "args": args,
                    "reason": reason,
                    "budget_status": trace.get_budget_status()
                }
                
                # Execute tool
                tool_call = ToolCall(tool=tool, args=args, reason=reason)
                
                try:
                    result = self.tool_executor.execute(tool, args)
                    tool_call.result = result
                    logger.debug(f"Tool result: {result[:200] if result else ''}...")
                except Exception as e:
                    tool_call.error = str(e)
                    logger.warning(f"Tool error: {e}")
                
                trace.add_tool_call(tool_call)
                
                # Emit tool result event
                yield {
                    "type": "tool_result",
                    "step": step,
                    "tool": tool,
                    "args": args,
                    "result": tool_call.result,
                    "error": tool_call.error,
                    "files_opened": trace.files_opened.copy(),
                    "budget_status": trace.get_budget_status()
                }
            
            elif response_type == "clarification":
                logger.info("Agent needs clarification from user")
                trace.stop_reason = "clarification_needed"
                
                yield {
                    "type": "clarification",
                    "question": response.get("question", "I need more information to proceed."),
                    "suggestions": response.get("suggestions", []),
                    "trace": trace.to_dict()
                }
                return
            
            elif response_type == "final":
                logger.info("Received final answer")
                trace.stop_reason = "final_answer"
                
                # Build final event - subclasses can add more fields
                final_event = {
                    "type": "final",
                    "answer": response.get("answer", ""),
                    "trace": trace.to_dict()
                }
                
                # Include any extra fields from the response
                for key in ["actions_taken", "changes_made", "citations", "notes"]:
                    if key in response:
                        final_event[key] = response[key]
                
                yield final_event
                return
            
            else:
                logger.warning(f"Unknown response type: {response_type}")
                continue
        
        # Budget exhausted
        logger.warning("Budget exhausted")
        trace.stop_reason = "budget_exhausted"
        
        yield {
            "type": "final",
            "answer": f"Operation limit reached. {trace.get_budget_status()}",
            "trace": trace.to_dict(),
            "budget_exhausted": True
        }
