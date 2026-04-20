# icon-gen

Генератор иконок. Пользователь пишет промпт в OpenWebUI, бэкенд берёт
N случайных референсов из хранилища, склеивает их заранее посчитанные
style-описания и отправляет стиль + пользовательский промпт в Text-to-Image
модель. Результат возвращается в OpenWebUI картинкой в чат.

**Ключевое решение:** vision-LLM (LLaVA через Ollama) анализирует
**каждый референс один раз при загрузке** и сохраняет описание стиля в БД.
На запрос генерации никакого LLM не дёргается — берём готовые описания.
Это делает сам момент генерации быстрым и снимает зависимость T2I от
доступности Ollama.

## Стек

- **FastAPI** — API слой (порт 8000)
- **PostgreSQL** — метаданные (`object_key`, `prompt`, `style_description`)
- **MinIO** — S3-совместимое хранилище для бинарников картинок
- **icon-style** — микросервис Темыча (FastAPI + Ollama + LLaVA:13b), анализ стиля (порт 8001)
- **SQLAlchemy** — ORM
- **Docker Compose** — оркестрация всех сервисов

T2I сейчас стаб (`StubT2IClient`) — при подключении реальной модели
добавляется новая реализация в `backend/app/clients/` и меняется фабрика
в `backend/app/deps.py`. Остальной код не трогается.

## Запуск

### Предварительно — Ollama на хосте

LLaVA работает через Ollama, которая запускается на хосте (не в docker, чтобы не тянуть в образ 8+ ГБ модели и видеокарту).

```bash
# 1. Поставить Ollama с https://ollama.com/download
# 2. Запустить сервер
ollama serve &
# 3. Скачать модель (один раз, ~8 ГБ)
ollama pull llava:13b
```

### Запуск проекта

```bash
cp .env.example .env
docker compose up --build
```

- Backend API: http://localhost:8000 (Swagger UI на `/docs`)
- icon-style API: http://localhost:8001 (Swagger UI на `/docs`)
- MinIO консоль: http://localhost:9001 (`minioadmin` / `minioadmin`)
- Postgres: `localhost:5432` (`icon` / `icon`)

Проверить что icon-style видит Ollama:
```bash
curl http://localhost:8001/health
# {"status":"ok","ollama_available":true,...}
```

---

## Архитектура

### Общая схема сервисов

```mermaid
flowchart LR
    User([Пользователь])
    OWU[OpenWebUI<br/>Андрюха]
    BE[Backend<br/>FastAPI]
    IS[icon-style<br/>Темыч]
    OL[Ollama<br/>LLaVA:13b]
    T2I[Text-to-Image<br/>Тимур]
    PG[(PostgreSQL<br/>метаданные + style)]
    S3[(MinIO / S3<br/>бинарники)]

    User -->|текст| OWU
    OWU <-->|OpenAI-compatible| BE
    BE -->|при загрузке<br/>картинка| IS
    IS <-->|vision prompt| OL
    IS -->|style_prompt| BE
    BE <-->|промпт + style| T2I
    BE <-->|CRUD + style_description| PG
    BE <-->|put/get/delete<br/>по object_key| S3

    style BE fill:#d1e7ff,stroke:#0066cc
    style PG fill:#e7d9ff,stroke:#6b2fc0
    style S3 fill:#ffe4cc,stroke:#cc6600
    style IS fill:#fff4b0,stroke:#b08800
```

Бэкенд — центральный хаб. Связь с icon-style идёт **только на аплоаде**
референса: анализ стиля выполняется один раз и сохраняется в Postgres.
При генерации иконки vision-LLM не дёргается. Все внешние сервисы за
Protocol-интерфейсами, реальные реализации подключаются без переписывания
бизнес-логики.

### Flow 1 — загрузка референса (`POST /v1/context`)

Администратор/куратор заливает в хранилище картинку с текстовым описанием —
это "контекст стиля", которым потом будет кормиться T2I. На этом же шаге
бэкенд просит icon-style описать визуальный стиль картинки, и описание
кладётся рядом в БД.

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

    Admin->>Router: POST /v1/context с prompt и file
    Router->>Router: генерирует object_key = uuid.ext
    Router->>Storage: put key + bytes
    Storage->>MinIO: PutObject
    Router->>Analyzer: analyze image_bytes
    Analyzer->>IS: POST /analyze
    IS-->>Analyzer: style_prompt или ошибка
    Analyzer-->>Router: string или None
    Router->>Repo: add object_key + prompt + style_description
    Repo->>PG: INSERT INTO style_context
    PG-->>Repo: id + created_at
    Repo-->>Router: StyleContext
    Router-->>Admin: 201 Created
```

Если icon-style недоступен — запись всё равно создаётся со `style_description = null`.
Запустить повторный анализ можно через `POST /v1/context/{id}/reanalyze`.

Метаданные и бинарник живут раздельно, но связаны через `object_key`:

```
PostgreSQL                                   MinIO bucket "icon-context"
┌───────────────────────────────────────┐     ┌────────────────────────────┐
│ style_context                         │     │ ab12cd34.png   [binary]    │
│  id                = "..."            │     │ ef56gh78.jpg   [binary]    │
│  object_key        = "ab12cd34.png"  ─┼────▶│ ...                        │
│  prompt            = "синяя иконка"   │     │                            │
│  style_description = "flat vector     │     └────────────────────────────┘
│                       icon, bold      │
│                       outlines, ..."  │
│  content_type      = "image/png"      │
│  created_at        = 2026-04-19 ...   │
└───────────────────────────────────────┘
```

### Flow 2 — генерация иконки (`POST /v1/chat/completions` из OpenWebUI)

```mermaid
sequenceDiagram
    participant User
    participant OWU as OpenWebUI
    participant Router as routers/openai.py
    participant Svc as GenerationService
    participant Repo as ContextRepository
    participant T2I as T2IClient

    User->>OWU: текстовый промпт
    OWU->>Router: POST /v1/chat/completions
    Router->>Svc: generate prompt
    Svc->>Repo: random N
    Repo-->>Svc: N × StyleContext со style_description
    Svc->>Svc: агрегирует описания в одну style-строку
    Svc->>T2I: generate prompt + style
    T2I-->>Svc: PNG bytes
    Svc-->>Router: prompt + style + image_base64
    Router->>Router: оборачивает картинку в markdown data-URI
    Router-->>OWU: OpenAI chat completion
    OWU-->>User: картинка в чате
```

На этом шаге ни vision-LLM, ни S3 не дёргаются — всё нужное уже лежит
в Postgres. Только если style_description у всех семплов будут null,
style-строка окажется пустой, и T2I получит голый пользовательский промпт.

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
        AN[clients/analyzer.py<br/>OllamaStyleAnalyzerClient]
        TT[clients/t2i.py<br/>StubT2IClient]
    end

    subgraph Infra ["Инфраструктура"]
        DB[(PostgreSQL)]
        S3[(MinIO)]
        IS[icon-style + Ollama]
        Future1[[будущее:<br/>ComfyUIT2IClient]]
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
    AN -.реализует.-> Proto
    TT -.реализует.-> Proto
    ST -.реализует.-> Proto
    Future1 -.реализует.-> Proto

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
| `POST` | `/v1/context` | `multipart: prompt, file` | Загрузить картинку-референс (синхронно вызовет анализ стиля, ~15–30 сек на LLaVA:13b) |
| `GET` | `/v1/context` | — | Список всех референсов |
| `DELETE` | `/v1/context/{id}` | — | Удалить референс (из БД и S3) |
| `POST` | `/v1/context/{id}/reanalyze` | — | Переанализировать стиль — если при загрузке Ollama была недоступна |

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
├── docker-compose.yml           # postgres + minio + icon-style + backend
├── .env.example                 # шаблон конфига
├── icon-style/                  # микросервис Темыча (FastAPI + Ollama LLaVA)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py              # FastAPI, lifespan, миграции, роутеры
        ├── config.py            # Settings через env
        ├── database.py          # SQLAlchemy engine/session
        ├── models.py            # ORM (таблица style_context)
        ├── schemas.py           # Pydantic для API
        ├── deps.py              # DI — точка замены реализаций клиентов
        ├── clients/
        │   ├── base.py          # Protocols: StorageClient / StyleAnalyzer / T2IClient
        │   ├── storage.py       # S3Storage (MinIO / AWS S3)
        │   ├── analyzer.py      # OllamaStyleAnalyzerClient → icon-style сервис
        │   └── t2i.py           # StubT2IClient
        ├── repositories/
        │   └── context.py       # CRUD + random(n) + set_style_description
        ├── services/
        │   └── generation.py    # repo → aggregate styles → t2i
        └── routers/
            ├── context.py       # CRUD референсов + /reanalyze
            ├── generate.py      # Внутренний /v1/generate
            └── openai.py        # OpenAI-совместимые эндпоинты для OpenWebUI
```

---

## Как расширять

**Подключить реальный T2I:**
1. Создать `backend/app/clients/t2i_comfy.py` (или любой другой файл) с
   классом, реализующим метод `generate(user_prompt, style) -> tuple[bytes, str]`.
2. В `backend/app/deps.py` заменить `return StubT2IClient()` на
   `return ComfyT2IClient()` в `get_t2i()`.
3. Всё. Ни роутеры, ни сервис, ни БД не трогаются.

**Свой анализатор стиля** (если когда-нибудь захочется мимо Темыча) —
в `clients/analyzer.py` добавить новый класс с методом `analyze(image_bytes,
content_type) -> str | None`, заменить фабрику `get_style_analyzer()`.

**Хранилище** — `S3Storage` можно заменить env-переменными (AWS S3
вместо MinIO). Для локальной ФС — написать `LocalStorage` с теми же
методами `put/get/delete`.

## Настройки (`.env`)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://icon:icon@postgres:5432/icon` | Строка подключения к Postgres |
| `S3_ENDPOINT` | `http://minio:9000` | Адрес S3 API |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | `minioadmin` / `minioadmin` | Ключи S3 |
| `S3_BUCKET` | `icon-context` | Имя бакета (создаётся автоматически при старте) |
| `ICON_STYLE_URL` | `http://icon-style:8000` | Адрес сервиса анализа стиля |
| `ICON_STYLE_TIMEOUT` | `180` | Таймаут запроса к icon-style, секунд (LLaVA:13b бывает медленной) |
| `CONTEXT_SAMPLE_SIZE` | `10` | Сколько референсов брать при генерации |
| `LLM_PROVIDER` / `T2I_PROVIDER` | `stub` | Задел для выбора реализации через env (пока не используется) |
