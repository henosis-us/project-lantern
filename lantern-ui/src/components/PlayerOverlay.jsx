import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import useHls from '../hooks/useHls'; // This will also be updated below
import useLocalStorage from '../hooks/useLocalStorage';
import MiniPlayer from './MiniPlayer';
import SettingsModal from './SettingsModal';
import ResumeModal from './ResumeModal';
import SubtitlePicker from './SubtitlePicker';

function PlayerOverlay({ movie, onClose }) {
  /* --------------- state --------------- */
  const [status, setStatus] = useState('loading');
  const [playbackUrl, setPlaybackUrl] = useState('');
  // State to explicitly tell HLS.js where to start (0 for beginning, >0 for seek)
  const [hlsStartTime, setHlsStartTime] = useState(0); 
  
  const [isMinimized, setIsMinimized] = useState(false);
  const [openSettings, setOpenSettings] = useState(false);
  const [openSubtitles, setOpenSubtitles] = useState(false);
  const [progress, setProgress] = useState({ currentTime: 0, buffered: 0, duration: 0 });
  const [resume, setResume] = useState({ show: false, pos: 0 });
  const [chosenSubtitle, setChosenSubtitle] = useState(null);
  const { mediaServerApi } = useAuth();

  /* --------------- user settings --------------- */
  const [settings, setSettings] = useLocalStorage('lanternSettings', {
    mode: 'auto',
    quality: 'medium',
    resolution: 'source',
    subs: 'off',
  });

  /* --------------- refs --------------- */
  const videoRef = useRef(null);
  const hasStartedRef = useRef(false); // Tracks if stream has been started at least once
  const lastSentRef = useRef(0); // For throttling progress updates
  const userPausedRef = useRef(false); // Tracks if user manually paused
  const didLoadInitialSub = useRef(false); // Ensures subtitles are fetched only once initially
  const seekDebounceTimer = useRef(null); // Timer for debouncing seek events
  // *** THE CRITICAL FLAG ***: True when the application is actively initiating a stream (new play, seek, resume)
  // This helps distinguish between user seeks and programmatic seeks by HLS.js
  const isStreamStartingRef = useRef(false); 

  const isEpisode = movie && (movie.series_id !== undefined || movie.season !== undefined);
  const itemType = isEpisode ? 'episode' : 'movie';

  /* --------------- helpers --------------- */
  const fmtTime = (secs) => {
    if (isNaN(secs) || secs < 0) return '0:00';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = Math.floor(secs % 60).toString().padStart(2, '0');
    return h ? `${h}:${m.toString().padStart(2, '0')}:${s}` : `${m}:${s}`;
  };

  /* --------------- HLS hook integration --------------- */
  // Pass hlsStartTime to the useHls hook, telling HLS.js where to start in the manifest
  useHls(videoRef, status !== 'direct' && status !== 'error' ? playbackUrl : null, hlsStartTime);
  
  /* --------------- Core stream management function --------------- */
  const startStream = useCallback(
    async (seek = 0) => {
      if (!movie || !mediaServerApi) return;
      
      // *** Set the flag indicating a stream startup is in progress ***
      isStreamStartingRef.current = true; 
      setStatus('loading');
      setHlsStartTime(seek); // Tell HLS.js to start from this position

      // Build parameters for the backend stream request
      const params = new URLSearchParams();
      params.append('item_type', itemType);
      params.append('seek_time', seek);

      // Determine transcoding preferences based on settings
      if (settings.mode === 'direct') {
        params.append('prefer_direct', 'true');
      } else if (settings.mode === 'transcode') {
        params.append('force_transcode', 'true');
        params.append('quality', settings.quality);
      } else { // 'auto' mode
        // Simple network speed check (can be improved)
        const getNetworkGrade = () => {
            const net = navigator.connection || {};
            const mbps = net.downlink || 10;
            if (mbps < 3) return 'low';
            if (mbps < 10) return 'medium';
            return 'high';
        };
        const shouldDirect = () => getNetworkGrade() === 'high';

        if (shouldDirect()) {
            params.append('prefer_direct', 'true');
        } else {
            params.append('force_transcode', 'true');
            params.append('quality', settings.quality);
        }
      }

      if (settings.resolution !== 'source') params.append('scale', settings.resolution);

      // Subtitle burning/soft-subs
      if (chosenSubtitle && settings.subs !== 'off') {
        params.append('subtitle_id', chosenSubtitle.id);
        if (settings.subs === 'burn') {
          params.append('burn', 'true');
        }
      }

      try {
        const { data } = await mediaServerApi.get(`/stream/${movie.id}?${params.toString()}`);
        const base = mediaServerApi.defaults.baseURL;
        
        setProgress(p => ({ ...p, duration: data.duration_seconds || movie.duration_seconds }));

        if (data.mode === 'direct' || data.direct_url) {
          // For direct play, HLS.js is not used, so we handle video element properties directly
          if (videoRef.current) {
            videoRef.current.src = new URL(data.direct_url, base).href;
            videoRef.current.currentTime = seek; // Manually set seek time for direct play
            videoRef.current.play().catch((e)=>{console.warn("Direct play autoplay prevented:", e);});
          }
          setStatus('direct');
          // Direct play doesn't involve HLS.js programmatic seeks, so clear flag here.
          isStreamStartingRef.current = false; 
        } else {
          // For HLS, set the playlist URL. HLS.js will pick up hlsStartTime from its config.
          setPlaybackUrl(new URL(data.hls_playlist_url, base).href);
        }
        
        // Handle soft subtitles if provided
        if (data.soft_sub_url && videoRef.current) {
          // Remove old dynamic tracks
          [...videoRef.current.querySelectorAll('track[data-dynamic]')].forEach(t => t.remove());
          const v = videoRef.current;
          const t = document.createElement('track');
          t.kind = 'subtitles';
          t.label = 'Selected Subtitle';
          t.srclang = chosenSubtitle ? chosenSubtitle.lang : 'en'; // Fallback to 'en'
          t.default = true; // Make it default so it shows up
          t.src = new URL(data.soft_sub_url, base).href;
          t.setAttribute('data-dynamic', ''); // Mark as dynamically added
          // Ensure track mode is 'showing' when loaded
          t.addEventListener('load', () => { if (t.track) t.track.mode = 'showing'; });
          v.appendChild(t);
        }
      } catch (e) {
        console.error("Error starting stream:", e);
        setStatus('error');
        // If stream fails to start, clear the flag to allow re-attempts
        isStreamStartingRef.current = false; 
      }
    },
    [movie, settings, chosenSubtitle, itemType, mediaServerApi]
  );
  
  /* --------------- Lifecycle Effects --------------- */

  // Effect for initial stream load and cleanup on component unmount
  useEffect(() => {
    if (!movie || !mediaServerApi) return;

    const init = async () => {
      // Fetch current subtitle selection
      try {
        const { data } = await mediaServerApi.get(`/subtitles/${movie.id}/current?item_type=${itemType}`);
        if (data && data.subtitle_id) {
          setChosenSubtitle({ id: data.subtitle_id, lang: data.lang || 'en' });
        }
      } catch (err) { /* Ignore if no subtitle preference found */ } finally { didLoadInitialSub.current = true; }

      // Check for watch history to offer resume
      try {
        const { data = {} } = await mediaServerApi.get(`/history/${movie.id}?item_type=${itemType}`);
        // Only offer resume if position is significant (>5s into content)
        if (data.position_seconds > 5) { 
          setResume({ show: true, pos: data.position_seconds });
        } else {
          startStream(0); // Start from beginning if no significant history
        }
      } catch { 
        startStream(0); // Start from beginning if history lookup fails
      }
    };

    // Trigger initial load only once
    if (movie && !hasStartedRef.current) {
      init();
      hasStartedRef.current = true;
    }

    // Cleanup function: save progress and stop stream on component unmount
    return () => {
      // Clear any pending debounce timers to prevent calls after unmount
      clearTimeout(seekDebounceTimer.current);

      // Tell the backend to stop the FFmpeg process
      if (movie && mediaServerApi) {
        mediaServerApi.delete(`/stream/${movie.id}`).catch((err) => console.error("Error stopping stream on backend:", err));
        
        // Save final watch progress
        const v = videoRef.current;
        if (v) { // Ensure video element exists before trying to read properties
          const ct = Math.floor(v.currentTime);
          const dur = Math.floor(v.duration);
          // Only save if progress is significant and not at the very end
          if (Number.isFinite(ct) && Number.isFinite(dur) && dur > 0 && ct > 5 && ct < dur - 5) {
            mediaServerApi.put(
              `/history/${movie.id}?item_type=${itemType}`,
              { position_seconds: ct, duration_seconds: dur }
            ).catch((err) => console.error("Failed to save final progress:", err));
          }
        }
      }
    };
  }, [movie, startStream, itemType, mediaServerApi]);

  // Effect to restart stream if subtitle choice changes (after initial load)
  useEffect(() => {
    // Only trigger if subtitle has been initially loaded AND movie is defined
    if (!movie || !didLoadInitialSub.current) return;
    // Don't re-trigger if it's the very first time setting a subtitle after init.
    // The initial startStream call already incorporates it.
    if (didLoadInitialSub.current && hasStartedRef.current && chosenSubtitle !== undefined) {
      const cur = videoRef.current ? Math.floor(videoRef.current.currentTime) : 0;
      startStream(cur);
    }
  }, [chosenSubtitle, movie, startStream]);

  // Effect to persist subtitle preference to backend
  useEffect(() => {
    // Only persist preference if initial subtitle load is complete
    if (!didLoadInitialSub.current || !movie || !mediaServerApi) return;
    mediaServerApi.put(
      `/subtitles/${movie.id}/select?item_type=${itemType}`,
      { subtitle_id: chosenSubtitle ? chosenSubtitle.id : null }
    ).catch((err) => console.error("Failed to persist subtitle selection:", err));
  }, [chosenSubtitle, movie, itemType, mediaServerApi]);
  
  /* --------------- Event Handlers --------------- */
  
  // Debounced seek handler. Called by both onSeeking and onSeeked events.
  const handleSeek = useCallback(() => {
    // If the app is currently in the process of starting a stream, ignore seek events.
    // This prevents HLS.js's programmatic seeks from triggering new stream requests.
    if (isStreamStartingRef.current || status === 'direct' || !videoRef.current) {
      return;
    }
    
    // Clear any existing timer to ensure we only act after a pause in seeking
    clearTimeout(seekDebounceTimer.current);

    // Set a new timer to call startStream after a short delay
    seekDebounceTimer.current = setTimeout(() => {
      // Re-check videoRef.current in case component unmounted during timeout
      if (videoRef.current) { 
        const seekTime = videoRef.current.currentTime;
        console.log(`[Player] User seek complete. Restarting stream at ${seekTime.toFixed(2)}s.`);
        startStream(seekTime);
      }
    }, 800); // Wait 800ms after the last seek event before restarting stream
  }, [status, startStream]);

  const onTimeUpdate = useCallback(() => {
    const v = videoRef.current;
    // Don't update or save progress if video is currently seeking OR paused by user
    if (!v || v.seeking || userPausedRef.current) return; 

    // Update frontend progress state
    setProgress(p => ({ ...p, currentTime: v.currentTime, duration: p.duration || v.duration }));
    
    // Throttle backend progress saving to every 15 seconds of actual playback
    if (Math.floor(v.currentTime) % 15 === 0 && v.currentTime - lastSentRef.current >= 15) {
      const ct = Math.floor(v.currentTime);
      const dur = Math.floor(v.duration || progress.duration); // Use stored duration if video.duration isn't final
      if (Number.isFinite(ct) && Number.isFinite(dur) && dur > 0 && mediaServerApi) {
        mediaServerApi.put(
          `/history/${movie.id}?item_type=${itemType}`,
          { position_seconds: ct, duration_seconds: dur }
        ).catch((err) => console.error("Failed to save progress:", err));
      }
      lastSentRef.current = v.currentTime; // Update last sent time
    }
  }, [movie, itemType, progress.duration, mediaServerApi, userPausedRef]);

  const onProgressUpdate = useCallback(() => {
    const v = videoRef.current;
    if (v && v.buffered.length) {
      const bufferedEnd = v.buffered.end(v.buffered.length - 1);
      setProgress(p => ({ ...p, buffered: bufferedEnd }));

      // Auto-play if paused (and not by user), not seeking, not in error, and has enough buffer
      if (v.paused && !v.seeking && status !== 'error' && !userPausedRef.current && (bufferedEnd - v.currentTime > 2)) {
        v.play().catch((e) => console.log("Autoplay on buffer prevented:", e));
      }
    }
  }, [status, userPausedRef]);

  const onWaiting = useCallback(() => {
    // Set status to loading when video is buffering
    if (status !== 'direct' && status !== 'error') {
      setStatus('loading'); 
    }
  }, [status]);

  const onPlaying = useCallback(() => {
    // *** Clear the stream starting flag ***
    // Once the video element reports 'playing', we consider the stream fully established.
    if (isStreamStartingRef.current) {
      isStreamStartingRef.current = false;
      console.log("[Player] Video playing, seek detection re-enabled.");
    }
    // Transition from 'loading' to 'playing' when actual playback starts
    if (status === 'loading') {
      setStatus('playing');
    }
  }, [status]);

  const onEnded = useCallback(() => {
    // Clear watch history when media finishes playing
    if (mediaServerApi) {
      mediaServerApi.delete(`/history/${movie.id}?item_type=${itemType}`).catch((err) => console.error("Failed to clear history on end:", err));
    }
    setStatus('finished');
  }, [movie, itemType, mediaServerApi]);

  const handleUserPlay = useCallback(() => {
    userPausedRef.current = false; // User initiated play
    const v = videoRef.current;
    // Attempt to unmute if autoplay prevented it
    if (v && v.muted) { v.muted = false; v.volume = 1; }
  }, []);

  const handleUserPause = useCallback(() => {
    const v = videoRef.current;
    // Only consider it a "user pause" if not already ended, seeking, or still loading
    if (v && !v.ended && !v.seeking && status !== 'loading') {
      userPausedRef.current = true;
    }
  }, [status]);

  const openSubtitlePicker = useCallback(() => setOpenSubtitles(true), []);

  const handleSubtitleSelect = useCallback(async (sub) => {
    setChosenSubtitle(sub);
    setOpenSubtitles(false);
  }, []); // Dependencies for this are handled by the useEffect for subtitle persistence

  const doResume = useCallback(() => {
    startStream(resume.pos);
    setResume({ show: false, pos: 0 }); // Hide resume modal
  }, [resume.pos, startStream]);

  const doStartOver = useCallback(async () => {
    try {
      if (mediaServerApi) {
        await mediaServerApi.delete(`/history/${movie.id}?item_type=${itemType}`); // Clear backend history
      }
    } catch (err) { console.error("Failed to clear progress (start over):", err); }
    startStream(0); // Start stream from beginning
    setResume({ show: false, pos: 0 }); // Hide resume modal
  }, [movie, itemType, startStream, mediaServerApi]);

  // Effect to toggle body class for minimized player styling
  useEffect(() => { document.body.classList.toggle('player-minimized', isMinimized); }, [isMinimized]);

  if (!movie) return null; // Don't render if no movie data

  const bufferPct = progress.duration ? (progress.buffered / progress.duration) * 100 : 0;

  return (
    <>
      <div id="player-wrapper" className={isMinimized ? 'minimized' : 'active'}>
        <ResumeModal isOpen={resume.show} onResume={doResume} onStartOver={doStartOver} resumeTime={fmtTime(resume.pos)} />
        {openSubtitles && (
          <SubtitlePicker
            movie={movie}
            itemType={itemType}
            onSelect={handleSubtitleSelect}
            onClose={() => setOpenSubtitles(false)}
            activeSubId={chosenSubtitle?.id ?? null}
          />
        )}
        {openSettings && (
          <SettingsModal settings={settings} onSettingsChange={setSettings} onClose={() => setOpenSettings(false)} />
        )}
        <div id="player-container">
          <div id="player-header">
            <h2 id="now-playing-title">{movie.title}</h2>
            <div className="player-controls">
              <button title="Subtitles" className={chosenSubtitle ? 'active' : ''} onClick={openSubtitlePicker}>Sub</button>
              <button title="Settings" onClick={() => setOpenSettings(true)}>⚙</button>
              <button title="Minimize" onClick={() => setIsMinimized(true)}>_</button>
              <button title="Close" onClick={() => { if (videoRef.current) { videoRef.current.src = ''; } onClose(); }}>X</button>
            </div>
          </div>
          <div id="video-area">
            {status === 'loading' && !resume.show && (
              <div className="loader" id="loader" style={{ display: 'block' }}></div>
            )}
            <div className="progress-container">
              <progress className="buffer-bar" value={bufferPct} max="100" />
            </div>
            <video
              id="video"
              ref={videoRef}
              controls
              autoPlay
              playsInline
              muted
              crossOrigin="anonymous"
              onPlay={handleUserPlay} // Handles user clicking play
              onPause={handleUserPause} // Handles user clicking pause
              onTimeUpdate={onTimeUpdate} // Updates current playback time
              onProgress={onProgressUpdate} // Updates buffered amount, attempts autoplay if stalled
              onSeeking={handleSeek} // Called repeatedly while seeking
              onSeeked={handleSeek} // Called once when seeking finishes
              onWaiting={onWaiting} // Called when video is waiting for data
              onEnded={onEnded} // Called when video finishes
              onPlaying={onPlaying} // Called when video actually starts playing
              onCanPlay={onPlaying} // Also useful for triggering onPlaying logic (e.g., after initial load)
            />
          </div>
        </div>
      </div>
      {isMinimized && (
        <MiniPlayer title={movie.title} onRestore={() => setIsMinimized(false)} />
      )}
    </>
  );
}

export default PlayerOverlay;