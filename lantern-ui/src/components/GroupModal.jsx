import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/api';

function GroupModal({ group, onClose, onPlay, onLibraryRefresh }) {
  const { isOwner } = useAuth();
  const [overview, setOverview] = useState('Loading description...');

  useEffect(() => {
    if (!group) return;
    api.get(`/library/movies/${group.rep.id}/details`)
      .then(res => setOverview(res.data.overview || 'No description available.'))
      .catch(() => setOverview('Could not load description.'));
  }, [group]);

  if (!group) return null;

  const handleFixMetadata = async (movie) => {
    const query = prompt("Search TMDb for…", movie.title);
    if (!query) return;

    try {
      const searchRes = await api.get(`/tmdb/search?q=${encodeURIComponent(query)}`);
      const list = searchRes.data;
      if (!list.length) return alert("No TMDb results found.");

      const choices = list.slice(0, 5).map((x, i) => `${i + 1}) ${x.title} (${x.release_date || 'n/a'})`).join('\n');
      const pickStr = prompt(`Select match:\n${choices}\n0) Cancel`, "1");
      const pick = parseInt(pickStr, 10);
      if (!pick || pick < 1 || pick > list.length) return;

      const tmdb_id = list[pick - 1].id;
      await api.post(`/library/movies/${movie.id}/set_tmdb`, { tmdb_id });
      alert("Metadata updated! Refreshing library.");
      onLibraryRefresh();
      onClose();
    } catch (e) {
      console.error(e);
      alert("Error during TMDb search or update.");
    }
  };

  const handleAssignParent = async (childId, parentId) => {
    try {
      await api.patch(`/library/movies/${childId}/parent`, { parent_id: parentId });
      alert("Item grouped with main movie. Refreshing library.");
      onLibraryRefresh();
      onClose();
    } catch (e) {
      console.error(e);
      alert("Error grouping items.");
    }
  };

  return (
    <div id="group-modal" className="active">
      <h2 id="group-title">{group.rep.title}</h2>
      <p id="movie-overview">{overview}</p>
      <ul id="group-list">
        {group.items.map(item => (
          <li key={item.id}>
            <span>{item.title}</span>
            <div>
              <button onClick={() => { onPlay(item); onClose(); }}>Play</button>
              {!item.poster_path && isOwner && (
                <button onClick={() => handleFixMetadata(item)}>Fix Match</button>
              )}
              {item.id !== group.rep.id && item.parent_id == null && (
                <button onClick={() => handleAssignParent(item.id, group.rep.id)}>Group</button>
              )}
            </div>
          </li>
        ))}
      </ul>
      <button onClick={onClose}>Close</button>
    </div>
  );
}

export default GroupModal;