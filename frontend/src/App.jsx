import React, { useState } from 'react';
import Navbar from './components/Navbar';
import Dashboard from './pages/Dashboard';
import BookList from './pages/BookList';
import Extraction from './pages/Extraction';
import Settings from './pages/Settings';
import BookDetails from './pages/BookDetails';
import LogsViewer from './pages/LogsViewer';
import UpdatesPage from './pages/UpdatesPage';

function App() {
  const [activePage, setActivePage] = useState('dashboard');
  const [selectedBookId, setSelectedBookId] = useState(null);

  const navigateTo = (page, bookId = null) => {
    setSelectedBookId(bookId);
    setActivePage(page);
  };

  const renderPage = () => {
    switch(activePage) {
      case 'dashboard':
        return <Dashboard onViewBook={(page) => navigateTo(page)} />;
      case 'booklist':
        return <BookList onViewBook={(id) => navigateTo('bookdetails', id)} />;
      case 'extract':
        return <Extraction />;
      case 'settings':
        return <Settings />;
      case 'logs':
        return <LogsViewer />;
      case 'updates':
        return <UpdatesPage onViewBook={(id) => navigateTo('bookdetails', id)} />;
      case 'bookdetails':
        return <BookDetails bookId={selectedBookId} onBack={() => navigateTo('booklist')} />;
      default:
        return <Dashboard onViewBook={(page) => navigateTo(page)} />;
    }
  };

  return (
    <div className="min-h-screen bg-gray-100">
      <Navbar activePage={activePage} setActivePage={(page) => navigateTo(page)} />
      <main className="py-8 px-4 max-w-[1600px] mx-auto main-content">
        {renderPage()}
      </main>
    </div>
  );
}

export default App;
