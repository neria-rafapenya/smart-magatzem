import {
  Children,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import MaterialCommunityIcons from "@expo/vector-icons/MaterialCommunityIcons";
import {
  ActivityIndicator as NativeActivityIndicator,
  Image,
  Keyboard,
  KeyboardAvoidingView,
  Linking,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleProp,
  StyleSheet,
  TextInput as NativeTextInput,
  Text as NativeText,
  View,
  ViewStyle,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "react-native-paper";

import {
  ApiError,
  BACKEND_API_URL,
  analyzeDeliveryNote,
  getCaptureSettings,
  getCustomers,
  getIntakeRecords,
  getAwsUsage,
  getSuppliers,
  submitDeliveryNote,
} from "./api";
import { BrandLogo } from "./BrandLogo";
import { AdminSettingsScreen } from "./AdminSettingsScreen";
import {
  DocumentCropper,
  type CropRequest,
  type CropResult,
} from "./DocumentCropper";
import { croppedDocumentFilename } from "./documentCropUtils";
import { compressDocumentForUpload } from "./documentUploadUtils";
import { inspectLocalImageQuality, type LocalCaptureQuality } from "./localCaptureQuality";
import { enqueueSubmission, getOfflineQueue, markQueuedSubmissionAttempt, removeQueuedSubmission } from "./offlineQueue";
import type {
  AuthSession,
  AwsUsageEvent,
  AwsUsageSummary,
  CaptureSettings,
  Customer,
  DeliveryNoteAnalysis,
  DocumentDirection,
  IntakeDocumentType,
  IntakeRecord,
  ManualDocumentData,
} from "./types";
import { FeedbackNotice } from "./FeedbackNotice";

type SelectedDocument = {
  filename: string;
  content_type: string;
  content_base64: string;
  preview_uri?: string;
};

type PickedDocumentAsset = {
  uri: string;
  name: string;
  mimeType?: string;
  base64?: string;
};

const DEFAULT_CAPTURE_SETTINGS: CaptureSettings = {
  guided_capture: true,
  quality_gate: true,
  torch_default: false,
  enable_multipage: false,
  enable_burst: false,
  max_pages_per_document: 20,
  max_file_size_mb: 2,
  remember_last_selection: true,
  offline_queue: true,
  confidence_threshold: 0.85,
};

type LastSelection = {
  documentType: IntakeDocumentType | null;
  direction: DocumentDirection;
  customerId: string | null;
};

const lastSelectionKey = (tenantId: string) => `@smart-magatzem/last-selection/${tenantId}`;

type AppButtonProps = {
  children: ReactNode;
  disabled?: boolean;
  mode?: "contained" | "outlined" | "text";
  onPress: () => void;
  onPressIn?: () => void;
  contentStyle?: StyleProp<ViewStyle>;
};

function AppButton({
  children,
  disabled = false,
  mode = "contained",
  onPress,
  onPressIn,
  contentStyle,
}: AppButtonProps) {
  const labelColor = mode === "contained" ? "#ffffff" : "#1f5fbf";
  const childNodes = Children.toArray(children);
  const hasComponentChild = childNodes.some(
    (child) => typeof child !== "string" && typeof child !== "number",
  );
  const content = hasComponentChild ? (
    childNodes.map((child, index) =>
      typeof child === "string" || typeof child === "number" ? (
        <NativeText
          key={`label-${index}`}
          style={[styles.appButtonLabel, { color: labelColor }]}
        >
          {child}
        </NativeText>
      ) : (
        child
      ),
    )
  ) : (
    <NativeText style={[styles.appButtonLabel, { color: labelColor }]}>
      {children}
    </NativeText>
  );
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      onPressIn={onPressIn}
      style={({ pressed }) => [
        styles.appButton,
        mode === "contained" ? styles.appButtonContained : null,
        mode === "outlined" ? styles.appButtonOutlined : null,
        mode === "text" ? styles.appButtonText : null,
        disabled ? styles.appButtonDisabled : null,
        pressed && !disabled ? styles.appButtonPressed : null,
        contentStyle,
      ]}
    >
      <View style={styles.appButtonContent}>{content}</View>
    </Pressable>
  );
}

function AppIconButton({
  accessibilityLabel,
  disabled = false,
  icon,
  onPress,
  size = 24,
  style,
}: {
  accessibilityLabel: string;
  disabled?: boolean;
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  onPress: () => void;
  size?: number;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Pressable
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.appIconButton,
        pressed && !disabled ? styles.appButtonPressed : null,
        style,
      ]}
    >
      <MaterialCommunityIcons
        name={icon}
        size={size}
        color={disabled ? "#9aa6b2" : "#53657d"}
      />
    </Pressable>
  );
}

function AppChip({
  children,
  textStyle,
}: {
  children: ReactNode;
  textStyle?: StyleProp<any>;
}) {
  return (
    <View style={styles.appChip}>
      <NativeText style={[styles.appChipText, textStyle]}>
        {children}
      </NativeText>
    </View>
  );
}

function DocumentTypeButton({
  icon,
  label,
  selected,
  onPress,
  style,
}: {
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  label: string;
  selected: boolean;
  onPress: () => void;
  style?: StyleProp<ViewStyle>;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [
        styles.documentTypeButton,
        style,
        selected ? styles.documentTypeButtonSelected : null,
        pressed ? styles.appButtonPressed : null,
      ]}
    >
      <MaterialCommunityIcons
        name={icon}
        size={36}
        color={selected ? "#1f5fbf" : "#53657d"}
      />
      <NativeText
        style={[
          styles.documentTypeButtonLabel,
          selected ? styles.documentTypeButtonLabelSelected : null,
        ]}
      >
        {label}
      </NativeText>
    </Pressable>
  );
}

function DocumentTypePicker({
  value,
  onChange,
}: {
  value: IntakeDocumentType | null;
  onChange: (type: IntakeDocumentType) => void;
}) {
  return (
    <View style={styles.documentTypeOptions}>
      <DocumentTypeButton
        icon="auto-fix"
        label="Automático"
        selected={value === "auto"}
        onPress={() => onChange("auto")}
      />
      <DocumentTypeButton
        icon="clipboard-text-outline"
        label="Pedido"
        selected={value === "order"}
        onPress={() => onChange("order")}
      />
      <DocumentTypeButton
        icon="truck-delivery-outline"
        label="Albarán"
        selected={value === "delivery_note"}
        onPress={() => onChange("delivery_note")}
      />
      <DocumentTypeButton
        icon="package-variant-closed"
        label="Packing list"
        selected={value === "packing_list"}
        onPress={() => onChange("packing_list")}
      />
      <DocumentTypeButton
        icon="truck-outline"
        label="Transporte"
        selected={value === "transport_document"}
        onPress={() => onChange("transport_document")}
      />
      <DocumentTypeButton
        icon="file-document-outline"
        label="Factura"
        selected={value === "invoice"}
        onPress={() => onChange("invoice")}
      />
      <DocumentTypeButton
        icon="file-certificate-outline"
        label="DeCA"
        selected={value === "deca"}
        onPress={() => onChange("deca")}
      />
    </View>
  );
}

type ManualDocumentDraft = {
  document_type: Exclude<IntakeDocumentType, "auto">;
  document_number: string;
  document_direction: Exclude<DocumentDirection, "auto"> | "";
  order_kind: "purchase" | "sales";
  lines: { sku: string; quantity: string }[];
  packages_count: string;
  weight_kg: string;
  dimensions: string;
  carrier: string;
  vehicle_plate: string;
  pickup: string;
  delivery_window: string;
};

const MANUAL_DOCUMENT_TYPES: Exclude<IntakeDocumentType, "auto">[] = [
  "order",
  "delivery_note",
  "packing_list",
  "transport_document",
  "invoice",
  "deca",
];

function ManualDocumentTypePicker({
  value,
  onChange,
}: {
  value: Exclude<IntakeDocumentType, "auto">;
  onChange: (type: Exclude<IntakeDocumentType, "auto">) => void;
}) {
  return (
    <View style={styles.documentTypeOptions}>
      {MANUAL_DOCUMENT_TYPES.map((type) => (
        <DocumentTypeButton
          key={type}
          icon={
            type === "order"
              ? "clipboard-text-outline"
              : type === "delivery_note"
                ? "truck-delivery-outline"
                : type === "packing_list"
                  ? "package-variant-closed"
                  : type === "transport_document"
                    ? "truck-outline"
                    : "file-document-outline"
          }
          label={DOCUMENT_TYPE_LABELS[type]}
          selected={value === type}
          onPress={() => onChange(type)}
        />
      ))}
    </View>
  );
}

function DocumentDirectionPicker({
  value,
  onChange,
}: {
  value: DocumentDirection;
  onChange: (direction: DocumentDirection) => void;
}) {
  return (
    <View style={styles.directionOptions}>
      <DocumentTypeButton
        style={styles.directionButton}
        icon="auto-fix"
        label="Detectar"
        selected={value === "auto"}
        onPress={() => onChange("auto")}
      />
      <DocumentTypeButton
        style={styles.directionButton}
        icon="login-variant"
        label="Entrada"
        selected={value === "inbound"}
        onPress={() => onChange("inbound")}
      />
      <DocumentTypeButton
        style={styles.directionButton}
        icon="logout-variant"
        label="Salida"
        selected={value === "outbound"}
        onPress={() => onChange("outbound")}
      />
    </View>
  );
}

function ManualEntryForm({
  draft,
  selectedCustomer,
  onChange,
}: {
  draft: ManualDocumentDraft;
  selectedCustomer: Customer | null;
  onChange: (next: ManualDocumentDraft) => void;
}) {
  const update = <K extends keyof ManualDocumentDraft>(
    key: K,
    value: ManualDocumentDraft[K],
  ) => {
    onChange({ ...draft, [key]: value });
  };
  const updateLine = (
    index: number,
    key: "sku" | "quantity",
    value: string,
  ) => {
    const lines = draft.lines.map((line, lineIndex) =>
      lineIndex === index ? { ...line, [key]: value } : line,
    );
    onChange({ ...draft, lines });
  };
  const removeLine = (index: number) => {
    const lines = draft.lines.filter((_, lineIndex) => lineIndex !== index);
    onChange({
      ...draft,
      lines: lines.length > 0 ? lines : [{ sku: "", quantity: "" }],
    });
  };

  return (
    <View style={styles.manualForm}>
      <View style={styles.manualFormHeader}>
        <MaterialCommunityIcons name="form-textbox" size={22} color="#1f5fbf" />
        <View style={styles.manualFormHeaderCopy}>
          <Text variant="titleMedium">Introducir datos manualmente</Text>
          <Text variant="bodySmall" style={styles.panelSubtitle}>
            Confirma los campos que no se han podido leer.
          </Text>
        </View>
      </View>
      <Text variant="bodySmall" style={styles.manualWarning}>
        Conservamos los datos aceptados por la lectura y dejamos vacíos los que
        necesitan confirmación. Compruébalos antes de continuar.
      </Text>
      {selectedCustomer ? (
        <View style={styles.manualConfirmedBox}>
          <MaterialCommunityIcons name="check-circle-outline" size={20} color="#1c7c54" />
          <View style={styles.manualConfirmedCopy}>
            <Text variant="labelMedium" style={styles.manualConfirmedLabel}>Cliente conservado</Text>
            <Text variant="bodySmall">{selectedCustomer.id} · {selectedCustomer.name}</Text>
          </View>
        </View>
      ) : null}
      <Text variant="labelLarge" style={styles.fieldLabel}>
        Tipo confirmado
      </Text>
      <ManualDocumentTypePicker
        value={draft.document_type}
        onChange={(value) => update("document_type", value)}
      />
      <Text variant="labelLarge" style={styles.fieldLabel}>
        Número del documento *
      </Text>
      <NativeTextInput
        style={styles.nativeInput}
        value={draft.document_number}
        onChangeText={(value) => update("document_number", value)}
        placeholder="Ej. ALB-2026-0042"
        placeholderTextColor="#718096"
      />
      <Text variant="labelLarge" style={styles.fieldLabel}>
        Dirección *
      </Text>
      <DocumentDirectionPicker
        value={draft.document_direction || "auto"}
        onChange={(value) =>
          update("document_direction", value === "auto" ? "" : value)
        }
      />
      {draft.document_type === "order" ? (
        <>
          <Text variant="labelLarge" style={styles.fieldLabel}>
            Pedido de compra o venta
          </Text>
          <View style={styles.manualChoiceRow}>
            <DocumentTypeButton
              style={styles.manualChoiceButton}
              icon="cart-arrow-down"
              label="Compra"
              selected={draft.order_kind === "purchase"}
              onPress={() => update("order_kind", "purchase")}
            />
            <DocumentTypeButton
              style={styles.manualChoiceButton}
              icon="cart-arrow-up"
              label="Venta"
              selected={draft.order_kind === "sales"}
              onPress={() => update("order_kind", "sales")}
            />
          </View>
        </>
      ) : null}
      <View style={styles.manualLinesHeader}>
        <Text variant="labelLarge" style={styles.fieldLabel}>
          Líneas *
        </Text>
        <AppButton
          mode="text"
          onPress={() =>
            onChange({
              ...draft,
              lines: [...draft.lines, { sku: "", quantity: "" }],
            })
          }
        >
          <MaterialCommunityIcons name="plus" size={18} color="#1f5fbf" />
          Añadir línea
        </AppButton>
      </View>
      {draft.lines.map((line, index) => (
        <View key={`manual-line-${index}`} style={styles.manualLineRow}>
          <NativeTextInput
            style={[styles.nativeInput, styles.manualSkuInput]}
            value={line.sku}
            onChangeText={(value) => updateLine(index, "sku", value)}
            placeholder="SKU / referencia"
            placeholderTextColor="#718096"
          />
          <NativeTextInput
            style={[styles.nativeInput, styles.manualQuantityInput]}
            value={line.quantity}
            onChangeText={(value) => updateLine(index, "quantity", value)}
            placeholder="Cantidad"
            placeholderTextColor="#718096"
            keyboardType="decimal-pad"
          />
          <AppIconButton
            icon="close"
            size={20}
            onPress={() => removeLine(index)}
            accessibilityLabel="Eliminar línea"
          />
        </View>
      ))}
      {draft.document_type === "packing_list" ? (
        <View style={styles.manualDetailsBox}>
          <Text variant="labelLarge">Datos del embalaje (opcionales)</Text>
          <View style={styles.manualTwoColumns}>
            <NativeTextInput
              style={[styles.nativeInput, styles.manualHalfInput]}
              value={draft.packages_count}
              onChangeText={(value) => update("packages_count", value)}
              placeholder="Bultos"
              placeholderTextColor="#718096"
              keyboardType="number-pad"
            />
            <NativeTextInput
              style={[styles.nativeInput, styles.manualHalfInput]}
              value={draft.weight_kg}
              onChangeText={(value) => update("weight_kg", value)}
              placeholder="Peso kg"
              placeholderTextColor="#718096"
              keyboardType="decimal-pad"
            />
          </View>
          <NativeTextInput
            style={styles.nativeInput}
            value={draft.dimensions}
            onChangeText={(value) => update("dimensions", value)}
            placeholder="Dimensiones"
            placeholderTextColor="#718096"
          />
        </View>
      ) : null}
      {draft.document_type === "transport_document" ? (
        <View style={styles.manualDetailsBox}>
          <Text variant="labelLarge">Datos del transporte (opcionales)</Text>
          <NativeTextInput
            style={styles.nativeInput}
            value={draft.carrier}
            onChangeText={(value) => update("carrier", value)}
            placeholder="Transportista"
            placeholderTextColor="#718096"
          />
          <View style={styles.manualTwoColumns}>
            <NativeTextInput
              style={[styles.nativeInput, styles.manualHalfInput]}
              value={draft.vehicle_plate}
              onChangeText={(value) => update("vehicle_plate", value)}
              placeholder="Matrícula"
              placeholderTextColor="#718096"
            />
            <NativeTextInput
              style={[styles.nativeInput, styles.manualHalfInput]}
              value={draft.pickup}
              onChangeText={(value) => update("pickup", value)}
              placeholder="Pickup / recogida"
              placeholderTextColor="#718096"
            />
          </View>
          <NativeTextInput
            style={styles.nativeInput}
            value={draft.delivery_window}
            onChangeText={(value) => update("delivery_window", value)}
            placeholder="Ventana horaria"
            placeholderTextColor="#718096"
          />
        </View>
      ) : null}
    </View>
  );
}

function DocumentSourceButton({
  disabled = false,
  icon,
  label,
  loading = false,
  onPress,
  primary = false,
}: {
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  label: string;
  disabled?: boolean;
  loading?: boolean;
  onPress: () => void;
  primary?: boolean;
}) {
  const color = primary ? "#ffffff" : "#53657d";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.documentSourceButton,
        primary ? styles.documentSourceButtonPrimary : null,
        disabled ? styles.appButtonDisabled : null,
        pressed && !disabled ? styles.appButtonPressed : null,
      ]}
    >
      {loading ? (
        <NativeActivityIndicator size="small" color={color} />
      ) : (
        <MaterialCommunityIcons name={icon} size={36} color={color} />
      )}
      <NativeText
        style={[
          styles.documentSourceButtonLabel,
          primary ? styles.documentSourceButtonLabelPrimary : null,
        ]}
      >
        {label}
      </NativeText>
    </Pressable>
  );
}

function PanelHeader({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <View style={styles.panelHeader}>
      <Text variant="titleMedium">{title}</Text>
      {subtitle ? (
        <Text variant="bodySmall" style={styles.panelSubtitle}>
          {subtitle}
        </Text>
      ) : null}
    </View>
  );
}

const MAX_CUSTOMERS = 25;
const MIN_CUSTOMER_SEARCH_CHARS = 3;
const INITIAL_LOADING_MIN_MS = 800;

function normalizeSearch(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

const STATUS_LABELS: Record<IntakeRecord["status"], string> = {
  accepted: "Pendiente de envío",
  rejected: "Rechazado por reglas",
  erp_rejected: "Rechazado por ERP",
  sent_to_erp: "Enviado al ERP",
};

const STATUS_COLORS: Record<IntakeRecord["status"], string> = {
  accepted: "#8a5b00",
  rejected: "#a43d3d",
  erp_rejected: "#a43d3d",
  sent_to_erp: "#1c7c54",
};

const DOCUMENT_TYPE_LABELS: Record<
  | "auto"
  | "unknown"
  | "order"
  | "delivery_note"
  | "packing_list"
  | "transport_document"
  | "invoice"
  | "deca",
  string
> = {
  auto: "Automático",
  unknown: "No identificado",
  order: "Pedido",
  delivery_note: "Albarán",
  packing_list: "Packing list",
  transport_document: "Transporte",
  invoice: "Factura",
  deca: "DeCA",
};

const DOCUMENT_DIRECTION_LABELS: Record<
  "inbound" | "outbound" | "unknown",
  string
> = {
  inbound: "Entrada",
  outbound: "Salida",
  unknown: "No identificada",
};

function humanizeQualityReason(reason: string) {
  const normalized = reason.toLowerCase();
  if (normalized.includes("lector ia") || normalized.includes("bedrock"))
    return "El lector IA de AWS no está disponible temporalmente.";
  if (normalized.includes("borrosa") || normalized.includes("desenfocada"))
    return "La imagen está borrosa o desenfocada.";
  if (normalized.includes("ilumin"))
    return "La iluminación no permite leer bien el documento.";
  if (normalized.includes("sombra"))
    return "Hay sombras que dificultan la lectura.";
  if (normalized.includes("resolución") || normalized.includes("resolucion"))
    return "La imagen tiene poca resolución.";
  if (normalized.includes("contraste")) return "El contraste es insuficiente.";
  return (
    reason.charAt(0).toUpperCase() + reason.slice(1).replace(/\.$/, "") + "."
  );
}

function getAnalysisIssues(analysis: DeliveryNoteAnalysis) {
  const issues: string[] = [];
  const qualityReport = analysis.quality_report;
  const qualityReasons = qualityReport?.reasons ?? [];
  const isDuplicate = analysis.duplicate_check?.status === "duplicate";
  if (isDuplicate) {
    const existingId = analysis.duplicate_check?.existing_record_id;
    issues.push(
      existingId
        ? `Este documento ya se ha procesado anteriormente (${existingId}).`
        : "Este documento ya se ha procesado anteriormente.",
    );
  }
  const qualityNeedsReview =
    qualityReport?.decision === "review" ||
    ["needs_review", "unavailable", "unreadable"].includes(
      qualityReport?.status ?? "",
    );
  if (qualityNeedsReview && !isDuplicate) {
    issues.push(
      ...(qualityReasons.length > 0
        ? qualityReasons.map(humanizeQualityReason)
        : ["La calidad de la imagen es insuficiente."]),
    );
  }
  if (analysis.interpretation.document_type === "unknown")
    issues.push("No se ha identificado el tipo de documento.");
  if (!analysis.interpretation.document_number)
    issues.push("No se ha leído el número del documento.");
  if (analysis.interpretation.lines.length === 0)
    issues.push("No se han leído líneas de producto.");
  if (analysis.interpretation.customer_match.status === "mismatch")
    issues.push("El cliente del documento no coincide con el seleccionado.");
  if (analysis.interpretation.customer_match.status === "unknown")
    issues.push("No se ha podido verificar el cliente del documento.");
  const directionConflict = analysis.interpretation.reasons.some((reason) => {
    const normalized = reason.toLowerCase();
    return (
      normalized.includes("dirección") &&
      normalized.includes("manuscrita") &&
      normalized.includes("impresa")
    );
  });
  if (directionConflict)
    issues.push("La dirección manuscrita y la impresa no coinciden.");
  else if (analysis.interpretation.document_direction === "unknown")
    issues.push("No se ha identificado si es entrada o salida.");
  if (analysis.missing_fields.some((field) => field.includes("correo")))
    issues.push("Falta un correo válido para enviar la copia.");
  return [...new Set(issues)];
}

function isAwsVisionUnavailable(analysis: DeliveryNoteAnalysis) {
  return (analysis.quality_report?.reasons ?? []).some((reason) => {
    const normalized = reason.toLowerCase();
    return (
      normalized.includes("lector ia") ||
      normalized.includes("bedrock") ||
      normalized.includes("aws")
    );
  });
}

function createManualDraft(
  documentType: IntakeDocumentType,
  documentDirection: DocumentDirection,
  analysis: DeliveryNoteAnalysis | null,
): ManualDocumentDraft {
  const detectedType = analysis?.interpretation.document_type;
  const type =
    documentType !== "auto"
      ? documentType
      : MANUAL_DOCUMENT_TYPES.includes(
            detectedType as Exclude<IntakeDocumentType, "auto">,
          )
        ? (detectedType as Exclude<IntakeDocumentType, "auto">)
        : "delivery_note";
  const detectedDirection = analysis?.interpretation.document_direction;
  const direction =
    documentDirection !== "auto"
      ? documentDirection
      : detectedDirection === "inbound" || detectedDirection === "outbound"
        ? detectedDirection
        : "";
  const detailValue = (key: string) => {
    const value = analysis?.interpretation.details?.[key];
    return value === undefined || value === null ? "" : String(value);
  };
  return {
    document_type: type,
    document_number: analysis?.interpretation.document_number ?? "",
    document_direction: direction,
    order_kind:
      analysis?.interpretation.order_kind === "purchase" ? "purchase" : "sales",
    lines: analysis?.interpretation.lines.length
      ? analysis.interpretation.lines.map((line) => ({
          sku: line.sku,
          quantity: String(line.quantity),
        }))
      : [{ sku: "", quantity: "" }],
    packages_count: detailValue("packages_count"),
    weight_kg: detailValue("weight_kg"),
    dimensions: detailValue("dimensions"),
    carrier: detailValue("carrier"),
    vehicle_plate: detailValue("vehicle_plate"),
    pickup: detailValue("pickup"),
    delivery_window: detailValue("delivery_window"),
  };
}

function evidenceExtension(filename: string) {
  const extension = filename.split(".").pop()?.trim().toLowerCase();
  return extension ? extension.toUpperCase() : "DOC";
}

function evidenceIcon(
  contentType: string,
  filename: string,
): keyof typeof MaterialCommunityIcons.glyphMap {
  const extension = filename.split(".").pop()?.trim().toLowerCase();
  if (contentType === "application/pdf" || extension === "pdf")
    return "file-pdf-box";
  if (
    contentType.includes("spreadsheet") ||
    ["xls", "xlsx", "csv"].includes(extension ?? "")
  )
    return "file-excel-box";
  if (contentType.includes("word") || ["doc", "docx"].includes(extension ?? ""))
    return "file-word-box";
  if (
    contentType.includes("presentation") ||
    ["ppt", "pptx"].includes(extension ?? "")
  )
    return "file-powerpoint-box";
  if (
    contentType.startsWith("text/") ||
    ["txt", "json", "xml"].includes(extension ?? "")
  )
    return "file-document-outline";
  return "file-outline";
}

function EvidencePreview({
  contentType,
  filename,
  uri,
}: {
  contentType: string;
  filename: string;
  uri: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const isImage =
    contentType.startsWith("image/") ||
    /\.(gif|jpe?g|png|webp|heic|bmp)$/i.test(filename);

  if (isImage) {
    return (
      <>
        <Pressable
          accessibilityLabel="Ampliar imagen de la evidencia"
          accessibilityRole="button"
          onPress={() => setExpanded(true)}
          style={styles.evidenceImageButton}
        >
          <Image
            source={{ uri }}
            style={styles.evidencePreview}
            resizeMode="contain"
            accessibilityLabel="Miniatura de la evidencia"
          />
          <View style={styles.evidenceHint}>
            <MaterialCommunityIcons
              name="magnify-plus-outline"
              size={18}
              color="#1f5fbf"
            />
            <NativeText style={styles.evidenceHintText}>
              Tocar para ampliar
            </NativeText>
          </View>
        </Pressable>
        <Modal
          visible={expanded}
          transparent
          animationType="fade"
          onRequestClose={() => setExpanded(false)}
        >
          <View style={styles.evidenceModal}>
            <Pressable
              accessibilityLabel="Cerrar vista ampliada"
              accessibilityRole="button"
              onPress={() => setExpanded(false)}
              style={styles.evidenceModalBackdrop}
            />
            <Image
              source={{ uri }}
              style={styles.evidenceExpanded}
              resizeMode="contain"
              accessibilityLabel="Evidencia ampliada"
            />
            <Pressable
              accessibilityLabel="Cerrar vista ampliada"
              accessibilityRole="button"
              onPress={() => setExpanded(false)}
              style={styles.evidenceModalClose}
            >
              <MaterialCommunityIcons name="close" size={30} color="#ffffff" />
            </Pressable>
          </View>
        </Modal>
      </>
    );
  }

  return (
    <Pressable
      accessibilityLabel={`Abrir documento ${filename}`}
      accessibilityRole="button"
      onPress={() => {
        void Linking.openURL(uri);
      }}
      style={({ pressed }) => [
        styles.evidenceDocument,
        pressed ? styles.appButtonPressed : null,
      ]}
    >
      <MaterialCommunityIcons
        name={evidenceIcon(contentType, filename)}
        size={42}
        color="#c34444"
      />
      <View style={styles.evidenceDocumentCopy}>
        <NativeText style={styles.evidenceDocumentExtension}>
          {evidenceExtension(filename)}
        </NativeText>
        <NativeText style={styles.evidenceDocumentName} numberOfLines={2}>
          {filename}
        </NativeText>
        <NativeText style={styles.evidenceDocumentAction}>
          Tocar para abrir
        </NativeText>
      </View>
      <MaterialCommunityIcons name="open-in-new" size={22} color="#1f5fbf" />
    </Pressable>
  );
}

function usageServiceIcon(
  service: string,
): keyof typeof MaterialCommunityIcons.glyphMap {
  if (service === "S3") return "database-outline";
  if (service === "Bedrock") return "brain";
  if (service === "Textract") return "text-box-search-outline";
  if (service === "Step Functions") return "transit-connection-variant";
  if (service === "SES") return "email-outline";
  return "cloud-outline";
}

function usageMetricSummary(metrics: AwsUsageSummary["summary"]["estimated"]) {
  const parts = [`${metrics.requests} peticiones`];
  if (metrics.pages) parts.push(`${metrics.pages} páginas`);
  if (metrics.input_tokens || metrics.output_tokens)
    parts.push(`${metrics.input_tokens + metrics.output_tokens} tokens`);
  if (metrics.token_cost_eur)
    parts.push(`${formatEur(metrics.token_cost_eur)} en tokens`);
  if (metrics.state_transitions)
    parts.push(`${metrics.state_transitions} transiciones`);
  if (metrics.messages) parts.push(`${metrics.messages} mensajes`);
  return parts.join(" · ");
}

function formatEur(value: number | undefined): string {
  const amount = Number(value ?? 0);
  if (amount === 0) return "0,00 €";
  if (Math.abs(amount) < 0.0001) return "<0,0001 €";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(amount);
}

function formatUsageEvent(event: AwsUsageEvent) {
  const metrics = usageMetricSummary(event);
  return `${event.service} · ${event.operation} · ${metrics}`;
}

function ProcessedDocumentsScreen({
  records,
  refreshing,
  onBack,
  onRefresh,
  onOpenUsage,
  onLogout,
}: {
  records: IntakeRecord[];
  refreshing: boolean;
  onBack: () => void;
  onRefresh: () => void;
  onOpenUsage: () => void;
  onLogout: () => void;
}) {
  const insets = useSafeAreaInsets();
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyFilter, setHistoryFilter] = useState<"all" | "today" | "pending" | "error">("all");
  const visibleRecords = useMemo(() => {
    const query = normalizeSearch(historyQuery.trim());
    const today = new Date().toISOString().slice(0, 10);
    return records.filter((record) => {
      const searchable = normalizeSearch(`${record.id} ${record.filename} ${record.client_id} ${record.interpretation.document_number ?? ""}`);
      if (query && !searchable.includes(query)) return false;
      if (historyFilter === "today" && !String(record.created_at ?? "").startsWith(today)) return false;
      if (historyFilter === "pending" && ["sent_to_erp", "erp_rejected", "rejected"].includes(record.status)) return false;
      if (historyFilter === "error" && !["erp_rejected", "rejected"].includes(record.status)) return false;
      return true;
    });
  }, [historyFilter, historyQuery, records]);
  return (
    <View style={styles.root}>
      <View
        style={[
          styles.appbar,
          { paddingTop: insets.top, minHeight: 64 + insets.top },
        ]}
      >
        <AppIconButton
          icon="arrow-left"
          onPress={onBack}
          accessibilityLabel="Volver"
        />
        <View style={styles.appbarCopy}>
          <Text variant="titleLarge">Documentos procesados</Text>
          <Text variant="bodySmall" style={styles.appbarSubtitle}>
            ERP y comunicaciones al cliente
          </Text>
        </View>
        <AppIconButton
          icon="refresh"
          onPress={onRefresh}
          accessibilityLabel="Actualizar documentos"
        />
        <AppIconButton
          icon="logout"
          onPress={onLogout}
          accessibilityLabel="Cerrar sesión"
        />
      </View>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingBottom: insets.bottom + 32 },
        ]}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      >
        <View style={styles.hero}>
          <Text variant="headlineSmall">Historial de documentos</Text>
          <Text variant="bodyMedium" style={styles.muted}>
            Consulta la interpretación, el envío al ERP y el estado del correo
            simulado al cliente.
          </Text>
          <AppButton mode="outlined" onPress={onOpenUsage}>
            <MaterialCommunityIcons
              name="chart-line"
              size={18}
              color="#1f5fbf"
            />
            Ver consumo de servicios AWS
          </AppButton>
          <NativeTextInput
            style={styles.historySearch}
            value={historyQuery}
            onChangeText={setHistoryQuery}
            placeholder="Buscar por número, cliente o archivo"
            placeholderTextColor="#718096"
          />
          <View style={styles.historyFilters}>
            {([
              ["all", "Todos"],
              ["today", "Hoy"],
              ["pending", "Pendientes"],
              ["error", "Con error"],
            ] as const).map(([value, label]) => (
              <AppButton key={value} mode={historyFilter === value ? "contained" : "outlined"} onPress={() => setHistoryFilter(value)}>
                {label}
              </AppButton>
            ))}
          </View>
        </View>
        {records.length === 0 ? (
          <View style={styles.card}>
            <View style={styles.cardContent}>
              <Text variant="bodyMedium" style={styles.muted}>
                Todavía no hay documentos procesados.
              </Text>
            </View>
          </View>
        ) : visibleRecords.length === 0 ? (
          <View style={styles.card}><View style={styles.cardContent}><Text variant="bodyMedium" style={styles.muted}>No hay documentos que coincidan con el filtro.</Text></View></View>
        ) : (
          visibleRecords.map((record) => {
            const detectedType =
              record.interpretation.document_type ??
              record.document_type ??
              "unknown";
            const emailStatus = record.email_delivery?.status;
            const evidenceUrl =
              record.evidence_url ??
              `${BACKEND_API_URL}/api/intake/documents/${encodeURIComponent(record.id)}/document`;
            return (
              <View key={record.id} style={styles.card}>
                <View style={styles.recordHeader}>
                  <View style={styles.recordHeaderCopy}>
                    <Text variant="titleMedium">{record.id}</Text>
                    <Text variant="bodySmall" style={styles.panelSubtitle}>
                      {record.filename} · {record.client_id}
                    </Text>
                  </View>
                  <AppChip textStyle={{ color: STATUS_COLORS[record.status] }}>
                    {STATUS_LABELS[record.status]}
                  </AppChip>
                </View>
                <View style={styles.cardContent}>
                  <Text variant="bodyMedium">
                    Documento:{" "}
                    {record.interpretation.document_number ?? "no identificado"}
                  </Text>
                  <Text variant="bodySmall" style={styles.panelSubtitle}>
                    Tipo: {DOCUMENT_TYPE_LABELS[detectedType]}
                  </Text>
                  <Text variant="bodySmall" style={styles.panelSubtitle}>
                    Dirección:{" "}
                    {
                      DOCUMENT_DIRECTION_LABELS[
                        record.document_direction ?? "unknown"
                      ]
                    }
                  </Text>
                  <Text variant="bodySmall" style={styles.panelSubtitle}>
                    Cliente: {record.client_email ?? "correo no configurado"}
                  </Text>
                  {record.input_mode === "manual" ? (
                    <Text variant="bodySmall" style={styles.manualHistoryLabel}>
                      Datos confirmados manualmente
                    </Text>
                  ) : null}
                  <EvidencePreview
                    contentType={record.content_type ?? ""}
                    filename={record.filename}
                    uri={evidenceUrl}
                  />
                  <View style={styles.resultSection}>
                    <Text variant="labelLarge">Interpretación</Text>
                    {record.interpretation.lines.length > 0 ? (
                      record.interpretation.lines.map((line) => (
                        <Text
                          key={`${line.sku}-${line.quantity}`}
                          variant="bodySmall"
                          style={styles.interpretedLine}
                        >
                          {line.sku} · cantidad: {line.quantity}
                        </Text>
                      ))
                    ) : (
                      <Text variant="bodySmall" style={styles.panelSubtitle}>
                        No se han interpretado líneas.
                      </Text>
                    )}
                  </View>
                  {record.erp ? (
                    <Text variant="bodySmall" style={styles.successText}>
                      ERP: {record.erp.id} · recibido correctamente
                    </Text>
                  ) : null}
                  {record.email_delivery ? (
                    <Text
                      variant="bodySmall"
                      style={
                        emailStatus === "simulated"
                          ? styles.successText
                          : styles.errorText
                      }
                    >
                      Correo:{" "}
                      {emailStatus === "simulated"
                        ? `simulado para ${record.email_delivery.to}`
                        : emailStatus}
                    </Text>
                  ) : null}
                  {record.interpretation.reasons.length > 0 ? (
                    <Text variant="bodySmall" style={styles.errorText}>
                      {record.interpretation.reasons.join(" · ")}
                    </Text>
                  ) : null}
                </View>
                <View style={styles.divider} />
              </View>
            );
          })
        )}
      </ScrollView>
    </View>
  );
}

function UsageScreen({
  onBack,
  onLogout,
}: {
  onBack: () => void;
  onLogout: () => void;
}) {
  const insets = useSafeAreaInsets();
  const [usage, setUsage] = useState<AwsUsageSummary | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const loadUsage = useCallback(async () => {
    try {
      const response = await getAwsUsage();
      setUsage(response);
      setError("");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoadingUsage(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const bootstrapUsage = async () => {
      if (!active) return;
      await loadUsage();
    };
    void bootstrapUsage();
    return () => {
      active = false;
    };
  }, [loadUsage]);

  const refreshUsage = async () => {
    setRefreshing(true);
    await loadUsage();
    setRefreshing(false);
  };

  if (loadingUsage) {
    return (
      <View style={styles.loadingRoot}>
        <NativeActivityIndicator size="large" color="#1f5fbf" />
        <Text variant="titleLarge" style={styles.loadingTitle}>
          Cargando consumo
        </Text>
      </View>
    );
  }

  const estimated = usage?.summary.estimated;
  const actual = usage?.summary.actual;
  return (
    <View style={styles.root}>
      <View
        style={[
          styles.appbar,
          { paddingTop: insets.top, minHeight: 64 + insets.top },
        ]}
      >
        <AppIconButton
          icon="arrow-left"
          onPress={onBack}
          accessibilityLabel="Volver"
        />
        <View style={styles.appbarCopy}>
          <Text variant="titleLarge">Consumo AWS</Text>
          <Text variant="bodySmall" style={styles.appbarSubtitle}>
            Telemetría del pipeline documental
          </Text>
        </View>
        <AppIconButton
          icon="refresh"
          onPress={refreshUsage}
          accessibilityLabel="Actualizar consumo"
        />
        <AppIconButton
          icon="logout"
          onPress={onLogout}
          accessibilityLabel="Cerrar sesión"
        />
      </View>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingBottom: insets.bottom + 32 },
        ]}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refreshUsage} />
        }
      >
        {error ? (
          <View style={[styles.card, styles.errorCard]}>
            <View style={styles.cardContent}>
              <Text variant="bodyMedium">{error}</Text>
            </View>
          </View>
        ) : null}
        <View style={styles.hero}>
          <Text variant="headlineSmall">Consumo aproximado</Text>
          <Text variant="bodyMedium" style={styles.muted}>
            {usage?.notice ?? "No hay datos de consumo disponibles."}
          </Text>
          <View style={styles.usageExclusion}>
            <MaterialCommunityIcons
              name="shield-check-outline"
              size={20}
              color="#1c7c54"
            />
            <Text variant="bodySmall" style={styles.successText}>
              Cognito no se incluye en este cálculo.
            </Text>
          </View>
        </View>
        <View style={styles.usageSummaryGrid}>
          <View style={[styles.card, styles.usageSummaryCard]}>
            <Text variant="labelLarge">Peticiones reales</Text>
            <Text variant="headlineMedium" style={styles.usageNumber}>
              {actual?.requests ?? 0}
            </Text>
            <Text variant="bodySmall" style={styles.muted}>
              Tokens: {formatEur(usage?.summary.actual_token_cost_eur)}
            </Text>
            <Text variant="bodySmall" style={styles.muted}>
              AWS conectado
            </Text>
          </View>
          <View style={[styles.card, styles.usageSummaryCard]}>
            <Text variant="labelLarge">Estimación equivalente</Text>
            <Text variant="headlineMedium" style={styles.usageNumber}>
              {estimated?.requests ?? 0}
            </Text>
            <Text variant="bodySmall" style={styles.muted}>
              Tokens: {formatEur(usage?.summary.estimated_token_cost_eur)}
            </Text>
            <Text variant="bodySmall" style={styles.muted}>
              {estimated ? usageMetricSummary(estimated) : "Sin datos"}
            </Text>
          </View>
        </View>
        <View style={styles.card}>
          <View style={styles.cardContent}>
            <Text variant="titleMedium">Acumulado del flujo</Text>
            <Text variant="bodySmall" style={styles.panelSubtitle}>
              {estimated?.pages ?? 0} páginas ·{" "}
              {(estimated?.input_tokens ?? 0) + (estimated?.output_tokens ?? 0)}{" "}
              tokens estimados · {estimated?.state_transitions ?? 0}{" "}
              transiciones · {estimated?.messages ?? 0} mensajes
            </Text>
            <Text variant="bodySmall" style={styles.successText}>
              Coste aproximado de tokens:{" "}
              {formatEur(usage?.summary.estimated_token_cost_eur)}
            </Text>
          </View>
        </View>
        <View style={styles.usageSectionHeading}>
          <Text variant="titleMedium">Por servicio</Text>
          <AppChip textStyle={{ color: "#53657d" }}>
            {usage?.summary.documents ?? 0} documentos
          </AppChip>
        </View>
        {(usage?.services ?? []).map((service) => (
          <View key={service.service} style={styles.card}>
            <View style={styles.usageServiceRow}>
              <MaterialCommunityIcons
                name={usageServiceIcon(service.service)}
                size={28}
                color="#1f5fbf"
              />
              <View style={styles.usageServiceCopy}>
                <Text variant="titleMedium">{service.service}</Text>
                <Text variant="bodySmall" style={styles.panelSubtitle}>
                  {usageMetricSummary(service)}
                </Text>
              </View>
              <AppChip>{service.requests} req.</AppChip>
            </View>
          </View>
        ))}
        <View style={styles.usageSectionHeading}>
          <Text variant="titleMedium">Detalle de peticiones estimadas</Text>
        </View>
        {(usage?.events ?? []).length === 0 ? (
          <View style={styles.card}>
            <View style={styles.cardContent}>
              <Text variant="bodySmall" style={styles.muted}>
                Todavía no hay documentos procesados.
              </Text>
            </View>
          </View>
        ) : (
          (usage?.events ?? []).map((event) => (
            <View key={event.id} style={styles.card}>
              <View style={styles.usageEventRow}>
                <MaterialCommunityIcons
                  name={usageServiceIcon(event.service)}
                  size={22}
                  color="#53657d"
                />
                <View style={styles.usageServiceCopy}>
                  <Text variant="bodyMedium">
                    {event.service} · {event.operation}
                  </Text>
                  <Text variant="bodySmall" style={styles.panelSubtitle}>
                    {event.document_id} · {formatUsageEvent(event)}
                  </Text>
                </View>
                <AppChip textStyle={{ color: "#8a5b00" }}>estimada</AppChip>
              </View>
            </View>
          ))
        )}
      </ScrollView>
    </View>
  );
}

export function InboundDeliveryScreen({
  session,
  onLogout,
}: {
  session: AuthSession;
  onLogout: () => void;
}) {
  const insets = useSafeAreaInsets();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [suppliers, setSuppliers] = useState<Customer[]>([]);
  const [records, setRecords] = useState<IntakeRecord[]>([]);
  const [customerQuery, setCustomerQuery] = useState("");
  const [customerInputFocused, setCustomerInputFocused] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(
    null,
  );
  const [documentType, setDocumentType] = useState<IntakeDocumentType | null>(
    null,
  );
  const [documentDirection, setDocumentDirection] =
    useState<DocumentDirection>("auto");
  const [activeScreen, setActiveScreen] = useState<
    "intake" | "processed" | "usage" | "admin"
  >("intake");
  const [document, setDocument] = useState<SelectedDocument | null>(null);
  const [documentPages, setDocumentPages] = useState<SelectedDocument[]>([]);
  const [captureSettings, setCaptureSettings] = useState<CaptureSettings>(DEFAULT_CAPTURE_SETTINGS);
  const [localQuality, setLocalQuality] = useState<LocalCaptureQuality | null>(null);
  const [cropRequest, setCropRequest] = useState<CropRequest | null>(null);
  const [pendingCropAssets, setPendingCropAssets] = useState<PickedDocumentAsset[]>([]);
  const [analysis, setAnalysis] = useState<DeliveryNoteAnalysis | null>(null);
  const analysisIsDuplicate = analysis?.duplicate_check?.status === "duplicate";
  const [manualMode, setManualMode] = useState(false);
  const [manualDraft, setManualDraft] = useState<ManualDocumentDraft>(() =>
    createManualDraft("delivery_note", "auto", null),
  );
  const [manualData, setManualData] = useState<ManualDocumentData | null>(null);
  const [showAnalysisDetails, setShowAnalysisDetails] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [cameraCountdown, setCameraCountdown] = useState<number | null>(null);
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [captureAppend, setCaptureAppend] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState("");
  const [successNotice, setSuccessNotice] = useState(false);
  const [closeManualAfterSuccess, setCloseManualAfterSuccess] = useState(false);
  const [error, setError] = useState("");
  const [dataLoadError, setDataLoadError] = useState("");
  const [queueNotice, setQueueNotice] = useState("");
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);
  const wizardScrollRef = useRef<ScrollView>(null);
  const selectionRestoredRef = useRef(false);
  const queueDrainedRef = useRef(false);

  const filteredCustomers = useMemo(() => {
    const query = normalizeSearch(customerQuery.trim());
    if (query.length > 0 && query.length < MIN_CUSTOMER_SEARCH_CHARS) return [];
    const counterparties =
      documentDirection === "inbound"
        ? suppliers
        : documentDirection === "outbound"
          ? customers
          : [...customers, ...suppliers];
    return counterparties
      .filter(
        (customer) =>
          !query ||
          normalizeSearch(`${customer.id} ${customer.name}`).includes(query),
      )
      .slice(0, MAX_CUSTOMERS);
  }, [customerQuery, customers, documentDirection, suppliers]);

  const showCustomerSuggestions = Boolean(
    !selectedCustomer &&
    customerInputFocused &&
    (customerQuery.trim().length === 0 ||
      customerQuery.trim().length >= MIN_CUSTOMER_SEARCH_CHARS),
  );

  const clearCustomer = () => {
    setSelectedCustomer(null);
    setCustomerQuery("");
    setCustomerInputFocused(true);
    setDocument(null);
    setDocumentPages([]);
    setLocalQuality(null);
    setAnalysis(null);
    setManualMode(false);
    setManualData(null);
  };

  const chooseDocumentType = (type: IntakeDocumentType) => {
    setDocumentType(type);
    setAnalysis(null);
    setManualMode(false);
    setManualData(null);
    setSuccessNotice(false);
    setError("");
    if (captureSettings.remember_last_selection) {
      void AsyncStorage.setItem(lastSelectionKey(session.user.tenant_id), JSON.stringify({ documentType: type, direction: documentDirection, customerId: selectedCustomer?.id ?? null } satisfies LastSelection));
    }
  };

  const chooseDocumentDirection = (direction: DocumentDirection) => {
    setDocumentDirection(direction);
    setSelectedCustomer(null);
    setCustomerQuery("");
    setDocument(null);
    setDocumentPages([]);
    setLocalQuality(null);
    setAnalysis(null);
    setManualMode(false);
    setManualData(null);
    if (captureSettings.remember_last_selection) {
      void AsyncStorage.setItem(lastSelectionKey(session.user.tenant_id), JSON.stringify({ documentType, direction, customerId: null } satisfies LastSelection));
    }
  };

  const loadData = useCallback(async () => {
    const [customerResponse, supplierResponse, intakeResponse, settingsResponse] =
      await Promise.all([getCustomers(), getSuppliers(), getIntakeRecords(), getCaptureSettings()]);
    setCustomers(customerResponse.data.slice(0, MAX_CUSTOMERS));
    setSuppliers(supplierResponse.data.slice(0, MAX_CUSTOMERS));
    setRecords(intakeResponse.data);
    setCaptureSettings({ ...DEFAULT_CAPTURE_SETTINGS, ...settingsResponse.capture_settings });
  }, []);

  const drainOfflineQueue = useCallback(async () => {
    if (queueDrainedRef.current || !captureSettings.offline_queue) return;
    queueDrainedRef.current = true;
    const queue = await getOfflineQueue(session.user.tenant_id);
    if (!queue.length) return;
    setQueueNotice(`Reintentando ${queue.length} documento${queue.length === 1 ? "" : "s"} guardado${queue.length === 1 ? "" : "s"} sin conexión…`);
    for (const item of queue) {
      try {
        const record = await submitDeliveryNote(item.payload);
        await removeQueuedSubmission(session.user.tenant_id, item.id);
        setRecords((current) => [record, ...current]);
      } catch {
        await markQueuedSubmissionAttempt(session.user.tenant_id, item.id);
        break;
      }
    }
    setQueueNotice("");
  }, [captureSettings.offline_queue, session.user.tenant_id]);

  const handleLoadError = useCallback(
    (cause: unknown) => {
      if (cause instanceof ApiError && cause.status === 401) {
        onLogout();
        return;
      }
      setDataLoadError("No se han podido actualizar los datos. Inténtalo de nuevo.");
    },
    [onLogout],
  );

  useEffect(() => {
    if (selectionRestoredRef.current || !captureSettings.remember_last_selection || (!customers.length && !suppliers.length)) return;
    selectionRestoredRef.current = true;
    void AsyncStorage.getItem(lastSelectionKey(session.user.tenant_id)).then((stored) => {
      if (!stored) return;
      try {
        const value = JSON.parse(stored) as LastSelection;
        if (value.documentType) setDocumentType(value.documentType);
        if (value.direction) setDocumentDirection(value.direction);
        const counterparties = value.direction === "inbound" ? suppliers : value.direction === "outbound" ? customers : [...customers, ...suppliers];
        const customer = counterparties.find((item) => item.id === value.customerId);
        if (customer) setSelectedCustomer(customer);
      } catch {
        // Una preferencia corrupta no debe impedir el uso del wizard.
      }
    });
  }, [captureSettings.remember_last_selection, customers, session.user.tenant_id, suppliers]);

  useEffect(() => {
    let active = true;
    let finishTimer: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();
    const bootstrap = async () => {
      try {
        await loadData();
      } catch (cause) {
        if (active) handleLoadError(cause);
      } finally {
        const remaining = Math.max(
          0,
          INITIAL_LOADING_MIN_MS - (Date.now() - startedAt),
        );
        const finish = () => {
          if (active) setLoading(false);
        };
        if (remaining > 0) {
          finishTimer = setTimeout(finish, remaining);
        } else {
          finish();
        }
      }
    };
    void bootstrap();
    return () => {
      active = false;
      if (finishTimer) clearTimeout(finishTimer);
    };
  }, [handleLoadError, loadData]);

  useEffect(() => {
    if (!loading) void drainOfflineQueue();
  }, [drainOfflineQueue, loading]);

  useEffect(() => {
    if (!message) return undefined;
    const timeout = setTimeout(() => setMessage(""), 5000);
    return () => clearTimeout(timeout);
  }, [message]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await loadData();
      setError("");
      setDataLoadError("");
    } catch (cause) {
      handleLoadError(cause);
    } finally {
      setRefreshing(false);
    }
  };

  const resetAfterDocumentSelection = () => {
    setAnalysis(null);
    setManualMode(false);
    setManualData(null);
    setSuccessNotice(false);
  };

  const setSelectedDocument = async (next: SelectedDocument, append = false) => {
    if (append && documentPages.length >= captureSettings.max_pages_per_document) {
      setError(`El documento no puede superar ${captureSettings.max_pages_per_document} hojas.`);
      return;
    }
    if (append) {
      setDocumentPages((current) => [...current, next]);
    } else {
      setDocumentPages([next]);
    }
    setDocument(next);
    setLocalQuality(next.preview_uri ? await inspectLocalImageQuality(next.preview_uri) : null);
    resetAfterDocumentSelection();
  };

  const addDocumentPage = () => {
    setQueueNotice("");
    setError("");
    void chooseDocumentFile(true);
  };

  const chooseDocumentFile = async (append = false) => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["image/*", "application/pdf", "text/plain"],
      copyToCacheDirectory: true,
      base64: true,
      multiple: captureSettings.enable_multipage,
    });
    if (result.canceled) return;
    const assets = result.assets as PickedDocumentAsset[];
    if (captureSettings.enable_multipage && assets.length > 1) {
      if (assets.some((asset) => !(asset.mimeType ?? "").startsWith("image/"))) {
        setError("La selección múltiple solo admite imágenes. Añade los PDF individualmente.");
        return;
      }
      const [first, ...remaining] = assets;
      setPendingCropAssets(remaining);
      setCropRequest({
        uri: first.uri,
        filename: first.name,
        content_type: first.mimeType ?? "image/jpeg",
        append,
      });
      setQueueNotice(`Se han seleccionado ${assets.length} imágenes. Recortaremos cada hoja antes de añadirla.`);
      return;
    }
    const asset = assets[0];
    const contentType = asset.mimeType ?? "application/octet-stream";
    if (Platform.OS === "web" && contentType.startsWith("image/")) {
      setCropRequest({
        uri: asset.uri,
        filename: asset.name,
        content_type: contentType,
        append,
      });
      if (append) setQueueNotice("Selecciona el recorte de la nueva hoja para añadirla al documento.");
    } else {
      await setSelectedDocument({
        filename: asset.name,
        content_type: contentType,
        content_base64: asset.base64 ?? "",
        preview_uri: contentType.startsWith("image/") ? asset.uri : undefined,
      }, append);
    }
    if (!append) resetAfterDocumentSelection();
  };

  const chooseMobileImage = async (append = false) => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [3, 4],
      base64: true,
      quality: 0.9,
    });
    if (result.canceled) return;
    const asset = result.assets[0];
    if (!asset.base64) {
      throw new Error("No se ha podido preparar la imagen recortada.");
    }
    await setSelectedDocument({
      filename: croppedDocumentFilename(),
      content_type: "image/jpeg",
      content_base64: asset.base64,
      preview_uri: asset.uri,
    }, append);
  };

  const choosePdfFile = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: ["application/pdf", "text/plain"],
      copyToCacheDirectory: true,
      base64: true,
    });
    if (result.canceled) return;
    const asset = result.assets[0];
    await setSelectedDocument({
      filename: asset.name,
      content_type: asset.mimeType ?? "application/octet-stream",
      content_base64: asset.base64 ?? "",
    });
  };

  const openCamera = async (append = false) => {
    setCaptureAppend(append);
    try {
      const permission = cameraPermission?.granted
        ? cameraPermission
        : await requestCameraPermission();
      if (!permission.granted) {
        setError(
          "Necesitamos permiso de cámara para capturar el documento. Revisa los permisos del navegador o del móvil.",
        );
        return;
      }
      setError("");
      setCameraReady(false);
      setCameraCountdown(5);
      setTorchEnabled(captureSettings.torch_default);
      setCameraOpen(true);
    } catch (cause) {
      setError((cause as Error).message);
    }
  };

  const closeCamera = useCallback(() => {
    setCameraOpen(false);
    setCameraReady(false);
    setCameraCountdown(null);
    setTorchEnabled(false);
    setCaptureAppend(false);
  }, []);

  const capturePhoto = useCallback(async () => {
    if (!cameraRef.current || !cameraReady) {
      setError("La cámara todavía no está preparada.");
      return;
    }
    setCapturing(true);
    setError("");
    try {
      const picture = await cameraRef.current.takePictureAsync({
        base64: true,
        imageType: "jpg",
        quality: 0.8,
      });
      if (!picture?.base64) {
        throw new Error("No se ha podido obtener la imagen de la cámara.");
      }
      setCropRequest({
        uri: picture.uri,
        filename: `albaran-${Date.now()}.jpg`,
        content_type: "image/jpeg",
        append: captureAppend,
      });
      setAnalysis(null);
      setManualMode(false);
      setManualData(null);
      setSuccessNotice(false);
      closeCamera();
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setCapturing(false);
    }
  }, [cameraReady, captureAppend, closeCamera]);

  useEffect(() => {
    if (!cameraOpen || !cameraReady) return undefined;
    const countdownTimer = setInterval(() => {
      setCameraCountdown((current) =>
        current && current > 1 ? current - 1 : 0,
      );
    }, 1000);
    const captureTimer = setTimeout(() => {
      void capturePhoto();
    }, 5000);
    return () => {
      clearInterval(countdownTimer);
      clearTimeout(captureTimer);
    };
  }, [cameraOpen, cameraReady, capturePhoto]);

  const completeCrop = async (result: CropResult) => {
    const next = {
      filename: result.filename,
      content_type: result.content_type,
      content_base64: result.base64,
      preview_uri: result.uri,
    };
    await setSelectedDocument(next, Boolean(cropRequest?.append));
    const [nextAsset, ...remaining] = pendingCropAssets;
    if (nextAsset) {
      setPendingCropAssets(remaining);
      setCropRequest({
        uri: nextAsset.uri,
        filename: nextAsset.name,
        content_type: nextAsset.mimeType ?? "image/jpeg",
        append: true,
      });
      setQueueNotice(remaining.length > 0 ? `Quedan ${remaining.length} hojas por recortar.` : "Última hoja: confirma el recorte para continuar.");
      return;
    }
    setPendingCropAssets([]);
    setCropRequest(null);
    setAnalysis(null);
    setManualMode(false);
    setManualData(null);
    setSuccessNotice(false);
  };

  const cancelCrop = () => {
    setPendingCropAssets([]);
    setCropRequest(null);
    setError(
      "Se ha descartado la imagen. Captura o selecciona otra para continuar.",
    );
  };

  const buildManualData = (): ManualDocumentData | null => {
    const documentNumber = manualDraft.document_number.trim();
    if (!documentNumber) {
      setError("Introduce el número del documento.");
      return null;
    }
    if (!manualDraft.document_direction) {
      setError("Selecciona si el documento es de entrada o de salida.");
      return null;
    }
    const lines = manualDraft.lines.flatMap((line) => {
      const sku = line.sku.trim();
      const quantity = Number(line.quantity.replace(",", "."));
      return sku && Number.isFinite(quantity) && quantity > 0
        ? [{ sku, quantity }]
        : [];
    });
    if (lines.length === 0) {
      setError("Añade al menos una línea con referencia y cantidad.");
      return null;
    }
    const details: Record<string, string | number> = {};
    const numericDetails: ["packages_count" | "weight_kg", string][] = [
      ["packages_count", "packages_count"],
      ["weight_kg", "weight_kg"],
    ];
    numericDetails.forEach(([draftKey, detailKey]) => {
      const value = manualDraft[draftKey].trim();
      if (value) {
        const number = Number(value.replace(",", "."));
        if (Number.isFinite(number) && number > 0) details[detailKey] = number;
      }
    });
    const textDetails: [
      "dimensions" | "carrier" | "vehicle_plate" | "pickup" | "delivery_window",
      string,
    ][] = [
      ["dimensions", "dimensions"],
      ["carrier", "carrier"],
      ["vehicle_plate", "vehicle_plate"],
      ["pickup", "pickup"],
      ["delivery_window", "delivery_window"],
    ];
    textDetails.forEach(([draftKey, detailKey]) => {
      const value = manualDraft[draftKey].trim();
      if (value) details[detailKey] = value;
    });
    return {
      document_type: manualDraft.document_type,
      document_number: documentNumber,
      document_direction: manualDraft.document_direction,
      order_kind: manualDraft.order_kind,
      lines,
      details,
    };
  };

  const analyzeWithManualData = async (
    manualOverride: ManualDocumentData | null = null,
  ) => {
    if (!documentType) {
      setError("Selecciona el tipo de documento.");
      return;
    }
    if (!selectedCustomer) {
      setError("Selecciona el cliente del documento.");
      return;
    }
    if (!document) {
      setError("Captura o selecciona un documento antes de analizarlo.");
      return;
    }
    setAnalyzing(true);
    setError("");
    setSuccessNotice(false);
    setCloseManualAfterSuccess(false);
    setShowAnalysisDetails(false);
    try {
      const result = await analyzeDeliveryNote({
        client_id: selectedCustomer.id,
        client_email: selectedCustomer.email,
        client_name: selectedCustomer.name,
        client_tax_id: selectedCustomer.tax_id,
        document_type: documentType,
        document_direction: documentDirection,
        filename: document.filename,
        content_type: document.content_type,
        content_base64: document.content_base64,
        ...(manualOverride ? { manual_data: manualOverride } : {}),
        ...(documentPages.length > 1
          ? {
              pages: documentPages.map((page) => ({
                filename: page.filename,
                content_type: page.content_type,
                content_base64: page.content_base64,
              })),
            }
          : {}),
      });
      setAnalysis(result);
      setManualData(manualOverride);
      setCloseManualAfterSuccess(Boolean(manualOverride && result.can_send));
      setMessage(
        result.can_send
          ? "Interpretación correcta. El documento puede enviarse al pipeline."
          : "Interpretación incompleta. Revisa los campos indicados.",
      );
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setAnalyzing(false);
    }
  };

  const analyzeDocument = async () => {
    setManualMode(false);
    await analyzeWithManualData();
  };

  const openManualEntry = () => {
    setManualDraft(
      createManualDraft(
        documentType ?? "delivery_note",
        documentDirection,
        analysis,
      ),
    );
    setManualData(null);
    setManualMode(true);
    setError("");
    setTimeout(
      () => wizardScrollRef.current?.scrollToEnd({ animated: true }),
      220,
    );
  };

  const analyzeManualDocument = async () => {
    const data = buildManualData();
    if (!data) return;
    await analyzeWithManualData(data);
  };

  const finishManualReview = useCallback(() => {
    setManualMode(false);
    setCloseManualAfterSuccess(false);
  }, []);

  const sendToPipeline = async () => {
    if (!documentType) {
      setError("Selecciona el tipo de documento.");
      return;
    }
    if (!selectedCustomer) {
      setError("Selecciona el cliente del documento.");
      return;
    }
    if (!analysis?.can_send) {
      setError(
        "Analiza el documento y corrige los campos indicados antes de enviarlo al pipeline.",
      );
      return;
    }
    if (manualMode && !manualData) {
      setError("Revisa de nuevo los datos introducidos manualmente.");
      return;
    }
    if (!document) {
      setError("Captura o selecciona un documento antes de enviarlo.");
      return;
    }
    setSending(true);
    setError("");
    try {
      const uploadDocument = await compressDocumentForUpload(document);
      const submissionPayload = {
        client_id: selectedCustomer.id,
        client_email: selectedCustomer.email,
        client_name: selectedCustomer.name,
        client_tax_id: selectedCustomer.tax_id,
        document_type: documentType,
        document_direction: documentDirection,
        filename: uploadDocument.filename,
        content_type: uploadDocument.content_type,
        content_base64: uploadDocument.content_base64,
        ...(manualData ? { manual_data: manualData } : {}),
        ...(documentPages.length > 1
          ? {
              pages: await Promise.all(
                documentPages.map(async (page) => {
                  const compressed = await compressDocumentForUpload(page);
                  return {
                    filename: compressed.filename,
                    content_type: compressed.content_type,
                    content_base64: compressed.content_base64,
                  };
                }),
              ),
            }
          : {}),
      };
      const record = await submitDeliveryNote(submissionPayload);
      setRecords((current) => [record, ...current]);
      if (record.status === "sent_to_erp") {
        setMessage("");
        setSuccessNotice(true);
      } else {
        setMessage("Documento recibido para revisión.");
        setSuccessNotice(false);
      }
      setDocument(null);
      setDocumentPages([]);
      setLocalQuality(null);
      setCropRequest(null);
      setAnalysis(null);
      setManualMode(false);
      setManualData(null);
    } catch (cause) {
      const isConnectivityError = !(cause instanceof ApiError) || (cause instanceof ApiError && cause.status >= 500);
      if (captureSettings.offline_queue && isConnectivityError && selectedCustomer && document) {
        try {
          const uploadDocument = await compressDocumentForUpload(document);
          const queuedPayload = {
            client_id: selectedCustomer.id,
            client_email: selectedCustomer.email,
            client_name: selectedCustomer.name,
            client_tax_id: selectedCustomer.tax_id,
            document_type: documentType,
            document_direction: documentDirection,
            filename: uploadDocument.filename,
            content_type: uploadDocument.content_type,
            content_base64: uploadDocument.content_base64,
            ...(manualData ? { manual_data: manualData } : {}),
            ...(documentPages.length > 1 ? {
              pages: await Promise.all(documentPages.map(async (page) => {
                const compressed = await compressDocumentForUpload(page);
                return { filename: compressed.filename, content_type: compressed.content_type, content_base64: compressed.content_base64 };
              })),
            } : {}),
          };
          await enqueueSubmission(session.user.tenant_id, queuedPayload);
          setQueueNotice("Documento guardado en la cola local. Se enviará automáticamente cuando vuelva la conexión.");
          setError("");
          setDocument(null);
          setDocumentPages([]);
          setAnalysis(null);
          setManualMode(false);
          setManualData(null);
        } catch (queueError) {
          setError((queueError as Error).message);
        }
      } else {
        setError((cause as Error).message);
      }
    } finally {
      setSending(false);
    }
  };

  const resetWizard = () => {
    setActiveScreen("intake");
    setDocumentType(null);
    setDocumentDirection("auto");
    setSelectedCustomer(null);
    setCustomerQuery("");
    setCustomerInputFocused(false);
    setDocument(null);
    setCropRequest(null);
    setAnalysis(null);
    setManualMode(false);
    setManualData(null);
    setCameraOpen(false);
    setCameraReady(false);
    setCameraCountdown(null);
    setSuccessNotice(false);
    setMessage("");
    setError("");
  };

  const startNextDocument = () => {
    setSuccessNotice(false);
    setMessage("");
    setError("");
    setDocument(null);
    setDocumentPages([]);
    setLocalQuality(null);
    setAnalysis(null);
    setManualMode(false);
    setManualData(null);
    setTimeout(() => wizardScrollRef.current?.scrollTo({ y: 0, animated: true }), 80);
  };

  if (loading) {
    return (
      <View style={styles.loadingRoot}>
        <NativeActivityIndicator size="large" color="#1f5fbf" />
        <Text variant="titleLarge" style={styles.loadingTitle}>
          Smart Magatzem
        </Text>
        <Text variant="bodyMedium" style={styles.loadingText}>
          Cargando recepción de documentos…
        </Text>
      </View>
    );
  }

  if (activeScreen === "processed") {
    return (
      <ProcessedDocumentsScreen
        records={records}
        refreshing={refreshing}
        onBack={resetWizard}
        onRefresh={refresh}
        onOpenUsage={() => setActiveScreen("usage")}
        onLogout={onLogout}
      />
    );
  }

  if (activeScreen === "usage") {
    return (
      <UsageScreen
        onBack={() => setActiveScreen("processed")}
        onLogout={onLogout}
      />
    );
  }

  if (activeScreen === "admin") {
    return (
      <AdminSettingsScreen
        session={session}
        onBack={() => setActiveScreen("intake")}
        onLogout={onLogout}
        onDocumentsReset={refresh}
      />
    );
  }

  return (
    <View style={styles.root}>
      <View
        style={[
          styles.appbar,
          { paddingTop: insets.top, minHeight: 64 + insets.top },
        ]}
      >
        <View style={styles.appbarCopy}>
          <View style={styles.headerLogoPanel}>
            <BrandLogo width={178} height={29} />
          </View>
        </View>
          <View style={styles.headerActions}>
            <>
            <AppIconButton
              icon="file-document-multiple-outline"
              onPress={() => setActiveScreen("processed")}
              accessibilityLabel="Documentos procesados"
            />
            {Platform.OS === "web" &&
            (session.user.permissions.includes("*") ||
              session.user.permissions.includes("tenant.configure")) ? (
              <AppIconButton
                icon="cog-outline"
                onPress={() => setActiveScreen("admin")}
                accessibilityLabel="Configuración del tenant"
              />
            ) : null}
            {documentType || successNotice ? (
              <>
              <AppIconButton
                icon="refresh"
                onPress={refresh}
                accessibilityLabel="Actualizar"
              />
              </>
            ) : null}
          </>
          <AppIconButton
            icon="logout"
            onPress={onLogout}
            accessibilityLabel="Cerrar sesión"
          />
        </View>
      </View>

      <KeyboardAvoidingView
        style={styles.keyboardContainer}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={64}
      >
        <ScrollView
          ref={wizardScrollRef}
          contentContainerStyle={[
            styles.content,
            styles.wizardContent,
            { paddingBottom: insets.bottom + 220 },
          ]}
          keyboardShouldPersistTaps="handled"
          automaticallyAdjustKeyboardInsets
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={refresh} />
          }
        >
          {!successNotice && !documentType ? (
            <View style={styles.wizardStart}>
              <Text variant="headlineSmall" style={styles.wizardTitle}>
                ¿Qué tipo de documento vas a procesar?
              </Text>
              <Text variant="bodyMedium" style={styles.muted}>
                Selecciona una opción para comenzar.
              </Text>
              <DocumentTypePicker
                value={documentType}
                onChange={chooseDocumentType}
              />
            </View>
          ) : null}

          {!successNotice && documentType ? (
            <View style={styles.hero}>
              <Text variant="headlineSmall">
                Procesar {DOCUMENT_TYPE_LABELS[documentType].toLowerCase()}
              </Text>
              <Text variant="bodyMedium" style={styles.muted}>
                Completa los pasos para guardar, interpretar y enviar el
                documento al ERP.
              </Text>
            </View>
          ) : null}

          {dataLoadError ? (
            <View style={[styles.card, styles.errorCard]}>
              <View style={styles.cardContent}>
                <Text variant="titleMedium">No se han podido actualizar los datos</Text>
                <Text variant="bodyMedium" style={styles.muted}>
                  {dataLoadError}
                </Text>
              </View>
            </View>
          ) : null}

          {error ? (
            <View style={[styles.card, styles.errorCard]}>
              <View style={styles.cardContent}>
                <Text variant="titleMedium">No se ha podido procesar</Text>
                <Text variant="bodyMedium" style={styles.muted}>
                  {error}
                </Text>
              </View>
            </View>
          ) : null}

          {queueNotice ? (
            <View style={[styles.card, styles.queueCard]} accessibilityRole="alert">
              <View style={styles.cardContent}>
                <View style={styles.analysisHeadingRow}>
                  <MaterialCommunityIcons name="cloud-sync-outline" size={24} color="#1f5fbf" />
                  <Text variant="bodyMedium" style={styles.queueText}>{queueNotice}</Text>
                </View>
              </View>
            </View>
          ) : null}

          {successNotice ? (
            <View
              style={[styles.card, styles.successAlert]}
              accessibilityRole="alert"
            >
              <View style={styles.cardContent}>
                <Text variant="titleMedium" style={styles.successText}>
                  Documento tramitado correctamente
                </Text>
                <Text variant="bodySmall" style={styles.muted}>
                  Se ha enviado al ERP y se ha preparado la copia para el
                  cliente.
                </Text>
                <AppButton
                  mode="text"
                  onPress={() => setActiveScreen("processed")}
                >
                  Ver documentos enviados al ERP
                </AppButton>
                {captureSettings.enable_burst ? (
                  <AppButton mode="outlined" onPress={startNextDocument}>
                    <MaterialCommunityIcons name="camera-plus-outline" size={18} color="#1f5fbf" />
                    Capturar siguiente
                  </AppButton>
                ) : null}
              </View>
            </View>
          ) : null}

          {!successNotice && documentType ? (
            <>
              <View style={[styles.card, styles.customerCard]}>
                <PanelHeader
                  title="1. Cliente"
                  subtitle="Busca por nombre o identificador"
                />
                <View style={styles.cardContent}>
                  <Text variant="labelLarge" style={styles.fieldLabel}>
                    Tipo de documento
                  </Text>
                  <DocumentTypePicker
                    value={documentType}
                    onChange={chooseDocumentType}
                  />
                  <Text variant="bodySmall" style={styles.helperText}>
                    Automático intenta diferenciar el documento a partir del
                    texto leído. Puedes fijarlo manualmente si es ambiguo.
                  </Text>
                  <Text variant="labelLarge" style={styles.fieldLabel}>
                    Dirección del documento
                  </Text>
                  <DocumentDirectionPicker
                    value={documentDirection}
                    onChange={chooseDocumentDirection}
                  />
                  <Text variant="bodySmall" style={styles.helperText}>
                    Entrada significa que recibimos el documento; salida, que lo
                    emitimos nosotros.
                  </Text>
                  <View style={styles.customerSelector}>
                    <Text variant="labelLarge" style={styles.fieldLabel}>
                      Cliente o proveedor
                    </Text>
                    <View style={styles.customerInputWrap}>
                      <NativeTextInput
                        style={[styles.nativeInput, styles.customerInput]}
                        value={
                          selectedCustomer
                            ? `${selectedCustomer.id} · ${selectedCustomer.name}`
                            : customerQuery
                        }
                        onFocus={() => {
                          setCustomerInputFocused(true);
                          setTimeout(
                            () =>
                              wizardScrollRef.current?.scrollToEnd({
                                animated: true,
                              }),
                            220,
                          );
                        }}
                        onBlur={() => {
                          setTimeout(() => setCustomerInputFocused(false), 150);
                        }}
                        onChangeText={(value) => {
                          setSelectedCustomer(null);
                          setCustomerQuery(value);
                          setCustomerInputFocused(true);
                          setDocument(null);
                          setAnalysis(null);
                        }}
                        placeholder="CLI-001 o nombre de empresa"
                        placeholderTextColor="#718096"
                      />
                      {selectedCustomer || customerQuery ? (
                        <AppIconButton
                          icon="close-circle"
                          size={20}
                          style={styles.clearCustomerButton}
                          onPress={clearCustomer}
                          accessibilityLabel="Borrar cliente"
                        />
                      ) : null}
                    </View>
                    {customerQuery.trim().length > 0 &&
                    customerQuery.trim().length < MIN_CUSTOMER_SEARCH_CHARS ? (
                      <Text variant="bodySmall" style={styles.helperText}>
                        Escribe al menos 3 caracteres para buscar.
                      </Text>
                    ) : null}
                    {selectedCustomer ? (
                      <Text variant="bodySmall" style={styles.helperText}>
                        La copia se preparará para: {selectedCustomer.email}
                      </Text>
                    ) : null}
                    {showCustomerSuggestions && filteredCustomers.length > 0 ? (
                      <View style={styles.suggestions}>
                        <ScrollView
                          nestedScrollEnabled
                          keyboardShouldPersistTaps="always"
                        >
                          {filteredCustomers.map((customer) => (
                            <AppButton
                              key={customer.id}
                              mode="text"
                              contentStyle={styles.suggestionButton}
                              onPressIn={() => {
                                setSelectedCustomer(customer);
                                setCustomerQuery("");
                                setCustomerInputFocused(false);
                                Keyboard.dismiss();
                                setDocument(null);
                                setDocumentPages([]);
                                setLocalQuality(null);
                                setAnalysis(null);
                                if (captureSettings.remember_last_selection) {
                                  void AsyncStorage.setItem(lastSelectionKey(session.user.tenant_id), JSON.stringify({ documentType, direction: documentDirection, customerId: customer.id } satisfies LastSelection));
                                }
                              }}
                              onPress={() => {
                                // Android can deliver both onPressIn and onPress; selection is handled once in onPressIn.
                              }}
                            >
                              {customer.id} · {customer.name}
                            </AppButton>
                          ))}
                        </ScrollView>
                      </View>
                    ) : null}
                  </View>
                </View>
              </View>

              {selectedCustomer ? (
                <View style={styles.card}>
                  <PanelHeader
                    title="2. Documento"
                    subtitle="Captura una foto o selecciona el archivo"
                  />
                  <View style={styles.documentSourceOptions}>
                    <DocumentSourceButton
                      icon="camera-outline"
                      label="Capturar documento"
                      onPress={openCamera}
                    />
                    {Platform.OS === "web" ? (
                      <DocumentSourceButton
                        icon="file-upload-outline"
                        label="Seleccionar archivo"
                        onPress={chooseDocumentFile}
                      />
                    ) : (
                      <>
                        <DocumentSourceButton
                          icon="image-edit-outline"
                          label="Seleccionar imagen"
                          onPress={() => {
                            void chooseMobileImage().catch((cause) =>
                              setError((cause as Error).message),
                            );
                          }}
                        />
                        <DocumentSourceButton
                          icon="file-document-outline"
                          label="Seleccionar PDF"
                          onPress={() => {
                            void choosePdfFile().catch((cause) =>
                              setError((cause as Error).message),
                            );
                          }}
                        />
                      </>
                    )}
                  </View>
                  {document ? (
                    <View style={styles.cardContent}>
                      <View style={styles.previewHeading}>
                        <Text variant="bodyMedium" style={styles.previewFilename}>
                          {documentPages.length > 1 ? `${documentPages.length} hojas seleccionadas` : `Seleccionado: ${document.filename}`}
                        </Text>
                        {captureSettings.enable_multipage ? (
                          <AppIconButton
                            icon="layers-plus"
                            onPress={addDocumentPage}
                            accessibilityLabel="Añadir otra hoja"
                          />
                        ) : null}
                      </View>
                      {queueNotice ? <Text variant="bodySmall" style={styles.helperText}>{queueNotice}</Text> : null}
                      {document.preview_uri ? (
                        <Image
                          source={{ uri: document.preview_uri }}
                          style={styles.documentPreview}
                          resizeMode="contain"
                          accessibilityLabel="Previsualización del documento"
                        />
                      ) : null}
                      {localQuality && localQuality.status !== "unavailable" ? (
                        <View style={[styles.captureQuality, localQuality.status === "good" ? styles.captureQualityGood : styles.captureQualityReview]}>
                          <MaterialCommunityIcons name={localQuality.status === "good" ? "check-circle-outline" : "alert-circle-outline"} size={18} color={localQuality.status === "good" ? "#1c7c54" : "#8a4b08"} />
                          <Text variant="bodySmall" style={localQuality.status === "good" ? styles.successText : styles.warningText}>
                            {localQuality.status === "good" ? "Calidad de captura correcta" : `Revisa la captura: ${localQuality.reasons.join(" · ")}`}
                          </Text>
                        </View>
                      ) : null}
                    </View>
                  ) : null}
                </View>
              ) : null}

              {selectedCustomer && cameraOpen ? (
                <View style={styles.card}>
                  <PanelHeader
                    title="Cámara"
                    subtitle="Alinea el documento y captura la imagen"
                  />
                  <View style={styles.cardContent}>
                    <CameraView
                      ref={cameraRef}
                      style={styles.cameraPreview}
                      facing="back"
                      mode="picture"
                      enableTorch={torchEnabled}
                      onCameraReady={() => setCameraReady(true)}
                    >
                      {captureSettings.guided_capture ? <View pointerEvents="none" style={styles.cameraGuideFrame} /> : null}
                      <View style={styles.cameraToolbar}>
                        <AppIconButton
                          icon={torchEnabled ? "flash" : "flash-off"}
                          onPress={() => setTorchEnabled((value) => !value)}
                          accessibilityLabel={torchEnabled ? "Desactivar linterna" : "Activar linterna"}
                          style={styles.cameraToolbarButton}
                        />
                      </View>
                    </CameraView>
                    <View style={styles.cameraCountdown}>
                      <Text variant="bodyMedium">
                        La foto se capturará automáticamente en
                      </Text>
                      <Text
                        variant="displaySmall"
                        style={styles.countdownNumber}
                      >
                        {cameraCountdown ?? 5}
                      </Text>
                      <Text variant="bodySmall" style={styles.panelSubtitle}>
                        Coloca el documento dentro del encuadre.
                      </Text>
                      <Text variant="bodySmall" style={styles.panelSubtitle}>
                        La comprobación de nitidez e iluminación se hará antes del análisis.
                      </Text>
                    </View>
                  </View>
                  <View style={styles.cardActions}>
                    <AppButton
                      mode="outlined"
                      onPress={closeCamera}
                      disabled={capturing}
                    >
                      Cerrar
                    </AppButton>
                  </View>
                </View>
              ) : null}

              {document ? (
                <View style={styles.card}>
                  <PanelHeader
                    title="3. Interpretación previa"
                    subtitle="La lectura y las reglas deben ser correctas antes de enviar"
                  />
                  <View style={styles.cardContent}>
                    <Text variant="bodySmall" style={styles.helperText}>
                      Analiza el documento capturado para comprobar su lectura y
                      los campos obligatorios.
                    </Text>
                    {analysis ? (
                      <View
                        style={[
                          styles.analysisBox,
                          analysis.can_send
                            ? styles.analysisGood
                            : styles.analysisBlocked,
                        ]}
                      >
                        <View style={styles.analysisHeadingRow}>
                          <MaterialCommunityIcons
                            name={
                              analysis.can_send
                                ? "check-circle-outline"
                                : "alert-circle-outline"
                            }
                            size={28}
                            color={analysis.can_send ? "#1c7c54" : "#a43d3d"}
                          />
                          <View style={styles.analysisHeadingCopy}>
                            <Text variant="titleMedium">
                              {analysis.can_send
                                ? "Documento listo"
                                : "Revisión necesaria"}
                            </Text>
                            <Text
                              variant="bodySmall"
                              style={styles.analysisSummary}
                            >
                              {analysis.can_send
                                ? "Cumple las reglas y puede enviarse al pipeline."
                                : "No se puede enviar todavía."}
                            </Text>
                          </View>
                        </View>
                        {!analysis.can_send ? (
                          <>
                            <Text
                              variant="labelLarge"
                              style={styles.analysisSectionTitle}
                            >
                              Revisa estos puntos
                            </Text>
                            <View style={styles.analysisIssues}>
                              {getAnalysisIssues(analysis).map((issue) => (
                                <View
                                  key={issue}
                                  style={styles.analysisIssueRow}
                                >
                                  <MaterialCommunityIcons
                                    name="chevron-right"
                                    size={18}
                                    color="#a43d3d"
                                  />
                                  <Text
                                    variant="bodySmall"
                                    style={styles.analysisIssueText}
                                  >
                                    {issue}
                                  </Text>
                                </View>
                              ))}
                            </View>
                            <View style={styles.analysisGuidance}>
                              <MaterialCommunityIcons
                                name={
                                  analysisIsDuplicate
                                    ? "content-duplicate"
                                    : isAwsVisionUnavailable(analysis)
                                      ? "cloud-alert-outline"
                                      : "camera-outline"
                                }
                                size={20}
                                color="#8a4b08"
                              />
                              <Text
                                variant="bodySmall"
                                style={styles.reviewDisclaimer}
                              >
                                {analysisIsDuplicate
                                  ? "Este documento ya se ha procesado y no se volverá a enviar al ERP. Comprueba el historial si necesitas consultar el resultado."
                                  : isAwsVisionUnavailable(analysis)
                                  ? "El documento no necesita otra captura. Espera a que AWS habilite el lector IA o utiliza la introducción manual."
                                  : "Vuelve a capturar con buena iluminación, enfoque y el documento completo dentro del encuadre."}
                              </Text>
                            </View>
                          </>
                        ) : null}
                        <View style={styles.analysisFacts}>
                          <Text
                            variant="bodySmall"
                            style={
                              analysis.interpretation.customer_match.status ===
                              "matched"
                                ? styles.successText
                                : styles.errorText
                            }
                          >
                            Cliente:{" "}
                            {analysis.interpretation.customer_match.status ===
                            "matched"
                              ? "coincide"
                              : "revisar"}
                          </Text>
                          {analysis.interpretation.document_customer.name || analysis.interpretation.document_customer.id ? (
                            <Text variant="bodySmall">
                              Detectado en documento: {analysis.interpretation.document_customer.id ?? analysis.interpretation.document_customer.name}
                            </Text>
                          ) : null}
                          <Text variant="bodySmall">
                            Dirección:{" "}
                            {
                              DOCUMENT_DIRECTION_LABELS[
                                analysis.interpretation.document_direction
                              ]
                            }
                          </Text>
                          {analysis.interpretation.document_type !==
                          "unknown" ? (
                            <Text variant="bodySmall">
                              Tipo:{" "}
                              {
                                DOCUMENT_TYPE_LABELS[
                                  analysis.interpretation.document_type
                                ]
                              }
                            </Text>
                          ) : null}
                        </View>
                        {Object.entries(analysis.interpretation.field_confidence ?? {}).some(([, confidence]) => confidence < captureSettings.confidence_threshold) ? (
                          <View style={styles.confidenceNotice}>
                            <MaterialCommunityIcons name="target-account" size={18} color="#8a4b08" />
                            <Text variant="bodySmall" style={styles.warningText}>
                              Hay campos con lectura dudosa. Abre los detalles antes de enviar.
                            </Text>
                          </View>
                        ) : null}
                        {!analysis.can_send ? (
                          <View style={styles.manualEntryAction}>
                            <AppButton
                              mode="text"
                              onPress={openManualEntry}
                              contentStyle={styles.manualEntryButtonContent}
                            >
                              <MaterialCommunityIcons
                                name="form-textbox"
                                size={18}
                                color="#64748b"
                              />
                              <NativeText style={styles.manualEntryButtonLabel}>
                                Introducir datos manualmente
                              </NativeText>
                            </AppButton>
                          </View>
                        ) : null}
                        <AppButton
                          mode="text"
                          onPress={() =>
                            setShowAnalysisDetails((current) => !current)
                          }
                        >
                          {showAnalysisDetails
                            ? "Ocultar detalles de lectura"
                            : "Ver detalles de lectura"}
                        </AppButton>
                        {showAnalysisDetails ? (
                          <View style={styles.analysisDetails}>
                            <Text variant="bodySmall">
                              Número:{" "}
                              {analysis.interpretation.document_number ??
                                "no identificado"}
                            </Text>
                            <Text variant="bodySmall">
                              Líneas detectadas:{" "}
                              {analysis.interpretation.lines.length}
                            </Text>
                            {Object.entries(analysis.interpretation.field_confidence ?? {}).map(([field, confidence]) => (
                              <View key={field} style={styles.confidenceRow}>
                                <Text variant="bodySmall">{field}</Text>
                                <Text variant="bodySmall" style={confidence < captureSettings.confidence_threshold ? styles.warningText : styles.successText}>
                                  {Math.round(confidence * 100)}% confianza
                                </Text>
                              </View>
                            ))}
                            {analysis.interpretation.lines.length > 0 ? (
                              <Text variant="bodySmall">
                                {analysis.interpretation.lines
                                  .map(
                                    (line) => `${line.sku} x ${line.quantity}`,
                                  )
                                  .join(" · ")}
                              </Text>
                            ) : null}
                            <Text variant="bodySmall" style={styles.ocrResult}>
                              {analysis.ocr.text || "Sin texto OCR obtenido."}
                            </Text>
                          </View>
                        ) : null}
                      </View>
                    ) : null}
                    {manualMode ? (
                      <>
                        <ManualEntryForm
                          draft={manualDraft}
                          selectedCustomer={selectedCustomer}
                          onChange={(next) => {
                            setManualDraft(next);
                            setManualData(null);
                            setAnalysis(null);
                          }}
                        />
                        <View style={styles.documentSourceOptions}>
                          <DocumentSourceButton
                            icon="file-check-outline"
                            label="Revisar datos manuales"
                            disabled={analyzing || sending}
                            loading={analyzing}
                            primary
                            onPress={analyzeManualDocument}
                          />
                        </View>
                      </>
                    ) : null}
                  </View>
                  <View style={styles.documentSourceOptions}>
                    <DocumentSourceButton
                      icon="file-search-outline"
                      label="Analizar documento"
                      disabled={!document || analyzing || sending}
                      loading={analyzing}
                      onPress={analyzeDocument}
                    />
                    {analysis?.can_send ? (
                      <DocumentSourceButton
                        icon="send-check"
                        label="Enviar al pipeline"
                        disabled={sending || analyzing}
                        loading={sending}
                        primary
                        onPress={sendToPipeline}
                      />
                    ) : null}
                  </View>
                </View>
              ) : null}
            </>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
      {cropRequest ? (
        <DocumentCropper
          request={cropRequest}
          onCancel={cancelCrop}
          onComplete={completeCrop}
        />
      ) : null}
      <FeedbackNotice
        message={message}
        error={error}
        onClosed={closeManualAfterSuccess ? finishManualReview : undefined}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#f5f7fb" },
  appButton: {
    minHeight: 44,
    borderRadius: 6,
    paddingHorizontal: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  appButtonContent: {
    minHeight: 42,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  appButtonLabel: { fontSize: 14, fontWeight: "700" },
  appButtonContained: { backgroundColor: "#1f5fbf" },
  appButtonOutlined: {
    borderWidth: 1,
    borderColor: "#1f5fbf",
    backgroundColor: "#ffffff",
  },
  appButtonText: { paddingHorizontal: 8, backgroundColor: "transparent" },
  appButtonDisabled: { opacity: 0.45 },
  appButtonPressed: { opacity: 0.78 },
  appIconButton: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
  },
  appChip: {
    minHeight: 28,
    paddingHorizontal: 10,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#e7eef8",
  },
  appChipText: { color: "#53657d", fontSize: 12, fontWeight: "700" },
  divider: { height: 1, backgroundColor: "#dbe3ef" },
  loadingRoot: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    padding: 24,
    backgroundColor: "#f5f7fb",
  },
  loadingTitle: { color: "#1f3c68" },
  loadingText: { color: "#5d6b7c" },
  appbar: {
    minHeight: 64,
    paddingHorizontal: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: "#ffffff",
    borderBottomWidth: 1,
    borderBottomColor: "#dbe3ef",
  },
  appbarCopy: { flex: 1, paddingLeft: 8 },
  headerLogoPanel: {
    alignSelf: "flex-start",
    borderRadius: 7,
    paddingHorizontal: 8,
    paddingVertical: 4,
    backgroundColor: "#ffffff",
  },
  headerActions: { flexDirection: "row", alignItems: "center", gap: 2 },
  appbarSubtitle: { color: "#5d6b7c" },
  keyboardContainer: { flex: 1 },
  content: {
    width: "100%",
    maxWidth: 920,
    alignSelf: "center",
    padding: 16,
    gap: 16,
  },
  wizardContent: { flexGrow: 1, maxWidth: 760, justifyContent: "center" },
  wizardStart: {
    padding: 20,
    borderRadius: 16,
    backgroundColor: "#eaf1ff",
    gap: 10,
  },
  wizardTitle: { color: "#1f3c68" },
  hero: { padding: 20, borderRadius: 16, backgroundColor: "#eaf1ff", gap: 8 },
  endpoint: { color: "#53657d", marginTop: 4 },
  muted: { color: "#5d6b7c" },
  warningText: { color: "#8a4b08" },
  card: {
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#dbe3ef",
    borderRadius: 12,
  },
  previewHeading: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  previewFilename: { flex: 1, fontWeight: "700" },
  captureQuality: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 8, marginTop: 10 },
  captureQualityGood: { backgroundColor: "#effaf4" },
  captureQualityReview: { backgroundColor: "#fff2dc" },
  confidenceNotice: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, marginTop: 10, borderRadius: 8, backgroundColor: "#fff2dc" },
  confidenceRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 2 },
  customerCard: { zIndex: 20, elevation: 20 },
  errorCard: { backgroundColor: "#fff5f5", borderColor: "#e3aaaa" },
  successAlert: { backgroundColor: "#effaf4", borderColor: "#9bd5b5" },
  queueCard: { backgroundColor: "#eef5ff", borderColor: "#b7cef0" },
  queueText: { flex: 1, color: "#1f5fbf" },
  usageExclusion: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 8,
  },
  usageSummaryGrid: { flexDirection: "row", gap: 10 },
  usageSummaryCard: { flex: 1, padding: 14, gap: 4 },
  usageNumber: { color: "#1f5fbf", marginTop: 4 },
  usageSectionHeading: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 4,
  },
  usageServiceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 14,
  },
  usageServiceCopy: { flex: 1, gap: 2 },
  usageEventRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 12,
  },
  panelHeader: {
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 8,
    gap: 3,
  },
  panelSubtitle: { color: "#5d6b7c" },
  cardContent: { padding: 16, paddingTop: 8 },
  cardActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  recordHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  recordHeaderCopy: { flex: 1 },
  customerSelector: { position: "relative", zIndex: 20 },
  documentTypeOptions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginBottom: 2,
  },
  directionOptions: { flexDirection: "row", gap: 8, marginBottom: 2 },
  directionButton: { minWidth: 0 },
  documentTypeButton: {
    flex: 1,
    minWidth: 100,
    minHeight: 96,
    paddingHorizontal: 4,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: "#c7d2e0",
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#ffffff",
  },
  documentTypeButtonSelected: {
    borderColor: "#1f5fbf",
    backgroundColor: "#eaf1ff",
  },
  documentTypeButtonLabel: {
    color: "#53657d",
    fontSize: 12,
    fontWeight: "700",
    textAlign: "center",
  },
  documentTypeButtonLabelSelected: { color: "#1f5fbf" },
  manualForm: {
    marginTop: 14,
    padding: 12,
    gap: 8,
    borderWidth: 1,
    borderColor: "#b7cbe8",
    borderRadius: 10,
    backgroundColor: "#f7faff",
  },
  manualFormHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  manualFormHeaderCopy: { flex: 1, gap: 2 },
  manualWarning: {
    color: "#8a4b08",
    padding: 8,
    borderRadius: 6,
    backgroundColor: "#fff0d8",
  },
  manualConfirmedBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: 8,
    borderRadius: 6,
    backgroundColor: "#eaf7f0",
  },
  manualConfirmedCopy: { flex: 1, gap: 1 },
  manualConfirmedLabel: { color: "#1c7c54" },
  manualHistoryLabel: { color: "#1f5fbf", fontWeight: "700" },
  manualChoiceRow: { flexDirection: "row", gap: 8 },
  manualChoiceButton: { flex: 1, minHeight: 74 },
  manualLinesHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 6,
  },
  manualLineRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  manualSkuInput: { flex: 1 },
  manualQuantityInput: { width: 104 },
  manualDetailsBox: {
    marginTop: 8,
    padding: 10,
    gap: 8,
    borderRadius: 8,
    backgroundColor: "#eef4fc",
  },
  manualTwoColumns: { flexDirection: "row", gap: 8 },
  manualHalfInput: { flex: 1 },
  manualEntryAction: { marginTop: 4, alignItems: "flex-start" },
  manualEntryButtonContent: { minHeight: 32, paddingHorizontal: 0 },
  manualEntryButtonLabel: { color: "#64748b", fontSize: 13, fontWeight: "600" },
  documentSourceOptions: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  documentSourceButton: {
    flex: 1,
    minHeight: 104,
    paddingHorizontal: 4,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: "#c7d2e0",
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#ffffff",
  },
  documentSourceButtonLabel: {
    color: "#53657d",
    fontSize: 12,
    fontWeight: "700",
    textAlign: "center",
  },
  documentSourceButtonPrimary: {
    borderColor: "#1f5fbf",
    backgroundColor: "#1f5fbf",
  },
  documentSourceButtonLabelPrimary: { color: "#ffffff" },
  suggestions: {
    position: "absolute",
    top: 80,
    left: 0,
    right: 0,
    maxHeight: 320,
    borderWidth: 1,
    borderColor: "#c7d2e0",
    borderRadius: 8,
    paddingVertical: 4,
    backgroundColor: "#ffffff",
    zIndex: 40,
    elevation: 40,
  },
  suggestionButton: { justifyContent: "flex-start" },
  helperText: { color: "#5d6b7c", marginTop: 6 },
  historySearch: { minHeight: 48, borderWidth: 1, borderColor: "#9bb3d3", borderRadius: 8, paddingHorizontal: 14, backgroundColor: "#ffffff", color: "#1f2937", fontSize: 15, marginTop: 8 },
  historyFilters: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 },
  fieldLabel: { color: "#3f4b5a", marginBottom: 6 },
  customerInputWrap: { position: "relative" },
  nativeInput: {
    minHeight: 52,
    borderWidth: 1,
    borderColor: "#718096",
    borderRadius: 4,
    paddingHorizontal: 14,
    paddingVertical: 12,
    backgroundColor: "#ffffff",
    color: "#1f2937",
    fontSize: 16,
  },
  customerInput: { paddingRight: 48 },
  clearCustomerButton: { position: "absolute", right: 2, top: 4, margin: 0 },
  cameraPreview: {
    width: "100%",
    height: 360,
    borderRadius: 12,
    overflow: "hidden",
  },
  cameraGuideFrame: { position: "absolute", left: "8%", right: "8%", top: "10%", bottom: "10%", borderWidth: 2, borderColor: "#ffffff", borderRadius: 12, opacity: 0.9 },
  cameraToolbar: { position: "absolute", right: 12, top: 12 },
  cameraToolbarButton: { backgroundColor: "rgba(0,0,0,0.45)" },
  cameraCountdown: { alignItems: "center", paddingVertical: 12, gap: 4 },
  countdownNumber: { color: "#1f5fbf", fontWeight: "700" },
  documentPreview: {
    width: "100%",
    height: 280,
    marginTop: 12,
    borderRadius: 8,
    backgroundColor: "#eef2f7",
  },
  evidencePreview: {
    width: "100%",
    height: 180,
    borderRadius: 8,
    backgroundColor: "#eef2f7",
  },
  evidenceImageButton: {
    marginTop: 12,
    borderRadius: 8,
    overflow: "hidden",
    backgroundColor: "#eef2f7",
  },
  evidenceHint: {
    minHeight: 34,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#eaf1ff",
  },
  evidenceHintText: { color: "#1f5fbf", fontSize: 12, fontWeight: "700" },
  evidenceDocument: {
    marginTop: 12,
    minHeight: 76,
    padding: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    borderWidth: 1,
    borderColor: "#dbe3ef",
    borderRadius: 8,
    backgroundColor: "#f8fafc",
  },
  evidenceDocumentCopy: { flex: 1, gap: 2 },
  evidenceDocumentExtension: {
    color: "#c34444",
    fontSize: 12,
    fontWeight: "800",
  },
  evidenceDocumentName: { color: "#334155", fontSize: 14, fontWeight: "600" },
  evidenceDocumentAction: { color: "#1f5fbf", fontSize: 12, fontWeight: "700" },
  evidenceModal: { flex: 1, alignItems: "center", justifyContent: "center" },
  evidenceModalBackdrop: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: "rgba(15, 23, 42, 0.9)",
  },
  evidenceExpanded: { width: "94%", height: "86%" },
  evidenceModalClose: {
    position: "absolute",
    top: 24,
    right: 20,
    width: 48,
    height: 48,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 24,
    backgroundColor: "rgba(15, 23, 42, 0.75)",
  },
  resultSection: { marginTop: 14, gap: 4 },
  ocrResult: {
    padding: 10,
    borderRadius: 6,
    backgroundColor: "#f4f6f8",
    color: "#334155",
  },
  interpretedLine: { color: "#334155" },
  analysisBox: {
    marginTop: 16,
    padding: 12,
    borderWidth: 1,
    borderRadius: 8,
    gap: 4,
  },
  analysisGood: { backgroundColor: "#effaf4", borderColor: "#9bd5b5" },
  analysisBlocked: { backgroundColor: "#fff7ed", borderColor: "#f2bd82" },
  analysisHeadingRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginBottom: 4,
  },
  analysisHeadingCopy: { flex: 1, gap: 2 },
  analysisSummary: { color: "#53657d" },
  analysisSectionTitle: { marginTop: 10, color: "#6d3c08" },
  analysisIssues: { gap: 5, marginTop: 4 },
  analysisIssueRow: { flexDirection: "row", alignItems: "flex-start", gap: 2 },
  analysisIssueText: { flex: 1, color: "#7f3030" },
  analysisGuidance: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    marginTop: 10,
    padding: 9,
    borderRadius: 7,
    backgroundColor: "#fff0d8",
  },
  analysisFacts: {
    gap: 2,
    marginTop: 10,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: "#f2d8b7",
  },
  analysisDetails: {
    gap: 4,
    padding: 10,
    borderRadius: 7,
    backgroundColor: "#f4f6f8",
  },
  reviewDisclaimer: { color: "#8a4b08", fontWeight: "600" },
  sectionHeading: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 8,
  },
  loader: { marginVertical: 24 },
  errorText: { color: "#a43d3d", marginTop: 6 },
  successText: { color: "#1c7c54", marginTop: 6 },
  toast: {
    position: "absolute",
    left: 16,
    right: 16,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderRadius: 8,
    backgroundColor: "#263238",
  },
  toastText: { color: "#ffffff" },
});
