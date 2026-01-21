# Project Specification

## Executive Summary

This is an AI-powered agentic system for insurance brokers that manages account memory through a filesystem-based architecture. The system uses Claude as the reasoning engine, Qdrant for semantic search, and a structured markdown-based memory format for transparency and auditability.

---

## Current Implementation (v3.3)

### Architecture Overview

The system uses a multi-agent architecture with the **Starter Agent** as the entry point:

```
User Query → Starter Agent → Routes to appropriate agent → Result
                 ↓
         Intent Classification
                 ↓
    ┌───────────┴───────────┐
    ↓                       ↓
Search Agent           Updater Agent
(read-only)            (write operations)
```

### The Three Agents

#### 1. Starter Agent (`starter_agent.py`)

The router that classifies intent and handles account resolution.

**Responsibilities:**
- Classify query intent (search vs update vs unclear)
- Extract account name/reference from query
- Look up account in Qdrant
- Handle new account creation (with user confirmation)
- Route to appropriate agent

**New Account Flow:**
When a user references an account that doesn't exist:
1. Starter Agent detects account not found
2. Returns confirmation request: "I don't have an account for 'ABC Company'. Create one?"
3. If user confirms, creates the account folder structure
4. Indexes in Qdrant (both name and description)
5. Continues with original request

#### 2. Search Agent (`orchestrator.py`)

The read-only exploration agent for answering questions.

**What it does:**
- Answers questions by exploring the filesystem
- Uses tools: `lookup_account`, `search_descriptions`, `list_files`, `read_file`, `search_files`
- Returns grounded answers with citations
- Supports streaming for real-time visualization

#### 3. Updater Agent (`updater_agent.py`)

Handles state changes and maintains the history chain.

**What it does:**
- Parse update requests using Claude
- Update `state.md` with new values
- Append to `history.md` with linked entries (history chain)
- Regenerate and update description in Qdrant
- Return comprehensive proof of what changed

**Rich Update Details (v3.2):**

The Updater Agent returns detailed proof of every operation:

| Field | Type | Description |
|-------|------|-------------|
| `account_id` | string | ID of the account that was updated |
| `account_name` | string | Name of the account |
| `changes` | array | List of field changes with old → new values |
| `files_modified` | array | Paths to files that were changed |
| `qdrant_updated` | boolean | Whether the Qdrant description was refreshed |
| `new_description` | string | The new searchable description in Qdrant |
| `state_file_path` | string | Path to the updated state.md |
| `history_file_path` | string | Path to the updated history.md |
| `history_entry_id` | string | Timestamp ID of the new history entry |
| `previous_history_entry` | string | Timestamp of the previous entry in the chain |

**History Chain Format:**

Each entry in `history.md` links to the previous entry:

```markdown
## 2026-01-21T14:30:00Z

Stage updated from "Application Received" to "Quoted" based on premium quote of $2,600.

- **stage**: Application Received → Quoted
- **Evidence**: User command: "Mark as Quoted, $2,600 premium"
- **Previous**: [2026-01-15T10:00:00Z](#2026-01-15t100000z)

---
```

### Components

| Component | File | What It Does |
|-----------|------|--------------|
| **Starter Agent** | `starter_agent.py` | Intent classification, account resolution, routing |
| **Search Agent** | `orchestrator.py` | Read-only exploration, answers questions |
| **Updater Agent** | `updater_agent.py` | State updates, history chain, Qdrant refresh |
| **Name Registry** | `name_registry.py` | Qdrant vector database for account lookup |
| **Ingestion Pipeline** | `ingest.py` | Bulk initial data load (batch processing) |
| **Server** | `server.py` | REST API with routing through Starter Agent |

### Available Tools (Search Agent)

| Tool | Purpose |
|------|---------|
| `lookup_account` | Find accounts by company name (e.g., "Sunny Days Childcare") |
| `search_descriptions` | Find accounts by attributes like stage, location, or industry |
| `list_files` | See what files and folders exist at a path |
| `read_file` | Read the contents of a specific file |
| `search_files` | Search for text within files |

### Agent Skills Architecture (v3.3)

Harper uses **Agent Skills** - a modular system for organizing agent instructions inspired by [Anthropic's Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) pattern.

#### What Are Skills?

Skills are organized folders of instructions that each agent can load. Each skill has:
- **SKILL.md** - Core instructions with YAML frontmatter (name, description)
- **Additional context files** - Loaded on-demand for specific scenarios
- **Scripts** - Deterministic helper utilities

#### Skills Directory Structure

```
mem/skills/
├── search/
│   ├── SKILL.md              # Core search agent instructions
│   ├── tool_reference.md     # Detailed tool usage (on-demand)
│   ├── reading_sources.md    # How to read source files (on-demand)
│   ├── formatting.md         # Answer formatting rules (on-demand)
│   └── examples.md           # Example exploration flows (on-demand)
├── router/
│   ├── SKILL.md              # Intent classification instructions
│   └── confirmation.md       # New account flow details
└── update/
    ├── SKILL.md              # Updater agent instructions
    └── history_chain.md      # History chain format details
```

#### SKILL.md Format

Each skill starts with YAML frontmatter:

```yaml
---
name: Harper Search Agent
description: Read-only exploration agent that answers questions by navigating 
  the filesystem memory. Finds accounts via Qdrant lookup, reads state.md and 
  sources, returns grounded answers with citations.
---

# Search Agent Skill

[Core instructions here...]
```

#### Progressive Disclosure

Skills support **progressive disclosure** - loading context only when needed:

| Level | What's Loaded | When |
|-------|---------------|------|
| 1 | name + description | At startup (for skill selection) |
| 2 | Full SKILL.md | When skill is triggered |
| 3 | Additional context files | On-demand during execution |

This reduces token usage while keeping detailed instructions available.

#### Skill Loading in Code

```python
# orchestrator.py
def load_skill(self, skill_name: str = "search") -> str:
    """Load a skill's SKILL.md content."""
    skill_path = self.mem_path / "skills" / skill_name / "SKILL.md"
    content = skill_path.read_text()
    metadata, body = self._parse_skill_frontmatter(content)
    return body

def load_skill_context(self, skill_name: str, context_file: str) -> str:
    """Load additional context file for progressive disclosure."""
    context_path = self.mem_path / "skills" / skill_name / context_file
    return context_path.read_text()
```

#### Backward Compatibility

The system falls back to `mem/system_rules.md` if skills aren't found, ensuring backward compatibility with the legacy format.

---

### File Structure

Each account is stored in its own folder with:

- **state.md** - Current account info (name, stage, contacts, coverage types)
- **history.md** - Log of changes over time with linked entries (history chain)
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

**Qdrant Updates:** When an account's state changes via the Updater Agent, its description in Qdrant is regenerated. This ensures that searching for "quoted accounts" or "accounts in Texas" returns accurate, current results.

---

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/query` | POST | Main entry - routes through Starter Agent |
| `/confirm` | POST | Handle confirmation for pending actions (new account creation) |
| `/search` | POST | Direct access to Search Agent (bypasses routing) |
| `/query/stream` | POST | SSE streaming for real-time exploration |
| `/health` | GET | Health check |
| `/cache/clear` | POST | Clear query cache |
| `/tree` | GET | Get filesystem tree for visualization |
| `/file` | GET | Read file contents for preview |

### Response Types

The `/query` endpoint returns different response types:

| Type | When | Contains |
|------|------|----------|
| `success` | Query processed successfully | `answer`, `citations`, `notes` |
| `success` (update) | Update processed successfully | `changes`, `history_entry_id`, `files_modified`, `qdrant_updated`, `new_description` |
| `confirmation_required` | Account not found, asking to create | `session_id`, `account_name`, `alternatives` |
| `clarification_needed` | Intent unclear | `suggestions` for how to rephrase |
| `error` | Something went wrong | `message` with error details |

### Update Response Fields (v3.2)

When `routed_to` is `updater_agent`, the response includes:

```json
{
  "type": "success",
  "message": "Updated Maple Avenue Dental: stage: Quoted",
  "routed_to": "updater_agent",
  "account_id": "29041",
  "account_name": "Maple Avenue Dental",
  "changes": [
    {"field": "stage", "old_value": "Quote Pitched", "new_value": "Quoted"}
  ],
  "history_entry_id": "2026-01-21T22:39:01.284545Z",
  "files_modified": [
    "mem/accounts/29041/state.md",
    "mem/accounts/29041/history.md"
  ],
  "qdrant_updated": true,
  "new_description": "Maple Avenue Dental | Stage: Quoted | Insurance: Dental Malpractice",
  "state_file_path": "mem/accounts/29041/state.md",
  "history_file_path": "mem/accounts/29041/history.md",
  "previous_history_entry": "2026-01-15T10:00:00Z"
}
```

### Example: Confirmation Flow

```json
// User: "Add a note to New Company LLC"
// Response:
{
  "type": "confirmation_required",
  "message": "I don't have an account for 'New Company LLC'. Would you like me to create a new account?",
  "session_id": "abc-123",
  "account_name": "New Company LLC",
  "alternatives": []
}

// User confirms via POST /confirm
{
  "session_id": "abc-123",
  "confirmed": true
}

// Response:
{
  "type": "success",
  "message": "Created new account: New Company LLC (ID: 10002)"
}
```

---

## Data Flows

### Flow: Answering a Question

User: "What is the status of Sunny Days Childcare?"

1. **Starter Agent** classifies as `search` intent, extracts "Sunny Days Childcare"
2. **Starter Agent** looks up account in Qdrant → found (ID: 29119)
3. **Starter Agent** routes to Search Agent
4. **Search Agent** reads `state.md`, returns answer with citation

### Flow: Updating Account Status

User: "Mark Sunny Days Childcare as Quoted"

1. **Starter Agent** classifies as `update` intent, extracts "Sunny Days Childcare"
2. **Starter Agent** looks up account → found (ID: 29119)
3. **Starter Agent** routes to Updater Agent with account info
4. **Updater Agent** parses update request
5. **Updater Agent** updates `state.md` (stage → Quoted)
6. **Updater Agent** appends entry to `history.md` with link to previous
7. **Updater Agent** regenerates description, updates Qdrant

### Flow: New Account Creation

User: "Add a note to ABC Security Services"

1. **Starter Agent** classifies as `update` intent, extracts "ABC Security Services"
2. **Starter Agent** looks up account → NOT FOUND
3. **Starter Agent** returns confirmation request with `session_id`
4. User confirms via `/confirm` endpoint
5. **Starter Agent** creates account folder structure, indexes in Qdrant
6. **Starter Agent** continues with original request → routes to Updater Agent
7. **Updater Agent** adds the note

---

## Key Design Decisions

### Why Multiple Agents Instead of One?

**Safety:** Read operations (search) and write operations (update) have very different risk profiles. Separating them makes it harder to accidentally modify data.

**Clarity:** When the system explicitly classifies intent, both the user and the system are clear about what action is being taken.

**Scalability:** Adding new capabilities (like a reporting agent) is easier when agents are modular.

### Why Linked List History?

**Traceability:** Every change points to its evidence and the previous state, creating a complete audit trail.

**Queryability:** Can follow the chain to understand how an account evolved over time.

**Debugging:** Easy to see exactly what changed when and why.

### Why User Confirmation for New Accounts?

**Safety:** Prevents accidentally creating duplicate accounts due to typos or slight name variations.

**Transparency:** User explicitly confirms they want to create a new account, not update an existing one.

**Alternatives:** When account not found, system shows similar accounts that might be what user meant.

### Why Regenerate Descriptions?

**Accuracy:** Descriptions should reflect current state, not stale information.

**Simplicity:** Full regeneration is simpler and more reliable than incremental updates.

### Why Agent Skills? (v3.3)

**Modularity:** Each agent has its own skill folder. Instructions for the Search Agent don't pollute the Updater Agent's context.

**Progressive Disclosure:** The system can load just the skill name/description at startup, full instructions when triggered, and additional context files only when needed. This reduces token usage.

**Maintainability:** Update one agent's behavior by editing its SKILL.md without touching other agents.

**Portability:** Skills follow [Anthropic's Agent Skills open standard](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills), making them portable across Claude-powered platforms.

**Future-Proof:** As we add more agents (reporting, notifications, ingestion), each gets its own skill folder without bloating existing agents.

---

## React UI

The frontend is a React + TypeScript application built with Vite that provides real-time visualization of agent operations.

### UI Components

| Component | File | Purpose |
|-----------|------|---------|
| **ExplorerLayout** | `ExplorerLayout.tsx` | Main layout with header, panels, and modals |
| **ConfirmationModal** | `ConfirmationModal.tsx` | New account confirmation dialog |
| **ClarificationModal** | `ConfirmationModal.tsx` | Clarification prompt dialog |
| **QueryInput** | `QueryInput.tsx` | Query input with submit/stop buttons |
| **QuerySelector** | `QuerySelector.tsx` | Sample queries organized by category |
| **ToolPanel** | `ToolPanel.tsx` | Agent journey visualization + update results |
| **FileTree** | `FileTree.tsx` | Filesystem visualization |
| **FilePreview** | `FilePreview.tsx` | File content preview and answer display |

### Sample Query Categories

| Category | Description |
|----------|-------------|
| **Updates & Actions** | State changes, notes, stage updates |
| **New Accounts** | Queries that trigger confirmation flow |
| **Level 1: Single Account** | Basic status queries |
| **Level 2: Multi-Source** | Cross-channel synthesis |
| **Level 3: Cross-Account** | Brokerage-level queries |
| **Follow-Up Actions** | Action drafting |
| **Edge Cases** | Ambiguous queries |
| **Data Exploration** | Pipeline and aggregate queries |

### UI State Machine

```
idle
  ↓ (submit query)
running
  ↓ (streaming events)
  ├── thinking → tool_result → thinking → ...
  ↓
completed / error / awaiting_confirmation / awaiting_clarification
```

### Key UI Features

1. **Starter Agent Thinking Card (v3.3)**: Shows the Starter Agent's decision-making process:
   - **Intent Classification**: Displays detected intent (search/update) with confidence score
   - **Account Extraction**: Shows the extracted account name from the query
   - **Routing Decision**: Visual indicator of which agent was selected
   - **Skill Loading**: Shows which Agent Skill was loaded with name and description

2. **Agent Routing Indicator**: Shows whether Search Agent or Updater Agent is handling the request

2. **Update Result Card (v3.2)**: For update operations, shows comprehensive proof:
   - **Account Info**: ID and name of the updated account
   - **State Changes**: Each field with old value (strikethrough) → new value
   - **Files Modified**: List of files that were changed with checkmarks
   - **Qdrant Status**: Confirmation that the vector DB was updated
   - **New Description**: The updated searchable description (expandable)
   - **History Chain**: Previous entry link → New entry timestamp

3. **Confirmation Modal**: For new account creation:
   - Shows account name to create
   - Lists similar accounts (alternatives)
   - Confirm/Cancel buttons

4. **Clarification Modal**: For unclear queries:
   - Shows clarification message
   - Lists suggested rephrases
   - Click to use suggestion

### TypeScript Types

Key types in `ui/src/types/exploration.ts`:

```typescript
type ResponseType = 'success' | 'confirmation_required' | 'clarification_needed' | 'error';
type IntentType = 'search' | 'update' | 'unclear';
type AgentType = 'search_agent' | 'updater_agent';

interface StateChange {
  field: string;
  old_value: string;
  new_value: string;
}

// Rich update details for proof of changes (v3.2)
interface UpdateDetails {
  account_id: string;
  account_name: string;
  files_modified: string[];
  qdrant_updated: boolean;
  new_description: string;
  state_file_path: string;
  history_file_path: string;
  previous_history_entry: string | null;
}

interface PendingConfirmation {
  session_id: string;
  message: string;
  account_name: string;
  alternatives: AccountAlternative[];
  original_query: string;
}

interface ExplorationState {
  status: 'idle' | 'running' | 'completed' | 'error' | 'awaiting_confirmation' | 'awaiting_clarification';
  query: string;
  steps: ExplorationStep[];
  routedTo?: AgentType;
  changes?: StateChange[];
  historyEntryId?: string;
  updateDetails?: UpdateDetails;  // Rich proof of updates (v3.2)
  pendingConfirmation?: PendingConfirmation;
  // ... other fields
}
```

---

## Success Metrics

| Metric | Target |
|--------|--------|
| Search query accuracy | >80% pass rate on L1/L2/L3 tests |
| State update consistency | 100% - no data corruption |
| Intent classification accuracy | >90% correct routing |
| Clarification rate | <15% of queries need clarification |
| Response latency | <5 seconds average |
