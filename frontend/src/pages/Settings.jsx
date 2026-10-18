import React, { useState, useEffect } from 'react';
import { settingsApi, errMsg } from '../api';
import Layout from '../components/Layout';

/** Built-in User-Agent choices for Selenium. The last dropdown option is always "custom". */
const USER_AGENT_PRESETS = [
  { id: 'chrome_win', label: 'Chrome 120 (Windows)', value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', description: 'Default — best compatibility with TruyenWiki' },
  { id: 'chrome_mac', label: 'Chrome 120 (macOS)', value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', description: 'Chrome on macOS' },
  { id: 'chrome_linux', label: 'Chrome 120 (Linux)', value: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', description: 'Chrome on Linux' },
  { id: 'firefox_win', label: 'Firefox 120 (Windows)', value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0', description: 'Alternative — Firefox on Windows' },
  { id: 'edge_win', label: 'Edge 120 (Windows)', value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0', description: 'Chromium-based Edge on Windows' },
  { id: 'android', label: 'Chrome (Android)', value: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36', description: 'Mobile Chrome — for mobile site views' },
];

/** Setting keys per section. Order = display order. */
const LOGIN_KEYS = ['login_url', 'login_domain', 'login_trigger_selector'];
const SITE_KEYS = ['domain', 'book_path', 'logs_path'];
const DOWNLOAD_KEYS = ['download_delay_min', 'download_delay_max', 'page_load_timeout'];
const TRANSLATE_KEYS = ['translate_source_path', 'translate_api_endpoint', 'translate_site', 'translate_target_lang',
  'translate_click_delay', 'translate_retry_delay', 'translate_max_retries',
  'translate_impersonate', 'translate_browser_ua',
  'translate_cookie_wait', 'translate_cookie_refresh_max'];
const LIMIT_KEYS = ['chapter_limit_session', 'chapter_limit_nonsession'];
/** Extra hint shown under specific Download Settings rows. */
const DOWNLOAD_HINTS = {
  download_delay_min: 'The downloader also adds a fixed 2–4 s pause between chapters.',
  download_delay_max: 'The downloader also adds a fixed 2–4 s pause between chapters.',
};

/**
 * Text input (or textarea) for one DB setting that saves on blur.
 *
 * Why local "draft" state: saving on every keystroke sent one PUT per
 * character, and because the visible value only updated after each request
 * returned, fast typing could drop characters or save out of order. Now the
 * input edits `draft` locally and we save once when focus leaves the field
 * (or Enter is pressed in a single-line input), and only if the value changed.
 *
 * @param {object} props
 * @param {string} props.settingKey - DB settings key
 * @param {string} props.value - last saved value (from the parent's config)
 * @param {(key: string, value: string) => Promise<boolean>} props.onSave - persists; resolves false on failure
 * @param {boolean} [props.multiline] - render a <textarea> instead of an <input>
 * Any other props (className, type, rows, placeholder...) are passed through.
 */
const SettingInput = ({ settingKey, value, onSave, multiline = false, ...rest }) => {
  const saved = value ?? ''; // `??` turns null/undefined into '' (keeps the input controlled)
  const [draft, setDraft] = useState(saved);

  // When the saved value changes from outside (initial load, reload), sync the draft.
  useEffect(() => { setDraft(saved); }, [saved]);

  /** Save if changed; on failure revert the field to the last saved value. */
  const commit = async () => {
    if (draft === saved) return;
    const ok = await onSave(settingKey, draft);
    if (!ok) setDraft(saved);
  };

  // A capitalized variable can be used as a JSX tag name, so one component renders either element.
  const Tag = multiline ? 'textarea' : 'input';
  return (
    <Tag
      {...rest}
      value={draft}
      onChange={e => setDraft(e.target.value)}
      onBlur={commit}
      // Enter in a one-line field blurs it, which triggers onBlur → commit.
      onKeyDown={multiline ? undefined : (e => { if (e.key === 'Enter') e.target.blur(); })}
    />
  );
};

/**
 * User-Agent picker: a preset dropdown (saves immediately) or a custom
 * string (saves on blur, like SettingInput).
 * @param {{currentValue: string, onSave: (value: string) => Promise<boolean>}} props
 */
const UserAgentSelector = ({ currentValue, onSave }) => {
  const matchedPreset = USER_AGENT_PRESETS.find(p => p.value === currentValue);
  const [preset, setPreset] = useState(matchedPreset?.id || 'custom');
  const [customVal, setCustomVal] = useState(matchedPreset ? '' : currentValue);

  // Re-derive the dropdown whenever the saved value changes (e.g. after the settings load).
  useEffect(() => {
    const m = USER_AGENT_PRESETS.find(p => p.value === currentValue);
    if (m) {
      setPreset(m.id);
    } else {
      setPreset('custom');
      setCustomVal(currentValue);
    }
  }, [currentValue]);

  /** Dropdown change: a preset is saved right away; "custom" just reveals the text box. */
  const handlePresetChange = (e) => {
    const id = e.target.value;
    setPreset(id);
    if (id !== 'custom') {
      const p = USER_AGENT_PRESETS.find(x => x.id === id);
      if (p) onSave(p.value);
    }
  };

  /** Custom text box blur: save only when it differs from the stored value. */
  const handleCustomBlur = () => {
    if (customVal !== currentValue) onSave(customVal);
  };

  const selectedData = USER_AGENT_PRESETS.find(p => p.id === preset);

  return (
    <div className="flex flex-col gap-3 p-3 border rounded-md">
      <label className="text-sm font-medium text-gray-700">User Agent</label>
      <select className="border rounded px-2 py-1.5 text-sm" value={preset} onChange={handlePresetChange}>
        {USER_AGENT_PRESETS.map(p => (
          <option key={p.id} value={p.id}>{p.label}</option>
        ))}
        <option value="custom">Custom…</option>
      </select>
      {preset === 'custom' && (
        <input
          className="border rounded px-2 py-1.5 text-sm font-mono w-full"
          value={customVal}
          onChange={e => setCustomVal(e.target.value)}
          onBlur={handleCustomBlur}
          onKeyDown={e => { if (e.key === 'Enter') e.target.blur(); }}
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

/**
 * One labelled setting field built on SettingInput (so it also saves on
 * blur/Enter and can create a key that isn't in the DB yet).
 *
 * Two layouts, matching the page's sections:
 * - 'inline': label on the left (fixed width), input filling the row.
 * - 'card':   bordered box with the label on top and an optional hint below.
 *
 * @param {object} props
 * @param {string} props.settingKey - DB settings key
 * @param {string} [props.label] - text shown as label (defaults to the key)
 * @param {string} [props.type] - input type, e.g. 'number' (ignored when multiline)
 * @param {string} [props.description] - hint shown under the input (card layout)
 * @param {string|undefined} props.value - stored value
 * @param {(key: string, value: string) => Promise<boolean>} props.onSave
 * @param {'inline'|'card'} [props.layout='inline']
 * @param {string} [props.labelWidth='w-48'] - Tailwind width class for inline labels
 * @param {boolean} [props.multiline] - use a textarea
 * Remaining props (min, rows, placeholder...) are passed to the input.
 */
const SettingRow = ({ settingKey, label, type, description, value, onSave, layout = 'inline', labelWidth = 'w-48', multiline = false, ...rest }) => {
  const input = (
    <SettingInput
      settingKey={settingKey}
      value={value}
      onSave={onSave}
      multiline={multiline}
      type={multiline ? undefined : type}
      className={`border rounded px-2 py-1.5 text-sm ${layout === 'card' ? 'w-full' : 'flex-1'} ${multiline ? 'font-mono' : ''}`}
      {...rest}
    />
  );

  if (layout === 'card') {
    return (
      <div className="flex flex-col gap-1.5 p-3 border rounded-md">
        <span className="text-sm font-medium text-gray-700">{label || settingKey}</span>
        {input}
        {description && <p className="text-xs text-gray-400">{description}</p>}
      </div>
    );
  }
  return (
    // items-start keeps the label at the top next to a multi-line textarea.
    <div className={`flex ${multiline ? 'items-start' : 'items-center'} gap-3`}>
      <span className={`text-sm font-medium text-gray-700 ${labelWidth} flex-shrink-0`}>{label || settingKey}</span>
      {input}
    </div>
  );
};

/**
 * Settings page: auto-login, cookies, site paths, download/browser/translate/
 * request settings. Most fields save on blur via SettingRow/SettingInput.
 */
const Settings = () => {
  const [config, setConfig] = useState({ truyenwiki: {}, cookies: {}, cookie_keys: [], db_settings: [] });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [autoLoginForm, setAutoLoginForm] = useState({ username: '', password: '' });
  // Unsaved cookie edits; sent together by "Save All Cookies".
  const [cookieEdits, setCookieEdits] = useState({});
  // Unsaved Site Configuration edits; sent together by "Save Site Config".
  const [siteEdits, setSiteEdits] = useState({});

  // Load once on mount.
  useEffect(() => {
    loadSettings();
  }, []);

  /** Fetch all settings (API call: getSettings; resets config, cookieEdits and siteEdits). */
  const loadSettings = async () => {
    try {
      const res = await settingsApi.getSettings();
      setConfig(res.data);
      setCookieEdits(res.data.cookies || {});
      setSiteEdits({});
    } catch (err) {
      console.error('Failed to load settings', err);
    }
  };

  /**
   * Read a setting's stored value, or undefined if the key is not in the DB yet.
   * @param {string} key
   */
  const getSetting = (key) => config.db_settings.find(s => s.key === key)?.value;

  /**
   * Run auto-login (API call: autoLogin; reloads settings on success).
   * @param {React.FormEvent} e
   */
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
      setMessage('Login failed: ' + errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  /** Update one cookie field locally (functional setState keeps other keys). */
  const handleCookieChange = (key, value) => {
    setCookieEdits(prev => ({ ...prev, [key]: value }));
  };

  /** Save all cookie edits (API call: updateCookies), then reload. */
  const handleSaveCookies = async () => {
    setLoading(true);
    setMessage('');
    try {
      const res = await settingsApi.updateCookies(cookieEdits);
      setMessage(res.data.message);
      loadSettings();
    } catch (err) {
      setMessage('Error saving cookies: ' + errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  /**
   * Persist one DB setting (API call: updateSetting) and mirror it in state.
   * If the key isn't in db_settings yet (new setting not seeded), it is
   * appended so the UI shows the saved value.
   * @param {string} key
   * @param {string} value
   * @returns {Promise<boolean>} true when saved
   */
  const handleSettingChange = async (key, value) => {
    try {
      await settingsApi.updateSetting(key, value);
      setConfig(prev => {
        const exists = prev.db_settings.some(s => s.key === key);
        return {
          ...prev,
          db_settings: exists
            ? prev.db_settings.map(s => s.key === key ? { ...s, value } : s)
            : [...prev.db_settings, { key, value, description: '' }],
        };
      });
      return true;
    } catch (err) {
      alert(`Error updating setting "${key}": ${errMsg(err)}`);
      return false;
    }
  };

  /** Save the Site Configuration block (API call: updateTruyenWiki), then reload. */
  const handleSaveSiteConfig = async () => {
    // Unedited fields fall back to the stored value.
    const val = (key) => siteEdits[key] ?? getSetting(key) ?? '';
    try {
      await settingsApi.updateTruyenWiki({
        domain: val('domain'),
        book_path: val('book_path'),
        logs_path: val('logs_path'),
      });
      setMessage('Site configuration saved.');
      loadSettings();
    } catch (err) {
      setMessage('Error: ' + errMsg(err));
    }
  };

  /**
   * The DB description of a setting (undefined if none / key missing).
   * @param {string} key
   */
  const dbDescription = (key) => config.db_settings.find(s => s.key === key)?.description;

  /**
   * Label text for a setting row: the DB description, or the key itself.
   * @param {string} key
   */
  const describe = (key) => dbDescription(key) || key;

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
            Changes are saved when you leave a field.
          </p>
          <div className="space-y-3">
            {LOGIN_KEYS.map(key => (
              <SettingRow key={key} settingKey={key} value={getSetting(key)} onSave={handleSettingChange} />
            ))}
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
                  {/* Green/red dot: does this cookie currently have a value? */}
                  <span className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${cookieEdits[key] ? 'bg-green-400' : 'bg-red-400'}`}
                    title={cookieEdits[key] ? 'Has value' : 'Empty'} />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-400 text-sm">No cookie keys configured.</p>
          )}
        </section>

        {/* Site Configuration Section (explicit Save button, edits kept in siteEdits) */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Site Configuration</h2>
          <p className="text-sm text-gray-500 mb-4">
            Set the main domain and file paths. <code>domain</code> is used to derive both book URL and cookie domain.
            After saving, restart the downloader for path changes to take effect on existing sessions.
          </p>
          <div className="space-y-3 mb-4">
            {SITE_KEYS.map(key => (
              <div key={key} className="flex items-center gap-3">
                <span className="text-sm font-medium text-gray-700 w-36 flex-shrink-0">{key}</span>
                <input
                  className="flex-1 border rounded px-2 py-1.5 text-sm"
                  value={siteEdits[key] ?? getSetting(key) ?? ''}
                  onChange={e => setSiteEdits(prev => ({ ...prev, [key]: e.target.value }))}
                />
              </div>
            ))}
            {config.truyenwiki?.book_domain && (
              <div className="text-xs text-gray-400 mt-1 ml-36">
                → book_domain: {config.truyenwiki.book_domain} | cookie_domain: {config.truyenwiki.cookie_domain}
              </div>
            )}
          </div>
          <button
            onClick={handleSaveSiteConfig}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium transition"
          >
            Save Site Config
          </button>
        </section>

        {/* Download Settings Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Download Settings</h2>
          <p className="text-sm text-gray-500 mb-4">
            Configure delays and timeout during chapter downloads.
            Changes are saved when you leave a field.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {DOWNLOAD_KEYS.map(key => (
              <SettingRow key={key} layout="card" settingKey={key}
                label={describe(key)} description={DOWNLOAD_HINTS[key]}
                value={getSetting(key)} onSave={handleSettingChange} />
            ))}
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
            currentValue={getSetting('user_agent') || ''}
            onSave={(val) => handleSettingChange('user_agent', val)}
          />
        </section>

        {/* Translation Settings Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Translation Settings</h2>
          <p className="text-sm text-gray-500 mb-4">
            Configure the dichtienghoa translation tool. If the API is blocked by Cloudflare,
            paste a fresh <code>cf_clearance</code> cookie (from your browser's DevTools) as
            <code> translate_cookies</code> JSON, e.g. <code>{'{"cf_clearance": "..."}'}</code>.
            <code> translate_click_delay</code> = seconds to wait before clicking the translate
            button; <code> translate_retry_delay</code> = seconds to wait before retrying the click
            when the result textarea stays empty; <code> translate_max_retries</code> = max click
            retries (keeps you from hammering the translation server). For the API method:
            <code> translate_browser_ua</code> = your real browser User-Agent (from DevTools → Network),
            <code> translate_impersonate</code> = curl_cffi target matching your Chrome version
            (e.g. <code>chrome131</code>). <code> translate_cookie_wait</code> = seconds to wait in a
            real Chrome for a fresh <code>cf_clearance</code> during auto refresh;
            <code> translate_cookie_refresh_max</code> = max auto refreshes per request (prevents
            blocking). When the refresh limit is reached, use the book's <code>Refresh Cookie</code>
            or <code>Continue</code> button. Changes are saved when you leave a field.
          </p>
          <div className="space-y-3">
            {TRANSLATE_KEYS.map(key => (
              <SettingRow key={key} labelWidth="w-52" settingKey={key}
                value={getSetting(key)} onSave={handleSettingChange} />
            ))}
            <SettingRow
              labelWidth="w-52"
              multiline
              rows={2}
              settingKey="translate_cookies"
              value={getSetting('translate_cookies') || '{}'}
              onSave={handleSettingChange}
              placeholder='{"cf_clearance": "..."}'
            />
          </div>
        </section>

        {/* Request Settings Section */}
        <section className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold border-b pb-3 mb-4">Request Settings</h2>
          <p className="text-sm text-gray-500 mb-4">
            Choose how chapter downloads access the site. <b>Session</b> injects your login
            cookies; <b>Non-session</b> downloads as a free/guest visitor (no cookies). The
            site keeps separate daily request quotas per access type, so you can mix both to
            get more chapter requests per day. The daily limits below power the alert colors
            and "remaining today" counter on the Statistics page (0 = no limit configured).
            Use the estimator on the Statistics page to derive limits from your own history.
            The mode saves immediately; limits save when you leave the field.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="flex flex-col gap-1.5 p-3 border rounded-md">
              <span className="text-sm font-medium text-gray-700">request_session_mode</span>
              {/* A select change is one discrete event, so saving on change is fine here. */}
              <select
                className="border rounded px-2 py-1.5 text-sm w-full"
                value={getSetting('request_session_mode') || 'session'}
                onChange={e => handleSettingChange('request_session_mode', e.target.value)}
              >
                <option value="session">session (logged-in cookies)</option>
                <option value="non_session">non_session (free, no cookies)</option>
              </select>
              <p className="text-xs text-gray-400">Applies to chapter downloads (and the resulting DOCX exports).</p>
            </div>
            {LIMIT_KEYS.map(key => (
              <SettingRow key={key} layout="card" settingKey={key} type="number" min="0"
                description={dbDescription(key)}
                value={getSetting(key)} onSave={handleSettingChange} />
            ))}
          </div>
        </section>

      </div>
    </Layout>
  );
};

export default Settings;
