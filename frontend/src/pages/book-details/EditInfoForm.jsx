import React, { useState } from 'react';
import { bookApi, errMsg } from '../../api';

/**
 * Edit Book Info form (title, author, web status, tags, cover, summary).
 *
 * The form keeps its own copy of the values in local state. The parent
 * renders it only while open (`{editOpen && <EditInfoForm/>}`), so it is
 * created fresh from the current book each time it opens, and background
 * polling in the parent can never overwrite what the user is typing.
 *
 * @param {object} props
 * @param {object} props.book - current book row (initial values)
 * @param {string[]} props.tags - current tag names (initial value)
 * @param {() => void} props.onSaved - called after a successful save (parent closes the form and reloads)
 */
const EditInfoForm = ({ book, tags, onSaved }) => {
  // Lazy initial state: the function runs only on the first render, so
  // later re-renders (with new props from polling) don't reset the fields.
  const [form, setForm] = useState(() => ({
    title: book.title || '',
    author: book.author || '',
    short_description: book.short_description || '',
    book_web_status: book.book_web_status || '',
  }));
  const [formTags, setFormTags] = useState(() => tags.join(', '));
  const [coverFile, setCoverFile] = useState(null);

  /**
   * Update one form field. Functional setState builds on the latest form.
   * @param {keyof typeof form} field
   * @param {string} value
   */
  const setField = (field, value) => setForm(prev => ({ ...prev, [field]: value }));

  /** Save info, tags and optional cover (up to 3 API calls), then notify the parent. */
  const handleSave = async () => {
    try {
      const payload = {};
      // An empty title is not sent, so the existing one is kept.
      if (form.title.trim()) payload.title = form.title.trim();
      payload.author = form.author.trim();
      payload.short_description = form.short_description.trim();
      payload.book_web_status = form.book_web_status.trim();
      await bookApi.updateInfo(book.id, payload);
      // "a, b, ,c" → ['a', 'b', 'c']; filter(Boolean) drops empty strings.
      const newTags = formTags.split(',').map(t => t.trim()).filter(Boolean);
      await bookApi.updateBookTags(book.id, newTags);
      if (coverFile) {
        await bookApi.uploadCover(book.id, coverFile);
      }
      alert('Book info saved.');
      onSaved();
    } catch (err) {
      alert('Save failed: ' + errMsg(err));
    }
  };

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-semibold mb-4">Edit Book Info</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Title</label>
          <input type="text" value={form.title}
            onChange={e => setField('title', e.target.value)}
            className="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Author</label>
          <input type="text" value={form.author}
            onChange={e => setField('author', e.target.value)}
            className="w-full border rounded px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Book web status</label>
          <input type="text" value={form.book_web_status}
            onChange={e => setField('book_web_status', e.target.value)}
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
          {/* File inputs can't be controlled (no `value`); we just remember the chosen File object. */}
          <input type="file" accept=".jpg,.jpeg,.png,.gif,.webp"
            onChange={e => setCoverFile(e.target.files[0] || null)}
            className="w-full text-sm" />
        </div>
      </div>
      <div className="mt-4">
        <label className="block text-xs font-medium text-gray-500 mb-1">Summary</label>
        <textarea value={form.short_description}
          onChange={e => setField('short_description', e.target.value)}
          rows={5}
          className="w-full border rounded px-3 py-2 text-sm" />
      </div>
      <div className="mt-4">
        <button onClick={handleSave}
          className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded text-sm font-medium transition">
          Save Info
        </button>
      </div>
    </div>
  );
};

export default EditInfoForm;
