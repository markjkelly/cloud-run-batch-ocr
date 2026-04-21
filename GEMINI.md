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
- **Commit Messages:** Use Conventional Commits format (e.g., `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- **Pull Requests:** Keep PRs to one logical change. Ensure all tests pass before requesting a review.
- **Logging:** Use structured logging to emit JSON payloads into Cloud Logging (`INFO`, `WARNING`, `ERROR`).
