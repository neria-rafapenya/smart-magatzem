import type { ReactNode } from 'react';

export type CropRequest = {
  uri: string;
  filename: string;
  content_type: string;
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
  onComplete: (result: CropResult) => void;
};

// El recorte interactivo solo se monta en web. En móvil el recortador nativo
// de expo-image-picker se abre antes de llegar a este componente.
export function DocumentCropper(_props: DocumentCropperProps): ReactNode {
  return null;
}
