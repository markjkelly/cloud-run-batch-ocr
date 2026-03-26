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

variable "name" {
  description = "The name of the Cloud Run service"
  type        = string
}

variable "project_id" {
  description = "The project ID to deploy to"
  type        = string
}

variable "location" {
  description = "The location to deploy to"
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "The container image to deploy"
  type        = string
}

variable "container_port" {
  description = "The port the container listens on"
  type        = number
  default     = 8080
}

variable "env_vars" {
  description = "Environment variables"
  type        = map(string)
  default     = {}
}

variable "allow_unauthenticated" {
  description = "Allow unauthenticated invocations"
  type        = bool
  default     = true
}

variable "service_account_email" {
  description = "The service account email for the Cloud Run instance"
  type        = string
  default     = null
}

variable "max_instance_count" {
  description = "Max instances for Cloud Run"
  type        = number
  default     = 100
}

variable "concurrency" {
  description = "Max concurrent requests per instance"
  type        = number
  default     = 80
}

variable "timeout" {
  description = "Max duration the instance is allowed for responding to a request"
  type        = string
  default     = "300s"
}
