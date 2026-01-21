#!/usr/bin/env python3
"""
Search across summary.md files for an account - a deterministic helper script.

This script searches through all source summaries without loading
full content into context.

Usage:
    python search_summaries.py <account_path> <search_term>
    
Example:
    python search_summaries.py mem/accounts/29040 "workers comp"
    
Output:
    JSON object with matching summaries
"""

import json
import os
import sys
from pathlib import Path


def search_summaries(account_path: str, search_term: str, max_results: int = 10) -> dict:
    """
    Search for a term across all summary.md files in an account.
    
    Args:
        account_path: Path to the account directory
        search_term: Term to search for (case-insensitive)
        max_results: Maximum number of results to return
        
    Returns:
        dict with matching files and snippets
    """
    account_dir = Path(account_path)
    sources_dir = account_dir / "sources"
    search_lower = search_term.lower()
    
    result = {
        "account_path": str(account_path),
        "search_term": search_term,
        "matches": [],
        "total_searched": 0
    }
    
    if not sources_dir.exists():
        result["error"] = "sources directory not found"
        return result
    
    # Search all summary.md files
    for summary_path in sources_dir.rglob("summary.md"):
        result["total_searched"] += 1
        
        try:
            content = summary_path.read_text(encoding='utf-8')
            if search_lower in content.lower():
                # Find matching lines
                lines = content.split('\n')
                matching_lines = []
                for i, line in enumerate(lines):
                    if search_lower in line.lower():
                        matching_lines.append({
                            "line_no": i + 1,
                            "content": line.strip()[:200]
                        })
                
                result["matches"].append({
                    "path": str(summary_path.relative_to(account_dir.parent)),
                    "matching_lines": matching_lines[:3]  # First 3 matches per file
                })
                
                if len(result["matches"]) >= max_results:
                    result["truncated"] = True
                    break
                    
        except Exception as e:
            continue
    
    return result


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: search_summaries.py <account_path> <search_term>"}))
        sys.exit(1)
    
    account_path = sys.argv[1]
    search_term = sys.argv[2]
    result = search_summaries(account_path, search_term)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
