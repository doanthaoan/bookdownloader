import { useState, useEffect, useRef } from 'react';
import { POLL_MS } from '../../constants';

/**
 * After starting a job, keep polling at least this long even if progress
 * still says inactive: the backend registers the job inside its background
 * thread, so the first poll can arrive before the job shows as active.
 */
const START_GRACE_MS = 10000;

/**
 * Custom hook: polling + "is a job running?" state for BookDetails.
 * (A custom hook is just a function whose name starts with `use` and that
 * calls other hooks; it lets a component share stateful logic.)
 *
 * How it works:
 * - The parent calls `applyProgress(p)` after every fetch with the job
 *   progress response.
 * - When a job is active and nobody is polling yet, polling starts and calls
 *   `refresh()` every POLL_MS.
 * - When progress says inactive, polling stops - unless a job was started
 *   by `trackJob()` less than START_GRACE_MS ago and hasn't been seen
 *   active yet (backend still spinning up its thread).
 *
 * Why refs instead of state for the bookkeeping: setInterval keeps calling
 * the function it was given. Anything that function read from state would be
 * frozen at the value of the render that created it ("stale closure"). Refs
 * are mutable boxes that always hold the current value, and changing them
 * does not cause a re-render.
 *
 * @param {() => void} refresh - reloads page data; must call applyProgress itself
 * @returns {{
 *   downloading: boolean,            // true while a job is (believed to be) running
 *   applyProgress: (p: {active?: boolean}) => void,
 *   trackJob: () => void,            // call right after successfully starting a job
 *   cancelJob: () => void,           // call after a successful cancel request
 * }}
 */
export default function useBookProgress(refresh) {
  const [downloading, setDownloading] = useState(false);
  const pollingRef = useRef(null);     // interval id, or null when not polling
  const pollSinceRef = useRef(0);      // Date.now() when polling started
  const sawActiveRef = useRef(false);  // has this polling run seen active=true yet?

  // Always call the latest `refresh` (the parent passes a new arrow function
  // each render). Updating the ref in an effect, not during render, follows
  // React's rule that rendering should not have side effects.
  const refreshRef = useRef(refresh);
  useEffect(() => { refreshRef.current = refresh; });

  /** Stop the interval if one is running. */
  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  /** (Re)start the interval. Clearing first guarantees at most one interval exists. */
  const startPolling = () => {
    stopPolling();
    pollSinceRef.current = Date.now();
    sawActiveRef.current = false;
    pollingRef.current = setInterval(() => refreshRef.current(), POLL_MS);
  };

  // Cleanup on unmount: leaving the page must not leave an interval running.
  // An effect with [] runs once; the function it returns runs on unmount.
  useEffect(() => stopPolling, []);

  /**
   * Update polling/downloading from a progress response.
   * @param {{active?: boolean}} p
   */
  const applyProgress = (p) => {
    if (p?.active) {
      // Page opened mid-job (or job started elsewhere): begin polling.
      if (!pollingRef.current) startPolling();
      sawActiveRef.current = true;
      setDownloading(true);
      return;
    }
    const inGrace = pollingRef.current
      && !sawActiveRef.current
      && Date.now() - pollSinceRef.current < START_GRACE_MS;
    if (!inGrace) {
      stopPolling();
      setDownloading(false);
    }
  };

  /** A job was just started: show the running state now and poll until it ends. */
  const trackJob = () => {
    setDownloading(true);
    startPolling();
  };

  /** A job was cancelled: stop polling and show the idle state. */
  const cancelJob = () => {
    stopPolling();
    setDownloading(false);
  };

  return { downloading, applyProgress, trackJob, cancelJob };
}
