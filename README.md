# Complaint Creator Manager

An AI-powered complaint management system for Supreme Pharma that ingests emails from Gmail, classifies them using Ollama LLM, stores structured data in SQLite, and enables semantic search via ChromaDB vector database.

---

## Architecture Overview

```
Gmail API ──► FastAPI ──► Ollama (LLM)
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
      SQLite            ChromaDB
  (Structured DB)      (Vector Store)
          ▲                   │
          └─────────┬─────────┘
                    ▼
              RAG Retrieval
                    │
              Ollama (Chat)
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| API Framework | FastAPI |
| Database | SQLite + SQLAlchemy ORM |
| Vector Store | ChromaDB (Persistent) |
| LLM | Ollama (mistral-large-3 or similar) |
| Embeddings | nomic-embed-text (via Ollama) |
| Email | Gmail API (google-api-python-client) |
| Auth | OAuth 2.0 (Google) |

---

## Project Structure

```
Complaint Creator using Mail/
├── main.py                          # FastAPI app entry point
├── app/
│   ├── main.py                      # (unused, kept for reference)
│   ├── models/
│   │   └── complaint_manager.py     # SQLAlchemy ORM model
│   ├── db/
│   │   └── database.py              # SQLite engine + session factory
│   ├── agents/
│   │   ├── complaint_summary_agent.py  # Ollama classification & suggestion
│   │   ├── vector_store.py          # ChromaDB store + upsert
│   │   ├── classification_prompt.txt # System prompt for classification
│   │   └── suggestion_prompt.txt    # System prompt for field suggestions
│   └── api/
│       └── mailAPI/
│           ├── routes.py            # All API endpoints
│           └── crud.py              # SQLite CRUD operations
├── chroma_db/                       # ChromaDB persistent storage
├── last_fetch_state.json            # Incremental sync state
├── requirements.txt
└── .env
```

---

## Database Schema

**Table: `complaints`**

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer | Auto-increment primary key |
| `complaint_id` | String | Unique ID (e.g., `COM_0001`) |
| `email_id` | String | Gmail message ID |
| `email_date` | String | Original email date |
| `fetched_at` | String | When the email was ingested |
| `sender` | String | Email sender |
| `recipient` | String | Email recipient |
| `subject` | String | Email subject |
| `body_snippet` | Text | Email body (snippet) |
| `is_complaint` | Integer | `1` = complaint, `0` = not |
| `category` | String | Complaint category |
| `sub_category` | String | Sub-category |
| `severity` | String | Critical / High / Medium / Low |
| `department` | String | Assigned department |
| `product` | String | Product name |
| `batch_number` | String | Batch/lot number |
| `shift` | String | Morning / Afternoon / Night |
| `status` | String | new / in_review / resolved |
| `reviewed_by` | String | Reviewer name |
| `reviewed_at` | String | Review timestamp |
| `resolution` | Text | Resolution notes |
| `chroma_id` | String | ChromaDB record ID |
| `created_at` | String | Record creation time |
| `updated_at` | String | Last update time |

**Indexes:**
- `complaint_id` (unique)
- `email_id` (unique)

---

## API Endpoints

Base URL: `/api`

---

### `GET /api/read_mails_by_date`

Fetch emails from Gmail since `last_fetch_date`, classify each one using Ollama, and store complaints to SQLite + ChromaDB.

**Request**

| Type | Parameter | Location | Description |
|------|-----------|----------|-------------|
| Query | `max_results` | int | Max emails to fetch. Default: `50` |

```
GET /api/read_mails_by_date?max_results=50
```

**Response** `200`

```json
{
  "status": "success",
  "data": [
    {
      "id": "abc123",
      "thread_id": "thread_xyz",
      "snippet": "Email snippet...",
      "from": "sender@example.com",
      "to": "recipient@example.com",
      "subject": "Complaint about broken tablets",
      "date": "Mon, 29 Mar 2026 10:00:00 +0000",
      "body": "Full email body text..."
    }
  ],
  "from_date": "2026-03-01 00:00:00",
  "to_date": "2026-03-29 22:52:55",
  "classification_output": [
    {
      "is_complaint": "1",
      "category": "Product Quality",
      "sub_category": "Broken tablets",
      "severity": "High",
      "department": "Quality Assurance",
      "product": "Aspirin 500mg",
      "batch_number": "BATCH_2026_03",
      "shift": "Morning",
      "status": "new",
      "email_id": "abc123"
    }
  ]
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `500` | `credentials.json` not found — Gmail API not configured |
| `500` | `{"detail": "<error message>"}` — Gmail query or classification failed |

---

### `POST /api/init_fetch`

Initialize `last_fetch_date` before the first `read_mails_by_date` call. Without this, no emails will be fetched.

**Request**

| Type | Field | Location | Description |
|------|-------|----------|-------------|
| Body | `from_date` | string | Start date in `YYYY-MM-DD` format |

```
POST /api/init_fetch
Content-Type: application/json

{
  "from_date": "2026-01-01"
}
```

**Response** `200`

```json
{
  "status": "success",
  "message": "Last fetch date initialized to 2026-01-01 00:00:00",
  "last_fetch_date": "2026-01-01 00:00:00"
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `400` | `{"detail": "Invalid date format. Use YYYY-MM-DD"}` |

---

### `GET /api/extract/complaint_manager database`

Returns all complaints stored in the SQLite database.

**Request**

```
GET /api/extract/complaint_manager database
```

**Response** `200`

```json
{
  "email_details": [
    {
      "id": 1,
      "complaint_id": "COM_0001",
      "email_id": "abc123",
      "email_date": "Mon, 29 Mar 2026 10:00:00 +0000",
      "fetched_at": "2026-03-29 22:52:55",
      "sender": "sender@example.com",
      "recipient": "recipient@example.com",
      "subject": "Complaint about broken tablets",
      "body_snippet": "Email snippet...",
      "is_complaint": 1,
      "category": "Product Quality",
      "sub_category": "Broken tablets",
      "severity": "High",
      "department": "Quality Assurance",
      "product": "Aspirin 500mg",
      "batch_number": "BATCH_2026_03",
      "shift": "Morning",
      "status": "new",
      "reviewed_by": null,
      "reviewed_at": null,
      "resolution": null,
      "chroma_id": "abc123",
      "created_at": "2026-03-29 22:52:55",
      "updated_at": "2026-03-29 22:52:55"
    }
  ]
}
```

---

### `GET /api/debug/chroma`

Returns the full ChromaDB collection state. Useful for debugging vector storage.

**Request**

```
GET /api/debug/chroma
```

**Response** `200`

```json
{
  "count": 42,
  "ids": ["abc123", "def456"],
  "metadatas": [
    {
      "sender": "sender@example.com",
      "subject": "Complaint about broken tablets",
      "email_date": "Mon, 29 Mar 2026 10:00:00 +0000",
      "category": "Product Quality",
      "severity": "High",
      "department": "Quality Assurance",
      "product": "Aspirin 500mg"
    }
  ],
  "collection": ["Complaint about broken tablets\nFull email body..."],
  "results": {
    "ids": [["abc123"]],
    "distances": [[0.123]],
    "metadatas": [[{...}]],
    "documents": [["..."]]
  }
}
```

---

### `GET /api/complaints/{complaint_id}`

Fetch a single complaint by its `complaint_id` (e.g., `COM_0001`).

**Request**

| Type | Parameter | Location | Description |
|------|-----------|----------|-------------|
| Path | `complaint_id` | string | The complaint ID (e.g., `COM_0001`) |

```
GET /api/complaints/COM_0001
```

**Response** `200`

```json
{
  "status": "success",
  "complaint": {
    "complaint_id": "COM_0001",
    "email_id": "abc123",
    "email_date": "Mon, 29 Mar 2026 10:00:00 +0000",
    "sender": "sender@example.com",
    "subject": "Complaint about broken tablets",
    "body_snippet": "Email snippet...",
    "is_complaint": 1,
    "category": "Product Quality",
    "sub_category": "Broken tablets",
    "severity": "High",
    "department": "Quality Assurance",
    "product": "Aspirin 500mg",
    "batch_number": "BATCH_2026_03",
    "shift": "Morning",
    "status": "new",
    "reviewed_by": null,
    "reviewed_at": null,
    "resolution": null,
    "chroma_id": "abc123",
    "created_at": "2026-03-29 22:52:55",
    "updated_at": "2026-03-29 22:52:55"
  }
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | `{"detail": "Complaint COM_XXXX not found"}` |

---

### `PUT /api/complaints/{complaint_id}`

Update complaint fields. Updates both SQLite and ChromaDB (deletes old vector and re-inserts with updated metadata).

**Request**

| Type | Parameter | Location | Description |
|------|-----------|----------|-------------|
| Path | `complaint_id` | string | The complaint ID to update |
| Body | `*` | dict | Any complaint fields to update |

```
PUT /api/complaints/COM_0001
Content-Type: application/json

{
  "category": "Product Quality",
  "severity": "Critical",
  "department": "Quality Assurance",
  "status": "in_review",
  "reviewed_by": "john.doe"
}
```

All fields in the [schema](#database-schema) are valid update targets.

**Response** `200`

```json
{
  "status": "success",
  "message": "Complaint COM_0001 updated",
  "complaint_id": "COM_0001"
}
```

**Error Responses**

| Status | Detail |
|--------|--------|
| `404` | `{"detail": "Complaint COM_XXXX not found"}` |

> **Feedback Loop:** Corrections made here update both SQLite and ChromaDB, ensuring RAG retrieval reflects the latest metadata.

---

## LLM Classification Fields

When an email is classified as a complaint (`is_complaint: "1"`), the following fields are extracted:

| Field | Options |
|-------|---------|
| `category` | Product Quality, Adverse Event, Packaging, Labeling, Delivery, Regulatory, Other |
| `sub_category` | Specific issue (e.g., Broken tablets, Missing seal) |
| `severity` | Critical, High, Medium, Low |
| `department` | Quality Assurance, Production, Warehouse, Regulatory Affairs, Medical Affairs, Customer Service |
| `product` | Product name or "Unknown" |
| `batch_number` | Batch/lot number or "Unknown" |
| `shift` | Morning, Afternoon, Night, Unknown |
| `status` | Always "new" for new complaints |

---

## Incremental Sync

`last_fetch_state.json` tracks the last successful fetch timestamp:

```json
{
  "last_fetch_date": "2026-03-29 22:52:55"
}
```

- **`/api/init_fetch`** sets the initial date (first run)
- **`/api/read_mails_by_date`** updates it after each successful fetch
- On first call without `init_fetch`, returns empty data with instruction to set initial date

---

## Ollama Configuration

From `app/agents/complaint_summary_agent.py`:

| Setting | Value |
|---------|-------|
| `OLLAMA_HOST` | `https://ollama.com` (cloud API) |
| `OLLAMA_MODEL` | `mistral-large-3:675b-cloud` (configurable via env) |
| Embedding Model | `nomic-embed-text` (local Ollama) |

**Local Ollama Setup:**
```bash
# Install Ollama from https://ollama.com
ollama pull nomic-embed-text  # for embeddings
ollama pull mistral-large-3   # for LLM (or llama3.1, mistral)
```

---

## Gmail API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Gmail API**
3. Create **OAuth 2.0 credentials** (Desktop app)
4. Download `credentials.json` → place in project root
5. Set in `.env`:
   ```
   SCOPES=['https://mail.google.com/']
   TOKEN_PATH=token.json
   CREDENTIALS_PATH=credentials.json
   ```
6. On first run, browser opens for OAuth consent → approve
7. `token.json` is generated automatically

---

## Environment Variables

Create a `.env` file:

```env
SCOPES=['https://mail.google.com/']
TOKEN_PATH=token.json
CREDENTIALS_PATH=credentials.json
OLLAMA_API_KEY=your_ollama_api_key
OLLAMA_MODEL=mistral-large-3:675b-cloud
OLLAMA_HOST=https://ollama.com
```

---

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn main:app --reload

# Access docs
# http://localhost:8000/docs   (Swagger UI)
# http://localhost:8000/redoc  (ReDoc)
```

---

## TODO

- [ ] Pull a free Ollama model (llama3.1 or mistral) locally
- [ ] Build RAG retrieval (embed query → ChromaDB search)
- [ ] Build chat prompt with context injection
- [ ] Build chat UI (Chainlit or Gradio)
- [ ] Build manual complaint creation form
- [ ] Build create-complaint API
- [ ] Add feedback loop for corrections
- [ ] Build suggestion prompt for all fields
- [ ] Build incremental email fetch (already implemented)

---

## Classification Prompt (Reference)

The system prompt in `app/agents/classification_prompt.txt` instructs Ollama to:
- Classify emails as complaint/non-complaint
- Extract: category, sub_category, severity, department, product, batch_number, shift
- Return ONLY valid JSON
- Default to "Unknown" for missing fields
- Classify adverse events as "Product Quality" with High/Critical severity
