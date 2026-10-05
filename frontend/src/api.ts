import type { AuthIdentity, AuthSession, AwsUsageSummary, CaptureSettings, Customer, DeliveryNote, DeliveryNoteAnalysis, DeliveryNoteStatus, DocumentDirection, ErpConnection, IntakeDocumentType, IntakeRecord, ManualDocumentData, Order, Tenant, TenantDocumentConfig, TenantDocumentField, TenantTemplate } from './types';
import { loginWithCognito } from './cognito';

declare const process: { env: { EXPO_PUBLIC_BACKEND_API_URL?: string; EXPO_PUBLIC_AUTH_PROVIDER?: string } };

// Expo sustituye las referencias directas a EXPO_PUBLIC_* al crear el bundle.
// No usar una lectura dinamica de globalThis: en Android dejaria la URL localhost.
export const BACKEND_API_URL = (process.env.EXPO_PUBLIC_BACKEND_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
export const AUTH_PROVIDER = (process.env.EXPO_PUBLIC_AUTH_PROVIDER ?? 'local').toLowerCase();
let accessToken: string | null = null;
let activeTenantId: string | null = null;
let authExpiredHandler: (() => void) | null = null;

type Collection<T> = { data: T[] };

function normalizeInterpretation(
  value: Partial<IntakeRecord['interpretation']> | null | undefined,
): IntakeRecord['interpretation'] {
  const interpretation = value ?? {};
  return {
    rules_version: interpretation.rules_version ?? '',
    client_id: interpretation.client_id ?? '',
    requested_document_type: interpretation.requested_document_type ?? 'auto',
    document_type: interpretation.document_type ?? 'unknown',
    document_direction: interpretation.document_direction ?? 'unknown',
    order_kind: interpretation.order_kind ?? 'unknown',
    details: interpretation.details ?? {},
    document_number: interpretation.document_number ?? null,
    document_customer: interpretation.document_customer ?? { id: null, name: null, tax_id: null },
    selected_customer: interpretation.selected_customer ?? { id: '', name: null, tax_id: null },
    customer_match: interpretation.customer_match ?? { status: 'unknown', reason: '' },
    lines: Array.isArray(interpretation.lines) ? interpretation.lines : [],
    reasons: Array.isArray(interpretation.reasons) ? interpretation.reasons : [],
    missing_fields: Array.isArray(interpretation.missing_fields) ? interpretation.missing_fields : [],
    field_confidence: interpretation.field_confidence ?? {},
  };
}

function normalizeIntakeRecord(value: IntakeRecord): IntakeRecord {
  return {
    ...value,
    interpretation: normalizeInterpretation(value.interpretation),
    ocr: value.ocr ?? { status: 'unknown', text: '' },
    quality_report: value.quality_report
      ? {
          ...value.quality_report,
          reasons: Array.isArray(value.quality_report.reasons) ? value.quality_report.reasons : [],
          warnings: Array.isArray(value.quality_report.warnings) ? value.quality_report.warnings : [],
          blocking_reasons: Array.isArray(value.quality_report.blocking_reasons) ? value.quality_report.blocking_reasons : [],
        }
      : value.quality_report,
  };
}

function normalizeAnalysis(value: DeliveryNoteAnalysis): DeliveryNoteAnalysis {
  return {
    ...value,
    interpretation: normalizeInterpretation(value.interpretation),
    missing_fields: Array.isArray(value.missing_fields) ? value.missing_fields : [],
    ocr: value.ocr ?? { status: 'unknown', text: '' },
  };
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${BACKEND_API_URL}${path}`, {
    headers: {
      Accept: 'application/json',
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(activeTenantId ? { 'X-Tenant-Id': activeTenantId } : {}),
      ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
      ...options?.headers,
    },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      accessToken = null;
      activeTenantId = null;
      authExpiredHandler?.();
    }
    throw new ApiError(
      body.error ?? `Error del ERP (${response.status})`,
      response.status,
    );
  }
  return body as T;
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setTenantId(tenantId: string | null) {
  activeTenantId = tenantId;
}

export function setAuthExpiredHandler(handler: (() => void) | null) {
  authExpiredHandler = handler;
  return () => {
    if (authExpiredHandler === handler) authExpiredHandler = null;
  };
}

export async function login(email: string, password: string) {
  if (AUTH_PROVIDER === 'cognito') {
    const session = await loginWithCognito(email, password);
    // El token de sesión ya contiene el ID token que valida API Gateway.
    setAccessToken(session.access_token);
    setTenantId(session.user.tenant_id);
    // Refresca el rol/tenant desde el backend, que aplica el mapping server-side
    // USER#sub además de los claims del token.
    try {
      const currentUser = await getCurrentUser();
      return { ...session, user: currentUser.user };
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) throw cause;
      return session;
    }
  }
  const session = await request<AuthSession>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  setAccessToken(session.access_token);
  setTenantId(session.user.tenant_id);
  return session;
}

export async function getCurrentUser() {
  return request<{ user: AuthIdentity }>('/api/auth/me');
}

export async function getTenants() {
  return request<{ data: Tenant[] }>('/api/tenants');
}

export async function createTenant(payload: { id: string; name: string }) {
  return request<Tenant>('/api/tenants', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getErpConnection() {
  return request<ErpConnection>('/api/admin/erp-connection');
}

export async function saveErpConnection(payload: {
  provider: string;
  base_url: string;
  auth_type: string;
  username: string;
  secret: string;
}) {
  return request<ErpConnection>('/api/admin/erp-connection', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function testErpConnection() {
  return request<{ status: string; connection: ErpConnection; response: Record<string, unknown> }>(
    '/api/admin/erp-connection/test',
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export async function getTenantDocumentConfig() {
  return request<TenantDocumentConfig>('/api/admin/document-config');
}

export async function getCaptureSettings() {
  return request<{ tenant_id: string; capture_settings: CaptureSettings }>('/api/tenant/capture-settings');
}

export async function saveCaptureSettings(capture_settings: Partial<CaptureSettings>) {
  return request<{ capture_settings: CaptureSettings }>('/api/admin/document-config/capture-settings', {
    method: 'POST',
    body: JSON.stringify({ capture_settings }),
  });
}

export async function saveTenantDocumentFields(fields: TenantDocumentField[]) {
  return request<{ fields: TenantDocumentField[] }>('/api/admin/document-config/fields', {
    method: 'POST',
    body: JSON.stringify({ fields }),
  });
}

export async function saveTenantValidationRules(validation_rules: Record<string, unknown>) {
  return request<{ validation_rules: Record<string, unknown> }>('/api/admin/document-config/validation-rules', {
    method: 'POST',
    body: JSON.stringify({ validation_rules }),
  });
}

export async function uploadTenantTemplate(payload: {
  filename: string;
  content_base64: string;
  document_type: string;
}) {
  return request<TenantTemplate>('/api/admin/document-config/templates', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getDeliveryNotes(status?: DeliveryNoteStatus) {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  return request<Collection<DeliveryNote>>(`/api/v1/delivery-notes${query}`);
}

export async function getCustomers(query = '') {
  const search = query ? `?q=${encodeURIComponent(query)}` : '';
  return request<Collection<Customer>>(`/api/customers${search}`);
}

export async function getSuppliers(query = '') {
  const search = query ? `?q=${encodeURIComponent(query)}` : '';
  return request<Collection<Customer>>(`/api/suppliers${search}`);
}

export async function getIntakeRecords() {
  const response = await request<Collection<IntakeRecord>>('/api/intake/documents');
  return {
    ...response,
    data: Array.isArray(response.data) ? response.data.map(normalizeIntakeRecord) : [],
  };
}

export async function getAwsUsage() {
  return request<AwsUsageSummary>('/api/usage/aws');
}

export type IntakePayload = {
  client_id: string;
  client_email?: string;
  client_name?: string;
  client_tax_id?: string;
  document_type: IntakeDocumentType;
  document_direction?: DocumentDirection;
  filename: string;
  content_type: string;
  content_base64?: string;
  manual_data?: ManualDocumentData;
  pages?: { filename: string; content_type: string; content_base64: string }[];
};

export async function analyzeDeliveryNote(payload: IntakePayload) {
  const response = await request<DeliveryNoteAnalysis>('/api/intake/documents/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return normalizeAnalysis(response);
}

export async function submitDeliveryNote(payload: IntakePayload) {
  const response = await request<IntakeRecord>('/api/intake/documents', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return normalizeIntakeRecord(response);
}

export async function getOrders() {
  return request<Collection<Order>>('/api/v1/orders');
}

export async function createDeliveryNoteFromOrder(orderId: string) {
  return request<DeliveryNote>(`/api/v1/orders/${encodeURIComponent(orderId)}/delivery-note`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export async function transitionDeliveryNote(noteId: string, action: 'confirm' | 'deliver' | 'cancel') {
  return request<DeliveryNote>(`/api/v1/delivery-notes/${encodeURIComponent(noteId)}/${action}`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
}
