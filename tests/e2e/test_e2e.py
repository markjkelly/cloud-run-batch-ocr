import os
import time
import pytest
from google.cloud import storage

# This test is marked as e2e. Run it explicitly with:
# uv run pytest ../tests/e2e/test_e2e.py
# Or if integrated into pyproject.toml paths: uv run pytest -m e2e

GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
INPUT_BUCKET = os.environ.get("OCR_INPUT_BUCKET", f"{GCP_PROJECT_ID}-ocr-input" if GCP_PROJECT_ID else None)


@pytest.mark.e2e
@pytest.mark.skipif(not GCP_PROJECT_ID, reason="GCP_PROJECT_ID not set")
def test_ocr_pipeline_e2e():
    """Live E2E test for the OCR pipeline."""
    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(INPUT_BUCKET)
    
    blob_name = f"tests/e2e_smoke_test_{int(time.time())}.pdf"
    blob = bucket.blob(blob_name)
    
    # Upload a dummy file (or real PDF if available)
    # Note: If this is not a valid PDF, Document AI might fail, but it will still test the EventArc trigger and Cloud Run execution path.
    content = b"Draft PDF content for E2E testing."
    blob.upload_from_string(content, content_type="application/pdf")
    
    print(f"Uploaded test file to gs://{INPUT_BUCKET}/{blob_name}")
    
    success = False
    error_msg = ""
    
    # Poll for status on the input object
    max_retries = 10
    delay = 10
    
    for i in range(max_retries):
        print(f"Polling status (attempt {i+1}/{max_retries})...")
        time.sleep(delay)
        
        # Reload blob to get fresh metadata
        blob = bucket.get_blob(blob_name)
        if not blob:
            print("Blob not found (unexpected, should be there until we delete it)")
            continue
            
        metadata = blob.metadata or {}
        status = metadata.get("ocr_status")
        
        if status:
            print(f"Found ocr_status: {status}")
            if status == "SUCCESS":
                success = True
                break
            elif status == "FAILED":
                error_msg = metadata.get("ocr_error", "Unknown error")
                print(f"Pipeline failed with: {error_msg}")
                # We break here because it didn't succeed, but it did run!
                # If we expect success (valid PDF), this is a failure.
                # If we just want to prove it ran, we might accept FAILED if the content was invalid.
                break
    
    # Clean up
    print("Cleaning up test file...")
    try:
        blob.delete()
    except Exception as e:
        print(f"Failed to delete test file: {e}")
        
    assert success, f"Pipeline did not complete successfully. Status was not SUCCESS. Error if any: {error_msg}"
