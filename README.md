# Harper AI Sales Assistant

An AI-powered agentic system for insurance brokers that manages account memory through a filesystem-based architecture. The system uses Claude as the reasoning engine, Qdrant for semantic search, and structured markdown-based memory for transparency and auditability.

## Features

- **Semantic Account Search** - Find accounts by company name or attributes (stage, location, industry)
- **File-Based Memory** - All account data stored as readable markdown files
- **Audit Trail** - Complete history tracking with links to evidence
- **Multi-Source Ingestion** - Process emails, calls, and SMS into structured memory
- **REST API + Web UI** - Interactive Streamlit interface and FastAPI backend

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Streamlit UI  │────▶│   FastAPI Server │────▶│   Orchestrator  │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                        ┌─────────────────────────────────┼─────────────────────────────────┐
                        │                                 │                                 │
                        ▼                                 ▼                                 ▼
               ┌─────────────────┐             ┌─────────────────┐             ┌─────────────────┐
               │  Name Registry  │             │   Claude API    │             │  Filesystem     │
               │    (Qdrant)     │             │   (Reasoning)   │             │  (mem/)         │
               └─────────────────┘             └─────────────────┘             └─────────────────┘
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| LLM | Claude (Anthropic API) |
| Embeddings | OpenAI |
| Vector DB | Qdrant |
| Backend | FastAPI + Uvicorn |
| Frontend | Streamlit |
| Memory Storage | Markdown files |

## Setup

### Prerequisites

- Python 3.8+
- Qdrant running locally or in cloud
- API keys for Anthropic and OpenAI

### Installation

1. Clone the repository:
```bash
git clone https://github.com/AHussain101/harper_work_trial.git
cd harper_work_trial
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your API keys:
```env
ANTHROPIC_API_KEY=your_anthropic_key
OPENAI_API_KEY=your_openai_key
QDRANT_URL=http://localhost:6333
```

4. Run the ingestion pipeline (if starting fresh):
```bash
python ingest.py
```

## Usage

### Start the API Server

```bash
python server.py
```

The server runs on `http://localhost:8000`.

### Start the Web UI

```bash
streamlit run app.py
```

The UI runs on `http://localhost:8501`.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/query` | POST | Send a question, get an answer |

## Project Structure

```
harper_v3/
├── app.py              # Streamlit web interface
├── server.py           # FastAPI REST server
├── orchestrator.py     # Agent loop & tool execution
├── name_registry.py    # Qdrant vector search
├── ingest.py           # Data ingestion pipeline
├── mem/
│   ├── system_rules.md # Agent instructions
│   └── accounts/       # Account memory
│       └── {id}/
│           ├── state.md    # Current account info
│           ├── history.md  # Change log
│           └── sources/    # Communications
│               ├── emails/
│               ├── calls/
│               └── sms/
└── requirements.txt
```

## Agent Tools

| Tool | Purpose |
|------|---------|
| `lookup_account` | Find accounts by company name |
| `search_descriptions` | Find accounts by attributes |
| `list_files` | List files at a path |
| `read_file` | Read file contents |
| `search_files` | Search text within files |

## License

MIT
