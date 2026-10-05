import { createElement, useCallback, useEffect, useState, type CSSProperties } from 'react';
import { Platform, Image, ScrollView, StyleSheet, View } from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Button, Menu, Surface, Text, TextInput } from 'react-native-paper';

import {
  createTenant,
  getErpConnection,
  getCaptureSettings,
  getTenantDocumentConfig,
  getTenants,
  saveErpConnection,
  saveCaptureSettings,
  saveTenantDocumentFields,
  saveTenantValidationRules,
  setTenantId,
  testErpConnection,
  resetProcessedDocuments,
  uploadTenantTemplate,
} from './api';
import type { AuthSession, ErpConnection, Tenant, TenantDocumentField, TenantTemplate } from './types';
import { FeedbackNotice } from './FeedbackNotice';

const AUTH_OPTIONS = [
  { value: 'none', label: 'Sin autenticación' },
  { value: 'api_key', label: 'API key' },
  { value: 'bearer', label: 'Bearer token' },
  { value: 'basic', label: 'Basic Auth' },
  { value: 'oauth2_client_credentials', label: 'OAuth2' },
];

const TEMPLATE_OPTIONS = [
  { value: 'order', label: 'Pedido' },
  { value: 'delivery_note', label: 'Albarán' },
  { value: 'packing_list', label: 'Packing list' },
  { value: 'transport_document', label: 'Transporte' },
  { value: 'invoice', label: 'Factura' },
  { value: 'deca', label: 'DeCA' },
];

export function AdminSettingsScreen({
  session,
  onBack,
  onLogout,
  onOpenUsage,
  onDocumentsReset,
}: {
  session: AuthSession;
  onBack: () => void;
  onLogout: () => void;
  onOpenUsage: () => void;
  onDocumentsReset?: () => Promise<void> | void;
}) {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState(session.user.tenant_id);
  const [tenantMenuVisible, setTenantMenuVisible] = useState(false);
  const [connection, setConnection] = useState<ErpConnection | null>(null);
  const [fields, setFields] = useState<TenantDocumentField[]>([]);
  const [templates, setTemplates] = useState<TenantTemplate[]>([]);
  const [quantityTolerance, setQuantityTolerance] = useState('0');
  const [priceTolerance, setPriceTolerance] = useState('0');
  const [batchEnabled, setBatchEnabled] = useState(false);
  const [maxPages, setMaxPages] = useState('20');
  const [guidedCapture, setGuidedCapture] = useState(true);
  const [torchDefault, setTorchDefault] = useState(false);
  const [offlineQueue, setOfflineQueue] = useState(true);
  const [rememberLastSelection, setRememberLastSelection] = useState(true);
  const [burstEnabled, setBurstEnabled] = useState(false);
  const [confidenceThreshold, setConfidenceThreshold] = useState('0.85');
  const [provider, setProvider] = useState('mock_erp');
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:9000');
  const [authType, setAuthType] = useState('none');
  const [username, setUsername] = useState('');
  const [secret, setSecret] = useState('');
  const [tenantId, setTenantIdDraft] = useState('');
  const [tenantName, setTenantName] = useState('');
  const [fieldKey, setFieldKey] = useState('');
  const [fieldLabel, setFieldLabel] = useState('');
  const [fieldRequired, setFieldRequired] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingFields, setSavingFields] = useState(false);
  const [uploadingTemplate, setUploadingTemplate] = useState(false);
  const [templateType, setTemplateType] = useState('order');
  const [testing, setTesting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [resettingDocuments, setResettingDocuments] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const loadConnection = useCallback(async (nextTenantId: string) => {
    setTenantId(nextTenantId);
    const value = await getErpConnection();
    const documentConfig = await getTenantDocumentConfig();
    const captureResponse = await getCaptureSettings();
    setConnection(value);
    setFields(documentConfig.fields);
    setTemplates(documentConfig.templates);
    const rules = documentConfig.validation_rules ?? {};
    const deliveryRule = rules.delivery_note_against_order as { quantity_tolerance_percent?: number } | undefined;
    const invoiceRule = rules.invoice_against_delivery_note as { price_tolerance_percent?: number } | undefined;
    setQuantityTolerance(String(deliveryRule?.quantity_tolerance_percent ?? 0));
    setPriceTolerance(String(invoiceRule?.price_tolerance_percent ?? 0));
    setBatchEnabled(Boolean(rules.enable_batch_documents));
    setMaxPages(String(rules.max_pages_per_document ?? 20));
    const capture = captureResponse.capture_settings;
    setGuidedCapture(Boolean(capture.guided_capture));
    setTorchDefault(Boolean(capture.torch_default));
    setOfflineQueue(Boolean(capture.offline_queue));
    setRememberLastSelection(Boolean(capture.remember_last_selection));
    setBurstEnabled(Boolean(capture.enable_burst));
    setConfidenceThreshold(String(capture.confidence_threshold ?? 0.85));
    setProvider(value.provider);
    setBaseUrl(value.base_url);
    setAuthType(value.auth_type);
    setUsername(value.username);
    setSecret('');
  }, []);

  const loadTenants = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await getTenants();
      setTenants(response.data);
      const preferred = response.data.find((tenant) => tenant.id === session.user.tenant_id) ?? response.data[0];
      if (preferred) {
        setSelectedTenantId(preferred.id);
        await loadConnection(preferred.id);
      }
    } catch (cause) {
      const message = (cause as Error).message;
      if (message.includes('autenticación') || message.includes('401')) onLogout();
      else setError(message);
    } finally {
      setLoading(false);
    }
  }, [loadConnection, onLogout, session.user.tenant_id]);

  useEffect(() => {
    if (Platform.OS === 'web') void loadTenants();
  }, [loadTenants]);

  const selectTenant = async (nextTenantId: string) => {
    setSelectedTenantId(nextTenantId);
    setError('');
    setMessage('');
    try {
      await loadConnection(nextTenantId);
    } catch (cause) {
      setError((cause as Error).message);
    }
  };

  const saveConnection = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const saved = await saveErpConnection({
        provider,
        base_url: baseUrl,
        auth_type: authType,
        username,
        secret,
      });
      setConnection(saved);
      setSecret('');
      setMessage('Conexión guardada. El secreto no se muestra de nuevo.');
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const addField = () => {
    const key = fieldKey.trim();
    const label = fieldLabel.trim();
    if (!key || !label) return;
    setFields((current) => [...current, { key, label, type: 'text', required: fieldRequired, source: 'erp' }]);
    setFieldKey('');
    setFieldLabel('');
    setFieldRequired(false);
  };

  const saveFields = async () => {
    setSavingFields(true);
    setError('');
    setMessage('');
    try {
      const response = await saveTenantDocumentFields(fields);
      setFields(response.fields);
      setMessage('Campos guardados correctamente.');
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSavingFields(false);
    }
  };

  const uploadTemplate = async () => {
    setUploadingTemplate(true);
    setError('');
    setMessage('');
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['application/pdf', 'image/*'],
        copyToCacheDirectory: true,
        base64: true,
      });
      if (result.canceled) return;
      const asset = result.assets[0];
      if (!asset.base64) throw new Error('No se ha podido leer la plantilla seleccionada.');
      const template = await uploadTenantTemplate({
        filename: asset.name,
        content_base64: asset.base64,
        document_type: templateType,
      });
      setTemplates((current) => [...current, template]);
      setMessage('Plantilla cargada correctamente.');
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setUploadingTemplate(false);
    }
  };

  const saveValidationRules = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const quantity = Number(quantityTolerance.replace(',', '.'));
      const price = Number(priceTolerance.replace(',', '.'));
      const pages = Number.parseInt(maxPages, 10);
      if (!Number.isFinite(quantity) || !Number.isFinite(price) || !Number.isInteger(pages)) {
        throw new Error('Las tolerancias y el límite de páginas deben ser numéricos.');
      }
      await saveTenantValidationRules({
        delivery_note_against_order: { enabled: true, quantity_tolerance_percent: quantity, on_mismatch: 'human_review' },
        invoice_against_delivery_note: { enabled: true, price_tolerance_percent: price, on_mismatch: 'human_review' },
        duplicate_policy: 'block',
        enable_batch_documents: batchEnabled,
        max_pages_per_document: pages,
        deca_native_required: true,
      });
      setMessage('Reglas de validación guardadas correctamente.');
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveCaptureConfiguration = async () => {
    setSaving(true);
    setError('');
    setMessage('');
    try {
      const threshold = Number(confidenceThreshold.replace(',', '.'));
      if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1) {
        throw new Error('El umbral de confianza debe estar entre 0 y 1.');
      }
      await saveCaptureSettings({
        guided_capture: guidedCapture,
        quality_gate: true,
        torch_default: torchDefault,
        enable_multipage: batchEnabled,
        enable_burst: burstEnabled,
        max_pages_per_document: Number.parseInt(maxPages, 10),
        max_file_size_mb: 2,
        remember_last_selection: rememberLastSelection,
        offline_queue: offlineQueue,
        confidence_threshold: threshold,
      });
      setMessage('Configuración de captura guardada correctamente.');
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const checkConnection = async () => {
    setTesting(true);
    setError('');
    setMessage('');
    try {
      const result = await testErpConnection();
      setConnection(result.connection);
      setMessage('Conexión comprobada correctamente.');
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setTesting(false);
    }
  };

  const addTenant = async () => {
    setCreating(true);
    setError('');
    setMessage('');
    try {
      const created = await createTenant({ id: tenantId, name: tenantName });
      setTenantIdDraft('');
      setTenantName('');
      setTenants((current) => [...current, created]);
      setSelectedTenantId(created.id);
      await loadConnection(created.id);
      setMessage(`Tenant ${created.id} creado y asignado a tu usuario.`);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const resetDocuments = async () => {
    const { default: Swal } = await import('sweetalert2');
    const confirmation = await Swal.fire({
      icon: 'warning',
      title: '¿Reiniciar documentos de prueba?',
      html: `Se borrarán los documentos procesados, análisis e imágenes del tenant <strong>${selectedTenantId}</strong>.<br/><br/>La configuración, las plantillas y el consumo se conservarán.`,
      input: 'text',
      inputLabel: 'Escribe BORRAR para confirmar',
      inputPlaceholder: 'BORRAR',
      showCancelButton: true,
      confirmButtonText: 'Borrar documentos',
      cancelButtonText: 'Cancelar',
      confirmButtonColor: '#b42318',
      inputValidator: (value) => value === 'BORRAR' ? undefined : 'Escribe BORRAR exactamente para continuar.',
    });
    if (!confirmation.isConfirmed) return;

    setResettingDocuments(true);
    setError('');
    setMessage('');
    try {
      const result = await resetProcessedDocuments();
      await onDocumentsReset?.();
      setMessage(`${result.deleted_documents} documentos y ${result.deleted_objects} archivos eliminados del tenant ${result.tenant_id}.`);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setResettingDocuments(false);
    }
  };

  if (Platform.OS !== 'web') return null;

  return (
    <View style={styles.root}>
      <View style={styles.header}>
        <Button icon="arrow-left" onPress={onBack}>Volver</Button>
        <View style={styles.headerCopy}>
          <Text variant="titleLarge">Configuración del tenant</Text>
          <Text variant="bodySmall" style={styles.muted}>Solo administradores · conexiones ERP</Text>
        </View>
        <Button icon="logout" onPress={onLogout}>Salir</Button>
      </View>
      <ScrollView contentContainerStyle={styles.content}>
        <FeedbackNotice message={message} error={error} />
        {loading ? <Text>Cargando configuración…</Text> : null}

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Tenants</Text>
          <Text variant="bodyMedium" style={styles.muted}>Selecciona el tenant cuya conexión quieres administrar.</Text>
          <Menu
            visible={tenantMenuVisible}
            onDismiss={() => setTenantMenuVisible(false)}
            anchor={(
              <Button
                mode="outlined"
                icon="chevron-down"
                contentStyle={styles.tenantSelectorContent}
                style={styles.tenantSelector}
                onPress={() => setTenantMenuVisible(true)}
                disabled={tenants.length === 0}
              >
                {tenants.find((tenant) => tenant.id === selectedTenantId)?.id ?? 'Seleccionar tenant'}
                {tenants.find((tenant) => tenant.id === selectedTenantId)
                  ? ` · ${tenants.find((tenant) => tenant.id === selectedTenantId)?.name}`
                  : ''}
              </Button>
            )}
          >
            {tenants.map((tenant) => (
              <Menu.Item
                key={tenant.id}
                title={`${tenant.id} · ${tenant.name}`}
                leadingIcon={tenant.id === selectedTenantId ? 'check' : undefined}
                onPress={() => {
                  setTenantMenuVisible(false);
                  void selectTenant(tenant.id);
                }}
              />
            ))}
          </Menu>
        </Surface>

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Consumo y costes</Text>
          <Text variant="bodyMedium" style={styles.muted}>
            Consulta las peticiones, tokens y coste estimado de los servicios AWS del tenant.
          </Text>
          <Button mode="outlined" icon="chart-line" onPress={onOpenUsage}>
            Ver consumo de servicios AWS
          </Button>
        </Surface>

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Campos del documento</Text>
          <Text variant="bodyMedium" style={styles.muted}>Estos son los campos que se validan y se preparan para el ERP de este tenant.</Text>
          <View style={styles.fieldList}>
            {fields.map((field) => (
              <View key={field.key} style={styles.fieldRow}>
                <View style={styles.fieldCopy}>
                  <Text variant="bodyMedium">{field.label}</Text>
                  <Text variant="bodySmall" style={styles.muted}>{field.key} · {field.type}{field.repeatable ? ' · repetible' : ''}</Text>
                </View>
                {field.required ? <Text variant="labelSmall" style={styles.required}>Obligatorio</Text> : null}
              </View>
            ))}
          </View>
          <View style={styles.inlineFields}>
            <TextInput label="Clave" value={fieldKey} onChangeText={setFieldKey} mode="outlined" placeholder="warehouse_code" style={styles.inlineInput} />
            <TextInput label="Etiqueta" value={fieldLabel} onChangeText={setFieldLabel} mode="outlined" placeholder="Código de almacén" style={styles.inlineInput} />
          </View>
          <View style={styles.actions}>
            <Button mode={fieldRequired ? 'contained' : 'outlined'} icon="asterisk" onPress={() => setFieldRequired((value) => !value)}>Obligatorio</Button>
            <Button mode="outlined" icon="plus" disabled={!fieldKey.trim() || !fieldLabel.trim()} onPress={addField}>Añadir campo</Button>
            <Button mode="contained" icon="content-save" loading={savingFields} disabled={savingFields} onPress={() => { void saveFields(); }}>Guardar campos</Button>
          </View>
        </Surface>

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Plantillas documentales</Text>
          <Text variant="bodyMedium" style={styles.muted}>Carga una plantilla por tipo de documento. El lector la usará como referencia visual y de campos para este tenant.</Text>
          {templates.map((template) => (
            <View key={template.id} style={styles.templateRow}>
              <View style={styles.templatePreview}>
                {template.url && /\.(jpe?g|png|webp|gif)$/i.test(template.filename)
                  ? <Image source={{ uri: template.url }} style={styles.templateImage} resizeMode="contain" />
                  : template.url && /\.pdf$/i.test(template.filename)
                    ? createElement('iframe', { title: `Vista previa ${template.filename}`, src: template.url, style: styles.templateFrame as CSSProperties })
                    : <MaterialCommunityIcons name="file-document-outline" size={40} color="#53657d" />}
              </View>
              <View style={styles.fieldCopy}>
                <Text variant="bodyMedium">{template.filename}</Text>
                <Text variant="bodySmall" style={styles.muted}>{TEMPLATE_OPTIONS.find((option) => option.value === template.document_type)?.label ?? template.document_type} · {template.scope}</Text>
              </View>
              <Text variant="labelSmall" style={styles.required}>Activa</Text>
            </View>
          ))}
          <View style={styles.optionGrid}>
            {TEMPLATE_OPTIONS.map((option) => (
              <Button
                key={option.value}
                mode={templateType === option.value ? 'contained' : 'outlined'}
                onPress={() => setTemplateType(option.value)}
                style={styles.optionButton}
              >
                {option.label}
              </Button>
            ))}
          </View>
          <Button mode="outlined" icon="file-upload-outline" loading={uploadingTemplate} disabled={uploadingTemplate} onPress={() => { void uploadTemplate(); }}>
            Cargar plantilla
          </Button>
        </Surface>

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Validaciones del pipeline</Text>
          <Text variant="bodyMedium" style={styles.muted}>Se aplican antes de enviar al ERP. Un desajuste queda en revisión humana.</Text>
          <View style={styles.inlineFields}>
            <TextInput label="Tolerancia cantidad (%)" value={quantityTolerance} onChangeText={setQuantityTolerance} keyboardType="decimal-pad" mode="outlined" style={styles.inlineInput} />
            <TextInput label="Tolerancia precio (%)" value={priceTolerance} onChangeText={setPriceTolerance} keyboardType="decimal-pad" mode="outlined" style={styles.inlineInput} />
            <TextInput label="Máximo de páginas" value={maxPages} onChangeText={setMaxPages} keyboardType="number-pad" mode="outlined" style={styles.inlineInput} />
          </View>
          <Button mode={batchEnabled ? 'contained' : 'outlined'} icon="layers-outline" onPress={() => setBatchEnabled((value) => !value)}>
            {batchEnabled ? 'Subida multipágina activa' : 'Activar subida multipágina'}
          </Button>
          <Button mode="contained" icon="content-save" loading={saving} disabled={saving} onPress={() => { void saveValidationRules(); }}>
            Guardar validaciones
          </Button>
        </Surface>

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Captura y operación móvil</Text>
          <Text variant="bodyMedium" style={styles.muted}>Estas preferencias se aplican solo al tenant seleccionado y no cambian las reglas del ERP.</Text>
          <Button mode={guidedCapture ? 'contained' : 'outlined'} icon="scan-helper" onPress={() => setGuidedCapture((value) => !value)}>
            {guidedCapture ? 'Captura guiada activa' : 'Activar captura guiada'}
          </Button>
          <Button mode={torchDefault ? 'contained' : 'outlined'} icon="flash-outline" onPress={() => setTorchDefault((value) => !value)}>
            {torchDefault ? 'Linterna inicial activa' : 'Activar linterna inicial'}
          </Button>
          <Button mode={offlineQueue ? 'contained' : 'outlined'} icon="cloud-sync-outline" onPress={() => setOfflineQueue((value) => !value)}>
            {offlineQueue ? 'Cola offline activa' : 'Activar cola offline'}
          </Button>
          <Button mode={rememberLastSelection ? 'contained' : 'outlined'} icon="history" onPress={() => setRememberLastSelection((value) => !value)}>
            {rememberLastSelection ? 'Recordar última selección' : 'No recordar selección'}
          </Button>
          <Button mode={burstEnabled ? 'contained' : 'outlined'} icon="camera-multiple-outline" onPress={() => setBurstEnabled((value) => !value)}>
            {burstEnabled ? 'Modo ráfaga activo' : 'Activar modo ráfaga'}
          </Button>
          <TextInput label="Umbral de confianza (0–1)" value={confidenceThreshold} onChangeText={setConfidenceThreshold} keyboardType="decimal-pad" mode="outlined" style={styles.input} />
          <Button mode="contained" icon="content-save" loading={saving} disabled={saving} onPress={() => { void saveCaptureConfiguration(); }}>
            Guardar captura
          </Button>
        </Surface>

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Crear tenant</Text>
          <Text variant="bodyMedium" style={styles.muted}>El tenant se crea activo y queda asignado a tu usuario administrador.</Text>
          <TextInput label="Identificador" value={tenantId} onChangeText={setTenantIdDraft} mode="outlined" placeholder="TEN-CLIENTE-001" style={styles.input} />
          <TextInput label="Nombre" value={tenantName} onChangeText={setTenantName} mode="outlined" placeholder="Cliente Demo S.L." style={styles.input} />
          <Button mode="outlined" icon="domain-plus" loading={creating} disabled={creating || !tenantId.trim() || !tenantName.trim()} onPress={() => { void addTenant(); }}>
            Crear tenant
          </Button>
        </Surface>

        <Surface style={[styles.card, styles.dangerCard]} elevation={1}>
          <Text variant="headlineSmall">Zona de pruebas</Text>
          <Text variant="bodyMedium" style={styles.muted}>
            Reinicia el tenant activo eliminando sus documentos, análisis e imágenes procesadas. La configuración, plantillas y consumo se mantienen.
          </Text>
          <Button
            mode="outlined"
            icon="delete-sweep-outline"
            textColor="#b42318"
            loading={resettingDocuments}
            disabled={resettingDocuments || !selectedTenantId}
            onPress={() => { void resetDocuments(); }}
          >
            Reiniciar documentos de prueba
          </Button>
        </Surface>

        <Surface style={styles.card} elevation={1}>
          <Text variant="headlineSmall">Conexión ERP</Text>
          <Text variant="bodyMedium" style={styles.muted}>Tenant activo: {selectedTenantId}</Text>
          <TextInput label="Proveedor" value={provider} onChangeText={setProvider} mode="outlined" style={styles.input} />
          <TextInput label="Endpoint base de la API" value={baseUrl} onChangeText={setBaseUrl} autoCapitalize="none" keyboardType="url" mode="outlined" style={styles.input} />
          <Text variant="labelLarge" style={styles.sectionLabel}>Autenticación</Text>
          <View style={styles.optionGrid}>
            {AUTH_OPTIONS.map((option) => (
              <Button
                key={option.value}
                mode={authType === option.value ? 'contained' : 'outlined'}
                onPress={() => setAuthType(option.value)}
                style={styles.optionButton}
              >
                {option.label}
              </Button>
            ))}
          </View>
          {authType !== 'none' ? <TextInput label="Usuario / Client ID" value={username} onChangeText={setUsername} autoCapitalize="none" mode="outlined" style={styles.input} /> : null}
          {authType !== 'none' ? <TextInput label={connection?.secret_configured ? 'Secreto (vacío = conservar el actual)' : 'Secreto / API key'} value={secret} onChangeText={setSecret} secureTextEntry mode="outlined" style={styles.input} /> : null}
          <Text variant="bodySmall" style={styles.muted}>
            Estado: {connection?.status === 'connected' ? 'conectado' : connection?.status === 'configured' || connection?.secret_configured ? 'configurado' : 'sin configurar'}
          </Text>
          <View style={styles.actions}>
            <Button mode="outlined" icon="connection" loading={testing} disabled={testing || !connection?.base_url} onPress={() => { void checkConnection(); }}>
              Probar conexión
            </Button>
            <Button mode="contained" icon="content-save" loading={saving} disabled={saving || !baseUrl.trim()} onPress={() => { void saveConnection(); }}>
              Guardar conexión
            </Button>
          </View>
        </Surface>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#f5f7fb' },
  header: { minHeight: 72, paddingHorizontal: 24, borderBottomWidth: 1, borderBottomColor: '#dce4ef', backgroundColor: '#ffffff', flexDirection: 'row', alignItems: 'center', gap: 16 },
  headerCopy: { flex: 1 },
  content: { width: '100%', maxWidth: 920, alignSelf: 'center', padding: 24, gap: 18 },
  card: { padding: 22, borderRadius: 16, backgroundColor: '#ffffff', gap: 12 },
  dangerCard: { borderWidth: 1, borderColor: '#efb0b0' },
  muted: { color: '#53657d' },
  tenantSelector: { alignSelf: 'stretch' },
  tenantSelectorContent: { justifyContent: 'space-between' },
  input: { backgroundColor: '#ffffff' },
  sectionLabel: { color: '#53657d', marginTop: 4 },
  optionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  optionButton: { marginRight: 4 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 4 },
  fieldList: { gap: 2 },
  fieldRow: { minHeight: 48, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#e5ebf3', flexDirection: 'row', alignItems: 'center', gap: 12 },
  templateRow: { minHeight: 170, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: '#e5ebf3', flexDirection: 'row', alignItems: 'center', gap: 14 },
  templatePreview: { width: 150, height: 150, borderRadius: 10, backgroundColor: '#eef2f7', overflow: 'hidden', alignItems: 'center', justifyContent: 'center' },
  templateImage: { width: '100%', height: '100%' },
  templateFrame: { width: '100%', height: '100%', borderWidth: 0, backgroundColor: '#ffffff' },
  fieldCopy: { flex: 1, gap: 2 },
  required: { color: '#1f7a54' },
  inlineFields: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  inlineInput: { flex: 1, minWidth: 240, backgroundColor: '#ffffff' },
});
