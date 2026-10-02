import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';
import { Button, HelperText, Surface, Text, TextInput } from 'react-native-paper';

import { AUTH_PROVIDER, login } from './api';
import { BrandLogo } from './BrandLogo';
import type { AuthSession } from './types';

export function LoginScreen({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [email, setEmail] = useState(AUTH_PROVIDER === 'cognito' ? '' : 'operario@smart-magatzem.local');
  const [password, setPassword] = useState(AUTH_PROVIDER === 'cognito' ? '' : 'demo1234');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (!email.trim() || !password) {
      setError('Introduce el correo y la contraseña.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const session = await login(email.trim(), password);
      onAuthenticated(session);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Surface style={styles.card} elevation={2}>
          <View style={styles.brand}>
            <View style={styles.logoPanel}>
              <BrandLogo width={230} height={38} />
            </View>
            <Text variant="bodyLarge" style={styles.subtitle}>Acceso a la plataforma documental</Text>
          </View>

          <View style={styles.localNotice}>
            <Text variant="labelLarge" style={styles.localNoticeTitle}>{AUTH_PROVIDER === 'cognito' ? 'AWS Cognito' : 'Entorno local'}</Text>
            <Text variant="bodySmall" style={styles.localNoticeText}>
              {AUTH_PROVIDER === 'cognito'
                ? 'Este acceso usa Cognito. El tenant y el rol llegan en el token y se validan en la API.'
                : 'Este acceso usa el proveedor local. Más adelante se sustituirá por Cognito o SSO corporativo.'}
            </Text>
          </View>

          <TextInput
            label="Correo electrónico"
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            mode="outlined"
            disabled={submitting}
            style={styles.input}
          />
          <TextInput
            label="Contraseña"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
            mode="outlined"
            disabled={submitting}
            onSubmitEditing={() => { void submit(); }}
            style={styles.input}
          />

          {error ? <HelperText type="error" visible>{error}</HelperText> : null}

          <Button
            mode="contained"
            icon="login"
            loading={submitting}
            disabled={submitting}
            onPress={() => { void submit(); }}
            contentStyle={styles.submitContent}
          >
            Entrar
          </Button>

          {AUTH_PROVIDER === 'local' ? (
            <Text variant="bodySmall" style={styles.credentials}>
              Prueba local: admin@smart-magatzem.local, supervisor@smart-magatzem.local u operario@smart-magatzem.local · contraseña demo1234
            </Text>
          ) : null}
        </Surface>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#f5f7fb' },
  content: { flexGrow: 1, justifyContent: 'center', padding: 20 },
  card: { width: '100%', maxWidth: 460, alignSelf: 'center', padding: 24, borderRadius: 18, backgroundColor: '#ffffff', gap: 14 },
  brand: { gap: 4, marginBottom: 4 },
  logoPanel: { minHeight: 64, borderRadius: 12, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ffffff' },
  subtitle: { color: '#5d6b7c', textAlign: 'center' },
  localNotice: { padding: 12, borderRadius: 10, backgroundColor: '#eaf1ff', gap: 4 },
  localNoticeTitle: { color: '#1f5fbf' },
  localNoticeText: { color: '#53657d' },
  input: { backgroundColor: '#ffffff' },
  submitContent: { minHeight: 46 },
  credentials: { color: '#718096', textAlign: 'center', lineHeight: 18 },
});
