import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import SettingsLibraries from './SettingsLibraries';
import SettingsSharing from './SettingsSharing';

const SettingsPage = () => {
  const { activeServer } = useAuth();
  const [activeTab, setActiveTab] = useState('libraries');

  // Determine if the current user is the owner of the active server
  const isOwner = !!activeServer?.is_owner;

  if (!activeServer) {
    return (
      <div className="auth-page">
        <h2>No active server selected. <Link to="/">Go back</Link> to select one.</h2>
      </div>
    );
  }

  return (
    <div className="settings-page-container">
      <header className="settings-header">
        <div>
          <h1>Settings</h1>
          <p>
            Managing server: <strong>{activeServer.friendly_name}</strong>
          </p>
        </div>
        <Link to="/">
          <button className="btn-primary">Back to Library</button>
        </Link>
      </header>

      <nav className="header-nav">
        <button
          className={activeTab === 'libraries' ? 'active' : ''}
          onClick={() => setActiveTab('libraries')}
        >
          Libraries
        </button>
        {isOwner && ( // Only show the Sharing tab to the server owner
          <button
            className={activeTab === 'sharing' ? 'active' : ''}
            onClick={() => setActiveTab('sharing')}
          >
            Sharing
          </button>
        )}
      </nav>

      {/* Render the active settings component based on the selected tab */}
      <div>
        {activeTab === 'libraries' && <SettingsLibraries />}
        {activeTab === 'sharing' && isOwner && <SettingsSharing />}
      </div>
    </div>
  );
};

export default SettingsPage;