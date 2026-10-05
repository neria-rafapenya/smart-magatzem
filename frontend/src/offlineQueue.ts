import AsyncStorage from '@react-native-async-storage/async-storage';

import type { IntakePayload } from './api';

export type QueuedSubmission = {
  id: string;
  tenant_id: string;
  created_at: string;
  attempts: number;
  payload: IntakePayload;
};

const queueKey = (tenantId: string) => `@smart-magatzem/offline-queue/${tenantId}`;

export async function getOfflineQueue(tenantId: string): Promise<QueuedSubmission[]> {
  const value = await AsyncStorage.getItem(queueKey(tenantId));
  if (!value) return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is QueuedSubmission => Boolean(item && typeof item === 'object' && 'payload' in item)) : [];
  } catch {
    return [];
  }
}

async function saveOfflineQueue(tenantId: string, queue: QueuedSubmission[]) {
  await AsyncStorage.setItem(queueKey(tenantId), JSON.stringify(queue.slice(-10)));
}

export async function enqueueSubmission(tenantId: string, payload: IntakePayload): Promise<QueuedSubmission> {
  const item: QueuedSubmission = {
    id: `QUE-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    tenant_id: tenantId,
    created_at: new Date().toISOString(),
    attempts: 0,
    payload,
  };
  const queue = await getOfflineQueue(tenantId);
  await saveOfflineQueue(tenantId, [...queue, item]);
  return item;
}

export async function removeQueuedSubmission(tenantId: string, id: string) {
  const queue = await getOfflineQueue(tenantId);
  await saveOfflineQueue(tenantId, queue.filter((item) => item.id !== id));
}

export async function markQueuedSubmissionAttempt(tenantId: string, id: string) {
  const queue = await getOfflineQueue(tenantId);
  await saveOfflineQueue(tenantId, queue.map((item) => item.id === id ? { ...item, attempts: item.attempts + 1 } : item));
}
