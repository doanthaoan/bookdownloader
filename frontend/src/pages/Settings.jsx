import React, { useState, useEffect } from 'react';
import { settingsApi } from '../api';
import Layout from '../components/Layout';

const USER_AGENT_PRESETS = [
  { id: 'chrome_win', label: 'Chrome 120 (Windows)', value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', description: 'Default — best compatibility with TruyenWiki' },
  { id: 'chrome_mac', label: 'Chrome 120 (macOS)', value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', description: 'Chrome on macOS' },
  { id: 'chrome_linux', label: 'Chrome 120 (Linux)', value: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', description: 'Chrome on Linux' },
  { id: 'firefox_win', label: 'Firefox 120 (Windows)', value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0', description: 'Alternative — Firefox on Windows' },
  { id: 'edge_win', label: 'Edge 120 (Windows)', value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0', description: 'Chromium-based Edge on Windows' },
  { id: 'android', label: 'Chrome (Android)', value: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36', description: 'Mobile Chrome — for mobile site views' },
];

const UserAgentSelector = ({ currentValue, onSave }) => {
  const matchedPreset = USER_AGENT_PRESETS.find(p => p.value === currentValue);
  const [preset, setPreset] = useState(matchedPreset?.id || 'custom');
  const [customVal, setCustomVal] = useState(matchedPreset ? '' : currentValue);

  useEffect(() => {
    const m = USER_AGENT_PRESETS.find(p => p.value === currentValue);
    if (m) {
      setPreset(m.id);
    } else {
      setPreset('custom');
      setCustomVal(currentValue);
    }
  }, [currentValue]);

  const handlePresetChange = (e) => {
    const id = e.target.value;
    setPreset(id);
    if (id !== 'custom') {
      const p = USER_AGENT_PRESETS.find(x => x.id === id);
      if (p) onSave(p.value);
    }
  };

  const handleCustomChange = (e) => {
    setCustomVal(e.target.value);
    onSave(e.target.value);
  };

  const selectedData = USER_AGENT_PRESETS.find(p => p.id === preset);

  return (
    <div className="flex flex-col gap-3 p-3 border rounded-md">
      <label className="text-sm font-medium text-gray-700">User Agent</label>
      <select className="border rounded px-2 py-1.5 text-sm" value={preset} onChange={handlePresetChange}>
        {USER_AGENT_PRESETS.map(p => (
          <option key={p.id} value={p.id}>{p.label}</option>
        ))}
      </select>
      {preset === 'custom' && (
        <input
          className="border rounded px-2 py-1.5 text-sm font-mono w-full"
          value={customVal}
          onChange={handleCustomChange}
          placeholder="Enter custom user agent string..."
        />
      )}
      {selectedData?.description && (
        <p className="text-xs text-gray-400 italic">{selectedData.description}</p>
      )}
      {!selectedData && (
        <p className="text-xs text-gray-400 italic">Custom user agent — enter any valid string</p>
      )}
    </div>
  );
};

const Settings = () => {
  const [config, setConfig] = useState({ truyenwiki: {}, cookies: {}, cookie_keys: [], db_settings: [] });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [autoLoginForm, setAutoLoginForm] = useState({ username: '', password: '' });
  const [cookieEdits, setCookieEdits] = useState({});

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const res = await settingsApi.getSettings();
      setConfig(res.data);
      setCookieEdits(res.data.cookies);
    } catch (err) {
      console.error('Failed to load settings', err);
    }
  };

  const handleAutoLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage('');
    try {
      const res = await settingsApi.autoLogin(autoLoginForm.username, autoLoginForm.password);
      setMessage(res.data.message);
      if (res.data.success) {
        loadSettings();
      }
    } catch (err) {
      setMessage('Login failed: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCookieChange = (key, value) => {
    setCookieEdits(prev => ({ ...prev, [key]: value }));
  };

  const handleSaveCookies = async () => {
    setLoading(true);
    setMessage('');
    try {
      const res = await settingsApi.updateCookies(cookieEdits);
      setMessage(res.data.message);
      loadSettings();
    } catch (err) {
      setMessage('Error saving cookies: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSettingChange = async (key, value) => {
    try {
      await settingsApi.updateSetting(key, value);
      setConfig(prev => ({
        ...prev,
        db_settings: prev.db_settings.map(s => s.key === key ? { ...s, value } : s)
      }));
    } catch (err) {
      alert('Error updating setting');
    }
  };

  return (
    <Layout title="Settings" subtitle="Manage cookies, auto-login, and application configuration">
      <div className="space-y-6">

        {/* Auto-Login Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Auto-Login</h2>
          <p className="text-sm text-gray-500 mb-4">
            Enter your credentials to automatically log in and extract all cookies.
            This launches a headless browser to perform the login.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 items-end">
            <div className="flex-1 w-full">
              <label className="block text-sm font-medium text-gray-700 mb-1">Username / Email</label>
              <input
                type="text"
                className="w-full p-2 border rounded-md"
                value={autoLoginForm.username}
                onChange={e => setAutoLoginForm({ ...autoLoginForm, username: e.target.value })}
              />
            </div>
            <div className="flex-1 w-full">
              <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
              <input
                type="password"
                className="w-full p-2 border rounded-md"
                value={autoLoginForm.password}
                onChange={e => setAutoLoginForm({ ...autoLoginForm, password: e.target.value })}
              />
            </div>
            <button
              onClick={handleAutoLogin}
              disabled={loading || !autoLoginForm.username || !autoLoginForm.password}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 text-white px-5 py-2 rounded-md transition w-full sm:w-auto"
            >
              {loading ? 'Processing...' : 'Auto-Login'}
            </button>
          </div>
          {message && (
            <div className="mt-3 p-3 bg-blue-50 text-blue-700 rounded border border-blue-200 text-sm">{message}</div>
          )}
        </section>

        {/* Login Configuration Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Login Configuration</h2>
          <p className="text-sm text-gray-500 mb-4">
            Configure how the auto-login works. The login trigger is clicked on the homepage to open the login form.
          </p>
          <div className="space-y-3">
            {['login_url', 'login_domain', 'login_trigger_selector'].map(key => {
              const setting = config.db_settings.find(s => s.key === key);
              if (!setting) return null;
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-sm font-medium text-gray-700 w-48 flex-shrink-0">{key}</span>
                  <input
                    className="flex-1 border rounded px-2 py-1.5 text-sm"
                    value={setting.value}
                    onChange={e => handleSettingChange(key, e.target.value)}
                  />
                </div>
              );
            })}
          </div>
        </section>

        {/* Cookie Manager Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <div className="flex justify-between items-center border-b pb-3 mb-4">
            <h2 className="text-lg font-semibold">Cookies</h2>
            <button
              onClick={handleSaveCookies}
              disabled={loading}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white px-4 py-1.5 rounded text-sm transition"
            >
              Save All Cookies
            </button>
          </div>
          <p className="text-sm text-gray-500 mb-4">
            Edit cookie values directly. Changes are saved to the database and used by the extractor/downloader.
          </p>
          {config.cookie_keys && config.cookie_keys.length > 0 ? (
            <div className="space-y-2">
              {config.cookie_keys.map(key => (
                <div key={key} className="flex items-center gap-3 p-2 border rounded-md hover:bg-gray-50">
                  <span className="text-sm font-medium text-gray-700 w-48 flex-shrink-0">{key}</span>
                  <input
                    type="text"
                    className="flex-1 p-1.5 border rounded text-sm font-mono"
                    value={cookieEdits[key] || ''}
                    onChange={e => handleCookieChange(key, e.target.value)}
                    placeholder="(empty)"
                  />
                  <span className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${cookieEdits[key] ? 'bg-green-400' : 'bg-red-400'}`}
                    title={cookieEdits[key] ? 'Has value' : 'Empty'} />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-400 text-sm">No cookie keys configured.</p>
          )}
        </section>

        {/* Site Configuration Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Site Configuration</h2>
          <p className="text-sm text-gray-500 mb-4">
            Set the main domain and file paths. <code>domain</code> is used to derive both book URL and cookie domain.
            After saving, restart the downloader for path changes to take effect on existing sessions.
          </p>
          <div className="space-y-3 mb-4">
            {['domain', 'book_path', 'logs_path'].map(key => {
              const setting = config.db_settings.find(s => s.key === key);
              if (!setting) return null;
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-sm font-medium text-gray-700 w-36 flex-shrink-0">{key}</span>
                  <input
                    className="flex-1 border rounded px-2 py-1.5 text-sm"
                    value={setting.value}
                    onChange={e => {
                      setConfig(prev => ({
                        ...prev,
                        db_settings: prev.db_settings.map(s => s.key === key ? { ...s, value: e.target.value } : s)
                      }));
                    }}
                  />
                </div>
              );
            })}
            {config.truyenwiki.book_domain && (
              <div className="text-xs text-gray-400 mt-1 ml-36">
                → book_domain: {config.truyenwiki.book_domain} | cookie_domain: {config.truyenwiki.cookie_domain}
              </div>
            )}
          </div>
          <button
            onClick={async () => {
              const getVal = (key) => (config.db_settings.find(s => s.key === key) || {}).value;
              try {
                await settingsApi.updateTruyenWiki({
                  domain: getVal('domain'),
                  book_path: getVal('book_path'),
                  logs_path: getVal('logs_path'),
                });
                setMessage('Site configuration saved.');
                loadSettings();
              } catch (err) {
                setMessage('Error: ' + err.message);
              }
            }}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium transition"
          >
            Save Site Config
          </button>
        </section>

        {/* Download Settings Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Download Settings</h2>
          <p className="text-sm text-gray-500 mb-4">
            Configure delays, timeout, and save behavior during chapter downloads.
            All changes are saved immediately.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {['download_delay_min', 'download_delay_max', 'save_interval', 'page_load_timeout'].map(key => {
              const setting = config.db_settings.find(s => s.key === key);
              if (!setting) return null;
              return (
                <div key={key} className="flex flex-col gap-1.5 p-3 border rounded-md">
                  <span className="text-sm font-medium text-gray-700">{setting.description || key}</span>
                  <input
                    className="border rounded px-2 py-1.5 text-sm w-full"
                    value={setting.value}
                    onChange={e => handleSettingChange(key, e.target.value)}
                  />
                </div>
              );
            })}
          </div>
        </section>

        {/* Browser Settings Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Browser Settings</h2>
          <p className="text-sm text-gray-500 mb-4">
            Configure the User Agent string used by Selenium for all browser sessions
            (downloads, chapter extraction, auto-login, and text cleaning tests).
          </p>
          <UserAgentSelector
            currentValue={(config.db_settings.find(s => s.key === 'user_agent') || {}).value || ''}
            onSave={(val) => handleSettingChange('user_agent', val)}
          />
        </section>

      </div>
    </Layout>
  );
};

export default Settings;
