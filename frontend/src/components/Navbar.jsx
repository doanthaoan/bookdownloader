import React from 'react';

/** Navigation entries: `id` must match a case in App.jsx renderPage(). */
const navItems = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'booklist', label: 'Book List' },
  { id: 'extract', label: 'Extract Book' },
  { id: 'updates', label: 'Updates' },
  { id: 'textcleaning', label: 'Text Cleaning' },
  { id: 'translate', label: 'Translate' },
  { id: 'statistics', label: 'Statistics' },
  { id: 'logs', label: 'Logs' },
  { id: 'settings', label: 'Settings' },
];

/**
 * Top navigation bar; highlights the active page.
 * @param {{activePage: string, setActivePage: (id: string) => void}} props
 */
const Navbar = ({ activePage, setActivePage }) => {
  return (
    <nav className="bg-slate-800 text-white shadow-lg">
      <div className="max-w-6xl mx-auto px-4 py-3 flex justify-between items-center">
        <div className="text-xl font-bold tracking-tight">Novel Downloader</div>
        <div className="flex gap-1">
          {/* Lists rendered with .map need a stable `key` so React can track items. */}
          {navItems.map(item => (
            <button
              key={item.id}
              onClick={() => setActivePage(item.id)}
              className={`px-4 py-2 rounded-md text-sm font-medium transition ${
                activePage === item.id
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-300 hover:text-white hover:bg-slate-700'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
