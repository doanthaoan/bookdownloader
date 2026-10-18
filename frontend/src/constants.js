/**
 * Shared UI constants and tiny helpers used by several pages.
 * Keeping them here means a new status or a colour change is a one-line edit.
 */

/** How often (ms) BookDetails and Translate poll a running job's progress. */
export const POLL_MS = 2000;

/** Badge classes per `books.download_status`. Keys also drive the BookList status filter. */
export const bookStatusColors = {
  pending: 'bg-yellow-100 text-yellow-800 border-l-4 border-yellow-400',
  ready_for_download: 'bg-blue-100 text-blue-800 border-l-4 border-blue-400',
  in_progress: 'bg-indigo-100 text-indigo-800 border-l-4 border-indigo-400',
  completed: 'bg-green-100 text-green-800 border-l-4 border-green-400',
  completed_with_errors: 'bg-orange-100 text-orange-800 border-l-4 border-orange-400',
  failed: 'bg-red-100 text-red-800 border-l-4 border-red-400',
  cancelled: 'bg-gray-100 text-gray-800 border-l-4 border-gray-400',
  paused: 'bg-amber-100 text-amber-800 border-l-4 border-amber-400',
};

/**
 * Book status filter options: '' (= all) followed by every status that has
 * a colour, so adding a status above automatically adds it to the filter.
 */
export const BOOK_STATUS_OPTIONS = ['', ...Object.keys(bookStatusColors)];

/** Badge classes per `chapters.download_status`. */
export const chapterStatusColors = {
  pending: 'bg-gray-100 text-gray-700',
  in_progress: 'bg-indigo-100 text-indigo-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
};

/**
 * `books.book_web_status` values exactly as scraped from the site
 * (Vietnamese data - the strings must match the DB, do not translate).
 */
export const WEB_STATUS = {
  COMPLETED: 'Hoàn thành',   // finished
  ONGOING: 'Còn tiếp',       // still publishing
  PAUSED: 'Tạm Ngưng',       // on hold
  UNVERIFIED: 'Chưa xác minh', // unknown / not verified
};

/** Web-status filter options: '' (= any) + all known values. */
export const WEB_STATUS_OPTIONS = ['', WEB_STATUS.ONGOING, WEB_STATUS.COMPLETED, WEB_STATUS.PAUSED, WEB_STATUS.UNVERIFIED];

/** Web statuses whose books may still get new chapters (Updates page / Continue Extract). */
export const WEB_STATUS_UPDATABLE = [WEB_STATUS.ONGOING, WEB_STATUS.UNVERIFIED];

/**
 * Badge classes per web status. Computed keys (`[WEB_STATUS.X]: ...`) use
 * the constant's value as the object key.
 */
export const webStatusColors = {
  [WEB_STATUS.COMPLETED]: 'bg-green-100 text-green-700',
  [WEB_STATUS.ONGOING]: 'bg-blue-100 text-blue-700',
  [WEB_STATUS.PAUSED]: 'bg-yellow-100 text-yellow-700',
};

/**
 * Badge classes for any web status, falling back to grey for unknown values.
 * @param {string} status
 * @returns {string}
 */
export const webStatusClass = (status) => webStatusColors[status] || 'bg-gray-100 text-gray-700';

/**
 * Is this a translated book (created by the Translate tool) rather than a
 * downloaded one? SQLite stores booleans as 0/1; Number() also accepts "1".
 * @param {{is_translated?: number}|null|undefined} book
 * @returns {boolean}
 */
export const isTranslated = (book) => Number(book?.is_translated) === 1;
