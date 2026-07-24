import React, { useState, useEffect } from 'react';
import { bookApi } from '../api';
import { bookStatusColors } from '../constants';
import Layout from '../components/Layout';

const BookList = ({ onViewBook }) => {
  const [books, setBooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [authorFilter, setAuthorFilter] = useState('');
  const [webStatusFilter, setWebStatusFilter] = useState('');
  const [sentFilter, setSentFilter] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);

  const fetchBooks = async () => {
    setLoading(true);
    try {
      const params = { page, per_page: 20 };
      if (search) params.search = search;
      if (statusFilter) params.status = statusFilter;
      if (authorFilter) params.author = authorFilter;
      if (webStatusFilter) params.book_web_status = webStatusFilter;
      if (sentFilter !== '') params.sent = sentFilter === 'sent' ? 1 : 0;
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
  }, [page, statusFilter, authorFilter, webStatusFilter, sentFilter]);

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

  const handleToggleFavorite = async (id) => {
    try {
      await bookApi.toggleFavorite(id);
      fetchBooks();
    } catch (err) {
      console.error('Toggle favorite failed', err);
    }
  };

  const handleToggleSent = async (id) => {
    try {
      await bookApi.toggleSent(id);
      fetchBooks();
    } catch (err) {
      console.error('Toggle sent failed', err);
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
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Author</label>
            <input
              className="border rounded px-3 py-2 text-sm w-40"
              placeholder="Filter author..."
              value={authorFilter}
              onChange={e => { setAuthorFilter(e.target.value); setPage(1); }}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Web Status</label>
            <select
              className="border rounded px-3 py-2 text-sm"
              value={webStatusFilter}
              onChange={e => { setWebStatusFilter(e.target.value); setPage(1); }}
            >
              {['', 'Còn tiếp', 'Hoàn thành', 'Tạm Ngưng', 'Chưa xác minh'].map(s => (
                <option key={s} value={s}>{s || 'Any'}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Sent</label>
            <select
              className="border rounded px-3 py-2 text-sm"
              value={sentFilter}
              onChange={e => { setSentFilter(e.target.value); setPage(1); }}
            >
              <option value="">All</option>
              <option value="sent">Sent</option>
              <option value="not_sent">Not sent</option>
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
              <th className="p-2 w-10 text-center" title="Favorite">☆</th>
              <th className="p-2 w-10 text-center" title="Sent">📤</th>
              <th className="p-2 w-14">ID</th>  
              <th className="p-2">Title</th>
              <th className="p-2 w-28">Author</th>
              <th className="p-2 w-24">Web</th>
              <th className="p-2 w-20">Ch.</th>
              <th className="p-2 w-28">Status</th>
              <th className="p-2 w-28 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {loading ? (
              <tr><td colSpan={9} className="px-6 py-12 text-center text-gray-400">Loading...</td></tr>
            ) : books.length === 0 ? (
              <tr><td colSpan={9} className="px-6 py-12 text-center text-gray-400">No books found.</td></tr>
            ) : (
              books.map(book => (
                <tr key={book.id} className="hover:bg-gray-50 transition">
                  <td className="p-2 text-center">
                    <button onClick={() => handleToggleFavorite(book.id)}
                      className={`text-lg leading-none transition ${book.is_favorite ? 'text-yellow-500' : 'text-gray-300 hover:text-yellow-400'}`}
                      title={book.is_favorite ? 'Remove from favorites' : 'Add to favorites'}>
                      {book.is_favorite ? '★' : '☆'}
                    </button>
                  </td>
                  <td className="p-2 text-center">
                    <button onClick={() => handleToggleSent(book.id)}
                      className={`text-sm leading-none px-1 py-0.5 rounded transition ${book.is_sent ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400 hover:text-gray-600'}`}
                      title={book.is_sent ? 'Mark as not sent' : 'Mark as sent'}>
                      ✓
                    </button>
                  </td>
                  <td className="p-2 text-sm text-gray-500">{book.id}</td>  
                  <td className="p-2 max-w-0">
                    <button onClick={() => onViewBook(book.id)}
                      className="font-medium text-gray-900 hover:text-blue-600 transition truncate block w-full text-left"
                      title={book.title}>
                      {book.title}
                    </button>
                  </td>
                  <td className="p-2 text-sm text-gray-500 truncate" title={book.author || ''}>{book.author || '—'}</td>
                  <td className="p-2">
                    {book.book_web_status && (
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${
                        book.book_web_status === 'Hoàn thành' ? 'bg-green-100 text-green-700' :
                        book.book_web_status === 'Còn tiếp' ? 'bg-blue-100 text-blue-700' :
                        book.book_web_status === 'Tạm Ngưng' ? 'bg-yellow-100 text-yellow-700' :
                        'bg-gray-100 text-gray-700'
                      }`}>
                        {book.book_web_status}
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-sm text-gray-500 whitespace-nowrap">
                    <span className="font-medium">{book.downloaded_chapters || 0}</span>/{book.total_chapters || 0}
                  </td>
                  <td className="p-2">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold whitespace-nowrap ${bookStatusColors[book.download_status] || 'bg-gray-100 text-gray-800'}`}>
                      {book.download_status.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td className="p-2 text-right whitespace-nowrap">
                    <button onClick={() => onViewBook(book.id)}
                      className="text-xs text-gray-500 hover:text-blue-600 px-1.5 py-1 transition" title="Details">
                      📋
                    </button>
                    {book.download_status !== 'completed' && book.download_status !== 'in_progress' && (
                      <button onClick={() => handleDownload(book.id)}
                        className="text-xs text-gray-500 hover:text-green-600 px-1.5 py-1 transition" title="Download">
                        ⬇
                      </button>
                    )}
                    {book.download_status === 'in_progress' && (
                      <button onClick={() => onViewBook(book.id)}
                        className="text-xs text-indigo-500 px-1.5 py-1 transition" title="In Progress">
                        ⏳
                      </button>
                    )}
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
