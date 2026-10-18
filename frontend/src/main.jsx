/**
 * App entry point: mounts <App /> into the #app div of index.html.
 * StrictMode renders components twice in development (not in production)
 * to surface side effects that lack proper useEffect cleanup.
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('app')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
