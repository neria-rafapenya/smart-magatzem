import { Snackbar } from 'react-native-paper';

type FeedbackNoticeProps = {
  message?: string;
  error?: string;
};

export function FeedbackNotice({ message, error }: FeedbackNoticeProps) {
  const text = error || message;
  if (!text) return null;

  return (
    <Snackbar
      visible
      onDismiss={() => undefined}
      duration={4200}
      action={{ label: 'Cerrar', onPress: () => undefined }}
      style={{ backgroundColor: error ? '#a43d3d' : '#1c7c54' }}
    >
      {text}
    </Snackbar>
  );
}
