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

variable "project_id" {
  description = "The GCP Project ID to deploy the OCR pipeline into"
  type        = string
}

variable "region" {
  description = "The GCP region for the Cloud Run service and Eventarc triggers"
  type        = string
  default     = "us-central1"
}

variable "docai_location" {
  description = "The location for the Document AI Processor (e.g., 'us' or 'eu')"
  type        = string
  default     = "us"
}

variable "discovery_engine_location" {
  description = "The location for Vertex AI Search data store (e.g., 'global', 'us', 'eu')"
  type        = string
  default     = "global"
}

variable "docker_repo_name" {
  description = "Name of the Artifact Registry repository where the OCR Processor image is pushed"
  type        = string
  default     = "repo"
}
