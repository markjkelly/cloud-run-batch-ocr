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

from google.cloud import documentai
from unittest.mock import MagicMock
import traceback

def test_name_check():
    """Verify ProcessRequest creation with valid arguments."""
    req = documentai.ProcessRequest(
        name="projects/test-project/locations/us/processors/test-processor",
        gcs_document=documentai.GcsDocument(gcs_uri="gs://foo/bar", mime_type="application/pdf")
    )
    assert req.gcs_document.gcs_uri == "gs://foo/bar"
    assert req.gcs_document.mime_type == "application/pdf"


def test_to_json():
    """Verify Document.to_json with a real Document."""
    doc = documentai.Document(text="hello world")
    json_str = documentai.Document.to_json(doc)
    assert isinstance(json_str, str)

