import { useEffect } from 'react';

type FeedbackNoticeProps = {
  message?: string;
  error?: string;
  onClosed?: () => void;
};

export function FeedbackNotice({ message, error, onClosed }: FeedbackNoticeProps) {
  useEffect(() => {
    const text = error || message;
    if (!text) return;

    let active = true;
    void import('sweetalert2').then(({ default: Swal }) => {
      if (!active) return;
      void Swal.fire({
        toast: true,
        position: 'top-end',
        icon: error ? 'error' : 'success',
        title: error ? 'No se ha podido completar' : 'Operación completada',
        text,
        showCloseButton: true,
        showConfirmButton: false,
        timer: 4200,
        timerProgressBar: true,
      }).then(() => onClosed?.());
    });
    return () => {
      active = false;
    };
  }, [error, message, onClosed]);

  return null;
}
