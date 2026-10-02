import type { UploadDocument } from './documentUploadUtils';
import { MAX_DOCUMENT_BYTES } from './documentUploadConstants';

function base64Bytes(value: string): number {
  return Math.ceil(value.replace(/^data:[^,]+,/, '').length * 3 / 4);
}

async function loadImage(uri: string): Promise<HTMLImageElement> {
  const image = new Image();
  image.src = uri;
  await image.decode();
  return image;
}

export async function compressDocumentForUpload(uploadDocument: UploadDocument): Promise<UploadDocument> {
  if (!uploadDocument.content_type.startsWith('image/') || base64Bytes(uploadDocument.content_base64) <= MAX_DOCUMENT_BYTES) {
    return uploadDocument;
  }
  if (!uploadDocument.preview_uri) {
    throw new Error('No se puede comprimir la imagen antes de subirla.');
  }

  const image = await loadImage(uploadDocument.preview_uri);
  let scale = Math.min(1, 1800 / Math.max(image.width, image.height));
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const canvas = globalThis.document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('No se ha podido preparar la compresión de la imagen.');
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const quality = Math.max(0.25, 0.86 - attempt * 0.07);
    const dataUrl = canvas.toDataURL('image/jpeg', quality);
    const base64 = dataUrl.split(',', 2)[1] ?? '';
    if (base64Bytes(base64) <= MAX_DOCUMENT_BYTES) {
      return { ...uploadDocument, content_type: 'image/jpeg', content_base64: base64, preview_uri: dataUrl };
    }
    scale *= 0.82;
  }
  throw new Error('No se ha podido reducir la imagen por debajo de 2 MB.');
}
