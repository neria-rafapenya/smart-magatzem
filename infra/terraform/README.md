# Infraestructura local y AWS

La misma configuración permite dos modos explícitos:

- `environment=local`: no crea recursos AWS y mantiene el mock ERP, la identidad local y el OCR local.
- `environment=aws`: prepara CloudFront + S3 privado para Expo web, API Gateway HTTP + Lambda, Cognito, DynamoDB `PAY_PER_REQUEST`, S3 documental, SQS y Step Functions.

El flujo AWS no publica un servidor ERP mock separado. El backend usa un adaptador
`mock_aws` con el mismo contrato del ERP local y persiste sus datos en DynamoDB. Cuando
conozcamos la API real, se sustituirá únicamente ese adaptador.

## Validación local

```bash
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan
```

## Preparar AWS sin desplegar todavía

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
terraform -chdir=infra/terraform plan -var-file=terraform.tfvars
```

Para activar el runtime hay que generar antes el paquete Lambda y establecer
`enable_aws_runtime=true`. No se ejecuta `apply` automáticamente.

```bash
./scripts/build-aws-lambda.sh
terraform -chdir=infra/terraform apply -var-file=terraform.tfvars
```

El script de cuentas crea dos usuarios fuera de Terraform para no guardar contraseñas
en el estado:

```bash
AWS_REGION=eu-west-1 \
COGNITO_USER_POOL_ID="$(terraform -chdir=infra/terraform output -raw cognito_user_pool_id)" \
CORE_TABLE="$(terraform -chdir=infra/terraform output -raw core_table)" \
ADMIN_EMAIL=admin@tu-dominio.example \
GUEST_EMAIL=guest@tu-dominio.example \
ADMIN_TEMP_PASSWORD='Cambia-Esta-Temporal-1!' \
GUEST_TEMP_PASSWORD='Cambia-Esta-Temporal-2!' \
./scripts/bootstrap-cognito.sh
```

Aunque las variables mantienen el nombre `TEMP_PASSWORD` por compatibilidad, el
script las convierte en contraseñas permanentes para que el primer acceso de la
demo no quede bloqueado por el reto de cambio de contraseña de Cognito.

Los grupos `admin` y `guest` son roles; el aislamiento multi-tenant se basa además en
`custom:tenant_id` y en la partición `TENANT#...` de DynamoDB. No se confía solamente en
el grupo Cognito para aislar datos.

CloudFront usa un bucket S3 privado mediante Origin Access Control. El móvil Android y
la web usan el mismo API Gateway y el mismo app client público de Cognito; la APK nunca
lleva claves AWS. Se configura con `EXPO_PUBLIC_BACKEND_API_URL`,
`EXPO_PUBLIC_AUTH_PROVIDER=cognito`, `EXPO_PUBLIC_COGNITO_USER_POOL_ID` y
`EXPO_PUBLIC_COGNITO_CLIENT_ID`.

La configuración evita servicios de cómputo permanente: no crea EC2, ECS, RDS, NAT
Gateway ni balanceadores. Lambda, API Gateway, DynamoDB on-demand, S3, SQS, Step
Functions, Bedrock, Textract y SES solo generan uso cuando se invocan. CloudWatch queda
para una fase posterior y no se crean alarmas por defecto.
