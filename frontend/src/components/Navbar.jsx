import React from 'react';

const navItems = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'booklist', label: 'Book List' },
  { id: 'extract', label: 'Extract Book' },
  { id: 'updates', label: 'Updates' },
  { id: 'logs', label: 'Logs' },
  { id: 'settings', label: 'Settings' },
];

const Navbar = ({ activePage, setActivePage }) => {
  return (
    <nav className="bg-slate-800 text-white shadow-lg">
      <div className="max-w-6xl mx-auto px-4 py-3 flex justify-between items-center">
        <div className="text-xl font-bold tracking-tight">Novel Downloader</div>
        <div className="flex gap-1">
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
