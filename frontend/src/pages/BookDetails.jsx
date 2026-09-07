import React, { useState, useEffect, useRef } from 'react';
import { bookApi, translateApi } from '../api';
import { bookStatusColors, chapterStatusColors } from '../constants';
import Layout from '../components/Layout';
import Modal from '../components/Modal';

const CorrectionSegments = ({ segments }) => (
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

const BookDetails = ({ bookId, onBack }) => {
  const [book, setBook] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [redownloadDocxExists, setRedownloadDocxExists] = useState(false);
  const [retranslateDocxExists, setRetranslateDocxExists] = useState(false);
  const [correctedDocxExists, setCorrectedDocxExists] = useState(false);
  const [preview, setPreview] = useState(null);
  const [exporting, setExporting] = useState(false);
  const [tags, setTags] = useState([]);
  const [maxChapters, setMaxChapters] = useState('');
  const [redownloadCount, setRedownloadCount] = useState('');
  const [redownloadFrom, setRedownloadFrom] = useState('');
  const [redownloadTo, setRedownloadTo] = useState('');
  const pollingRef = useRef(null);

  // Edit info form
  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState({ title: '', author: '', short_description: '', book_web_status: '' });
  const [formTags, setFormTags] = useState('');
  const [coverFile, setCoverFile] = useState(null);

  // Per-book corrections
  const [corrections, setCorrections] = useState([]);
  const [correctionsOpen, setCorrectionsOpen] = useState(false);
  const [copySourceId, setCopySourceId] = useState('');
  const [copyingCorrections, setCopyingCorrections] = useState(false);
  const correctionsOpenRef = useRef(false);

  useEffect(() => {
    correctionsOpenRef.current = correctionsOpen;
  }, [correctionsOpen]);

  useEffect(() => {
    if (!bookId) return;
    fetchData();
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [bookId]);

  const fetchData = async () => {
    try {
      const [bookRes, chaptersRes, progressRes, tagsRes, correctionsRes, correctedRes] = await Promise.all([
        bookApi.getOne(bookId),
        bookApi.getChapters(bookId),
        bookApi.getProgress(bookId).catch(() => ({ data: { active: false } })),
        bookApi.bookTags(bookId).catch(() => ({ data: { tags: [] } })),
        translateApi.corrections(bookId).catch(() => []),
        bookApi.exportCorrectedDocxInfo(bookId).catch(() => ({ data: { exists: false } })),
      ]);
      setBook(bookRes.data);
      setChapters(chaptersRes.data);
      setTags(tagsRes.data.tags);
      if (!correctionsOpenRef.current) {
        setCorrections(correctionsRes.data || correctionsRes || []);
      }
      setCorrectedDocxExists(correctedRes.data.exists);
      setForm({
        title: bookRes.data.title || '',
        author: bookRes.data.author || '',
        short_description: bookRes.data.short_description || '',
        book_web_status: bookRes.data.book_web_status || '',
      });
      setFormTags(tagsRes.data.tags.join(', '));
      const isTranslated = bookRes.data.is_translated === 1;

      if (isTranslated) {
        // Translation progress + retranslate docx info
        const [tp, rt] = await Promise.all([
          translateApi.progress(bookId),
          translateApi.retranslateDocxInfo(bookId).catch(() => ({ data: { exists: false } })),
        ]);
        setRetranslateDocxExists(rt.data.exists);
        const p = tp.data;
        setProgress(p);
        if (p.active) {
          setDownloading(true);
        } else if (downloading) {
          setDownloading(false);
          stopPolling();
        }
      } else {
        const [rdInfoRes] = [await bookApi.redownloadDocxInfo(bookId).catch(() => ({ data: { exists: false } }))];
        setRedownloadDocxExists(rdInfoRes.data.exists);
        const p = progressRes.data;
        setProgress(p);
        if (p.active) {
          setDownloading(true);
        } else if (downloading) {
          setDownloading(false);
          stopPolling();
        }
      }
    } catch (err) {
      console.error('Failed to fetch book details', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (progress && progress.active) {
      startPolling();
    }
  }, [progress?.active]);

  const startPolling = () => {
    stopPolling();
    pollingRef.current = setInterval(fetchData, 2000);
  };

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  const handleDownload = async () => {
    setDownloading(true);
    startPolling();
    try {
      const params = {};
      const val = parseInt(maxChapters, 10);
      if (val > 0) params.max_chapters = val;
      await bookApi.download(bookId, params);
    } catch (err) {
      alert('Download failed: ' + err.message);
      stopPolling();
      setDownloading(false);
    }
  };

  const handleRedownload = async () => {
    if (!confirm('Re-download failed chapters? Content goes to _redownload.docx.')) return;
    try {
      await bookApi.redownload(bookId, { all_chapters: false });
      alert('Re-download started for failed chapters.');
    } catch (err) {
      alert('Re-download failed: ' + err.message);
    }
  };

  const handleRedownloadAll = async () => {
    if (!confirm('Re-download ALL chapters? This will fetch every chapter into _redownload.docx.')) return;
    try {
      await bookApi.redownload(bookId, { all_chapters: true });
      alert('Re-download started for ALL chapters.');
    } catch (err) {
      alert('Re-download all failed: ' + err.message);
    }
  };

  const handleRedownloadCount = async () => {
    const n = parseInt(redownloadCount, 10);
    if (!(n > 0)) {
      alert('Enter a valid number of chapters (N).');
      return;
    }
    if (!confirm(`Re-download the first ${n} chapters? Content goes to _redownload.docx.`)) return;
    try {
      await bookApi.redownload(bookId, { count: n });
      alert(`Re-download started for the first ${n} chapters.`);
    } catch (err) {
      alert('Re-download failed: ' + err.message);
    }
  };

  const handleRedownloadRange = async () => {
    const from = parseInt(redownloadFrom, 10);
    const to = parseInt(redownloadTo, 10);
    if (!(from > 0) || !(to > 0) || to < from) {
      alert('Enter a valid range (From ≤ To).');
      return;
    }
    if (!confirm(`Re-download chapters ${from} to ${to}? Content goes to _redownload.docx.`)) return;
    try {
      await bookApi.redownload(bookId, { start_order: from, end_order: to });
      alert(`Re-download started for chapters ${from} to ${to}.`);
    } catch (err) {
      alert('Re-download failed: ' + err.message);
    }
  };

  const handleCancel = async () => {
    if (!confirm('Cancel download? Progress will be saved.')) return;
    try {
      await bookApi.cancelDownload(bookId);
      stopPolling();
      setDownloading(false);
      fetchData();
    } catch (err) {
      alert('Cancel failed: ' + err.message);
    }
  };

  const handleChapterDownload = async (chapterId) => {
    try {
      await bookApi.downloadChapter(bookId, chapterId);
      fetchData();
    } catch (err) {
      alert('Chapter download failed: ' + err.message);
    }
  };

  const handleContinueExtract = async () => {
    if (!confirm('Check for new chapters and append them to the existing list?')) return;
    try {
      await bookApi.continueExtract(bookId);
      alert('Continue extraction started. Refresh to see new chapters.');
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleRefreshInfo = async () => {
    if (!confirm('Re-scrape book metadata (cover, description, author, status) from the web?')) return;
    try {
      const res = await bookApi.refreshInfo(bookId);
      alert('Book info refreshed: ' + res.data.updated_fields.join(', '));
      fetchData();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const handleUpdateFull = async () => {
    if (!confirm('Check for updates, extract new chapters, and download them? This may take a while.')) return;
    try {
      const params = {};
      const val = parseInt(maxChapters, 10);
      if (val > 0) params.max_chapters = val;
      await bookApi.updateFull(bookId, params);
      alert('Full update started. Refresh the page to see progress after a moment.');
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  const getTranslateMethod = async () => {
    try {
      const res = await translateApi.prepare();
      return res.data.method || 'api';
    } catch (err) {
      return 'api';
    }
  };

  const handleTranslateAll = async () => {
    setDownloading(true);
    startPolling();
    try {
      const method = await getTranslateMethod();
      const params = {};
      const val = parseInt(maxChapters, 10);
      if (val > 0) params.max_chapters = val;
      await translateApi.run(bookId, method, params.max_chapters || null);
    } catch (err) {
      alert('Translate failed: ' + (err.response?.data?.detail || err.message));
      stopPolling();
      setDownloading(false);
    }
  };

  const handleRetranslate = async () => {
    if (!confirm('Re-translate failed chapters? Output goes to _retranslate.docx.')) return;
    try {
      const method = await getTranslateMethod();
      await translateApi.retranslate(bookId, method);
      setDownloading(true);
      startPolling();
    } catch (err) {
      alert('Re-translate failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleContinue = async () => {
    if (!confirm('Continue failed chapters into the main DOCX? Use after updating the Cloudflare cookie.')) return;
    try {
      const method = await getTranslateMethod();
      await translateApi.continueRun(bookId, method);
      setDownloading(true);
      startPolling();
    } catch (err) {
      alert('Continue failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleRefreshCookie = async () => {
    try {
      alert('A Chrome window will open so Cloudflare can issue a fresh cookie.\n' +
            'If a challenge appears, click it once and wait.');
      const res = await translateApi.refreshCookies();
      alert(res.data.ok ? 'Fresh cookie captured and saved.' : 'Could not capture a fresh cookie.');
    } catch (err) {
      alert('Cookie refresh failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleCancelTranslate = async () => {
    if (!confirm('Cancel translation? Progress will be saved.')) return;
    try {
      await translateApi.cancel(bookId);
      stopPolling();
      setDownloading(false);
      fetchData();
    } catch (err) {
      alert('Cancel failed: ' + err.message);
    }
  };

  const handleExportCorrected = async () => {
    if (!confirm('Export the whole book as a corrected DOCX? Corrections are applied now; the database is not modified.')) return;
    try {
      setExporting(true);
      const res = await bookApi.exportCorrected(bookId, []);
      setCorrectedDocxExists(true);
      alert(`Corrected DOCX exported: ${res.data.file_name}`);
    } catch (err) {
      alert('Export failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setExporting(false);
    }
  };

  const handleExportChapterCorrected = async (chapterId) => {
    if (!confirm('Export ONLY this chapter into the corrected DOCX? (This replaces the whole-book corrected file.)')) return;
    try {
      setExporting(true);
      const res = await bookApi.exportCorrected(bookId, [chapterId]);
      setCorrectedDocxExists(true);
      alert(`Chapter exported into: ${res.data.file_name}`);
    } catch (err) {
      alert('Export failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setExporting(false);
    }
  };

  const handlePreviewCorrection = async (chapterId) => {
    try {
      const res = await bookApi.previewCorrection(bookId, chapterId);
      setPreview(res.data);
    } catch (err) {
      alert('Preview failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleSaveInfo = async () => {
    try {
      const payload = {};
      if (form.title.trim()) payload.title = form.title.trim();
      payload.author = form.author.trim();
      payload.short_description = form.short_description.trim();
      payload.book_web_status = form.book_web_status.trim();
      await bookApi.updateInfo(bookId, payload);
      const newTags = formTags.split(',').map(t => t.trim()).filter(Boolean);
      await bookApi.updateBookTags(bookId, newTags);
      if (coverFile) {
        await bookApi.uploadCover(bookId, coverFile);
      }
      setCoverFile(null);
      setEditOpen(false);
      alert('Book info saved.');
      fetchData();
    } catch (err) {
      alert('Save failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleSaveCorrections = async () => {
    const clean = corrections
      .filter(c => (c.find_text || '').trim())
      .map(c => ({
        find_text: (c.find_text || '').trim(),
        replace_text: c.replace_text || '',
        enabled: !!c.enabled,
      }));
    try {
      await translateApi.updateCorrections(bookId, clean);
      setCorrectionsOpen(false);
      alert('Corrections saved.');
    } catch (err) {
      alert('Save corrections failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const updateCorrection = (idx, field, value) => {
    setCorrections(prev => prev.map((c, i) => i === idx ? { ...c, [field]: value } : c));
  };

  const handleCopyCorrections = async () => {
    const sid = parseInt(copySourceId, 10);
    if (!sid || sid === bookId) {
      alert('Enter a valid source book ID (different from this book).');
      return;
    }
    const currentCount = corrections.filter(c => (c.find_text || '').trim()).length;
    if (!confirm(`Replace all ${currentCount} correction(s) of this book with the corrections of book #${sid}?`)) return;
    setCopyingCorrections(true);
    try {
      const res = await translateApi.copyCorrections(bookId, sid);
      const data = res.data || res;
      setCorrections(data.corrections || []);
      setCopySourceId('');
      alert(data.message || 'Corrections copied.');
    } catch (err) {
      alert('Copy failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setCopyingCorrections(false);
    }
  };

  if (loading) return <div className="text-center py-10 text-gray-500">Loading book details...</div>;
  if (!book) return <div className="text-center py-10 text-red-500">Book not found</div>;

  const completedChapters = chapters.filter(ch => ch.download_status === 'completed').length;
  const failedChapters = chapters.filter(ch => ch.download_status === 'failed');
  const totalChapters = book.total_chapters || 0;
  const progressPct = totalChapters > 0 ? Math.round((completedChapters / totalChapters) * 100) : 0;
  const isCompleted = ['completed', 'completed_with_errors'].includes(book.download_status);
  const isTranslated = book.is_translated === 1;

  return (
    <Layout>
      <div className="sticky top-0 z-20 bg-white/95 backdrop-blur-sm border-b border-gray-200 py-2 -mx-4 px-4 mb-4 flex items-center justify-between">
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-blue-600 transition">&larr; Back</button>
        <div className="flex gap-2">
          <button onClick={() => setEditOpen(!editOpen)}
            className="text-sm px-3 py-1 rounded transition bg-gray-100 text-gray-600 hover:text-blue-600">
            {editOpen ? 'Cancel' : 'Edit Info'}
          </button>
          <button onClick={() => setCorrectionsOpen(true)}
            className={`text-sm px-3 py-1 rounded transition ${correctionsOpen ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-600 hover:text-indigo-600'}`}
            title="Open text corrections settings">
            Corrections
          </button>
          <button onClick={async () => { await bookApi.toggleFavorite(bookId); fetchData(); }}
            className={`text-lg leading-none px-2 py-1 rounded transition ${book.is_favorite ? 'text-yellow-500 bg-yellow-50' : 'text-gray-300 hover:text-yellow-400 hover:bg-gray-50'}`}
            title={book.is_favorite ? 'Remove from favorites' : 'Add to favorites'}>
            {book.is_favorite ? '★' : '☆'} Favorites
          </button>
          <button onClick={async () => { await bookApi.toggleSent(bookId); fetchData(); }}
            className={`text-sm leading-none px-2 py-1 rounded transition ${book.is_sent ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400 hover:text-gray-600'}`}
            title={book.is_sent ? 'Mark as not sent' : 'Mark as sent'}>
            ✓ {book.is_sent ? 'Sent' : 'Not sent'}
          </button>
          <label className={`flex items-center gap-1.5 text-sm leading-none px-2 py-1 rounded transition cursor-pointer select-none ${book.auto_export_docx ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-400 hover:text-gray-600'}`}
            title="Export DOCX automatically after each download/redownload">
            <input type="checkbox" checked={!!book.auto_export_docx}
              onChange={async e => { await bookApi.toggleAutoExport(bookId); fetchData(); }}
              className="h-4 w-4" />
            Auto DOCX
          </label>
        </div>
      </div>

      {editOpen && (
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <h2 className="text-lg font-semibold mb-4">Edit Book Info</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Title</label>
              <input type="text" value={form.title}
                onChange={e => setForm({ ...form, title: e.target.value })}
                className="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Author</label>
              <input type="text" value={form.author}
                onChange={e => setForm({ ...form, author: e.target.value })}
                className="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Book web status</label>
              <input type="text" value={form.book_web_status}
                onChange={e => setForm({ ...form, book_web_status: e.target.value })}
                placeholder="e.g. Hoàn thành, Còn tiếp, Parsed"
                className="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Tags (comma separated)</label>
              <input type="text" value={formTags}
                onChange={e => setFormTags(e.target.value)}
                className="w-full border rounded px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Cover image</label>
              <input type="file" accept=".jpg,.jpeg,.png,.gif,.webp"
                onChange={e => setCoverFile(e.target.files[0] || null)}
                className="w-full text-sm" />
            </div>
          </div>
          <div className="mt-4">
            <label className="block text-xs font-medium text-gray-500 mb-1">Summary</label>
            <textarea value={form.short_description}
              onChange={e => setForm({ ...form, short_description: e.target.value })}
              rows={5}
              className="w-full border rounded px-3 py-2 text-sm" />
          </div>
          <div className="mt-4">
            <button onClick={handleSaveInfo}
              className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded text-sm font-medium transition">
              Save Info
            </button>
          </div>
        </div>
      )}

      <Modal open={correctionsOpen} onClose={() => setCorrectionsOpen(false)} title="Text Corrections">
          <p className="text-xs text-gray-500 mb-4">
            Find/replace applied to downloaded or translated text, after the global Text Cleaning rules.
            Matching is case-insensitive. Empty rows are ignored on save.
          </p>
          {corrections.length === 0 && (
            <p className="text-sm text-gray-400 mb-3">No corrections yet. Add one below.</p>
          )}
          <div className="space-y-2">
            {corrections.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <input type="checkbox" checked={!!c.enabled}
                  onChange={e => updateCorrection(i, 'enabled', e.target.checked)}
                  className="h-4 w-4" title="Enabled" />
                <input type="text" value={c.find_text || ''}
                  onChange={e => updateCorrection(i, 'find_text', e.target.value)}
                  placeholder="Find text"
                  className="flex-1 min-w-[140px] border rounded px-2 py-1.5 text-sm" />
                <span className="text-gray-400">→</span>
                <input type="text" value={c.replace_text || ''}
                  onChange={e => updateCorrection(i, 'replace_text', e.target.value)}
                  placeholder="Replace with"
                  className="flex-1 min-w-[140px] border rounded px-2 py-1.5 text-sm" />
                <button onClick={() => setCorrections(prev => prev.filter((_, j) => j !== i))}
                  className="text-sm text-red-500 hover:text-red-700 px-2">✕</button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button onClick={() => setCorrections(prev => [...prev, { find_text: '', replace_text: '', enabled: true }])}
              className="text-sm border border-gray-300 text-gray-600 hover:bg-gray-50 px-3 py-1.5 rounded transition">
              + Add correction
            </button>
            <button onClick={handleSaveCorrections}
              className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-1.5 rounded text-sm font-medium transition">
              Save Corrections
            </button>
          </div>
          <div className="mt-4 pt-3 border-t border-gray-100">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Copy from another book</p>
            <div className="flex flex-wrap items-center gap-2">
              <input type="number" min="1" value={copySourceId}
                onChange={e => setCopySourceId(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleCopyCorrections(); }}
                placeholder="Source book ID"
                className="w-36 border rounded px-2 py-1.5 text-sm" />
              <button onClick={handleCopyCorrections} disabled={copyingCorrections}
                className="text-sm border border-indigo-300 text-indigo-600 hover:bg-indigo-50 px-3 py-1.5 rounded transition disabled:opacity-50">
                {copyingCorrections ? 'Copying…' : 'Copy Corrections'}
              </button>
              <span className="text-xs text-gray-400">Replaces this book's corrections.</span>
            </div>
          </div>
        </Modal>

      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Cover image */}
          <div className="flex-shrink-0">
            <img src={bookApi.coverUrl(bookId)}
              className="w-32 h-44 object-cover rounded-lg shadow-md"
              alt=""
              onError={e => { e.target.style.display = 'none' }} />
          </div>

          {/* Book info */}
          <div className="flex-1 min-w-0">
            <h1 className="text-2xl font-bold text-gray-900">{book.title}</h1>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-gray-500">
              <span>ID: {book.id}</span>
              {book.stt && <span>STT: {book.stt}</span>}
              {book.author && <span>Tác giả: <strong>{book.author}</strong></span>}
              {book.book_web_status && (
                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                  book.book_web_status === 'Hoàn thành' ? 'bg-green-100 text-green-700' :
                  book.book_web_status === 'Còn tiếp' ? 'bg-blue-100 text-blue-700' :
                  book.book_web_status === 'Tạm Ngưng' ? 'bg-yellow-100 text-yellow-700' :
                  'bg-gray-100 text-gray-700'
                }`}>
                  {book.book_web_status}
                </span>
              )}
              {failedChapters.length > 0 && <span className="text-red-500">{failedChapters.length} failed</span>}
            </div>
            {tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {tags.map(tag => (
                  <a key={tag} href={`/?tag=${encodeURIComponent(tag)}`}
                    className="inline-block px-2 py-0.5 text-xs bg-sky-100 text-sky-700 rounded-full hover:bg-sky-200 transition">
                    {tag}
                  </a>
                ))}
              </div>
            )}
            {book.book_url && (
              <a href={book.book_url} target="_blank" rel="noreferrer" className="inline-block mt-1 text-sm text-blue-500 hover:underline">
                {book.book_url}
              </a>
            )}

            {/* Short description accordion */}
            {book.short_description && (
              <details className="mt-3 group">
                <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700 select-none">
                  Summary <span className="text-xs text-gray-400 group-open:hidden">(click to expand)</span>
                </summary>
                <p className="mt-2 text-sm text-gray-600 leading-relaxed whitespace-pre-line">
                  {book.short_description}
                </p>
              </details>
            )}
          </div>

          {/* Status badges */}
          <div className="flex flex-col items-end gap-2 flex-shrink-0">
            <span className={`inline-block px-3 py-1 rounded-full text-sm font-semibold ${bookStatusColors[book.download_status] || 'bg-gray-100 text-gray-800'}`}>
              {book.download_status.replace(/_/g, ' ')}
            </span>
            <span className="text-sm text-gray-500">
              {completedChapters} / {totalChapters} chapters
            </span>
          </div>
        </div>

        {totalChapters > 0 && (
          <div className="mt-4">
            <div className="w-full bg-gray-200 rounded-full h-2.5">
              <div className="bg-green-500 h-2.5 rounded-full transition-all" style={{ width: `${progressPct}%` }}></div>
            </div>
          </div>
        )}

        {progress && progress.active && (
          <div className="mt-3 p-3 bg-indigo-50 border border-indigo-200 rounded text-sm">
            <div className="font-medium text-indigo-800">
              {isTranslated ? 'Translating' : 'Downloading'}: {progress.current_title}
            </div>
            <div className="text-indigo-600 mt-1">
              {progress.success_count} success / {progress.fail_count} failed
              &nbsp;— chapter {progress.current_index} of {progress.total} in this session
            </div>
          </div>
        )}

        <div className="mt-4">
          {isTranslated ? (
            <>
          <div className="flex flex-wrap gap-2 items-center">
          <div className="flex items-center gap-1 mr-1">
            <label className="text-xs text-gray-500 whitespace-nowrap">Max:</label>
            <input type="number" min="0" value={maxChapters}
              onChange={e => setMaxChapters(e.target.value)}
              placeholder="no limit"
              className="w-20 border rounded px-2 py-1.5 text-sm text-center" />
          </div>
          {downloading ? (
            <button onClick={handleCancelTranslate} className="bg-red-600 hover:bg-red-700 text-white px-5 py-2 rounded text-sm font-medium transition">
              Cancel Translate
            </button>
          ) : isCompleted ? (
            <>
              {failedChapters.length > 0 && (
                <button onClick={handleContinue}
                  className="bg-teal-600 hover:bg-teal-700 text-white px-5 py-2 rounded text-sm font-medium transition"
                  title="Reset failed chapters to pending and append them to the main DOCX">
                  Continue ({failedChapters.length} failed)
                </button>
              )}
              <button onClick={handleRetranslate} disabled={failedChapters.length === 0}
                className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
                Re-translate ({failedChapters.length} failed)
              </button>
              <button onClick={handleRefreshCookie}
                className="bg-gray-600 hover:bg-gray-700 text-white px-5 py-2 rounded text-sm font-medium transition"
                title="Open Chrome to refresh the cf_clearance cookie">
                Refresh Cookie
              </button>
              <span className="text-xs bg-cyan-100 text-cyan-700 px-3 py-1.5 rounded font-medium">
                Translated book — content produced by the Translate tool.
              </span>
            </>
          ) : (
            <>
              <button onClick={handleContinue} disabled={failedChapters.length === 0}
                className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition"
                title="Reset failed chapters to pending and append them to the main DOCX">
                Continue ({failedChapters.length} failed)
              </button>
              <button onClick={handleRetranslate} disabled={failedChapters.length === 0}
                className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
                Re-translate ({failedChapters.length} failed)
              </button>
              <button onClick={handleRefreshCookie}
                className="bg-gray-600 hover:bg-gray-700 text-white px-5 py-2 rounded text-sm font-medium transition"
                title="Open Chrome to refresh the cf_clearance cookie">
                Refresh Cookie
              </button>
              <button onClick={handleTranslateAll} disabled={totalChapters === 0}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
                Translate All
              </button>
            </>
          )}
              {completedChapters > 0 && (
                <a href={bookApi.docxUrl(bookId)} target="_blank"
                  className="bg-green-600 hover:bg-green-700 text-white px-5 py-2 rounded text-sm font-medium transition inline-block">
                  Open DOCX
                </a>
              )}
              {retranslateDocxExists && (
                <a href={translateApi.retranslateDocxUrl(bookId)} target="_blank"
                  className="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded text-sm font-medium transition inline-block">
                  Open Re-translate DOCX
                </a>
              )}
              {completedChapters > 0 && (
                <button onClick={handleExportCorrected} disabled={exporting}
                  className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition"
                  title="Render the book from stored content, applying global cleaning + corrections now">
                  Export Corrected
                </button>
              )}
              {correctedDocxExists && (
                <a href={bookApi.exportCorrectedDocxUrl(bookId)} target="_blank"
                  className="bg-emerald-700 hover:bg-emerald-800 text-white px-5 py-2 rounded text-sm font-medium transition inline-block">
                  Open Corrected DOCX
                </a>
              )}
          </div>
            </>
          ) : downloading ? (
            <div className="flex flex-wrap gap-2 items-center">
              <button onClick={handleCancel} className="bg-red-600 hover:bg-red-700 text-white px-5 py-2 rounded text-sm font-medium transition">
                Cancel Download
              </button>
            </div>
          ) : (
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
                  className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
                  Download All
                </button>
              </div>

              {/* Re-download */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider w-30 flex-shrink-0">Re-download</span>
                {!isCompleted && (
                  <button onClick={handleRedownload} disabled={failedChapters.length === 0}
                    className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
                    Re-download ({failedChapters.length} failed)
                  </button>
                )}
                {/* <div className="flex items-center gap-1 mr-1">
                  <label className="text-xs text-gray-500 whitespace-nowrap">N:</label>
                  <input type="number" min="1" value={redownloadCount}
                    onChange={e => setRedownloadCount(e.target.value)}
                    placeholder="count"
                    title="Number of chapters to re-download from the start"
                    className="w-16 border rounded px-2 py-1.5 text-sm text-center" />
                  <button onClick={handleRedownloadCount}
                    className="bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 rounded text-sm font-medium transition"
                    title="Re-download the first N chapters">
                    Re-download N
                  </button>
                </div> */}
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
                <button onClick={handleRedownloadAll}
                  className="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded text-sm font-medium transition">
                  Re-download All
                </button>
              </div>

              {/* Others */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider w-30 flex-shrink-0">Others</span>
                {book.book_url && (
                  <>
                    <button onClick={handleUpdateFull}
                      className="bg-teal-600 hover:bg-teal-700 text-white px-5 py-2 rounded text-sm font-medium transition">
                      Update & Download
                    </button>
                    <button onClick={handleRefreshInfo}
                      className="bg-cyan-600 hover:bg-cyan-700 text-white px-5 py-2 rounded text-sm font-medium transition">
                      Refresh Info
                    </button>
                  </>
                )}
                {book.book_web_status && ['Còn tiếp', 'Chưa xác minh'].includes(book.book_web_status) && (
                  <button onClick={handleContinueExtract}
                    className="bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2 rounded text-sm font-medium transition">
                    Continue Extract
                  </button>
                )}
                {completedChapters > 0 && (
                  <a href={bookApi.docxUrl(bookId)} target="_blank"
                    className="bg-green-600 hover:bg-green-700 text-white px-5 py-2 rounded text-sm font-medium transition inline-block">
                    Open DOCX
                  </a>
                )}
                {redownloadDocxExists && (
                  <a href={bookApi.redownloadDocxUrl(bookId)} target="_blank"
                    className="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded text-sm font-medium transition inline-block">
                    Open Redownload DOCX
                  </a>
                )}
                {completedChapters > 0 && (
                  <button onClick={handleExportCorrected} disabled={exporting}
                    className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition"
                    title="Render the book from stored content, applying corrections now">
                    Export Corrected
                  </button>
                )}
                {correctedDocxExists && (
                  <a href={bookApi.exportCorrectedDocxUrl(bookId)} target="_blank"
                    className="bg-emerald-700 hover:bg-emerald-800 text-white px-5 py-2 rounded text-sm font-medium transition inline-block">
                    Open Corrected DOCX
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <Modal open={!!preview} onClose={() => setPreview(null)} wide
        title={preview ? `Correction preview — Chương ${preview.chapter_order}` : ''}>
        <p className="text-xs text-gray-500 mb-3">
          This is how the chapter will look after corrections are applied.
          <span className="line-through text-red-500 ml-1">Struck text</span> was replaced by
          <span className="bg-yellow-200 rounded px-0.5 mx-1">highlighted text</span>.
          Nothing is saved.
        </p>
        <h3 className="text-base font-semibold text-gray-800 mb-3">
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

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h2 className="text-lg font-semibold">Chapters</h2>
          <span className="text-sm text-gray-500">{chapters.length} total</span>
        </div>
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <th className="px-6 py-4 w-16">#</th>
              <th className="px-6 py-4">Title</th>
              <th className="px-6 py-4 w-32">Status</th>
              <th className="px-6 py-4">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {chapters.length === 0 && (
              <tr><td colSpan={4} className="px-6 py-12 text-center text-gray-400">No chapters extracted yet.</td></tr>
            )}
            {chapters.map(ch => (
              <tr key={ch.id} className="hover:bg-gray-50 transition">
                <td className="px-6 py-3 text-sm text-gray-500">{ch.chapter_order}</td>
                <td className="px-6 py-3 text-sm text-gray-900">{ch.chapter_title}</td>
                <td className="px-6 py-3">
                  <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${chapterStatusColors[ch.download_status] || 'bg-gray-100 text-gray-700'}`}>
                    {ch.download_status}
                  </span>
                </td>
                <td className="px-6 py-3">
                  {ch.download_status === 'completed' && (
                    <>
                      <button onClick={() => handlePreviewCorrection(ch.id)}
                        className="text-xs bg-emerald-100 hover:bg-emerald-200 text-emerald-700 px-2 py-1 rounded transition">
                        Preview
                      </button>
                      <button onClick={() => handleExportChapterCorrected(ch.id)}
                        className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white px-2 py-1 rounded transition ml-1">
                        Export
                      </button>
                    </>
                  )}
                  {!isTranslated && ch.download_status === 'failed' && (
                    <button onClick={() => handleChapterDownload(ch.id)}
                      className="text-xs bg-orange-100 hover:bg-orange-200 text-orange-700 px-2 py-1 rounded transition">
                      Retry
                    </button>
                  )}
                  {!isTranslated && ch.download_status === 'completed' && (
                    <button onClick={() => handleChapterDownload(ch.id)}
                      className="text-xs bg-purple-100 hover:bg-purple-200 text-purple-700 px-2 py-1 rounded transition ml-1">
                      Redownload
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Layout>
  );
};

export default BookDetails;
