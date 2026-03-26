# Runbook

Operations reference for the OCR pipeline.

## Service Overview

| Component | Name | Purpose |
|-----------|------|---------|
| Cloud Run service | `ocr-processor-service` | Processes individual PDF documents |
| GCS input bucket | `{PROJECT_ID}-ocr-input` | Trigger source; PDFs uploaded here |
| GCS output bucket | `{PROJECT_ID}-ocr-output` | OCR JSON results written here |
| Eventarc trigger | `ocr-processor-trigger` | Routes GCS `object.finalized` events to Cloud Run |
| Document AI processor | `ocr-document-processor` | OCR_PROCESSOR type |
| Vertex AI Search data store | `ocr-document-store-v5` | Full-text search index |
| Service account | `ocr-processor-sa` | Identity used by Cloud Run |

Set these shell variables before running any commands below:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"
export DOCAI_LOCATION="us"
export SEARCH_LOCATION="global"
```

---

## Health Checks

### Cloud Run service status

```bash
gcloud run services describe ocr-processor-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --format="table(status.conditions[0].type, status.conditions[0].status, status.conditions[0].message)"
```

`Ready: True` means the latest revision is serving traffic.

### Eventarc trigger status

```bash
gcloud eventarc triggers describe ocr-processor-trigger \
  --location=$REGION \
  --project=$PROJECT_ID \
  --format="table(name, state, transport.pubsub.topic)"
```

### Verify the pipeline end-to-end

```bash
gsutil cp sample.pdf gs://${PROJECT_ID}-ocr-input/smoke-test.pdf

# Poll until ocr_status appears (typically 30–90 seconds)
watch -n 5 "gsutil stat gs://${PROJECT_ID}-ocr-input/smoke-test.pdf 2>&1 | grep ocr_status"
```

Expected result: `ocr_status: SUCCESS`

---

## Monitoring

### Stream live logs

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="ocr-processor-service"' \
  --project=$PROJECT_ID \
  --freshness=30m \
  --format="value(timestamp, jsonPayload.message)" \
  --order=asc
```

### Check for recent errors

```bash
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="ocr-processor-service"
   AND severity>=ERROR' \
  --project=$PROJECT_ID \
  --freshness=1h \
  --format="value(timestamp, jsonPayload.message)"
```

### Processing status values

Each processed object has an `ocr_status` metadata key on the GCS input object:

| Value | Meaning |
|-------|---------|
| `SUCCESS` | OCR and Vertex AI Search indexing both completed |
| `OCR_SUCCESS_INDEX_FAILED` | OCR completed; JSON is in output bucket but Vertex AI Search import failed |
| `FAILED` | Document AI processing failed; `ocr_error` metadata contains the error message |

Check status for a specific file:

```bash
gsutil stat gs://${PROJECT_ID}-ocr-input/FILENAME.pdf
```

---

## Common Issues

### Documents not being processed

**Symptom:** Files uploaded to the input bucket produce no logs and no `ocr_status` metadata.

**Check the Eventarc trigger:**

```bash
gcloud eventarc triggers describe ocr-processor-trigger \
  --location=$REGION \
  --project=$PROJECT_ID
```

Ensure `state: ACTIVE`. If not, check that the GCS service agent has `roles/pubsub.publisher`:

```bash
GCS_SA=$(gcloud storage service-agent --project=$PROJECT_ID)
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:${GCS_SA} AND bindings.role:roles/pubsub.publisher" \
  --format="table(bindings.role)"
```

If the binding is missing, add it:

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${GCS_SA}" \
  --role="roles/pubsub.publisher"
```

### HTTP 429 — Quota Exceeded

**Symptom:** Logs show `429` responses from Document AI or Vertex AI Search.

This is expected behaviour during large batch uploads. Pub/Sub exponential backoff will redeliver the messages automatically — no intervention needed unless 429s persist for more than a few hours.

If sustained, check quota usage in the GCP console:
- Document AI: **APIs & Services → Document AI API → Quotas**
- Vertex AI Search: **APIs & Services → Discovery Engine API → Quotas**

Do not increase `max_instance_count` without first confirming quota headroom in both services.

### `ocr_status: OCR_SUCCESS_INDEX_FAILED`

**Symptom:** OCR JSON is present in the output bucket but the document is not appearing in Vertex AI Search.

**Check the Vertex AI Search data store is active:**

```bash
curl -s \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://discoveryengine.googleapis.com/v1beta/projects/${PROJECT_ID}/locations/${SEARCH_LOCATION}/collections/default_collection/dataStores/ocr-document-store-v5" \
  | python3 -c "import sys, json; d = json.load(sys.stdin); print(d.get('name', 'ERROR'), d.get('state', ''))"
```

**Re-trigger indexing** by re-uploading the original PDF (or copying it to force a new `object.finalized` event):

```bash
gsutil cp gs://${PROJECT_ID}-ocr-input/FILENAME.pdf /tmp/FILENAME.pdf
gsutil cp /tmp/FILENAME.pdf gs://${PROJECT_ID}-ocr-input/FILENAME.pdf
```

### `ocr_status: FAILED`

**Symptom:** Document AI returned an error.

Retrieve the error message:

```bash
gsutil stat gs://${PROJECT_ID}-ocr-input/FILENAME.pdf 2>&1 | grep ocr_error
```

Common causes:
- File is not a valid PDF (encrypted, corrupted, or a non-PDF with a `.pdf` extension)
- Document AI processor was deleted or disabled — check the processor exists:

```bash
gcloud documentai processors list \
  --location=$DOCAI_LOCATION \
  --project=$PROJECT_ID
```

---

## Rollback

Cloud Run keeps previous revisions. To roll back to the last known good revision:

```bash
# List recent revisions
gcloud run revisions list \
  --service=ocr-processor-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --sort-by=~createTime \
  --limit=5

# Route 100% of traffic to a specific revision
gcloud run services update-traffic ocr-processor-service \
  --region=$REGION \
  --project=$PROJECT_ID \
  --to-revisions=REVISION_NAME=100
```

To revert to the previous image tag, rebuild and push that tag, then deploy:

```bash
docker build -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/repo/ocr-processor:PREVIOUS_TAG ./app/
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/repo/ocr-processor:PREVIOUS_TAG

gcloud run deploy ocr-processor-service \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/repo/ocr-processor:PREVIOUS_TAG \
  --region=$REGION \
  --project=$PROJECT_ID
```

---

## Scaling

The pipeline is intentionally capped at 20 Cloud Run instances with concurrency 1. This is the main throttle protecting Document AI and Vertex AI Search from quota exhaustion.

To change the instance limit:

```bash
gcloud run services update ocr-processor-service \
  --max-instances=NEW_LIMIT \
  --region=$REGION \
  --project=$PROJECT_ID
```

**Before increasing:** verify available quota for both Document AI (`pages_per_minute`) and Vertex AI Search (`import_documents_per_minute`) in the GCP console. Setting the limit too high will cause sustained 429 errors and stall the Pub/Sub queue rather than drain it faster.
