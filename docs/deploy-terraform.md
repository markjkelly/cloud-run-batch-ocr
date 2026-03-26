# Deploy via Terraform

This guide provisions the full OCR pipeline using Terraform. All infrastructure is managed as code and can be torn down with a single command.

**Required tools:** gcloud CLI (v460+), Terraform ≥ 1.5, Docker

---

## 1. Prerequisites

Install the following tools before starting:

*   [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install) — tested with v460+
*   [Terraform](https://developer.hashicorp.com/terraform/downloads) >= v1.5.0
*   [Docker](https://docs.docker.com/get-docker/) — to build and push the container image

Verify versions:
```bash
gcloud --version
terraform -version
docker --version
```

## 2. Authenticate and Configure gcloud

```bash
# Log in interactively
gcloud auth login

# Set up Application Default Credentials (used by Terraform's Google provider)
gcloud auth application-default login

# Set your project as the default to avoid repeating --project flags
export PROJECT_ID="YOUR_PROJECT_ID"
gcloud config set project $PROJECT_ID
```

## 3. Enable Bootstrap APIs

Terraform enables most APIs automatically, but it needs a few to already be active before it can run — specifically Artifact Registry (to store the image) and the services that underpin the Terraform Google provider itself.

```bash
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  --project=$PROJECT_ID
```

> Terraform's `main.tf` enables `documentai.googleapis.com`, `discoveryengine.googleapis.com`, `aiplatform.googleapis.com`, and `eventarc.googleapis.com` automatically during `apply`. Cloud Run, Cloud Storage, Pub/Sub, and Cloud Logging APIs are enabled by default in all GCP projects.

## 4. Create an Artifact Registry Repository and Push the Image

Set the variables used throughout the build and push steps:

```bash
export REGION="us-central1"       # Must match the 'region' you'll set in terraform.tfvars
export REPO_NAME="repo"           # Must match 'docker_repo_name' in terraform.tfvars
export IMAGE_NAME="ocr-processor"
export IMAGE_TAG="latest"
export IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${IMAGE_TAG}"
```

Create the repository:

```bash
gcloud artifacts repositories create $REPO_NAME \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID
```

Authenticate Docker to push to Artifact Registry:

```bash
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

Build and push the image:

```bash
cd app/

docker build -t $IMAGE_URI .

docker push $IMAGE_URI
```

Verify the image is present:

```bash
gcloud artifacts docker images list ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME} \
  --project=$PROJECT_ID
```

## 5. Deploy Infrastructure via Terraform

```bash
cd ../terraform/
terraform init
```

Create a `terraform.tfvars` file — all values must be concrete strings, no variable references:

```hcl
project_id       = "YOUR_PROJECT_ID"
region           = "us-central1"
docker_repo_name = "repo"

# Optional overrides (defaults shown):
# docai_location             = "us"     # Document AI multi-region: "us" or "eu" only
# discovery_engine_location  = "global" # Vertex AI Search location: "global", "us", or "eu"
```

> **Location constraints:**
> - `docai_location`: Document AI only supports `"us"` or `"eu"` as multi-region endpoints. Single regions (e.g. `"us-central1"`) are not valid here.
> - `discovery_engine_location`: Vertex AI Search supports `"global"`, `"us"`, or `"eu"`. The default `"global"` is recommended unless you have data residency requirements.
> - `region`: The Cloud Run service and Eventarc trigger region. This can be any standard GCP region (e.g. `"us-central1"`, `"europe-west1"`).

Review what Terraform will create before applying:

```bash
terraform plan
```

Apply (Terraform will prompt for confirmation):

```bash
terraform apply
```

This creates:
- Service account `ocr-processor-sa` with Document AI, Vertex AI Search, Storage, Eventarc, and Cloud Run Invoker roles
- GCS input bucket: `YOUR_PROJECT_ID-ocr-input`
- GCS output bucket: `YOUR_PROJECT_ID-ocr-output`
- Document AI OCR processor
- Vertex AI Search data store (`ocr-document-store-v5`)
- Cloud Run service (`ocr-processor-service`, max 20 instances, concurrency 1)
- Eventarc trigger listening for `google.cloud.storage.object.v1.finalized` on the input bucket

## 6. Test the Pipeline

Upload a PDF to the input bucket to trigger the pipeline end-to-end:

```bash
gsutil cp sample.pdf gs://${PROJECT_ID}-ocr-input/
```

Check processing status via the object's metadata (set by the processor):

```bash
gsutil stat gs://${PROJECT_ID}-ocr-input/sample.pdf
```

Look for `ocr_status: SUCCESS` in the metadata output. Possible values:
- `SUCCESS` — OCR and Vertex AI Search indexing both completed
- `OCR_SUCCESS_INDEX_FAILED` — OCR completed but Vertex AI Search import failed; the JSON is in the output bucket
- `FAILED` — Document AI processing failed; `ocr_error` metadata contains the error

Verify the OCR JSON output was written:

```bash
gsutil ls gs://${PROJECT_ID}-ocr-output/
```

## 7. Monitor with Cloud Logging

Stream live logs from the Cloud Run service:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="ocr-processor-service"' \
  --project=$PROJECT_ID \
  --freshness=10m \
  --format="value(timestamp, jsonPayload.message)" \
  --order=asc
```

Or open the Cloud Run console directly:

```bash
gcloud run services describe ocr-processor-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --format="value(status.url)"
```

Eventarc trigger details:

```bash
gcloud eventarc triggers describe ocr-processor-trigger \
  --location=$REGION \
  --project=$PROJECT_ID
```

## 8. Tear Down

To destroy all resources created by Terraform:

```bash
cd terraform/
terraform destroy
```

> The GCS buckets use `force_destroy = false` by default (see `modules/gcs-bucket/variables.tf`). If the buckets contain objects, `terraform destroy` will fail on them. Either empty the buckets first or set `force_destroy = true` in the module calls in `main.tf` before destroying.

```bash
# Empty buckets before destroying if needed
gsutil -m rm -r gs://${PROJECT_ID}-ocr-input/**
gsutil -m rm -r gs://${PROJECT_ID}-ocr-output/**
```

The Artifact Registry repository and its images are not managed by Terraform (you created it manually in step 4). Delete it separately if needed:

```bash
gcloud artifacts repositories delete $REPO_NAME \
  --location=$REGION \
  --project=$PROJECT_ID
```
