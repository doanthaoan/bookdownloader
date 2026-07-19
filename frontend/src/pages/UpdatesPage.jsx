import React, { useState } from 'react';
import { bookApi } from '../api';
import Layout from '../components/Layout';

const UpdatesPage = ({ onViewBook }) => {
  const [updatedBooks, setUpdatedBooks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [checked, setChecked] = useState(false);
  const [message, setMessage] = useState('');

  const handleCheck = async () => {
    setLoading(true);
    setMessage('');
    try {
      const res = await bookApi.checkUpdates();
      setUpdatedBooks(res.data.books || []);
      setChecked(true);
      setMessage(`Checked ${res.data.updated} book(s) with new chapters.`);
    } catch (err) {
      setMessage('Error checking updates: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleContinueExtract = async (bookId) => {
    try {
      await bookApi.continueExtract(bookId);
      alert('Continue extraction started. New chapters will be appended.');
    } catch (err) {
      alert('Error: ' + err.message);
    }
  };

  return (
    <Layout title="Updates" subtitle="Check ongoing books for new chapters">
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <p className="text-sm text-gray-600 mb-4">
          Scans all books with web status <strong>"Còn tiếp"</strong> (Ongoing) or <strong>"Chưa xác minh"</strong> (Unknown)
          to see if the latest chapter has changed since your last extraction.
        </p>
        <button
          onClick={handleCheck}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-5 py-2 rounded text-sm font-medium transition"
        >
          {loading ? 'Checking...' : 'Check for Updates'}
        </button>
        {message && (
          <div className="mt-3 p-3 bg-blue-50 text-blue-700 rounded border border-blue-200 text-sm">{message}</div>
        )}
      </div>

      {checked && updatedBooks.length === 0 && (
        <div className="bg-white rounded-lg shadow p-6 text-center text-gray-400 text-sm">
          No updates found. All ongoing books are up to date.
        </div>
      )}

      {updatedBooks.length > 0 && (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                <th className="px-6 py-4">Title</th>
                <th className="px-6 py-4">Author</th>
                <th className="px-6 py-4">Old Latest</th>
                <th className="px-6 py-4">New Latest</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {updatedBooks.map(b => (
                <tr key={b.id} className="hover:bg-gray-50 transition">
                  <td className="px-6 py-4">
                    <button onClick={() => onViewBook(b.id)} className="font-medium text-gray-900 hover:text-blue-600 transition">
                      {b.title}
                    </button>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">{b.author || '—'}</td>
                  <td className="px-6 py-4 text-sm text-gray-500 truncate max-w-[200px]">{b.old_last_chapter || '—'}</td>
                  <td className="px-6 py-4 text-sm text-blue-600 truncate max-w-[200px]">{b.new_last_chapter}</td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => handleContinueExtract(b.id)}
                      className="text-xs bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-1.5 rounded transition"
                    >
                      Continue Extract
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Layout>
  );
};

export default UpdatesPage;
