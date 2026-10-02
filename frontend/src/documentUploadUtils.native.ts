import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';

import type { UploadDocument } from './documentUploadUtils';
import { MAX_DOCUMENT_BYTES } from './documentUploadConstants';

function base64Bytes(value: string): number {
  return Math.ceil(value.replace(/^data:[^,]+,/, '').length * 3 / 4);
}

export async function compressDocumentForUpload(document: UploadDocument): Promise<UploadDocument> {
  if (!document.content_type.startsWith('image/') || base64Bytes(document.content_base64) <= MAX_DOCUMENT_BYTES) {
    return document;
  }
  if (!document.preview_uri) {
    throw new Error('No se puede comprimir la imagen antes de subirla.');
  }

  let last = document;
  for (const width of [1800, 1500, 1200, 1000, 800]) {
    for (const compress of [0.82, 0.68, 0.54, 0.4, 0.28]) {
      const result = await manipulateAsync(
        document.preview_uri,
        [{ resize: { width } }],
        { base64: true, compress, format: SaveFormat.JPEG },
      );
      if (!result.base64) continue;
      last = { ...document, content_type: 'image/jpeg', content_base64: result.base64, preview_uri: result.uri };
      if (base64Bytes(result.base64) <= MAX_DOCUMENT_BYTES) return last;
    }
  }
  throw new Error('No se ha podido reducir la imagen por debajo de 2 MB.');
}
