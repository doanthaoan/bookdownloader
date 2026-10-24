import React, { useState } from 'react';
import { bookApi, errMsg } from '../../api';
import { WEB_STATUS_UPDATABLE } from '../../constants';

/** Shared button look for this panel. */
// TODO: a small <Btn color=...> component would remove these long class strings across pages.
const BTN = 'text-white px-5 py-2 rounded text-sm font-medium transition';

/**
 * Action panel for downloaded (scraped) books: Download, Re-download
 * (failed / range / all), Update & Download, Refresh Info, Continue Extract,
 * plus the shared DOCX links. While a job runs, shows only Cancel.
 *
 * Each handler calls the API itself, then tells the parent what happened:
 * `onJobStarted` (parent starts polling), `onJobCancelled`, or `onRefresh`.
 *
 * @param {object} props
 * @param {object} props.book - book row (id, book_url, book_web_status)
 * @param {boolean} props.downloading - a job is running
 * @param {boolean} props.isCompleted - book status is completed(_with_errors)
 * @param {number} props.failedCount
 * @param {number} props.totalChapters
 * @param {React.ReactNode} props.docxLinks - <DocxLinks/> element rendered in the "Others" row
 * @param {() => void} props.onJobStarted
 * @param {() => void} props.onJobCancelled
 * @param {() => void} props.onRefresh
 */
const DownloadActions = ({ book, downloading, isCompleted, failedCount, totalChapters, docxLinks, onJobStarted, onJobCancelled, onRefresh }) => {
  const bookId = book.id;
  // Form inputs used only by this panel, so the state lives here.
  const [maxChapters, setMaxChapters] = useState('');
  const [redownloadFrom, setRedownloadFrom] = useState('');
  const [redownloadTo, setRedownloadTo] = useState('');

  /**
   * Parse the "Max" box into API params ({} when empty = no limit).
   * @returns {{max_chapters?: number}}
   */
  const maxChaptersParams = () => {
    const val = parseInt(maxChapters, 10);
    return val > 0 ? { max_chapters: val } : {};
  };

  /** Start downloading pending chapters (API call: download). */
  const handleDownload = async () => {
    try {
      await bookApi.download(bookId, maxChaptersParams());
      onJobStarted();
    } catch (err) {
      alert('Download failed: ' + errMsg(err));
    }
  };

  /**
   * Shared runner for the re-download variants (API call: redownload).
   * @param {object} params - redownload query params
   * @param {string} confirmText - confirmation question
   * @param {string} label - used in the error message
   */
  const runRedownload = async (params, confirmText, label = 'Re-download') => {
    if (!confirm(confirmText)) return;
    try {
      await bookApi.redownload(bookId, params);
      onJobStarted();
    } catch (err) {
      alert(`${label} failed: ` + errMsg(err));
    }
  };

  /** Re-download chapters From..To (by chapter_order), after validating the range. */
  const handleRedownloadRange = () => {
    const from = parseInt(redownloadFrom, 10);
    const to = parseInt(redownloadTo, 10);
    // `!(from > 0)` is also true for NaN (empty box), unlike `from <= 0`.
    if (!(from > 0) || !(to > 0) || to < from) {
      alert('Enter a valid range (From ≤ To).');
      return;
    }
    runRedownload(
      { start_order: from, end_order: to },
      `Re-download chapters ${from} to ${to}? Their stored content will be replaced.`,
    );
  };

  /** Cancel the running download (API call: cancelDownload). */
  const handleCancel = async () => {
    if (!confirm('Cancel download? Progress will be saved.')) return;
    try {
      await bookApi.cancelDownload(bookId);
      onJobCancelled();
    } catch (err) {
      alert('Cancel failed: ' + errMsg(err));
    }
  };

  /** Append newly published chapters to the list (API call: continueExtract). */
  const handleContinueExtract = async () => {
    if (!confirm('Check for new chapters and append them to the existing list?')) return;
    try {
      await bookApi.continueExtract(bookId);
      onJobStarted();
    } catch (err) {
      alert('Error: ' + errMsg(err));
    }
  };

  /** Re-scrape metadata (API call: refreshInfo), then reload. */
  const handleRefreshInfo = async () => {
    if (!confirm('Re-scrape book metadata (cover, description, author, status) from the web?')) return;
    try {
      const res = await bookApi.refreshInfo(bookId);
      alert('Book info refreshed: ' + res.data.updated_fields.join(', '));
      onRefresh();
    } catch (err) {
      alert('Error: ' + errMsg(err));
    }
  };

  /** Extract new chapters and download them (API call: updateFull). */
  const handleUpdateFull = async () => {
    if (!confirm('Check for updates, extract new chapters, and download them? This may take a while.')) return;
    try {
      await bookApi.updateFull(bookId, maxChaptersParams());
      onJobStarted();
    } catch (err) {
      alert('Error: ' + errMsg(err));
    }
  };

  if (downloading) {
    return (
      <div className="flex flex-wrap gap-2 items-center">
        <button onClick={handleCancel} className={`bg-red-600 hover:bg-red-700 ${BTN}`}>
          Cancel Download
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Download */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider w-30 flex-shrink-0">Download</span>
        <div className="flex items-center gap-1 mr-1">
          <label className="text-xs text-gray-500 whitespace-nowrap">Max:</label>
          <input type="number" min="0" value={maxChapters}
            onChange={e => setMaxChapters(e.target.value)}
            placeholder="no limit"
            className="w-20 border rounded px-2 py-1.5 text-sm text-center" />
        </div>
        <button onClick={handleDownload} disabled={totalChapters === 0}
          className={`bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 ${BTN}`}>
          Download All
        </button>
      </div>

      {/* Re-download */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider w-30 flex-shrink-0">Re-download</span>
        {!isCompleted && (
          <button
            onClick={() => runRedownload({ all_chapters: false }, 'Re-download failed chapters?')}
            disabled={failedCount === 0}
            className={`bg-orange-600 hover:bg-orange-700 disabled:bg-gray-400 ${BTN}`}>
            Re-download ({failedCount} failed)
          </button>
        )}
        <div className="flex items-center gap-1 mr-1">
          <label className="text-xs text-gray-500 whitespace-nowrap">From:</label>
          <input type="number" min="1" value={redownloadFrom}
            onChange={e => setRedownloadFrom(e.target.value)}
            placeholder="1"
            title="First chapter order to re-download"
            className="w-14 border rounded px-2 py-1.5 text-sm text-center" />
          <label className="text-xs text-gray-500 whitespace-nowrap">To:</label>
          <input type="number" min="1" value={redownloadTo}
            onChange={e => setRedownloadTo(e.target.value)}
            placeholder="10"
            title="Last chapter order to re-download"
            className="w-14 border rounded px-2 py-1.5 text-sm text-center" />
          <button onClick={handleRedownloadRange}
            className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 rounded text-sm font-medium transition"
            title="Re-download chapters in the given range">
            Re-download Range
          </button>
        </div>
        <button
          onClick={() => runRedownload(
            { all_chapters: true },
            'Re-download ALL chapters? The stored content of every chapter will be replaced.',
            'Re-download all',
          )}
          className={`bg-purple-600 hover:bg-purple-700 ${BTN}`}>
          Re-download All
        </button>
      </div>

      {/* Others */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider w-30 flex-shrink-0">Others</span>
        {book.book_url && (
          <>
            <button onClick={handleUpdateFull} className={`bg-teal-600 hover:bg-teal-700 ${BTN}`}>
              Update & Download
            </button>
            <button onClick={handleRefreshInfo} className={`bg-cyan-600 hover:bg-cyan-700 ${BTN}`}>
              Refresh Info
            </button>
          </>
        )}
        {/* Only ongoing/unverified books can have new chapters to append. */}
        {WEB_STATUS_UPDATABLE.includes(book.book_web_status) && (
          <button onClick={handleContinueExtract} className={`bg-indigo-600 hover:bg-indigo-700 ${BTN}`}>
            Continue Extract
          </button>
        )}
        {docxLinks}
      </div>
    </div>
  );
};

export default DownloadActions;
