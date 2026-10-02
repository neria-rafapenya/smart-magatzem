import AsyncStorage from '@react-native-async-storage/async-storage';

import type { AuthSession } from './types';

const SESSION_KEY = '@smart-magatzem/auth-session';

export async function loadAuthSession(): Promise<AuthSession | null> {
  const value = await AsyncStorage.getItem(SESSION_KEY);
  if (!value) return null;
  try {
    const session = JSON.parse(value) as AuthSession;
    return session?.access_token && session?.user ? session : null;
  } catch {
    await AsyncStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export async function saveAuthSession(session: AuthSession) {
  await AsyncStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export async function clearAuthSession() {
  await AsyncStorage.removeItem(SESSION_KEY);
}

