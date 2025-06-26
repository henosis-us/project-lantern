import React from 'react';

export default function SeriesCard({ series, onSelect, subtitle = null, progress = null }) {
  const art = series.poster_path
    ? `https://image.tmdb.org/t/p/w500${series.poster_path}`
    : 'https://via.placeholder.com/500x750.png?text=No+Poster';

  return (
    <div className="movie-item" onClick={() => onSelect(series)}>
      <img src={art} alt={series.title} />
      {progress !== null && (
        <div className="progress-overlay" style={{
           height: '5px',
           background: `linear-gradient(to right, #007bff ${progress * 100}%, #5a5a5a ${progress * 100}%)`
         }}></div>
      )}
      <div className="movie-item-info">
        <p title={series.title}>{series.title}</p>
        {subtitle && (
            <span className="duration">{subtitle}</span>
        )}
      </div>
    </div>
  );
}