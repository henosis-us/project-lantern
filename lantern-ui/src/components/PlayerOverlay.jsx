import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
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
  const hasStartedRef = useRef(false);
  const lastSentRef = useRef(0);
  const userPausedRef = useRef(false);
  const didLoadInitialSub = useRef(false);
  const seekDebounceTimer = useRef(null);
  const isStreamStartingRef = useRef(false);
  // This ref is the source of truth for the stream type
  const streamTypeRef = useRef('hls');

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
  useHls(videoRef, streamTypeRef.current === 'hls' && status !== 'error' ? playbackUrl : null, hlsStartTime);

  /* --------------- Core stream management function --------------- */
  const startStream = useCallback(
    async (seek = 0) => {
      if (!movie || !mediaServerApi) return;
      isStreamStartingRef.current = true;
      setStatus('loading');
      setHlsStartTime(seek);

      const params = new URLSearchParams();
      params.append('item_type', itemType);
      params.append('seek_time', seek);

      if (settings.mode === 'direct') {
        params.append('prefer_direct', 'true');
      } else if (settings.mode === 'transcode') {
        params.append('force_transcode', 'true');
        params.append('quality', settings.quality);
      } else {
        const getNetworkGrade = () => {
          const net = navigator.connection || {};
          const mbps = net.downlink || 10;
          if (mbps < 3) return 'low';
          if (mbps < 10) return 'medium';
          return 'high';
        };
        if (getNetworkGrade() === 'high' && !chosenSubtitle) { // Can't direct play with soft subs yet
          params.append('prefer_direct', 'true');
        } else {
          params.append('force_transcode', 'true');
          params.append('quality', settings.quality);
        }
      }
      if (settings.resolution !== 'source') params.append('scale', settings.resolution);
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
          streamTypeRef.current = 'direct';
          if (videoRef.current) {
            videoRef.current.src = new URL(data.direct_url, base).href;
            videoRef.current.currentTime = seek;
            videoRef.current.play().catch((e) => { console.warn("Direct play autoplay prevented:", e); });
          }
          setStatus('direct'); // Can be 'direct' or 'playing'
        } else {
          streamTypeRef.current = 'hls';
          setPlaybackUrl(new URL(data.hls_playlist_url, base).href);
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
        console.error("Error starting stream:", e);
        setStatus('error');
        isStreamStartingRef.current = false;
      }
    },
    [movie, settings, chosenSubtitle, itemType, mediaServerApi]
  );

  /* --------------- Lifecycle Effects --------------- */
  useEffect(() => {
    if (!movie || !mediaServerApi) return;
    const init = async () => {
      try {
        const { data } = await mediaServerApi.get(`/subtitles/${movie.id}/current?item_type=${itemType}`);
        if (data && data.subtitle_id) {
          setChosenSubtitle({ id: data.subtitle_id, lang: data.lang || 'en' });
        }
      } catch (err) { /* Ignore */ } finally { didLoadInitialSub.current = true; }
      try {
        const { data = {} } = await mediaServerApi.get(`/history/${movie.id}?item_type=${itemType}`);
        if (data.position_seconds > 5) {
          setResume({ show: true, pos: data.position_seconds });
        } else {
          startStream(0);
        }
      } catch {
        startStream(0);
      }
    };
    if (movie && !hasStartedRef.current) {
      init();
      hasStartedRef.current = true;
    }
    return () => {
      clearTimeout(seekDebounceTimer.current);
      if (movie && mediaServerApi) {
        mediaServerApi.delete(`/stream/${movie.id}`).catch((err) => console.error("Error stopping stream on backend:", err));
        const v = videoRef.current;
        if (v) {
          const ct = Math.floor(v.currentTime);
          const dur = Math.floor(v.duration);
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

  useEffect(() => {
    if (!movie || !didLoadInitialSub.current) return;
    if (didLoadInitialSub.current && hasStartedRef.current && chosenSubtitle !== undefined) {
      const cur = videoRef.current ? Math.floor(videoRef.current.currentTime) : 0;
      startStream(cur);
    }
  }, [chosenSubtitle, movie, startStream]);

  useEffect(() => {
    if (!didLoadInitialSub.current || !movie || !mediaServerApi) return;
    mediaServerApi.put(
      `/subtitles/${movie.id}/select?item_type=${itemType}`,
      { subtitle_id: chosenSubtitle ? chosenSubtitle.id : null }
    ).catch((err) => console.error("Failed to persist subtitle selection:", err));
  }, [chosenSubtitle, movie, itemType, mediaServerApi]);

  /* --------------- Event Handlers --------------- */

  // This handler is now ONLY used for HLS streams.
  const handleHlsSeek = useCallback(() => {
    if (isStreamStartingRef.current || !videoRef.current) {
      return;
    }
    clearTimeout(seekDebounceTimer.current);
    seekDebounceTimer.current = setTimeout(() => {
      if (videoRef.current) {
        const seekTime = videoRef.current.currentTime;
        console.log(`[Player] HLS seek complete. Restarting stream at ${seekTime.toFixed(2)}s.`);
        startStream(seekTime);
      }
    }, 800);
  }, [startStream]);

  const onTimeUpdate = useCallback(() => {
    const v = videoRef.current;
    if (!v || v.seeking || userPausedRef.current) return;
    setProgress(p => ({ ...p, currentTime: v.currentTime, duration: p.duration || v.duration }));
    if (Math.floor(v.currentTime) % 15 === 0 && v.currentTime - lastSentRef.current >= 15) {
      const ct = Math.floor(v.currentTime);
      const dur = Math.floor(v.duration || progress.duration);
      if (Number.isFinite(ct) && Number.isFinite(dur) && dur > 0 && mediaServerApi) {
        mediaServerApi.put(
          `/history/${movie.id}?item_type=${itemType}`,
          { position_seconds: ct, duration_seconds: dur }
        ).catch((err) => console.error("Failed to save progress:", err));
      }
      lastSentRef.current = v.currentTime;
    }
  }, [movie, itemType, progress.duration, mediaServerApi]);

  const onProgressUpdate = useCallback(() => {
    const v = videoRef.current;
    if (v && v.buffered.length) {
      const bufferedEnd = v.buffered.end(v.buffered.length - 1);
      setProgress(p => ({ ...p, buffered: bufferedEnd }));
      if (v.paused && !v.seeking && status !== 'error' && !userPausedRef.current && (bufferedEnd - v.currentTime > 2)) {
        v.play().catch((e) => console.log("Autoplay on buffer prevented:", e));
      }
    }
  }, [status]);

  const onWaiting = useCallback(() => {
    if (streamTypeRef.current !== 'direct' && status !== 'error') {
      setStatus('loading');
    }
  }, [status]);

  const onPlaying = useCallback(() => {
    if (isStreamStartingRef.current) {
      isStreamStartingRef.current = false;
      console.log("[Player] Video playing, seek detection re-enabled.");
    }
    if (status === 'loading' || status === 'direct') {
      setStatus('playing');
    }
  }, [status]);

  const onEnded = useCallback(() => {
    if (mediaServerApi) {
      mediaServerApi.delete(`/history/${movie.id}?item_type=${itemType}`).catch((err) => console.error("Failed to clear history on end:", err));
    }
    setStatus('finished');
  }, [movie, itemType, mediaServerApi]);

  const handleUserPlay = useCallback(() => {
    userPausedRef.current = false;
    const v = videoRef.current;
    if (v && v.muted) { v.muted = false; v.volume = 1; }
  }, []);

  const handleUserPause = useCallback(() => {
    const v = videoRef.current;
    if (v && !v.ended && !v.seeking && status !== 'loading') {
      userPausedRef.current = true;
    }
  }, [status]);

  const openSubtitlePicker = useCallback(() => setOpenSubtitles(true), []);

  const handleSubtitleSelect = useCallback(async (sub) => {
    setChosenSubtitle(sub);
    setOpenSubtitles(false);
  }, []);

  const doResume = useCallback(() => {
    startStream(resume.pos);
    setResume({ show: false, pos: 0 });
  }, [resume.pos, startStream]);

  const doStartOver = useCallback(async () => {
    try {
      if (mediaServerApi) {
        await mediaServerApi.delete(`/history/${movie.id}?item_type=${itemType}`);
      }
    } catch (err) { console.error("Failed to clear progress (start over):", err); }
    startStream(0);
    setResume({ show: false, pos: 0 });
  }, [movie, itemType, startStream, mediaServerApi]);

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
              {streamTypeRef.current === 'hls' && (
                <progress className="buffer-bar" value={bufferPct} max="100" />
              )}
            </div>
            <video
              id="video"
              ref={videoRef}
              controls
              autoPlay
              playsInline
              muted
              crossOrigin="anonymous"
              onPlay={handleUserPlay}
              onPause={handleUserPause}
              onTimeUpdate={onTimeUpdate}
              onProgress={onProgressUpdate}
              // *** THE CRITICAL FIX ***
              // Only attach custom seek handlers for HLS streams.
              // For direct play, these will be undefined, allowing the browser to handle seeking natively.
              onSeeking={streamTypeRef.current === 'hls' ? handleHlsSeek : undefined}
              onSeeked={streamTypeRef.current === 'hls' ? handleHlsSeek : undefined}
              onWaiting={onWaiting}
              onEnded={onEnded}
              onPlaying={onPlaying}
              onCanPlay={onPlaying}
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