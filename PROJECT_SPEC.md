# Project Specification

## Executive Summary

This is an AI-powered agentic system for insurance brokers that manages account memory through a filesystem-based architecture. The system uses Claude as the reasoning engine, Qdrant for semantic search, and a structured markdown-based memory format for transparency and auditability.

---

## Current Implementation (v3.0)

### How It Works Right now

The system currently has one agent: the **Search Agent**. This is a read-only assistant that answers questions about insurance accounts by exploring files stored on disk.

When a user asks a question like "What is the status of Sunny Days Childcare?", the agent:

1. Searches Qdrant to find which account folder matches that company name
2. Reads the account's `state.md` file to get current status
3. If needed, explores source files (emails, calls, SMS) for more details
4. Returns an answer with citations to the files it read

### Current Components

| Component | What It Does |
|-----------|--------------|
| **Orchestrator** | Runs the agent loop - sends queries to Claude, executes tools, tracks progress |
| **Name Registry** | Manages Qdrant vector database for finding accounts by name or description |
| **Ingestion Pipeline** | One-time script that converts raw account data into the filesystem structure |
| **Server** | REST API that accepts queries and returns answers |
| **Web UI** | Streamlit interface for interactive use |

### Available Tools

The Search Agent has 5 tools:

| Tool | Purpose |
|------|---------|
| `lookup_account` | Find accounts by company name (e.g., "Sunny Days Childcare") |
| `search_descriptions` | Find accounts by attributes like stage, location, or industry |
| `list_files` | See what files and folders exist at a path |
| `read_file` | Read the contents of a specific file |
| `search_files` | Search for text within files |

### File Structure

Each account is stored in its own folder with:

- **state.md** - Current account info (name, stage, contacts, coverage types)
- **history.md** - Log of changes over time with links to evidence
- **sources/** - Folder containing all communications
  - **emails/** - Each email has a summary and raw content
  - **calls/** - Each call has a transcript summary and raw transcript
  - **sms/** - Each SMS has a summary and raw content

### Qdrant Collections

Two collections enable fast semantic search:

| Collection | What It Stores |
|------------|----------------|
| `account_names` | Company names - used when user asks about a specific company |
| `account_descriptions` | Rich summaries including stage, location, industry - used for broader queries |

---

## Future Implementation (v3.1+)

### The Big Picture

Instead of one agent, the system will have a **Starter Agent** that routes queries to specialized agents based on what the user wants to do.

**User Query → Starter Agent → Routes to appropriate agent → Result**

### The Four Flows

#### 1. Starter Agent (Router)

This agent looks at the incoming query and decides where to send it:

| If the user wants to... | Route to... |
|------------------------|-------------|
| Ask a question, look something up | Search Agent |
| Update something, add a note, change status | Creation Agent |
| Process new incoming data (email, call, SMS) | Ingestion Agent |
| Query is unclear or matches multiple accounts | Clarification Flow |

The Starter Agent uses Claude to classify intent. It extracts key information like account names, requested actions, and any ambiguities.

#### 2. Search Agent (Current - Read Only)

This is what exists today. It answers questions by exploring the filesystem and returns grounded answers with citations.

**Enhancements planned:**
- Better handling when multiple accounts match a query
- Improved cross-account queries ("which accounts need follow-up?")
- Streaming responses for complex explorations

#### 3. Creation Agent (New - Write Operations)

This agent handles updates and changes to account memory.

**What it can do:**
- Update account state (change stage, add coverage type, update contacts)
- Add notes from conversations
- Record changes with timestamps and evidence links
- Write new source files (when a new email or call comes in)

**How history tracking works:**

When something changes, the Creation Agent:
1. Updates `state.md` with the new values
2. Appends an entry to `history.md` with:
   - Timestamp of the change
   - What changed (old value → new value)
   - Why it changed (LLM-generated summary)
   - Link to the evidence (which email/call/SMS triggered this)
   - Link to the previous history entry (creating a chain)
3. Regenerates the account description in Qdrant so search stays accurate

The history format is like a linked list - each entry points to the previous one, creating a complete audit trail.

#### 4. Ingestion Agent (New - Process New Data)

This agent handles new incoming communications and integrates them into account memory.

**Workflow:**

1. **Extract entities** - Parse the email/call/SMS to identify company name, contact info, dates, topics discussed

2. **Resolve to account** - Search existing accounts to find which one this belongs to. If no match, create a new account.

3. **Store the source** - Write the raw content and generate an LLM summary

4. **Detect state changes** - Analyze if this communication indicates a status change (e.g., "quote received" suggests stage should change to "Quoted")

5. **Update if needed** - Hand off to Creation Agent to update state and record in history

#### 5. Clarification Flow (Handle Ambiguity)

When a query can't be confidently processed, the system asks for clarification instead of guessing.

**Types of ambiguity handled:**

| Situation | Example | Response |
|-----------|---------|----------|
| Multiple account matches | "Update Sunny's status" matches 2 accounts | "I found 2 accounts matching 'Sunny'. Which one: Sunny Days Childcare or Sunny Side Landscaping?" |
| Unclear intent | "Sunny Days Childcare" | "Did you want to look up information or update something?" |
| Missing information | "Mark as quoted" | "Which account should I update, and what was the quoted premium?" |
| Conflicting info | "Change stage to Lead" (already Lead) | "This account is already in Lead stage. Did you mean something else?" |

The system maintains session state so the user can answer and resume where they left off.

---

## How the Agents Work Together

### Example: Answering a Question

User: "What is the status of Sunny Days Childcare?"

1. **Starter Agent** classifies this as a search query
2. **Search Agent** looks up the account, reads state.md, returns answer with citation

### Example: Updating Account Status

User: "Mark Sunny Days Childcare as Quoted, $2,600 premium"

1. **Starter Agent** classifies this as an update request
2. **Creation Agent** updates state.md, appends to history.md, refreshes Qdrant

### Example: Processing New Email

System receives new email from client

1. **Ingestion Agent** extracts entities, identifies account
2. **Ingestion Agent** stores email in sources/emails/
3. **Ingestion Agent** detects "quote received" in content
4. **Creation Agent** updates stage to "Quoted", records in history

### Example: Ambiguous Query

User: "Update Sunny"

1. **Starter Agent** searches and finds 2 matching accounts
2. **Clarification Flow** asks: "Which account: Sunny Days Childcare or Sunny Side Landscaping?"
3. User selects one
4. **Starter Agent** re-routes with clarified target

---

## Data Model Changes

### History File Format

The history.md file will use a linked list structure where each entry contains:

- **Timestamp** - When the change occurred
- **Summary** - LLM-generated explanation of what happened and why
- **Changes** - List of fields that changed with old and new values
- **Evidence** - Link to the source file that triggered the change
- **Previous** - Link to the previous history entry (creates the chain)

This allows complete traceability - you can start at any change and follow the chain back to the beginning.

### Qdrant Updates

When an account's state changes, its description in Qdrant is regenerated. This ensures that searching for "quoted accounts" or "accounts in Texas" returns accurate, current results.

---

## API Changes

### Current

One endpoint that handles all queries:
- `POST /query` - Send a question, get an answer

### Future

Multiple endpoints for explicit control:
- `POST /query` - Unified entry (auto-routes based on intent)
- `POST /search` - Direct to Search Agent
- `POST /update` - Direct to Creation Agent  
- `POST /ingest` - Direct to Ingestion Agent
- `POST /clarify` - Continue after a clarification prompt

When clarification is needed, the response includes options for the user to choose from and a session ID to continue the conversation.

---

## Development Phases

### Phase 1: Starter Agent + Clarification
- Build intent classification
- Handle multiple account matches gracefully
- Add session management for multi-turn clarification

### Phase 2: Creation Agent
- State update logic
- History tracking with linked list format
- Qdrant description refresh

### Phase 3: Ingestion Agent
- Entity extraction from raw content
- Account resolution
- State change detection

### Phase 4: Integration
- Unified API with smart routing
- Error handling across all agents
- Expanded evaluation suite

---

## Key Design Decisions

### Why Multiple Agents Instead of One?

**Safety:** Read operations (search) and write operations (create/update) have very different risk profiles. Separating them makes it harder to accidentally modify data.

**Clarity:** When the system explicitly classifies intent, both the user and the system are clear about what action is being taken.

**Scalability:** Adding new capabilities (like a reporting agent or a notification agent) is easier when agents are modular.

### Why Linked List History?

**Traceability:** Every change points to its evidence and the previous state, creating a complete audit trail.

**Queryability:** Can follow the chain to understand how an account evolved over time.

**Debugging:** Easy to see exactly what changed when and why.

### Why Regenerate Descriptions?

**Accuracy:** Descriptions should reflect current state plus recent activity, not stale information.

**Simplicity:** Full regeneration is simpler and more reliable than trying to incrementally update embeddings.

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Search query accuracy | >80% pass rate on L1/L2/L3 tests |
| State update consistency | 100% - no data corruption |
| Account resolution accuracy | >90% correct on ingestion |
| Clarification rate | <15% of queries need clarification |
| Response latency | <5 seconds average |
