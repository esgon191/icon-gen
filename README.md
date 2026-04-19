# icon-gen

Генератор иконок. Пользователь пишет промпт в OpenWebUI, бэкенд достаёт
N случайных референсных картинок из хранилища, просит LLM составить описание
стиля на их основе, затем отправляет стиль + пользовательский промпт в
Text-to-Image модель. Результат возвращается в OpenWebUI картинкой в чат.

## Стек

- **FastAPI** — API слой
- **PostgreSQL** — метаданные (промпты, ключи объектов)
- **MinIO** — S3-совместимое хранилище для бинарников картинок
- **SQLAlchemy** — ORM
- **Docker Compose** — оркестрация всех трёх сервисов

LLM и T2I сейчас стабы (`StubLLMClient`, `StubT2IClient`) — при подключении
реальных моделей добавляется новая реализация в `backend/app/clients/` и
меняется фабрика в `backend/app/deps.py`. Остальной код не трогается.

## Запуск

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000 (Swagger UI на `/docs`)
- MinIO консоль: http://localhost:9001 (`minioadmin` / `minioadmin`)
- Postgres: `localhost:5432` (`icon` / `icon`)

---

## Архитектура

### Общая схема сервисов

```mermaid
flowchart LR
    User([Пользователь])
    OWU[OpenWebUI<br/>Андрюха]
    BE[Backend<br/>FastAPI]
    LLM[LLM<br/>Темыч]
    T2I[Text-to-Image<br/>Тимур]
    PG[(PostgreSQL<br/>метаданные)]
    S3[(MinIO / S3<br/>бинарники)]

    User -->|текст| OWU
    OWU <-->|OpenAI-compatible| BE
    BE <-->|промпт + N картинок| LLM
    BE <-->|промпт + стиль| T2I
    BE <-->|id, prompt,<br/>object_key| PG
    BE <-->|put/get/delete<br/>по object_key| S3

    style BE fill:#d1e7ff,stroke:#0066cc
    style PG fill:#e7d9ff,stroke:#6b2fc0
    style S3 fill:#ffe4cc,stroke:#cc6600
```

Бэкенд — центральный хаб. Все внешние сервисы (LLM, T2I, S3) за
интерфейсами-Protocol'ами, поэтому реальные реализации подключаются без
переписывания бизнес-логики.

### Flow 1 — загрузка референса (`POST /v1/context`)

Администратор/куратор заливает в хранилище картинку с текстовым описанием —
это "контекст стиля", которым потом будет кормиться LLM.

```mermaid
sequenceDiagram
    participant Admin
    participant Router as routers/context.py
    participant Storage as S3Storage
    participant Repo as ContextRepository
    participant MinIO
    participant PG as PostgreSQL

    Admin->>Router: POST /v1/context<br/>(prompt, file)
    Router->>Router: генерируем object_key<br/>= uuid4().ext
    Router->>Storage: put(key, bytes, content_type)
    Storage->>MinIO: PutObject
    Router->>Repo: add(object_key, prompt, content_type)
    Repo->>PG: INSERT INTO style_context
    PG-->>Repo: id, created_at
    Repo-->>Router: StyleContext
    Router-->>Admin: 201 { id, object_key, prompt, ... }
```

Метаданные и бинарник живут раздельно, но связаны через `object_key`:

```
PostgreSQL                               MinIO bucket "icon-context"
┌──────────────────────────────────┐     ┌────────────────────────────┐
│ style_context                    │     │ ab12cd34.png   [binary]    │
│  id            = "..."           │     │ ef56gh78.jpg   [binary]    │
│  object_key    = "ab12cd34.png" ─┼────▶│ ...                        │
│  prompt        = "flat blue..."  │     │                            │
│  content_type  = "image/png"     │     └────────────────────────────┘
│  created_at    = 2026-04-19 ...  │
└──────────────────────────────────┘
```

### Flow 2 — генерация иконки (`POST /v1/chat/completions` из OpenWebUI)

```mermaid
sequenceDiagram
    participant User
    participant OWU as OpenWebUI
    participant Router as routers/openai.py
    participant Svc as GenerationService
    participant Repo as ContextRepository
    participant Storage as S3Storage
    participant LLM as LLMClient
    participant T2I as T2IClient

    User->>OWU: "иконка настроек"
    OWU->>Router: POST /v1/chat/completions<br/>{messages, model: icon-gen}
    Router->>Svc: generate(prompt)
    Svc->>Repo: random(10)
    Repo-->>Svc: 10 × StyleContext
    loop для каждого семпла
        Svc->>Storage: get(object_key)
        Storage-->>Svc: bytes
    end
    Svc->>LLM: describe_style(prompt, samples)
    LLM-->>Svc: "минимализм, flat, синий градиент..."
    Svc->>T2I: generate(prompt, style)
    T2I-->>Svc: PNG bytes
    Svc-->>Router: { prompt, style, image_base64 }
    Router->>Router: оборачиваем в<br/>![icon](data:image/png;base64,...)
    Router-->>OWU: OpenAI chat completion
    OWU-->>User: картинка в чате
```

### Слои и зависимости в коде

```mermaid
flowchart TB
    subgraph HTTP ["HTTP слой"]
        R1[routers/context.py]
        R2[routers/generate.py]
        R3[routers/openai.py]
    end

    subgraph Business ["Бизнес-логика"]
        S[services/generation.py<br/>GenerationService]
    end

    subgraph Data ["Доступ к данным"]
        Repo[repositories/context.py<br/>ContextRepository]
    end

    subgraph Clients ["Внешние клиенты<br/>Protocol + реализация"]
        Proto[clients/base.py<br/>Protocols]
        ST[clients/storage.py<br/>S3Storage]
        LL[clients/llm.py<br/>StubLLMClient]
        TT[clients/t2i.py<br/>StubT2IClient]
    end

    subgraph Infra ["Инфраструктура"]
        DB[(PostgreSQL)]
        S3[(MinIO)]
        Future1[[будущее:<br/>OllamaLLMClient]]
        Future2[[будущее:<br/>ComfyUIT2IClient]]
    end

    R1 --> Repo
    R1 --> ST
    R2 --> S
    R3 --> S
    S --> Repo
    S --> ST
    S --> LL
    S --> TT
    Repo --> DB
    ST --> S3
    LL -.реализует.-> Proto
    TT -.реализует.-> Proto
    ST -.реализует.-> Proto
    Future1 -.реализует.-> Proto
    Future2 -.реализует.-> Proto

    style Proto fill:#fff4b0,stroke:#b08800
    style Future1 fill:#e8f5e9,stroke:#2e7d32,stroke-dasharray: 5 5
    style Future2 fill:#e8f5e9,stroke:#2e7d32,stroke-dasharray: 5 5
```

**Ключевой инвариант:** `GenerationService` зависит только от Protocol'ов,
не от конкретных классов. Замена стабов на реальные модели — это одна
строка в `deps.py`, всё остальное не меняется.

---

## API

### Хранилище референсов

| Метод | Путь | Тело | Описание |
|---|---|---|---|
| `POST` | `/v1/context` | `multipart: prompt, file` | Загрузить картинку-референс |
| `GET` | `/v1/context` | — | Список всех референсов |
| `DELETE` | `/v1/context/{id}` | — | Удалить референс (из БД и S3) |

### Генерация

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/v1/generate` | Внутренний эндпоинт для отладки: `{prompt, n?}` → `{image_base64, style, ...}` |
| `GET` | `/v1/models` | OpenAI-совместимый, для OpenWebUI |
| `POST` | `/v1/chat/completions` | OpenAI-совместимый, для OpenWebUI |

### Подключение к OpenWebUI

`Settings → Connections → OpenAI API`:

- URL: `http://backend:8000/v1` (если OpenWebUI в том же `docker-compose.yml`)
  или `http://host.docker.internal:8000/v1` (если OpenWebUI в отдельном контейнере на том же хосте)
- API Key: любая непустая строка (авторизация пока не проверяется)
- В списке моделей появится `icon-gen`

---

## Структура проекта

```
icon-gen/
├── docker-compose.yml           # postgres + minio + backend
├── .env.example                 # шаблон конфига
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py              # FastAPI, lifespan, подключение роутеров
        ├── config.py            # Settings через env
        ├── database.py          # SQLAlchemy engine/session
        ├── models.py            # ORM (таблица style_context)
        ├── schemas.py           # Pydantic для API
        ├── deps.py              # DI — точка замены реализаций клиентов
        ├── clients/
        │   ├── base.py          # Protocols: StorageClient / LLMClient / T2IClient
        │   ├── storage.py       # S3Storage (MinIO / AWS S3)
        │   ├── llm.py           # StubLLMClient
        │   └── t2i.py           # StubT2IClient
        ├── repositories/
        │   └── context.py       # CRUD + random(n)
        ├── services/
        │   └── generation.py    # Оркестрация: repo → storage → llm → t2i
        └── routers/
            ├── context.py       # CRUD референсов
            ├── generate.py      # Внутренний /v1/generate
            └── openai.py        # OpenAI-совместимые эндпоинты для OpenWebUI
```

---

## Как расширять

**Подключить реальный LLM:**
1. Создать `backend/app/clients/llm_ollama.py` с классом, реализующим
   метод `describe_style(user_prompt, samples) -> str`.
2. В `backend/app/deps.py` заменить `return StubLLMClient()` на
   `return OllamaLLMClient()` в `get_llm()`.
3. Всё. Ни роутеры, ни сервис, ни БД не трогаются.

Аналогично для T2I (`get_t2i`) и storage (`get_storage` — если захочется
поменять MinIO на AWS S3, достаточно поменять env-переменные; если на
локальную ФС — написать `LocalStorage` с теми же методами).

## Настройки (`.env`)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://icon:icon@postgres:5432/icon` | Строка подключения к Postgres |
| `S3_ENDPOINT` | `http://minio:9000` | Адрес S3 API |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | `minioadmin` / `minioadmin` | Ключи S3 |
| `S3_BUCKET` | `icon-context` | Имя бакета (создаётся автоматически при старте) |
| `CONTEXT_SAMPLE_SIZE` | `10` | Сколько референсов отдавать в LLM на один запрос |
| `LLM_PROVIDER` / `T2I_PROVIDER` | `stub` | Задел для выбора реализации через env (пока не используется) |
