export type LocalCaptureQuality = {
  status: 'good' | 'needs_review' | 'unavailable';
  score: number;
  reasons: string[];
  metrics: { width?: number; height?: number; brightness?: number; contrast?: number; sharpness?: number };
};

/**
 * Comprobación ligera en el dispositivo/navegador. No sustituye al lector:
 * sirve para avisar antes de gastar una petición de IA en una captura obvia.
 */
export async function inspectLocalImageQuality(uri: string): Promise<LocalCaptureQuality> {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    return { status: 'unavailable', score: 0, reasons: [], metrics: {} };
  }

  return new Promise((resolve) => {
    const image = new window.Image();
    image.onload = () => {
      const maxSide = 720;
      const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
      const width = Math.max(1, Math.round(image.naturalWidth * scale));
      const height = Math.max(1, Math.round(image.naturalHeight * scale));
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      if (!context) {
        resolve({ status: 'unavailable', score: 0, reasons: [], metrics: { width: image.naturalWidth, height: image.naturalHeight } });
        return;
      }
      context.drawImage(image, 0, 0, width, height);
      const pixels = context.getImageData(0, 0, width, height).data;
      const luminance: number[] = [];
      for (let index = 0; index < pixels.length; index += 4) {
        luminance.push((pixels[index] * 0.299) + (pixels[index + 1] * 0.587) + (pixels[index + 2] * 0.114));
      }
      const average = luminance.reduce((sum, value) => sum + value, 0) / Math.max(1, luminance.length);
      const variance = luminance.reduce((sum, value) => sum + ((value - average) ** 2), 0) / Math.max(1, luminance.length);
      let edgeDelta = 0;
      let edgeSamples = 0;
      for (let y = 0; y < height; y += 3) {
        for (let x = 0; x < width; x += 3) {
          const current = luminance[(y * width) + x] ?? 0;
          const right = luminance[(y * width) + Math.min(width - 1, x + 1)] ?? current;
          const down = luminance[(Math.min(height - 1, y + 1) * width) + x] ?? current;
          edgeDelta += Math.abs(current - right) + Math.abs(current - down);
          edgeSamples += 2;
        }
      }
      const sharpness = Math.min(1, (edgeDelta / Math.max(1, edgeSamples)) / 22);
      const lighting = Math.max(0, 1 - Math.abs(128 - average) / 128);
      const contrast = Math.min(1, Math.sqrt(variance) / 72);
      const resolution = Math.min(1, (image.naturalWidth * image.naturalHeight) / 1_500_000);
      const score = Number((resolution * 0.25 + sharpness * 0.35 + lighting * 0.2 + contrast * 0.2).toFixed(3));
      const reasons: string[] = [];
      if (resolution < 0.55) reasons.push('resolución baja');
      if (sharpness < 0.34) reasons.push('posible desenfoque');
      if (lighting < 0.42) reasons.push('iluminación insuficiente');
      if (contrast < 0.28) reasons.push('contraste bajo');
      resolve({
        status: reasons.length ? 'needs_review' : 'good',
        score,
        reasons,
        metrics: { width: image.naturalWidth, height: image.naturalHeight, brightness: Number(average.toFixed(1)), contrast: Number(contrast.toFixed(3)), sharpness: Number(sharpness.toFixed(3)) },
      });
    };
    image.onerror = () => resolve({ status: 'unavailable', score: 0, reasons: [], metrics: {} });
    image.src = uri;
  });
}
