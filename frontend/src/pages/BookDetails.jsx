import React, { useState, useEffect, useRef } from 'react';
import { bookApi } from '../api';
import { bookStatusColors, chapterStatusColors } from '../constants';
import Layout from '../components/Layout';

const BookDetails = ({ bookId, onBack }) => {
  const [book, setBook] = useState(null);
  const [chapters, setChapters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [redownloadDocxExists, setRedownloadDocxExists] = useState(false);
  const [maxChapters, setMaxChapters] = useState('');
  const pollingRef = useRef(null);

  useEffect(() => {
    if (!bookId) return;
    fetchData();
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [bookId]);

  const fetchData = async () => {
    try {
      const [bookRes, chaptersRes, progressRes, rdInfoRes] = await Promise.all([
        bookApi.getOne(bookId),
        bookApi.getChapters(bookId),
        bookApi.getProgress(bookId),
        bookApi.redownloadDocxInfo(bookId).catch(() => ({ data: { exists: false } })),
      ]);
      setBook(bookRes.data);
      setChapters(chaptersRes.data);
      setRedownloadDocxExists(rdInfoRes.data.exists);
      const p = progressRes.data;
      setProgress(p);
      if (p.active) {
        setDownloading(true);
      } else if (downloading) {
        setDownloading(false);
        stopPolling();
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
      await bookApi.redownload(bookId, false);
      alert('Re-download started for failed chapters.');
    } catch (err) {
      alert('Re-download failed: ' + err.message);
    }
  };

  const handleRedownloadAll = async () => {
    if (!confirm('Re-download ALL chapters? This will fetch every chapter into _redownload.docx.')) return;
    try {
      await bookApi.redownload(bookId, true);
      alert('Re-download started for ALL chapters.');
    } catch (err) {
      alert('Re-download all failed: ' + err.message);
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

  if (loading) return <div className="text-center py-10 text-gray-500">Loading book details...</div>;
  if (!book) return <div className="text-center py-10 text-red-500">Book not found</div>;

  const completedChapters = chapters.filter(ch => ch.download_status === 'completed').length;
  const failedChapters = chapters.filter(ch => ch.download_status === 'failed');
  const totalChapters = book.total_chapters || 0;
  const progressPct = totalChapters > 0 ? Math.round((completedChapters / totalChapters) * 100) : 0;
  const isCompleted = ['completed', 'completed_with_errors'].includes(book.download_status);

  return (
    <Layout>
      <button onClick={onBack} className="mb-4 text-sm text-gray-500 hover:text-blue-600 transition">&larr; Back</button>

      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <div className="flex flex-col lg:flex-row lg:justify-between lg:items-start gap-4">
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-gray-900">{book.title}</h1>
            <div className="flex flex-wrap gap-4 mt-2 text-sm text-gray-500">
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
            {book.book_url && (
              <a href={book.book_url} target="_blank" rel="noreferrer" className="inline-block mt-1 text-sm text-blue-500 hover:underline">
                {book.book_url}
              </a>
            )}
          </div>
          <div className="flex flex-col items-end gap-2">
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
              Downloading: {progress.current_title}
            </div>
            <div className="text-indigo-600 mt-1">
              {progress.success_count} success / {progress.fail_count} failed
              &nbsp;— chapter {progress.current_index} of {progress.total} remaining
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-2 items-center">
          <div className="flex items-center gap-1 mr-1">
            <label className="text-xs text-gray-500 whitespace-nowrap">Max:</label>
            <input type="number" min="0" value={maxChapters}
              onChange={e => setMaxChapters(e.target.value)}
              placeholder="no limit"
              className="w-20 border rounded px-2 py-1.5 text-sm text-center" />
          </div>
          {downloading ? (
            <button onClick={handleCancel} className="bg-red-600 hover:bg-red-700 text-white px-5 py-2 rounded text-sm font-medium transition">
              Cancel Download
            </button>
          ) : isCompleted ? (
            <>
              <button onClick={handleRedownload} disabled={failedChapters.length === 0}
                className="bg-orange-600 hover:bg-orange-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
                Re-download ({failedChapters.length} failed)
              </button>
              <button onClick={handleRedownloadAll}
                className="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded text-sm font-medium transition">
                Re-download All
              </button>
            </>
          ) : (
            <button onClick={handleDownload} disabled={totalChapters === 0}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
              Download All
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
          {book.book_web_status && ['Còn tiếp', 'Chưa xác minh'].includes(book.book_web_status) && (
            <button onClick={handleContinueExtract}
              className="bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2 rounded text-sm font-medium transition">
              Continue Extract
            </button>
          )}
          {book.book_url && (
            <button onClick={handleUpdateFull}
              className="bg-teal-600 hover:bg-teal-700 text-white px-5 py-2 rounded text-sm font-medium transition">
              Update & Download
            </button>
          )}
        </div>
      </div>

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
              <th className="px-6 py-4 w-28">Action</th>
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
                  {ch.download_status === 'failed' && (
                    <button onClick={() => handleChapterDownload(ch.id)}
                      className="text-xs bg-orange-100 hover:bg-orange-200 text-orange-700 px-2 py-1 rounded transition">
                      Retry
                    </button>
                  )}
                  {ch.download_status === 'completed' && (
                    <button onClick={() => handleChapterDownload(ch.id)}
                      className="text-xs bg-purple-100 hover:bg-purple-200 text-purple-700 px-2 py-1 rounded transition">
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
