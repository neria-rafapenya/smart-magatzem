# Smart Magatzem

Primer vertical local para simular la recepción y validación de pedidos, albaranes, packing lists, documentos de transporte y facturas. El proyecto está separado en
`backend`, `ERP` y `frontend`, y se puede probar sin credenciales, servicios externos
ni conexión con AWS.

En esta fase todo funciona en local: mock ERP, backend integrador y frontend Expo.

## Estructura

- `backend/`: API HTTP local y punto de arranque del servidor.
- `ERP/`: modelos y reglas de negocio del ERP mock, con endpoints separados para documentos comerciales y logísticos.
- `frontend/`: app Expo para capturar documentos y seleccionar clientes.
- `infra/terraform/`: infraestructura Terraform para el modo local y el demo AWS.

## Mock ERP para pruebas

Para levantar el mock ERP, el backend y el frontend Expo juntos:

```bash
bash scripts/start-local.sh
```

Si has cambiado el frontend y Expo conserva un bundle anterior, detén el proceso
anterior y ejecuta una vez:

```bash
EXPO_CLEAR_CACHE=1 bash scripts/start-local.sh
```

El backend extrae texto de PDFs digitales localmente con `pypdf` y mantiene
Tesseract como respaldo para imágenes y PDFs escaneados. No se usa AWS en esta
fase. Las imágenes pasan además por un analizador local de calidad que comprueba
resolución, enfoque, iluminación, contraste, sombras y posibles recortes antes del OCR.

El pipeline también distingue documentos nativos: un XML se interpreta directamente
con su estructura y un PDF con texto seleccionable se lee sin OCR. El tipo `deca`
solo acepta ese formato nativo; una fotografía o un escaneo no se envían como DeCA.

El proveedor de lectura documental se selecciona de forma explícita con
`DOCUMENT_AI_PROVIDER`. Por defecto es `local`, que mantiene el flujo actual de
Pillow + Tesseract + reglas deterministas. El runtime desplegado en AWS utiliza
Bedrock + Textract; el servidor local rechaza `DOCUMENT_AI_PROVIDER=aws` para evitar
conexiones accidentales desde localhost.

```bash
DOCUMENT_AI_PROVIDER=local bash scripts/start-local.sh
```

El script comprueba `/health`, reutiliza servicios que ya estén activos y mantiene
los procesos abiertos hasta pulsar `Ctrl+C`. Expo se inicia en modo LAN con la URL
del backend configurada automáticamente.

Arranca el ERP simulado con datos semilla deterministas, incluyendo 20 clientes,
10 proveedores españoles y un albarán histórico (`ALB-1000`).

```bash
python -m ERP.mock_erp
```

Queda disponible en `http://127.0.0.1:9000`.

Sandbox Swagger UI:

```text
http://127.0.0.1:9000/docs
```

Contrato OpenAPI:

```text
http://127.0.0.1:9000/openapi.json
```

Comprobación rápida:

```bash
curl http://127.0.0.1:9000/health
curl http://127.0.0.1:9000/api/v1/products
curl http://127.0.0.1:9000/api/v1/orders
curl http://127.0.0.1:9000/api/v1/delivery-notes
curl http://127.0.0.1:9000/api/v1/snapshot
```

Consultar clientes para el autocomplete:

```bash
curl 'http://127.0.0.1:9000/api/v1/customers?q=garcia'
curl 'http://127.0.0.1:9000/api/v1/suppliers?q=transporte'
```

El flujo principal ya no crea documentos desde la web. El backend recibe una imagen o
PDF, lo guarda en `data/local-s3`, ejecuta OCR/reglas, identifica automáticamente el
tipo de documento y la dirección de entrada/salida, y permite fijarlos manualmente
cuando el documento es ambiguo.
Si es válido, lo importa al endpoint correspondiente del ERP mock y prepara una copia
local para el cliente.

El campo `document_type` acepta `auto`, `order`, `delivery_note`, `packing_list`,
`transport_document`, `invoice` o `deca`. Los pedidos se clasifican además como compra o venta
cuando el texto lo permite. `document_direction` admite `auto`, `inbound` u `outbound`.

```bash
GET  http://127.0.0.1:8000/api/customers
GET  http://127.0.0.1:8000/api/intake/documents
GET  http://127.0.0.1:8000/api/usage/aws
POST http://127.0.0.1:8000/api/intake/documents/analyze
POST http://127.0.0.1:8000/api/intake/documents

# Compatibilidad con el endpoint histórico de albaranes
GET  http://127.0.0.1:8000/api/intake/delivery-notes
POST http://127.0.0.1:8000/api/intake/delivery-notes/analyze
POST http://127.0.0.1:8000/api/intake/delivery-notes
```

El endpoint `analyze` hace la prevalidación de OCR, calidad y campos obligatorios sin
enviar el documento al ERP. El envío solo se permite después de una interpretación válida.
Antes del envío se calcula una huella del contenido y una clave de negocio (tenant,
cliente, tipo y número) para bloquear duplicados. Cuando un albarán incluye una referencia
a un pedido, o una factura a un albarán, se intenta validar el documento relacionado y
sus cantidades; las diferencias quedan en revisión. Las tolerancias y el comportamiento
se guardan por tenant.

Si el análisis falla, la interfaz ofrece `Introducir datos manualmente`: el operador puede
confirmar tipo, número, dirección y líneas (además de datos logísticos opcionales), y volver
a ejecutar la misma prevalidación mediante `manual_data`. La evidencia original se conserva
y el registro queda marcado con `input_mode=manual` para distinguir la corrección humana.
Cuando el documento se acepta, el mock prepara también una copia para el cliente y
registra un envío de correo simulado en `data/local-s3/outbox`. Para probar más adelante
con una dirección propia, se puede usar `EMAIL_RECIPIENT_OVERRIDE` (en AWS,
`email_recipient_override` en Terraform); mientras el proveedor siga siendo local no se
envía ningún correo real.

`/api/usage/aws` separa las peticiones reales de la estimación equivalente del futuro
flujo AWS y excluye Cognito. En local, las peticiones reales permanecen a cero y la
estimación se desglosa por S3, Bedrock, Textract, Step Functions y SES.
La pantalla también muestra el coste aproximado de los tokens en euros. Por defecto
usa los precios estándar configurados para Amazon Nova Lite (0,06 USD por millón de
tokens de entrada y 0,24 USD por millón de salida) y un cambio configurable de 0,92
USD/EUR. Se pueden ajustar mediante `BEDROCK_INPUT_USD_PER_MILLION`,
`BEDROCK_OUTPUT_USD_PER_MILLION` y `USD_TO_EUR_RATE`; la cifra es orientativa y no
sustituye a Cost Explorer ni a la factura de AWS.

Prueba de aceptación completa a través del backend:

```bash
./scripts/test-albaranes.sh
```

El script comprueba los dos servicios, reinicia los datos semilla y valida el ciclo
documento → object store local → OCR/reglas → ERP → copia cliente sin tocar AWS.

Para probar el pipeline sin depender del mock ERP como destino, arranca el backend con
un conector genérico de ficheros:

```bash
DOCUMENT_CONNECTOR=file bash scripts/start-local.sh
```

Si se quiere probar solo el pipeline y el conector de ficheros, sin arrancar el mock
ERP, se puede usar `START_MOCK_ERP=0`. En ese modo el frontend no podrá cargar los
maestros del ERP, pero el backend seguirá aceptando documentos con los datos del cliente
incluidos en la petición.

Cada documento aprobado queda en `data/connectors/files` como JSON canónico, CSV y XLSX
compatible con Excel. El conector usa una huella estable del contenido para evitar
duplicados.

La autenticación local está preparada para sustituirse por Cognito o SSO corporativo:

```text
POST http://127.0.0.1:8000/api/auth/login
{
  "email": "admin@smart-magatzem.local",
  "password": "demo1234"
}
```

Usuarios locales disponibles: administrador, supervisor y operario. Para activar la
comprobación de permisos en los endpoints de captura y envío se puede usar
`LOCAL_AUTH_REQUIRED=1`. Por defecto permanece desactivada para no romper las pruebas
actuales del frontend.

### Configuración de tenants en localhost

En la web, entra con el usuario administrador local:

```text
admin@smart-magatzem.local
demo1234
```

La pantalla de configuración aparece con el icono de ajustes de la cabecera y permite:

- crear tenants;
- configurar el endpoint y el tipo de autenticación del ERP;
- guardar el secreto sin volver a mostrarlo;
- probar la conexión contra el ERP mock;
- editar los campos del documento que acepta el ERP;
- cargar plantillas PDF generales por tenant.
- configurar tolerancias de cantidad/precio, política de duplicados y subida multipágina.
- configurar captura guiada, linterna inicial, cola offline, modo ráfaga, memoria de la
  última selección y umbral de confianza de lectura.

El usuario operario no puede acceder a esta pantalla aunque conozca la ruta o intente
llamar directamente a la API. La autorización se comprueba en backend mediante el
permiso `tenant.configure`.

La configuración local se guarda en `data/local-secrets/tenant-config.json` con permisos
restringidos y las plantillas en `data/local-tenant-templates/<TENANT_ID>`. En AWS, el
secreto de conexión se sustituirá por Secrets Manager; DynamoDB conservará la configuración
no sensible y la referencia al secreto.

El tenant inicial `TEN-001` incluye como ejemplo los campos de la plantilla de pedido
`08-plantilla-pedido-en-blanco.pdf`, copiada desde el documento de referencia del proyecto.
Los campos sembrados son número, fecha, entrega prevista, dirección, cliente/proveedor,
CIF, email, dirección, SKU, descripción, cantidad, unidad, observaciones y firmas.

La subida multipágina está desactivada por defecto para evitar consumo accidental. Se
activa por tenant desde la pantalla de configuración o, para una prueba local puntual,
con `ENABLE_BATCH_DOCUMENTS=1`. El contrato acepta `pages: [{filename, content_type,
content_base64}]` y limita el número de páginas configurado. La aplicación muestra un
marco de captura, permite activar la linterna, comprueba localmente iluminación/nitidez,
recorta la imagen y puede añadir varias hojas al mismo documento.

La configuración de captura se consulta con `GET /api/tenant/capture-settings` y solo un
administrador puede modificarla mediante `POST /api/admin/document-config/capture-settings`.
Las preferencias de cliente, tipo y dirección se guardan separadas por usuario y tenant.
Si se pierde la conexión al enviar un documento, la app lo conserva temporalmente en una
cola local y lo reintenta cuando vuelve la conectividad. El runtime Cognito renueva la
sesión antes de restaurarla para evitar caducidades durante un turno.

La interpretación incluye una confianza estimada por campo. La pantalla destaca los
campos dudosos y permite abrir los detalles de lectura antes del envío. El historial
incluye búsqueda y filtros por hoy, pendientes y errores.

También se puede crear un tenant mediante API, siempre autenticado como administrador:

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@smart-magatzem.local","password":"demo1234"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -X POST http://127.0.0.1:8000/api/tenants \
  -H "Authorization: Bearer $TOKEN" \
  -H 'X-Tenant-Id: TEN-001' \
  -H 'Content-Type: application/json' \
  -d '{"id":"TEN-CLIENTE-001","name":"Cliente Demo S.L."}'
```

El nuevo tenant queda asignado al administrador que lo crea. Las peticiones posteriores
pueden operar sobre él usando `X-Tenant-Id`; el backend comprueba que el usuario pertenece
a ese tenant antes de aceptar la operación.

El backend consume este flujo mediante `/api/delivery-notes` y comprueba la
dependencia ERP con `http://127.0.0.1:8000/ready`.

## Arranque rápido

Requiere Python 3.11+ y Terraform 1.5+ para validar la capa de infraestructura.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s backend/tests -v
./scripts/start-local.sh
```

El mock ERP queda en `http://127.0.0.1:9000`, el backend integrador en
`http://127.0.0.1:8000` y Expo usa el puerto `8081`.

## Frontend Expo

El frontend está preparado con Expo, React Native, React Native Web y React Native
Paper. Para probarlo en web:

```bash
cd frontend
npx expo start --web
```

Para probarlo con Expo Go:

```bash
cd frontend
npx expo start
```

En un dispositivo físico, configura la IP de tu Mac para que el teléfono pueda
alcanzar el mock ERP y haz que los servicios escuchen en la red local:

```bash
LOCAL_BIND_HOST=0.0.0.0 \
EXPO_PUBLIC_BACKEND_API_URL=http://TU_IP_LOCAL:8000 \
./scripts/start-local.sh
```

La pantalla inicial se centra en capturar albaranes, seleccionar un cliente con
autocomplete y revisar el resultado del pipeline. Usa Material mediante React Native
Paper.

## Despliegue AWS del demo

El modo local sigue siendo el modo por defecto. AWS solo se activa cuando
`environment=aws` y `enable_aws_runtime=true` están configurados explícitamente.

La arquitectura demo es serverless: frontend Expo web en S3 privado y CloudFront, API
Gateway HTTP + Lambda, Cognito, DynamoDB `PAY_PER_REQUEST`, S3 documental, SQS y Step
Functions. Bedrock, Textract y SES solo se invocan al procesar documentos. El ERP mock
local no se publica como servidor: en AWS Lambda se usa el adaptador `mock_aws` y más
adelante se sustituirá por el conector del ERP real.

El despliegue crea recursos AWS y puede generar costes por uso. Para la demo existe una
alerta mensual de 5 USD asociada al presupuesto `smart-magatzem-demo-monthly`.

### Requisitos

Se necesita AWS CLI v2, Terraform 1.5+, Python 3.11+, Node.js, una cuenta AWS con
permisos sobre los recursos definidos y las dependencias locales instaladas.

### 1. Autenticar AWS

```bash
aws login --profile smart-magatzem --region eu-west-1
export AWS_PROFILE=smart-magatzem
export AWS_REGION=eu-west-1
aws sts get-caller-identity
```

Si la sesión caduca, repetir `aws login`.

### 2. Configurar Terraform

```bash
cp infra/terraform/terraform.tfvars.example \
  infra/terraform/terraform.tfvars
```

Editar `infra/terraform/terraform.tfvars`:

```hcl
environment          = "aws"
aws_region           = "eu-west-1"
project_name         = "smart-magatzem"
auth_provider        = "cognito"
document_ai_provider = "aws"

enable_aws_runtime  = true
lambda_package_path = "../../build/aws-lambda.zip"
frontend_bucket_name = ""

bedrock_model_id = "amazon.nova-lite-v1:0"

# Mantener vacíos mientras el email sea simulado.
ses_from_email   = ""
ses_identity_arn = ""

# Opcional para pruebas: redirige el correo efectivo sin modificar el cliente leído.
email_recipient_override = "rafa@wad.cat"
```

El modelo Bedrock debe admitir imágenes y estar disponible en `eu-west-1`:

```bash
aws bedrock list-foundation-models \
  --profile smart-magatzem \
  --region eu-west-1 \
  --by-provider Amazon \
  --query "modelSummaries[?contains(inputModalities, 'IMAGE')].[modelId,inputModalities]" \
  --output table
```

### 3. Preparar y revisar el plan

```bash
export AWS_PROFILE=smart-magatzem
export AWS_REGION=eu-west-1

terraform -chdir=infra/terraform init
./scripts/build-aws-lambda.sh
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform plan \
  -var-file=terraform.tfvars
```

El paquete Lambda se genera en `build/aws-lambda.zip`; por eso Terraform usa la ruta
`../../build/aws-lambda.zip` desde `infra/terraform`.

### 4. Desplegar backend y frontend web

Cuando el plan sea correcto:

```bash
AWS_PROFILE=smart-magatzem \
AWS_REGION=eu-west-1 \
./scripts/deploy-demo.sh
```

El script aplica Terraform, empaqueta Lambda, crea la infraestructura, exporta el
frontend Expo web, lo sube a S3 e invalida CloudFront. Terraform pedirá confirmación:
escribir `yes` y pulsar Enter.

Si el primer `apply` falla al crear DynamoDB con un mensaje de KMS indicando que
`alias/aws/dynamodb` todavía no existe, se trata de una propagación eventual de la clave
gestionada por AWS. Esperar unos segundos y ejecutar de nuevo el mismo comando; Terraform
reutilizará CloudFront y los recursos ya creados y continuará con los pendientes.

Al terminar mostrará `frontend_url`, `api_url`, los identificadores de Cognito, la tabla
principal y el bucket de documentos. La APK todavía no se genera en este paso.

### 5. Crear las cuentas Cognito

```bash
export AWS_PROFILE=smart-magatzem
export AWS_REGION=eu-west-1
export COGNITO_USER_POOL_ID="$(terraform -chdir=infra/terraform output -raw cognito_user_pool_id)"
export CORE_TABLE="$(terraform -chdir=infra/terraform output -raw core_table)"
export ADMIN_EMAIL="tu-correo-admin@example.com"
export GUEST_EMAIL="tu-correo-guest@example.com"
export ADMIN_TEMP_PASSWORD='Cambia-Esta-Temporal-1!'
export GUEST_TEMP_PASSWORD='Cambia-Esta-Temporal-2!'
export TENANT_ID="TEN-DEMO"

./scripts/bootstrap-cognito.sh
```

El script crea los grupos `admin` y `guest`, asocia ambos usuarios al tenant indicado y
guarda la relación usuario–tenant en DynamoDB.

### 6. Configurar y generar la APK Android

La APK no contiene claves AWS. Solo incorpora la URL pública de API Gateway y los
identificadores públicos de Cognito.

```bash
export API_URL="$(terraform -chdir=infra/terraform output -raw api_url)"
export USER_POOL_ID="$(terraform -chdir=infra/terraform output -raw cognito_user_pool_id)"
export CLIENT_ID="$(terraform -chdir=infra/terraform output -raw cognito_client_id)"
cd frontend

npx eas-cli env:set --name EXPO_PUBLIC_BACKEND_API_URL \
  --value "$API_URL" --environment preview --visibility plaintext
npx eas-cli env:set --name EXPO_PUBLIC_AUTH_PROVIDER \
  --value cognito --environment preview --visibility plaintext
npx eas-cli env:set --name EXPO_PUBLIC_AWS_REGION \
  --value eu-west-1 --environment preview --visibility plaintext
npx eas-cli env:set --name EXPO_PUBLIC_COGNITO_USER_POOL_ID \
  --value "$USER_POOL_ID" --environment preview --visibility plaintext
npx eas-cli env:set --name EXPO_PUBLIC_COGNITO_CLIENT_ID \
  --value "$CLIENT_ID" --environment preview --visibility plaintext

npx eas-cli build --platform android --profile preview
```

EAS alojará el artefacto APK y devolverá un enlace de descarga. La APK instalada se
conectará a API Gateway AWS, no a `127.0.0.1`.

### 7. SES real opcional

Para mantener el correo simulado, dejar `ses_from_email` y `ses_identity_arn` vacíos. Si
se quiere enviar correo real, verificar primero una dirección o dominio en SES en
`eu-west-1`, rellenar ambos valores y volver a ejecutar el despliegue.

### 8. Destruir la demo

```bash
AWS_PROFILE=smart-magatzem \
AWS_REGION=eu-west-1 \
terraform -chdir=infra/terraform destroy \
  -var-file=terraform.tfvars
```

Revisar la destrucción antes de confirmarla. El bucket de documentos puede tener objetos
y deberá vaciarse manualmente solo si se desea eliminar también las evidencias.

## Decisiones iniciales

- API basada en la biblioteca estándar de Python para que el primer arranque sea ligero.
- El mock ERP mantiene datos semilla reiniciables para probar albaranes de forma repetible.
- El modo local mantiene AWS explícitamente fuera; el modo AWS se activa de forma separada
  mediante Terraform cuando el demo esté preparado.
- En AWS no se usan EC2, ECS, RDS, NAT Gateway ni balanceadores: la capacidad de cómputo
  se activa por petición y el móvil consume la misma API protegida por Cognito.
