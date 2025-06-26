// src/hooks/useHls.jsx
import { useEffect, useRef } from 'react';
import Hls from 'hls.js';

function useHls(videoRef, src, onFragBuffered) {
  const hlsRef = useRef(null);

  useEffect(() => {
    if (!videoRef.current || !src) return;

    // Destroy previous HLS instance if it exists
    if (hlsRef.current) {
      hlsRef.current.destroy();
    }

    // Handle native HLS support (e.g., Safari)
    if (videoRef.current.canPlayType('application/vnd.apple.mpegurl') && !Hls.isSupported()) {
      videoRef.current.src = src;
      videoRef.current.addEventListener('loadedmetadata', () => {
        videoRef.current.play().catch((e) => console.log("Autoplay was prevented:", e));
      });
      return; // No further action for native HLS
    }

    // HLS.js setup for other browsers
    const hls = new Hls({
      debug: true, // Enable verbose logging for debugging
      maxBufferLength: 120, // Buffer up to 30 seconds of video
      maxBufferSize: 300 * 1024 * 1024, // 60 MB buffer size
      fragLoadingMaxRetry: 10, // Increase max retries for fragment loading
      fragLoadingRetryDelay: 800, // Set retry delay to 800ms for faster recovery
      startPosition: -1, // Let HLS.js handle the starting position automatically
    });

    // Add diagnostic logging for fragment events
    ['FRAG_LOADING', 'FRAG_LOADED'].forEach(evt => {
      hls.on(Hls.Events[evt], (event, data) => {
        console.log(evt, data.frag?.sn, data);
      });
    });

    // Existing event handlers
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      videoRef.current.play().catch((e) => console.log("Autoplay was prevented:", e));
    });

    hls.on(Hls.Events.FRAG_BUFFERED, () => {
      if (onFragBuffered) onFragBuffered();
      
      // Emit a native progress event to trigger onProgress in PlayerOverlay
      if (videoRef.current) {
        videoRef.current.dispatchEvent(new Event('progress'));
      }
    });

    hls.on(Hls.Events.ERROR, (event, data) => {
      console.warn('[HLS.js Error]', data.details, data); // Log errors with details
      if (data.fatal) {
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            console.log("Network error detected, attempting to restart load...");
            hls.startLoad(); // Attempt to restart the load process
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            console.log("Media error detected, attempting media recovery...");
            hls.recoverMediaError(); // Try to recover from media errors
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

    // Cleanup function to destroy HLS instance on unmount or src change
    return () => {
      if (hlsRef.current) {
        hlsRef.current.destroy();
      }
    };
  }, [videoRef, src, onFragBuffered]);

  return null; // This hook doesn't render any UI
}

export default useHls;