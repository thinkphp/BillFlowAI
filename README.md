# BillFlowAI

A full-stack application that turns PDF invoices into structured, reviewable data. It uses Google Gemini for invoice extraction, Pydantic for deterministic validation, FastAPI for the API, PostgreSQL for persistence, and React with Vite for the user interface.

The application is designed to support human review: fields that are missing, low-confidence, or involved in a validation mismatch are flagged so they can be corrected before the invoice is treated as approved.

## Features

- Upload PDF invoices by choosing a file or dragging it into the upload area.
- Extract supplier, tax ID, invoice number, dates, currency, totals, and line items with Gemini.
- Interpret Romanian and English invoice labels, including Romanian decimal and currency formats.
- Prefer explicitly printed Romanian invoice totals (such as `Total de plată`) over inferred arithmetic totals when selectable PDF text is available; track a carried-forward previous balance separately.
- Process text-based PDFs with PyMuPDF and send scanned PDFs directly to Gemini for multimodal extraction.
- Validate extracted values with Pydantic and deterministic business rules, including separately listed charges or adjustments.
- Review field-level confidence scores, correct extracted values, and save changes.
- Browse, search, and filter saved invoices by review status.
- Persist invoice data in PostgreSQL using a Docker-managed volume.
- Use a responsive English-language interface.

## Processing workflow

1. The API checks that the uploaded file is a PDF and that it is within the configured size limit.
2. PyMuPDF attempts to extract selectable text from the PDF.
3. If text is available, the extracted text is sent to Gemini. If the PDF is scanned and contains no selectable text, the PDF is sent directly to Gemini.
4. Gemini returns structured invoice fields and confidence scores. The response is validated against a Pydantic schema.
5. Deterministic validation flags missing or low-confidence fields, due dates earlier than issue dates, and mismatches between subtotal, tax, additional charges or adjustments, total, and line-item sums.
6. The extraction result and validation state are saved in PostgreSQL. The user can review and edit the fields in the interface.

By default, a field is considered uncertain when it is missing or its confidence score is below `0.75`. Confidence is an AI estimate of how clearly the value appears in the source; it is not a guarantee that the value is correct. A record is marked `validated` only when there are no uncertain fields or validation errors.

## Requirements

### Docker setup

- Docker Engine
- Docker Compose v2
- A Google Gemini API key with access to a model that supports content generation

### Local development without Docker

- Python 3.12
- Node.js 22 and npm
- A PostgreSQL server
- A Google Gemini API key with access to a content-generation model

## Run with Docker Compose

From the project root:

```bash
cd ~/invoice-extractor
cp .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY` to the key created in [Google AI Studio](https://aistudio.google.com/app/apikey). Choose a model that is available for your API key and supports content generation. The default is `gemini-3.8-flash`; if that model is unavailable or experiencing errors, set `GEMINI_MODEL` to another supported model.

Start the application:

```bash
sudo docker compose up --build -d
```

Open the following URLs:

- Frontend: [http://localhost:5174](http://localhost:5174)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- API health check: [http://localhost:8000/api/health](http://localhost:8000/api/health)

The frontend is published on host port `5174` by default to avoid conflicts with Vite's usual port `5173`. The frontend container itself listens on port `5173`.

To follow service logs:

```bash
sudo docker compose logs -f backend frontend db
```

To stop the application while keeping saved invoices:

```bash
sudo docker compose down
```

To start it again:

```bash
sudo docker compose up -d
```

To rebuild after changing application code:

```bash
sudo docker compose up --build -d
```

Docker Compose stores PostgreSQL data in the `postgres_data` named volume. **Do not use `docker compose down -v` unless you intentionally want to delete the database volume and all stored invoices.**

## Configuration

Docker Compose reads these optional settings from the project-root `.env` file:

| Variable | Default | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | Empty | Google Gemini API key. Required to process invoices. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model name available to the API key. |
| `FRONTEND_PORT` | `5174` | Host port used to open the frontend. |
| `FRONTEND_ORIGIN` | `http://localhost:5174` | Allowed browser origin for backend CORS. Set this to the frontend URL if you change its host or port. |

Backend settings also include:

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://invoice:invoice@localhost:5432/invoices` | SQLAlchemy PostgreSQL connection URL. Docker Compose overrides this to connect to its `db` service. |
| `MAX_UPLOAD_SIZE_MB` | `15` | Maximum accepted PDF upload size in megabytes. |
| `MINIMUM_CONFIDENCE` | `0.75` | Minimum confidence score before a field is flagged for review. |

If you already have a `.env` file from an earlier version, update its `GEMINI_MODEL` value if needed. Values set explicitly in `.env` override the defaults in `docker-compose.yml`.

Keep `.env` private. It is excluded from Git by `.gitignore`; never commit or share the API key.

## Local development

Start with a running PostgreSQL instance and a Gemini API key. Set `DATABASE_URL` and `GEMINI_API_KEY` in the project-root `.env` file, or export them in your shell. When using a PostgreSQL instance outside Docker, make sure the host and credentials in `DATABASE_URL` match that instance.

### Backend

```bash
cd ~/invoice-extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

The backend runs at [http://localhost:8000](http://localhost:8000). Its CORS origin defaults to `http://localhost:5173` for local Vite development.

### Frontend

In a separate terminal:

```bash
cd ~/invoice-extractor/frontend
npm ci
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The Vite development server calls the API at `http://localhost:8000` unless `VITE_API_URL` is set.

## API endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Basic API health check. |
| `GET` | `/api/invoices` | List saved invoices, newest first. |
| `POST` | `/api/invoices` | Upload and process a PDF invoice. Accepts multipart form data with a `file` field. |
| `GET` | `/api/invoices/{invoice_id}` | Retrieve one saved invoice. |
| `PATCH` | `/api/invoices/{invoice_id}` | Update invoice fields and rerun deterministic validation. |

Interactive API documentation is available at `/docs` when the backend is running.

## Data and privacy

- The original PDF is processed in memory and is **not stored** in PostgreSQL or on the application filesystem.
- The filename, extracted fields, confidence scores, uncertain field names, validation messages, invoice status, and timestamps are stored in PostgreSQL.
- The PDF content is sent to Google Gemini for extraction. Review Google's terms and data-handling policies before processing sensitive documents.
- Docker Compose includes PostgreSQL development credentials in `docker-compose.yml`. Change these credentials before exposing the database or application beyond a trusted local development environment.
- This project does not currently implement user authentication or authorization. Do not expose it publicly without adding appropriate access controls and production security configuration.

## Tests and production build

Run backend tests:

```bash
cd ~/invoice-extractor/backend
../.venv/bin/python -m unittest discover -s tests -v
```

Build the frontend:

```bash
cd ~/invoice-extractor/frontend
npm ci
npm run build
```

## Project structure

```text
backend/
  app/
    main.py                 FastAPI routes and application lifecycle
    schemas.py              Pydantic extraction, update, and response schemas
    models.py               SQLAlchemy invoice model
    database.py             PostgreSQL engine and session setup
    services/
      extractor.py          Gemini extraction and transient retries
      validation.py         Deterministic invoice validation
  tests/                    Backend unit tests
frontend/
  src/
    App.tsx                 Invoice dashboard and review interface
    styles.css              Responsive UI styling
docker-compose.yml          PostgreSQL, backend, and frontend services
.env.example                Environment variable template
```
