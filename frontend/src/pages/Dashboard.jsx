import React, { useState, useEffect } from 'react';
import { bookApi, settingsApi } from '../api';
import Layout from '../components/Layout';

/**
 * Dashboard: book counts per status plus the current site configuration.
 * @param {{onViewBook: (page: string) => void}} props
 *   Despite the name, `onViewBook` navigates to a page id ('booklist', 'extract').
 */
const Dashboard = ({ onViewBook }) => {
  const [books, setBooks] = useState([]);
  // db_settings is an array of {key, value, description} rows.
  const [siteConfig, setSiteConfig] = useState([]);
  const [loading, setLoading] = useState(true);

  /**
   * Load books for the counters (API call, sets `books`).
   * TODO: ask the backend for counts instead of fetching up to 1000 books (counts are wrong past 1000).
   */
  const fetchBooks = async () => {
    const res = await bookApi.getAll({ per_page: 1000 });
    setBooks(res.data.books || []);
  };

  /** Load DB settings (API call, sets `siteConfig`). Falls back to [] if the shape is unexpected. */
  const fetchSiteConfig = async () => {
    const res = await settingsApi.getSettings();
    const rows = res.data?.db_settings;
    setSiteConfig(Array.isArray(rows) ? rows : []);
  };

  // Run both loads once on mount (empty dependency array). allSettled lets
  // one failure not hide the other's data; failures are only logged.
  useEffect(() => {
    Promise.allSettled([fetchBooks(), fetchSiteConfig()])
      .then(results => results
        .filter(r => r.status === 'rejected')
        .forEach(r => console.error('Failed to fetch dashboard data', r.reason)))
      .finally(() => setLoading(false));
  }, []);

  const stats = {
    total: books.length,
    completed: books.filter(b => b.download_status === 'completed').length,
    pending: books.filter(b => b.download_status === 'pending' || b.download_status === 'ready_for_download').length,
    failed: books.filter(b => b.download_status === 'failed').length,
  };

  /** Read one setting value, or 'Not set'. `?.` avoids a crash when the key is missing. */
  const settingValue = (key) => siteConfig.find(c => c.key === key)?.value || 'Not set';

  if (loading) return <div className="text-center py-10 text-gray-500">Loading...</div>;

  return (
    <Layout title="Dashboard" subtitle="Overview of all your books">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <div className="bg-white p-5 rounded-lg shadow border-l-4 border-blue-500">
          <p className="text-gray-500 text-sm font-medium">Total Books</p>
          <p className="text-3xl font-bold mt-1">{stats.total}</p>
        </div>
        <div className="bg-white p-5 rounded-lg shadow border-l-4 border-green-500">
          <p className="text-gray-500 text-sm font-medium">Completed</p>
          <p className="text-3xl font-bold mt-1 text-green-600">{stats.completed}</p>
        </div>
        <div className="bg-white p-5 rounded-lg shadow border-l-4 border-yellow-500">
          <p className="text-gray-500 text-sm font-medium">Pending</p>
          <p className="text-3xl font-bold mt-1 text-yellow-600">{stats.pending}</p>
        </div>
        <div className="bg-white p-5 rounded-lg shadow border-l-4 border-red-500">
          <p className="text-gray-500 text-sm font-medium">Failed</p>
          <p className="text-3xl font-bold mt-1 text-red-600">{stats.failed}</p>
        </div>
      </div>
      <div className="bg-white rounded-lg shadow p-6 mb-8">
        <h2 className="text-lg font-semibold mb-2">Site Configuration</h2>
        <p className="text-gray-500 text-sm mb-4">Current site configuration for TruyenWiki.</p>
        <p className="text-gray-700 text-sm mb-2"><strong>Domain:</strong> {settingValue('domain')}</p>
        <p className="text-gray-700 text-sm mb-2"><strong>Book Path:</strong> {settingValue('book_path')}</p>
        <p className="text-gray-700 text-sm mb-2"><strong>Logs Path:</strong> {settingValue('logs_path')}</p>
      </div>
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold mb-2">Recent Books</h2>
        <p className="text-gray-500 text-sm mb-4">View all your books in the Book List page.</p>
        <div className="flex gap-3">
          <button onClick={() => onViewBook('booklist')} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm">
            Go to Book List
          </button>
          <button onClick={() => onViewBook('extract')} className="bg-gray-200 hover:bg-gray-300 text-gray-700 px-4 py-2 rounded text-sm">
            Extract New Book
          </button>
        </div>
      </div>
    </Layout>
  );
};

export default Dashboard;
