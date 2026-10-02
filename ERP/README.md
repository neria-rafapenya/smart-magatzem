# ERP

Esta carpeta contiene el dominio funcional del ERP mock: pedidos, clientes, productos,
almacenes, albaranes y recepción de albaranes previamente validados.

El flujo de recepción que estamos probando es:

```text
documento capturado → OCR/reglas → importación ERP → copia cliente
                              ↘ rechazado para revisión
```

Los clientes se consultan desde `/api/v1/customers` y el resultado validado entra por
`/api/v1/delivery-notes/import`. El backend expone el pipeline y el frontend Expo solo
captura documentos y muestra su resultado; no crea albaranes.
