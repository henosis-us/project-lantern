// src/pages/ClaimServerPage.jsx
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { identityApi } from '../api/api';
import axios from 'axios'; // Import axios

const ClaimServerPage = () => {
  const [serverUrl, setServerUrl] = useState('http://localhost:8000');
  const [token, setToken] = useState('');
  const [friendlyName, setFriendlyName] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isFetching, setIsFetching] = useState(false); // For fetching claim info
  const navigate = useNavigate();
  const { refreshServers, selectServer, availableServers } = useAuth();
  const [initialServerIds, setInitialServerIds] = useState(new Set());

  useEffect(() => {
    if (availableServers !== null && initialServerIds.size === 0) {
      setInitialServerIds(new Set(availableServers.map(s => s.server_unique_id)));
    }
  }, [availableServers, initialServerIds.size]);

  // NEW: Function to fetch claim info from the server
  const fetchClaimInfo = async () => {
    if (!serverUrl) {
      setError('Please enter the server address first.');
      return;
    }
    setIsFetching(true);
    setError('');
    try {
      // Construct the full URL for the new endpoint
      const url = `${serverUrl.replace(/\/$/, '')}/server/claim-info`;
      const response = await axios.get(url);
      const { claim_token } = response.data;
      if (claim_token) {
        setToken(claim_token);
      } else {
        setError('Could not fetch claim token. The server might already be claimed.');
      }
    } catch (err) {
      const errorMsg = err.response?.data?.detail || 'Failed to connect to the server. Check the address and ensure it is running.';
      setError(errorMsg);
    } finally {
      setIsFetching(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    // MODIFIED: Check for all three fields (URL, Token, Friendly Name)
    if (!token || !friendlyName || !serverUrl) {
      setError('Please fill in all fields.');
      return;
    }
    setIsLoading(true);
    setError('');

    try {
      // MODIFIED: Include the serverUrl in the payload sent to the Identity Service
      await identityApi.post('/servers/claim', {
        claim_token: token,
        friendly_name: friendlyName,
        url: serverUrl, // This is the crucial new field
      });

      // On successful claim, refresh the list of servers the user has access to
      // Use the returned value from our updated refreshServers function.
      const newServerList = await refreshServers();

      // Find the server in the new list that was not in the old list.
      const newServer = newServerList.find(s => !initialServerIds.has(s.server_unique_id));

      // Automatically select the new server to make it active.
      if (newServer) {
        selectServer(newServer);
      }

      // Navigate directly to the settings page for immediate configuration.
      navigate('/settings');
    } catch (err) {
      // Provide a user-friendly error message
      const errorMsg = err.response?.data?.detail || 'Failed to claim server. The token may be invalid or expired.';
      setError(errorMsg);
      setIsLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h2>Claim Your Server</h2>
        <p style={{ color: '#aaa', textAlign: 'center', marginBottom: '20px' }}>
          Enter the address of your new server to automatically fetch the claim token.
        </p>
        {error && <p className="error">{error}</p>}

        <div className="server-url-input">
          <input
            type="text"
            placeholder="Server Address (e.g., http://192.168.1.10:8000)"
            value={serverUrl}
            onChange={(e) => setServerUrl(e.target.value)}
            required
          />
          <button type="button" onClick={fetchClaimInfo} disabled={isFetching}>
            {isFetching ? '...' : 'Fetch'}
          </button>
        </div>

        <input
          type="text"
          placeholder="Claim Token (will be auto-filled)"
          value={token}
          onChange={(e) => setToken(e.target.value.toUpperCase())}
          required
        />
        <input
          type="text"
          placeholder="Friendly Name (e.g., Living Room TV)"
          value={friendlyName}
          onChange={(e) => setFriendlyName(e.target.value)}
          required
        />

        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Claiming...' : 'Claim Server'}
        </button>

        <div className="switch-link" style={{ marginTop: '25px' }}>
          {/* Link to go back to the previous page */}
          <a href="#" onClick={() => navigate(-1)}>Back</a>
        </div>
      </form>
    </div>
  );
};

export default ClaimServerPage;