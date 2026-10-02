terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "environment" {
  description = "Entorno que se está preparando: local o aws."
  type        = string
  default     = "local"

  validation {
    condition     = contains(["local", "aws"], var.environment)
    error_message = "environment debe ser local o aws."
  }
}

variable "aws_region" {
  description = "Región AWS para el entorno serverless."
  type        = string
  default     = "eu-west-1"
}

variable "project_name" {
  description = "Prefijo estable de los recursos AWS."
  type        = string
  default     = "smart-magatzem"
}

variable "lambda_package_path" {
  description = "ZIP del runtime Lambda preparado por scripts/build-aws-lambda.sh."
  type        = string
  default     = ""
}

variable "enable_aws_runtime" {
  description = "Crea Lambda, API Gateway y Step Functions cuando el paquete está preparado."
  type        = bool
  default     = false

  validation {
    condition     = !var.enable_aws_runtime || (var.environment == "aws" && var.lambda_package_path != "")
    error_message = "enable_aws_runtime requiere environment=aws y lambda_package_path apuntando a un ZIP válido."
  }
}

variable "frontend_bucket_name" {
  description = "Nombre opcional del bucket privado que sirve la web Expo exportada."
  type        = string
  default     = ""
}

variable "cognito_domain_prefix" {
  description = "Prefijo opcional para el dominio gestionado de Cognito."
  type        = string
  default     = ""
}

variable "ses_identity_arn" {
  description = "Identidad SES verificada opcional para el correo saliente."
  type        = string
  default     = ""
}

variable "ses_from_email" {
  description = "Correo remitente SES verificado; vacío mantiene el envío desactivado."
  type        = string
  default     = ""
}

variable "email_recipient_override" {
  description = "Destinatario efectivo de pruebas; vacío usa el correo del cliente."
  type        = string
  default     = ""
}

variable "bedrock_model_id" {
  description = "Modelo Bedrock multimodal autorizado para la lectura documental."
  type        = string
  default     = ""
}

variable "default_tenant_id" {
  description = "Tenant inicial del demo; en producción se resuelve por el mapping USER#sub."
  type        = string
  default     = "TEN-DEMO"
}

variable "document_connector" {
  description = "Conector local que recibe el documento canónico durante las pruebas."
  type        = string
  default     = "mock_erp"

  validation {
    condition     = contains(["mock_erp", "file"], var.document_connector)
    error_message = "El conector local debe ser mock_erp o file."
  }
}

variable "auth_provider" {
  description = "Proveedor de identidad: local o cognito."
  type        = string
  default     = "local"

  validation {
    condition     = contains(["local", "cognito"], var.auth_provider)
    error_message = "auth_provider debe ser local o cognito."
  }
}

variable "document_ai_provider" {
  description = "Proveedor explícito de lectura documental: local o aws."
  type        = string
  default     = "local"

  validation {
    condition     = contains(["local", "aws"], var.document_ai_provider)
    error_message = "document_ai_provider debe ser local o aws."
  }
}

output "environment" {
  description = "Entorno activo de esta configuración."
  value       = var.environment
}

output "aws_enabled" {
  description = "Indica si la configuración apunta a recursos AWS."
  value       = var.environment == "aws"
}

output "document_connector" {
  description = "Conector activo del pipeline local."
  value       = var.document_connector
}

output "auth_provider" {
  description = "Proveedor de identidad activo del entorno local."
  value       = var.auth_provider
}

output "aws_region" {
  description = "Región AWS configurada."
  value       = var.aws_region
}

output "document_ai_provider" {
  description = "Proveedor explícito de análisis documental."
  value       = var.document_ai_provider
}
