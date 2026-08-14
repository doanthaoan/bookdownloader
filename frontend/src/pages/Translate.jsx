import React, { useState, useEffect, useCallback, useRef } from 'react';
import { translateApi, bookApi } from '../api';
import Layout from '../components/Layout';

const Translate = ({ onViewBook }) => {
  const [prepare, setPrepare] = useState(null);
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState('');
  const [parsed, setParsed] = useState(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [title, setTitle] = useState('');
  const [author, setAuthor] = useState('');
  const [titleTranslating, setTitleTranslating] = useState(false);
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState('info');
  const [bookId, setBookId] = useState(null);
  const [corrections, setCorrections] = useState([]);
  const [newCorr, setNewCorr] = useState({ find_text: '', replace_text: '' });
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(null);
  const [docxInfo, setDocxInfo] = useState(null);
  const pollRef = useRef(null);

  const showMsg = (text, type = 'info') => { setMsg(text); setMsgType(type); };

  useEffect(() => { init(); return () => clearInterval(pollRef.current); }, []);

  const init = async () => {
    setLoading(true);
    try {
      const [p, f] = await Promise.all([translateApi.prepare(), translateApi.sourceFiles()]);
      setPrepare(p.data);
      setFiles(f.data.files || []);
    } catch (err) {
      showMsg('Failed to load translate page: ' + (err.response?.data?.detail || err.message), 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleRecheck = async () => {
    try {
      const res = await translateApi.check();
      setPrepare(prev => ({ ...prev, ...res.data }));
      showMsg(res.data.api_available ? 'API is available.' : 'API blocked — using web method.', res.data.api_available ? 'success' : 'info');
    } catch (err) {
      showMsg('Check failed: ' + (err.response?.data?.detail || err.message), 'error');
    }
  };

  const refreshFiles = async () => {
    const res = await translateApi.sourceFiles();
    setFiles(res.data.files || []);
  };

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      await translateApi.upload(file);
      showMsg(`Uploaded ${file.name}`, 'success');
      refreshFiles();
    } catch (err) {
      showMsg('Upload failed: ' + (err.response?.data?.detail || err.message), 'error');
    }
    e.target.value = '';
  };

  const handleDeleteFile = async (filename) => {
    if (!confirm(`Delete ${filename}?`)) return;
    try {
      await translateApi.deleteFile(filename);
      if (selectedFile === filename) { setSelectedFile(''); setParsed(null); }
      refreshFiles();
    } catch (err) {
      showMsg('Delete failed: ' + err.message, 'error');
    }
  };

  const handleParse = async () => {
    if (!selectedFile) return;
    setParseLoading(true);
    setParsed(null);
    setBookId(null);
    try {
      const res = await translateApi.parse(selectedFile);
      setParsed(res.data);
      setTitle(res.data.raw_title);
      setAuthor(res.data.author || '');
    } catch (err) {
      showMsg('Parse failed: ' + (err.response?.data?.detail || err.message), 'error');
    } finally {
      setParseLoading(false);
    }
  };

  const handleTranslateTitle = async () => {
    if (!title.trim()) return;
    setTitleTranslating(true);
    try {
      // Always try the API first; translate() auto-falls-back to web if blocked.
      const res = await translateApi.translateText(title, 'api');
      setTitle(res.data.translated);
    } catch (err) {
      showMsg('Title translation failed: ' + (err.response?.data?.detail || err.message), 'error');
    } finally {
      setTitleTranslating(false);
    }
  };

  const handleCreateBook = async () => {
    if (!parsed) return;
    try {
      const res = await translateApi.createBook(selectedFile, title.trim(), author.trim());
      setBookId(res.data.book_id);
      showMsg(res.data.message, 'success');
      const corr = await translateApi.corrections(res.data.book_id);
      setCorrections(corr.data || []);
      const di = await bookApi.docxInfo(res.data.book_id);
      setDocxInfo(di.data);
    } catch (err) {
      showMsg('Create book failed: ' + (err.response?.data?.detail || err.message), 'error');
    }
  };

  const handleAddCorrection = () => {
    if (!newCorr.find_text.trim()) return;
    setCorrections([...corrections, { ...newCorr, enabled: true, id: Date.now() }]);
    setNewCorr({ find_text: '', replace_text: '' });
  };

  const handleRemoveCorrection = (idx) => {
    setCorrections(corrections.filter((_, i) => i !== idx));
  };

  const handleSaveCorrections = async () => {
    try {
      const clean = corrections.map(c => ({ find_text: c.find_text, replace_text: c.replace_text, enabled: c.enabled !== false }));
      await translateApi.updateCorrections(bookId, clean);
      showMsg('Corrections saved.', 'success');
    } catch (err) {
      showMsg('Save corrections failed: ' + err.message, 'error');
    }
  };

  const startTranslation = async () => {
    try {
      const method = prepare?.api_available === undefined
        ? (await translateApi.check()).data.method
        : (prepare?.api_available ? 'api' : 'web');
      await translateApi.run(bookId, method);
      setRunning(true);
      showMsg(`Translation started (${method === 'api' ? 'API' : 'Web'} method).`, 'info');
      pollRef.current = setInterval(pollProgress, 2000);
    } catch (err) {
      showMsg('Start failed: ' + (err.response?.data?.detail || err.message), 'error');
    }
  };

  const pollProgress = async () => {
    if (!bookId) return;
    try {
      const res = await translateApi.progress(bookId);
      setProgress(res.data);
      if (!res.data.active) {
        clearInterval(pollRef.current);
        setRunning(false);
        const di = await bookApi.docxInfo(bookId);
        setDocxInfo(di.data);
        const book = await bookApi.getOne(bookId);
        setProgress(p => ({ ...p, download_status: book.data.download_status }));
      }
    } catch (err) {
      clearInterval(pollRef.current);
      setRunning(false);
    }
  };

  const handleCancel = async () => {
    try {
      await translateApi.cancel(bookId);
      showMsg('Cancellation requested.', 'info');
    } catch (err) {
      showMsg('Cancel failed: ' + err.message, 'error');
    }
  };

  const resetAll = () => {
    setSelectedFile(''); setParsed(null); setTitle(''); setAuthor('');
    setBookId(null); setCorrections([]); setProgress(null); setDocxInfo(null);
    setRunning(false);
    if (pollRef.current) clearInterval(pollRef.current);
  };

  const isActive = running || (progress && progress.active);

  if (loading) return <Layout><div className="text-center py-10 text-gray-500">Loading translate tools...</div></Layout>;

  return (
    <Layout title="Translate Novels" subtitle="Convert raw Chinese TXT novels to Vietnamese DOCX using dichtienghoa">
      {/* Step 1: Connection status */}
      <div className="bg-white rounded-lg shadow p-5 mb-6 flex items-center gap-4">
        <div className={`w-3 h-3 rounded-full ${prepare?.api_available === undefined ? 'bg-gray-400' : prepare?.api_available ? 'bg-green-500' : 'bg-red-500'}`} />
        <div className="flex-1">
          <p className="text-sm font-medium">
            Method: <span className={prepare?.api_available === undefined ? 'text-gray-500' : prepare?.api_available ? 'text-green-700' : 'text-red-600'}>
              {prepare?.api_available === undefined
                ? 'Not checked yet — click Re-check'
                : prepare?.api_available ? 'API (dichtienghoa transtext)' : 'Web (Selenium fallback)'}
            </span>
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Source folder: {prepare?.source_path}
            {prepare?.settings?.has_cookies && <span className="text-green-600"> · cookies set</span>}
            {!prepare?.api_available && prepare?.api_available !== undefined && !prepare?.settings?.has_cookies && ' — API blocked by Cloudflare; set translate_cookies (cf_clearance) in Settings for the web method.'}
          </p>
        </div>
        <button onClick={handleRecheck} className="bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded text-xs font-medium transition">Re-check</button>
      </div>

      {msg && (
        <div className={`mb-4 p-3 rounded text-sm ${msgType === 'error' ? 'bg-red-50 text-red-700' : msgType === 'success' ? 'bg-green-50 text-green-700' : 'bg-blue-50 text-blue-700'}`}>
          {msg}
        </div>
      )}

      {/* Step 2: File selection */}
      <div className="bg-white rounded-lg shadow p-5 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">1. Source Files</h3>
          <label className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded text-xs font-medium transition cursor-pointer">
            + Upload TXT
            <input type="file" accept=".txt,.text" className="hidden" onChange={handleUpload} />
          </label>
        </div>
        {files.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">No TXT files in source folder. Upload one above.</p>
        ) : (
          <div className="divide-y divide-gray-100">
            {files.map(f => (
              <div key={f.filename} className="flex items-center gap-3 py-2">
                <button
                  onClick={() => setSelectedFile(f.filename)}
                  className={`flex-1 text-left px-3 py-2 rounded text-sm transition ${selectedFile === f.filename ? 'bg-blue-50 text-blue-800 font-medium' : 'hover:bg-gray-50'}`}>
                  <span className="font-mono">{f.filename}</span>
                  <span className="text-xs text-gray-400 ml-3">{(f.size / 1024).toFixed(1)} KB</span>
                </button>
                <button onClick={() => handleDeleteFile(f.filename)} className="text-xs bg-red-100 hover:bg-red-200 text-red-700 px-2 py-1 rounded transition">Delete</button>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center gap-3 mt-4">
          <select value={selectedFile} onChange={e => setSelectedFile(e.target.value)} className="flex-1 border rounded px-3 py-2 text-sm">
            <option value="">Select a file...</option>
            {files.map(f => <option key={f.filename} value={f.filename}>{f.filename}</option>)}
          </select>
          <button onClick={handleParse} disabled={!selectedFile || parseLoading}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 text-white px-4 py-2 rounded text-sm font-medium transition">
            {parseLoading ? 'Parsing...' : 'Parse File'}
          </button>
        </div>
      </div>

      {/* Step 3: Book info */}
      {parsed && !bookId && (
        <div className="bg-white rounded-lg shadow p-5 mb-6">
          <h3 className="text-lg font-semibold mb-3">2. Book Info ({parsed.chapters?.length} chapters found)</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Title (raw: {parsed.raw_title})</label>
              <div className="flex gap-2">
                <input value={title} onChange={e => setTitle(e.target.value)}
                  className="flex-1 border rounded px-3 py-2 text-sm" />
                <button onClick={handleTranslateTitle} disabled={titleTranslating || !title.trim()}
                  className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-400 text-white px-3 py-2 rounded text-sm font-medium transition whitespace-nowrap">
                  {titleTranslating ? '...' : 'Translate'}
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Author</label>
              <input value={author} onChange={e => setAuthor(e.target.value)}
                className="w-full border rounded px-3 py-2 text-sm" />
            </div>
          </div>
          <div className="mt-4 max-h-48 overflow-y-auto border rounded">
            <table className="w-full text-sm">
              <thead><tr className="bg-gray-50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                <th className="px-4 py-2 w-16">Ch</th><th className="px-4 py-2">Raw Title</th>
              </tr></thead>
              <tbody className="divide-y divide-gray-100">
                {parsed.chapters.slice(0, 50).map(c => (
                  <tr key={c.order}><td className="px-4 py-1.5 text-gray-400">{c.order}</td>
                  <td className="px-4 py-1.5 font-mono text-xs">{c.title}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex gap-2">
            <button onClick={handleCreateBook} disabled={!title.trim()}
              className="bg-green-600 hover:bg-green-700 disabled:bg-gray-400 text-white px-4 py-2 rounded text-sm font-medium transition">
              Create Book & Chapters
            </button>
            <button onClick={resetAll} className="bg-gray-300 hover:bg-gray-400 text-gray-700 px-4 py-2 rounded text-sm font-medium transition">Reset</button>
          </div>
        </div>
      )}

      {/* Step 4: Corrections + run */}
      {bookId && (
        <div className="bg-white rounded-lg shadow p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold">3. Corrections & Run</h3>
            <button onClick={resetAll} className="text-xs bg-gray-200 hover:bg-gray-300 text-gray-600 px-2 py-1 rounded transition">New book</button>
          </div>

          <div className="mb-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Book Corrections (find → replace, applied to translated text)</p>
            <div className="space-y-2 mb-2">
              {corrections.length === 0 && <p className="text-sm text-gray-400">No corrections yet.</p>}
              {corrections.map((c, i) => (
                <div key={c.id || i} className="flex items-center gap-2">
                  <input value={c.find_text} disabled className="flex-1 border rounded px-2 py-1.5 text-xs font-mono bg-gray-50" />
                  <span className="text-gray-400 text-xs">→</span>
                  <input value={c.replace_text} disabled className="flex-1 border rounded px-2 py-1.5 text-xs font-mono bg-gray-50" />
                  <button onClick={() => handleRemoveCorrection(i)} className="text-xs bg-red-100 hover:bg-red-200 text-red-700 px-2 py-1 rounded transition">Remove</button>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <input value={newCorr.find_text} onChange={e => setNewCorr({ ...newCorr, find_text: e.target.value })}
                placeholder="Find text" className="flex-1 border rounded px-2 py-1.5 text-xs font-mono" />
              <span className="text-gray-400 text-xs">→</span>
              <input value={newCorr.replace_text} onChange={e => setNewCorr({ ...newCorr, replace_text: e.target.value })}
                placeholder="Replace with" className="flex-1 border rounded px-2 py-1.5 text-xs font-mono" />
              <button onClick={handleAddCorrection} disabled={!newCorr.find_text.trim()}
                className="bg-indigo-100 hover:bg-indigo-200 text-indigo-700 px-2 py-1.5 rounded text-xs font-medium transition">Add</button>
            </div>
            <button onClick={handleSaveCorrections} className="mt-2 text-xs bg-green-100 hover:bg-green-200 text-green-700 px-3 py-1.5 rounded font-medium transition">
              Save Corrections
            </button>
          </div>

          <div className="border-t pt-4">
            {isActive ? (
              <div>
                {progress && (
                  <div className="mb-3">
                    <div className="flex justify-between text-xs text-gray-600 mb-1">
                      <span>{progress.current_title || 'Starting...'}</span>
                      <span>{progress.current_index}/{progress.total} · ✓{progress.success_count} · ✗{progress.fail_count}</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-2.5">
                      <div className="bg-blue-600 h-2.5 rounded-full transition-all"
                        style={{ width: `${progress.total ? (progress.current_index / progress.total) * 100 : 0}%` }} />
                    </div>
                    {progress.message && <p className="text-xs text-gray-500 mt-2">{progress.message}</p>}
                  </div>
                )}
                <button onClick={handleCancel} className="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded text-sm font-medium transition">Cancel Translation</button>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <button onClick={startTranslation}
                  className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded text-sm font-medium transition">
                  Start Translation ({prepare?.api_available === undefined ? 'auto' : prepare?.api_available ? 'API' : 'Web'})
                </button>
                {progress?.download_status && (
                  <span className={`text-xs font-medium px-2 py-1 rounded ${progress.download_status === 'completed' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                    Status: {progress.download_status}
                  </span>
                )}
                {docxInfo?.exists && (
                  <a href={bookApi.docxUrl(bookId)} target="_blank"
                    className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded text-sm font-medium transition">
                    Open DOCX
                  </a>
                )}
                {onViewBook && (
                  <button onClick={() => onViewBook(bookId)} className="bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded text-sm font-medium transition">
                    View in Book List
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </Layout>
  );
};

export default Translate;