// src/hooks/useHls.jsx
import { useEffect, useRef } from 'react';
import Hls from 'hls.js';

// MODIFIED: Added startTime parameter
function useHls(videoRef, src, startTime, onFragBuffered) {
  const hlsRef = useRef(null);

  useEffect(() => {
    if (!videoRef.current || !src) return;

    if (hlsRef.current) {
      hlsRef.current.destroy();
    }
    
    // Handle native HLS support (e.g., Safari)
    if (videoRef.current.canPlayType('application/vnd.apple.mpegurl') && !Hls.isSupported()) {
      videoRef.current.src = src;
      // For native HLS, we manually set the start time
      videoRef.current.addEventListener('loadedmetadata', () => {
        if (startTime > 0) {
          videoRef.current.currentTime = startTime;
        }
        videoRef.current.play().catch((e) => console.log("Autoplay was prevented:", e));
      }, { once: true });
      return;
    }
    
    const hls = new Hls({
      debug: false, // Set to true for verbose logging if needed
      maxBufferLength: 120,
      maxBufferSize: 300 * 1024 * 1024,
      fragLoadingMaxRetry: 6,
      fragLoadingRetryDelay: 1000,
      // *** THE CRITICAL FIX ***
      // Use the passed startTime. If it's 0 or less, Hls.js defaults to -1 (auto-start).
      startPosition: startTime > 0 ? startTime : -1,
    });

    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      videoRef.current.play().catch((e) => console.log("Autoplay was prevented:", e));
    });

    hls.on(Hls.Events.FRAG_BUFFERED, (event, data) => {
      if (onFragBuffered) onFragBuffered(data);
      if (videoRef.current) {
        videoRef.current.dispatchEvent(new Event('progress'));
      }
    });

    hls.on(Hls.Events.ERROR, (event, data) => {
      console.warn('[HLS.js Error]', data.details, data);
      if (data.fatal) {
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            console.log("Network error, attempting to restart load...");
            hls.startLoad();
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            console.log("Media error, attempting media recovery...");
            hls.recoverMediaError();
            break;
          default:
            console.error("Unrecoverable HLS error, destroying instance.");
            hls.destroy();
            break;
        }
      }
    });

    hls.loadSource(src);
    hls.attachMedia(videoRef.current);
    hlsRef.current = hls;

    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
      }
    };
  }, [videoRef, src, startTime, onFragBuffered]); // Add startTime to dependency array

  return null;
}

export default useHls;