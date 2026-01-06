import React, { useEffect, useMemo, useState } from 'react';
import { useAuth } from '../context/AuthContext';

export default function SeriesFilesTechModal({ series, initialSeason = null, onClose }) {
  const { mediaServerApi } = useAuth();
  const [status, setStatus] = useState('loading');
  const [episodes, setEpisodes] = useState([]);
  const [selectedSeason, setSelectedSeason] = useState(initialSeason);
  const [selectedEpisode, setSelectedEpisode] = useState(null);
  const [sidecarSubs, setSidecarSubs] = useState([]);
  const [subsStatus, setSubsStatus] = useState('idle');

  useEffect(() => {
    if (!series || !mediaServerApi) return;
    setStatus('loading');
    setEpisodes([]);
    setSelectedEpisode(null);
    setSidecarSubs([]);

    mediaServerApi.get(`/library/series/${series.id}/episodes/tech`)
      .then((res) => {
        const eps = res.data || [];
        setEpisodes(eps);
        if (selectedSeason == null) {
          const seasons = [...new Set(eps.map((e) => e.season))].sort((a, b) => a - b);
          if (seasons.length) setSelectedSeason(seasons[0]);
        }
        setStatus('loaded');
      })
      .catch((err) => {
        console.error('Failed to fetch episode tech info:', err);
        setStatus('error');
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, mediaServerApi]);

  useEffect(() => {
    if (!selectedEpisode || !mediaServerApi) return;
    setSubsStatus('loading');
    setSidecarSubs([]);
    mediaServerApi.get(`/library/episodes/${selectedEpisode.id}/sidecar_subtitles`)
      .then((res) => setSidecarSubs(res.data || []))
      .catch((err) => {
        console.error('Failed to fetch sidecar subtitles for episode:', err);
        setSidecarSubs([]);
      })
      .finally(() => setSubsStatus('loaded'));
  }, [selectedEpisode, mediaServerApi]);

  const seasons = useMemo(() => {
    const s = [...new Set(episodes.map((e) => e.season))].sort((a, b) => a - b);
    return s;
  }, [episodes]);

  const filteredEpisodes = useMemo(() => {
    if (selectedSeason == null) return episodes;
    return episodes.filter((e) => e.season === selectedSeason);
  }, [episodes, selectedSeason]);

  const triggerDownload = (url) => {
    const a = document.createElement('a');
    a.href = url;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const downloadEpisodeAndSubs = async () => {
    if (!selectedEpisode) return;
    const jwt = localStorage.getItem('jwt');
    if (!jwt) return alert('Not logged in.');

    const base = mediaServerApi?.defaults?.baseURL;
    if (!base) return alert('No server selected.');

    triggerDownload(`${base}/download/episode/${selectedEpisode.id}?token=${encodeURIComponent(jwt)}`);
    (sidecarSubs || []).forEach((s) => {
      triggerDownload(`${base}/download/episode/${selectedEpisode.id}/subtitle/${encodeURIComponent(s.filename)}?token=${encodeURIComponent(jwt)}`);
    });
  };

  return (
    <div className="files-tech-modal-overlay" onClick={onClose}>
      <div className="files-tech-modal" onClick={(e) => e.stopPropagation()}>
        <div className="files-tech-modal-header">
          <h2>Files & Tech Info - {series?.title}</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        {status === 'loading' && <p>Loading episode info...</p>}
        {status === 'error' && <p>Failed to load episode tech info.</p>}

        {status === 'loaded' && (
          <>
            <div className="files-tech-controls">
              <label>
                Season
                <select value={selectedSeason ?? ''} onChange={(e) => setSelectedSeason(parseInt(e.target.value, 10))}>
                  {seasons.map((s) => (
                    <option key={s} value={s}>{s === 0 ? 'Specials' : `Season ${s}`}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="files-tech-grid">
              <div className="files-tech-episode-list">
                <h3>Episodes</h3>
                <ul>
                  {filteredEpisodes.map((e) => (
                    <li
                      key={e.id}
                      className={selectedEpisode?.id === e.id ? 'active' : ''}
                      onClick={() => setSelectedEpisode(e)}
                    >
                      <span className="ep-code">S{String(e.season).padStart(2, '0')}E{String(e.episode).padStart(2, '0')}</span>
                      <span className="ep-title">{e.title || 'Untitled'}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="files-tech-details">
                {!selectedEpisode ? (
                  <p>Select an episode to view file details.</p>
                ) : (
                  <>
                    <h3>Selected Episode</h3>
                    <p><strong>File Path:</strong> <code>{selectedEpisode.filepath}</code></p>
                    <p>
                      <strong>Streaming:</strong>
                      <span className={`stream-status ${selectedEpisode.is_direct_play ? 'direct-play' : 'transcode'}`}>
                        {selectedEpisode.is_direct_play ? 'Direct Play Compatible' : 'Requires Transcoding'}
                      </span>
                    </p>
                    <p><strong>Video Codec:</strong> <code>{selectedEpisode.video_codec || 'Unknown'}</code></p>
                    <p><strong>Audio Codec:</strong> <code>{selectedEpisode.audio_codec || 'Unknown'}</code></p>

                    <div className="admin-actions">
                      <button onClick={downloadEpisodeAndSubs}>Download Video + Sidecar Subtitles</button>
                    </div>

                    <div className="sidecar-subs">
                      <h4>Sidecar Subtitle Files</h4>
                      {subsStatus === 'loading' ? (
                        <p>Loading subtitle files...</p>
                      ) : sidecarSubs.length ? (
                        <ul>
                          {sidecarSubs.map((s) => (
                            <li key={s.filename}><code>{s.filename}</code></li>
                          ))}
                        </ul>
                      ) : (
                        <p>No matching subtitle files found next to this episode.</p>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
