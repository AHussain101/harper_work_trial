#!/usr/bin/env python3
"""
Count sources for an account - a deterministic helper script.

This script can be executed by Claude to get accurate source counts
without loading file contents into context.

Usage:
    python count_sources.py <account_path>
    
Example:
    python count_sources.py mem/accounts/29040
    
Output:
    JSON object with source counts and latest source info
"""

import json
import os
import sys
from pathlib import Path


def count_sources(account_path: str) -> dict:
    """
    Count sources (emails, calls, SMS) for an account.
    
    Args:
        account_path: Path to the account directory
        
    Returns:
        dict with counts and latest source info
    """
    account_dir = Path(account_path)
    sources_dir = account_dir / "sources"
    
    result = {
        "account_path": str(account_path),
        "sources": {
            "emails": {"count": 0, "latest": None},
            "calls": {"count": 0, "latest": None},
            "sms": {"count": 0, "latest": None}
        },
        "total": 0
    }
    
    if not sources_dir.exists():
        result["error"] = "sources directory not found"
        return result
    
    for source_type in ["emails", "calls", "sms"]:
        type_dir = sources_dir / source_type
        if not type_dir.exists():
            continue
            
        # Count subdirectories (each source is a folder)
        sources = [d for d in type_dir.iterdir() if d.is_dir()]
        result["sources"][source_type]["count"] = len(sources)
        result["total"] += len(sources)
        
        # Find latest (highest ID, roughly chronological)
        if sources:
            latest = max(sources, key=lambda x: x.name)
            result["sources"][source_type]["latest"] = str(latest.relative_to(account_dir))
    
    return result


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: count_sources.py <account_path>"}))
        sys.exit(1)
    
    account_path = sys.argv[1]
    result = count_sources(account_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
