# Contributing

## Development Environment

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — Python package manager
- Docker — to build and test the container image locally
- gcloud CLI — optional, for manual end-to-end testing against GCP

### Setup

Install `uv` then sync the project dependencies:

```bash
# Install uv (Linux/macOS)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
cd app/
uv sync
```

## Running Tests

```bash
cd app/
uv run pytest test_main.py
```

Run with coverage:

```bash
cd app/
uv run pytest test_main.py --cov=main --cov-report=term-missing
```

## Building the Container

```bash
cd app/
docker build -t ocr-processor:local .
```

This uses the same multi-stage build as CI. If the image builds locally, it will build in Artifact Registry.

## Code Organisation

`app/main.py` follows a linear stage pipeline:

1. **Download** — fetch the PDF from the GCS input bucket
2. **OCR** — send to Document AI, receive structured JSON
3. **Upload** — write JSON to the GCS output bucket
4. **Index** — import the document into Vertex AI Search
5. **Patch metadata** — write `ocr_status` back to the GCS input object

New functionality should fit into one of these stages. Cross-cutting concerns (client initialisation, logging) live at module level as lazy-loaded singletons.

## Pull Requests

- One logical change per PR
- All tests must pass before requesting review
- PR description should describe what the code does now — not discarded approaches or prior iterations
- Commit messages use [Conventional Commits](https://www.conventionalcommits.org/) format: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
