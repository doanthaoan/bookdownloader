import React, { useState, useEffect } from 'react';
import { bookApi, errMsg } from '../api';
import { bookStatusColors, BOOK_STATUS_OPTIONS, WEB_STATUS_OPTIONS, webStatusClass, isTranslated } from '../constants';
import Layout from '../components/Layout';

/** Books per page requested from the backend. */
const PER_PAGE = 20;
/** Delay before the author filter is applied after the last keystroke. */
const AUTHOR_DEBOUNCE_MS = 400;

/**
 * Book list page: filterable, paginated table of all books.
 * @param {{onViewBook: (id: number) => void}} props - opens BookDetails
 */
const BookList = ({ onViewBook }) => {
  const [books, setBooks] = useState([]);
  const [loading, setLoading] = useState(true);
  // `search` is the text box; `searchQuery` is the value actually sent
  // (only updated on submit, so typing doesn't fetch).
  const [search, setSearch] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  // `authorInput` follows every keystroke; `authorFilter` follows it after a pause (debounce).
  const [authorInput, setAuthorInput] = useState('');
  const [authorFilter, setAuthorFilter] = useState('');
  const [webStatusFilter, setWebStatusFilter] = useState('');
  const [sentFilter, setSentFilter] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [allTags, setAllTags] = useState([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  // Bumping this number forces a refetch with unchanged filters (e.g. after a toggle).
  const [reloadTick, setReloadTick] = useState(0);

  /** Ask the list effect below to fetch again. Functional setState reads the latest value. */
  const reload = () => setReloadTick(t => t + 1);

  // Load the tag dropdown once on mount.
  useEffect(() => {
    bookApi.allTags().then(r => setAllTags(r.data || [])).catch(() => {});
  }, []);

  // Debounce: every keystroke restarts a 400 ms timer; only when the user
  // stops typing does the timer fire and update `authorFilter` (which
  // triggers the fetch). The cleanup clears the previous timer, which is
  // what "restarts" it - React runs cleanup before each re-run.
  useEffect(() => {
    const t = setTimeout(() => {
      setAuthorFilter(authorInput);
      setPage(1);
    }, AUTHOR_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [authorInput]);

  // The single place that fetches books: runs whenever a filter, the page,
  // or reloadTick changes. Several setState calls in one handler are
  // batched by React into one render, so this effect runs once per action.
  useEffect(() => {
    // `cancelled` guards against out-of-order responses: if filters change
    // again before this request returns, cleanup marks it stale and its
    // result is ignored.
    let cancelled = false;
    const params = { page, per_page: PER_PAGE };
    if (searchQuery) params.search = searchQuery;
    if (statusFilter) params.status = statusFilter;
    if (authorFilter) params.author = authorFilter;
    if (webStatusFilter) params.book_web_status = webStatusFilter;
    if (sentFilter !== '') params.sent = sentFilter === 'sent' ? 1 : 0;
    if (tagFilter) params.tag = tagFilter;

    setLoading(true);
    bookApi.getAll(params)
      .then(res => {
        if (cancelled) return;
        const data = res.data;
        setBooks(data.books || []);
        setTotal(data.total || 0);
        setTotalPages(data.total_pages || 1);
      })
      .catch(err => console.error('Failed to fetch books', err))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [page, searchQuery, statusFilter, authorFilter, webStatusFilter, sentFilter, tagFilter, reloadTick]);

  /** Search submit: commit the text, go to page 1, and force one fetch. */
  const handleSearch = (e) => {
    e.preventDefault();
    setSearchQuery(search);
    setPage(1);
    reload(); // ensures a fetch even if the query and page didn't change
  };

  /**
   * Filter by a tag clicked in the table.
   * @param {string} tag
   */
  const handleTagClick = (tag) => {
    setTagFilter(tag);
    setPage(1);
  };

  /**
   * Delete a book after confirmation (API call: bookApi.delete; removes it from local state).
   * @param {number} id
   */
  // TODO: not wired to any button yet - add a delete action to the row or remove this handler.
  const handleDelete = async (id) => {
    if (!confirm('Delete this book and all its chapters?')) return;
    try {
      await bookApi.delete(id);
      // Functional update: filter the latest list, not a possibly stale copy.
      setBooks(prev => prev.filter(b => b.id !== id));
    } catch (err) {
      alert('Delete failed: ' + errMsg(err));
    }
  };

  /**
   * Start downloading a book in the background (API call: bookApi.download).
   * @param {number} id
   */
  const handleDownload = async (id) => {
    try {
      const res = await bookApi.download(id);
      alert(res.data.message);
    } catch (err) {
      alert('Download start failed: ' + errMsg(err));
    }
  };

  /** Toggle favorite flag (API call), then refetch the page. */
  const handleToggleFavorite = async (id) => {
    try {
      await bookApi.toggleFavorite(id);
      reload();
    } catch (err) {
      alert('Toggle favorite failed: ' + errMsg(err));
    }
  };

  /** Toggle sent flag (API call), then refetch the page. */
  const handleToggleSent = async (id) => {
    try {
      await bookApi.toggleSent(id);
      reload();
    } catch (err) {
      alert('Toggle sent failed: ' + errMsg(err));
    }
  };

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
              {BOOK_STATUS_OPTIONS.map(s => (
                <option key={s} value={s}>{s ? s.replace(/_/g, ' ') : 'All statuses'}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Author</label>
            <input
              className="border rounded px-3 py-2 text-sm w-40"
              placeholder="Filter author..."
              value={authorInput}
              onChange={e => setAuthorInput(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Web Status</label>
            <select
              className="border rounded px-3 py-2 text-sm"
              value={webStatusFilter}
              onChange={e => { setWebStatusFilter(e.target.value); setPage(1); }}
            >
              {WEB_STATUS_OPTIONS.map(s => (
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
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Tag</label>
            <select
              className="border rounded px-3 py-2 text-sm"
              value={tagFilter}
              onChange={e => { setTagFilter(e.target.value); setPage(1); }}
            >
              <option value="">All tags</option>
              {allTags.map(t => (
                <option key={t.id} value={t.name}>{t.name} ({t.book_count})</option>
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
              <th className="p-2 w-10 text-center" title="Favorite">☆</th>
              <th className="p-2 w-10 text-center" title="Sent">📤</th>
              <th className="p-2 w-14">ID</th>
              <th className="p-2">Title</th>
              <th className="p-2 w-28">Author</th>
              <th className="p-2 w-32">Tags</th>
              <th className="p-2 w-24">Web</th>
              <th className="p-2 w-20">Ch.</th>
              <th className="p-2 w-28">Status</th>
              <th className="p-2 w-28 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {loading ? (
              <tr><td colSpan={10} className="px-6 py-12 text-center text-gray-400">Loading...</td></tr>
            ) : books.length === 0 ? (
              <tr><td colSpan={10} className="px-6 py-12 text-center text-gray-400">No books found.</td></tr>
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
                    <div className="flex items-center gap-2">
                      {/* Hide the <img> if the book has no cover (backend returns 404). */}
                      <img src={bookApi.coverUrl(book.id)}
                        className="w-8 h-10 object-cover rounded flex-shrink-0"
                        alt=""
                        onError={e => { e.target.style.display = 'none' }} />
                      <button onClick={() => onViewBook(book.id)}
                        className="font-medium text-gray-900 hover:text-blue-600 transition truncate block text-left"
                        title={book.title}>
                        {book.title}
                      </button>
                    </div>
                  </td>
                  <td className="p-2 text-sm text-gray-500 truncate" title={book.author || ''}>{book.author || '—'}</td>
                  <td className="p-2">
                    {book.tags && book.tags.length > 0 && (
                      <div className="flex flex-wrap gap-0.5 max-h-10 overflow-hidden">
                        {/* Show at most 3 tags; clicking one filters the list by it. */}
                        {book.tags.slice(0, 3).map(t => (
                          <button key={t} type="button" onClick={() => handleTagClick(t)}
                            title={`Filter by tag "${t}"`}
                            className="inline-block px-1.5 py-0.5 text-xs bg-sky-50 text-sky-600 rounded hover:bg-sky-100 transition whitespace-nowrap">
                            {t}
                          </button>
                        ))}
                        {book.tags.length > 3 && (
                          <span className="text-xs text-gray-400">+{book.tags.length - 3}</span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="p-2">
                    {book.book_web_status && (
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${webStatusClass(book.book_web_status)}`}>
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
                    {/* Downloaded books can be started from here; translated books are run from BookDetails. */}
                    {book.download_status !== 'completed' && book.download_status !== 'in_progress' && !isTranslated(book) && (
                      <button onClick={() => handleDownload(book.id)}
                        className="text-xs text-gray-500 hover:text-green-600 px-1.5 py-1 transition" title="Download">
                        ⬇
                      </button>
                    )}
                    {book.download_status !== 'completed' && book.download_status !== 'in_progress' && isTranslated(book) && (
                      <button onClick={() => onViewBook(book.id)}
                        className="text-xs text-gray-500 hover:text-cyan-600 px-1.5 py-1 transition" title="Translate">
                        ✍
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
