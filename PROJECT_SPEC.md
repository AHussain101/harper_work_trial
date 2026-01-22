# Project Specification

## Executive Summary

This is an AI-powered agentic system for insurance brokers that manages account memory through a filesystem-based architecture. The system uses Claude as the reasoning engine, Qdrant for semantic search, and a structured markdown-based memory format for transparency and auditability.

---

## Current Implementation (v3.7)

### Architecture Overview

The system uses a multi-agent architecture with the **Starter Agent** as the entry point:

```
User Query → Starter Agent → Routes to appropriate agent → Result
                 ↓
         Intent Classification
                 ↓
    ┌───────────┼───────────┐
    ↓           ↓           ↓
Search      Updater     Follow-Up
Agent       Agent       Agent
(read)      (write)     (automation)
```

### The Four Agents

#### 1. Starter Agent (`starter_agent.py`)

The router that classifies intent and handles account resolution.

**Responsibilities:**
- Classify query intent (search vs update vs followup vs unclear)
- Extract account name/reference from query
- Detect if query requires a specific account (vs cross-account queries)
- Look up account in Qdrant
- Handle new account creation (with user confirmation)
- Route to appropriate agent

**Ambiguous Account Clarification:**

When a query needs a specific account but none is mentioned (e.g., "What did the customer say in the call?"), the Starter Agent:

1. Detects `requires_specific_account: true` but `account_name: null`
2. Returns clarification request: "Which account are you asking about?"
3. User can provide company name or description (e.g., "the childcare center in Texas")

This distinguishes between:
- **Single-account queries missing context**: "What did the customer say?" → asks for account
- **Cross-account queries**: "Which accounts need follow-up?" → routes to search

**New Account Flow:**
When a user references an account that doesn't exist:
1. Starter Agent detects account not found
2. Returns confirmation request: "I don't have an account for 'ABC Company'. Create one?"
3. User sees expandable form with optional fields:
   - Industry
   - Location
   - Primary Email / Phone
   - Insurance Types (checkboxes)
   - Other Information (notes)
4. If user confirms, routes to **Updater Agent** (account-create skill)
5. Updater Agent creates folders, state.md, history.md
6. Indexes in Qdrant (name + description with details for searchability)
7. Continues with original request if it was an update

#### 2. Search Agent (`search_agent.py`)

The read-only exploration agent for answering questions.

**What it does:**
- Answers questions by exploring the filesystem
- Uses tools: `lookup_account`, `search_descriptions`, `list_files`, `read_file`, `search_files`
- Returns grounded answers with citations
- Supports streaming for real-time visualization
- **Enforces source evidence requirement** - all answers must cite at least one source file

**Source Evidence Requirement:**

Every answer must cite at least one source file from `sources/emails/`, `sources/calls/`, or `sources/sms/`. Answers that only cite `state.md` or `history.md` are rejected and the agent is prompted to read source files first.

This ensures all claims are verified against primary evidence (actual emails, call transcripts, SMS) rather than just the summarized state.

**Budget Limits:**
- `MAX_TOOL_CALLS = 15` - Total tool calls per query
- `MAX_READ_FILE = 8` - File reads (enough for state + multiple sources)
- `MAX_SEARCH = 4` - Text search operations

#### 3. Updater Agent (`updater_agent.py`)

Handles state changes and maintains the history chain.

**What it does:**
- Parse update requests using Claude
- Update `state.md` with new values
- Append to `history.md` with linked entries (history chain)
- Regenerate and update description in Qdrant
- Return comprehensive proof of what changed

**Vague Update Clarification (v3.7):**

When an update request is too vague to execute (e.g., "update this account", "change the status"), the Updater Agent detects this and requests clarification:

1. User sends vague update: "Update Sunny Days Childcare"
2. Updater Agent cannot determine what to change
3. Returns `vague_update_clarification` event with form fields
4. UI shows modal with form:
   - Pipeline Stage (dropdown)
   - Insurance Types (multi-select)
   - Next Step (text input)
   - Add Note (textarea)
5. User fills in desired changes
6. System processes the clarified update normally

**Vague Update Detection Examples:**
- "Update this account" → Needs clarification
- "Change the status" → Needs clarification (which status?)
- "Make some updates" → Needs clarification
- "Mark as Quoted" → Clear, no clarification needed

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

#### 4. Follow-Up Agent (`followup_agent.py`) (v3.5)

Automates follow-up workflows across pipeline stages.

**What it does:**
- Scan accounts to find those needing follow-up based on stage and time since last contact
- Determine appropriate channel (email, call script, SMS) based on stage and context
- Draft personalized communications by analyzing the client's communication style from their emails, calls, and texts (not template-based)
- Execute follow-ups (mock send) and record actions in history chain

**Personalized Communication Drafting:**

The Follow-Up Agent analyzes each client's communication patterns to tailor messages:
- **Formality level** - Matches their greeting/sign-off style
- **Message length** - Brief for busy executives, detailed for relationship-builders
- **Tone** - Professional, casual, or friendly based on their style
- **Channel preference** - Uses the channel they respond to most

**Stage-Based Follow-Up Rules:**

| Stage | Days Until Follow-Up | Primary Channel | Follow-Up Type |
|-------|---------------------|-----------------|----------------|
| New Lead / Intake | 2 days | Email | Document collection, qualification |
| Application | 3 days | Email/Call | Form completion, corrections |
| Submission | 5 days | Email | Underwriter status, info requests |
| Quoted | 2 days | Call/Email | Decision follow-up, competitor check |
| Bound | N/A | - | No follow-up needed |

**Draft Communication Response:**

| Field | Type | Description |
|-------|------|-------------|
| `channel` | string | "email", "call_script", or "sms" |
| `subject` | string | Email subject line (null for call/sms) |
| `body` | string | The drafted communication content |
| `context_used` | array | Files read for personalization |
| `rationale` | string | Why this message was drafted |

**Execution Result:**

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether the action completed |
| `sent` | boolean | Whether the communication was sent (false if dry_run) |
| `recorded` | boolean | Whether the action was logged in history |
| `history_entry_id` | string | Timestamp of the history entry |

### Components

| Component | File | What It Does |
|-----------|------|--------------|
| **Starter Agent** | `starter_agent.py` | Intent classification, account resolution, routing |
| **Search Agent** | `search_agent.py` | Read-only exploration, answers questions |
| **Updater Agent** | `updater_agent.py` | State updates, history chain, Qdrant refresh |
| **Follow-Up Agent** | `followup_agent.py` | Automated follow-up scanning, drafting, execution |
| **Name Registry** | `name_registry.py` | Qdrant vector database for account lookup |
| **Ingestion Pipeline** | `ingest.py` | Bulk initial data load (batch processing, `--clean` to reset Qdrant) |
| **Server** | `server.py` | REST API with routing through Starter Agent |

### Available Tools (Search Agent)

| Tool | Purpose |
|------|---------|
| `lookup_account` | Find accounts by company name (e.g., "Sunny Days Childcare") |
| `search_descriptions` | Find accounts by attributes like stage, location, or industry |
| `list_files` | See what files and folders exist at a path |
| `read_file` | Read the contents of a specific file |
| `search_files` | Search for text within files |

### Agent Skills Architecture (v3.6)

Harper uses **Agent Skills** - a modular system for progressive context disclosure.

#### Tools vs Skills: The Core Distinction

| Aspect | **Tools** | **Skills** |
|--------|-----------|------------|
| What they are | Atomic operations the agent executes | Knowledge about when/how to use tools effectively |
| Defined in | Python code (`ToolExecutor` class) | Markdown files (`SKILL.md`) |
| Context cost | Tool schemas always loaded (~50 tokens each) | Progressive: metadata at startup, full instructions on-demand |

**Key insight**: Skills don't replace tools - they teach the agent to use tools better, with context loaded only when needed.

#### What Are Skills?

Skills are folders containing instructions that agents can activate on-demand. Each skill has:
- **SKILL.md** - Core instructions with YAML frontmatter (name, description)
- **references/** - Detailed documentation loaded on-demand
- **assets/** - Templates, examples, static resources

#### Skills Directory Structure

```
skills/
├── search/
│   ├── name-lookup/
│   │   └── SKILL.md          # Find accounts by company name
│   ├── description-search/
│   │   └── SKILL.md          # Find accounts by attributes
│   ├── file-navigation/
│   │   ├── SKILL.md          # Navigate and read files
│   │   └── references/
│   │       └── directory-structure.md
│   └── text-search/
│       └── SKILL.md          # Search text in files
├── update/
│   ├── account-create/
│   │   └── SKILL.md          # Create new accounts (v3.7)
│   ├── state-edit/
│   │   └── SKILL.md          # Modify state.md fields
│   ├── history-chain/
│   │   ├── SKILL.md          # Maintain linked history
│   │   └── references/
│   │       └── format-examples.md
│   └── qdrant-sync/
│       └── SKILL.md          # Update search descriptions
└── followup/
    ├── pending-scan/
    │   ├── SKILL.md          # Find accounts needing follow-up
    │   └── references/
    │       └── stage-rules.md
    ├── communication-draft/
    │   ├── SKILL.md          # Draft emails/calls/SMS
    │   └── assets/
    │       └── templates.md
    └── action-execute/
        └── SKILL.md          # Execute and record follow-ups
```

#### SKILL.md Format

Each skill follows the Agent Skills specification:

```yaml
---
name: name-lookup
description: Find accounts by company name using semantic search. Use when 
  query mentions a specific company like "Sunny Days Childcare" or "ABC Corp".
---

# Name Lookup

## When to use this skill
- Query mentions a specific company name
- User asks "What's the status of [Company]?"

## How to use the tool
Call `lookup_account` with the company name...
```

**Naming constraints** (per spec):
- Lowercase letters, numbers, hyphens only
- 1-64 characters
- Must match parent directory name

#### Progressive Disclosure

Skills use three levels of context loading:

| Level | What's Loaded | Tokens | When |
|-------|---------------|--------|------|
| 1 | name + description only | ~50-100 | At startup (injected as XML) |
| 2 | Full SKILL.md | ~150-300 | When agent reads the skill file |
| 3 | references/ or assets/ | ~100-500 | On-demand during execution |

#### Skill Discovery and Injection

At startup, agents discover available skills and inject them as XML:

```xml
<available_skills>
  <skill>
    <name>name-lookup</name>
    <description>Find accounts by company name using semantic search...</description>
    <location>skills/search/name-lookup/SKILL.md</location>
  </skill>
  ...
</available_skills>
```

#### Skill Activation

Agents activate skills by reading their SKILL.md file:

```python
# Search Agent uses read_file tool to activate skills
{
  "type": "tool_call",
  "tool": "read_file",
  "args": {"path": "skills/search/name-lookup/SKILL.md"},
  "reason": "Activating name-lookup skill - query mentions specific company"
}

# Updater/Follow-Up agents use activate_skill method
skill_content = agent.activate_skill("state-edit")
```

#### Available Skills by Agent

| Agent | Skills |
|-------|--------|
| Search | `name-lookup`, `description-search`, `file-navigation`, `text-search` |
| Updater | `account-create`, `state-edit`, `history-chain`, `qdrant-sync` |
| Follow-Up | `pending-scan`, `communication-draft`, `action-execute` |

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
| `/followup/pending` | GET | List accounts needing follow-up (v3.5) |
| `/followup/draft` | POST | Draft a follow-up communication (v3.5) |
| `/followup/execute` | POST | Execute a follow-up action (v3.5) |
| `/followup/batch` | POST | Process multiple follow-ups in batch (v3.5) |

### Response Types

The `/query` endpoint returns different response types:

| Type | When | Contains |
|------|------|----------|
| `success` | Query processed successfully | `answer`, `citations`, `notes` |
| `success` (update) | Update processed successfully | `changes`, `history_entry_id`, `files_modified`, `qdrant_updated`, `new_description` |
| `success` (followup) | Follow-up processed | `draft`, `sent`, `recorded`, `history_entry_id` |
| `confirmation_required` | Account not found, asking to create | `session_id`, `account_name`, `alternatives` |
| `clarification_needed` | Intent unclear OR query needs specific account but none provided | `suggestions` for rephrasing, or `reason: "Query requires specific account"` |
| `vague_update_clarification` | Update too vague to execute | `session_id`, `account_id`, `clarification_fields` |
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

### Follow-Up API Endpoints (v3.5)

**GET /followup/pending**

Returns accounts that need follow-up based on stage and days since last contact:

```json
{
  "accounts": [
    {
      "account_id": "29041",
      "account_name": "Maple Avenue Dental",
      "stage": "Quoted",
      "days_since_contact": 48,
      "urgency": "critical",
      "recommended_channel": "call_script",
      "next_steps": ["Client confirmation on biBERK quote"],
      "pending_actions": ["Client review of emailed quote"]
    }
  ],
  "total": 12,
  "filters": {"stage": null, "days_threshold": null}
}
```

**POST /followup/draft**

Draft a follow-up communication:

```json
// Request
{
  "account_id": "29041",
  "channel": "email",
  "purpose": "quote decision follow-up"
}

// Response
{
  "draft": {
    "channel": "email",
    "subject": "Following up on your Workers' Comp quote",
    "body": "Hi Dr. Reed,\n\nI wanted to check in regarding the quote...",
    "context_used": ["state.md", "sources/calls/call_150301/summary.md"],
    "rationale": "48 days since last contact, quote pending decision"
  },
  "account_id": "29041"
}
```

**POST /followup/execute**

Execute a follow-up (draft + optionally send):

```json
// Request
{
  "account_id": "29041",
  "channel": "email",
  "dry_run": false
}

// Response
{
  "result": {
    "success": true,
    "sent": true,
    "recorded": true,
    "message": "Sent email to Maple Avenue Dental",
    "history_entry_id": "2026-01-21T14:30:00Z"
  },
  "draft": { ... },
  "account_id": "29041"
}
```

### Example: Confirmation Flow with Account Details (v3.7)

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

// User expands "Add Details" form and fills in optional info, then confirms via POST /confirm
{
  "session_id": "abc-123",
  "confirmed": true,
  "industry": "Healthcare",
  "location": "Austin, TX",
  "primary_email": "contact@newcompany.com",
  "primary_phone": "(512) 555-1234",
  "insurance_types": ["Workers' Compensation", "General Liability"],
  "notes": "Referred by existing client"
}

// Response:
{
  "type": "success",
  "message": "Created new account: New Company LLC (ID: 10002)",
  "account_id": "10002",
  "account_name": "New Company LLC"
}
```

### Example: Vague Update Clarification Flow (v3.7)

```json
// User: "Update Sunny Days Childcare"
// Response (via SSE stream):
{
  "type": "vague_update_clarification",
  "message": "I need more details to complete this update. Please specify what you'd like to change.",
  "session_id": "xyz-789",
  "account_id": "29119",
  "account_name": "Sunny Days Childcare",
  "clarification_fields": [
    {
      "id": "stage",
      "label": "Pipeline Stage",
      "type": "select",
      "options": ["New Lead", "Application Received", "Quoted", "Bound", "Closed Won", "Closed Lost"],
      "current_value": "Quoted"
    },
    {
      "id": "insurance_types",
      "label": "Insurance Types",
      "type": "multi-select",
      "options": ["Workers' Compensation", "General Liability", "Commercial Auto", ...],
      "current_value": ["Workers' Compensation"]
    },
    {
      "id": "next_step",
      "label": "Next Step",
      "type": "text",
      "placeholder": "What's the next action item?"
    },
    {
      "id": "note",
      "label": "Add a Note",
      "type": "textarea",
      "placeholder": "Add any notes about this account..."
    }
  ]
}

// User fills form and submits via POST /confirm
{
  "session_id": "xyz-789",
  "confirmed": true,
  "clarification_data": {
    "stage": "Bound",
    "note": "Policy bound effective 2/1/2026"
  }
}

// Response:
{
  "type": "success",
  "message": "Updated Sunny Days Childcare: stage: Bound, note: Policy bound effective 2/1/2026",
  "changes": [
    {"field": "stage", "old_value": "Quoted", "new_value": "Bound"},
    {"field": "note", "old_value": "", "new_value": "Policy bound effective 2/1/2026"}
  ],
  "history_entry_id": "2026-01-22T10:30:00Z",
  ...
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
4. User fills optional details form and confirms via `/confirm` endpoint
5. **Starter Agent** routes to **Updater Agent** (account-create skill)
6. **Updater Agent** creates account folder, state.md, history.md
7. **Updater Agent** indexes in Qdrant (name + description)
8. **Starter Agent** continues with original request → routes to Updater Agent
9. **Updater Agent** adds the note

### Flow: Vague Update with Clarification (v3.7)

User: "Update Sunny Days Childcare"

1. **Starter Agent** classifies as `update` intent, extracts "Sunny Days Childcare"
2. **Starter Agent** looks up account → found (ID: 29119)
3. **Starter Agent** routes to Updater Agent
4. **Updater Agent** parses update request → detects it's too vague
5. **Updater Agent** returns clarification request with form fields
6. **UI** shows VagueUpdateClarificationModal with:
   - Current values for reference
   - Dropdowns/inputs for stage, insurance types, next step, notes
7. User fills in: stage → "Bound", note → "Policy effective 2/1"
8. User submits clarification via `/confirm` with `clarification_data`
9. **Updater Agent** processes clarified update normally
10. **Updater Agent** updates `state.md`, `history.md`, and Qdrant

### Flow: Automated Follow-Up (v3.5)

User: "Follow up with Maple Avenue Dental"

1. **Starter Agent** classifies as `followup` intent, extracts "Maple Avenue Dental"
2. **Starter Agent** looks up account → found (ID: 29041)
3. **Starter Agent** routes to Follow-Up Agent with account info
4. **Follow-Up Agent** reads `state.md` for context (stage: Quoted, 48 days since contact)
5. **Follow-Up Agent** reads recent source summaries for conversation history
6. **Follow-Up Agent** drafts personalized email using Claude
7. **Follow-Up Agent** records action in `history.md`
8. **Follow-Up Agent** returns draft with execution status

### Flow: Batch Follow-Up Processing (v3.5)

Via API: `POST /followup/batch`

1. **Follow-Up Agent** scans all accounts in `mem/accounts/`
2. For each account, checks stage and last contact date
3. Filters to accounts exceeding their stage threshold
4. Sorts by urgency (critical > high > normal)
5. For each account (up to limit):
   - Drafts appropriate communication based on stage
   - Executes (if not dry_run) or just records draft
6. Returns results for all processed accounts

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

**Portability:** Skills follow a standard structure, making them portable across Claude-powered platforms.

**Future-Proof:** As we add more agents (reporting, notifications, ingestion), each gets its own skill folder without bloating existing agents.

---

## Context Engineering

Harper is built on **context engineering** principles - the practice of carefully designing what information an AI model receives in its context window to maximize effectiveness.

### What is Context Engineering?

Unlike prompt engineering (which focuses on *how* you ask), context engineering focuses on *what context* you provide and *when*. The core insight: LLMs are stateless - they only know what's in their context window. Context engineering is about strategically managing that window.

### The Three Pillars

#### 1. Agent Skills (Modular Instructions)

Instead of one giant system prompt, Harper breaks instructions into granular skill folders:

```
skills/
├── search/
│   ├── name-lookup/       # Find by company name
│   ├── description-search/ # Find by attributes
│   ├── file-navigation/   # Read account files
│   └── text-search/       # Search in files
├── update/
│   ├── state-edit/        # Modify state.md
│   ├── history-chain/     # Maintain history
│   └── qdrant-sync/       # Update search index
└── followup/
    ├── pending-scan/      # Find accounts needing follow-up
    ├── communication-draft/ # Draft messages
    └── action-execute/    # Execute and record
```

**Why:** Each skill teaches when/how to use specific tools. Agents only load the skills they need.

#### 2. Progressive Disclosure (Load On-Demand)

Not all context is loaded at once:

| Level | What's Loaded | When | Token Cost |
|-------|--------------|------|------------|
| 1 | Skill name + description (XML) | At startup | ~50-100 tokens per skill |
| 2 | Full SKILL.md | When agent activates skill | ~150-300 tokens |
| 3 | references/ or assets/ | On-demand during execution | ~100-500 tokens each |

**Why:** Saves tokens. The agent only loads a skill when it decides it's relevant.

#### 3. Filesystem as Memory

Everything is stored as markdown files the agent can explore:

- `state.md` - Current account status (LLM-friendly structure)
- `history.md` - Linked list of changes (temporal context)
- `sources/*/summary.md` - Compressed summaries of raw communications

**Why:** Human-readable, LLM-friendly, tool-accessible.

### Key Patterns

| Pattern | Implementation | Benefit |
|---------|---------------|---------|
| **Structured Frontmatter** | YAML in SKILL.md | Quick scanning without full load |
| **Source Summaries** | Concise summary.md + raw.txt per communication | Summaries proportional to source length, not templated |
| **Semantic Search** | Qdrant vectors for accounts | Instant discovery, no exploration tokens |
| **History Chain** | Linked entries with `Previous:` links | Temporal context on demand |
| **Tool Schemas** | Explicit definitions per tool | Clear capabilities for the model |

### Context Flow Example

Query: "Follow up with Maple Avenue Dental"

```
Step 1: Starter Agent
├── Uses: Hardcoded intent classification prompt (~150 tokens)
├── Task: Classify intent → "followup"
└── Output: Route to Follow-Up Agent

Step 2: Account Resolution  
├── Loads: Qdrant query (0 LLM tokens)
├── Task: Find account ID
└── Output: account_id=29041

Step 3: Follow-Up Agent
├── Loads progressively:
│   ├── Available skills metadata (~150 tokens, 3 skills × 50)
│   ├── pending-scan/SKILL.md (~200 tokens, if needed)
│   ├── communication-draft/SKILL.md (~200 tokens, activated)
│   ├── state.md (~200 tokens)
│   └── assets/templates.md (~400 tokens, only if needed)
├── Task: Draft personalized email
└── Output: Email with subject, body, rationale

Total: ~1,000 tokens vs ~2,000+ if all loaded upfront
```

### Benefits

| Metric | Without Context Engineering | With Context Engineering |
|--------|---------------------------|-------------------------|
| Tokens per query | 5,000+ | 1,200-1,600 |
| Agent confusion | High (mixed instructions) | Low (focused context) |
| Add new agent | Edit monolithic prompt | Add new skill folder |
| Debug issues | Unclear what agent saw | Clear context per agent |
| Cost per query | Higher | ~70% reduction |

---

## React UI

The frontend is a React + TypeScript application built with Vite that provides real-time visualization of agent operations.

### UI Components

| Component | File | Purpose |
|-----------|------|---------|
| **ExplorerLayout** | `ExplorerLayout.tsx` | Main layout with header, panels, and modals |
| **ConfirmationModal** | `ConfirmationModal.tsx` | New account confirmation with optional details form |
| **ClarificationModal** | `ConfirmationModal.tsx` | Clarification prompt dialog |
| **VagueUpdateClarificationModal** | `ConfirmationModal.tsx` | Form for specifying update details (v3.7) |
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
completed / error / awaiting_confirmation / awaiting_clarification / awaiting_vague_update_clarification
                                                                            ↓ (user fills form)
                                                                         running → completed
```

### Key UI Features

1. **Starter Agent Thinking Card (v3.3)**: Shows the Starter Agent's decision-making process:
   - **Intent Classification**: Displays detected intent (search/update/followup) with confidence score
   - **Account Extraction**: Shows the extracted account name from the query
   - **Routing Decision**: Visual indicator of which agent was selected
   - **Skill Loading**: Shows which Agent Skill was loaded with name and description

2. **Agent Routing Indicator**: Shows whether Search Agent, Updater Agent, or Follow-Up Agent is handling the request

2. **Update Result Card (v3.2)**: For update operations, shows comprehensive proof:
   - **Account Info**: ID and name of the updated account
   - **State Changes**: Each field with old value (strikethrough) → new value
   - **Files Modified**: List of files that were changed with checkmarks
   - **Qdrant Status**: Confirmation that the vector DB was updated
   - **New Description**: The updated searchable description (expandable)
   - **History Chain**: Previous entry link → New entry timestamp

3. **Confirmation Modal (v3.7)**: For new account creation:
   - Shows account name to create
   - Lists similar accounts (alternatives)
   - Expandable "Add Details" form with optional fields:
     - Industry (dropdown with common industries)
     - Location (text input)
     - Primary Email / Phone (text inputs)
     - Insurance Types (multi-select checkboxes)
     - Notes (textarea)
   - All fields optional - can create with just the name
   - Confirm/Cancel buttons

4. **Clarification Modal**: For unclear queries:
   - Shows clarification message
   - Lists suggested rephrases
   - Click to use suggestion

5. **Vague Update Clarification Modal (v3.7)**: For vague update requests:
   - Shows account name being updated
   - Dynamic form based on clarification fields:
     - Pipeline Stage (dropdown with current value shown)
     - Insurance Types (multi-select with current values)
     - Next Step (text input)
     - Add Note (textarea)
   - Shows current values for reference
   - Apply Update / Cancel buttons
   - Requires at least one field to be filled

### TypeScript Types

Key types in `ui/src/types/exploration.ts`:

```typescript
type ResponseType = 'success' | 'confirmation_required' | 'clarification_needed' | 'error';
type IntentType = 'search' | 'update' | 'followup' | 'unclear';
type AgentType = 'search_agent' | 'updater_agent' | 'followup_agent';

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

// Clarification field for vague update forms (v3.7)
interface ClarificationField {
  id: string;
  label: string;
  type: 'select' | 'multi-select' | 'text' | 'textarea';
  options?: string[];
  placeholder?: string;
  current_value?: string | string[];
}

// Pending vague update clarification (v3.7)
interface PendingVagueUpdateClarification {
  session_id: string;
  message: string;
  account_id: string;
  account_name: string;
  clarification_fields: ClarificationField[];
  original_query: string;
}

interface ExplorationState {
  status: 'idle' | 'running' | 'completed' | 'error' | 'awaiting_confirmation' | 'awaiting_clarification' | 'awaiting_vague_update_clarification';
  query: string;
  steps: ExplorationStep[];
  routedTo?: AgentType;
  changes?: StateChange[];
  historyEntryId?: string;
  updateDetails?: UpdateDetails;  // Rich proof of updates (v3.2)
  pendingConfirmation?: PendingConfirmation;
  pendingVagueUpdateClarification?: PendingVagueUpdateClarification;  // v3.7
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
