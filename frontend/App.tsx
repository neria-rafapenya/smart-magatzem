import { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { ActivityIndicator, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { MD3LightTheme, PaperProvider } from 'react-native-paper';

import { AUTH_PROVIDER, getCurrentUser, setAccessToken, setTenantId } from './src/api';
import { clearAuthSession, loadAuthSession, saveAuthSession } from './src/authStorage';
import { refreshCognitoSession, signOutCognito } from './src/cognito';
import { InboundDeliveryScreen } from './src/InboundDeliveryScreen';
import { LoginScreen } from './src/LoginScreen';
import type { AuthSession } from './src/types';

export default function App() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);

  useEffect(() => {
    let active = true;
    const restore = async () => {
      const saved = await loadAuthSession();
      if (!saved) {
        if (active) setSession(null);
        return;
      }
      let restored = saved;
      if (AUTH_PROVIDER === 'cognito') {
        try {
          restored = (await refreshCognitoSession(saved.user.email)) ?? saved;
        } catch {
          // El backend será quien determine si el token almacenado sigue siendo válido.
        }
      }
      setAccessToken(restored.access_token);
      setTenantId(restored.user.tenant_id);
      try {
        const currentUser = await getCurrentUser();
        const current = { ...restored, user: currentUser.user };
        await saveAuthSession(current);
        if (active) setSession(current);
      } catch {
        setAccessToken(null);
        await clearAuthSession();
        if (active) setSession(null);
      }
    };
    void restore();
    return () => { active = false; };
  }, []);

  const handleAuthenticated = async (nextSession: AuthSession) => {
    await saveAuthSession(nextSession);
    setSession(nextSession);
  };

  const logout = async () => {
    if (AUTH_PROVIDER === 'cognito') signOutCognito();
    setAccessToken(null);
    setTenantId(null);
    await clearAuthSession();
    setSession(null);
  };

  return (
    <SafeAreaProvider>
      <PaperProvider
        theme={theme}
        settings={{
          icon: (props) => <MaterialCommunityIcons {...props} />,
        }}
      >
        {session === undefined ? (
          <View style={styles.loadingRoot}>
            <ActivityIndicator size="large" color="#1f5fbf" />
          </View>
        ) : session ? (
          <InboundDeliveryScreen session={session} onLogout={() => { void logout(); }} />
        ) : (
          <LoginScreen onAuthenticated={(nextSession) => { void handleAuthenticated(nextSession); }} />
        )}
      </PaperProvider>
      <StatusBar style="auto" />
    </SafeAreaProvider>
  );
}

const styles = {
  loadingRoot: { flex: 1, alignItems: 'center' as const, justifyContent: 'center' as const, backgroundColor: '#f5f7fb' },
};

const theme = {
  ...MD3LightTheme,
  colors: {
    ...MD3LightTheme.colors,
    primary: '#1f5fbf',
    secondary: '#53657d',
    background: '#f5f7fb',
    surface: '#ffffff',
  },
};
