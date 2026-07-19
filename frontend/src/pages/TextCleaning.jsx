import React, { useState, useEffect } from 'react';
import { textCleaningApi } from '../api';
import Layout from '../components/Layout';

const emptyRule = { rule_type: 'remove', match_type: 'simple', find_text: '', replace_text: '', enabled: 1, description: '' };

const TextCleaning = () => {
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState({ ...emptyRule });
  const [testUrl, setTestUrl] = useState('');
  const [testMsg, setTestMsg] = useState('');
  const [testLoading, setTestLoading] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState('');

  useEffect(() => { fetchRules(); }, []);

  const fetchRules = async () => {
    try {
      const res = await textCleaningApi.list();
      setRules(res.data);
    } catch (err) {
      console.error('Failed to load rules', err);
    } finally {
      setLoading(false);
    }
  };

  const openAdd = () => {
    setEditingId(null);
    setForm({ ...emptyRule });
    setShowForm(true);
  };

  const openEdit = (r) => {
    setEditingId(r.id);
    setForm({ ...r });
    setShowForm(true);
  };

  const handleSave = async () => {
    try {
      if (editingId) {
        await textCleaningApi.update(editingId, form);
      } else {
        await textCleaningApi.add(form);
      }
      setShowForm(false);
      fetchRules();
    } catch (err) {
      alert('Save failed: ' + err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this rule?')) return;
    try {
      await textCleaningApi.delete(id);
      fetchRules();
    } catch (err) {
      alert('Delete failed: ' + err.message);
    }
  };

  const handleToggle = async (r) => {
    try {
      await textCleaningApi.update(r.id, { enabled: r.enabled ? 0 : 1 });
      fetchRules();
    } catch (err) {
      alert('Toggle failed: ' + err.message);
    }
  };

  const handleMove = async (id, dir) => {
    const idx = rules.findIndex(r => r.id === id);
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= rules.length) return;
    try {
      await textCleaningApi.reorder(id, newIdx);
      fetchRules();
    } catch (err) {
      alert('Reorder failed: ' + err.message);
    }
  };

  const handleTest = async () => {
    if (!testUrl.trim()) return;
    setTestLoading(true);
    setTestMsg('');
    setDownloadUrl('');
    try {
      const res = await textCleaningApi.test(testUrl.trim());
      setDownloadUrl(res.data.download_url);
      setTestMsg('Test complete. Download the result below.');
    } catch (err) {
      setTestMsg('Error: ' + (err.response?.data?.detail || err.message));
    } finally {
      setTestLoading(false);
    }
  };

  if (loading) return <Layout><div className="text-center py-10 text-gray-500">Loading rules...</div></Layout>;

  return (
    <Layout title="Text Cleaning" subtitle="Manage rules for cleaning chapter content before DOCX output">
      <div className="flex gap-2 mb-4">
        <button onClick={openAdd} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium transition">
          + Add Rule
        </button>
      </div>

      {showForm && (
        <div className="bg-white rounded-lg shadow p-6 mb-6 border border-blue-200">
          <h3 className="text-lg font-semibold mb-4">{editingId ? 'Edit Rule' : 'Add Rule'}</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
              <select value={form.rule_type} onChange={e => setForm({...form, rule_type: e.target.value})}
                className="w-full border rounded px-3 py-2 text-sm">
                <option value="remove">Remove</option>
                <option value="replace">Replace</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Match</label>
              <select value={form.match_type} onChange={e => setForm({...form, match_type: e.target.value})}
                className="w-full border rounded px-3 py-2 text-sm">
                <option value="simple">Simple</option>
                <option value="regex">Regex</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Enabled</label>
              <select value={form.enabled} onChange={e => setForm({...form, enabled: Number(e.target.value)})}
                className="w-full border rounded px-3 py-2 text-sm">
                <option value={1}>Yes</option>
                <option value={0}>No</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Find Text</label>
              <textarea value={form.find_text} onChange={e => setForm({...form, find_text: e.target.value})}
                className="w-full border rounded px-3 py-2 text-sm font-mono" rows={2} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Replace Text (only for Replace type)</label>
              <textarea value={form.replace_text} onChange={e => setForm({...form, replace_text: e.target.value})}
                className="w-full border rounded px-3 py-2 text-sm font-mono" rows={2} />
            </div>
          </div>
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
            <input value={form.description} onChange={e => setForm({...form, description: e.target.value})}
              className="w-full border rounded px-3 py-2 text-sm" />
          </div>
          <div className="flex gap-2">
            <button onClick={handleSave} className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded text-sm font-medium transition">
              Save
            </button>
            <button onClick={() => setShowForm(false)} className="bg-gray-300 hover:bg-gray-400 text-gray-700 px-4 py-2 rounded text-sm font-medium transition">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg shadow overflow-hidden mb-6">
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <th className="px-4 py-4 w-16">Order</th>
              <th className="px-4 py-4 w-20">Active</th>
              <th className="px-4 py-4 w-20">Type</th>
              <th className="px-4 py-4 w-20">Match</th>
              <th className="px-4 py-4">Find</th>
              <th className="px-4 py-4">Replace</th>
              <th className="px-4 py-4">Description</th>
              <th className="px-4 py-4 w-40 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {rules.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-12 text-center text-gray-400">No rules yet.</td></tr>
            )}
            {rules.map((r, i) => (
              <tr key={r.id} className={`hover:bg-gray-50 transition ${!r.enabled ? 'bg-gray-50' : ''}`}>
                <td className="px-4 py-3 text-sm text-gray-500">
                  <div className="flex items-center gap-1">
                    <span className="w-5 text-center">{i + 1}</span>
                    <div className="flex flex-col">
                      <button onClick={() => handleMove(r.id, -1)} disabled={i === 0}
                        className="text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30 leading-tight">▲</button>
                      <button onClick={() => handleMove(r.id, 1)} disabled={i === rules.length - 1}
                        className="text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30 leading-tight">▼</button>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <button onClick={() => handleToggle(r)}
                    className={`text-xs font-bold px-2 py-1 rounded transition cursor-pointer ${
                      r.enabled ? 'bg-green-100 text-green-700 hover:bg-green-200' : 'bg-gray-200 text-gray-500 hover:bg-gray-300'
                    }`}
                    title="Click to toggle">
                    {r.enabled ? 'ON' : 'OFF'}
                  </button>
                </td>
                <td className="px-4 py-3 text-sm font-medium">{r.rule_type}</td>
                <td className="px-4 py-3 text-sm">{r.match_type === 'regex' ? <span className="text-purple-600 font-mono text-xs">regex</span> : <span className="text-gray-600">simple</span>}</td>
                <td className="px-4 py-3 text-sm font-mono max-w-[250px] truncate">{r.find_text}</td>
                <td className="px-4 py-3 text-sm font-mono max-w-[150px] truncate">{r.replace_text || '—'}</td>
                <td className="px-4 py-3 text-sm text-gray-500 max-w-[200px] truncate">{r.description || '—'}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => openEdit(r)} className="text-xs bg-indigo-100 hover:bg-indigo-200 text-indigo-700 px-2 py-1 rounded transition mr-1">Edit</button>
                  <button onClick={() => handleDelete(r.id)} className="text-xs bg-red-100 hover:bg-red-200 text-red-700 px-2 py-1 rounded transition">Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Test Section */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-2">Test Current Rules</h3>
        <p className="text-sm text-gray-500 mb-3">Enter a chapter URL to fetch and clean its content with the currently enabled rules.</p>
        <div className="flex gap-2">
          <input value={testUrl} onChange={e => setTestUrl(e.target.value)}
            placeholder="Chapter URL (e.g. /doc-truyen/.../chuong-1 or full URL)"
            className="flex-1 border rounded px-3 py-2 text-sm" />
          <button onClick={handleTest} disabled={testLoading || !testUrl.trim()}
            className="bg-teal-600 hover:bg-teal-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition">
            {testLoading ? 'Processing...' : 'Test'}
          </button>
        </div>
        {testMsg && <div className={`mt-3 text-sm ${testMsg.startsWith('Error') ? 'text-red-600' : 'text-blue-700'}`}>{testMsg}</div>}
        {downloadUrl && (
          <a href={downloadUrl} target="_blank"
            className="mt-2 inline-block bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded text-sm font-medium transition">
            Download Result
          </a>
        )}
      </div>
    </Layout>
  );
};

export default TextCleaning;
