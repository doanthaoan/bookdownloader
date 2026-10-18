import React from 'react';
import { bookApi, errMsg } from '../api';
import Layout from '../components/Layout';

/**
 * Extract page: submit a book title + URL so the backend scrapes its
 * chapter list (the download itself is started later from BookDetails).
 */
const Extraction = () => {
  const [form, setForm] = React.useState({ title: '', url: '' });
  const [loading, setLoading] = React.useState(false);
  // Result banner; `isError` decides the color instead of sniffing the text.
  const [message, setMessage] = React.useState('');
  const [isError, setIsError] = React.useState(false);

  /**
   * Submit handler (API call: bookApi.extract; sets message/loading).
   * @param {React.FormEvent} e
   */
  const handleSubmit = async (e) => {
    e.preventDefault(); // stop the browser's default full-page form submit
    setLoading(true);
    setMessage('');
    try {
      const res = await bookApi.extract(form.title, form.url);
      setIsError(false);
      setMessage(res.data.message);
    } catch (err) {
      setIsError(true);
      setMessage('Error: ' + errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Layout title="Extract Book" subtitle="Enter a book URL to extract its chapter list">
      <div className="max-w-2xl bg-white rounded-lg shadow p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Book Title</label>
            {/* Controlled input: value comes from state, onChange copies the form object with one field replaced. */}
            <input
              type="text"
              className="w-full p-2.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              value={form.title}
              onChange={(e) => setForm({...form, title: e.target.value})}
              placeholder="Enter book title..."
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Book URL</label>
            <input
              type="url"
              className="w-full p-2.5 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              value={form.url}
              onChange={(e) => setForm({...form, url: e.target.value})}
              placeholder="https://wikicv.org/..."
              required
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className={`w-full py-2.5 px-4 rounded-md text-white font-semibold transition ${loading ? 'bg-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'}`}
          >
            {loading ? 'Extracting...' : 'Start Extraction'}
          </button>
          {message && (
            <div className={`p-3 rounded text-sm ${isError ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-green-50 text-green-700 border border-green-200'}`}>
              {message}
            </div>
          )}
        </form>
      </div>
    </Layout>
  );
};

export default Extraction;
