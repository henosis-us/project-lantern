// src/components/MiniPlayer.jsx
import React from 'react';

function MiniPlayer({ title, onRestore }) {
  return (
    <div id="mini-player">
      <p id="mini-player-title">{`Now Playing: ${title}`}</p>
      <div className="player-controls">
        <button id="restore-btn" title="Restore" onClick={onRestore}>^</button>
      </div>
    </div>
  );
}

export default MiniPlayer;