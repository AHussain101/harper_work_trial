#!/usr/bin/env python3
"""
Harper Super Day - Self-Evaluation Script

Usage:
    python evaluate.py <endpoint_url>
    python evaluate.py http://localhost:8000/query

This script tests your memory system against sample queries and reports:
- L1: Single-account query accuracy
- L2: Source attribution (grounding)
- L3: Cross-account query capability
- Latency metrics

Note: This is a simplified evaluation for self-testing.
Full assessment includes qualitative review of architecture and reasoning.
"""

import argparse
import json
import time
import sys
from typing import Dict, List, Any, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


# ============================================================
# EVALUATION QUERIES
# ============================================================

EVAL_QUERIES = [
    # Level 1: Single Account Queries
    {
        "query": "What is the current status of Sunny Days Childcare's application?",
        "level": 1,
        "expected_keywords": ["application", "received", "intake", "stage"],
        "description": "Basic account status query"
    },
    {
        "query": "What coverage types does Sunny Days Childcare have?",
        "level": 1,
        "expected_keywords": ["general liability", "GL", "liability"],
        "description": "Coverage type retrieval"
    },
    {
        "query": "When did we last communicate with Sunny Days Childcare?",
        "level": 1,
        "expected_keywords": ["email", "call", "sms", "contact", "message"],
        "description": "Communication history"
    },

    # Level 2: Observable Reasoning
    {
        "query": "Summarize all communication with Sunny Days Childcare about their coverage.",
        "level": 2,
        "expected_keywords": ["email", "source", "based on"],
        "requires_sources": True,
        "description": "Multi-source synthesis with attribution"
    },
    {
        "query": "Give me a complete picture of where we are with Sunny Days Childcare.",
        "level": 2,
        "expected_keywords": ["stage", "status", "next", "pending"],
        "requires_sources": True,
        "description": "Comprehensive account summary"
    },

    # Level 3: Cross-Account Reasoning
    {
        "query": "Which accounts in the application phase need follow-up?",
        "level": 3,
        "expected_type": "list",
        "description": "Cross-account aggregation"
    },
    {
        "query": "What's the oldest outstanding document request we have?",
        "level": 3,
        "expected_keywords": ["account", "document", "days", "waiting"],
        "description": "Brokerage-level query"
    },
    {
        "query": "That childcare center in Texas - where are they in the process?",
        "level": 3,
        "expected_keywords": ["sunny days", "childcare", "stage", "application"],
        "description": "Implicit account resolution"
    },
]


# ============================================================
# EVALUATION FUNCTIONS
# ============================================================

def send_query(endpoint: str, query: str, timeout: int = 60) -> Dict[str, Any]:
    """Send a query to the endpoint and return the response."""
    try:
        data = json.dumps({"query": query}).encode('utf-8')
        req = Request(
            endpoint,
            data=data,
            headers={'Content-Type': 'application/json'}
        )

        start_time = time.time()
        with urlopen(req, timeout=timeout) as response:
            latency_ms = (time.time() - start_time) * 1000
            result = json.loads(response.read().decode('utf-8'))
            result['_latency_ms'] = latency_ms
            return result

    except HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "_latency_ms": -1}
    except URLError as e:
        return {"error": f"Connection failed: {e.reason}", "_latency_ms": -1}
    except json.JSONDecodeError:
        return {"error": "Invalid JSON response", "_latency_ms": -1}
    except Exception as e:
        return {"error": str(e), "_latency_ms": -1}


def check_keywords(response_text: str, keywords: List[str]) -> bool:
    """Check if response contains expected keywords (case-insensitive)."""
    response_lower = response_text.lower()
    return any(kw.lower() in response_lower for kw in keywords)


def check_has_sources(response: Dict[str, Any]) -> bool:
    """Check if response includes source citations."""
    # Check common patterns for source attribution
    response_str = json.dumps(response).lower()

    source_indicators = [
        "source", "email_id", "call_id", "sms_id", "record",
        "based on", "according to", "from the", "referenced",
        "evidence", "citation"
    ]

    return any(ind in response_str for ind in source_indicators)


def evaluate_query(endpoint: str, query_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a single query against the endpoint."""
    result = {
        "query": query_spec["query"],
        "level": query_spec["level"],
        "description": query_spec.get("description", ""),
        "passed": False,
        "latency_ms": -1,
        "details": ""
    }

    response = send_query(endpoint, query_spec["query"])

    if "error" in response:
        result["details"] = f"Error: {response['error']}"
        return result

    result["latency_ms"] = response.get("_latency_ms", -1)

    # Extract response text (handle various response formats)
    response_text = ""
    if isinstance(response.get("answer"), str):
        response_text = response["answer"]
    elif isinstance(response.get("response"), str):
        response_text = response["response"]
    elif isinstance(response.get("result"), str):
        response_text = response["result"]
    else:
        response_text = json.dumps(response)

    # Check keywords if specified
    if "expected_keywords" in query_spec:
        if check_keywords(response_text, query_spec["expected_keywords"]):
            result["passed"] = True
            result["details"] = "Contains expected keywords"
        else:
            result["details"] = f"Missing expected keywords: {query_spec['expected_keywords']}"

    # Check for sources if required
    if query_spec.get("requires_sources"):
        if not check_has_sources(response):
            result["passed"] = False
            result["details"] += " | Missing source attribution"
        else:
            result["details"] += " | Has source attribution"

    # Check for list response if expected
    if query_spec.get("expected_type") == "list":
        if isinstance(response.get("accounts"), list) or "[" in response_text:
            result["passed"] = True
            result["details"] = "Returns list of accounts"
        else:
            result["details"] = "Expected list response"

    return result


def run_evaluation(endpoint: str) -> Dict[str, Any]:
    """Run full evaluation suite."""
    results = {
        "endpoint": endpoint,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "queries": [],
        "summary": {
            "l1_total": 0, "l1_passed": 0,
            "l2_total": 0, "l2_passed": 0,
            "l3_total": 0, "l3_passed": 0,
            "avg_latency_ms": 0
        }
    }

    latencies = []

    for query_spec in EVAL_QUERIES:
        print(f"  Testing L{query_spec['level']}: {query_spec.get('description', query_spec['query'][:50])}...")

        query_result = evaluate_query(endpoint, query_spec)
        results["queries"].append(query_result)

        level = query_spec["level"]
        results["summary"][f"l{level}_total"] += 1
        if query_result["passed"]:
            results["summary"][f"l{level}_passed"] += 1

        if query_result["latency_ms"] > 0:
            latencies.append(query_result["latency_ms"])

    if latencies:
        results["summary"]["avg_latency_ms"] = sum(latencies) / len(latencies)

    return results


def print_results(results: Dict[str, Any]):
    """Print evaluation results in a readable format."""
    print("\n" + "=" * 60)
    print("HARPER SUPER DAY - EVALUATION RESULTS")
    print("=" * 60)

    summary = results["summary"]

    # Level scores
    print("\nSCORES BY LEVEL:")
    print("-" * 40)

    for level in [1, 2, 3]:
        total = summary[f"l{level}_total"]
        passed = summary[f"l{level}_passed"]
        pct = (passed / total * 100) if total > 0 else 0
        status = "PASS" if pct >= 50 else "NEEDS WORK"
        print(f"  Level {level}: {passed}/{total} ({pct:.0f}%) - {status}")

    # Latency
    print(f"\nAVERAGE LATENCY: {summary['avg_latency_ms']:.0f}ms", end="")
    if summary['avg_latency_ms'] < 5000:
        print(" (Good)")
    elif summary['avg_latency_ms'] < 10000:
        print(" (Acceptable)")
    else:
        print(" (Slow - consider optimization)")

    # Detailed results
    print("\nDETAILED RESULTS:")
    print("-" * 40)

    for q in results["queries"]:
        status = "PASS" if q["passed"] else "FAIL"
        print(f"\n  [{status}] L{q['level']}: {q['description']}")
        print(f"       Query: {q['query'][:60]}...")
        print(f"       {q['details']}")
        if q["latency_ms"] > 0:
            print(f"       Latency: {q['latency_ms']:.0f}ms")

    # Overall assessment
    print("\n" + "=" * 60)
    total_passed = sum(summary[f"l{l}_passed"] for l in [1, 2, 3])
    total_queries = sum(summary[f"l{l}_total"] for l in [1, 2, 3])
    overall_pct = (total_passed / total_queries * 100) if total_queries > 0 else 0

    print(f"OVERALL: {total_passed}/{total_queries} ({overall_pct:.0f}%)")

    if overall_pct >= 75:
        print("STATUS: Strong - ready for presentation")
    elif overall_pct >= 50:
        print("STATUS: Good progress - focus on failing areas")
    else:
        print("STATUS: Needs work - review Level 1 basics first")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Harper Super Day - Self-Evaluation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python evaluate.py http://localhost:8000/query
    python evaluate.py http://localhost:3000/api/chat

Your endpoint should accept POST requests with JSON body:
    {"query": "your question here"}

And return JSON with the answer:
    {"answer": "response text", "sources": [...]}
        """
    )

    parser.add_argument(
        "endpoint",
        help="URL of your query endpoint (e.g., http://localhost:8000/query)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON results instead of formatted text"
    )

    args = parser.parse_args()

    print(f"\nHarper Super Day Evaluation")
    print(f"Testing endpoint: {args.endpoint}")
    print("-" * 40)

    results = run_evaluation(args.endpoint)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_results(results)


if __name__ == "__main__":
    main()