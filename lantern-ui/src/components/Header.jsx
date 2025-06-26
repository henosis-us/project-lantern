import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function Header({ onSearchChange, onScan, isScanning, activeTab, onNavClick }) {
  const { logout, isOwner } = useAuth();
  const navigate = useNavigate();

  const handleNavClick = (tab) => {
    if (typeof onNavClick === 'function') {
      onNavClick(tab); // Use the prop if it's a function
    } else {
      // Fallback to default navigation based on tab
      if (tab === 'movies') {
        window.location.href = '/';
      } else if (tab === 'tv') {
        window.location.href = '/tv'; // Assuming /tv is the route for TV shows
      }
    }
  };

  return (
    <div className="header">
      <h1 style={{ cursor: 'pointer' }} onClick={() => (window.location.href = '/')}>Lantern</h1>
      {/* Central Navigation */}
      <nav className="header-nav">
        <button
          className={activeTab === 'movies' ? 'active' : ''}
          onClick={() => handleNavClick('movies')}
        >
          Movies
        </button>
        <button
          className={activeTab === 'tv' ? 'active' : ''}
          onClick={() => handleNavClick('tv')}
        >
          TV Shows
        </button>
      </nav>
      {/* Search and Controls */}
      <input
        id="search-input"
        type="text"
        placeholder={activeTab === 'movies' ? "Search movies…" : "Search TV shows…"}
        onChange={(e) => onSearchChange(e.target.value)}
      />
      <div style={{ display: 'flex', gap: '10px' }}>
        {isOwner && (
          <button id="scan-button" onClick={onScan} disabled={isScanning}>
            {isScanning ? 'Scanning…' : 'Scan Library'}
          </button>
        )}
        {isOwner && (
          <button onClick={() => navigate('/settings')}>Settings</button>
        )}
        <button id="logout-btn" onClick={logout}>
          Logout
        </button>
      </div>
    </div>
  );
}

export default Header;