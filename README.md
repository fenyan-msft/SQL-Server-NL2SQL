# AdventureWorks Cycles AI Assistant

A Python desktop demo application using SQL Server 2025 that lets you type or speak questions and get answers from an LLM or your SQL Server — automatically routed by an orchestrator agent. The domain agent that the question is routed to uses a workflow to generate NL2SQL queries, including semantic search where relevant, and formulates the response to the user.  

---

## Quick-start

### 1. Prerequisites

- Python 3.11 or later
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) (if using SQL Server)
- A working microphone (optional — the app works without one)

> **PyAudio on Windows** (optional — install if using speech to text to enter input) 
— if `pip install pyaudio` fails, install a pre-built wheel:
> ```
> pip install pipwin
> pipwin install pyaudio
> ```

### 2. Deploy models in Azure AI Foundry

In your [Azure AI Foundry](https://ai.azure.com) project, deploy the following models:

| Model | Purpose |
|---|---|
| `text-embedding-3-small` | Generates vector embeddings for semantic/vector search |
| `gpt-4.1` | Powers the orchestrator and domain agents |

After deployment, copy the endpoint URL and API key for each model into `config.py`.

### 3. Clone the repository

```
git clone https://github.com/fenyan-msft/ConversationalAI.git
cd ConversationalAI
```

### 4. Create and activate a virtual environment

```
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> **Note:** If you see a script execution error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` first.

### 5. Install dependencies

```
pip install -r requirements.txt
```

### 6. SQL Server Setup

Restore a backup of AdventureWorks from https://learn.microsoft.com/en-us/sql/samples/adventureworks-install-configure?view=sql-server-ver17&tabs=ssms. Either AdventureWorks2022.bak or AdventureWorks2025.bak can be used.

Run the code in the files in `sql_setup/` against your AdventureWorks database **in order**. Note that you may need to run a step at a time in some cases:

| Script | What it does |
|---|---|
| `001 Adjust Order Dates to be recent.sql` | Shifts order dates so data appears current |
| `002 Adventureworks service account.sql` | Creates the service account used by the app |
| `003 Row Level Security.sql` | Applies row-level security policies per PersonID |
| `004 Loyalty Schema.sql` | Creates the loyalty programme schema and tables |
| `005 Add Extended Properties.sql` | Adds column descriptions used for schema context |
| `006 Vector Search.sql` | Creates vector columns and indexes for semantic search |

### 7. Configure endpoints

Open **`config.py`** and replace every `YOUR_*` placeholder:

```
# Search for all placeholders (PowerShell):
Select-String -Path config.py -Pattern "YOUR_"
```

### 8. Run

```
python main.py
```

---

## Project structure

```
ConversationalAI/
├── main.py                   Entry point
├── config.py                 All configuration (gitignored — copy from example_config.py)
├── example_config.py         Configuration template with all placeholders
├── requirements.txt
│
├── agent/
│   └── nl2sqlagents.py       LangGraph pipeline: orchestrator → domain agents → SQL/vector execution
│
├── prompts/
│   ├── orchestrator_agent.prompty
│   ├── customer_service_agent.prompty
│   ├── product_recommender_agent.prompty
│   └── loyalty_programme_agent.prompty
│
├── services/
│   ├── llm_service.py        LLM embeddings and chat history
│   ├── sql_service.py        SQL Server connection, schema introspection, query execution
│   └── speech_service.py     Microphone capture + speech-to-text transcription
│
├── tools/
│   ├── orchestrator_tools.py
│   ├── sql_generator_tools.py
│   ├── validate_tools.py
│   ├── query_runner_tools.py
│   ├── vector_search_tools.py
│   └── grounder_tools.py
│
└── ui/
    ├── login_window.py       PersonID selection screen
    └── chat_window.py        Tkinter chat window (the visible application)
```

---

## Routing logic

The pipeline is a three-level [LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph` defined in `agent/nl2sqlagents.py`:

```
User input
    │
    └─ Orchestrator node  (classifies intent)
           │
           ├─ customer_service    ──► SQL generator ──┐
           ├─ product_recommender ──► SQL generator ──┤
           ├─ loyalty_programme   ──► SQL generator ──┤
           │                                          │
           │                              ┌───────────┘
           │                              │
           │                    LIKE / text search?
           │                     Yes ──► vector_pipeline (VECTOR_DISTANCE cosine)
           │                     No  ──► sql_pipeline    (exact T-SQL)
           │
           └─ General / clarifying question ──► direct LLM answer

sql_pipeline:    validate → repair (×3 max) → query_runner → responder
vector_pipeline: vector_search → validate → repair (×3 max) → query_runner → responder
```

---

## Speech recognition engines

| Engine | Requires | Notes |
|---|---|---|
| `"google"` | Internet connection | Free, no key needed |
| `"azure"` | `AZURE_SPEECH_KEY` + `AZURE_SPEECH_REGION` in config.py | Azure Cognitive Services |
| `"whisper"` | Local compute | Uses OpenAI Whisper model bundled with SpeechRecognition |

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| **Enter** | Send message |
| **Ctrl+C** | Copy selected chat text |
| **Ctrl+A** | Select all chat text |
| **Ctrl+L** | Clear conversation |
| **Right-click** | Context menu (Copy / Select All / Clear) |

---

## Security notes

- The SQL service rejects any statement that is not a `SELECT`, `WITH`, or
  `sp_help` call — preventing accidental data modification.
- For production deploymentsconsider using environment variables or a secrets manager (e.g. Azure Key Vault) 
