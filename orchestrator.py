#!/usr/bin/env python3
"""
Orchestrator for Experiment 1: Pure Exploration Workflow Agent

Manages the Plan-Act-Observe loop between Claude and filesystem tools.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import time

# PyYAML for skill frontmatter parsing (optional)
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional, Generator, Any

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

# Budget constants - balanced for speed + multi-source queries
MAX_TOOL_CALLS = 10  # Enough for multi-source queries (was 15)
MAX_READ_FILE = 6    # Enough to read multiple sources (was 8)
MAX_SEARCH = 4       # Reduced from 6
MAX_FILE_SIZE = 200 * 1024  # 200KB
MAX_SEARCH_RESULTS = 20  # Reduced from 50


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
    """Tracks the exploration trace for a query."""
    question: str
    tool_calls: list = field(default_factory=list)
    files_opened: list = field(default_factory=list)
    stop_reason: str = ""
    invalid_citations_removed: list = field(default_factory=list)
    
    # Budget tracking
    read_file_count: int = 0
    search_count: int = 0
    
    @property
    def tool_call_count(self) -> int:
        return len(self.tool_calls)
    
    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the trace."""
        self.tool_calls.append(tool_call)
        
        # Track specific tool usage
        if tool_call.tool == "read_file":
            self.read_file_count += 1
            # Track opened files for citation validation
            path = tool_call.args.get("path", "")
            if path and tool_call.error is None:
                self.files_opened.append(path)
        elif tool_call.tool == "search_files":
            self.search_count += 1
    
    def is_budget_exhausted(self) -> bool:
        """Check if any budget limit has been reached."""
        return (
            self.tool_call_count >= MAX_TOOL_CALLS or
            self.read_file_count >= MAX_READ_FILE or
            self.search_count >= MAX_SEARCH
        )
    
    def get_budget_status(self) -> str:
        """Get a human-readable budget status."""
        return (
            f"Tool calls: {self.tool_call_count}/{MAX_TOOL_CALLS}, "
            f"Read file: {self.read_file_count}/{MAX_READ_FILE}, "
            f"Search: {self.search_count}/{MAX_SEARCH}"
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
            "invalid_citations_removed": self.invalid_citations_removed,
            "budget_status": self.get_budget_status()
        }


class ToolExecutor:
    """Executes file exploration tools with safety constraints."""
    
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        
        # Initialize name registry for fast account lookup
        self._name_registry = None
        try:
            self._name_registry = NameRegistry()
            logger.info("Connected to Qdrant name registry")
        except Exception as e:
            logger.warning(f"Could not connect to Qdrant: {e}")
            logger.warning("lookup_account tool will be unavailable")
    
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
        # Handle both absolute and relative paths
        if Path(path).is_absolute():
            resolved = Path(path).resolve()
        else:
            resolved = (self.repo_root / path).resolve()
        
        # Security check: ensure path is within repo root
        try:
            resolved.relative_to(self.repo_root)
        except ValueError:
            raise ValueError(f"Path escapes repo root: {path}")
        
        return resolved
    
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
        
        # Check file size
        size = resolved.stat().st_size
        if size > MAX_FILE_SIZE:
            raise ValueError(f"File too large ({size} bytes > {MAX_FILE_SIZE} bytes): {path}")
        
        return resolved.read_text(encoding='utf-8')
    
    def search_files(self, query: str, path: str) -> list[dict]:
        """
        Search for text in files under the given path.
        
        Uses ripgrep (rg) if available, falls back to Python implementation.
        
        Args:
            query: Search query (treated as literal string)
            path: Directory path to search in
            
        Returns:
            List of matches with path, line_no, snippet
        """
        resolved = self.validate_path(path)
        
        if not resolved.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        
        results = []
        
        # Try ripgrep first (faster)
        try:
            rg_results = self._search_with_ripgrep(query, resolved)
            return rg_results[:MAX_SEARCH_RESULTS]
        except (FileNotFoundError, subprocess.SubprocessError):
            pass
        
        # Fallback to Python implementation
        return self._search_with_python(query, resolved)[:MAX_SEARCH_RESULTS]
    
    def _search_with_ripgrep(self, query: str, path: Path) -> list[dict]:
        """Search using ripgrep."""
        result = subprocess.run(
            ["rg", "--json", "--fixed-strings", "--max-count", "100", query, str(path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        matches = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data["data"]
                    # Convert absolute path to relative
                    abs_path = match_data["path"]["text"]
                    try:
                        rel_path = str(Path(abs_path).relative_to(self.repo_root))
                    except ValueError:
                        rel_path = abs_path
                    
                    matches.append({
                        "path": rel_path,
                        "line_no": match_data["line_number"],
                        "snippet": match_data["lines"]["text"].strip()
                    })
            except (json.JSONDecodeError, KeyError):
                continue
        
        return matches
    
    def _search_with_python(self, query: str, path: Path) -> list[dict]:
        """Fallback Python-based search."""
        matches = []
        
        # Walk directory tree
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            
            # Skip binary files and large files
            try:
                if file_path.stat().st_size > MAX_FILE_SIZE:
                    continue
                
                content = file_path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, PermissionError):
                continue
            
            # Search line by line
            for line_no, line in enumerate(content.split('\n'), start=1):
                if query.lower() in line.lower():
                    try:
                        rel_path = str(file_path.relative_to(self.repo_root))
                    except ValueError:
                        rel_path = str(file_path)
                    
                    matches.append({
                        "path": rel_path,
                        "line_no": line_no,
                        "snippet": line.strip()[:200]  # Truncate long lines
                    })
                    
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        return matches
        
        return matches
    
    def lookup_account(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search for accounts by company name using semantic search.
        
        Args:
            query: Company name to search for
            top_k: Number of results to return
            
        Returns:
            List of matching accounts with scores
        """
        if self._name_registry is None:
            raise RuntimeError("Name registry not available. Ensure Qdrant is running.")
        
        return self._name_registry.search(query, top_k)
    
    def search_descriptions(self, query: str, top_k: int = 10) -> list[dict]:
        """
        Search for accounts by description (stage, location, industry, insurance type).
        
        Use for:
        - Implicit account references ("that childcare center in Texas")
        - Stage-based queries ("accounts in application phase")
        - Location queries ("accounts in California")
        - Industry queries ("security companies")
        - Insurance type queries ("workers comp accounts")
        
        Args:
            query: Descriptive search query
            top_k: Number of results to return
            
        Returns:
            List of matching accounts with descriptions and scores
        """
        if self._name_registry is None:
            raise RuntimeError("Name registry not available. Ensure Qdrant is running.")
        
        return self._name_registry.search_descriptions(query, top_k)
    
    def execute(self, tool: str, args: dict) -> str:
        """
        Execute a tool and return the result as a string.
        
        Args:
            tool: Tool name (list_files, read_file, search_files)
            args: Tool arguments
            
        Returns:
            Result as string (JSON for structured data)
        """
        if tool == "list_files":
            result = self.list_files(args.get("path", ""))
            return json.dumps(result, indent=2)
        
        elif tool == "read_file":
            return self.read_file(args.get("path", ""))
        
        elif tool == "search_files":
            result = self.search_files(
                args.get("query", ""),
                args.get("path", "")
            )
            return json.dumps(result, indent=2)
        
        elif tool == "lookup_account":
            result = self.lookup_account(
                args.get("query", ""),
                args.get("top_k", 5)
            )
            return json.dumps(result, indent=2)
        
        elif tool == "search_descriptions":
            result = self.search_descriptions(
                args.get("query", ""),
                args.get("top_k", 10)
            )
            return json.dumps(result, indent=2)
        
        else:
            raise ValueError(f"Unknown tool: {tool}")


class Orchestrator:
    """
    Main orchestrator that manages the Plan-Act-Observe loop.
    """
    
    def __init__(
        self,
        mem_path: str = "mem",
        api_key: Optional[str] = None,
        model: str = "claude-haiku-4-5-20251001"
    ):
        self.mem_path = Path(mem_path)
        self.repo_root = self.mem_path.parent
        self.tool_executor = ToolExecutor(str(self.repo_root))
        self.model = model
        
        # Initialize Anthropic client
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment or constructor")
        self.client = anthropic.Anthropic(api_key=api_key)
        logger.info(f"Using Anthropic model: {model}")
        
        # Cache skill content
        self._skill_content: Optional[str] = None
        self._skill_metadata: Optional[dict] = None
        
        # Legacy fallback
        self._system_rules: Optional[str] = None
        
        # Query result cache (query_hash -> (result, timestamp))
        self._query_cache: dict[str, tuple[dict, float]] = {}
        self._cache_ttl: float = 300.0  # 5 minute cache TTL
    
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
                    if HAS_YAML:
                        metadata = yaml.safe_load(parts[1])
                    else:
                        # Simple fallback parser for basic key: value pairs
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
    
    def load_skill(self, skill_name: str = "search") -> str:
        """
        Load a skill from the skills directory.
        
        Args:
            skill_name: Name of the skill folder (search, update, router)
            
        Returns:
            The skill content (body without frontmatter)
        """
        skill_path = self.mem_path / "skills" / skill_name / "SKILL.md"
        
        if not skill_path.exists():
            # Fallback to legacy system_rules.md
            logger.warning(f"Skill not found at {skill_path}, falling back to system_rules.md")
            return self.load_system_rules()
        
        content = skill_path.read_text(encoding='utf-8')
        metadata, body = self._parse_skill_frontmatter(content)
        
        self._skill_metadata = metadata
        logger.info(f"Loaded skill: {metadata.get('name', skill_name)}")
        
        return body
    
    def load_skill_context(self, skill_name: str, context_file: str) -> str:
        """
        Load additional context file from a skill directory.
        
        This enables progressive disclosure - loading extra context only when needed.
        
        Args:
            skill_name: Name of the skill folder
            context_file: Name of the context file (e.g., 'formatting.md')
            
        Returns:
            Content of the context file
        """
        context_path = self.mem_path / "skills" / skill_name / context_file
        
        if not context_path.exists():
            raise FileNotFoundError(f"Skill context not found: {context_path}")
        
        content = context_path.read_text(encoding='utf-8')
        logger.info(f"Loaded skill context: {skill_name}/{context_file}")
        return content
    
    def get_skill_metadata(self, skill_name: str = "search") -> dict:
        """
        Get just the metadata (name, description) from a skill.
        
        This is the first level of progressive disclosure - enough info
        to decide if the skill should be loaded.
        
        Args:
            skill_name: Name of the skill folder
            
        Returns:
            Metadata dict with 'name' and 'description'
        """
        skill_path = self.mem_path / "skills" / skill_name / "SKILL.md"
        
        if not skill_path.exists():
            return {"name": skill_name, "description": "Skill not found"}
        
        content = skill_path.read_text(encoding='utf-8')
        metadata, _ = self._parse_skill_frontmatter(content)
        return metadata
    
    def load_system_rules(self) -> str:
        """Load and cache system rules from mem/system_rules.md (legacy fallback)."""
        if self._system_rules is None:
            rules_path = self.mem_path / "system_rules.md"
            if not rules_path.exists():
                raise FileNotFoundError(f"System rules not found: {rules_path}")
            self._system_rules = rules_path.read_text(encoding='utf-8')
        return self._system_rules
    
    def build_system_prompt(self) -> str:
        """Build the full system prompt for Claude using the skill system."""
        # Try to load from skills first
        if self._skill_content is None:
            try:
                self._skill_content = self.load_skill("search")
            except Exception as e:
                logger.warning(f"Failed to load skill, using legacy system_rules: {e}")
                self._skill_content = self.load_system_rules()
        
        return self._skill_content
    
    def build_messages(self, query: str, trace: Trace) -> list[dict]:
        """
        Build the message history for Claude.
        
        Args:
            query: User's question
            trace: Current exploration trace
            
        Returns:
            List of messages for Claude API
        """
        messages = []
        
        # Initial user message with query
        messages.append({
            "role": "user",
            "content": f"Question: {query}\n\nBegin your exploration. Remember to respond with a single JSON object."
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
        
        # Add budget reminder if getting close to limits
        if trace.tool_call_count >= MAX_TOOL_CALLS - 2:
            messages.append({
                "role": "user",
                "content": f"Note: You are approaching the tool call limit. {trace.get_budget_status()}. Consider providing a final answer soon."
            })
        
        return messages
    
    def parse_response(self, content: str) -> dict:
        """
        Parse Claude's JSON response.
        
        Args:
            content: Raw response content
            
        Returns:
            Parsed JSON object
        """
        # Try to extract JSON from the response
        content = content.strip()
        
        # Handle markdown code blocks
        if content.startswith("```"):
            # Extract content between code fences
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
                    fixed_json = self._fix_malformed_json(json_str)
                    if fixed_json:
                        try:
                            return json.loads(fixed_json)
                        except json.JSONDecodeError:
                            pass
            raise ValueError(f"Failed to parse JSON response: {e}\nContent: {content[:500]}")
    
    def _fix_malformed_json(self, json_str: str) -> Optional[str]:
        """
        Attempt to fix common JSON malformations from LLM output.
        
        Args:
            json_str: Potentially malformed JSON string
            
        Returns:
            Fixed JSON string or None if unfixable
        """
        # Fix duplicate key pattern: "key": "key": "value" -> "key": "value"
        # This handles cases like "tool": "tool": "list_files"
        fixed = re.sub(r'"(\w+)":\s*"\1":\s*', r'"\1": ', json_str)
        
        # Fix duplicate key pattern with different values: "key": "other": "value"
        # E.g., "tool": "tool": "list_files" where first "tool" is key, second is erroneous
        fixed = re.sub(r'"(\w+)":\s*"(\w+)":\s*"', r'"\1": "', fixed)
        
        if fixed != json_str:
            logger.warning(f"Fixed malformed JSON: {json_str[:100]}... -> {fixed[:100]}...")
            return fixed
        
        return None
    
    def call_claude(self, query: str, trace: Trace, max_retries: int = 2) -> dict:
        """
        Call Claude API and get response.
        
        Args:
            query: User's question
            trace: Current exploration trace
            max_retries: Number of retries on parse failure
            
        Returns:
            Parsed response dict
        """
        system_prompt = self.build_system_prompt()
        messages = self.build_messages(query, trace)
        
        logger.debug(f"Calling Claude with {len(messages)} messages")
        
        # Use prompt caching for the system prompt
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
            
            # Log cache usage if available
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
                cache_create = getattr(usage, 'cache_creation_input_tokens', 0) or 0
                if cache_read > 0:
                    logger.info(f"Prompt cache HIT: {cache_read} tokens read from cache")
                elif cache_create > 0:
                    logger.info(f"Prompt cache MISS: {cache_create} tokens cached for next call")
            
            logger.debug(f"Claude response (attempt {attempt + 1}): {content[:200]}...")
            
            try:
                return self.parse_response(content)
            except ValueError as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(f"JSON parse failed (attempt {attempt + 1}), retrying: {e}")
                    messages.append({
                        "role": "user",
                        "content": "Your previous response had invalid JSON syntax. Please respond with a valid JSON object only."
                    })
                else:
                    logger.error(f"JSON parse failed after {max_retries + 1} attempts")
        
        raise last_error
    
    def validate_citations(self, citations: list, trace: Trace) -> list:
        """
        Validate citations against opened files.
        
        Args:
            citations: List of cited file paths
            trace: Current trace with files_opened
            
        Returns:
            List of valid citations
        """
        valid = []
        for citation in citations:
            if citation in trace.files_opened:
                valid.append(citation)
            else:
                trace.invalid_citations_removed.append(citation)
                logger.warning(f"Removed invalid citation (not opened): {citation}")
        
        return valid
    
    def build_response(self, final_response: dict, trace: Trace) -> dict:
        """
        Build the final response object.
        
        Args:
            final_response: Claude's final answer response
            trace: Exploration trace
            
        Returns:
            Complete response dict
        """
        # Validate citations
        raw_citations = final_response.get("citations", [])
        valid_citations = self.validate_citations(raw_citations, trace)
        
        response = {
            "answer": final_response.get("answer", ""),
            "citations": valid_citations,
            "notes": final_response.get("notes", ""),
            "trace_summary": final_response.get("trace_summary", []),
            "trace": trace.to_dict()
        }
        
        # Add warning if citations were removed
        if trace.invalid_citations_removed:
            if response["notes"]:
                response["notes"] += " "
            response["notes"] += f"Note: {len(trace.invalid_citations_removed)} citation(s) were omitted because the files weren't opened."
        
        return response
    
    def build_budget_exhausted_response(self, trace: Trace) -> dict:
        """
        Build a best-effort response when budget is exhausted.
        
        Args:
            trace: Exploration trace
            
        Returns:
            Response dict with partial information
        """
        # Summarize what was found
        files_read = [tc for tc in trace.tool_calls if tc.tool == "read_file" and not tc.error]
        
        answer = "Exploration limit reached. "
        if files_read:
            answer += f"I examined {len(files_read)} file(s) but could not complete the exploration. "
            answer += "Based on partial exploration:\n\n"
            
            # Try to provide some useful info from what was read
            for tc in files_read:
                answer += f"- Read: {tc.args.get('path')}\n"
        else:
            answer += "No files were successfully read before the limit was reached."
        
        return {
            "answer": answer,
            "citations": trace.files_opened,
            "notes": f"Budget exhausted: {trace.get_budget_status()}",
            "trace_summary": [f"Exploration stopped: {trace.get_budget_status()}"],
            "trace": trace.to_dict()
        }
    
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
                # Expired, remove from cache
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
    
    def run(self, query: str, use_cache: bool = True) -> dict:
        """
        Main entry point: run the exploration loop for a query.
        
        Args:
            query: User's question
            use_cache: Whether to use cached results (default True)
            
        Returns:
            Response dict with answer, citations, and trace
        """
        # Check cache first
        if use_cache:
            cached = self._get_cached_result(query)
            if cached:
                cached["from_cache"] = True
                return cached
        
        trace = Trace(question=query)
        logger.info(f"Starting exploration for query: {query}")
        
        while not trace.is_budget_exhausted():
            try:
                response = self.call_claude(query, trace)
            except Exception as e:
                logger.error(f"Claude API error: {e}")
                trace.stop_reason = "error"
                return {
                    "answer": f"An error occurred while processing your query: {e}",
                    "citations": [],
                    "notes": "API error",
                    "trace_summary": [],
                    "trace": trace.to_dict()
                }
            
            response_type = response.get("type")
            
            if response_type == "tool_call":
                tool = response.get("tool")
                args = response.get("args", {})
                reason = response.get("reason", "")
                
                logger.info(f"Tool call: {tool}({args}) - {reason}")
                
                # Execute tool
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
                result = self.build_response(response, trace)
                # Cache successful results
                if use_cache:
                    self._cache_result(query, result)
                return result
            
            else:
                logger.warning(f"Unknown response type: {response_type}")
                # Try to continue anyway
                continue
        
        # Budget exhausted
        logger.warning("Budget exhausted")
        trace.stop_reason = "budget_exhausted"
        return self.build_budget_exhausted_response(trace)
    
    def run_streaming(self, query: str) -> Generator[dict, None, None]:
        """
        Streaming version of run that yields exploration steps in real-time.
        
        Yields events:
        - {"type": "start", "query": str}
        - {"type": "thinking", "step": int, "tool": str, "args": dict, "reason": str}
        - {"type": "tool_result", "step": int, "tool": str, "result": str, "error": str|None}
        - {"type": "final", "answer": str, "citations": list, "notes": str, "trace": dict}
        - {"type": "error", "message": str}
        
        Args:
            query: User's question
            
        Yields:
            Event dictionaries for each step of exploration
        """
        trace = Trace(question=query)
        logger.info(f"Starting streaming exploration for query: {query}")
        
        # Emit start event
        yield {
            "type": "start",
            "query": query,
            "budget": {
                "max_tool_calls": MAX_TOOL_CALLS,
                "max_read_file": MAX_READ_FILE,
                "max_search": MAX_SEARCH
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
                    logger.debug(f"Tool result: {result[:200]}...")
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
                
            elif response_type == "final":
                logger.info("Received final answer")
                trace.stop_reason = "final_answer"
                result = self.build_response(response, trace)
                
                # Emit final event
                yield {
                    "type": "final",
                    "answer": result["answer"],
                    "citations": result["citations"],
                    "notes": result["notes"],
                    "trace_summary": result.get("trace_summary", []),
                    "trace": trace.to_dict()
                }
                return
            
            else:
                logger.warning(f"Unknown response type: {response_type}")
                continue
        
        # Budget exhausted
        logger.warning("Budget exhausted")
        trace.stop_reason = "budget_exhausted"
        result = self.build_budget_exhausted_response(trace)
        
        yield {
            "type": "final",
            "answer": result["answer"],
            "citations": result["citations"],
            "notes": result["notes"],
            "trace_summary": result.get("trace_summary", []),
            "trace": trace.to_dict(),
            "budget_exhausted": True
        }


def main():
    """CLI entry point for testing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run exploration agent query")
    parser.add_argument("query", help="The question to answer")
    parser.add_argument("--mem-path", default="mem", help="Path to mem directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    orchestrator = Orchestrator(mem_path=args.mem_path)
    result = orchestrator.run(args.query)
    
    print("\n" + "=" * 60)
    print("ANSWER")
    print("=" * 60)
    print(result["answer"])
    
    print("\n" + "-" * 60)
    print("CITATIONS")
    print("-" * 60)
    for citation in result["citations"]:
        print(f"  - {citation}")
    
    if result["notes"]:
        print("\n" + "-" * 60)
        print("NOTES")
        print("-" * 60)
        print(result["notes"])
    
    print("\n" + "-" * 60)
    print("TRACE")
    print("-" * 60)
    for tc in result["trace"]["tool_calls"]:
        print(f"  {tc['tool']}({tc['args']}) - {tc['reason']}")
    print(f"\nStop reason: {result['trace']['stop_reason']}")
    print(f"Budget: {result['trace']['budget_status']}")
    
    if result["trace"]["invalid_citations_removed"]:
        print(f"\nInvalid citations removed: {result['trace']['invalid_citations_removed']}")


if __name__ == "__main__":
    main()
