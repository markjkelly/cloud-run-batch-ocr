# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Cloud Run Batch OCR Processor

Deployment Path (Cloud Console - Simple Code-Only Deployment):
1. Navigate to Cloud Run in the Google Cloud Console.
2. Select "Deploy Container" -> "Service" and choose "Deploy one revision from source code".
3. Upload this source code bundle.
4. In Advanced Settings -> Variables & Secrets, configure the required Environment Variables:
   - GCP_PROJECT_ID
   - DOCAI_PROCESSOR_ID
   - OCR_OUTPUT_BUCKET
   - SEARCH_DATA_STORE_ID
5. Add an Eventarc Trigger for "Cloud Storage" with event type "google.cloud.storage.object.v1.finalized" pointing to your input bucket.
"""

import os
import json
import logging
import google.cloud.logging
from cloudevents.http import CloudEvent
import functions_framework

from google.cloud import storage
from google.cloud import documentai
from google.cloud import discoveryengine_v1beta as discoveryengine
from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.api_core import retry, exceptions

# 1. Structured Logging
logger = logging.getLogger("ocr_processor")
logger.setLevel(logging.INFO)
_logging_initialized = False


def _setup_logging():
    """Initializes Google Cloud Logging Client lazily."""
    global _logging_initialized
    if not _logging_initialized:
        try:
            logging_client = google.cloud.logging.Client()
            logging_client.setup_logging()
            _logging_initialized = True
        except Exception as e:
            # Fallback to standard logging if client fails
            print(f"Warning: Failed to initialize Cloud Logging client: {e}")

# 2. Global API Clients Lazy Initialization
# This prevents crashes during import if environment variables aren't set yet.
storage_client = None
docai_client = None
discovery_client = None


def get_storage_client() -> storage.Client:
    global storage_client
    if not storage_client:
        storage_client = storage.Client()
    return storage_client


def get_docai_client(location: str) -> documentai.DocumentProcessorServiceClient:
    global docai_client
    if not docai_client:
        docai_client = documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(
                api_endpoint=f"{location}-documentai.googleapis.com"
            )
        )
    return docai_client


def get_discovery_client(location: str) -> discoveryengine.DocumentServiceClient:
    global discovery_client
    if not discovery_client:
        discovery_client = discoveryengine.DocumentServiceClient(
            client_options=ClientOptions(
                api_endpoint=f"{location}-discoveryengine.googleapis.com"
            )
        )
    return discovery_client


def _run_document_ai(
    gcs_uri: str, mime_type: str, project_id: str, location: str, processor_id: str
) -> documentai.Document:
    """Invokes Document AI processor."""
    client = get_docai_client(location)
    resource_name = client.processor_path(project_id, location, processor_id)

    gcs_document = documentai.GcsDocument(
        gcs_uri=gcs_uri,
        mime_type=mime_type,
    )
    request = documentai.ProcessRequest(
        name=resource_name,
        gcs_document=gcs_document,
    )

    try:
        result = client.process_document(request=request)
        return result.document
    except (GoogleAPICallError, RetryError) as e:
        logger.error(f"Document AI transient/API error: {e}")
        raise  # Reraise so Eventarc/PubSub handles the retry via exponential backoff
    except Exception as e:
        logger.error(f"Document AI unexpected error: {e}")
        raise


def _upload_json_to_gcs(
    document: documentai.Document, bucket_name: str, output_filename: str
) -> str:
    """Uploads the Document JSON to the destination bucket."""
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(output_filename)

    output_gcs_uri = f"gs://{bucket_name}/{output_filename}"
    try:
        # Clear the bytestream content before serializing to JSON to reduce file size
        document.content = b""
        
        blob.upload_from_string(
            documentai.Document.to_json(document),
            content_type="application/json",
        )
        logger.info(f"Saved OCR output to {output_gcs_uri}")
        return output_gcs_uri
    except Exception as e:
        logger.error(f"GCS Upload failed for {output_filename}: {e}")
        raise


def _index_in_vertex_search(
    gcs_uri: str, project_id: str, location: str, data_store_id: str
) -> bool:
    """Imports the document to Vertex AI Search without blocking on completion."""
    client = get_discovery_client(location)

    parent_path = (
        f"projects/{project_id}/locations/{location}/"
        f"collections/default_collection/dataStores/{data_store_id}/"
        f"branches/default_branch"
    )

    import_request = discoveryengine.ImportDocumentsRequest(
        parent=parent_path,
        gcs_source=discoveryengine.GcsSource(
            input_uris=[gcs_uri],
            data_schema="content",
        ),
        reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
    )

    @retry.Retry(
        predicate=retry.if_exception_type(exceptions.ResourceExhausted),
        initial=10.0,
        maximum=120.0,
        multiplier=2.0,
        deadline=900.0
    )
    def _execute_import():
        return client.import_documents(request=import_request)

    try:
        operation = _execute_import()
        logger.info(f"Started Vertex AI Search import operation: {operation.operation.name}")
        return True
    except exceptions.ResourceExhausted as e:
        logger.error(f"Vertex AI Search indexing failed due to continuous 429 errors despite retries: {e}")
        return False
    except Exception as e:
        indexing_error = str(e)
        if "409" in indexing_error and "already exists" in indexing_error.lower():
            logger.info(f"Document already exists in Vertex AI Search for {gcs_uri}.")
            return True
        logger.error(f"Vertex AI Search indexing failed: {indexing_error}")
        return False


def _safe_patch_metadata(blob: storage.Blob, metadata: dict, expected_metageneration: int):
    """Updates metadata using optimistic concurrency to avoid race conditions."""
    blob.metadata = metadata
    try:
        blob.patch(if_metageneration_match=expected_metageneration)
    except Exception as e:
        logger.warning(
            f"Failed to patch metadata (expected metageneration {expected_metageneration}). "
            f"Likely modified concurrently: {e}"
        )


@functions_framework.cloud_event
def ocr_document_processor(cloud_event: CloudEvent):
    _setup_logging()

    # Verify environment variables
    required_vars = [
        "GCP_PROJECT_ID",
        "DOCAI_PROCESSOR_ID",
        "OCR_OUTPUT_BUCKET",
        "SEARCH_DATA_STORE_ID",
    ]
    missing = [var for var in required_vars if not os.environ.get(var)]
    if missing:
        msg = f"CRITICAL: Missing required environment variables: {', '.join(missing)}"
        logger.critical(msg)
        return

    gcp_project_id = os.environ["GCP_PROJECT_ID"]
    docai_location = os.environ.get("DOCAI_LOCATION", "us")
    docai_processor_id = os.environ["DOCAI_PROCESSOR_ID"]
    ocr_output_bucket = os.environ["OCR_OUTPUT_BUCKET"]
    search_location = os.environ.get("SEARCH_LOCATION", "us")
    search_data_store_id = os.environ["SEARCH_DATA_STORE_ID"]

    # Read Event Payload
    data = cloud_event.data
    bucket_name = data.get("bucket")
    file_name = data.get("name")
    generation = str(data.get("generation", ""))

    if not bucket_name or not file_name:
        logger.error("Missing bucket or file name in event payload.")
        return

    gcs_uri = f"gs://{bucket_name}/{file_name}"
    logger.info(f"Processing {gcs_uri} (generation: {generation or 'unknown'})")

    storage_client = get_storage_client()
    source_blob = storage_client.bucket(bucket_name).get_blob(file_name)
    if not source_blob:
        logger.warning(f"File not found: {gcs_uri}")
        return

    # 0. Filter for PDFs only
    content_type = source_blob.content_type or ""
    if not (file_name.lower().endswith(".pdf") or content_type == "application/pdf"):
        logger.info(f"Skipping non-PDF file: {file_name} (Type: {content_type})")
        return

    existing_metadata = source_blob.metadata or {}
    metageneration = source_blob.metageneration

    # Idempotency check
    if (
        existing_metadata.get("ocr_status") == "SUCCESS"
        and existing_metadata.get("ocr_generation") == generation
    ):
        logger.info(f"Skipping already processed generation {generation} for {file_name}")
        return

    # 1. Run Document AI
    mime_type = source_blob.content_type or "application/pdf"
    try:
        document = _run_document_ai(
            gcs_uri=gcs_uri,
            mime_type=mime_type,
            project_id=gcp_project_id,
            location=docai_location,
            processor_id=docai_processor_id,
        )
        logger.info("Document AI processing successful.")
    except Exception as e:
        failed_metadata = existing_metadata.copy()
        failed_metadata.update(
            {
                "ocr_status": "FAILED",
                "ocr_generation": generation,
                "ocr_error": str(e)[:1500],
            }
        )
        _safe_patch_metadata(source_blob, failed_metadata, metageneration)

        if isinstance(e, (GoogleAPICallError, RetryError)):
            logger.error(f"Propagating transient error to trigger event retry: {e}")
            raise
        return

    # 2. Upload to GCS
    safe_generation = generation or "unknown"
    output_filename = f"{file_name}.{safe_generation}.json"
    try:
        output_gcs_uri = _upload_json_to_gcs(document, ocr_output_bucket, output_filename)
    except Exception as e:
        logger.error("Propagating GCS upload error to trigger event retry.")
        raise

    # 3. Index in Vertex Search
    indexing_succeeded = _index_in_vertex_search(
        gcs_uri=gcs_uri,
        project_id=gcp_project_id,
        location=search_location,
        data_store_id=search_data_store_id,
    )

    # 4. Final Metadata Update
    updated_metadata = existing_metadata.copy()
    updated_metadata.update(
        {
            "ocr_status": "SUCCESS" if indexing_succeeded else "OCR_SUCCESS_INDEX_FAILED",
            "ocr_generation": generation,
            "ocr_output_path": output_gcs_uri,
        }
    )
    updated_metadata.pop("ocr_error", None)

    _safe_patch_metadata(source_blob, updated_metadata, metageneration)

    if indexing_succeeded:
        logger.info(f"Successfully processed and indexed {file_name}")
    else:
        logger.warning(
            f"OCR succeeded but indexing failed for {file_name}. "
            f"Output saved to {output_gcs_uri}"
        )