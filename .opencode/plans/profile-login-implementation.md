# Profile Login Implementation Plan

## Goal
Allow login via Google Account by launching visible Chrome with the user's existing profile (where Google is already logged in). Cookies are auto-extracted once login completes, with a manual stop button as fallback.

---

## 1. DB Schema — Add Chrome Profile Settings

**File:** `backend/data/database_schema.sql`

Add after the `logs_path` seed line:

```sql
('chrome_profile_path', '', 'Path to Chrome user data directory for profile-based login'),
('profile_directory', 'Default', 'Chrome profile folder name (e.g., Default, Profile 1)');
```

---

## 2. Backend: `login.py` — Add Profile Login

**File:** `backend/app/services/login.py`

Add a new `ProfileLoginManager` (global, similar to `_active_downloads`) and add `profile_login()` method to `AutoLogin`.

### New global state
```python
_active_profile_logins = {}

def register_profile_login(session_id: str, driver, cancel_flag):
    _active_profile_logins[session_id] = (driver, cancel_flag)

def unregister_profile_login(session_id: str):
    _active_profile_logins.pop(session_id, None)

def stop_profile_login(session_id: str):
    entry = _active_profile_logins.get(session_id)
    if entry:
        entry[1][0] = True  # set cancel flag
        return True
    return False
```

### New method on AutoLogin
```python
def profile_login(self, session_id: str) -> dict:
    """Launch visible Chrome with user profile for interactive Google login."""
    import platform, os, threading, time
    
    chrome_profile_path = self.db.get_setting('chrome_profile_path', '')
    profile_directory = self.db.get_setting('profile_directory', 'Default')
    
    if not chrome_profile_path or not os.path.exists(chrome_profile_path):
        return {"success": False, "message": f"Chrome profile path not found: {chrome_profile_path}. Set it in Settings."}
    
    chrome_options = Options()
    chrome_options.add_argument(f"--user-data-dir={chrome_profile_path}")
    chrome_options.add_argument(f"--profile-directory={profile_directory}")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # NOT headless
    # NOT disabling automation features — looks more like normal Chrome
    
    self.driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
    
    cancel_flag = [False]
    register_profile_login(session_id, self.driver, cancel_flag)
    
    try:
        self.driver.get(TRUYENWIKI['book_domain'])
        
        # Poll for cookies with a check every 2 seconds
        extracted = {}
        poll_count = 0
        max_polls = 300  # 10 minutes max
        
        while poll_count < max_polls and not cancel_flag[0]:
            time.sleep(2)
            poll_count += 1
            
            # Re-read target domain cookies
            all_cookies = self.driver.get_cookies()
            current = {}
            for c in all_cookies:
                if c['name'] in COOKIE_KEYS:
                    current[c['name']] = c['value']
            
            # Check if we got all cookie keys filled (or most of them)
            if current and len(current) >= len(COOKIE_KEYS) * 0.5:
                # Also navigate to book domain to get domain-specific cookies
                self.driver.get(TRUYENWIKI['book_domain'])
                time.sleep(3)
                for c in self.driver.get_cookies():
                    if c['name'] in COOKIE_KEYS and c['name'] not in current:
                        current[c['name']] = c['value']
                extracted = current
                break
        
        if cancel_flag[0]:
            # User clicked Stop — extract whatever cookies exist
            all_cookies = self.driver.get_cookies()
            for c in all_cookies:
                if c['name'] in COOKIE_KEYS and c['name'] not in extracted:
                    extracted[c['name']] = c['value']
        
        if extracted:
            self._save_cookies(extracted)
            return {
                "success": True,
                "extracted": list(extracted.keys()),
                "message": f"Extracted {len(extracted)} cookies: {', '.join(extracted.keys())}"
            }
        else:
            return {
                "success": False,
                "message": "No target cookies found. Login might not have completed."
            }
    
    except Exception as e:
        return {"success": False, "message": f"Profile login error: {str(e)}"}
    finally:
        if self.driver:
            self.driver.quit()
            self.driver = None
        unregister_profile_login(session_id)
```

### New convenience function
```python
def start_profile_login(session_id: str) -> dict:
    """Start a profile login in a background thread."""
    service = AutoLogin()
    return service.profile_login(session_id)
```

---

## 3. Backend: `settings.py` — New Endpoints

**File:** `backend/app/api/settings.py`

Add imports:
```python
import uuid
import threading
from fastapi import BackgroundTasks
from app.services.login import start_profile_login, stop_profile_login
```

Add global active sessions dict and endpoints:

```python
_active_login_sessions = {}

@router.post("/profile-login/start")
async def start_profile_login_api():
    """Launch visible Chrome with user profile for interactive login."""
    session_id = str(uuid.uuid4())
    
    def run_login(sid):
        result = start_profile_login(sid)
        _active_login_sessions[sid] = result
    
    thread = threading.Thread(target=run_login, args=(session_id,), daemon=True)
    thread.start()
    
    _active_login_sessions[session_id] = {"status": "starting", "result": None}
    
    return {
        "session_id": session_id,
        "message": "Browser opening. Complete Google login in the window."
    }


@router.get("/profile-login/status/{session_id}")
async def profile_login_status(session_id: str):
    """Poll login status — used by frontend to check progress."""
    entry = _active_login_sessions.get(session_id)
    if not entry:
        return {"status": "unknown", "message": "Session not found or expired."}
    
    if isinstance(entry, dict) and entry.get("status") == "starting":
        return {"status": "waiting", "message": "Browser opened — waiting for login..."}
    
    if isinstance(entry, dict) and "success" in entry:
        result = entry
        if result.get("success"):
            return {
                "status": "extracted", 
                "cookies": result.get("extracted", []),
                "message": result.get("message", "Cookies extracted successfully.")
            }
        else:
            return {
                "status": "error",
                "message": result.get("message", "Login failed.")
            }
    
    # entry is the result dict directly
    if entry.get("success"):
        return {
            "status": "extracted",
            "cookies": entry.get("extracted", []),
            "message": entry.get("message", "Cookies extracted successfully.")
        }
    elif "success" in entry:
        return {
            "status": "error",
            "message": entry.get("message", "Login failed.")
        }
    
    return {"status": "waiting", "message": "In progress..."}


@router.post("/profile-login/stop/{session_id}")
async def profile_login_stop(session_id: str):
    """Stop the profile login session and close the browser."""
    stopped = stop_profile_login(session_id)
    if stopped:
        return {"message": "Browser closing..."}
    return {"message": "Session not found or already completed."}
```

---

## 4. Frontend: `api/index.js` — Add API Calls

**File:** `frontend/src/api/index.js`

Add to `settingsApi`:
```js
startProfileLogin: () => api.post('/settings/profile-login/start'),
getProfileLoginStatus: (sessionId) => api.get(`/settings/profile-login/status/${sessionId}`),
stopProfileLogin: (sessionId) => api.post(`/settings/profile-login/stop/${sessionId}`),
```

---

## 5. Frontend: `Settings.jsx` — Add Profile Login Section

**File:** `frontend/src/pages/Settings.jsx`

Add a new section between the Login Configuration and Cookie Manager sections:

```jsx
{/* Profile Login Section */}
<section className="bg-white rounded-lg shadow p-6">
  <h2 className="text-lg font-semibold border-b pb-3 mb-4">Google Login with Chrome Profile</h2>
  <p className="text-sm text-gray-500 mb-4">
    Log in using your Google account via your existing Chrome profile.
    A visible browser window opens — complete the login there, then cookies are
    auto-extracted. Use this if the site only supports Google OAuth.
  </p>
  
  {/* Profile settings */}
  <div className="space-y-3 mb-4">
    {['chrome_profile_path', 'profile_directory'].map(key => {
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

  {/* Status area — only visible during active login */}
  {profileLoginSession && (
    <div className="mb-4 p-3 bg-gray-50 border rounded-md">
      <p className="text-sm text-gray-600 mb-2">
        Status: <span className="font-medium">{profileLoginStatus}</span>
      </p>
      {profileLoginResult && (
        <div className={`text-sm p-2 rounded ${profileLoginResult.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
          {profileLoginResult.message}
        </div>
      )}
    </div>
  )}

  {/* Action buttons */}
  <div className="flex gap-3">
    <button
      onClick={handleStartProfileLogin}
      disabled={profileLoginSession !== null}
      className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 text-white px-5 py-2 rounded-md transition"
    >
      {profileLoginSession ? 'Browser Open...' : 'Login with Chrome Profile'}
    </button>
    {profileLoginSession && (
      <button
        onClick={handleStopProfileLogin}
        className="bg-red-600 hover:bg-red-700 text-white px-5 py-2 rounded-md transition"
      >
        Stop
      </button>
    )}
  </div>
</section>
```

### State and handler additions:

Add to component state:
```js
const [profileLoginSession, setProfileLoginSession] = useState(null);
const [profileLoginStatus, setProfileLoginStatus] = useState('');
const [profileLoginResult, setProfileLoginResult] = useState(null);
```

Add handlers:
```js
const handleStartProfileLogin = async () => {
  try {
    const res = await settingsApi.startProfileLogin();
    setProfileLoginSession(res.data.session_id);
    setProfileLoginStatus('waiting');
    setProfileLoginResult(null);
    startPollingProfileLogin(res.data.session_id);
  } catch (err) {
    setProfileLoginResult({ success: false, message: 'Failed to start: ' + err.message });
  }
};

const startPollingProfileLogin = (sessionId) => {
  const interval = setInterval(async () => {
    try {
      const res = await settingsApi.getProfileLoginStatus(sessionId);
      const data = res.data;
      
      if (data.status === 'extracted' || data.status === 'error') {
        clearInterval(interval);
        setProfileLoginSession(null);
        setProfileLoginStatus(data.status);
        setProfileLoginResult({
          success: data.status === 'extracted',
          message: data.message,
          cookies: data.cookies || []
        });
      }
    } catch (err) {
      clearInterval(interval);
      setProfileLoginSession(null);
      setProfileLoginStatus('error');
    }
  }, 2000);
  
  // Store interval ref for cleanup
  return interval;
};

const handleStopProfileLogin = async () => {
  if (profileLoginSession) {
    await settingsApi.stopProfileLogin(profileLoginSession);
    setProfileLoginSession(null);
    setProfileLoginStatus('stopped');
  }
};
```

Add cleanup in useEffect:
```js
useEffect(() => {
  return () => {
    if (profileLoginSession) {
      settingsApi.stopProfileLogin(profileLoginSession).catch(() => {});
    }
  };
}, []);
```

---

## Implementation Order

1. `database_schema.sql` — add 2 settings rows
2. `login.py` — add `profile_login()`, `ProfileLoginManager`
3. `settings.py` — add 3 endpoints, start/status/stop
4. `api/index.js` — add 3 API functions
5. `Settings.jsx` — add Profile Login section + state/handlers

Each step is self-contained and can be applied independently.
