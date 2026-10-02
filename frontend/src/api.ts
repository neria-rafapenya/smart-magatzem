import type { AuthIdentity, AuthSession, AwsUsageSummary, Customer, DeliveryNote, DeliveryNoteAnalysis, DeliveryNoteStatus, DocumentDirection, ErpConnection, IntakeDocumentType, IntakeRecord, ManualDocumentData, Order, Tenant, TenantDocumentConfig, TenantDocumentField, TenantTemplate } from './types';
import { loginWithCognito } from './cognito';

declare const process: { env: { EXPO_PUBLIC_BACKEND_API_URL?: string; EXPO_PUBLIC_AUTH_PROVIDER?: string } };

// Expo sustituye las referencias directas a EXPO_PUBLIC_* al crear el bundle.
// No usar una lectura dinamica de globalThis: en Android dejaria la URL localhost.
export const BACKEND_API_URL = (process.env.EXPO_PUBLIC_BACKEND_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
export const AUTH_PROVIDER = (process.env.EXPO_PUBLIC_AUTH_PROVIDER ?? 'local').toLowerCase();
let accessToken: string | null = null;
let activeTenantId: string | null = null;

type Collection<T> = { data: T[] };

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
    if (response.status === 401) accessToken = null;
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

export async function login(email: string, password: string) {
  if (AUTH_PROVIDER === 'cognito') {
    const session = await loginWithCognito(email, password);
    // Cognito autentica correctamente, pero las peticiones posteriores al API
    // necesitan reutilizar explícitamente el access token.
    setAccessToken(session.access_token);
    setTenantId(session.user.tenant_id);
    // Refresca el rol/tenant desde el backend, que aplica el mapping server-side
    // USER#sub además de los claims del token.
    try {
      const currentUser = await getCurrentUser();
      return { ...session, user: currentUser.user };
    } catch {
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
  return request<Collection<IntakeRecord>>('/api/intake/documents');
}

export async function getAwsUsage() {
  return request<AwsUsageSummary>('/api/usage/aws');
}

type IntakePayload = {
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
  return request<DeliveryNoteAnalysis>('/api/intake/documents/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function submitDeliveryNote(payload: IntakePayload) {
  return request<IntakeRecord>('/api/intake/documents', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
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
