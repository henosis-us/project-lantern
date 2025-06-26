import React, { useState, useEffect, useMemo, useCallback } from 'react';
// DELETED: import api, { getContinue } from '../api/api';
import { useAuth } from '../context/AuthContext'; // NEW: Import useAuth to get mediaServerApi

import Header from '../components/Header';
import MovieCard from '../components/MovieCard';
import SeriesCard from '../components/SeriesCard';
import MovieDetailsModal from '../components/MovieDetailsModal'; // Updated import
import SeasonModal from '../components/SeasonModal';
import PlayerOverlay from '../components/PlayerOverlay';

function LibraryPage() {
  // --- State Management ---
  const [activeTab, setActiveTab] = useState('movies'); // 'movies' or 'tv'
  const [movies, setMovies] = useState([]);
  const [series, setSeries] = useState([]);
  const [continueList, setContinueList] = useState({ movies: [], episodes: [] });
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);

  // Modal and Player State
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [selectedSeries, setSelectedSeries] = useState(null);
  const [playingItem, setPlayingItem] = useState(null); // Can be a movie or an episode

  // NEW: Get the dynamic mediaServerApi instance from the context
  const { mediaServerApi } = useAuth();

  // --- Data Fetching ---
  const fetchLibraryData = useCallback(async () => {
    // NEW: Ensure mediaServerApi is available before making calls
    if (!mediaServerApi) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    try {
      // Use mediaServerApi for all calls to the media server
      const [moviesRes, seriesRes, continueRes] = await Promise.all([
        mediaServerApi.get('/library/movies'),
        mediaServerApi.get('/library/series'),
        mediaServerApi.get('/history/continue/'), // Use mediaServerApi for getContinue
      ]);
      setMovies(moviesRes.data || []);
      setSeries(seriesRes.data || []);
      setContinueList(continueRes.data || { movies: [], episodes: [] });
    } catch (error) {
      console.error("Failed to fetch library data:", error);
    } finally {
      setIsLoading(false);
    }
  }, [mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  useEffect(() => {
    fetchLibraryData();
  }, [fetchLibraryData]);

  // --- Event Handlers ---
  const handleScan = async () => {
    // NEW: Ensure mediaServerApi is available
    if (!mediaServerApi) {
      alert("No media server selected or connected.");
      return;
    }

    setIsScanning(true);
    try {
      // Use mediaServerApi for the scan request
      await mediaServerApi.post('/library/scan');
      // Poll for completion or just wait a fixed time and refresh
      setTimeout(() => {
        fetchLibraryData();
        setIsScanning(false);
      }, 5000); // Simple refresh after 5s
    } catch (error) {
      console.error("Failed to start scan:", error);
      setIsScanning(false);
    }
  };

  // --- Memoized Filtering and Grouping ---
  const filteredMovies = useMemo(() =>
    movies.filter(m => m.title.toLowerCase().includes(searchQuery.toLowerCase())),
    [movies, searchQuery]
  );

  const filteredSeries = useMemo(() =>
    series.filter(s => s.title.toLowerCase().includes(searchQuery.toLowerCase())),
    [series, searchQuery]
  );

  const movieGroups = useMemo(() => {
    const groups = {};
    filteredMovies.forEach(movie => {
      const key = movie.parent_id || movie.id;
      if (!groups[key]) {
        groups[key] = { rep: null, items: [] };
      }
      groups[key].items.push(movie);
      if (movie.id === key) {
        groups[key].rep = movie;
      }
    });
    return Object.values(groups).map(g => {
      if (!g.rep) g.rep = g.items[0]; // Fallback rep
      return g;
    });
  }, [filteredMovies]);

  // --- Rendering ---
  return (
    <>
      <Header
        onSearchChange={setSearchQuery}
        onScan={handleScan}
        isScanning={isScanning}
        activeTab={activeTab}
        onNavClick={setActiveTab}
      />
      <main id="main-content" className={isLoading ? 'loading' : ''}>
        {/* Modals and Overlays */}
        {playingItem && <PlayerOverlay movie={playingItem} onClose={() => setPlayingItem(null)} />}
        {selectedGroup && (
          <MovieDetailsModal // Updated to use MovieDetailsModal
            group={selectedGroup}
            onClose={() => setSelectedGroup(null)}
            onPlay={setPlayingItem}
            onLibraryRefresh={fetchLibraryData}
          />
        )}
        {selectedSeries && (
          <SeasonModal
            series={selectedSeries}
            onClose={() => setSelectedSeries(null)}
            onPlayEpisode={setPlayingItem}
          />
        )}

        {/* Continue Watching Section */}
        {(continueList.movies.length > 0 || continueList.episodes.length > 0) && (
          <div className="continue-row">
            <h2>Continue Watching</h2>
            <div className="movie-row">
              {continueList.movies.map(movie => (
                <div key={`continue-movie-${movie.id}`} className="movie-item-wrapper">
                  <MovieCard
                    group={{ rep: movie, items: [movie] }}
                    onSelect={() => setPlayingItem(movie)}
                    progress={movie.position_seconds / movie.duration_seconds}
                  />
                </div>
              ))}
              {continueList.episodes.map(ep => (
                <div key={`continue-ep-${ep.id}`} className="movie-item-wrapper">
                  <SeriesCard
                    series={{
                      id: ep.series_id,
                      title: ep.series_title,
                      poster_path: ep.series_poster_path // Assuming this is available in the continue list data
                    }}
                    subtitle={`S${ep.season} E${ep.episode}`}
                    progress={ep.position_seconds / ep.duration_seconds}
                    onSelect={() => setPlayingItem(ep)}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Main Library Grid */}
        <div id="library">
          {activeTab === 'movies' && movieGroups.map(group => (
            <MovieCard key={group.rep.id} group={group} onSelect={setSelectedGroup} />
          ))}
          {activeTab === 'tv' && filteredSeries.map(seriesItem => (
            <SeriesCard key={seriesItem.id} series={seriesItem} onSelect={setSelectedSeries} />
          ))}
        </div>
      </main>
    </>
  );
}

export default LibraryPage;