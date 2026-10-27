import React, { useState, useEffect, useRef } from 'react';
import { bookApi, translateApi, errMsg } from '../api';
import { isTranslated } from '../constants';
import Layout from '../components/Layout';
import useBookProgress from './book-details/useBookProgress';
import BookToolbar from './book-details/BookToolbar';
import EditInfoForm from './book-details/EditInfoForm';
import CorrectionsModal from './book-details/CorrectionsModal';
import BookHeader from './book-details/BookHeader';
import DocxLinks from './book-details/DocxLinks';
import DownloadActions from './book-details/DownloadActions';
import TranslateActions from './book-details/TranslateActions';
import CorrectionPreviewModal from './book-details/CorrectionPreviewModal';
import ChapterTable from './book-details/ChapterTable';

/**
 * Book detail page (container). Owns the data loading and polling and
 * passes data + callbacks down to the presentational pieces in
 * ./book-details/. Children that write data either report the result up
 * (CorrectionsModal → setCorrections) or ask for a reload (onRefresh), so
 * the next poll always agrees with what the user just saved.
 *
 * @param {{bookId: number, onBack: () => void}} props
 */
const BookDetails = ({ bookId, onBack }) => {
  const [book, setBook] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState(null);
  const [tags, setTags] = useState([]);
  const [corrections, setCorrections] = useState([]);
  const [correctedDocxExists, setCorrectedDocxExists] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [preview, setPreview] = useState(null);
  const [editOpen, setEditOpen] = useState(false);
  const [correctionsOpen, setCorrectionsOpen] = useState(false);

  // Polling + "job running" state. The arrow defers the lookup of fetchData
  // (declared below) until the interval actually fires.
  const { downloading, applyProgress, trackJob, cancelJob } = useBookProgress(() => fetchData('poll'));

  // "success/fail" counts seen at the last chapters reload during polling.
  // A ref (not state) because changing it must not re-render the page.
  const lastCountsRef = useRef('');

  /**
   * Load what the page shows and feed the job progress to the polling hook.
   * @param {'poll'|any} mode - 'poll' = cheap tick: fetch only the job
   *   progress, and reload book + chapters only when a chapter finished
   *   (success/fail count changed) or the job ended. Anything else (incl. a
   *   click event when used as a callback) = full reload, also tags,
   *   corrections and DOCX info.
   * Side effects: 1 (quiet poll), 3 (poll after a chapter finished) or 6-7
   *   (full) read-only API calls; sets state; may start/stop polling.
   * TODO: skip bookApi.getProgress for translated books (fetched but unused there).
   */
  const fetchData = async (mode) => {
    const full = mode !== 'poll';
    try {
      // `book` is from the latest render (the hook always calls the newest
      // fetchData), so we know which job tracker to ask.
      if (!full && book) {
        const p = (await (isTranslated(book) ? translateApi.progress(bookId) : bookApi.getProgress(bookId))
          .catch(() => ({ data: { active: false } }))).data;
        const counts = `${p.success_count}/${p.fail_count}`;
        if (p.active && counts === lastCountsRef.current) {
          // Nothing finished since the last reload: just update the progress bar.
          setProgress(p);
          applyProgress(p);
          return;
        }
        // A chapter finished (or the job ended): refresh its row status.
        lastCountsRef.current = counts;
        const [bookRes, chaptersRes] = await Promise.all([
          bookApi.getOne(bookId),
          bookApi.getChapters(bookId),
        ]);
        setBook(bookRes.data);
        setChapters(chaptersRes.data);
        setProgress(p);
        applyProgress(p);
        return;
      }

      // Optional requests get a .catch with a fallback so one failure
      // doesn't reject the whole Promise.all. In poll mode the extra slots
      // are `null` (Promise.all passes plain values through unchanged).
      const [bookRes, chaptersRes, progressRes, tagsRes, correctionsRes, correctedRes] = await Promise.all([
        bookApi.getOne(bookId),
        bookApi.getChapters(bookId),
        bookApi.getProgress(bookId).catch(() => ({ data: { active: false } })),
        full && bookApi.bookTags(bookId).catch(() => ({ data: { tags: [] } })),
        full && translateApi.corrections(bookId).catch(() => ({ data: [] })),
        full && bookApi.exportCorrectedDocxInfo(bookId).catch(() => ({ data: { exists: false } })),
      ]);
      setBook(bookRes.data);
      setChapters(chaptersRes.data);
      if (full) {
        setTags(tagsRes.data.tags);
        // Safe to overwrite: the modal edits its own copy (see CorrectionsModal).
        setCorrections(correctionsRes.data || []);
        setCorrectedDocxExists(correctedRes.data.exists);
      }

      // Translated books report progress from the translate job tracker.
      const p = isTranslated(bookRes.data)
        ? (await translateApi.progress(bookId).catch(() => ({ data: { active: false } }))).data
        : progressRes.data;
      setProgress(p);
      applyProgress(p);
    } catch (err) {
      console.error('Failed to fetch book details', err);
    } finally {
      setLoading(false);
    }
  };

  // Load when the book changes. Polling cleanup on unmount is in the hook.
  useEffect(() => {
    if (bookId) fetchData();
  }, [bookId]);

  /** A cancel request succeeded: stop polling and reload. */
  const handleJobCancelled = () => {
    cancelJob();
    fetchData();
  };

  /**
   * Render a corrected DOCX from stored content (API call: exportCorrected).
   * The DB is not modified; corrections are applied at render time.
   * @param {number[]} chapterIds - [] = whole book
   * @param {string} confirmText
   * @param {string} doneText - prefix for the success alert
   */
  const runExportCorrected = async (chapterIds, confirmText, doneText) => {
    if (!confirm(confirmText)) return;
    try {
      setExporting(true);
      const res = await bookApi.exportCorrected(bookId, chapterIds);
      setCorrectedDocxExists(true);
      alert(`${doneText}: ${res.data.file_name}`);
    } catch (err) {
      alert('Export failed: ' + errMsg(err));
    } finally {
      setExporting(false);
    }
  };

  /** Export the whole book as a corrected DOCX. */
  const handleExportCorrected = () => runExportCorrected(
    [],
    'Export the whole book as a corrected DOCX? Corrections are applied now; the database is not modified.',
    'Corrected DOCX exported',
  );

  /** Export one chapter into the corrected DOCX (replaces the whole-book file). */
  const handleExportChapter = (chapterId) => runExportCorrected(
    [chapterId],
    'Export ONLY this chapter into the corrected DOCX? (This replaces the whole-book corrected file.)',
    'Chapter exported into',
  );

  /**
   * Show how a chapter looks after corrections (API call: previewCorrection; opens the modal).
   * @param {number} chapterId
   */
  const handlePreview = async (chapterId) => {
    try {
      const res = await bookApi.previewCorrection(bookId, chapterId);
      setPreview(res.data);
    } catch (err) {
      alert('Preview failed: ' + errMsg(err));
    }
  };

  /**
   * Download (or re-download) one chapter (API call), then poll.
   * @param {number} chapterId
   */
  const handleChapterDownload = async (chapterId) => {
    try {
      await bookApi.downloadChapter(bookId, chapterId);
      trackJob();
    } catch (err) {
      alert('Chapter download failed: ' + errMsg(err));
    }
  };

  if (loading) return <div className="text-center py-10 text-gray-500">Loading book details...</div>;
  if (!book) return <div className="text-center py-10 text-red-500">Book not found</div>;

  // Derived values: recomputed each render (cheap, so no need for state).
  const completedChapters = chapters.filter(ch => ch.download_status === 'completed').length;
  const failedCount = chapters.filter(ch => ch.download_status === 'failed').length;
  const totalChapters = book.total_chapters || 0;
  const isCompleted = ['completed', 'completed_with_errors'].includes(book.download_status);
  const translated = isTranslated(book);

  // Built once here and handed to whichever action panel is shown.
  const docxLinks = (
    <DocxLinks
      bookId={bookId}
      hasContent={completedChapters > 0}
      correctedDocxExists={correctedDocxExists}
      exporting={exporting}
      onExportCorrected={handleExportCorrected}
      exportTitle={translated
        ? 'Render the book from stored content, applying global cleaning + corrections now'
        : 'Render the book from stored content, applying corrections now'}
    />
  );

  return (
    <Layout>
      <BookToolbar
        book={book}
        editOpen={editOpen}
        correctionsOpen={correctionsOpen}
        onBack={onBack}
        onToggleEdit={() => setEditOpen(open => !open)}
        onOpenCorrections={() => setCorrectionsOpen(true)}
        onChanged={fetchData}
      />

      {/* Mounted only while open, so each opening starts from fresh data. */}
      {editOpen && (
        <EditInfoForm
          book={book}
          tags={tags}
          onSaved={() => { setEditOpen(false); fetchData(); }}
        />
      )}

      {correctionsOpen && (
        <CorrectionsModal
          bookId={bookId}
          initialCorrections={corrections}
          onClose={() => setCorrectionsOpen(false)}
          onSaved={(saved) => { setCorrections(saved); setCorrectionsOpen(false); }}
          onCopied={setCorrections}
        />
      )}

      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <BookHeader
          book={book}
          tags={tags}
          completedChapters={completedChapters}
          totalChapters={totalChapters}
          failedCount={failedCount}
          progress={progress}
          translated={translated}
        />
        <div className="mt-4">
          {translated ? (
            <TranslateActions
              bookId={bookId}
              downloading={downloading}
              isCompleted={isCompleted}
              failedCount={failedCount}
              totalChapters={totalChapters}
              docxLinks={docxLinks}
              onJobStarted={trackJob}
              onJobCancelled={handleJobCancelled}
            />
          ) : (
            <DownloadActions
              book={book}
              downloading={downloading}
              isCompleted={isCompleted}
              failedCount={failedCount}
              totalChapters={totalChapters}
              docxLinks={docxLinks}
              onJobStarted={trackJob}
              onJobCancelled={handleJobCancelled}
              onRefresh={fetchData}
            />
          )}
        </div>
      </div>

      <CorrectionPreviewModal preview={preview} onClose={() => setPreview(null)} />

      <ChapterTable
        chapters={chapters}
        translated={translated}
        onPreview={handlePreview}
        onExport={handleExportChapter}
        onDownload={handleChapterDownload}
      />
    </Layout>
  );
};

export default BookDetails;
