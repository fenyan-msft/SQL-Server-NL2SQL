# =============================================================================
#  CONFIGURATION  —  fill in every placeholder before running the application
#  Search for "YOUR_" to find every value you must provide.
# =============================================================================

# -----------------------------------------------------------------------------
#  LARGE LANGUAGE MODEL
#  Used by the Microsoft Agent Framework (AzureOpenAIChatClient) and LLMService.
#  • Azure OpenAI  →  LLM_ENDPOINT = "https://<resource>.openai.azure.com/"
#  • OpenAI        →  LLM_ENDPOINT = "https://api.openai.com/v1"
#  • Other         →  any OpenAI-compatible endpoint
#
#  Azure AI Foundry option: to use a Foundry project endpoint instead of Azure
#  OpenAI directly, set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL_DEPLOYMENT
#  below and update orchestrator.py's _client() factory (see inline comment).
# -----------------------------------------------------------------------------
LLM_ENDPOINT      = ""
LLM_API_KEY       = ""   # Leave empty to use Entra (DefaultAzureCredential) instead of API key auth
LLM_TENANT_ID     = ""   # Leave empty to use the default tenant from the credential chain
LLM_MODEL         = ""   # e.g. "gpt-4o", "gpt-4"
LLM_API_VERSION   = ""   # Used only when LLM_ENDPOINT is Azure OpenAI
EMBEDDING_MODEL      = ""   # Used for vector / semantic search
EMBEDDING_DIMENSIONS = 1536                         # Must match the VECTOR(N) column definition
# When the embedding model is deployed in a different resource or Foundry project
# than the chat model, set EMBEDDING_ENDPOINT to that resource/project's endpoint.
# • Azure OpenAI resource:  "https://<resource>.openai.azure.com"
# • Foundry project:        "https://<hub>.services.ai.azure.com/api/projects/<project>"
#   (Foundry project endpoints require the https://ai.azure.com/.default token scope)
# Leave empty to use LLM_ENDPOINT for both chat and embeddings.
EMBEDDING_ENDPOINT   = ""   # Empty = use LLM_ENDPOINT for embeddings

# -----------------------------------------------------------------------------
#  SQL SERVER  (used for natural-language → T-SQL query generation and execution)
#  The LLM generates T-SQL; the SQL service executes it against this server.
# -----------------------------------------------------------------------------
SQL_SERVER                   = ""       # e.g. "myserver.database.windows.net"
SQL_DATABASE                 = "AdventureWorks2025"    # e.g. "AdventureWorks"
SQL_USERNAME                 = ""
SQL_PASSWORD                 = ""
SQL_DRIVER                   = "{ODBC Driver 18 for SQL Server}"   # adjust version if needed
# Authentication mode:
#   ""                          – SQL Server login (SQL_USERNAME + SQL_PASSWORD required)
#                                 After login, sp_set_session_context @key=N'PersonID' is set
#                                 on the connection so SQL Server can enforce row-level security.
#   "ActiveDirectoryIntegrated" – Entra/Azure AD integrated (no credentials needed)
#   "ActiveDirectoryInteractive" – Entra interactive MFA prompt
SQL_AUTHENTICATION           = ""   # empty = SQL Server login (SQL_USERNAME + SQL_PASSWORD)
SQL_ENCRYPT                  = True
SQL_TRUST_SERVER_CERTIFICATE = True   # required for local SQL Server with self-signed certificate
SQL_CONNECTION_TIMEOUT       = 30   # seconds

# -----------------------------------------------------------------------------
#  SPEECH RECOGNITION
#  Engine options:
#    "google"   – Google Web Speech API (free, requires internet, no key needed)
#    "azure"    – Azure Cognitive Services Speech (requires key + region below)
#    "whisper"  – OpenAI Whisper via speech_recognition (local, no key needed)
# -----------------------------------------------------------------------------
SPEECH_ENGINE       = "azure"
AZURE_SPEECH_KEY    = "YOUR_AZURE_SPEECH_KEY_HERE"
AZURE_SPEECH_REGION = "YOUR_AZURE_REGION_HERE"       # e.g. "eastus"

# -----------------------------------------------------------------------------
#  SPEECH  (Azure AI Foundry project endpoint, keyless auth)
#  A Foundry project exposes a single Cognitive Services endpoint used for
#  both speech-to-text and text-to-speech with Entra token authentication.
#  The SDK requires the explicit endpoint URL so AAD tokens are accepted.
#  • SPEECH_ENDPOINT – e.g. "https://<project>.cognitiveservices.azure.com/"
#  Leave SPEECH_ENDPOINT as the placeholder string to use the standard
#  regional endpoint (requires AZURE_SPEECH_KEY or AZURE_SPEECH_REGION).
# -----------------------------------------------------------------------------
SPEECH_ENDPOINT = "YOUR_SPEECH_ENDPOINT_HERE"   # Foundry project Cognitive Services URL


# -----------------------------------------------------------------------------
#  APPLICATION SETTINGS
# -----------------------------------------------------------------------------
APP_TITLE        = "Conversational AI Assistant"
APP_WIDTH        = 960
APP_HEIGHT       = 700
MAX_SQL_ROWS     = 200    # Maximum rows returned per SQL query
MAX_VECTOR_ROWS  = 10     # Maximum rows returned by vector similarity searches
FONT_FAMILY      = "Segoe UI"
FONT_MONO        = "Consolas"
PERSON_IDS       = [13332]  # Person IDs available in the login screen dropdown
