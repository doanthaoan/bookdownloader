import React from 'react';
import { bookApi } from '../../api';
import { bookStatusColors, webStatusClass } from '../../constants';

/**
 * Top part of the book card: cover, title/meta, tags, summary, status badge,
 * overall progress bar and (while a job runs) the live progress box.
 * Purely presentational: no state, no API calls.
 *
 * @param {object} props
 * @param {object} props.book - book row
 * @param {string[]} props.tags
 * @param {number} props.completedChapters
 * @param {number} props.totalChapters
 * @param {number} props.failedCount
 * @param {object|null} props.progress - latest job progress response
 * @param {boolean} props.translated - translated book? (changes the progress label)
 */
const BookHeader = ({ book, tags, completedChapters, totalChapters, failedCount, progress, translated }) => {
  const progressPct = totalChapters > 0 ? Math.round((completedChapters / totalChapters) * 100) : 0;

  return (
    <>
      <div className="flex flex-col lg:flex-row gap-6">
        {/* Cover image; onError hides the <img> when the book has no cover (404). */}
        <div className="flex-shrink-0">
          <img src={bookApi.coverUrl(book.id)}
            className="w-32 h-44 object-cover rounded-lg shadow-md"
            alt=""
            onError={e => { e.target.style.display = 'none' }} />
        </div>

        {/* Book info */}
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-bold text-gray-900">{book.title}</h1>
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-gray-500">
            <span>ID: {book.id}</span>
            {book.stt && <span>STT: {book.stt}</span>}
            {book.author && <span>Tác giả: <strong>{book.author}</strong></span>}
            {book.book_web_status && (
              <span className={`px-2 py-0.5 rounded text-xs font-medium ${webStatusClass(book.book_web_status)}`}>
                {book.book_web_status}
              </span>
            )}
            {failedCount > 0 && <span className="text-red-500">{failedCount} failed</span>}
          </div>
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {/* TODO: link to filtered BookList once hash routing exists (PLAN.md Phase 3) */}
              {tags.map(tag => (
                <span key={tag}
                  className="inline-block px-2 py-0.5 text-xs bg-sky-100 text-sky-700 rounded-full">
                  {tag}
                </span>
              ))}
            </div>
          )}
          {book.book_url && (
            <a href={book.book_url} target="_blank" rel="noopener noreferrer" className="inline-block mt-1 text-sm text-blue-500 hover:underline">
              {book.book_url}
            </a>
          )}

          {/* Short description accordion: native <details>/<summary> toggles without any JS state. */}
          {book.short_description && (
            <details className="mt-3 group">
              <summary className="text-sm text-gray-500 cursor-pointer hover:text-gray-700 select-none">
                Summary <span className="text-xs text-gray-400 group-open:hidden">(click to expand)</span>
              </summary>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed whitespace-pre-line">
                {book.short_description}
              </p>
            </details>
          )}
        </div>

        {/* Status badges */}
        <div className="flex flex-col items-end gap-2 flex-shrink-0">
          <span className={`inline-block px-3 py-1 rounded-full text-sm font-semibold ${bookStatusColors[book.download_status] || 'bg-gray-100 text-gray-800'}`}>
            {/* The regex /_/g replaces every underscore, not just the first. */}
            {book.download_status.replace(/_/g, ' ')}
          </span>
          <span className="text-sm text-gray-500">
            {completedChapters} / {totalChapters} chapters
          </span>
        </div>
      </div>

      {totalChapters > 0 && (
        <div className="mt-4">
          <div className="w-full bg-gray-200 rounded-full h-2.5">
            <div className="bg-green-500 h-2.5 rounded-full transition-all" style={{ width: `${progressPct}%` }}></div>
          </div>
        </div>
      )}

      {/* Optional chaining: `progress?.active` is undefined (falsy) while progress is null. */}
      {progress?.active && (
        <div className="mt-3 p-3 bg-indigo-50 border border-indigo-200 rounded text-sm">
          <div className="font-medium text-indigo-800">
            {translated ? 'Translating' : 'Downloading'}: {progress.current_title}
          </div>
          <div className="text-indigo-600 mt-1">
            {progress.success_count} success / {progress.fail_count} failed
            &nbsp;— chapter {progress.current_index} of {progress.total} in this session
          </div>
          {/* identity / wait_seconds come from download progress only (absent for translations). */}
          {progress.identity && (
            <div className="text-indigo-600 mt-1">
              Access: {progress.identity}
              {progress.wait_seconds > 0 && ` — all access limits reached, retrying in ${Math.ceil(progress.wait_seconds / 60)} min`}
            </div>
          )}
        </div>
      )}
    </>
  );
};

export default BookHeader;
