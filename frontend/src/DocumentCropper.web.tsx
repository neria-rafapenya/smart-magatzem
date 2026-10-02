import { useCallback, useState } from 'react';
import Cropper, { type Area } from 'react-easy-crop';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { type CropRequest, type CropResult, type DocumentCropperProps } from './DocumentCropper';
import { croppedDocumentFilename } from './documentCropUtils';

async function cropImage(request: CropRequest, area: Area): Promise<CropResult> {
  const image = new Image();
  image.crossOrigin = 'anonymous';
  image.src = request.uri;
  await image.decode();

  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(area.width));
  canvas.height = Math.max(1, Math.round(area.height));
  const context = canvas.getContext('2d');
  if (!context) throw new Error('No se ha podido preparar el recorte de la imagen.');

  context.drawImage(
    image,
    Math.round(area.x),
    Math.round(area.y),
    Math.round(area.width),
    Math.round(area.height),
    0,
    0,
    canvas.width,
    canvas.height,
  );

  const dataUrl = canvas.toDataURL('image/jpeg', 0.9);
  return {
    uri: dataUrl,
    base64: dataUrl.split(',', 2)[1] ?? '',
    filename: croppedDocumentFilename(),
    content_type: 'image/jpeg',
  };
}

export function DocumentCropper({ request, onCancel, onComplete }: DocumentCropperProps) {
  const [crop, setCrop] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [area, setArea] = useState<Area | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const complete = useCallback(async () => {
    if (!area || saving) return;
    setSaving(true);
    setError('');
    try {
      onComplete(await cropImage(request, area));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'No se ha podido recortar la imagen.');
      setSaving(false);
    }
  }, [area, onComplete, request, saving]);

  return (
      <View style={styles.overlay}>
      <View style={styles.panel}>
        <Text style={styles.title}>Recorta el documento</Text>
        <Text style={styles.subtitle}>Ajusta el marco para dejar fuera el fondo y conservar todo el documento.</Text>
        <View style={styles.cropArea}>
          <Cropper
            image={request.uri}
            crop={crop}
            zoom={zoom}
            aspect={3 / 4}
            cropShape="rect"
            showGrid
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={(_croppedArea, croppedAreaPixels) => setArea(croppedAreaPixels)}
          />
        </View>
        <View style={styles.controls}>
          <Text style={styles.zoomLabel}>Zoom</Text>
          <input
            aria-label="Zoom del recorte"
            type="range"
            min="1"
            max="3"
            step="0.05"
            value={zoom}
            onChange={(event) => setZoom(Number(event.currentTarget.value))}
            style={styles.slider}
          />
        </View>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.actions}>
          <Pressable accessibilityRole="button" disabled={saving} onPress={onCancel} style={styles.secondaryButton}>
            <Text style={styles.secondaryText}>Cancelar</Text>
          </Pressable>
          <Pressable accessibilityRole="button" disabled={!area || saving} onPress={() => { void complete(); }} style={[styles.primaryButton, (!area || saving) && styles.disabledButton]}>
            <Text style={styles.primaryText}>{saving ? 'Preparando…' : 'Usar imagen recortada'}</Text>
          </Pressable>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: { position: 'fixed' as never, inset: 0, zIndex: 1000, backgroundColor: 'rgba(15, 29, 48, 0.78)', alignItems: 'center', justifyContent: 'center', padding: 20 },
  panel: { width: 'min(760px, 100%)' as never, backgroundColor: '#ffffff', borderRadius: 18, padding: 20, gap: 12, boxShadow: '0 14px 44px rgba(0,0,0,.28)' as never },
  title: { color: '#1f3c68', fontSize: 22, fontWeight: '700' },
  subtitle: { color: '#53657d', fontSize: 14, lineHeight: 20 },
  cropArea: { height: 460, position: 'relative', backgroundColor: '#182638', borderRadius: 10, overflow: 'hidden' },
  controls: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  zoomLabel: { color: '#53657d', fontWeight: '700' },
  slider: { flex: 1 },
  error: { color: '#a43d3d', fontSize: 13 },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 10 },
  secondaryButton: { paddingHorizontal: 16, paddingVertical: 11, borderWidth: 1, borderColor: '#c7d2e0', borderRadius: 9 },
  secondaryText: { color: '#53657d', fontWeight: '700' },
  primaryButton: { paddingHorizontal: 16, paddingVertical: 11, borderRadius: 9, backgroundColor: '#1f5fbf' },
  primaryText: { color: '#ffffff', fontWeight: '700' },
  disabledButton: { opacity: 0.5 },
});
