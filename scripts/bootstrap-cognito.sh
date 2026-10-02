#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_CONFIG="$SCRIPT_DIR/.bootstrap-cognito.env"
if [[ -f "$LOCAL_CONFIG" ]]; then
  # Configuración privada de la demo; este fichero está excluido de Git.
  source "$LOCAL_CONFIG"
fi

: "${AWS_REGION:?Define AWS_REGION}"
: "${COGNITO_USER_POOL_ID:?Define COGNITO_USER_POOL_ID con el output de Terraform}"
: "${CORE_TABLE:?Define CORE_TABLE con el output de Terraform}"
: "${ADMIN_EMAIL:?Define ADMIN_EMAIL}"
: "${GUEST_EMAIL:?Define GUEST_EMAIL}"

# Si no existe la configuración privada local, se solicitan las contraseñas
# de forma interactiva y no se muestran en pantalla.
if [[ -z "${ADMIN_TEMP_PASSWORD:-}" ]]; then
  read -r -s -p "Contraseña temporal para ${ADMIN_EMAIL}: " ADMIN_TEMP_PASSWORD
  printf '\n'
fi
if [[ -z "${GUEST_TEMP_PASSWORD:-}" ]]; then
  read -r -s -p "Contraseña temporal para ${GUEST_EMAIL}: " GUEST_TEMP_PASSWORD
  printf '\n'
fi
: "${ADMIN_TEMP_PASSWORD:?Define ADMIN_TEMP_PASSWORD}"
: "${GUEST_TEMP_PASSWORD:?Define GUEST_TEMP_PASSWORD}"

TENANT_ID="${TENANT_ID:-TEN-DEMO}"

create_user() {
  local email="$1"
  local password="$2"
  if (( ${#password} < 12 )) ||
    [[ ! "$password" =~ [[:lower:]] ]] ||
    [[ ! "$password" =~ [[:upper:]] ]] ||
    [[ ! "$password" =~ [[:digit:]] ]] ||
    [[ ! "$password" =~ [^[:alnum:]] ]]; then
    echo "La contraseña de $email debe tener al menos 12 caracteres, mayúscula, minúscula, número y símbolo." >&2
    exit 1
  fi
  if aws cognito-idp admin-get-user --region "$AWS_REGION" --user-pool-id "$COGNITO_USER_POOL_ID" --username "$email" >/dev/null 2>&1; then
    echo "Usuario Cognito ya existente: $email"
  else
    aws cognito-idp admin-create-user \
      --region "$AWS_REGION" \
      --user-pool-id "$COGNITO_USER_POOL_ID" \
      --username "$email" \
      --temporary-password "$password" \
      --message-action SUPPRESS \
      --user-attributes "Name=email,Value=$email" "Name=email_verified,Value=true" "Name=custom:tenant_id,Value=$TENANT_ID" >/dev/null
    echo "Usuario Cognito creado: $email"
  fi

  # El frontend de demo no necesita mostrar el reto NEW_PASSWORD_REQUIRED.
  # Se establece la contraseña como permanente para que el primer login funcione.
  aws cognito-idp admin-set-user-password \
    --region "$AWS_REGION" \
    --user-pool-id "$COGNITO_USER_POOL_ID" \
    --username "$email" \
    --password "$password" \
    --permanent >/dev/null
}

set_role_group() {
  local email="$1"
  local group="$2"
  local other_group="guest"
  [[ "$group" == "guest" ]] && other_group="admin"

  aws cognito-idp admin-add-user-to-group \
    --region "$AWS_REGION" \
    --user-pool-id "$COGNITO_USER_POOL_ID" \
    --username "$email" \
    --group-name "$group"

  if aws cognito-idp admin-list-groups-for-user \
    --region "$AWS_REGION" \
    --user-pool-id "$COGNITO_USER_POOL_ID" \
    --username "$email" \
    --query "Groups[?GroupName=='$other_group'].GroupName" \
    --output text | grep -q "$other_group"; then
    aws cognito-idp admin-remove-user-from-group \
      --region "$AWS_REGION" \
      --user-pool-id "$COGNITO_USER_POOL_ID" \
      --username "$email" \
      --group-name "$other_group"
  fi
}

map_user_to_tenant() {
  local email="$1"
  local role="$2"
  local sub
  sub="$(aws cognito-idp admin-get-user --region "$AWS_REGION" --user-pool-id "$COGNITO_USER_POOL_ID" --username "$email" --query "UserAttributes[?Name=='sub'].Value | [0]" --output text)"
  aws dynamodb put-item \
    --region "$AWS_REGION" \
    --table-name "$CORE_TABLE" \
    --item "{\"pk\":{\"S\":\"USER#$sub\"},\"sk\":{\"S\":\"PROFILE\"},\"tenant_id\":{\"S\":\"$TENANT_ID\"},\"role\":{\"S\":\"$role\"},\"email\":{\"S\":\"$email\"}}"
}

create_user "$ADMIN_EMAIL" "$ADMIN_TEMP_PASSWORD"
create_user "$GUEST_EMAIL" "$GUEST_TEMP_PASSWORD"
set_role_group "$ADMIN_EMAIL" admin
set_role_group "$GUEST_EMAIL" guest
map_user_to_tenant "$ADMIN_EMAIL" admin
map_user_to_tenant "$GUEST_EMAIL" guest

echo "Cognito preparado para tenant $TENANT_ID: admin=$ADMIN_EMAIL guest=$GUEST_EMAIL"
