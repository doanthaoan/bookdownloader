import React, { useEffect } from 'react';

/**
 * Simple modal dialog. Closes on Escape, backdrop click, or the ✕ button.
 * @param {{open: boolean, onClose: () => void, title: string, children: React.ReactNode, wide?: boolean}} props
 *   `wide` switches from max-w-2xl to max-w-4xl.
 */
const Modal = ({ open, onClose, title, children, wide = false }) => {
  // Listen for Escape only while open. The returned function is the effect
  // cleanup: React calls it before re-running the effect and on unmount, so
  // the global listener never leaks.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4"
      onClick={onClose}
    >
      {/* stopPropagation: clicks inside the dialog must not reach the backdrop's onClick. */}
      <div
        className={`bg-white rounded-xl shadow-xl w-full ${wide ? 'max-w-4xl' : 'max-w-2xl'} my-8`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl leading-none px-1 transition"
            title="Close"
          >
            ✕
          </button>
        </div>
        <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">{children}</div>
      </div>
    </div>
  );
};

export default Modal;
