import React, { useState, useEffect } from 'react';
import { bookApi } from '../api';
import { bookStatusColors } from '../constants';
import Layout from '../components/Layout';

const BookList = ({ onViewBook }) => {
  const [books, setBooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);

  const fetchBooks = async () => {
    setLoading(true);
    try {
      const params = { page, per_page: 20 };
      if (search) params.search = search;
      if (statusFilter) params.status = statusFilter;
      const res = await bookApi.getAll(params);
      const data = res.data;
      setBooks(data.books || []);
      setTotal(data.total || 0);
      setTotalPages(data.total_pages || 1);
    } catch (err) {
      console.error('Failed to fetch books', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBooks();
  }, [page, statusFilter]);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(1);
    fetchBooks();
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this book and all its chapters?')) return;
    try {
      await bookApi.delete(id);
      setBooks(books.filter(b => b.id !== id));
    } catch (err) {
      alert('Delete failed: ' + err.message);
    }
  };

  const handleDownload = async (id) => {
    try {
      const res = await bookApi.download(id);
      alert(res.data.message);
    } catch (err) {
      alert('Download start failed: ' + err.message);
    }
  };

  const statusOptions = [
    '', 'pending', 'in_progress', 'completed', 'failed', 'completed_with_errors', 'cancelled',
  ];

  return (
    <Layout title="Book List" subtitle={`${total} book${total !== 1 ? 's' : ''} in your library`}>
      <div className="bg-white rounded-lg shadow p-4 mb-4">
        <form onSubmit={handleSearch} className="flex flex-wrap gap-3 items-end">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs font-medium text-gray-500 mb-1">Search</label>
            <input
              className="w-full border rounded px-3 py-2 text-sm"
              placeholder="Search by title..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
            <select
              className="border rounded px-3 py-2 text-sm"
              value={statusFilter}
              onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            >
              {statusOptions.map(s => (
                <option key={s} value={s}>{s || 'All statuses'}</option>
              ))}
            </select>
          </div>
          <button type="submit" className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm">
            Search
          </button>
        </form>
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-gray-50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <th className="px-6 py-4">Title</th>
              <th className="px-6 py-4">Chapters</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {loading ? (
              <tr><td colSpan={4} className="px-6 py-12 text-center text-gray-400">Loading...</td></tr>
            ) : books.length === 0 ? (
              <tr><td colSpan={4} className="px-6 py-12 text-center text-gray-400">No books found.</td></tr>
            ) : (
              books.map(book => (
                <tr key={book.id} className="hover:bg-gray-50 transition">
                  <td className="px-6 py-4">
                    <button onClick={() => onViewBook(book.id)} className="font-medium text-gray-900 hover:text-blue-600 transition">
                      {book.title}
                    </button>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    <span className="font-medium">{book.downloaded_chapters || 0}</span> / {book.total_chapters || 0}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold ${bookStatusColors[book.download_status] || 'bg-gray-100 text-gray-800'}`}>
                      {book.download_status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right space-x-2">
                    <button onClick={() => onViewBook(book.id)} className="text-xs bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-3 py-1.5 rounded transition">
                      Details
                    </button>
                    {(book.downloaded_chapters || 0) > 0 && (
                      <a
                        href={bookApi.docxUrl(book.id)}
                        target="_blank"
                        className="text-xs bg-green-600 hover:bg-green-700 text-white px-3 py-1.5 rounded transition inline-block"
                      >
                        DOCX
                      </a>
                    )}
                    {book.download_status !== 'completed' && book.download_status !== 'in_progress' && (
                      <button onClick={() => handleDownload(book.id)} className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded transition">
                        Download
                      </button>
                    )}
                    {book.download_status === 'in_progress' && (
                      <button onClick={() => onViewBook(book.id)} className="text-xs bg-indigo-100 text-indigo-700 px-3 py-1.5 rounded transition">
                        In Progress
                      </button>
                    )}
                    <button onClick={() => handleDelete(book.id)} className="text-xs bg-red-50 border border-red-200 hover:bg-red-100 text-red-600 px-3 py-1.5 rounded transition">
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-2 mt-4">
          <button
            disabled={page <= 1}
            onClick={() => setPage(p => Math.max(1, p - 1))}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 hover:bg-gray-50"
          >
            &larr; Prev
          </button>
          <span className="text-sm text-gray-600">
            Page {page} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            className="px-3 py-1.5 border rounded text-sm disabled:opacity-40 hover:bg-gray-50"
          >
            Next &rarr;
          </button>
        </div>
      )}
    </Layout>
  );
};

export default BookList;
