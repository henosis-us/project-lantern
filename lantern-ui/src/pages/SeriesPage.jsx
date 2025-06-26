import React, { useEffect, useState } from 'react';
// DELETED: import api from '../api/api';
import { useAuth } from '../context/AuthContext'; // NEW: Import useAuth to get mediaServerApi

import Header from '../components/Header';
import SeriesCard from '../components/SeriesCard';
import SeasonModal from '../components/SeasonModal';

export default function SeriesPage() {
  const [series, setSeries] = useState([]);
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState(null);
  const [status, setStatus] = useState('Loading series…');

  // NEW: Get the dynamic mediaServerApi instance from the context
  const { mediaServerApi } = useAuth();

  useEffect(() => {
    // NEW: Ensure mediaServerApi is available before making the call
    if (!mediaServerApi) {
      setStatus('No media server selected or connected.');
      return;
    }

    setStatus('Loading series…');
    // Use mediaServerApi for the call
    mediaServerApi.get('/library/series')
      .then((r) => {
        setSeries(r.data);
        setStatus('');
      })
      .catch(() => setStatus('Failed to load series.'));
  }, [mediaServerApi]); // NEW: Add mediaServerApi to dependency array

  const list = !filter
    ? series
    : series.filter((s) => s.title.toLowerCase().includes(filter.toLowerCase()));

  return (
    <>
      {/* Note: Header component might also need `mediaServerApi` if it performs API calls */}
      <Header onSearchChange={setFilter} /> 
      {status && !list.length ? (
        <p id="status-message">{status}</p>
      ) : (
        <div id="library">
          {list.map((s) => (
            <SeriesCard key={s.id} series={s} onSelect={setSelected} />
          ))}
        </div>
      )}
      {selected && (
        <SeasonModal series={selected} onClose={() => setSelected(null)} />
      )}
    </>
  );
}