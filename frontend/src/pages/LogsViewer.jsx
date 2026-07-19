import React, { useState, useEffect } from 'react';
import { logsApi } from '../api';
import Layout from '../components/Layout';

const LogsViewer = () => {
  const [files, setFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [logContent, setLogContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  const fetchFiles = async () => {
    try {
      const res = await logsApi.list(search || undefined);
      setFiles(res.data);
    } catch (err) {
      console.error('Failed to load log files', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFiles();
  }, []);

  const handleSearch = (e) => {
    e.preventDefault();
    fetchFiles();
  };

  const handleSelectFile = async (name) => {
    setSelectedFile(name);
    try {
      const res = await logsApi.read(name, 1000);
      setLogContent(res.data.content);
    } catch (err) {
      setLogContent('Error reading log file: ' + err.message);
    }
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const formatDate = (ts) => {
    return new Date(ts * 1000).toLocaleString();
  };

  return (
    <Layout title="Logs Viewer" subtitle="View download success/failure logs">
      <div className="flex gap-4 flex-col lg:flex-row">
        <div className="lg:w-72 flex-shrink-0">
          <div className="bg-white rounded-lg shadow p-4">
            <form onSubmit={handleSearch} className="mb-3">
              <input
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="Filter files..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </form>
            <div className="space-y-1 max-h-[70vh] overflow-y-auto">
              {loading ? (
                <p className="text-sm text-gray-400">Loading...</p>
              ) : files.length === 0 ? (
                <p className="text-sm text-gray-400">No log files found.</p>
              ) : (
                files.map(f => (
                  <button
                    key={f.name}
                    onClick={() => handleSelectFile(f.name)}
                    className={`w-full text-left px-3 py-2 rounded text-sm transition ${
                      selectedFile === f.name
                        ? 'bg-blue-100 text-blue-800'
                        : 'hover:bg-gray-100 text-gray-700'
                    }`}
                  >
                    <div className="truncate font-medium">{f.name}</div>
                    <div className="text-xs text-gray-400">{formatSize(f.size)} &middot; {formatDate(f.modified)}</div>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
        <div className="flex-1">
          <div className="bg-white rounded-lg shadow p-4">
            {selectedFile ? (
              <>
                <div className="flex justify-between items-center mb-3">
                  <h2 className="text-sm font-semibold text-gray-700 truncate">{selectedFile}</h2>
                  <button
                    onClick={() => handleSelectFile(selectedFile)}
                    className="text-xs bg-gray-100 hover:bg-gray-200 px-2 py-1 rounded"
                  >
                    Refresh
                  </button>
                </div>
                <pre className="bg-gray-900 text-gray-100 p-4 rounded text-xs leading-relaxed overflow-auto max-h-[70vh] whitespace-pre-wrap">
                  {logContent || '(empty)'}
                </pre>
              </>
            ) : (
              <div className="text-center py-20 text-gray-400 text-sm">
                Select a log file from the left to view its contents.
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
};

export default LogsViewer;
