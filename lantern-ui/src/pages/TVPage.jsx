// src/pages/TVPage.jsx

import React, { useState, useEffect } from 'react';
// DELETED: import api from '../api/api';
import { useAuth } from '../context/AuthContext'; // NEW: Import useAuth
import SeriesCard from '../components/SeriesCard';
import SeasonModal from '../components/SeasonModal';

function TVPage() {
  const [seriesList, setSeriesList] = useState([]);
  const [selectedSeries, setSelectedSeries] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // NEW: Get the dynamic media server API client from the context
  const { mediaServerApi } = useAuth();

  useEffect(() => {
    // NEW: Don't run the fetch if the API client isn't ready
    if (!mediaServerApi) {
      setError("No media server is currently selected.");
      setIsLoading(false);
      return;
    }

    setError(null); // Clear previous errors
    setIsLoading(true);

    // MODIFIED: Use the mediaServerApi from context
    mediaServerApi.get('/library/series')
      .then(response => {
        // MODIFIED: Ensure response.data is an array. If not, use an empty array.
        setSeriesList(response.data || []);
      })
      .catch(err => {
        console.error("Failed to fetch series:", err);
        setError("Could not load TV shows. Please try again later.");
        setSeriesList([]); // Also clear list on error
      })
      .finally(() => {
        setIsLoading(false);
      });
  // MODIFIED: Add mediaServerApi to the dependency array
  }, [mediaServerApi]);

  const handleSelectSeries = (series) => {
    setSelectedSeries(series);
  };

  const handleCloseModal = () => {
    setSelectedSeries(null);
  };

  if (isLoading) {
    return <div className="content-area"><p>Loading TV shows...</p></div>;
  }

  if (error) {
    return <div className="content-area"><p style={{ color: 'red' }}>{error}</p></div>;
  }

  return (
    <div className="content-area">
      <div className="movie-grid">
        {seriesList.map(series => (
          <SeriesCard
            key={series.id}
            series={series}
            onSelect={() => handleSelectSeries(series)}
          />
        ))}
      </div>
      {selectedSeries && (
        <SeasonModal
          series={selectedSeries}
          onClose={handleCloseModal}
        />
      )}
    </div>
  );
}

export default TVPage;