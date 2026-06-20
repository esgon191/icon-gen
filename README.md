# icon-gen

Icon generator. The user writes a prompt in OpenWebUI, the backend takes
N random references from storage, concatenates their pre-computed
style descriptions, and sends the style + user prompt to a Text-to-Image
model. The result is returned to OpenWebUI as an image in the chat.

**Key design decision:** a vision LLM (LLaVA via Ollama) analyzes
**each reference once, at upload time**, and stores the style description in the DB.
No LLM is called on generation requests — ready-made descriptions are used instead.
This keeps the generation step fast and removes T2I's dependency on
Ollama's availability.

## Stack

- **FastAPI** — API layer (port 8000)
- **PostgreSQL** — metadata (`object_key`, `prompt`, `style_description`)
- **MinIO** — S3-compatible storage for image binaries
- **icon-style** — microservice (FastAPI + Ollama + LLaVA:13b), style analysis (port 8001)
- **SQLAlchemy** — ORM
- **Docker Compose** — orchestration for all services

T2I is currently a stub (`StubT2IClient`) — when connecting a real model,
a new implementation is added in `backend/app/clients/` and the factory
in `backend/app/deps.py` is updated. The rest of the code stays untouched.

## Running

### Prerequisite — Ollama on the host

LLaVA runs through Ollama, which runs on the host (not in Docker, to avoid
pulling 8+ GB of model weights and the GPU into the image).

```bash
# 1. Install Ollama from https://ollama.com/download
# 2. Start the server
ollama serve &
# 3. Pull the model (once, ~8 GB)
ollama pull llava:13b
```

### Running the project

```bash
cp .env.example .env
docker compose up --build
```

- Backend API: http://localhost:8000 (Swagger UI at `/docs`)
- icon-style API: http://localhost:8001 (Swagger UI at `/docs`)
- MinIO console: http://localhost:9001 (`minioadmin` / `minioadmin`)
- Postgres: `localhost:5432` (`icon` / `icon`)

Check that icon-style can see Ollama:
```bash
curl http://localhost:8001/health
# {"status":"ok","ollama_available":true,...}
```

---

## Architecture

### Overall service diagram

```mermaid
flowchart LR
    User([User])
    OWU[OpenWebUI<br/>Andryukha]
    BE[Backend<br/>FastAPI]
    IS[icon-style<br/>Tyomych]
    OL[Ollama<br/>LLaVA:13b]
    T2I[Text-to-Image<br/>Timur]
    PG[(PostgreSQL<br/>metadata + style)]
    S3[(MinIO / S3<br/>binaries)]

    User -->|text| OWU
    OWU <-->|OpenAI-compatible| BE
    BE -->|on upload<br/>image| IS
    IS <-->|vision prompt| OL
    IS -->|style_prompt| BE
    BE <-->|prompt + style| T2I
    BE <-->|CRUD + style_description| PG
    BE <-->|put/get/delete<br/>by object_key| S3

    style BE fill:#d1e7ff,stroke:#0066cc
    style PG fill:#e7d9ff,stroke:#6b2fc0
    style S3 fill:#ffe4cc,stroke:#cc6600
    style IS fill:#fff4b0,stroke:#b08800
```

The backend is the central hub. Communication with icon-style happens
**only on reference upload**: style analysis runs once and is saved to
Postgres. The vision LLM is not called during icon generation. All external
services sit behind Protocol interfaces, so real implementations can be
plugged in without rewriting business logic.

### Flow 1 — uploading a reference (`POST /v1/context`)

An admin/curator uploads an image with a text description to storage —
this is the "style context" that will later feed the T2I model. In the same
step, the backend asks icon-style to describe the image's visual style,
and the description is stored alongside it in the DB.

```mermaid
sequenceDiagram
    participant Admin
    participant Router as routers/context.py
    participant Storage as S3Storage
    participant Analyzer as StyleAnalyzer
    participant Repo as ContextRepository
    participant MinIO
    participant IS as icon-style + Ollama
    participant PG as PostgreSQL

    Admin->>Router: POST /v1/context with prompt and file
    Router->>Router: generates object_key = uuid.ext
    Router->>Storage: put key + bytes
    Storage->>MinIO: PutObject
    Router->>Analyzer: analyze image_bytes
    Analyzer->>IS: POST /analyze
    IS-->>Analyzer: style_prompt or error
    Analyzer-->>Router: string or None
    Router->>Repo: add object_key + prompt + style_description
    Repo->>PG: INSERT INTO style_context
    PG-->>Repo: id + created_at
    Repo-->>Router: StyleContext
    Router-->>Admin: 201 Created
```

If icon-style is unavailable, the record is still created with
`style_description = null`. A re-analysis can be triggered later via
`POST /v1/context/{id}/reanalyze`.

Metadata and the binary live separately, linked via `object_key`:

```
PostgreSQL                                   MinIO bucket "icon-context"
┌───────────────────────────────────────┐     ┌────────────────────────────┐
│ style_context                         │     │ ab12cd34.png   [binary]    │
│  id                = "..."            │     │ ef56gh78.jpg   [binary]    │
│  object_key        = "ab12cd34.png"  ─┼────▶│ ...                        │
│  prompt            = "blue icon"      │     │                            │
│  style_description = "flat vector     │     └────────────────────────────┘
│                       icon, bold      │
│                       outlines, ..."  │
│  content_type      = "image/png"      │
│  created_at        = 2026-04-19 ...   │
└───────────────────────────────────────┘
```

### Flow 2 — icon generation (`POST /v1/chat/completions` from OpenWebUI)

```mermaid
sequenceDiagram
    participant User
    participant OWU as OpenWebUI
    participant Router as routers/openai.py
    participant Svc as GenerationService
    participant Repo as ContextRepository
    participant T2I as T2IClient

    User->>OWU: text prompt
    OWU->>Router: POST /v1/chat/completions
    Router->>Svc: generate prompt
    Svc->>Repo: random N
    Repo-->>Svc: N × StyleContext with style_description
    Svc->>Svc: aggregates descriptions into one style string
    Svc->>T2I: generate prompt + style
    T2I-->>Svc: PNG bytes
    Svc-->>Router: prompt + style + image_base64
    Router->>Router: wraps the image in a markdown data-URI
    Router-->>OWU: OpenAI chat completion
    OWU-->>User: image in chat
```

At this step neither the vision LLM nor S3 is called — everything needed
already lives in Postgres. Only if every sampled `style_description` is
null does the style string end up empty, leaving T2I with the bare user
prompt.

### Layers and dependencies in the code

```mermaid
flowchart TB
    subgraph HTTP ["HTTP layer"]
        R1[routers/context.py]
        R2[routers/generate.py]
        R3[routers/openai.py]
    end

    subgraph Business ["Business logic"]
        S[services/generation.py<br/>GenerationService]
    end

    subgraph Data ["Data access"]
        Repo[repositories/context.py<br/>ContextRepository]
    end

    subgraph Clients ["External clients<br/>Protocol + implementation"]
        Proto[clients/base.py<br/>Protocols]
        ST[clients/storage.py<br/>S3Storage]
        AN[clients/analyzer.py<br/>OllamaStyleAnalyzerClient]
        TT[clients/t2i.py<br/>StubT2IClient]
    end

    subgraph Infra ["Infrastructure"]
        DB[(PostgreSQL)]
        S3[(MinIO)]
        IS[icon-style + Ollama]
        Future1[[future:<br/>ComfyUIT2IClient]]
    end

    R1 --> Repo
    R1 --> ST
    R1 --> AN
    R2 --> S
    R3 --> S
    S --> Repo
    S --> TT
    Repo --> DB
    ST --> S3
    AN --> IS
    AN -.implements.-> Proto
    TT -.implements.-> Proto
    ST -.implements.-> Proto
    Future1 -.implements.-> Proto

    style Proto fill:#fff4b0,stroke:#b08800
    style Future1 fill:#e8f5e9,stroke:#2e7d32,stroke-dasharray: 5 5
    style Future2 fill:#e8f5e9,stroke:#2e7d32,stroke-dasharray: 5 5
```

**Key invariant:** `GenerationService` only depends on Protocols,
never on concrete classes. Swapping stubs for real models is a one-line
change in `deps.py` — nothing else needs to change.

---

## API

### Reference storage

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/v1/context` | `multipart: prompt, file` | Upload a reference image (synchronously triggers style analysis, ~15–30 sec on LLaVA:13b) |
| `GET` | `/v1/context` | — | List all references |
| `DELETE` | `/v1/context/{id}` | — | Delete a reference (from DB and S3) |
| `POST` | `/v1/context/{id}/reanalyze` | — | Re-analyze style — for when Ollama was unavailable at upload time |

### Generation

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/generate` | Internal debugging endpoint: `{prompt, n?}` → `{image_base64, style, ...}` |
| `GET` | `/v1/models` | OpenAI-compatible, for OpenWebUI |
| `POST` | `/v1/chat/completions` | OpenAI-compatible, for OpenWebUI |

### Connecting to OpenWebUI

`Settings → Connections → OpenAI API`:

- URL: `http://backend:8000/v1` (if OpenWebUI is in the same `docker-compose.yml`)
  or `http://host.docker.internal:8000/v1` (if OpenWebUI is in a separate container on the same host)
- API Key: any non-empty string (authorization isn't checked yet)
- `icon-gen` will appear in the model list

---

## Project structure

```
icon-gen/
├── docker-compose.yml           # postgres + minio + icon-style + backend
├── .env.example                 # config template
├── icon-style/                  # Tyomych's microservice (FastAPI + Ollama LLaVA)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py              # FastAPI, lifespan, migrations, routers
        ├── config.py            # Settings via env
        ├── database.py          # SQLAlchemy engine/session
        ├── models.py            # ORM (style_context table)
        ├── schemas.py           # Pydantic for the API
        ├── deps.py              # DI — the swap point for client implementations
        ├── clients/
        │   ├── base.py          # Protocols: StorageClient / StyleAnalyzer / T2IClient
        │   ├── storage.py       # S3Storage (MinIO / AWS S3)
        │   ├── analyzer.py      # OllamaStyleAnalyzerClient → icon-style service
        │   └── t2i.py           # StubT2IClient
        ├── repositories/
        │   └── context.py       # CRUD + random(n) + set_style_description
        ├── services/
        │   └── generation.py    # repo → aggregate styles → t2i
        └── routers/
            ├── context.py       # reference CRUD + /reanalyze
            ├── generate.py      # internal /v1/generate
            └── openai.py        # OpenAI-compatible endpoints for OpenWebUI
```

---

## How to extend

**Connect a real T2I model:**
1. Create `backend/app/clients/t2i_comfy.py` (or any other filename) with
   a class implementing `generate(user_prompt, style) -> tuple[bytes, str]`.
2. In `backend/app/deps.py`, replace `return StubT2IClient()` with
   `return ComfyT2IClient()` in `get_t2i()`.
3. That's it. No router, service, or DB code needs to change.

**Custom style analyzer** (in case you ever want to skip Tyomych's service) —
add a new class with an `analyze(image_bytes, content_type) -> str | None`
method to `clients/analyzer.py`, and swap the `get_style_analyzer()` factory.

**Storage** — `S3Storage` can be repointed via env variables (AWS S3
instead of MinIO). For local filesystem storage, write a `LocalStorage`
class with the same `put/get/delete` methods.

## Settings (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://icon:icon@postgres:5432/icon` | Postgres connection string |
| `S3_ENDPOINT` | `http://minio:9000` | S3 API address |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | `minioadmin` / `minioadmin` | S3 keys |
| `S3_BUCKET` | `icon-context` | Bucket name (created automatically on startup) |
| `ICON_STYLE_URL` | `http://icon-style:8000` | Style analysis service address |
| `ICON_STYLE_TIMEOUT` | `180` | Request timeout to icon-style, seconds (LLaVA:13b can be slow) |
| `CONTEXT_SAMPLE_SIZE` | `10` | How many references to sample for generation |
| `LLM_PROVIDER` / `T2I_PROVIDER` | `stub` | Placeholder for selecting an implementation via env (not yet used) |
