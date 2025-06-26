import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

const SettingsSharing = () => {
  const { mediaServerApi, activeServer } = useAuth();
  const [invitee, setInvitee] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleInvite = async (e) => {
    e.preventDefault();
    if (!invitee) {
      setError('Please enter a username or email to invite.');
      return;
    }
    setError('');
    setMessage('');
    setIsLoading(true);

    try {
      const response = await mediaServerApi.post('/sharing/invite', {
        invite_request: {
          server_unique_id: activeServer.server_unique_id,
          invitee_identifier: invitee
        }
      });
      setMessage(response.data.message || 'Invitation sent successfully!');
      setInvitee('');
    } catch (err) {
      let errorMessage = 'Failed to send invitation.';
      if (err.response?.data?.detail) {
        if (Array.isArray(err.response.data.detail)) {
          errorMessage = err.response.data.detail.map(d => d.msg).join(', ');
        } else {
          errorMessage = err.response.data.detail;
        }
      }
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="info-panel">
      <h3>Share Server Access</h3>
      <p style={{ color: '#aaa' }}>Invite another Lantern user to access your server '{activeServer?.friendly_name}'.</p>
      
      {error && <p className="error">{error}</p>}
      {message && <p style={{ color: '#28a745' }}>{message}</p>}
      
      <form onSubmit={handleInvite}>
        <input
          type="text"
          value={invitee}
          onChange={e => setInvitee(e.target.value)}
          placeholder="Username or Email to invite"
          required
        />
        <button type="submit" disabled={isLoading}>
          {isLoading ? 'Sending...' : 'Send Invitation'}
        </button>
      </form>
    </div>
  );
};

export default SettingsSharing;