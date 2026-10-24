/**
 * API layer: every backend call the pages make goes through this file.
 * Pages never import axios directly, so changing the server address or
 * an endpoint path only needs an edit here.
 */
import axios from 'axios';

/**
 * Backend origin (scheme + host + port). Exported so pages can turn
 * server-relative paths (e.g. "/api/text-cleaning/test/x.docx") into
 * absolute links without repeating the URL string.
 * TODO: read from an env var (import.meta.env.VITE_API_ORIGIN) if the port ever needs to change per machine.
 */
export const API_ORIGIN = 'http://127.0.0.1:8000';

// One shared axios instance; every request path below is relative to /api.
const api = axios.create({
  baseURL: `${API_ORIGIN}/api`,
});

/**
 * Turn an axios error into a human-readable message.
 * FastAPI puts its error text in `response.data.detail` (e.g. the 409
 * "already running" message), so prefer that over axios' generic text.
 * Optional chaining (`?.`) returns undefined instead of throwing when a
 * level is missing (network errors have no `response`).
 * @param {any} err - error thrown by an axios call
 * @returns {string}
 */
export const errMsg = (err) => err?.response?.data?.detail || err?.message || String(err);

/**
 * Book (downloaded or translated) endpoints. Functions return the axios
 * promise; callers read `.data`. Functions named `*Url` return a plain
 * string for <a href>/<img src> instead of making a request.
 */
export const bookApi = {
  getAll: (params) => api.get('/books', { params }),
  getOne: (id) => api.get(`/books/${id}`),
  extract: (title, url) => api.post('/books/extract', null, { params: { book_title: title, book_url: url } }),
  getChapters: (id) => api.get(`/books/${id}/chapters`),
  download: (id, params = {}) => api.post(`/books/${id}/download`, null, { params }),
  cancelDownload: (id) => api.post(`/books/${id}/cancel-download`),
  getProgress: (id) => api.get(`/books/${id}/progress`),
  delete: (id) => api.delete(`/books/${id}`),
  redownload: (id, params = {}) => api.post(`/books/${id}/redownload`, null, { params }),
  downloadChapter: (bookId, chapterId) => api.post(`/books/${bookId}/chapters/${chapterId}/download`),
  // Body is a JSON array of chapter ids; an empty array means "whole book".
  exportCorrected: (id, chapterIds = []) => api.post(`/books/${id}/export-corrected`, chapterIds),
  exportCorrectedDocxInfo: (id) => api.get(`/books/${id}/export-corrected-docx-info`),
  exportCorrectedDocxUrl: (id) => `${API_ORIGIN}/api/books/${id}/export-corrected-docx`,
  previewCorrection: (id, chapterId) => api.post(`/books/${id}/preview-correction`, null, { params: { chapter_id: chapterId } }),
  toggleFavorite: (id) => api.post(`/books/${id}/toggle-favorite`),
  toggleSent: (id) => api.post(`/books/${id}/toggle-sent`),
  coverUrl: (id) => `${API_ORIGIN}/api/books/${id}/cover`,
  checkUpdates: () => api.get('/books/updates/check'),
  refreshInfo: (id) => api.post(`/books/${id}/refresh-info`),
  continueExtract: (id) => api.post(`/books/${id}/continue-extract`),
  updateFull: (id, params = {}) => api.post(`/books/${id}/update-full`, null, { params }),
  bookTags: (id) => api.get(`/books/${id}/tags`),
  updateBookTags: (id, tags) => api.put(`/books/${id}/tags`, tags),
  allTags: () => api.get('/books/tags'),
  updateInfo: (id, data) => api.put(`/books/${id}`, data),
  /** Upload a cover image as multipart/form-data (FormData sets the header for us). */
  uploadCover: (id, file) => {
    const form = new FormData();
    form.append('file', file);
    return api.post(`/books/${id}/cover`, form);
  },
};

/** Settings endpoints (cookies, DB key/value settings, auto-login). */
export const settingsApi = {
  getSettings: () => api.get('/settings'),
  updateCookies: (cookies) => api.put('/settings/cookies', cookies),
  updateSetting: (key, value) => api.put('/settings/update-setting', null, { params: { key, value } }),
  updateTruyenWiki: (config) => api.put('/settings/update-truyenwiki', null, { params: config }),
  autoLogin: (username, password) => api.post('/settings/auto-login', null, { params: { username, password } }),
  // Extra site accounts (fallbacks when the access limit is reached). Credentials go in the JSON body.
  listAccounts: () => api.get('/settings/accounts'),
  addAccount: (username, password) => api.post('/settings/accounts', { username, password }),
  deleteAccount: (id) => api.delete(`/settings/accounts/${id}`),
  loginAccount: (id) => api.post(`/settings/accounts/${id}/login`),
};

/** Log file listing / reading. */
export const logsApi = {
  list: (search) => api.get('/logs', { params: { search } }),
  // encodeURIComponent keeps file names with spaces/special chars URL-safe.
  read: (filename, lines = 200, offset = 0) => api.get(`/logs/${encodeURIComponent(filename)}`, { params: { lines, offset } }),
};

/** Global text-cleaning (regex/simple) rules. */
export const textCleaningApi = {
  list: () => api.get('/text-cleaning'),
  add: (params) => api.post('/text-cleaning', null, { params }),
  update: (id, params) => api.put(`/text-cleaning/${id}`, null, { params }),
  reorder: (id, newOrder) => api.put(`/text-cleaning/${id}/reorder`, null, { params: { new_order: newOrder } }),
  delete: (id) => api.delete(`/text-cleaning/${id}`),
  test: (chapterUrl) => api.post('/text-cleaning/test', null, { params: { chapter_url: chapterUrl } }),
};

/** Request statistics. */
export const statsApi = {
  meta: () => api.get('/stats/meta'),
  summary: (params) => api.get('/stats/summary', { params }),
  requests: (params) => api.get('/stats/requests', { params }),
  limitEstimate: (params) => api.get('/stats/limit-estimate', { params }),
};

/**
 * Translate tool endpoints. run/retranslate/continue return HTTP 409 when a
 * job is already active for the book; show the message with errMsg(err).
 */
export const translateApi = {
  prepare: () => api.get('/translate/prepare'),
  check: () => api.get('/translate/check'),
  sourceFiles: () => api.get('/translate/source-files'),
  upload: (file) => {
    const form = new FormData();
    form.append('file', file);
    return api.post('/translate/upload', form);
  },
  deleteFile: (filename) => api.delete(`/translate/source-files/${encodeURIComponent(filename)}`),
  parse: (filename) => api.post('/translate/parse', null, { params: { filename } }),
  translateText: (text, method = 'api') => api.post('/translate/text', { text, method }),
  createBook: (filename, title, author) => api.post('/translate/books', { filename, title, author }),
  corrections: (id) => api.get(`/translate/books/${id}/corrections`),
  updateCorrections: (id, corrections) => api.put(`/translate/books/${id}/corrections`, { corrections }),
  copyCorrections: (id, sourceBookId) => api.post(`/translate/books/${id}/corrections/copy`, { source_book_id: sourceBookId }),
  run: (id, method = 'api', maxChapters = null) => api.post(`/translate/books/${id}/run`, null, { params: { method, max_chapters: maxChapters } }),
  retranslate: (id, method = 'api') => api.post(`/translate/books/${id}/retranslate`, null, { params: { method } }),
  continueRun: (id, method = 'api') => api.post(`/translate/books/${id}/continue`, null, { params: { method } }),
  refreshCookies: () => api.post('/translate/refresh-cookies'),
  progress: (id) => api.get(`/translate/books/${id}/progress`),
  cancel: (id) => api.post(`/translate/books/${id}/cancel`),
};

export default api;
