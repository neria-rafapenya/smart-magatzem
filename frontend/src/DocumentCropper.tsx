import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native';
import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';

import { croppedDocumentFilename } from './documentCropUtils';

export type CropRequest = {
  uri: string;
  filename: string;
  content_type: string;
  append?: boolean;
};

export type CropResult = {
  uri: string;
  base64: string;
  filename: string;
  content_type: string;
};

export type DocumentCropperProps = {
  request: CropRequest;
  onCancel: () => void;
  onComplete: (result: CropResult) => void | Promise<void>;
};

// En web se utiliza el recortador interactivo; en móvil este componente prepara
// un recorte centrado después de la captura integrada de la cámara.
export function DocumentCropper(_props: DocumentCropperProps): ReactNode {
  const { request, onCancel, onComplete } = _props;
  const [result, setResult] = useState<CropResult | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    const prepare = async () => {
      try {
        const size = await new Promise<{ width: number; height: number }>((resolve, reject) => {
          Image.getSize(request.uri, (width, height) => resolve({ width, height }), reject);
        });
        const targetRatio = 3 / 4;
        const sourceRatio = size.width / Math.max(1, size.height);
        const cropWidth = sourceRatio > targetRatio ? Math.round(size.height * targetRatio) : size.width;
        const cropHeight = sourceRatio > targetRatio ? size.height : Math.round(size.width / targetRatio);
        const transformed = await manipulateAsync(
          request.uri,
          [{ crop: { originX: Math.max(0, Math.round((size.width - cropWidth) / 2)), originY: Math.max(0, Math.round((size.height - cropHeight) / 2)), width: cropWidth, height: cropHeight } }],
          { base64: true, compress: 0.9, format: SaveFormat.JPEG },
        );
        if (!active || !transformed.base64) return;
        setResult({ uri: transformed.uri, base64: transformed.base64, filename: croppedDocumentFilename(), content_type: 'image/jpeg' });
      } catch (cause) {
        if (active) setError((cause as Error).message || 'No se ha podido recortar la imagen.');
      }
    };
    void prepare();
    return () => { active = false; };
  }, [request.uri]);

  return (
    <View style={styles.root}>
      <View style={styles.card}>
        <Text style={styles.title}>Revisar recorte</Text>
        {result ? <Image source={{ uri: result.uri }} style={styles.preview} resizeMode="contain" /> : <ActivityIndicator size="large" color="#1f5fbf" />}
        {error ? <Text style={styles.error}>{error}</Text> : <Text style={styles.hint}>Hemos ajustado la imagen al formato del documento. Puedes volver a capturarla si el encuadre no es correcto.</Text>}
        <View style={styles.actions}>
          <Pressable style={styles.secondary} onPress={onCancel}><Text style={styles.secondaryLabel}>Descartar</Text></Pressable>
          <Pressable style={[styles.primary, !result ? styles.disabled : null]} disabled={!result} onPress={() => result && onComplete(result)}><Text style={styles.primaryLabel}>Usar imagen</Text></Pressable>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { position: 'absolute', inset: 0, zIndex: 100, backgroundColor: 'rgba(15, 23, 42, 0.78)', alignItems: 'center', justifyContent: 'center', padding: 20 },
  card: { width: '100%', maxWidth: 520, maxHeight: '92%', backgroundColor: '#ffffff', borderRadius: 16, padding: 18, gap: 14 },
  title: { fontSize: 20, fontWeight: '700', color: '#1f2937' },
  preview: { width: '100%', height: 420, backgroundColor: '#eef2f7', borderRadius: 10 },
  hint: { color: '#53657d', lineHeight: 20 },
  error: { color: '#a43d3d' },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', gap: 10 },
  primary: { minHeight: 44, paddingHorizontal: 18, borderRadius: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: '#1f5fbf' },
  secondary: { minHeight: 44, paddingHorizontal: 18, borderRadius: 8, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: '#1f5fbf' },
  primaryLabel: { color: '#ffffff', fontWeight: '700' },
  secondaryLabel: { color: '#1f5fbf', fontWeight: '700' },
  disabled: { opacity: 0.45 },
});
