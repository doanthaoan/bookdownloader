import React from 'react';
import Modal from '../../components/Modal';

/**
 * Render a correction preview as spans: removed text struck through,
 * replacement text highlighted, unchanged text plain.
 * @param {{segments: {type: 'removed'|'replaced'|string, text: string}[]}} props
 */
export const CorrectionSegments = ({ segments }) => (
  // <>...</> is a Fragment: groups children without adding a DOM element.
  <>
    {segments.map((s, i) => {
      if (s.type === 'removed') {
        return <span key={i} className="line-through text-red-500">{s.text}</span>;
      }
      if (s.type === 'replaced') {
        return s.text
          ? <span key={i} className="bg-yellow-200 rounded px-0.5">{s.text}</span>
          : null;
      }
      return <span key={i}>{s.text}</span>;
    })}
  </>
);

/**
 * Modal showing how one chapter looks after corrections (nothing is saved).
 * Open whenever `preview` is not null.
 * @param {{preview: object|null, onClose: () => void}} props
 *   preview: response of bookApi.previewCorrection (title/content + *_segments, chapter_order)
 */
const CorrectionPreviewModal = ({ preview, onClose }) => (
  // `!!preview` → boolean; `preview?.x` reads safely while preview is null.
  <Modal open={!!preview} onClose={onClose} wide
    title={preview ? `Correction preview — Chương ${preview.chapter_order}` : ''}>
    <p className="text-xs text-gray-500 mb-3">
      This is how the chapter will look after corrections are applied.
      <span className="line-through text-red-500 ml-1">Struck text</span> was replaced by
      <span className="bg-yellow-200 rounded px-0.5 mx-1">highlighted text</span>.
      Nothing is saved.
    </p>
    <h3 className="text-base font-semibold text-gray-800 mb-3">
      {/* Fall back to the plain text when the backend sent no segments. */}
      {preview?.title_segments?.some(s => s.text)
        ? <CorrectionSegments segments={preview.title_segments} />
        : preview?.title}
    </h3>
    <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
      {preview?.content_segments?.some(s => s.text)
        ? <CorrectionSegments segments={preview.content_segments} />
        : (preview?.content || '(no content stored)')}
    </div>
  </Modal>
);

export default CorrectionPreviewModal;
