import React from 'react';
import { bookApi, errMsg } from '../../api';

/**
 * Sticky toolbar at the top of BookDetails: Back, Edit Info, Corrections,
 * and the favorite / sent toggles.
 *
 * @param {object} props
 * @param {object} props.book - book row (reads is_favorite, is_sent)
 * @param {boolean} props.editOpen - whether the Edit Info form is shown
 * @param {boolean} props.correctionsOpen - whether the Corrections modal is shown
 * @param {() => void} props.onBack - go back to the book list
 * @param {() => void} props.onToggleEdit - show/hide the Edit Info form
 * @param {() => void} props.onOpenCorrections - open the Corrections modal
 * @param {() => void} props.onChanged - reload page data after a toggle was saved
 */
const BookToolbar = ({ book, editOpen, correctionsOpen, onBack, onToggleEdit, onOpenCorrections, onChanged }) => {
  /**
   * Run one toggle endpoint (API call), then let the parent reload.
   * @param {(id: number) => Promise<any>} apiFn - e.g. bookApi.toggleFavorite
   */
  const toggle = async (apiFn) => {
    try {
      await apiFn(book.id);
      onChanged();
    } catch (err) {
      alert('Update failed: ' + errMsg(err));
    }
  };

  return (
    // `sticky top-0` keeps the bar visible while scrolling the long chapter list.
    <div className="sticky top-0 z-20 bg-white/95 backdrop-blur-sm border-b border-gray-200 py-2 -mx-4 px-4 mb-4 flex items-center justify-between">
      <button onClick={onBack} className="text-sm text-gray-500 hover:text-blue-600 transition">&larr; Back</button>
      <div className="flex gap-2">
        <button onClick={onToggleEdit}
          className="text-sm px-3 py-1 rounded transition bg-gray-100 text-gray-600 hover:text-blue-600">
          {editOpen ? 'Cancel' : 'Edit Info'}
        </button>
        <button onClick={onOpenCorrections}
          className={`text-sm px-3 py-1 rounded transition ${correctionsOpen ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-600 hover:text-indigo-600'}`}
          title="Open text corrections settings">
          Corrections
        </button>
        <button onClick={() => toggle(bookApi.toggleFavorite)}
          className={`text-lg leading-none px-2 py-1 rounded transition ${book.is_favorite ? 'text-yellow-500 bg-yellow-50' : 'text-gray-300 hover:text-yellow-400 hover:bg-gray-50'}`}
          title={book.is_favorite ? 'Remove from favorites' : 'Add to favorites'}>
          {book.is_favorite ? '★' : '☆'} Favorites
        </button>
        <button onClick={() => toggle(bookApi.toggleSent)}
          className={`text-sm leading-none px-2 py-1 rounded transition ${book.is_sent ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400 hover:text-gray-600'}`}
          title={book.is_sent ? 'Mark as not sent' : 'Mark as sent'}>
          ✓ {book.is_sent ? 'Sent' : 'Not sent'}
        </button>
      </div>
    </div>
  );
};

export default BookToolbar;
