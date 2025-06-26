import React, { useEffect, useState } from 'react';
// DELETED: import api from '../api/api';
import { useAuth } from '../context/AuthContext'; // NEW: Import useAuth to get mediaServerApi
import EpisodeList from './EpisodeList';

// Helper to format rating, consistent with MovieDetailsModal
const formatRating = (rating) => (rating ? rating.toFixed(1) : 'N/A');

export default function SeasonModal({ series, onClose, onPlayEpisode }) {
  // Get the dynamic mediaServerApi instance from the context
  const { mediaServerApi } = useAuth(); // NEW: Get mediaServerApi from context
  
  // State for detailed series info, fetched after modal opens
  const [seriesDetails, setSeriesDetails] = useState(null);
  // State for episodes and UI
  const [allEpisodes, setAllEpisodes] = useState([]);
  const [seasons, setSeasons] = useState([]);
  const [selectedSeason, setSelectedSeason] = useState(null);
  const [status, setStatus] = useState('loading');

  // Effect to fetch detailed series information
  useEffect(() => {
    // NEW: Add check for mediaServerApi
    if (!series || !mediaServerApi) return; 

    setSeriesDetails(null); // Reset on new series selection
    // Use mediaServerApi for the call
    mediaServerApi.get(`/library/series/${series.id}/details`)
      .then(res => {
        setSeriesDetails(res.data);
      })
      .catch(err => {
        console.error("Failed to fetch series details:", err);
        // Fallback to the basic info from the prop if the details fetch fails
        setSeriesDetails(series);
      });
  }, [series, mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  // Effect to fetch the list of all episodes for the series
  useEffect(() => {
    // NEW: Add check for mediaServerApi
    if (!series || !mediaServerApi) return;

    setStatus('loading');
    // Use mediaServerApi for the call
    mediaServerApi.get(`/library/series/${series.id}/episodes`)
      .then((r) => {
        const episodesData = r.data || [];
        setAllEpisodes(episodesData);
        const uniqueSeasons = [...new Set(episodesData.map(e => e.season))].sort((a, b) => a - b);
        setSeasons(uniqueSeasons);
        if (uniqueSeasons.length > 0) {
          // Attempt to select the season with the latest watched episode first, or season 1
          // This logic would ideally come from the history API, but for simplicity,
          // we'll just pick the first season or a common one like '1' if available.
          setSelectedSeason(uniqueSeasons[0]);
        }
        setStatus('loaded');
      })
      .catch(() => {
        setStatus('error');
      });
  }, [series, mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  // When an episode is clicked, tell the parent to play it AND close this modal.
  const handlePlayEpisode = (episode) => {
    if (onPlayEpisode) {
      onPlayEpisode(episode); // Tell parent to start playing
    }
    onClose(); // Close this modal so the player is visible
  };

  // Use detailed info if available, otherwise fall back to the basic prop
  const displayData = seriesDetails || series;
  const genres = displayData.genres ? displayData.genres.split(', ') : [];
  const rating = displayData.vote_average ? formatRating(displayData.vote_average) : 'N/A';
  const year = displayData.first_air_date ? `(${displayData.first_air_date.substring(0, 4)})` : '';
  
  // Note: backdrop_path is for series details, poster_path is usually for thumbnails.
  // Assuming backdrop_path is available from seriesDetails for hero image.
  const heroStyle = displayData.backdrop_path
    ? { backgroundImage: `url(https://image.tmdb.org/t/p/w1280${displayData.backdrop_path})` }
    : { backgroundColor: '#222' };
  
  const posterArt = displayData.poster_path
    ? `https://image.tmdb.org/t/p/w500${displayData.poster_path}`
    : 'https://via.placeholder.com/500x750.png?text=No+Poster';

  const episodesForSelectedSeason = allEpisodes.filter(e => e.season === selectedSeason);

  return (
    <div className="series-detail-page">
      <div className="series-hero" style={heroStyle}>
        <button className="back-button" onClick={onClose}>←</button>
        <div className="series-hero-content">
          <img src={posterArt} alt={`${displayData.title} Poster`} className="series-hero-poster" />
          <div className="series-hero-info">
            <h1>{displayData.title} <span className="year">{year}</span></h1>
            
            <div className="meta-info" style={{ marginBottom: '1rem' }}>
              {rating !== 'N/A' && (
                <span className="meta-badge rating">⭐ {rating}</span>
              )}
              {genres.map(genre => (
                <span key={genre} className="meta-badge genre">{genre}</span>
              ))}
            </div>
            
            <p>{displayData.overview || 'No overview available.'}</p>
          </div>
        </div>
      </div>
      <div className="series-browser">
        {status === 'loading' && <p>Loading episodes...</p>}
        {status === 'error' && <p>Could not load episode information.</p>}
        {status === 'loaded' && (
          <>
            <div className="season-tabs">
              {seasons.length > 0 ? seasons.map((s) => (
                <button
                  key={s}
                  className={selectedSeason === s ? 'active' : ''}
                  onClick={() => setSelectedSeason(s)}
                >
                  {s === 0 ? 'Specials' : `Season ${s}`}
                </button>
              )) : <p>No seasons found.</p>}
            </div>
            <EpisodeList
              episodes={episodesForSelectedSeason}
              onPlay={handlePlayEpisode}
            />
          </>
        )}
      </div>
    </div>
  );
}