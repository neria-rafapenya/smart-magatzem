import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
  CognitoUserSession,
} from 'amazon-cognito-identity-js';

import type { AuthSession } from './types';

declare const process: { env: {
  EXPO_PUBLIC_AWS_REGION?: string;
  EXPO_PUBLIC_COGNITO_USER_POOL_ID?: string;
  EXPO_PUBLIC_COGNITO_CLIENT_ID?: string;
} };

const userPoolId = process.env.EXPO_PUBLIC_COGNITO_USER_POOL_ID ?? '';
const clientId = process.env.EXPO_PUBLIC_COGNITO_CLIENT_ID ?? '';

function pool() {
  if (!userPoolId || !clientId) {
    throw new Error('Falta configurar EXPO_PUBLIC_COGNITO_USER_POOL_ID y EXPO_PUBLIC_COGNITO_CLIENT_ID.');
  }
  return new CognitoUserPool({ UserPoolId: userPoolId, ClientId: clientId });
}

function identityFromSession(session: CognitoUserSession, email: string) {
  const accessToken = session.getAccessToken().getJwtToken();
  const idToken = session.getIdToken().getJwtToken();
  // CognitoJwtToken ya incluye un decodificador base64 compatible con web,
  // React Native y los tokens base64url emitidos por Cognito.
  const claims = session.getIdToken().decodePayload() as Record<string, unknown>;
  const groups = Array.isArray(claims['cognito:groups']) ? claims['cognito:groups'].map(String) : [];
  const isAdmin = groups.includes('admin');
  return {
    access_token: accessToken,
    token_type: 'Bearer' as const,
    provider: 'cognito',
    user: {
      user_id: String(claims.sub ?? ''),
      email: String(claims.email ?? email),
      tenant_id: String(claims['custom:tenant_id'] ?? 'TEN-DEMO'),
      roles: groups.length > 0 ? groups : ['guest'],
      permissions: isAdmin ? ['*'] : ['document.read'],
    },
  } satisfies AuthSession;
}

export async function loginWithCognito(email: string, password: string): Promise<AuthSession> {
  const user = new CognitoUser({ Username: email, Pool: pool() });
  const details = new AuthenticationDetails({ Username: email, Password: password });
  return new Promise((resolve, reject) => {
    user.authenticateUser(details, {
      onSuccess: (session) => resolve(identityFromSession(session, email)),
      onFailure: reject,
      newPasswordRequired: () => reject(new Error('Cognito requiere cambiar la contraseña temporal antes de continuar.')),
    });
  });
}

export function signOutCognito() {
  try {
    pool().getCurrentUser()?.signOut();
  } catch {
    // Si el proveedor no está configurado, el cierre local sigue siendo válido.
  }
}
