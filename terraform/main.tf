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

# Service Account for OCR Processor
resource "google_service_account" "ocr_processor_sa" {
  account_id   = "ocr-processor-sa"
  display_name = "OCR Processor Service Account"
  project      = var.project_id
}

# Enable required APIs
locals {
  services = [
    "documentai.googleapis.com",
    "discoveryengine.googleapis.com",
    "aiplatform.googleapis.com",
    "eventarc.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# IAM Role bindings for the SA
resource "google_project_iam_member" "docai_user" {
  project = var.project_id
  role    = "roles/documentai.apiUser"
  member  = "serviceAccount:${google_service_account.ocr_processor_sa.email}"
}

resource "google_project_iam_member" "discoveryengine_editor" {
  project = var.project_id
  role    = "roles/discoveryengine.editor"
  member  = "serviceAccount:${google_service_account.ocr_processor_sa.email}"
}

resource "google_project_iam_member" "storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.ocr_processor_sa.email}"
}

resource "google_project_iam_member" "eventarc_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.ocr_processor_sa.email}"
}

resource "google_project_iam_member" "run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.ocr_processor_sa.email}"
}

# Provide pubsub publisher role so GCS can publish to pubsub for eventarc
data "google_storage_project_service_account" "gcs_account" {
  project    = var.project_id
  depends_on = [google_project_service.apis]
}

resource "google_project_iam_member" "gcs_pubsub_publishing" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}

# Input Storage Bucket
module "ocr_input_bucket" {
  source                      = "./modules/gcs-bucket"
  project_id                  = var.project_id
  name                        = "${var.project_id}-ocr-input"
  location                    = var.region
  uniform_bucket_level_access = true

  iam_members = [
    { role = "roles/storage.objectAdmin", member = "serviceAccount:${google_service_account.ocr_processor_sa.email}" }
  ]
}

# Output Storage Bucket
module "ocr_output_bucket" {
  source                      = "./modules/gcs-bucket"
  project_id                  = var.project_id
  name                        = "${var.project_id}-ocr-output"
  location                    = var.region
  uniform_bucket_level_access = true

  iam_members = [
    { role = "roles/storage.objectAdmin", member = "serviceAccount:${google_service_account.ocr_processor_sa.email}" }
  ]
}

# Document AI Processor
resource "google_document_ai_processor" "ocr_processor" {
  project      = var.project_id
  location     = var.docai_location
  display_name = "ocr-document-processor"
  type         = "OCR_PROCESSOR"

  depends_on = [google_project_service.apis]
}

# Vertex AI Search Data Store
resource "google_discovery_engine_data_store" "ocr_datastore" {
  project           = var.project_id
  location          = var.discovery_engine_location
  data_store_id     = "ocr-document-store-v5"
  display_name      = "OCR Document Store"
  industry_vertical = "GENERIC"
  content_config    = "CONTENT_REQUIRED"
  solution_types    = ["SOLUTION_TYPE_SEARCH"]

  depends_on = [google_project_service.apis]

  lifecycle {
    ignore_changes = [
      document_processing_config
    ]
  }
}

# Cloud Run Service (using module)
module "ocr_cloud_run_service" {
  source                = "./modules/cloud-run"
  name                  = "ocr-processor-service"
  project_id            = var.project_id
  location              = var.region
  image                 = "${var.region}-docker.pkg.dev/${var.project_id}/${var.docker_repo_name}/ocr-processor:latest"
  service_account_email = google_service_account.ocr_processor_sa.email
  allow_unauthenticated = false

  max_instance_count = 20
  concurrency        = 1
  timeout            = "3600s"

  env_vars = {
    GCP_PROJECT_ID       = var.project_id
    DOCAI_LOCATION       = var.docai_location
    DOCAI_PROCESSOR_ID   = google_document_ai_processor.ocr_processor.name
    OCR_OUTPUT_BUCKET    = module.ocr_output_bucket.name
    SEARCH_LOCATION      = var.discovery_engine_location
    SEARCH_DATA_STORE_ID = google_discovery_engine_data_store.ocr_datastore.data_store_id
  }
}

# Eventarc Trigger
resource "google_eventarc_trigger" "ocr_trigger" {
  name     = "ocr-processor-trigger"
  location = var.region
  project  = var.project_id

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }
  matching_criteria {
    attribute = "bucket"
    value     = module.ocr_input_bucket.name
  }

  destination {
    cloud_run_service {
      service = module.ocr_cloud_run_service.name
      region  = var.region
    }
  }

  service_account = google_service_account.ocr_processor_sa.email

  depends_on = [google_project_service.apis]
}
