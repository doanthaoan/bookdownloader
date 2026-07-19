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
  download: (id) => api.post(`/books/${id}/download`),
  cancelDownload: (id) => api.post(`/books/${id}/cancel-download`),
  getProgress: (id) => api.get(`/books/${id}/progress`),
  delete: (id) => api.delete(`/books/${id}`),
  redownload: (id, allChapters = false) => api.post(`/books/${id}/redownload`, null, { params: { all_chapters: allChapters } }),
  downloadChapter: (bookId, chapterId) => api.post(`/books/${bookId}/chapters/${chapterId}/download`),
  docxInfo: (id) => api.get(`/books/${id}/docx-info`),
  redownloadDocxInfo: (id) => api.get(`/books/${id}/redownload-docx-info`),
  docxUrl: (id) => `${BASE_URL}/api/books/${id}/docx`,
  redownloadDocxUrl: (id) => `${BASE_URL}/api/books/${id}/redownload-docx`,
  checkUpdates: () => api.get('/books/updates/check'),
  continueExtract: (id) => api.post(`/books/${id}/continue-extract`),
  updateFull: (id) => api.post(`/books/${id}/update-full`),
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

export default api;
