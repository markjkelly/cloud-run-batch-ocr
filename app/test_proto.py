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

print("Testing Name Check:")
try:
    req = documentai.ProcessRequest(
        name=MagicMock(),
        gcs_document=documentai.GcsDocument(gcs_uri="gs://foo/bar", mime_type="application/pdf")
    )
    print("Success")
except Exception as e:
    print("Error in name check:", repr(e))

print("Testing to_json:")
try:
    json_str = documentai.Document.to_json(MagicMock())
    print("Success", json_str)
except Exception as e:
    print("Error in to_json check:", repr(e))

