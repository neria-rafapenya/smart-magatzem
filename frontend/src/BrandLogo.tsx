import { Image, Platform, StyleSheet, View } from 'react-native';

const logoSource = require('../assets/logo-smart-magatzem-blanco.svg');
// Expo Go Android no resuelve de forma fiable SVG locales mediante SvgUri.
// Este PNG se genera a partir del SVG original y queda empaquetado en la app.
const nativeLogoSource = require('../assets/logo-smart-magatzem-blanco.png');

export function BrandLogo({ width = 168, height = 28 }: { width?: number; height?: number }) {
  return (
    <View style={[styles.container, { width, height }]} accessibilityLabel="Smart Magatzem">
      <Image
        source={Platform.OS === 'web' ? logoSource : nativeLogoSource}
        style={{ width, height }}
        resizeMode="contain"
        accessibilityLabel="Smart Magatzem"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { overflow: 'hidden', justifyContent: 'center' },
});
