import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const OnboardingPage = () => {
  const { logout } = useAuth();
  
  return (
    <div className="auth-page">
      <div className="auth-form" style={{ maxWidth: '500px' }}>
        <h2>Welcome to Lantern!</h2>
        <p style={{ color: '#ccc', textAlign: 'center', lineHeight: 1.6 }}>
          You don't have any media servers linked to your account yet.
        </p>
        <p style={{ color: '#aaa', textAlign: 'center' }}>
          Get started by downloading the server application.
        </p>
        
        <a 
          href="https://github.com/your-username/your-repo/releases" // <-- UPDATE THIS LINK
          target="_blank" 
          rel="noopener noreferrer"
        >
          <button style={{ width: '100%', marginBottom: '15px' }}>
            Download Lantern Media Server
          </button>
        </a>

        <Link to="/claim">
          <button style={{ width: '100%', background: '#333' }}>
            I already have a server running
          </button>
        </Link>
        
        <div className="switch-link" style={{ marginTop: '25px' }}>
            <a href="#" onClick={logout}>Log Out</a>
        </div>
      </div>
    </div>
  );
};

export default OnboardingPage;