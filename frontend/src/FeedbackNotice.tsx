import { Snackbar } from 'react-native-paper';

type FeedbackNoticeProps = {
  message?: string;
  error?: string;
  onClosed?: () => void;
};

export function FeedbackNotice({ message, error, onClosed }: FeedbackNoticeProps) {
  const text = error || message;
  if (!text) return null;

  return (
    <Snackbar
      visible
      onDismiss={() => onClosed?.()}
      duration={4200}
      action={{ label: 'Cerrar', onPress: () => onClosed?.() }}
      style={{ backgroundColor: error ? '#a43d3d' : '#1c7c54' }}
    >
      {text}
    </Snackbar>
  );
}
