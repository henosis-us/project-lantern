import React, { useState, useEffect, useRef, useCallback } from 'react';
// DELETED: import api from '../api/api';
// DELETED: import { saveProgress, getProgress, clearProgress, getCurrentSubtitleSelection, setSubtitleSelection } from '../api/api';
import { useAuth } from '../context/AuthContext'; // NEW: Import useAuth to get mediaServerApi

import useHls from '../hooks/useHls';
import useLocalStorage from '../hooks/useLocalStorage';
import MiniPlayer from './MiniPlayer';
import SettingsModal from './SettingsModal';
import ResumeModal from './ResumeModal';
import SubtitlePicker from './SubtitlePicker';

function PlayerOverlay({ movie, onClose }) {
  /* --------------- state --------------- */
  const [status, setStatus] = useState('loading');
  const [playbackUrl, setPlaybackUrl] = useState('');
  const [isMinimized, setIsMinimized] = useState(false);
  const [openSettings, setOpenSettings] = useState(false);
  const [openSubtitles, setOpenSubtitles] = useState(false);
  const [progress, setProgress] = useState({ currentTime: 0, buffered: 0, duration: 0 });
  const [resume, setResume] = useState({ show: false, pos: 0 });
  const [chosenSubtitle, setChosenSubtitle] = useState(null);
  const didLoadInitialSub = useRef(false);

  // NEW: Get the dynamic mediaServerApi instance from the context
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
  const seekTimerRef = useRef(null);
  const isSeekingRef = useRef(false);
  const hasStartedRef = useRef(false);
  const lastSentRef = useRef(0);
  const initialSeekRef = useRef(0);
  const userPausedRef = useRef(false); // *** FIX: Track if the user manually paused

  const isEpisode = movie && (movie.series_id !== undefined || movie.season !== undefined);
  const itemType = isEpisode ? 'episode' : 'movie';

  /* --------------- helpers --------------- */
  const getNetworkGrade = () => {
    const net = navigator.connection || {};
    const mbps = net.downlink || 10;
    if (mbps < 3) return 'low';
    if (mbps < 10) return 'medium';
    return 'high';
  };

  const shouldDirect = () => getNetworkGrade() === 'high';

  const fmtTime = (secs) => {
    if (isNaN(secs) || secs < 0) return '0:00';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = Math.floor(secs % 60).toString().padStart(2, '0');
    return h ? `${h}:${m.toString().padStart(2, '0')}:${s}` : `${m}:${s}`;
  };

  /* --------------- HLS hook --------------- */
  const handleFragBuffered = useCallback(() => {
    setStatus(s => (s === 'playing' ? s : 'playing'));
  }, []);

  useHls(
    videoRef,
    status !== 'direct' && status !== 'error' ? playbackUrl : null,
    handleFragBuffered
  );

  /* --------------- start / restart stream with subtitle support --------------- */
  const startStream = useCallback(
    async (seek = 0) => {
      // NEW: Ensure mediaServerApi is available
      if (!movie || !mediaServerApi) return; 

      setStatus('loading');
      initialSeekRef.current = seek;
      setProgress(p => ({ ...p, currentTime: seek }));

      const params = new URLSearchParams();
      params.append('item_type', itemType);
      params.append('seek_time', seek);

      if (settings.mode === 'direct') {
        params.append('prefer_direct', 'true');
      } else if (settings.mode === 'transcode') {
        params.append('force_transcode', 'true');
        params.append('quality', settings.quality);
      } else {
        shouldDirect()
          ? params.append('prefer_direct', 'true')
          : params.append('force_transcode', 'true') && params.append('quality', settings.quality);
      }

      if (settings.resolution !== 'source') params.append('scale', settings.resolution);

      if (chosenSubtitle && settings.subs !== 'off') {
        params.append('subtitle_id', chosenSubtitle.id);
        if (settings.subs === 'burn') {
          params.append('burn', 'true');
        }
      }

      try {
        // Use mediaServerApi for the stream request
        const { data } = await mediaServerApi.get(`/stream/${movie.id}?${params.toString()}`);
        
        // NEW: Base URL for resolving relative paths should be from mediaServerApi
        const base = mediaServerApi.defaults.baseURL;

        if (data.direct_url) data.direct_url = new URL(data.direct_url, base).href;
        if (data.hls_playlist_url) data.hls_playlist_url = new URL(data.hls_playlist_url, base).href;

        setProgress(p => ({ ...p, duration: data.duration_seconds || movie.duration_seconds }));

        if (data.mode === 'direct' || data.direct_url) {
          setPlaybackUrl(data.direct_url);
          setStatus('direct');
        } else {
          setPlaybackUrl(data.hls_playlist_url);
          setStatus('playing');
        }

        if (data.soft_sub_url && videoRef.current) {
          [...videoRef.current.querySelectorAll('track[data-dynamic]')].forEach(t => t.remove());
          const v = videoRef.current;
          const t = document.createElement('track');
          t.kind = 'subtitles';
          t.label = 'Selected Subtitle';
          t.srclang = chosenSubtitle ? chosenSubtitle.lang : 'en';
          t.default = true;
          t.src = new URL(data.soft_sub_url, base).href;
          t.setAttribute('data-dynamic', '');
          t.addEventListener('load', () => { if (t.track) t.track.mode = 'showing'; });
          v.appendChild(t);
        }
      } catch (e) {
        console.error(e);
        setStatus('error');
      }
    },
    [movie, settings, chosenSubtitle, itemType, mediaServerApi] // NEW: Add mediaServerApi to dependency array
  );

  /* --------------- init first load with resume check --------------- */
  useEffect(() => {
    // NEW: Ensure movie and mediaServerApi are available
    if (!movie || !mediaServerApi) return; 

    const init = async () => {
      try {
        // Use mediaServerApi for subtitle selection check
        const { data } = await mediaServerApi.get(`/subtitles/${movie.id}/current?item_type=${itemType}`);
        if (data && data.subtitle_id) {
          setChosenSubtitle({ id: data.subtitle_id, lang: data.lang || 'en' });
        }
      } catch {/* ignore – default to no subs */ } finally { didLoadInitialSub.current = true; }
      
      try {
        // Use mediaServerApi for progress check
        const { data = {} } = await mediaServerApi.get(`/history/${movie.id}?item_type=${itemType}`);
        if (data.position_seconds > 0) {
          setResume({ show: true, pos: data.position_seconds });
        } else {
          startStream(0);
        }
      } catch { startStream(0); }
    };

    if (movie && !hasStartedRef.current) {
      init();
      hasStartedRef.current = true;
    }

    return () => {
      if (movie && mediaServerApi) mediaServerApi.delete(`/stream/${movie.id}`).catch(() => {}); // NEW: Use mediaServerApi
      const v = videoRef.current;
      if (movie && v && mediaServerApi) { // NEW: Check mediaServerApi
        const ct = Math.floor(v.currentTime);
        const dur = Math.floor(v.duration);
        if (Number.isFinite(ct) && Number.isFinite(dur) && dur > 0 && ct > 5 && ct < dur - 5) {
          // Use mediaServerApi for saving progress
          mediaServerApi.put(
            `/history/${movie.id}?item_type=${itemType}`,
            { position_seconds: ct, duration_seconds: dur }
          ).catch(() => {});
        }
      }
    };
  }, [movie, startStream, itemType, mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  /* --------------- handle subtitle change: restart stream --------------- */
  useEffect(() => {
    // NEW: Ensure movie and mediaServerApi are available
    if (!movie || !didLoadInitialSub.current || !mediaServerApi) return; 

    const cur = videoRef.current ? Math.floor(videoRef.current.currentTime) : 0;
    startStream(cur);
  }, [chosenSubtitle, movie, startStream, mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  /* --------------- persist programmatic subtitle changes ---------- */
  useEffect(() => {
    // NEW: Ensure movie and mediaServerApi are available
    if (!didLoadInitialSub.current || !movie || !mediaServerApi) return; 

    // Use mediaServerApi for setting subtitle selection
    mediaServerApi.put(
      `/subtitles/${movie.id}/select?item_type=${itemType}`, 
      { subtitle_id: chosenSubtitle ? chosenSubtitle.id : null }
    ).catch(() => {});
  }, [chosenSubtitle, movie, itemType, mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  /* --------------- direct-play handling & auto-seek --------------- */
  useEffect(() => {
    if (status !== 'direct' || !playbackUrl || !videoRef.current) return;
    const v = videoRef.current;
    const tgt = initialSeekRef.current || 0;
    const onLoaded = () => {
      if (tgt > 0) { try { v.currentTime = tgt; } catch {} }
      v.play().catch(() => {});
    };
    v.addEventListener('loadedmetadata', onLoaded, { once: true });
    v.src = playbackUrl;
    return () => v.removeEventListener('loadedmetadata', onLoaded);
  }, [status, playbackUrl]);

  /* --------------- event handlers --------------- */
  const onTimeUpdate = () => {
    if (isSeekingRef.current) return;
    const v = videoRef.current;
    if (!v) return;
    setProgress(p => ({ ...p, currentTime: v.currentTime, duration: p.duration || v.duration }));
    if (Math.floor(v.currentTime) % 15 === 0 && v.currentTime - lastSentRef.current >= 15) {
      const ct = Math.floor(v.currentTime);
      const dur = Math.floor(v.duration || progress.duration);
      if (Number.isFinite(ct) && Number.isFinite(dur) && dur > 0 && mediaServerApi) { // NEW: Check mediaServerApi
        // Use mediaServerApi for saving progress
        mediaServerApi.put(
          `/history/${movie.id}?item_type=${itemType}`,
          { position_seconds: ct, duration_seconds: dur }
        ).catch(() => {});
      }
      lastSentRef.current = v.currentTime;
    }
  };

  const onProgressUpdate = () => {
    const v = videoRef.current;
    if (v && v.buffered.length) {
      setProgress(p => ({ ...p, buffered: v.buffered.end(v.buffered.length - 1) }));
      // *** FIX: Only auto-play if the user has NOT manually paused ***
      if (v.paused && !isSeekingRef.current && status !== 'error' && !userPausedRef.current && (v.buffered.end(v.buffered.length - 1) - v.currentTime > 5)) {
        v.play().catch(() => {});
      }
    }
  };

  const onSeeking = () => {
    if (status === 'direct' || !isSeekingRef.current) return;
    clearTimeout(seekTimerRef.current);
    setStatus('loading');
    seekTimerRef.current = setTimeout(() => startStream(videoRef.current.currentTime), 800);
  };

  const onWaiting = () => {
    if (status !== 'direct') setStatus('loading');
  };

  const onEnded = () => {
    if (mediaServerApi) { // NEW: Check mediaServerApi
      mediaServerApi.delete(`/history/${movie.id}?item_type=${itemType}`).catch(() => {}); // NEW: Use mediaServerApi
    }
    setStatus('finished');
  };

  // *** FIX: Add handlers to track user pause/play actions ***
  const handleUserPlay = () => {
    userPausedRef.current = false;
  };
  const handleUserPause = () => {
    // We only set the user pause ref if the pause is not due to seeking or buffering.
    if (!isSeekingRef.current && status !== 'loading') {
      userPausedRef.current = true;
    }
  };

  const handlePlayAutounmute = () => {
    const v = videoRef.current;
    if (v) { v.muted = false; v.volume = 1; }
  };

  const openSubtitlePicker = () => setOpenSubtitles(true);

  const handleSubtitleSelect = async (sub) => {
    setChosenSubtitle(sub);
    setOpenSubtitles(false);
    try {
      if (mediaServerApi) { // NEW: Check mediaServerApi
        // Use mediaServerApi for setting subtitle selection
        await mediaServerApi.put(
          `/subtitles/${movie.id}/select?item_type=${itemType}`, 
          { subtitle_id: sub ? sub.id : null }
        );
      }
    } catch (err) { console.error('[SUB] failed to save subtitle selection', err); }
  };

  const doResume = () => { startStream(resume.pos); setResume({ show: false, pos: 0 }); };

  const doStartOver = async () => {
    try { 
      if (mediaServerApi) { // NEW: Check mediaServerApi
        await mediaServerApi.delete(`/history/${movie.id}?item_type=${itemType}`); // NEW: Use mediaServerApi
      }
    } catch (err) { console.error("Failed to clear progress", err); }
    startStream(0);
    setResume({ show: false, pos: 0 });
  };

  useEffect(() => { document.body.classList.toggle('player-minimized', isMinimized); }, [isMinimized]);

  if (!movie) return null;

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
              onPlay={() => {
                handlePlayAutounmute();
                handleUserPlay(); // *** FIX: Register play action
              }}
              onPause={handleUserPause} // *** FIX: Register pause action
              onTimeUpdate={onTimeUpdate}
              onProgress={onProgressUpdate}
              onSeeking={onSeeking}
              onWaiting={onWaiting}
              onEnded={onEnded}
              onCanPlay={() => {
                const v = videoRef.current;
                // *** FIX: Only auto-play if user has not paused
                if (v && v.paused && !userPausedRef.current) {
                  v.play().catch(() => {});
                }
                if (status === 'loading') {
                  setStatus(status === 'direct' ? 'direct' : 'playing');
                }
              }}
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