import React from 'react';
import { bookApi } from '../../api';

/**
 * DOCX buttons shared by both action panels: Export Corrected and
 * Open Corrected DOCX. Export is the ONLY way a DOCX gets written (downloads
 * and translations never export automatically). Presentational; the export
 * itself runs in the parent.
 *
 * @param {object} props
 * @param {number} props.bookId
 * @param {boolean} props.hasContent - at least one completed chapter (enables Export)
 * @param {boolean} props.correctedDocxExists
 * @param {boolean} props.exporting - disables Export while an export runs
 * @param {() => void} props.onExportCorrected
 * @param {string} props.exportTitle - tooltip for the Export button
 */
const DocxLinks = ({ bookId, hasContent, correctedDocxExists, exporting, onExportCorrected, exportTitle }) => (
  // Fragment: the buttons flow into the parent's flex row.
  <>
    {hasContent && (
      <button onClick={onExportCorrected} disabled={exporting}
        className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition"
        title={exportTitle}>
        Export Corrected
      </button>
    )}
    {correctedDocxExists && (
      // rel="noopener noreferrer": the new tab gets no window.opener access to this page.
      <a href={bookApi.exportCorrectedDocxUrl(bookId)} target="_blank" rel="noopener noreferrer"
        className="bg-emerald-700 hover:bg-emerald-800 text-white px-5 py-2 rounded text-sm font-medium transition inline-block">
        Open Corrected DOCX
      </a>
    )}
  </>
);

export default DocxLinks;
