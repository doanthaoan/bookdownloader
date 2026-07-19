import React from 'react';
import { bookApi, settingsApi } from '../api';
import Layout from '../components/Layout';

const Extraction = () => {
  const [form, setForm] = React.useState({ title: '', url: '' });
  const [loading, setLoading] = React.useState(false);
  const [message, setMessage] = React.useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage('');
    try {
      const res = await bookApi.extract(form.title, form.url);
      setMessage(res.data.message);
    } catch (err) {
      setMessage('Error: ' + (err.response?.data?.detail || err.message));
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
            <div className={`p-3 rounded text-sm ${message.includes('Error') ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-green-50 text-green-700 border border-green-200'}`}>
              {message}
            </div>
          )}
        </form>
      </div>
    </Layout>
  );
};

export default Extraction;
