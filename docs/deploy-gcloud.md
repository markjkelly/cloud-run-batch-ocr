# Deploy via gcloud CLI

This guide deploys the full OCR pipeline using only `gcloud` CLI commands. All resource names and configuration values match the [Terraform deployment](deploy-terraform.md) exactly — the two paths are interchangeable.

**Required tools:** gcloud CLI (v460+), Docker

---

## 1. Set Variables

Export these once — they are referenced throughout every step below.

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"           # Cloud Run and Eventarc region
export DOCAI_LOCATION="us"            # Document AI: "us" or "eu" only
export SEARCH_LOCATION="global"       # Vertex AI Search: "global", "us", or "eu"
export REPO_NAME="repo"
export IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/ocr-processor:latest"
export SA_EMAIL="ocr-processor-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export DATA_STORE_ID="ocr-document-store-v5"
```

> **Location constraints:**
> - `DOCAI_LOCATION`: Document AI only supports `"us"` or `"eu"` as multi-region endpoints. Single regions (e.g. `"us-central1"`) are not valid here.
> - `SEARCH_LOCATION`: Vertex AI Search supports `"global"`, `"us"`, or `"eu"`. The default `"global"` is recommended unless you have data residency requirements.

## 2. Authenticate

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project $PROJECT_ID
```

## 3. Enable All Required APIs

```bash
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  run.googleapis.com \
  storage.googleapis.com \
  pubsub.googleapis.com \
  logging.googleapis.com \
  eventarc.googleapis.com \
  documentai.googleapis.com \
  discoveryengine.googleapis.com \
  aiplatform.googleapis.com \
  --project=$PROJECT_ID
```

## 4. Create Service Account and IAM Bindings

```bash
gcloud iam service-accounts create ocr-processor-sa \
  --display-name="OCR Processor Service Account" \
  --project=$PROJECT_ID

# Grant the five roles the processor needs
for ROLE in \
  roles/documentai.apiUser \
  roles/discoveryengine.editor \
  roles/storage.objectAdmin \
  roles/eventarc.eventReceiver \
  roles/run.invoker; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE"
done

# Grant the GCS service agent permission to publish to Pub/Sub (required for Eventarc)
GCS_SA=$(gcloud storage service-agent --project=$PROJECT_ID)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${GCS_SA}" \
  --role="roles/pubsub.publisher"
```

## 5. Create GCS Buckets

```bash
# Input bucket
gcloud storage buckets create gs://${PROJECT_ID}-ocr-input \
  --project=$PROJECT_ID \
  --location=$REGION \
  --uniform-bucket-level-access

gcloud storage buckets add-iam-policy-binding gs://${PROJECT_ID}-ocr-input \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# Output bucket
gcloud storage buckets create gs://${PROJECT_ID}-ocr-output \
  --project=$PROJECT_ID \
  --location=$REGION \
  --uniform-bucket-level-access

gcloud storage buckets add-iam-policy-binding gs://${PROJECT_ID}-ocr-output \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"
```

## 6. Build and Push the Container Image

```bash
# Create Artifact Registry repository
gcloud artifacts repositories create $REPO_NAME \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID

# Authenticate Docker to push to Artifact Registry
gcloud auth configure-docker ${REGION}-docker.pkg.dev

# Build and push
cd app/
docker build -t $IMAGE_URI .
docker push $IMAGE_URI
cd ..
```

## 7. Create the Document AI Processor

```bash
DOCAI_PROCESSOR_NAME=$(gcloud documentai processors create \
  --display-name="ocr-document-processor" \
  --type=OCR_PROCESSOR \
  --location=$DOCAI_LOCATION \
  --project=$PROJECT_ID \
  --format="value(name)")

echo "Processor resource name: $DOCAI_PROCESSOR_NAME"
```

The captured value is the full resource name (`projects/PROJECT_NUMBER/locations/LOCATION/processors/ID`). It is used verbatim as the `DOCAI_PROCESSOR_ID` environment variable in the next step.

## 8. Create the Vertex AI Search Data Store

The gcloud CLI for Discovery Engine is in alpha with limited coverage; use the REST API directly:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://discoveryengine.googleapis.com/v1beta/projects/${PROJECT_ID}/locations/${SEARCH_LOCATION}/collections/default_collection/dataStores?dataStoreId=${DATA_STORE_ID}" \
  -d '{
    "displayName": "OCR Document Store",
    "industryVertical": "GENERIC",
    "solutionTypes": ["SOLUTION_TYPE_SEARCH"],
    "contentConfig": "CONTENT_REQUIRED"
  }'
```

Wait for the data store to be ready (typically 1–2 minutes) before deploying Cloud Run, then confirm:

```bash
curl -s \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://discoveryengine.googleapis.com/v1beta/projects/${PROJECT_ID}/locations/${SEARCH_LOCATION}/collections/default_collection/dataStores/${DATA_STORE_ID}" \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d.get('name', 'not ready yet'))"
```

## 9. Deploy the Cloud Run Service

```bash
gcloud run deploy ocr-processor-service \
  --image=$IMAGE_URI \
  --region=$REGION \
  --project=$PROJECT_ID \
  --service-account=$SA_EMAIL \
  --max-instances=20 \
  --concurrency=1 \
  --timeout=3600 \
  --no-allow-unauthenticated \
  --port=8080 \
  --set-env-vars="\
GCP_PROJECT_ID=${PROJECT_ID},\
DOCAI_LOCATION=${DOCAI_LOCATION},\
DOCAI_PROCESSOR_ID=${DOCAI_PROCESSOR_NAME},\
OCR_OUTPUT_BUCKET=${PROJECT_ID}-ocr-output,\
SEARCH_LOCATION=${SEARCH_LOCATION},\
SEARCH_DATA_STORE_ID=${DATA_STORE_ID}"
```

## 10. Create the Eventarc Trigger

```bash
gcloud eventarc triggers create ocr-processor-trigger \
  --location=$REGION \
  --project=$PROJECT_ID \
  --destination-run-service=ocr-processor-service \
  --destination-run-region=$REGION \
  --event-filters="type=google.cloud.storage.object.v1.finalized" \
  --event-filters="bucket=${PROJECT_ID}-ocr-input" \
  --service-account=$SA_EMAIL
```

Confirm the trigger is active:

```bash
gcloud eventarc triggers describe ocr-processor-trigger \
  --location=$REGION \
  --project=$PROJECT_ID
```

## 11. Test the Pipeline

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

Stream live logs from the Cloud Run service:

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="ocr-processor-service"' \
  --project=$PROJECT_ID \
  --freshness=10m \
  --format="value(timestamp, jsonPayload.message)" \
  --order=asc
```

## 12. Tear Down

Delete resources in reverse dependency order:

```bash
# Eventarc trigger
gcloud eventarc triggers delete ocr-processor-trigger \
  --location=$REGION --project=$PROJECT_ID

# Cloud Run service
gcloud run services delete ocr-processor-service \
  --region=$REGION --project=$PROJECT_ID

# Document AI processor — list first to get the short ID
gcloud documentai processors list \
  --location=$DOCAI_LOCATION --project=$PROJECT_ID

# Then delete using the ID from the NAME column above
gcloud documentai processors delete PROCESSOR_ID \
  --location=$DOCAI_LOCATION --project=$PROJECT_ID

# Vertex AI Search data store
curl -s -X DELETE \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://discoveryengine.googleapis.com/v1beta/projects/${PROJECT_ID}/locations/${SEARCH_LOCATION}/collections/default_collection/dataStores/${DATA_STORE_ID}"

# GCS buckets (empty first to avoid deletion failure)
gsutil -m rm -r "gs://${PROJECT_ID}-ocr-input/**" || true
gsutil -m rm -r "gs://${PROJECT_ID}-ocr-output/**" || true
gcloud storage buckets delete gs://${PROJECT_ID}-ocr-input --project=$PROJECT_ID
gcloud storage buckets delete gs://${PROJECT_ID}-ocr-output --project=$PROJECT_ID

# Service account
gcloud iam service-accounts delete $SA_EMAIL --project=$PROJECT_ID

# Artifact Registry repository and images
gcloud artifacts repositories delete $REPO_NAME \
  --location=$REGION --project=$PROJECT_ID
```
