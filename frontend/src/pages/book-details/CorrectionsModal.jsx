import React, { useState, useRef } from 'react';
import { translateApi, errMsg } from '../../api';
import Modal from '../../components/Modal';

/**
 * Per-book find/replace corrections editor (modal), with "copy from another book".
 *
 * Rows live in local state, copied from `initialCorrections` when the modal
 * mounts. The parent renders it only while open, so polling in the parent
 * can't overwrite unsaved edits, and closing without saving discards them.
 * Every successful write reports the saved list up (onSaved / onCopied) so
 * the parent's copy is current immediately.
 *
 * @param {object} props
 * @param {number} props.bookId
 * @param {{find_text: string, replace_text: string, enabled: any}[]} props.initialCorrections
 * @param {() => void} props.onClose
 * @param {(saved: object[]) => void} props.onSaved - after Save (modal should be closed by the parent)
 * @param {(copied: object[]) => void} props.onCopied - after a copy from another book (modal stays open)
 */
const CorrectionsModal = ({ bookId, initialCorrections, onClose, onSaved, onCopied }) => {
  // Each row gets a local `_key` used only as the React list key. Using the
  // array index as key would make React reuse the wrong <input> (and its
  // focus) when a row in the middle is deleted.
  const nextKey = useRef(0);
  /** Give rows fresh local keys. */
  const withKeys = (list) => list.map(c => ({ ...c, _key: nextKey.current++ }));

  const [rows, setRows] = useState(() => withKeys(initialCorrections || []));
  const [copySourceId, setCopySourceId] = useState('');
  const [copying, setCopying] = useState(false);

  /**
   * Edit one field of one row. `map` returns a new array (React only
   * re-renders when it gets a new reference; mutating in place would not).
   * @param {number} key - row _key
   * @param {'find_text'|'replace_text'|'enabled'} field
   * @param {any} value
   */
  const updateRow = (key, field, value) => {
    setRows(prev => prev.map(c => c._key === key ? { ...c, [field]: value } : c));
  };

  /** Rows with text, trimmed, without the local `_key` (the shape the API expects). */
  const cleanRows = () => rows
    .filter(c => (c.find_text || '').trim())
    .map(c => ({
      find_text: (c.find_text || '').trim(),
      replace_text: c.replace_text || '',
      enabled: !!c.enabled, // `!!` converts any value to a real boolean
    }));

  /** Save all rows (API call: updateCorrections); blank rows are dropped. */
  const handleSave = async () => {
    const clean = cleanRows();
    try {
      await translateApi.updateCorrections(bookId, clean);
      alert('Corrections saved.');
      onSaved(clean);
    } catch (err) {
      alert('Save corrections failed: ' + errMsg(err));
    }
  };

  /** Replace this book's corrections with another book's (API call: copyCorrections). */
  const handleCopy = async () => {
    const sid = parseInt(copySourceId, 10);
    if (!sid || sid === bookId) {
      alert('Enter a valid source book ID (different from this book).');
      return;
    }
    const currentCount = cleanRows().length;
    if (!confirm(`Replace all ${currentCount} correction(s) of this book with the corrections of book #${sid}?`)) return;
    setCopying(true);
    try {
      const res = await translateApi.copyCorrections(bookId, sid);
      const data = res.data || {};
      const copied = data.corrections || [];
      setRows(withKeys(copied));
      setCopySourceId('');
      onCopied(copied);
      alert(data.message || 'Corrections copied.');
    } catch (err) {
      alert('Copy failed: ' + errMsg(err));
    } finally {
      setCopying(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="Text Corrections">
      <p className="text-xs text-gray-500 mb-4">
        Find/replace applied to downloaded or translated text, after the global Text Cleaning rules.
        Matching is case-insensitive. Empty rows are ignored on save.
      </p>
      {rows.length === 0 && (
        <p className="text-sm text-gray-400 mb-3">No corrections yet. Add one below.</p>
      )}
      <div className="space-y-2">
        {rows.map(c => (
          <div key={c._key} className="flex flex-wrap items-center gap-2">
            <input type="checkbox" checked={!!c.enabled}
              onChange={e => updateRow(c._key, 'enabled', e.target.checked)}
              className="h-4 w-4" title="Enabled" />
            <input type="text" value={c.find_text || ''}
              onChange={e => updateRow(c._key, 'find_text', e.target.value)}
              placeholder="Find text"
              className="flex-1 min-w-[140px] border rounded px-2 py-1.5 text-sm" />
            <span className="text-gray-400">→</span>
            <input type="text" value={c.replace_text || ''}
              onChange={e => updateRow(c._key, 'replace_text', e.target.value)}
              placeholder="Replace with"
              className="flex-1 min-w-[140px] border rounded px-2 py-1.5 text-sm" />
            <button onClick={() => setRows(prev => prev.filter(r => r._key !== c._key))}
              className="text-sm text-red-500 hover:text-red-700 px-2">✕</button>
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button onClick={() => setRows(prev => [...prev, ...withKeys([{ find_text: '', replace_text: '', enabled: true }])])}
          className="text-sm border border-gray-300 text-gray-600 hover:bg-gray-50 px-3 py-1.5 rounded transition">
          + Add correction
        </button>
        <button onClick={handleSave}
          className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-1.5 rounded text-sm font-medium transition">
          Save Corrections
        </button>
      </div>
      <div className="mt-4 pt-3 border-t border-gray-100">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Copy from another book</p>
        <div className="flex flex-wrap items-center gap-2">
          <input type="number" min="1" value={copySourceId}
            onChange={e => setCopySourceId(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleCopy(); }}
            placeholder="Source book ID"
            className="w-36 border rounded px-2 py-1.5 text-sm" />
          <button onClick={handleCopy} disabled={copying}
            className="text-sm border border-indigo-300 text-indigo-600 hover:bg-indigo-50 px-3 py-1.5 rounded transition disabled:opacity-50">
            {copying ? 'Copying…' : 'Copy Corrections'}
          </button>
          <span className="text-xs text-gray-400">Replaces this book's corrections.</span>
        </div>
      </div>
    </Modal>
  );
};

export default CorrectionsModal;
