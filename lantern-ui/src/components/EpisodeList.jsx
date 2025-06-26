import React from 'react';

// The base URL of your backend server where the static files are hosted.
const API_BASE_URL = 'http://localhost:8000';

function EpisodeList({ episodes, onPlay }) {
  if (!episodes || episodes.length === 0) {
    return <p>No episodes found for this season.</p>;
  }

  return (
    <ul className="episode-list">
      {episodes.map(episode => {
        // Construct the full, absolute URL for the image
        const imageUrl = episode.still_path
          ? episode.still_path.startsWith('http')
            ? episode.still_path
            : `${API_BASE_URL}/static/${episode.still_path}`
          : null;

        return (
          <li key={episode.id} className="episode-list-item" onClick={() => onPlay(episode)}>
            <div className="episode-thumbnail">
              {imageUrl ? (
                <img 
                  src={imageUrl}
                  alt={`Thumbnail for ${episode.title || 'episode'}`}
                  // The onError logic is still good to have as a fallback
                  onError={(e) => {
                    e.target.style.display = 'none';
                    const playIcon = e.target.parentElement.querySelector('.play-icon');
                    if (playIcon) playIcon.style.display = 'flex';
                  }}
                />
              ) : null}
              {/* This span acts as a fallback if the image fails or doesn't exist */}
              <span 
                className="play-icon" 
                style={{ display: imageUrl ? 'none' : 'flex' }}
              >
                ▶
              </span>
            </div>
            <div className="episode-info">
              <h3>{episode.episode}. {episode.title || 'Untitled'}</h3>
              <p>{episode.overview || 'No description available.'}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export default EpisodeList;