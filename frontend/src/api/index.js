import axios from 'axios';

const BASE_URL = 'http://127.0.0.1:8000';
const api = axios.create({
  baseURL: `${BASE_URL}/api`,
});

export const bookApi = {
  getAll: (params) => api.get('/books', { params }),
  getOne: (id) => api.get(`/books/${id}`),
  extract: (title, url) => api.post('/books/extract', null, { params: { book_title: title, book_url: url } }),
  getChapters: (id) => api.get(`/books/${id}/chapters`),
  download: (id, params = {}) => api.post(`/books/${id}/download`, null, { params }),
  cancelDownload: (id) => api.post(`/books/${id}/cancel-download`),
  getProgress: (id) => api.get(`/books/${id}/progress`),
  delete: (id) => api.delete(`/books/${id}`),
  redownload: (id, allChapters = false) => api.post(`/books/${id}/redownload`, null, { params: { all_chapters: allChapters } }),
  downloadChapter: (bookId, chapterId) => api.post(`/books/${bookId}/chapters/${chapterId}/download`),
  docxInfo: (id) => api.get(`/books/${id}/docx-info`),
  redownloadDocxInfo: (id) => api.get(`/books/${id}/redownload-docx-info`),
  exportCorrected: (id, chapterIds = []) => api.post(`/books/${id}/export-corrected`, chapterIds),
  exportCorrectedDocxInfo: (id) => api.get(`/books/${id}/export-corrected-docx-info`),
  exportCorrectedDocxUrl: (id) => `${BASE_URL}/api/books/${id}/export-corrected-docx`,
  previewCorrection: (id, chapterId) => api.post(`/books/${id}/preview-correction`, null, { params: { chapter_id: chapterId } }),
  toggleFavorite: (id) => api.post(`/books/${id}/toggle-favorite`),
  toggleSent: (id) => api.post(`/books/${id}/toggle-sent`),
  coverUrl: (id) => `${BASE_URL}/api/books/${id}/cover`,
  docxUrl: (id) => `${BASE_URL}/api/books/${id}/docx`,
  redownloadDocxUrl: (id) => `${BASE_URL}/api/books/${id}/redownload-docx`,
  checkUpdates: () => api.get('/books/updates/check'),
  refreshInfo: (id) => api.post(`/books/${id}/refresh-info`),
  continueExtract: (id) => api.post(`/books/${id}/continue-extract`),
  updateFull: (id, params = {}) => api.post(`/books/${id}/update-full`, null, { params }),
  bookTags: (id) => api.get(`/books/${id}/tags`),
  updateBookTags: (id, tags) => api.put(`/books/${id}/tags`, tags),
  allTags: () => api.get('/books/tags'),
  updateInfo: (id, data) => api.put(`/books/${id}`, data),
  uploadCover: (id, file) => {
    const form = new FormData();
    form.append('file', file);
    return api.post(`/books/${id}/cover`, form);
  },
};

export const settingsApi = {
  getSettings: () => api.get('/settings'),
  getCookies: () => api.get('/settings/cookies'),
  updateCookie: (name, value) => api.put('/settings/update-cookie', null, { params: { cookie_name: name, cookie_value: value } }),
  updateCookies: (cookies) => api.put('/settings/cookies', cookies),
  updateSetting: (key, value) => api.put('/settings/update-setting', null, { params: { key, value } }),
  updateTruyenWiki: (config) => api.put('/settings/update-truyenwiki', null, { params: config }),
  updateLoginConfig: (config) => api.put('/settings/login-config', null, { params: config }),
  autoLogin: (username, password) => api.post('/settings/auto-login', null, { params: { username, password } }),
};

export const logsApi = {
  list: (search) => api.get('/logs', { params: { search } }),
  read: (filename, lines = 200, offset = 0) => api.get(`/logs/${encodeURIComponent(filename)}`, { params: { lines, offset } }),
};

export const textCleaningApi = {
  list: () => api.get('/text-cleaning'),
  add: (params) => api.post('/text-cleaning', null, { params }),
  update: (id, params) => api.put(`/text-cleaning/${id}`, null, { params }),
  reorder: (id, newOrder) => api.put(`/text-cleaning/${id}/reorder`, null, { params: { new_order: newOrder } }),
  delete: (id) => api.delete(`/text-cleaning/${id}`),
  test: (chapterUrl) => api.post('/text-cleaning/test', null, { params: { chapter_url: chapterUrl } }),
};

export const statsApi = {
  meta: () => api.get('/stats/meta'),
  summary: (params) => api.get('/stats/summary', { params }),
  requests: (params) => api.get('/stats/requests', { params }),
  daily: (params) => api.get('/stats/daily', { params }),
  limitEstimate: (params) => api.get('/stats/limit-estimate', { params }),
};

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
  getBook: (id) => api.get(`/translate/books/${id}`),
  corrections: (id) => api.get(`/translate/books/${id}/corrections`),
  updateCorrections: (id, corrections) => api.put(`/translate/books/${id}/corrections`, { corrections }),
  run: (id, method = 'api', maxChapters = null) => api.post(`/translate/books/${id}/run`, null, { params: { method, max_chapters: maxChapters } }),
  retranslate: (id, method = 'api') => api.post(`/translate/books/${id}/retranslate`, null, { params: { method } }),
  continueRun: (id, method = 'api') => api.post(`/translate/books/${id}/continue`, null, { params: { method } }),
  refreshCookies: () => api.post('/translate/refresh-cookies'),
  retranslateDocxInfo: (id) => api.get(`/translate/books/${id}/retranslate-docx-info`),
  retranslateDocxUrl: (id) => `${api.defaults.baseURL}/translate/books/${id}/retranslate-docx`,
  progress: (id) => api.get(`/translate/books/${id}/progress`),
  cancel: (id) => api.post(`/translate/books/${id}/cancel`),
};

export default api;
