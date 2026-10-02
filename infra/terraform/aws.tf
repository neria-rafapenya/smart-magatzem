locals {
  aws_enabled     = var.environment == "aws"
  runtime_enabled = local.aws_enabled && var.enable_aws_runtime
  name            = replace(lower(var.project_name), "_", "-")
  frontend_bucket = var.frontend_bucket_name != "" ? var.frontend_bucket_name : "${local.name}-${try(data.aws_caller_identity.current[0].account_id, "local")}-frontend"
}

provider "aws" {
  region                      = var.aws_region
  access_key                  = var.environment == "local" ? "local" : null
  secret_key                  = var.environment == "local" ? "local" : null
  skip_credentials_validation = var.environment == "local"
  skip_requesting_account_id  = var.environment == "local"
  skip_region_validation      = var.environment == "local"
  skip_metadata_api_check     = var.environment == "local"

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {
  count = local.aws_enabled ? 1 : 0
}

resource "aws_s3_bucket" "frontend" {
  count  = local.aws_enabled ? 1 : 0
  bucket = local.frontend_bucket
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  count                   = local.aws_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.frontend[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  count  = local.aws_enabled ? 1 : 0
  bucket = aws_s3_bucket.frontend[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "frontend" {
  count                             = local.aws_enabled ? 1 : 0
  name                              = "${local.name}-frontend-oac"
  description                       = "Acceso privado de CloudFront al frontend Expo"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "frontend" {
  count               = local.aws_enabled ? 1 : 0
  enabled             = true
  default_root_object = "index.html"
  comment             = "${var.project_name} demo web"

  origin {
    domain_name              = aws_s3_bucket.frontend[0].bucket_regional_domain_name
    origin_id                = "${local.name}-frontend"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend[0].id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD", "OPTIONS"]
    target_origin_id       = "${local.name}-frontend"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }
}

data "aws_iam_policy_document" "frontend_bucket" {
  count = local.aws_enabled ? 1 : 0

  statement {
    sid    = "AllowCloudFrontReadOnly"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend[0].arn}/*"]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend[0].arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  count  = local.aws_enabled ? 1 : 0
  bucket = aws_s3_bucket.frontend[0].id
  policy = data.aws_iam_policy_document.frontend_bucket[0].json
}

resource "aws_s3_bucket" "documents" {
  count  = local.aws_enabled ? 1 : 0
  bucket = "${local.name}-${data.aws_caller_identity.current[0].account_id}-documents"
}

resource "aws_s3_bucket_public_access_block" "documents" {
  count                   = local.aws_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.documents[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  count  = local.aws_enabled ? 1 : 0
  bucket = aws_s3_bucket.documents[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  count  = local.aws_enabled ? 1 : 0
  bucket = aws_s3_bucket.documents[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  count  = local.aws_enabled ? 1 : 0
  bucket = aws_s3_bucket.documents[0].id

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_dynamodb_table" "core" {
  count        = local.aws_enabled ? 1 : 0
  name         = "${local.name}-core"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_sqs_queue" "document_dlq" {
  count                     = local.aws_enabled ? 1 : 0
  name                      = "${local.name}-documents-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "documents" {
  count                      = local.aws_enabled ? 1 : 0
  name                       = "${local.name}-documents"
  visibility_timeout_seconds = 180
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.document_dlq[0].arn
    maxReceiveCount     = 3
  })
}

resource "aws_cognito_user_pool" "app" {
  count = local.aws_enabled ? 1 : 0
  name  = "${local.name}-users"

  # Cognito no permite modificar ni eliminar atributos de esquema después de crear
  # el User Pool. La definición inicial se mantiene, pero Terraform no debe intentar
  # reconciliar cambios posteriores en este bloque inmutable.
  lifecycle {
    ignore_changes = [schema]
  }

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OFF"

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  schema {
    name                = "tenant_id"
    attribute_data_type = "String"
    mutable             = true
    required            = false
  }
}

resource "aws_cognito_user_pool_client" "web_mobile" {
  count        = local.aws_enabled ? 1 : 0
  name         = "${local.name}-web-mobile"
  user_pool_id = aws_cognito_user_pool.app[0].id

  generate_secret                      = false
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  allowed_oauth_flows_user_pool_client = false
  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
}

resource "aws_cognito_user_group" "admin" {
  count        = local.aws_enabled ? 1 : 0
  name         = "admin"
  user_pool_id = aws_cognito_user_pool.app[0].id
  description  = "Administración de tenants, usuarios y documentos"
  precedence   = 10
}

resource "aws_cognito_user_group" "guest" {
  count        = local.aws_enabled ? 1 : 0
  name         = "guest"
  user_pool_id = aws_cognito_user_pool.app[0].id
  description  = "Consulta limitada de documentos autorizados"
  precedence   = 20
}

resource "aws_iam_role" "lambda" {
  count = local.runtime_enabled ? 1 : 0
  name  = "${local.name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  count      = local.runtime_enabled ? 1 : 0
  role       = aws_iam_role.lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_documents" {
  count = local.runtime_enabled ? 1 : 0
  name  = "${local.name}-lambda-documents"
  role  = aws_iam_role.lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.documents[0].arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
        Resource = aws_dynamodb_table.core[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.documents[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["textract:AnalyzeDocument", "textract:DetectDocumentText"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:Converse"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ses:SendEmail", "ses:SendRawEmail"]
        Resource = var.ses_identity_arn != "" ? var.ses_identity_arn : "*"
      },
    ]
  })
}

resource "aws_lambda_function" "api" {
  count            = local.runtime_enabled ? 1 : 0
  function_name    = "${local.name}-api"
  role             = aws_iam_role.lambda[0].arn
  handler          = "backend.aws_lambda.handler"
  runtime          = "python3.12"
  architectures    = ["arm64"]
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)
  timeout          = 30
  memory_size      = 1024

  environment {
    variables = {
      APP_ENV                  = "aws"
      AUTH_PROVIDER            = "cognito"
      DOCUMENT_AI_PROVIDER     = "aws"
      ERP_MODE                 = "mock_aws"
      DOCUMENTS_BUCKET         = aws_s3_bucket.documents[0].bucket
      CORE_TABLE               = aws_dynamodb_table.core[0].name
      DOCUMENT_QUEUE_URL       = aws_sqs_queue.documents[0].url
      COGNITO_USER_POOL_ID     = aws_cognito_user_pool.app[0].id
      DEFAULT_TENANT_ID        = var.default_tenant_id
      BEDROCK_MODEL_ID         = var.bedrock_model_id
      SES_FROM_EMAIL           = var.ses_from_email
      EMAIL_RECIPIENT_OVERRIDE = var.email_recipient_override
    }
  }
}

resource "aws_apigatewayv2_api" "http" {
  count         = local.runtime_enabled ? 1 : 0
  name          = "${local.name}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_headers = ["authorization", "content-type"]
    allow_methods = ["GET", "POST", "PUT", "OPTIONS"]
    allow_origins = ["*"]
  }
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  count            = local.runtime_enabled ? 1 : 0
  api_id           = aws_apigatewayv2_api.http[0].id
  authorizer_type  = "JWT"
  authorizer_uri   = null
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.name}-cognito"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web_mobile[0].id]
    issuer   = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.app[0].id}"
  }
}

resource "aws_apigatewayv2_integration" "api" {
  count                  = local.runtime_enabled ? 1 : 0
  api_id                 = aws_apigatewayv2_api.http[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api[0].invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "api" {
  count              = local.runtime_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.http[0].id
  route_key          = "$default"
  target             = "integrations/${aws_apigatewayv2_integration.api[0].id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito[0].id
}

# El navegador envía OPTIONS antes de las peticiones autenticadas con
# Authorization. Esta ruta no puede exigir JWT; de lo contrario API Gateway
# responde 401 al preflight y el frontend queda bloqueado por CORS.
resource "aws_apigatewayv2_route" "cors_preflight" {
  count              = local.runtime_enabled ? 1 : 0
  api_id             = aws_apigatewayv2_api.http[0].id
  route_key          = "OPTIONS /{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.api[0].id}"
  authorization_type = "NONE"
}

resource "aws_apigatewayv2_stage" "default" {
  count       = local.runtime_enabled ? 1 : 0
  api_id      = aws_apigatewayv2_api.http[0].id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "api_gateway" {
  count         = local.runtime_enabled ? 1 : 0
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http[0].execution_arn}/*/*"
}

resource "aws_iam_role" "step_functions" {
  count = local.runtime_enabled ? 1 : 0
  name  = "${local.name}-step-functions-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "step_functions" {
  count = local.runtime_enabled ? 1 : 0
  name  = "${local.name}-step-functions-policy"
  role  = aws_iam_role.step_functions[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = aws_lambda_function.api[0].arn
    }]
  })
}

resource "aws_sfn_state_machine" "documents" {
  count    = local.runtime_enabled ? 1 : 0
  name     = "${local.name}-documents"
  role_arn = aws_iam_role.step_functions[0].arn
  definition = jsonencode({
    StartAt = "ProcessDocument"
    States = {
      ProcessDocument = {
        Type     = "Task"
        Resource = aws_lambda_function.api[0].arn
        End      = true
      }
    }
  })
}

output "frontend_url" {
  description = "URL pública HTTPS del frontend CloudFront."
  value       = local.aws_enabled ? "https://${aws_cloudfront_distribution.frontend[0].domain_name}" : null
}

output "frontend_bucket" {
  description = "Bucket S3 privado del frontend."
  value       = local.aws_enabled ? aws_s3_bucket.frontend[0].bucket : null
}

output "cloudfront_distribution_id" {
  description = "Identificador de la distribución CloudFront."
  value       = local.aws_enabled ? aws_cloudfront_distribution.frontend[0].id : null
}

output "api_url" {
  description = "URL pública de la API HTTP API Gateway."
  value       = local.runtime_enabled ? aws_apigatewayv2_stage.default[0].invoke_url : null
}

output "documents_bucket" {
  description = "Bucket privado de evidencias documentales."
  value       = local.aws_enabled ? aws_s3_bucket.documents[0].bucket : null
}

output "cognito_user_pool_id" {
  description = "User Pool Cognito para web y Android."
  value       = local.aws_enabled ? aws_cognito_user_pool.app[0].id : null
}

output "cognito_client_id" {
  description = "App client público sin secreto para web y Android."
  value       = local.aws_enabled ? aws_cognito_user_pool_client.web_mobile[0].id : null
}

output "cognito_groups" {
  description = "Grupos Cognito creados para autorización."
  value       = local.aws_enabled ? [aws_cognito_user_group.admin[0].name, aws_cognito_user_group.guest[0].name] : []
}

output "core_table" {
  description = "Tabla DynamoDB multi-tenant en modo PAY_PER_REQUEST."
  value       = local.aws_enabled ? aws_dynamodb_table.core[0].name : null
}
