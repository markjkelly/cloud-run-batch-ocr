# Project Overview
This repository contains a **Scalable Batch OCR Document Processor**. It uses an event-driven architecture on Google Cloud Platform to ingest unstructured documents (PDFs), extract text via Document AI, and import them into a Vertex AI Search index without exhausting API quotas during large batch uploads.

**Main Technologies:**
- Python 3.12+
- Google Cloud Platform (Cloud Storage, Eventarc, Pub/Sub, Cloud Run, Document AI, Vertex AI Search, Cloud Logging)
- `functions-framework` for handling CloudEvents
- `uv` for Python dependency management
- Docker
- Terraform for Infrastructure-as-Code

**Architecture highlights:**
- Uses **Pub/Sub Push Backpressure** and Cloud Run instance limits (`max_instance_count = 20`, `concurrency = 1`) to automatically reject excess traffic with HTTP 429, allowing Pub/Sub to queue and trickle-deliver backlog.
- Global lazy initialization of GCP API clients to reuse connection pools across Cloud Run invocations.
- Optimistic concurrency control using `if_metageneration_match` to safely update GCS object metadata (`ocr_status`).

# Building and Running

### Setup
The Python application uses `uv` for fast package management.
```bash
# Navigate to the app directory
cd app/

# Install dependencies (requires uv)
uv sync
```

### Testing
Tests are managed via `pytest`.
```bash
cd app/

# Run unit tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=main --cov-report=term-missing

# Run end-to-end live tests (requires GCP_PROJECT_ID and authenticated environment)
uv run pytest ../tests/e2e
```

### Docker
To build the container image locally:
```bash
cd app/
docker build -t ocr-processor:local .
```

### Deployment
Infrastructure is deployed via Terraform (in the `terraform/` directory) or `gcloud` CLI.
- **Terraform:** See `docs/deploy-terraform.md`
- **gcloud CLI:** See `docs/deploy-gcloud.md`

# Development Conventions

- **Application Pipeline:** `app/main.py` follows a linear stage pipeline: Download (fetch PDF from GCS) -> OCR (Document AI) -> Upload (write JSON to GCS) -> Index (Vertex AI Search) -> Patch metadata (write `ocr_status` to GCS object). New functionality should fit into one of these stages.
- **Client Initialization:** Cross-cutting concerns like API client initialization and logging must live at the module level as lazy-loaded singletons to optimize performance and prevent crashes if environment variables are missing during import.
- **Logging:** Use structured logging to emit JSON payloads into Cloud Logging (`INFO`, `WARNING`, `ERROR`).

## Version Control

- **Commit frequently** — after each meaningful change (new feature, bug fix, refactor, config change). Small, focused commits over large monolithic ones.
- **Write verbose commit messages** — first line is a concise summary (imperative mood, under 72 chars), followed by a blank line and a detailed body explaining *what* changed and *why*. Include context that won't be obvious from the diff.
- **Never commit secrets** — `.gitignore` protects `*-sa-key.json` and `.env`. Verify with `git status` before committing.
- **Review before pushing** — use `git diff --staged` to review staged changes before committing.
- **Keep `main` stable** — use feature branches for non-trivial work, merge back to `main` when ready.
- **Tag milestones** — use annotated git tags for significant releases or milestones.

**Always work in a feature branch.** Never commit or push directly to `main`.

```bash
git checkout -b <type>/<short-description>   # e.g. chore/reconcile-apigee-x-528
# ... make changes, commit ...
git push -u origin <branch>
gh pr create
```

This applies to all changes — Terraform, docs, scripts, everything.

## Key Documents

| Document | Purpose |
|----------|---------|
| `docs/archive/` | Historical records and completed plans |
| `docs/PROGRESS.md` | Session-by-session development log (update every session) |

## Progress Journaling

- **Always update docs/PROGRESS.md** at the end of every session with:
  - Date and session number
  - What was accomplished (with specifics — files changed, features added, bugs fixed)
  - Key decisions made and rationale
  - Next steps / open items
