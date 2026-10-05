import { useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { Button, Text } from 'react-native-paper';
import type { AuthSession } from './types';

// Incrementamos la versión para que los usuarios que probaron la primera
// implementación vuelvan a ver el tutorial corregido una sola vez.
const ONBOARDING_VERSION = 2;

const SPOTLIGHTS = [
  { top: '21%', height: 190 },
  { top: '43%', height: 220 },
  { top: '58%', height: 230 },
] as const;

const STEPS = [
  {
    icon: 'file-document-outline' as const,
    title: 'Elige el tipo de documento',
    body: 'Empieza seleccionando Pedido, Albarán, Factura u otro tipo. También puedes dejarlo en Automático.',
    hint: 'Paso 1 · Selección',
  },
  {
    icon: 'camera-outline' as const,
    title: 'Captura o sube el documento',
    body: 'Después podrás usar la cámara o cargar una imagen. El recorte y la mejora de lectura preparan el documento para la IA.',
    hint: 'Paso 2 · Captura',
  },
  {
    icon: 'check-decagram-outline' as const,
    title: 'Revisa antes de enviarlo',
    body: 'La aplicación muestra los campos detectados. Corrige solo lo necesario y envía el documento al ERP cuando todo sea correcto.',
    hint: 'Paso 3 · Revisión',
  },
];

function onboardingKey(session: AuthSession) {
  return `smart-magatzem:onboarding:${session.user.user_id}:${session.user.tenant_id}:v${ONBOARDING_VERSION}`;
}

export function OnboardingCoach({ session }: { session: AuthSession }) {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);
  const storageKey = onboardingKey(session);

  useEffect(() => {
    let active = true;
    void AsyncStorage.getItem(storageKey).then((value) => {
      if (active && value !== 'completed') setVisible(true);
    });
    return () => {
      active = false;
    };
  }, [storageKey]);

  const finish = () => {
    setVisible(false);
    void AsyncStorage.setItem(storageKey, 'completed');
  };

  const current = STEPS[step];
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={finish}>
      <View style={styles.overlay}>
        <Pressable accessibilityLabel="Saltar tutorial" onPress={finish} style={styles.dismissArea} />
        <View style={[styles.spotlight, SPOTLIGHTS[step]]} />
        <View style={styles.tooltip} accessibilityViewIsModal>
          <View style={styles.iconCircle}>
            <MaterialCommunityIcons name={current.icon} size={30} color="#1f5fbf" />
          </View>
          <Text variant="labelLarge" style={styles.stepLabel}>{current.hint}</Text>
          <Text variant="headlineSmall" style={styles.title}>{current.title}</Text>
          <Text variant="bodyMedium" style={styles.body}>{current.body}</Text>
          <View style={styles.progress}>
            {STEPS.map((item, index) => (
              <View key={item.hint} style={[styles.progressDot, index === step && styles.progressDotActive]} />
            ))}
          </View>
          <View style={styles.actions}>
            <Button mode="text" onPress={finish}>Saltar</Button>
            {step > 0 ? <Button mode="text" onPress={() => setStep((value) => value - 1)}>Atrás</Button> : null}
            <Button mode="contained" onPress={() => step === STEPS.length - 1 ? finish() : setStep((value) => value + 1)}>
              {step === STEPS.length - 1 ? 'Empezar' : 'Siguiente'}
            </Button>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(15, 23, 42, 0.68)',
    alignItems: 'center',
    justifyContent: 'flex-end',
    padding: 24,
  },
  spotlight: {
    position: 'absolute',
    width: '88%',
    borderRadius: 22,
    borderWidth: 2,
    borderColor: '#8fb7f2',
    backgroundColor: 'rgba(255, 255, 255, 0.08)',
    zIndex: 0,
  },
  tooltip: {
    width: '100%',
    maxWidth: 460,
    borderRadius: 20,
    padding: 24,
    backgroundColor: '#ffffff',
    elevation: 8,
    shadowColor: '#000000',
    shadowOpacity: 0.24,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    zIndex: 2,
    marginBottom: 8,
  },
  iconCircle: { width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center', backgroundColor: '#e8f0ff', marginBottom: 12 },
  stepLabel: { color: '#1f5fbf', marginBottom: 6 },
  title: { color: '#172b4d', marginBottom: 8 },
  body: { color: '#53657d', lineHeight: 22 },
  progress: { flexDirection: 'row', gap: 7, marginTop: 22, marginBottom: 12 },
  progressDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#cbd5e1' },
  progressDotActive: { width: 24, backgroundColor: '#1f5fbf' },
  actions: { flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 4 },
  dismissArea: { ...StyleSheet.absoluteFill, zIndex: 1 },
});
