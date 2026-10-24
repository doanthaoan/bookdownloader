import React, { useState } from 'react';
import { translateApi, errMsg } from '../../api';

/** Shared button look for this panel. */
const BTN = 'text-white px-5 py-2 rounded text-sm font-medium transition';

/**
 * Ask the backend which translate method to use ('api' or 'web').
 * Falls back to 'api' if the check fails.
 * @returns {Promise<string>}
 */
const getTranslateMethod = async () => {
  try {
    const res = await translateApi.prepare();
    return res.data.method || 'api';
  } catch (err) {
    return 'api';
  }
};

/**
 * Action panel for translated books: Continue / Re-translate failed chapters,
 * Refresh Cookie, Translate All (until completed), Cancel while running,
 * plus the shared DOCX links.
 *
 * Start endpoints return HTTP 409 when a job is already running; errMsg()
 * shows the backend's message.
 *
 * @param {object} props
 * @param {number} props.bookId
 * @param {boolean} props.downloading - a translation job is running
 * @param {boolean} props.isCompleted - book status is completed(_with_errors)
 * @param {number} props.failedCount
 * @param {number} props.totalChapters
 * @param {React.ReactNode} props.docxLinks - <DocxLinks/> element appended to the row
 * @param {() => void} props.onJobStarted - parent starts polling
 * @param {() => void} props.onJobCancelled - parent stops polling and reloads
 */
const TranslateActions = ({ bookId, downloading, isCompleted, failedCount, totalChapters, docxLinks, onJobStarted, onJobCancelled }) => {
  const [maxChapters, setMaxChapters] = useState('');

  /**
   * Shared runner: confirm (optional) → pick method → call the start endpoint → notify parent.
   * @param {(method: string) => Promise<any>} start - API call to make
   * @param {string} label - used in the error message
   * @param {string} [confirmText] - ask first when given
   */
  const runJob = async (start, label, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    try {
      const method = await getTranslateMethod();
      await start(method);
      onJobStarted();
    } catch (err) {
      alert(`${label} failed: ` + errMsg(err));
    }
  };

  /** Translate pending chapters (API call: run), honoring the Max box. */
  const handleTranslateAll = () => {
    const val = parseInt(maxChapters, 10);
    return runJob(method => translateApi.run(bookId, method, val > 0 ? val : null), 'Translate');
  };

  /** Re-translate failed chapters (API call: retranslate). */
  const handleRetranslate = () => runJob(
    method => translateApi.retranslate(bookId, method),
    'Re-translate',
    'Re-translate failed chapters?',
  );

  /** Reset failed chapters to pending and translate them again (API call: continueRun). */
  const handleContinue = () => runJob(
    method => translateApi.continueRun(bookId, method),
    'Continue',
    'Continue failed chapters? Use after updating the Cloudflare cookie.',
  );

  /** Open Chrome so Cloudflare issues a fresh cookie (API call: refreshCookies; waits until done). */
  const handleRefreshCookie = async () => {
    try {
      alert('A Chrome window will open so Cloudflare can issue a fresh cookie.\n' +
            'If a challenge appears, click it once and wait.');
      const res = await translateApi.refreshCookies();
      alert(res.data.ok ? 'Fresh cookie captured and saved.' : 'Could not capture a fresh cookie.');
    } catch (err) {
      alert('Cookie refresh failed: ' + errMsg(err));
    }
  };

  /** Cancel the running translation (API call: cancel). */
  const handleCancel = async () => {
    if (!confirm('Cancel translation? Progress will be saved.')) return;
    try {
      await translateApi.cancel(bookId);
      onJobCancelled();
    } catch (err) {
      alert('Cancel failed: ' + errMsg(err));
    }
  };

  return (
    <div className="flex flex-wrap gap-2 items-center">
      <div className="flex items-center gap-1 mr-1">
        <label className="text-xs text-gray-500 whitespace-nowrap">Max:</label>
        <input type="number" min="0" value={maxChapters}
          onChange={e => setMaxChapters(e.target.value)}
          placeholder="no limit"
          className="w-20 border rounded px-2 py-1.5 text-sm text-center" />
      </div>
      {downloading ? (
        <button onClick={handleCancel} className={`bg-red-600 hover:bg-red-700 ${BTN}`}>
          Cancel Translate
        </button>
      ) : (
        <>
          {/* Once completed, Continue is shown only when there is something to continue. */}
          {(!isCompleted || failedCount > 0) && (
            <button onClick={handleContinue} disabled={failedCount === 0}
              className={`bg-teal-600 hover:bg-teal-700 disabled:bg-gray-400 ${BTN}`}
              title="Reset failed chapters to pending and translate them again">
              Continue ({failedCount} failed)
            </button>
          )}
          <button onClick={handleRetranslate} disabled={failedCount === 0}
            className={`bg-orange-600 hover:bg-orange-700 disabled:bg-gray-400 ${BTN}`}>
            Re-translate ({failedCount} failed)
          </button>
          <button onClick={handleRefreshCookie}
            className={`bg-gray-600 hover:bg-gray-700 ${BTN}`}
            title="Open Chrome to refresh the cf_clearance cookie">
            Refresh Cookie
          </button>
          {isCompleted ? (
            <span className="text-xs bg-cyan-100 text-cyan-700 px-3 py-1.5 rounded font-medium">
              Translated book — content produced by the Translate tool.
            </span>
          ) : (
            <button onClick={handleTranslateAll} disabled={totalChapters === 0}
              className={`bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 ${BTN}`}>
              Translate All
            </button>
          )}
        </>
      )}
      {docxLinks}
    </div>
  );
};

export default TranslateActions;
