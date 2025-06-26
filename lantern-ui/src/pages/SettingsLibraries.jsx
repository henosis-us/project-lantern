import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';

const SettingsLibraries = () => {
  const { mediaServerApi } = useAuth();
  const [libraries, setLibraries] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  
  // Form state for new library
  const [newName, setNewName] = useState('');
  const [newPath, setNewPath] = useState('');
  const [newType, setNewType] = useState('movie');

  const fetchLibraries = async () => {
    if (!mediaServerApi) return;
    try {
      setIsLoading(true);
      const { data } = await mediaServerApi.get('/libraries');
      setLibraries(data);
    } catch (err) {
      setError('Failed to fetch libraries.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLibraries();
  }, [mediaServerApi]);

  const handleAddLibrary = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await mediaServerApi.post('/libraries', { library: { name: newName, path: newPath, type: newType } });
      setNewName('');
      setNewPath('');
      await fetchLibraries(); // Refresh the list
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to add library.');
    }
  };

  const handleDelete = async (id) => {
    if (window.confirm('Are you sure you want to delete this library?')) {
      try {
        await mediaServerApi.delete(`/libraries/${id}`);
        await fetchLibraries(); // Refresh the list
      } catch (err) {
        setError('Failed to delete library.');
      }
    }
  };

  if (isLoading) return <p>Loading libraries...</p>;

  return (
    <div className="info-panel">
      <h3>Manage Libraries</h3>
      {error && <p className="error">{error}</p>}
      
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {libraries.map(lib => (
          <li key={lib.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#2a2a2a', padding: '10px', borderRadius: '5px', marginBottom: '10px' }}>
            <div>
              <strong>{lib.name}</strong> <span className="badge">{lib.type}</span>
              <p style={{ margin: '5px 0 0', color: '#aaa', fontSize: '14px' }}>{lib.path}</p>
            </div>
            <button onClick={() => handleDelete(lib.id)} style={{ background: '#dc3545' }}>Delete</button>
          </li>
        ))}
      </ul>
      
      <form onSubmit={handleAddLibrary} style={{ marginTop: '20px', borderTop: '1px solid #444', paddingTop: '20px' }}>
        <h4>Add New Library</h4>
        <input type="text" value={newName} onChange={e => setNewName(e.target.value)} placeholder="Library Name (e.g., Movies)" required />
        <input type="text" value={newPath} onChange={e => setNewPath(e.target.value)} placeholder="Full Path on Server (e.g., /data/movies)" required />
        <select value={newType} onChange={e => setNewType(e.target.value)}>
          <option value="movie">Movies</option>
          <option value="tv">TV Shows</option>
        </select>
        <button type="submit">Add Library</button>
      </form>
    </div>
  );
};

export default SettingsLibraries;