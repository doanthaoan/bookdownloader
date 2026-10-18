import React, { useState } from 'react';
import Navbar from './components/Navbar';
import Dashboard from './pages/Dashboard';
import BookList from './pages/BookList';
import Extraction from './pages/Extraction';
import Settings from './pages/Settings';
import BookDetails from './pages/BookDetails';
import LogsViewer from './pages/LogsViewer';
import UpdatesPage from './pages/UpdatesPage';
import TextCleaning from './pages/TextCleaning';
import Translate from './pages/Translate';
import Statistics from './pages/Statistics';

/**
 * Root component and poor-man's router: the current page lives in state
 * instead of the URL, so a browser refresh always returns to the Dashboard.
 * TODO: switch to hash routing so pages/filters are linkable (PLAN.md Phase 3).
 */
function App() {
  const [activePage, setActivePage] = useState('dashboard');
  const [selectedBookId, setSelectedBookId] = useState(null);

  /**
   * Switch page (and optionally which book BookDetails shows).
   * @param {string} page - page id (see the switch below / Navbar items)
   * @param {number|null} bookId - book to open on 'bookdetails'
   */
  const navigateTo = (page, bookId = null) => {
    setSelectedBookId(bookId);
    setActivePage(page);
  };

  /** Return the element for the active page. */
  const renderPage = () => {
    switch(activePage) {
      case 'dashboard':
        // Dashboard's buttons pass a page id, not a book id.
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
      case 'textcleaning':
        return <TextCleaning />;
      case 'translate':
        return <Translate onViewBook={(id) => navigateTo('bookdetails', id)} />;
      case 'statistics':
        return <Statistics />;
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
