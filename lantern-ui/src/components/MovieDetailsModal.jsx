import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
// DELETED: import api from '../api/api';

// Helper function to format duration
const fmtDur = (s) => {
  if (!s) return '';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};

function MovieDetailsModal({ group, onClose, onPlay, onLibraryRefresh }) {
  // Get the dynamic mediaServerApi instance from the context
  const { isOwner, mediaServerApi } = useAuth(); 
  const [details, setDetails] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showInfoPanel, setShowInfoPanel] = useState(false);

  useEffect(() => {
    if (!group || !mediaServerApi) return; // <-- Add check for mediaServerApi

    setIsLoading(true);
    setDetails(null);
    setShowInfoPanel(false);

    // Fetch the full details using the dynamic API instance from the context
    mediaServerApi.get(`/library/movies/${group.rep.id}/details`)
      .then(res => {
        const movieData = res.data;
        console.log('Movie Details Fetched:', movieData);
        console.log('Video Codec:', movieData.video_codec);
        console.log('Audio Codec:', movieData.audio_codec);
        setDetails(movieData);
      })
      .catch(err => {
        console.error("Failed to fetch movie details:", err);
        console.log('Error fetching movie details for ID:', group.rep.id, 'Error:', err);
        setDetails({ ...group.rep, overview: "Could not load full details." });
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [group, mediaServerApi]); // <-- Add mediaServerApi to dependency array

  const handleFixMetadata = async (movie) => {
    const query = prompt("Search TMDb for…", movie.title);
    if (!query) return;

    try {
      // Use mediaServerApi for this call as well
      const searchRes = await mediaServerApi.get(`/tmdb/search?q=${encodeURIComponent(query)}`);
      const list = searchRes.data;
      if (!list.length) return alert("No TMDb results found.");
      
      const choices = list.slice(0, 5).map((x, i) => `${i + 1}) ${x.title} (${x.release_date || 'n/a'})`).join('\n');
      const pickStr = prompt(`Select match:\n${choices}\n0) Cancel`, "1");
      const pick = parseInt(pickStr, 10);
      if (!pick || pick < 1 || pick > list.length) return;
      const tmdb_id = list[pick - 1].id;
      
      // And here too
      await mediaServerApi.post(`/library/movies/${movie.id}/set_tmdb`, { tmdb_id });

      alert("Metadata updated! Refreshing library.");
      onLibraryRefresh();
      onClose();
    } catch (e) {
      console.error(e);
      alert("Error during TMDb search or update.");
    }
  };

  if (isLoading || !details) {
    return (
      <div id="movie-details-modal" className="active">
        <div className="modal-content-wrapper"><div className="loader"></div></div>
      </div>
    );
  }

  const representative = details;
  const posterArt = representative.poster_path
    ? `https://image.tmdb.org/t/p/w500${representative.poster_path}`
    : 'https://via.placeholder.com/500x750.png?text=No+Poster';
    
  const year = representative.release_date ? `(${representative.release_date.substring(0, 4)})` : '';
  const rating = representative.vote_average ? representative.vote_average.toFixed(1) : 'N/A';
  const genres = representative.genres ? representative.genres.split(', ') : [];

  return (
    <div id="movie-details-modal" className="active" onClick={onClose}>
      <div className="modal-content-wrapper" onClick={(e) => e.stopPropagation()}>
        <button className="close-btn" onClick={onClose}>×</button>
        
        <div className="details-content">
          <div className="details-poster">
            <img src={posterArt} alt={`Poster for ${representative.title}`} />
          </div>
          <div className="details-info">
            <h1>{representative.title} <span className="year">{year}</span></h1>
            
            <div className="meta-info">
              {rating !== 'N/A' && (
                <span className="meta-badge rating">⭐ {rating}</span>
              )}
              <span className="meta-badge duration">{fmtDur(representative.duration_seconds)}</span>
              {genres.map(genre => (
                <span key={genre} className="meta-badge genre">{genre}</span>
              ))}
            </div>

            <h3>Overview</h3>
            <p className="overview">{representative.overview || 'No description available.'}</p>
            
            <div className="versions-list">
              <h3>Available Versions</h3>
              <ul>
                {group.items.map(item => (
                  <li key={item.id}>
                    <span>{item.title}</span>
                    <button onClick={() => { onPlay(item); onClose(); }}>Play</button>
                  </li>
                ))}
              </ul>
            </div>
            
            {isOwner && (
              <div className="owner-actions">
                <button className="info-toggle-btn" onClick={() => setShowInfoPanel(!showInfoPanel)}>
                  {showInfoPanel ? 'Hide File & Tech Info' : 'Show File & Tech Info'}
                </button>
              </div>
            )}
          </div>
        </div>
        
        {isOwner && showInfoPanel && (
          <div className="info-panel">
            <h3>Technical & File Information</h3>
            <div className="tech-details">
                <p><strong>File Path:</strong> <code>{representative.filepath}</code></p>
                <p>
                  <strong>Streaming:</strong> 
                  <span className={`stream-status ${representative.is_direct_play ? 'direct-play' : 'transcode'}`}>
                    {representative.is_direct_play ? 'Direct Play Compatible' : 'Requires Transcoding'}
                  </span>
                </p>
                <p><strong>Video Codec:</strong> <code>{representative.video_codec || 'Unknown'}</code></p>
                <p><strong>Audio Codec:</strong> <code>{representative.audio_codec || 'Unknown'}</code></p>
            </div>
            <div className="admin-actions">
                <button onClick={() => handleFixMetadata(representative)}>Fix Match...</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default MovieDetailsModal;