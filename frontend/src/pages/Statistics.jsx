import React, { useState, useEffect, useCallback } from 'react';
import { statsApi, settingsApi } from '../api';
import Layout from '../components/Layout';

const TYPE_LABELS = {
  chapter: 'Chapter request',
  book_page: 'Book page',
  chapter_list: 'Chapter list',
  cover_image: 'Cover image',
  book_added: 'Book added',
  book_download: 'Book download',
  book_extract: 'Book extract',
  translate_api: 'Translate API',
  translate_web: 'Translate web',
};

const SESSION_LABELS = {
  session: 'Session (logged in)',
  non_session: 'Non-session (free)',
};

const LEVEL_STYLES = {
  none: 'bg-gray-300',
  ok: 'bg-green-500',
  warn: 'bg-yellow-500',
  danger: 'bg-red-500',
};

const LEVEL_TEXT = {
  none: 'text-gray-500',
  ok: 'text-green-600',
  warn: 'text-yellow-600',
  danger: 'text-red-600',
};

const todayISO = () => new Date().toISOString().slice(0, 10);
const daysAgoISO = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

const statCard = (label, value, color = 'text-gray-900') => (
  <div className="bg-white rounded-lg shadow p-4 flex flex-col">
    <span className="text-sm text-gray-500">{label}</span>
    <span className={`text-2xl font-bold ${color}`}>{value}</span>
  </div>
);

const ProgressBar = ({ used, limit, level, pct }) => {
  const width = limit > 0 ? Math.min(100, (used * 100) / limit) : 0;
  return (
    <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
      <div
        className={`h-3 rounded-full ${LEVEL_STYLES[level] || 'bg-gray-300'}`}
        style={{ width: `${width}%` }}
      />
    </div>
  );
};

const DailyBars = ({ days }) => {
  const max = Math.max(...days.map((d) => d.total), 1);
  return (
    <div className="flex items-end gap-1 h-32">
      {days.map((d) => (
        <div key={d.day} className="flex-1 flex flex-col items-center justify-end group relative">
          <div className="w-full flex flex-col justify-end" style={{ height: '100%' }}>
            <div
              className="w-full bg-blue-500 rounded-t"
              style={{ height: `${Math.max(3, (d.total / max) * 100)}%` }}
              title={`${d.day}: ${d.total} (${d.success} ok / ${d.failed} failed)`}
            />
          </div>
          <div className="text-[9px] text-gray-400 truncate w-full text-center">{d.day.slice(5)}</div>
        </div>
      ))}
    </div>
  );
};

const Statistics = () => {
  const [filters, setFilters] = useState({
    start: daysAgoISO(6),
    end: todayISO(),
    request_type: '',
    status: '',
    session_type: '',
    domain: '',
  });
  const [summary, setSummary] = useState(null);
  const [meta, setMeta] = useState({ request_types: [], statuses: [], session_types: [], domains: [] });
  const [logs, setLogs] = useState({ logs: [], total: 0, page: 1, per_page: 50, total_pages: 1 });
  const [logPage, setLogPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const [estDays, setEstDays] = useState(7);
  const [estSession, setEstSession] = useState('session');
  const [estimate, setEstimate] = useState(null);
  const [estimating, setEstimating] = useState(false);

  const loadSummary = useCallback(async () => {
    setLoading(true);
    try {
      const params = {
        start: filters.start,
        end: filters.end,
        request_type: filters.request_type || undefined,
        status: filters.status || undefined,
        session_type: filters.session_type || undefined,
        domain: filters.domain || undefined,
      };
      const res = await statsApi.summary(params);
      setSummary(res.data);
    } catch (err) {
      setMessage('Failed to load stats: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  const loadLogs = useCallback(async (page = 1) => {
    try {
      const params = {
        start: filters.start,
        end: filters.end,
        request_type: filters.request_type || undefined,
        status: filters.status || undefined,
        session_type: filters.session_type || undefined,
        domain: filters.domain || undefined,
        page,
        per_page: 50,
      };
      const res = await statsApi.requests(params);
      setLogs(res.data);
    } catch (err) {
      setMessage('Failed to load request log: ' + (err.response?.data?.detail || err.message));
    }
  }, [filters]);

  useEffect(() => {
    statsApi.meta().then((res) => setMeta(res.data)).catch(() => {});
  }, []);

  useEffect(() => {
    loadSummary();
    loadLogs(logPage);
  }, [loadSummary, loadLogs, logPage]);

  const updateFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setLogPage(1);
  };

  const runEstimate = async () => {
    setEstimating(true);
    setMessage('');
    try {
      const res = await statsApi.limitEstimate({ days: estDays, session_type: estSession });
      setEstimate(res.data);
    } catch (err) {
      setMessage('Estimate failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setEstimating(false);
    }
  };

  const applyLimit = async () => {
    if (!estimate) return;
    try {
      await settingsApi.updateSetting(`chapter_limit_${estSession}`, String(estimate.suggested_limit));
      setMessage(`Applied ${estimate.suggested_limit} as the daily chapter limit for ${SESSION_LABELS[estSession] || estSession}.`);
      setEstimate((prev) => ({ ...prev, current_limit: estimate.suggested_limit }));
      loadSummary();
    } catch (err) {
      setMessage('Apply failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const usage = summary?.chapter_usage_today || {};
  const byType = summary?.by_type || {};
  const byStatus = summary?.by_status || {};
  const bySession = summary?.by_session || {};
  const byDay = summary?.by_day || [];

  return (
    <Layout title="Statistics" subtitle="Request history, daily limits, and access-mode usage">
      {message && (
        <div className="mb-4 p-3 bg-blue-50 text-blue-700 rounded border border-blue-200 text-sm">{message}</div>
      )}

      {/* Filters */}
      <section className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 items-end">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">From</label>
            <input type="date" className="border rounded px-2 py-1.5 text-sm w-full" value={filters.start} onChange={(e) => updateFilter('start', e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">To</label>
            <input type="date" className="border rounded px-2 py-1.5 text-sm w-full" value={filters.end} onChange={(e) => updateFilter('end', e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Type</label>
            <select className="border rounded px-2 py-1.5 text-sm w-full" value={filters.request_type} onChange={(e) => updateFilter('request_type', e.target.value)}>
              <option value="">All</option>
              {meta.request_types.map((t) => (
                <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Status</label>
            <select className="border rounded px-2 py-1.5 text-sm w-full" value={filters.status} onChange={(e) => updateFilter('status', e.target.value)}>
              <option value="">All</option>
              {meta.statuses.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Access</label>
            <select className="border rounded px-2 py-1.5 text-sm w-full" value={filters.session_type} onChange={(e) => updateFilter('session_type', e.target.value)}>
              <option value="">All</option>
              {meta.session_types.map((s) => (
                <option key={s} value={s}>{SESSION_LABELS[s] || s}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Domain</label>
            <select className="border rounded px-2 py-1.5 text-sm w-full" value={filters.domain} onChange={(e) => updateFilter('domain', e.target.value)}>
              <option value="">All</option>
              {meta.domains.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button onClick={loadSummary} disabled={loading} className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-1.5 rounded text-sm transition w-full">
              {loading ? '...' : 'Refresh'}
            </button>
          </div>
        </div>
      </section>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {statCard('Total requests', summary?.total ?? '—')}
        {statCard('Success', byStatus.success ?? 0, 'text-green-600')}
        {statCard('Failed', byStatus.failed ?? 0, 'text-red-600')}
        {statCard('Current mode', summary ? (SESSION_LABELS[summary.session_mode] || summary.session_mode) : '—', 'text-indigo-600')}
      </div>

      {/* By type / session breakdown */}
      <div className="grid md:grid-cols-2 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">By type</h3>
          {Object.keys(byType).length === 0 ? (
            <p className="text-sm text-gray-400">No requests in this range.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {Object.entries(byType).map(([t, n]) => (
                <span key={t} className="text-xs bg-blue-50 text-blue-700 rounded-full px-2.5 py-1">
                  {TYPE_LABELS[t] || t}: {n}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">By access type</h3>
          {Object.keys(bySession).length === 0 ? (
            <p className="text-sm text-gray-400">No requests in this range.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {Object.entries(bySession).map(([s, n]) => (
                <span key={s} className="text-xs bg-indigo-50 text-indigo-700 rounded-full px-2.5 py-1">
                  {SESSION_LABELS[s] || s}: {n}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Daily chart */}
      <section className="bg-white rounded-lg shadow p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Daily requests ({filters.start} → {filters.end})</h3>
        {byDay.length === 0 ? (
          <p className="text-sm text-gray-400">No data for this range.</p>
        ) : (
          <DailyBars days={byDay} />
        )}
      </section>

      {/* Chapter limits + estimate */}
      <section className="bg-white rounded-lg shadow p-4 mb-6">
        <h3 className="text-sm font-semibold text-gray-700 mb-1">Chapter-request limits — today</h3>
        <p className="text-xs text-gray-400 mb-3">
          Only chapter downloads count toward the daily limit. Set limits in Settings, or estimate from recent days below.
        </p>
        <div className="grid md:grid-cols-2 gap-4">
          {['session', 'non_session'].map((st) => {
            const u = usage[st];
            if (!u) return null;
            return (
              <div key={st} className="border rounded-md p-3">
                <div className="flex justify-between items-center mb-1">
                  <span className="text-sm font-medium text-gray-700">{SESSION_LABELS[st] || st}</span>
                  {u.limit > 0 ? (
                    <span className={`text-xs font-semibold ${LEVEL_TEXT[u.level]}`}>
                      {u.used} / {u.limit} · {u.remaining} remaining
                    </span>
                  ) : (
                    <span className="text-xs text-gray-400">no limit set</span>
                  )}
                </div>
                <ProgressBar used={u.used} limit={u.limit} level={u.level} pct={u.pct} />
                {u.level === 'danger' && (
                  <p className="text-xs text-red-600 mt-1 font-medium">Near/at the daily limit — switch access mode or stop.</p>
                )}
                {u.level === 'warn' && (
                  <p className="text-xs text-yellow-600 mt-1 font-medium">Getting close to the daily limit.</p>
                )}
              </div>
            );
          })}
        </div>

        {/* Estimator */}
        <div className="mt-5 border-t pt-4">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">Estimate limit from recent days</h4>
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Days to look back</label>
              <input type="number" min="1" className="border rounded px-2 py-1.5 text-sm w-24" value={estDays} onChange={(e) => setEstDays(Math.max(1, Number(e.target.value) || 1))} />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">Access type</label>
              <select className="border rounded px-2 py-1.5 text-sm" value={estSession} onChange={(e) => setEstSession(e.target.value)}>
                {['session', 'non_session'].map((s) => (
                  <option key={s} value={s}>{SESSION_LABELS[s]}</option>
                ))}
              </select>
            </div>
            <button onClick={runEstimate} disabled={estimating} className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-1.5 rounded text-sm transition">
              {estimating ? '...' : 'Calculate'}
            </button>
          </div>

          {estimate && (
            <div className="mt-4 border rounded-md p-3 bg-gray-50">
              <div className="flex flex-wrap items-center gap-4 mb-3">
                <span className="text-sm text-gray-700">
                  Last {estimate.days_requested} days · max daily = <b className="text-indigo-700">{estimate.max_daily}</b>
                </span>
                <span className="text-sm text-gray-500">
                  Current limit: <b>{estimate.current_limit}</b>
                </span>
                <button
                  onClick={applyLimit}
                  disabled={estimate.suggested_limit === estimate.current_limit}
                  className="bg-green-600 hover:bg-green-700 disabled:bg-gray-300 text-white px-4 py-1.5 rounded text-sm transition"
                >
                  Apply max ({estimate.suggested_limit}) as limit
                </button>
              </div>
              {estimate.days.length === 0 ? (
                <p className="text-xs text-gray-400">No chapter requests recorded in the selected window.</p>
              ) : (
                <DailyBars days={estimate.days.map((d) => ({ ...d, total: d.total }))} />
              )}
            </div>
          )}
        </div>
      </section>

      {/* Request log table */}
      <section className="bg-white rounded-lg shadow p-4">
        <div className="flex justify-between items-center mb-3">
          <h3 className="text-sm font-semibold text-gray-700">Request log ({logs.total} entries)</h3>
        </div>
        {logs.logs.length === 0 ? (
          <p className="text-sm text-gray-400">No requests logged yet. Requests are recorded as the downloader, extractor, and translator run.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b">
                    <th className="py-2 pr-3">Time</th>
                    <th className="py-2 pr-3">Type</th>
                    <th className="py-2 pr-3">Status</th>
                    <th className="py-2 pr-3">Access</th>
                    <th className="py-2 pr-3">Book</th>
                    <th className="py-2 pr-3">URL</th>
                    <th className="py-2 pr-3">ms</th>
                    <th className="py-2">Detail / Error</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.logs.map((l) => (
                    <tr key={l.id} className="border-b hover:bg-gray-50">
                      <td className="py-2 pr-3 whitespace-nowrap text-xs text-gray-500">{l.created_at}</td>
                      <td className="py-2 pr-3">{TYPE_LABELS[l.request_type] || l.request_type}</td>
                      <td className="py-2 pr-3">
                        <span className={`text-xs font-semibold ${l.status === 'success' ? 'text-green-600' : 'text-red-600'}`}>{l.status}</span>
                      </td>
                      <td className="py-2 pr-3 text-xs">{SESSION_LABELS[l.session_type] || l.session_type}</td>
                      <td className="py-2 pr-3 text-xs">{l.book_title || `#${l.book_id || ''}`}</td>
                      <td className="py-2 pr-3 text-xs text-gray-500 max-w-[220px] truncate" title={l.url}>{l.url}</td>
                      <td className="py-2 pr-3 text-xs text-gray-500">{l.duration_ms ?? ''}</td>
                      <td className="py-2 text-xs text-gray-500 max-w-[260px] truncate" title={l.detail || l.error}>{l.error || l.detail || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {logs.total_pages > 1 && (
              <div className="flex items-center justify-between mt-3">
                <button
                  onClick={() => setLogPage((p) => Math.max(1, p - 1))}
                  disabled={logs.page <= 1}
                  className="text-sm bg-gray-200 hover:bg-gray-300 disabled:bg-gray-100 disabled:text-gray-400 px-3 py-1 rounded"
                >
                  Prev
                </button>
                <span className="text-xs text-gray-500">Page {logs.page} / {logs.total_pages}</span>
                <button
                  onClick={() => setLogPage((p) => Math.min(logs.total_pages, p + 1))}
                  disabled={logs.page >= logs.total_pages}
                  className="text-sm bg-gray-200 hover:bg-gray-300 disabled:bg-gray-100 disabled:text-gray-400 px-3 py-1 rounded"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </Layout>
  );
};

export default Statistics;