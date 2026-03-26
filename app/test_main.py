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

import os
import pytest
from unittest.mock import MagicMock, patch
from cloudevents.http import CloudEvent
from google.api_core.exceptions import GoogleAPICallError

import main

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("DOCAI_LOCATION", "us")
    monkeypatch.setenv("DOCAI_PROCESSOR_ID", "test-processor")
    monkeypatch.setenv("OCR_OUTPUT_BUCKET", "test-output-bucket")
    monkeypatch.setenv("SEARCH_LOCATION", "global")
    monkeypatch.setenv("SEARCH_DATA_STORE_ID", "test-datastore")

@pytest.fixture
def sample_cloud_event():
    attributes = {
        "type": "google.cloud.storage.object.v1.finalized",
        "source": "//storage.googleapis.com/test-bucket",
    }
    data = {
        "bucket": "test-bucket",
        "name": "test-doc.pdf",
        "generation": "12345",
    }
    return CloudEvent(attributes, data)

def test_missing_env_vars(monkeypatch, sample_cloud_event, caplog):
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    main.ocr_document_processor(sample_cloud_event)
    assert "CRITICAL: Missing required environment variables: GCP_PROJECT_ID" in caplog.text

@patch("main.documentai.Document.to_json")
@patch("main.get_storage_client")
@patch("main.get_docai_client")
@patch("main.get_discovery_client")
def test_successful_processing(_mock_discovery, _mock_docai, _mock_storage, _mock_to_json, mock_env, sample_cloud_event):
    # Setup mocks
    mock_blob = MagicMock()
    mock_blob.metadata = {}
    mock_blob.metageneration = 1
    mock_blob.content_type = "application/pdf"
    
    # Mock Storage
    storage_instance = MagicMock()
    _mock_storage.return_value = storage_instance
    storage_instance.bucket.return_value.get_blob.return_value = mock_blob
    
    # Mock DocAI
    docai_instance = MagicMock()
    _mock_docai.return_value = docai_instance
    docai_instance.processor_path.return_value = "projects/test/locations/us/processors/test-processor"
    mock_result = MagicMock()
    mock_result.document = MagicMock()
    _mock_to_json.return_value = '{"text": "mocked"}'
    docai_instance.process_document.return_value = mock_result
    
    # Mock Discovery Engine
    discovery_instance = MagicMock()
    _mock_discovery.return_value = discovery_instance
    mock_operation = MagicMock()
    mock_operation.operation.name = "test-operation"
    discovery_instance.import_documents.return_value = mock_operation
    
    # Execute the handler with a mocked payload (CloudEvent)
    main.ocr_document_processor(sample_cloud_event)
    
    # Assert Input GCS checked properly
    storage_instance.bucket.assert_any_call("test-bucket")
    storage_instance.bucket.return_value.get_blob.assert_called_with("test-doc.pdf")
    
    # Assert DocAI successfully triggered
    docai_instance.process_document.assert_called_once()
    
    # Assert Output was sent to GCS
    storage_instance.bucket.assert_any_call("test-output-bucket")
    target_blob = storage_instance.bucket.return_value.blob.return_value
    target_blob.upload_from_string.assert_called_once()
    
    # Assert Vertex AI index was triggred
    discovery_instance.import_documents.assert_called_once()
    
    # Assert blob metdata was safely patched using proper generation matching
    mock_blob.patch.assert_called_once_with(if_metageneration_match=1)
    patched_metadata = mock_blob.metadata
    assert patched_metadata["ocr_status"] == "SUCCESS"
    assert patched_metadata["ocr_generation"] == "12345"

@patch("main.get_storage_client")
def test_already_processed_skips(_mock_storage, mock_env, sample_cloud_event, caplog):
    mock_blob = MagicMock()
    mock_blob.metadata = {
        "ocr_status": "SUCCESS",
        "ocr_generation": "12345"
    }
    
    storage_instance = MagicMock()
    _mock_storage.return_value = storage_instance
    storage_instance.bucket.return_value.get_blob.return_value = mock_blob
    
    main.ocr_document_processor(sample_cloud_event)
    
    assert "Skipping already processed generation 12345" in caplog.text

@patch("main.get_storage_client")
@patch("main.get_docai_client")
def test_docai_failure_reraises_and_updates_status(_mock_docai, _mock_storage, mock_env, sample_cloud_event):
    mock_blob = MagicMock()
    mock_blob.metadata = {}
    mock_blob.metageneration = 1
    mock_blob.content_type = "application/pdf"
    
    storage_instance = MagicMock()
    _mock_storage.return_value = storage_instance
    storage_instance.bucket.return_value.get_blob.return_value = mock_blob
    
    docai_instance = MagicMock()
    _mock_docai.return_value = docai_instance
    docai_instance.processor_path.return_value = "projects/test/locations/us/processors/test-processor"
    docai_instance.process_document.side_effect = GoogleAPICallError("Test API Transient Disconnection")
    
    # Should catch GoogleAPICallError and reraise to trigger PubSub exponential backoff
    with pytest.raises(GoogleAPICallError):
        main.ocr_document_processor(sample_cloud_event)
        
    assert mock_blob.metadata["ocr_status"] == "FAILED"
    mock_blob.patch.assert_called_once_with(if_metageneration_match=1)
