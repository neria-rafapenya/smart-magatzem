#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT_DIR/infra/terraform"
TFVARS_FILE="${TFVARS_FILE:-$TF_DIR/terraform.tfvars}"

if [[ ! -f "$TFVARS_FILE" ]]; then
  echo "Falta $TFVARS_FILE. Copia terraform.tfvars.example y revisa sus valores." >&2
  exit 1
fi

terraform -chdir="$TF_DIR" init
"$ROOT_DIR/scripts/build-aws-lambda.sh"
terraform -chdir="$TF_DIR" apply -var-file="$TFVARS_FILE"

FRONTEND_BUCKET="$(terraform -chdir="$TF_DIR" output -raw frontend_bucket 2>/dev/null || true)"
CLOUDFRONT_ID="$(terraform -chdir="$TF_DIR" output -raw cloudfront_distribution_id 2>/dev/null || true)"
API_URL="$(terraform -chdir="$TF_DIR" output -raw api_url 2>/dev/null || true)"
USER_POOL_ID="$(terraform -chdir="$TF_DIR" output -raw cognito_user_pool_id 2>/dev/null || true)"
CLIENT_ID="$(terraform -chdir="$TF_DIR" output -raw cognito_client_id 2>/dev/null || true)"
if [[ -z "$FRONTEND_BUCKET" ]]; then
  echo "Terraform no devolvió frontend_bucket; revisa los outputs." >&2
  exit 1
fi

(cd "$ROOT_DIR/frontend" && \
  EXPO_PUBLIC_BACKEND_API_URL="$API_URL" \
  EXPO_PUBLIC_AUTH_PROVIDER=cognito \
  EXPO_PUBLIC_AWS_REGION="${AWS_REGION:-eu-west-1}" \
  EXPO_PUBLIC_COGNITO_USER_POOL_ID="$USER_POOL_ID" \
  EXPO_PUBLIC_COGNITO_CLIENT_ID="$CLIENT_ID" \
  npx expo export --platform web --clear)
aws s3 sync "$ROOT_DIR/frontend/dist" "s3://$FRONTEND_BUCKET" --delete
if [[ -n "$CLOUDFRONT_ID" ]]; then
  aws cloudfront create-invalidation --distribution-id "$CLOUDFRONT_ID" --paths '/*' >/dev/null
fi
terraform -chdir="$TF_DIR" output
