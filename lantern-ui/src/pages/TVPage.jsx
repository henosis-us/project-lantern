import React, { useState, useEffect } from 'react';
import api from '../api/api';
import SeriesCard from '../components/SeriesCard';
import SeasonModal from '../components/SeasonModal';

function TVPage() {
  const [seriesList, setSeriesList] = useState([]);
  const [selectedSeries, setSelectedSeries] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Fetch the list of all series when the component mounts
    api.get('/library/series')
      .then(response => {
        setSeriesList(response.data);
        setIsLoading(false);
      })
      .catch(err => {
        console.error("Failed to fetch series:", err);
        setError("Could not load TV shows. Please try again later.");
        setIsLoading(false);
      });
  }, []);

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