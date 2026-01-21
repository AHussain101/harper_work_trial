# Harper AI Sales Assistant

An AI-powered agentic system for insurance brokers that manages account memory through a filesystem-based architecture. Harper helps brokers quickly understand account status, find relevant communications, update account state, and get answers grounded in actual data.

## What It Does

Harper acts as an intelligent assistant that can:

- **Answer account questions** — "What is the status of Maple Avenue Dental?"
- **Find communications** — "Summarize all calls with that dental practice"
- **Search by attributes** — "Which accounts need follow-up?"
- **Update account state** — "Mark Maple Avenue Dental as Quoted"
- **Create new accounts** — Automatically prompts for confirmation when an account doesn't exist
- **Provide grounded answers** — Every response cites the actual files it read

The system uses Claude as the reasoning engine, exploring a structured filesystem memory to find answers and apply updates. All data is stored as readable markdown files, making it fully transparent and auditable.

## How It Works

Harper uses a multi-agent architecture with the **Starter Agent** routing queries to specialized agents:

```
User Query
    ↓
┌─────────────────────────────────────────────────────────┐
│                   Starter Agent                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  1. Classify intent (search vs update)          │    │
│  │  2. Extract account reference                   │    │
│  │  3. Look up account in Qdrant                   │    │
│  │  4. Route to appropriate agent                  │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
    ↓                                    ↓
┌─────────────────┐              ┌─────────────────┐
│  Search Agent   │              │  Updater Agent  │
│  (read-only)    │              │  (write ops)    │
│                 │              │                 │
│ • Explore files │              │ • Update state  │
│ • Read sources  │              │ • Append history│
│ • Return answer │              │ • Update Qdrant │
└─────────────────┘              └─────────────────┘
    ↓                                    ↓
Grounded Answer              Changes Applied + History
```

### New Account Flow

When you reference an account that doesn't exist, Harper:
1. Prompts for confirmation: "I don't have an account for 'ABC Company'. Create one?"
2. Shows similar accounts if found (in case of typo)
3. Creates the account structure if confirmed
4. Continues with your original request

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│    React UI      │     │   FastAPI Server │     │  Starter Agent   │
│   (Vite + TS)    │────▶│   /query         │────▶│  Intent Routing  │
│   Port 5173      │     │   /confirm       │     └────────┬─────────┘
└──────────────────┘     │   Port 8000      │              │
                         └──────────────────┘     ┌────────┴────────┐
                                                  ↓                 ↓
                                         ┌──────────────┐   ┌──────────────┐
                                         │Search Agent  │   │Updater Agent │
                                         │(orchestrator)│   │(state writes)│
                                         └──────────────┘   └──────────────┘
                                                  │                 │
                    ┌─────────────────────────────┼─────────────────┼──────────────────────────┐
                    ▼                             ▼                 ▼                          ▼
           ┌──────────────────┐       ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
           │  Name Registry   │       │    Claude API    │   │   Filesystem     │   │    Qdrant        │
           │    (Qdrant)      │       │   (Reasoning)    │   │     (mem/)       │   │  (Descriptions)  │
           │                  │       │                  │   │                  │   │                  │
           │ • account_names  │       │ • Haiku 4.5      │   │ • state.md       │   │ • Updated on     │
           │ • descriptions   │       │ • JSON responses │   │ • history.md     │   │   every change   │
           └──────────────────┘       └──────────────────┘   │ • sources/       │   └──────────────────┘
                                                             └──────────────────┘
```

## The Three Agents

### 1. Starter Agent (`starter_agent.py`)

The router that classifies intent and handles account resolution.

- **Intent Classification**: Uses Claude to determine if query is search or update
- **Account Lookup**: Searches Qdrant to find matching accounts
- **New Account Creation**: Handles confirmation flow when account not found
- **Routing**: Sends to Search Agent or Updater Agent

### 2. Search Agent (`orchestrator.py`)

The read-only exploration agent for answering questions.

- Constrained to 10 tool calls maximum
- Optimized for 2-3 calls for simple queries, 4-7 for complex ones
- Returns grounded answers with file citations
- Supports real-time streaming via SSE

### 3. Updater Agent (`updater_agent.py`)

Handles state changes and maintains the history chain.

- Parses update requests using Claude
- Updates `state.md` with new values
- Appends linked entries to `history.md`
- Regenerates Qdrant description to keep search accurate
- Returns comprehensive proof of what changed (account ID, files modified, Qdrant status, history chain)

## Memory Structure

Each account is stored in its own folder with a consistent structure:

```
mem/
├── system_rules.md              # Legacy agent instructions (fallback)
├── skills/                      # Agent Skills (modular instructions)
│   ├── search/
│   │   ├── SKILL.md             # Core search agent skill
│   │   ├── tool_reference.md    # Detailed tool usage
│   │   └── formatting.md        # Answer formatting rules
│   ├── router/
│   │   └── SKILL.md             # Intent classification skill
│   └── update/
│       └── SKILL.md             # Updater agent skill
└── accounts/
    └── {account_id}/
        ├── state.md             # Current account info (name, stage, contacts, coverage)
        ├── history.md           # Change log with linked entries (history chain)
        └── sources/
            ├── emails/
            │   └── email_{id}/
            │       ├── summary.md   # LLM-generated summary
            │       └── raw.txt      # Full email content
            ├── calls/
            │   └── call_{id}/
            │       ├── summary.md   # Call summary with key points
            │       └── raw.txt      # Full transcript
            └── sms/
                └── sms_{id}/
                    ├── summary.md   # SMS summary
                    └── raw.txt      # Full message content
```

### Agent Skills

Harper uses **Agent Skills** - a modular instruction system inspired by [Anthropic's Agent Skills pattern](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills). Each skill is a folder containing:

- **SKILL.md** - Core instructions with YAML frontmatter (name, description)
- **Additional files** - Context loaded on-demand (tool reference, formatting rules, etc.)
- **Scripts** - Deterministic Python utilities for common operations

Benefits:
- **Modular** - Each agent has its own skill folder
- **Scalable** - Add new agents by adding new skill folders
- **Efficient** - Only load the context needed for each query

### History Chain Format

Each change is recorded with a link to the previous entry:

```markdown
## 2026-01-21T14:30:00Z

Stage updated from "Application Received" to "Quoted" based on premium quote of $2,600.

- **stage**: Application Received → Quoted
- **Evidence**: User command: "Mark as Quoted, $2,600 premium"
- **Previous**: [2026-01-15T10:00:00Z](#2026-01-15t100000z)

---
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| LLM | Claude Haiku 4.5 | Reasoning and exploration decisions |
| Embeddings | OpenAI | Semantic similarity for account search |
| Vector DB | Qdrant | Fast account lookup by name or description |
| Backend | FastAPI + Uvicorn | REST API with SSE streaming |
| Frontend | React + Vite + TypeScript | Real-time exploration visualization |
| Memory | Markdown files | Transparent, auditable data storage |
| Agent Skills | SKILL.md + context files | Modular agent instructions |

## Setup

### Prerequisites

- Python 3.8+
- Node.js 18+ (for the React UI)
- Qdrant running locally or in cloud
- API keys for Anthropic and OpenAI

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/AHussain101/harper_work_trial.git
cd harper_work_trial
```

2. **Install Python dependencies:**
```bash
pip install -r requirements.txt
```

3. **Install UI dependencies:**
```bash
cd ui
npm install
cd ..
```

4. **Create a `.env` file with your API keys:**
```env
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
QDRANT_URL=http://localhost:6333
```

5. **Start Qdrant** (if running locally):
```bash
docker run -p 6333:6333 qdrant/qdrant
```

6. **Run the ingestion pipeline** (if starting fresh):
```bash
python ingest.py
```

## Usage

### Start the API Server

```bash
python server.py
```

The server runs on `http://localhost:8000`.

### Start the React UI

```bash
cd ui
npm run dev
```

The UI runs on `http://localhost:5173` and shows:
- **Starter Agent thinking**: Intent classification, confidence score, routing decision
- **Skill loading**: Which Agent Skill was loaded (name, description, path)
- Real-time exploration steps as the agent works
- Agent routing indicator (Search Agent vs Updater Agent)
- Confirmation modals for new account creation
- Rich update results with proof:
  - Account ID and name
  - Field changes (old → new values)
  - Files modified with checkmarks
  - Qdrant update status
  - History chain (previous → new entry)

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/query` | POST | Main entry - routes through Starter Agent |
| `/confirm` | POST | Handle confirmation for new account creation |
| `/search` | POST | Direct access to Search Agent (bypasses routing) |
| `/query/stream` | POST | Stream exploration steps via SSE |
| `/tree` | GET | Get filesystem tree for visualization |
| `/file` | GET | Read a file's contents for preview |
| `/cache/clear` | POST | Clear the query result cache |
| `/health` | GET | Health check |

### Example: Search Query

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the status of Maple Avenue Dental?"}'
```

Response:
```json
{
  "type": "success",
  "message": "Maple Avenue Dental is currently in the Quote Pitched stage...",
  "answer": "Maple Avenue Dental is currently in the Quote Pitched stage...",
  "citations": ["mem/accounts/29041/state.md"],
  "routed_to": "search_agent"
}
```

### Example: Update Query

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Mark Maple Avenue Dental as Bound"}'
```

Response (with proof of changes):
```json
{
  "type": "success",
  "message": "Updated Maple Avenue Dental: stage: Bound",
  "routed_to": "updater_agent",
  "account_id": "29041",
  "account_name": "Maple Avenue Dental",
  "changes": [
    {"field": "stage", "old_value": "Quoted", "new_value": "Bound"}
  ],
  "history_entry_id": "2026-01-21T22:45:00.000000Z",
  "files_modified": [
    "mem/accounts/29041/state.md",
    "mem/accounts/29041/history.md"
  ],
  "qdrant_updated": true,
  "new_description": "Maple Avenue Dental | Stage: Bound | Insurance: Dental Malpractice",
  "previous_history_entry": "2026-01-21T22:39:01.284545Z"
}
```

### Example: New Account (Confirmation Required)

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Add a note to ABC Insurance Corp"}'
```

Response:
```json
{
  "type": "confirmation_required",
  "message": "I don't have an account for 'ABC Insurance Corp'. Would you like me to create a new account?",
  "session_id": "abc-123",
  "account_name": "ABC Insurance Corp",
  "alternatives": []
}
```

Confirm:
```bash
curl -X POST http://localhost:8000/confirm \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc-123", "confirmed": true}'
```

## Agent Tools

The Search Agent has 5 tools for exploring the filesystem:

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `lookup_account` | Find accounts by company name | "What is Maple Avenue Dental's status?" |
| `search_descriptions` | Find accounts by attributes | "Accounts needing follow-up", "dental practices" |
| `list_files` | List files at a path | Explore directories |
| `read_file` | Read file contents | Get state, history, or communication details |
| `search_files` | Search text within files | Find specific content across files |

## Qdrant Collections

Two vector collections enable fast semantic search:

| Collection | What It Stores | Use Case |
|------------|----------------|----------|
| `account_names` | Company names | Direct name lookup |
| `account_descriptions` | Rich summaries with stage, location, industry | Attribute-based queries |

**Note**: Descriptions are regenerated after each update to keep search results accurate.

## Key Design Decisions

### Why Multi-Agent Architecture?

- **Safety**: Read and write operations are separated, reducing accidental modifications
- **Clarity**: Explicit intent classification makes actions transparent
- **Scalability**: Easy to add new agents (reporting, notifications, etc.)

### Why User Confirmation for New Accounts?

- **Safety**: Prevents accidental duplicates from typos
- **Transparency**: User explicitly confirms new account creation
- **Alternatives**: Shows similar accounts that might be the intended target

### Why Linked History Chain?

- **Traceability**: Every change points to evidence and previous state
- **Auditability**: Complete audit trail from any point in time
- **Debugging**: Easy to see exactly what changed when and why

### Why Filesystem-Based Memory?

- **Transparency**: Anyone can browse and verify the data
- **Auditability**: Git-trackable changes, linked evidence
- **Debuggability**: Easy to inspect what the agent "sees"
- **Simplicity**: No complex database schemas

### Why Agent Skills?

- **Modularity**: Each agent has its own skill folder with focused instructions
- **Progressive Disclosure**: Core instructions always loaded; detailed context on-demand
- **Maintainability**: Update one agent's instructions without touching others
- **Scalability**: Add new agents by adding new skill folders
- **Portability**: Skills follow Anthropic's open standard for cross-platform use

## Project Structure

```
harper_v3/
├── server.py           # FastAPI REST server with multi-agent routing
├── starter_agent.py    # Intent classification and routing
├── orchestrator.py     # Search Agent (Plan-Act-Observe loop, skill loading)
├── updater_agent.py    # Updater Agent (state changes, history)
├── name_registry.py    # Qdrant vector search for accounts
├── ingest.py           # Bulk data ingestion pipeline
├── requirements.txt    # Python dependencies
├── accounts.jsonl      # Source account data
├── PROJECT_SPEC.md     # Detailed architecture specification
├── mem/
│   ├── system_rules.md # Legacy agent instructions (fallback)
│   ├── skills/         # Agent Skills (modular instructions)
│   │   ├── search/
│   │   │   ├── SKILL.md            # Core search skill
│   │   │   ├── tool_reference.md   # Tool usage details
│   │   │   ├── formatting.md       # Answer formatting
│   │   │   ├── reading_sources.md  # Source file strategy
│   │   │   └── examples.md         # Example flows
│   │   ├── router/
│   │   │   ├── SKILL.md            # Router/intent skill
│   │   │   └── confirmation.md     # New account flow
│   │   └── update/
│   │       ├── SKILL.md            # Updater skill
│   │       └── history_chain.md    # History format
│   └── accounts/       # Account memory (state, history, sources)
└── ui/
    ├── src/
    │   ├── App.tsx
    │   ├── types/
    │   │   └── exploration.ts      # TypeScript types for events
    │   ├── hooks/
    │   │   └── useExplorationStream.ts  # SSE streaming hook
    │   └── components/
    │       ├── ExplorerLayout.tsx  # Main layout with modals
    │       ├── ConfirmationModal.tsx # New account confirmation
    │       ├── FileTree.tsx        # Filesystem visualization
    │       ├── ToolPanel.tsx       # Agent journey + update results
    │       ├── QueryInput.tsx      # Query input component
    │       ├── QuerySelector.tsx   # Sample queries by category
    │       └── FilePreview.tsx     # File content preview
    ├── package.json
    └── vite.config.ts
```

## License

MIT
