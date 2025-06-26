import React from 'react';

// Helper from original script
const fmtDur = (s) => {
  if (!s) return '';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};

// Update to accept onSelect callback and optional progress prop
function MovieCard({ group, onSelect, progress = null }) {
  const representative = group.rep;
  const art = representative.poster_path
    ? `https://image.tmdb.org/t/p/w500${representative.poster_path}`
    : 'https://via.placeholder.com/500x750.png?text=No+Poster';

  return (
    // Call onSelect when the card is clicked
    <div className="movie-item" onClick={() => onSelect(group)}>
      <img src={art} alt={`Poster for ${representative.title}`} />
      {progress !== null && (  // Conditionally render progress bar
        <div className="progress-overlay" style={{ 
          height: '5px', 
          background: `linear-gradient(to right, green ${progress * 100}%, grey ${progress * 100}%)` 
        }}></div>
      )}
      <div className="movie-item-info">
        <p title={representative.title}>
          {representative.title}
          {group.items.length > 1 && (
            <span className="badge">{group.items.length}</span>
          )}
        </p>
        <span className="duration">{fmtDur(representative.duration_seconds)}</span>
      </div>
    </div>
  );
}

export default MovieCard;