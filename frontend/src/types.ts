export type DeliveryNoteStatus = 'draft' | 'confirmed' | 'delivered' | 'cancelled';

export type DeliveryNoteLine = {
  sku: string;
  name: string;
  quantity: number;
  unit: string;
};

export type DeliveryNote = {
  id: string;
  order_id: string | null;
  customer_id: string;
  warehouse_id: string;
  status: DeliveryNoteStatus;
  lines: DeliveryNoteLine[];
  created_at: string;
  confirmed_at: string | null;
  delivered_at: string | null;
};

export type Order = {
  id: string;
  status: string;
  customer_id: string;
  warehouse_id: string;
  lines: { sku: string; quantity: number }[];
};

export type Customer = {
  id: string;
  name: string;
  tax_id: string;
  email: string;
};

export type AuthIdentity = {
  user_id: string;
  email: string;
  tenant_id: string;
  roles: string[];
  permissions: string[];
};

export type AuthSession = {
  access_token: string;
  token_type: 'Bearer';
  provider: 'local' | string;
  user: AuthIdentity;
};

export type Tenant = {
  id: string;
  name: string;
  status: string;
};

export type ErpConnection = {
  tenant_id: string;
  provider: 'mock_erp' | 'generic_rest' | string;
  base_url: string;
  auth_type: 'none' | 'api_key' | 'bearer' | 'basic' | 'oauth2_client_credentials' | string;
  username: string;
  secret_configured: boolean;
  status: string;
  last_checked_at: string | null;
  updated_at?: string | null;
};

export type TenantDocumentField = {
  key: string;
  label: string;
  type: string;
  required: boolean;
  source?: string;
  repeatable?: boolean;
  values?: string[];
};

export type TenantTemplate = {
  id: string;
  document_type: string;
  scope: string;
  filename: string;
  path?: string;
  uploaded_at?: string;
};

export type TenantDocumentConfig = {
  tenant_id: string;
  fields: TenantDocumentField[];
  templates: TenantTemplate[];
  validation_rules?: Record<string, unknown>;
  capture_settings?: CaptureSettings;
};

export type CaptureSettings = {
  guided_capture: boolean;
  quality_gate: boolean;
  torch_default: boolean;
  enable_multipage: boolean;
  enable_burst: boolean;
  max_pages_per_document: number;
  max_file_size_mb: number;
  remember_last_selection: boolean;
  offline_queue: boolean;
  confidence_threshold: number;
};

export type IntakeDocumentType = 'auto' | 'order' | 'delivery_note' | 'packing_list' | 'transport_document' | 'invoice' | 'deca';
export type DetectedDocumentType = 'unknown' | 'order' | 'delivery_note' | 'packing_list' | 'transport_document' | 'invoice' | 'deca';
export type DocumentDirection = 'auto' | 'inbound' | 'outbound';

export type ManualDocumentData = {
  document_type: Exclude<IntakeDocumentType, 'auto'>;
  document_number: string;
  document_direction: Exclude<DocumentDirection, 'auto'>;
  lines: { sku: string; quantity: number; unit_price?: number }[];
  order_kind?: 'purchase' | 'sales';
  details?: Record<string, string | number>;
};

export type AwsUsageMetrics = {
  requests: number;
  pages: number;
  input_tokens: number;
  output_tokens: number;
  state_transitions: number;
  messages: number;
  token_cost_eur?: number;
};

export type AwsUsageEvent = AwsUsageMetrics & {
  id: string;
  document_id: string;
  created_at: string;
  service: string;
  operation: string;
  mode: 'estimate' | 'observed';
};

export type AwsUsageSummary = {
  provider: string;
  aws_connected: boolean;
  cognito_excluded: boolean;
  notice: string;
  summary: {
    documents: number;
    actual: AwsUsageMetrics;
    estimated: AwsUsageMetrics;
    actual_token_cost_eur: number;
    estimated_token_cost_eur: number;
  };
  pricing?: {
    currency: string;
    model_id: string;
    usd_to_eur: number;
    input_usd_per_million: number;
    output_usd_per_million: number;
    basis: string;
  };
  services: ({ service: string } & AwsUsageMetrics)[];
  events: AwsUsageEvent[];
};

export type IntakeRecord = {
  id: string;
  created_at?: string;
  filename: string;
  client_id: string;
  client_email: string | null;
  document_type: DetectedDocumentType;
  document_direction: Exclude<DocumentDirection, 'auto'> | 'unknown';
  content_type: string;
  source_object_key: string;
  source_object_keys?: string[];
  pages_count?: number;
  content_fingerprint?: string | null;
  duplicate_check?: { status: string; kind?: string | null; existing_record_id?: string | null };
  cross_validation?: { status: string; reference?: string | null; reasons?: string[]; missing_fields?: string[] };
  native_reading?: { format: string; is_native: boolean; ocr_used: boolean; text_available: boolean; required?: boolean };
  evidence_url?: string;
  input_mode?: 'document' | 'manual';
  tenant_id?: string;
  connector?: string;
  quality_report?: {
    status: string;
    score: number;
    decision: string;
    metrics?: Record<string, string | number>;
    reasons?: string[];
    warnings?: string[];
    blocking_reasons?: string[];
    provider?: string;
  };
  status: 'accepted' | 'rejected' | 'erp_rejected' | 'sent_to_erp';
  ocr: { status: string; text: string };
  interpretation: {
    rules_version: string;
    client_id: string;
    requested_document_type: IntakeDocumentType;
    document_type: DetectedDocumentType;
    document_direction: Exclude<DocumentDirection, 'auto'> | 'unknown';
    order_kind: 'purchase' | 'sales' | 'unknown';
    details?: Record<string, string | number | null>;
    document_number: string | null;
    document_customer: { id: string | null; name: string | null; tax_id: string | null };
    selected_customer: { id: string; name: string | null; tax_id: string | null };
    customer_match: { status: 'matched' | 'mismatch' | 'unknown'; reason: string };
    lines: { sku: string; quantity: number; unit_price?: number }[];
    reasons: string[];
    missing_fields?: string[];
    field_confidence?: Record<string, number>;
  };
  erp?: { id: string; status: string; document_number: string };
  client_copy?: { status: string; object_key: string };
  email_delivery?: { status: string; provider: string; to?: string; subject?: string; attachment_object_key?: string };
};

export type DeliveryNoteAnalysis = {
  id: string;
  filename: string;
  client_id: string;
  client_email: string;
  document_direction: Exclude<DocumentDirection, 'auto'> | 'unknown';
  content_type: string;
  source_object_key: string;
  source_object_keys?: string[];
  pages_count?: number;
  duplicate_check?: { status: string; kind?: string | null; existing_record_id?: string | null };
  cross_validation?: { status: string; reference?: string | null; reasons?: string[]; missing_fields?: string[] };
  native_reading?: { format: string; is_native: boolean; ocr_used: boolean; text_available: boolean; required?: boolean };
  input_mode?: 'document' | 'manual';
  status: 'ready' | 'blocked';
  can_send: boolean;
  quality: 'good' | 'needs_review';
  quality_report?: IntakeRecord['quality_report'];
  missing_fields: string[];
  ocr: { status: string; text: string };
  interpretation: IntakeRecord['interpretation'];
  field_confidence?: Record<string, number>;
};
