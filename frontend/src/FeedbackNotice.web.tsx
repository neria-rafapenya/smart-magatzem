import { useEffect } from 'react';

type FeedbackNoticeProps = {
  message?: string;
  error?: string;
};

export function FeedbackNotice({ message, error }: FeedbackNoticeProps) {
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
        showConfirmButton: false,
        timer: 4200,
        timerProgressBar: true,
      });
    });
    return () => {
      active = false;
    };
  }, [error, message]);

  return null;
}
