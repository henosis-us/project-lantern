import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const ServerSelectorPage = () => {
  const { availableServers, selectServer, logout } = useAuth();

  return (
    <div className="auth-page">
      <div className="auth-form" style={{ maxWidth: '500px', textAlign: 'center' }}>
        <h2>Select a Server</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', margin: '20px 0' }}>
          {availableServers.map((server) => (
            <button
              key={server.server_unique_id}
              onClick={() => selectServer(server)}
              style={{ padding: '15px' }}
            >
              {server.friendly_name}
              {server.is_owner && <span className="badge" style={{ marginLeft: '10px'}}>Owner</span>}
            </button>
          ))}
        </div>
        
        <Link to="/claim">
            <button style={{ width: '100%', background: '#333', marginTop: '10px' }}>
                + Claim a New Server
            </button>
        </Link>
        
        <div className="switch-link" style={{ marginTop: '25px' }}>
          <a href="#" onClick={logout}>Log Out</a>
        </div>
      </div>
    </div>
  );
};

export default ServerSelectorPage;
