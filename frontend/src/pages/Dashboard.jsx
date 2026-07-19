import React, { useState, useEffect } from 'react';
import { bookApi } from '../api';
import { bookStatusColors } from '../constants';
import Layout from '../components/Layout';

const Dashboard = ({ onViewBook }) => {
  const [books, setBooks] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchBooks = async () => {
    try {
      const res = await bookApi.getAll({ per_page: 1000 });
      const data = res.data;
      const books = data.books || data;
      setBooks(books);
    } catch (err) {
      console.error('Failed to fetch books', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBooks();
  }, []);

  const stats = {
    total: books.length,
    completed: books.filter(b => b.download_status === 'completed').length,
    pending: books.filter(b => b.download_status === 'pending' || b.download_status === 'ready_for_download').length,
    failed: books.filter(b => b.download_status === 'failed').length,
  };

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
