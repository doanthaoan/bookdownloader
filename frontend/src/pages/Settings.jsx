import React, { useState, useEffect } from 'react';
import { settingsApi } from '../api';
import Layout from '../components/Layout';

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
          </p>
          <div className="space-y-3">
            {['domain', 'book_path', 'logs_path'].map(key => {
              const setting = config.db_settings.find(s => s.key === key);
              if (!setting) return null;
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-sm font-medium text-gray-700 w-36 flex-shrink-0">{key}</span>
                  <input
                    className="flex-1 border rounded px-2 py-1.5 text-sm"
                    value={setting.value}
                    onChange={e => handleSettingChange(key, e.target.value)}
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
        </section>

        {/* General Settings Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Application Settings</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {config.db_settings.filter(s => !s.key.startsWith('cookie_') && !['login_url', 'login_domain', 'login_trigger_selector', 'account_username', 'account_password', 'domain', 'book_path', 'logs_path'].includes(s.key)).map(setting => (
              <div key={setting.key} className="flex items-center justify-between p-3 border rounded-md">
                <span className="text-sm text-gray-600 flex-1 mr-2">{setting.description || setting.key}</span>
                <input
                  className="border rounded px-2 py-1 text-sm w-40"
                  value={setting.value}
                  onChange={e => handleSettingChange(setting.key, e.target.value)}
                />
              </div>
            ))}
          </div>
        </section>

      </div>
    </Layout>
  );
};

export default Settings;
