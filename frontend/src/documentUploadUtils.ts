export type UploadDocument = {
  filename: string;
  content_type: string;
  content_base64: string;
  preview_uri?: string;
};

export async function compressDocumentForUpload(document: UploadDocument): Promise<UploadDocument> {
  return document;
}
