#!/usr/bin/env python3
"""
Streamlit UI for Experiment 1: Pure Exploration Workflow Agent

A web interface for asking questions and exploring the filesystem memory.
Includes speed testing functionality with sample query buttons.
"""

import os
import threading
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from orchestrator import Orchestrator

# Load environment variables from .env file
load_dotenv()

# Sample queries organized by level/category
SAMPLE_QUERIES = {
    "Level 1: Single Account Queries": {
        "Basic Status": [
            "What is the current status of Sunny Days Childcare's application?",
            "When did we last communicate with Sunny Days Childcare?",
            "What coverage types does Sunny Days Childcare have?",
        ],
        "Document Tracking": [
            "What documents are we waiting for from Sunny Days Childcare?",
            "What is the employee count for Sunny Days Childcare?",
            "Who is the primary contact at Blue Sky Homecare Services?",
        ],
        "Communication History": [
            "Show me the recent emails with Lakeview Concierge Services",
            "What was discussed in the last call with Sunny Days Childcare?",
            "Has SafeGuard Solutions LLC responded to our last message?",
        ],
    },
    "Level 2: Cross-Channel & Observable Reasoning": {
        "Multi-Source Synthesis": [
            "Summarize all communication with Sunny Days Childcare about their coverage.",
            "What did the customer say in the call versus what's in the emails for Sunny Days Childcare?",
            "Give me a complete picture of where we are with Brightside Playthings LLC.",
        ],
        "Conflict Detection": [
            "Are there any inconsistencies in the data for Sunny Days Childcare?",
            "What's the staff count for Sunny Days Childcare based on the call transcript?",
        ],
        "Source Attribution": [
            "What sources did you use to determine Sunny Days Childcare's stage?",
            "Show me the evidence for Boardman Diner & Cafe's current stage.",
        ],
    },
    "Level 3: Cross-Account & Implicit Resolution": {
        "Brokerage-Level": [
            "Which accounts in the application phase need follow-up?",
            "What's the oldest outstanding document request we have?",
            "How many accounts are submitted to underwriter?",
            "List all accounts that are in Lead Ingested stage.",
        ],
        "Implicit Account Resolution": [
            "That childcare center in Texas - where are they in the process?",
            "The security company that needs follow-up",
            "The diner we were working with on their quote",
        ],
        "Aggregation": [
            "What's our pipeline breakdown by stage?",
            "Which accounts have received quotes from carriers?",
            "What are the most common coverage types being requested?",
        ],
    },
    "Follow-Up Agent Queries": {
        "Follow-Up Identification": [
            "What follow-up should we do for Sunny Days Childcare?",
            "Which accounts need follow-up today?",
            "What's the most urgent follow-up in our queue?",
        ],
        "Action Drafting": [
            "Draft an email to the underwriter requesting a quote for SafeGuard Solutions LLC.",
            "Write a follow-up SMS to Sunny Days Childcare about their pending documents.",
            "Create a call script for checking in with Sentinel Patrol Services about their application.",
        ],
        "Channel Appropriateness": [
            "Should we call or email Sunny Days Childcare about their background check documents?",
            "What's the best way to reach out to Blue Sky Technologies LLC?",
        ],
    },
    "Edge Cases": {
        "Ambiguous": [
            "What's happening with the childcare center?",
            "Tell me about the home care company",
        ],
        "Temporal Reasoning": [
            "What changed in Sunny Days Childcare's situation since December 5th?",
            "Has the customer uploaded any documents recently?",
        ],
        "Missing Information": [
            "What do we NOT know about SafeGuard Solutions LLC that we should?",
            "What information is missing from Johnson Engineering's application?",
        ],
    },
    "Data Exploration": {
        "Exploration": [
            "What industries are represented in our accounts?",
            "How many accounts do we have in each stage?",
            "What carriers have provided quotes?",
            "Which accounts have phone call transcripts?",
            "What are the quote amounts we've received?",
        ],
    },
}

# Page configuration
st.set_page_config(
    page_title="Harper Exploration Agent",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .stAlert {
        margin-top: 1rem;
    }
    .citation-box {
        background-color: #f0f2f6;
        border-radius: 0.5rem;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    .tool-call {
        font-family: monospace;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)


def preview_file(path: str, max_lines: int = 50) -> str:
    """
    Read file and return preview for citation expansion.
    
    Args:
        path: File path to preview
        max_lines: Maximum number of lines to show
        
    Returns:
        File content preview as string
    """
    try:
        full_path = Path(path)
        if not full_path.exists():
            # Try relative to current directory
            full_path = Path.cwd() / path
        
        content = full_path.read_text(encoding='utf-8')
        lines = content.split('\n')
        
        if len(lines) > max_lines:
            preview_lines = lines[:max_lines]
            preview_lines.append(f"\n... ({len(lines) - max_lines} more lines)")
            return '\n'.join(preview_lines)
        
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def init_session_state():
    """Initialize session state variables."""
    if 'last_result' not in st.session_state:
        st.session_state.last_result = None
    if 'query_history' not in st.session_state:
        st.session_state.query_history = []
    if 'orchestrator' not in st.session_state:
        st.session_state.orchestrator = None
    if 'last_execution_time' not in st.session_state:
        st.session_state.last_execution_time = None
    if 'query_timings' not in st.session_state:
        st.session_state.query_timings = []
    if 'selected_query' not in st.session_state:
        st.session_state.selected_query = None


def get_orchestrator() -> Orchestrator:
    """Get or create the orchestrator instance."""
    if st.session_state.orchestrator is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            st.error("ANTHROPIC_API_KEY environment variable not set. Please set it and restart the app.")
            st.stop()
        
        try:
            st.session_state.orchestrator = Orchestrator(mem_path="mem", api_key=api_key)
        except Exception as e:
            st.error(f"Failed to initialize orchestrator: {e}")
            st.stop()
    
    return st.session_state.orchestrator


def run_query(query: str):
    """Run a query through the orchestrator with timing and live progress."""
    orchestrator = get_orchestrator()
    
    # Storage for thread results
    thread_result = {"result": None, "error": None, "done": False}
    
    def run_in_thread():
        """Execute the query in a background thread."""
        try:
            thread_result["result"] = orchestrator.run(query)
        except Exception as e:
            thread_result["error"] = e
        finally:
            thread_result["done"] = True
    
    # Start the query in a background thread
    query_thread = threading.Thread(target=run_in_thread)
    start_time = time.perf_counter()
    query_thread.start()
    
    # Show live progress with timer
    status_messages = [
        "Searching for relevant accounts...",
        "Reading account files...",
        "Analyzing information...",
        "Preparing response...",
    ]
    
    with st.status("Processing query...", expanded=True) as status:
        timer_placeholder = st.empty()
        message_placeholder = st.empty()
        
        message_idx = 0
        last_message_change = start_time
        
        # Update timer while query runs
        while not thread_result["done"]:
            elapsed = time.perf_counter() - start_time
            
            # Update the timer display
            timer_placeholder.markdown(f"⏱️ **Elapsed: {elapsed:.1f}s**")
            
            # Cycle through status messages every 2 seconds
            if elapsed - (message_idx * 2) >= 2 and message_idx < len(status_messages) - 1:
                message_idx += 1
            message_placeholder.markdown(f"_{status_messages[message_idx]}_")
            
            time.sleep(0.1)  # Update every 100ms
        
        # Query finished
        end_time = time.perf_counter()
        execution_time = end_time - start_time
        
        if thread_result["error"]:
            status.update(label=f"Query failed after {execution_time:.1f}s", state="error")
            timer_placeholder.empty()
            message_placeholder.empty()
        else:
            # Check if from cache
            from_cache = thread_result["result"].get("from_cache", False)
            if from_cache:
                status.update(label=f"Completed in {execution_time:.1f}s (cached)", state="complete")
            else:
                status.update(label=f"Completed in {execution_time:.1f}s", state="complete")
            timer_placeholder.empty()
            message_placeholder.empty()
    
    # Wait for thread to fully complete
    query_thread.join()
    
    # Process results
    if thread_result["error"]:
        st.error(f"Error running query: {thread_result['error']}")
        st.session_state.last_result = None
        st.session_state.last_execution_time = execution_time
        
        # Record failed query timing
        timing_entry = {
            "query": query,
            "execution_time": execution_time,
            "timestamp": time.time(),
            "success": False,
            "error": str(thread_result["error"])
        }
        st.session_state.query_timings.append(timing_entry)
    else:
        result = thread_result["result"]
        st.session_state.last_result = result
        st.session_state.last_execution_time = execution_time
        
        # Store timing data
        timing_entry = {
            "query": query,
            "execution_time": execution_time,
            "timestamp": time.time(),
            "success": True
        }
        st.session_state.query_timings.append(timing_entry)
        
        # Update query history with timing
        st.session_state.query_history.append({
            "query": query,
            "result": result,
            "execution_time": execution_time
        })


def render_answer_panel(result: dict):
    """Render the answer panel."""
    st.subheader("Answer")
    
    # Main answer
    answer = result.get("answer", "No answer available")
    st.markdown(answer)
    
    # Notes/caveats
    notes = result.get("notes", "")
    if notes:
        st.info(f"**Notes:** {notes}")


def render_citations_panel(result: dict):
    """Render the citations panel with expandable file previews."""
    st.subheader("Citations")
    
    citations = result.get("citations", [])
    
    if not citations:
        st.write("*No citations*")
        return
    
    for citation in citations:
        with st.expander(f"📄 {citation}"):
            preview = preview_file(citation)
            st.code(preview, language=None)


def render_trace_summary_panel(result: dict):
    """Render the trace summary panel."""
    st.subheader("Trace Summary")
    
    trace_summary = result.get("trace_summary", [])
    
    if not trace_summary:
        st.write("*No trace summary*")
        return
    
    for i, step in enumerate(trace_summary, 1):
        st.write(f"{i}. {step}")


def render_tool_calls_panel(result: dict):
    """Render the tool calls panel."""
    with st.expander("🔧 Tool Calls", expanded=False):
        trace = result.get("trace", {})
        tool_calls = trace.get("tool_calls", [])
        
        if not tool_calls:
            st.write("*No tool calls*")
            return
        
        for i, tc in enumerate(tool_calls, 1):
            tool = tc.get("tool", "unknown")
            args = tc.get("args", {})
            reason = tc.get("reason", "")
            
            # Format arguments
            args_str = ", ".join(f'{k}="{v}"' for k, v in args.items())
            
            st.markdown(f"**{i}. `{tool}({args_str})`**")
            if reason:
                st.write(f"   *Reason: {reason}*")
            st.divider()


def render_debug_panel(result: dict):
    """Render the debug info panel."""
    with st.expander("🐛 Debug Info", expanded=False):
        trace = result.get("trace", {})
        
        # Stop reason
        stop_reason = trace.get("stop_reason", "unknown")
        st.write(f"**Stop Reason:** `{stop_reason}`")
        
        # Budget status
        budget_status = trace.get("budget_status", "")
        if budget_status:
            st.write(f"**Budget:** {budget_status}")
        
        # Files opened
        files_opened = trace.get("files_opened", [])
        st.write(f"**Files Opened ({len(files_opened)}):**")
        if files_opened:
            for f in files_opened:
                st.write(f"  - `{f}`")
        else:
            st.write("  *None*")
        
        # Invalid citations removed
        invalid = trace.get("invalid_citations_removed", [])
        if invalid:
            st.warning(f"**Invalid Citations Removed ({len(invalid)}):**")
            for c in invalid:
                st.write(f"  - `{c}`")


def format_time(seconds: float) -> str:
    """Format execution time for display."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"


def render_query_buttons():
    """Render the sample queries section with clickable buttons."""
    with st.expander("Sample Queries (Speed Test)", expanded=False):
        st.markdown("Click any query below to run it and measure execution time.")
        
        for level_name, categories in SAMPLE_QUERIES.items():
            st.markdown(f"### {level_name}")
            
            for category_name, queries in categories.items():
                st.markdown(f"**{category_name}**")
                
                # Create columns for buttons (2 columns for better layout)
                cols = st.columns(2)
                
                for idx, query in enumerate(queries):
                    col = cols[idx % 2]
                    with col:
                        # Truncate long queries for button display
                        display_text = query[:60] + "..." if len(query) > 60 else query
                        button_key = f"query_{level_name}_{category_name}_{idx}"
                        
                        if st.button(display_text, key=button_key, use_container_width=True):
                            st.session_state.selected_query = query
                            run_query(query)
                            st.rerun()
            
            st.divider()


def render_performance_metrics():
    """Render the performance metrics panel."""
    timings = st.session_state.query_timings
    
    if not timings:
        return
    
    with st.expander("Performance Metrics", expanded=False):
        # Calculate statistics
        successful_timings = [t["execution_time"] for t in timings if t.get("success", True)]
        
        if successful_timings:
            total_queries = len(timings)
            successful_queries = len(successful_timings)
            avg_time = sum(successful_timings) / len(successful_timings)
            min_time = min(successful_timings)
            max_time = max(successful_timings)
            
            # Display metrics in columns
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Queries", total_queries)
            with col2:
                st.metric("Avg Time", format_time(avg_time))
            with col3:
                st.metric("Fastest", format_time(min_time))
            with col4:
                st.metric("Slowest", format_time(max_time))
            
            # Show recent query timings
            st.markdown("**Recent Queries:**")
            
            # Show last 10 queries
            recent = list(reversed(timings[-10:]))
            for entry in recent:
                status = "Success" if entry.get("success", True) else "Failed"
                query_preview = entry["query"][:50] + "..." if len(entry["query"]) > 50 else entry["query"]
                time_str = format_time(entry["execution_time"])
                
                if entry.get("success", True):
                    st.write(f"- `{time_str}` - {query_preview}")
                else:
                    st.write(f"- `{time_str}` - {query_preview} (Failed)")
            
            # Clear history button
            if st.button("Clear Performance History"):
                st.session_state.query_timings = []
                st.rerun()
        else:
            st.write("No successful queries yet.")


def render_timing_display():
    """Render the timing display for the last query."""
    execution_time = st.session_state.last_execution_time
    result = st.session_state.last_result
    
    if execution_time is not None:
        time_str = format_time(execution_time)
        # Check if result was from cache
        from_cache = result.get("from_cache", False) if result else False
        if from_cache:
            st.success(f"Query completed in **{time_str}** (cached)")
        else:
            st.success(f"Query completed in **{time_str}**")


def main():
    """Main application entry point."""
    init_session_state()
    
    # Header
    st.title("Harper Exploration Agent")
    st.markdown("Ask questions about accounts in the filesystem memory. The agent will explore and find answers.")
    
    # Input section
    st.divider()
    
    col_input, col_button = st.columns([5, 1])
    
    with col_input:
        query = st.text_input(
            "Question",
            placeholder="e.g., What is the status of Sunny Days Childcare?",
            label_visibility="collapsed"
        )
    
    with col_button:
        run_button = st.button("Run", type="primary", use_container_width=True)
    
    # Run query on button click or Enter
    if run_button and query:
        run_query(query)
    
    # Sample Queries Section (Speed Test)
    render_query_buttons()
    
    # Performance Metrics Section
    render_performance_metrics()
    
    # Display results
    st.divider()
    
    result = st.session_state.last_result
    
    if result is None:
        st.info("Enter a question above and click Run to start exploring. Or use the Sample Queries above to test performance.")
        return
    
    # Timing display
    render_timing_display()
    
    # Answer panel
    render_answer_panel(result)
    
    st.divider()
    
    # Citations and Trace Summary side by side
    col1, col2 = st.columns([2, 1])
    
    with col1:
        render_citations_panel(result)
    
    with col2:
        render_trace_summary_panel(result)
    
    st.divider()
    
    # Tool calls panel (expandable)
    render_tool_calls_panel(result)
    
    # Debug info panel (expandable)
    render_debug_panel(result)


if __name__ == "__main__":
    main()
