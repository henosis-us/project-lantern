// src/pages/LoginPage.jsx
import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]     = useState('');

  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();

  /* ------------------------------------------------------------------
   * If the user becomes authenticated (token is stored in context),
   * send them straight to the library page.
   * ---------------------------------------------------------------- */
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      await login(username, password);   // only sets the token
      // navigation happens automatically in useEffect above
    } catch (err) {
      setError('Login failed. Please check your credentials.');
      console.error(err);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-form">
        <h2>Login to Lantern</h2>

        <form onSubmit={handleSubmit}>
          {error && <p className="error">{error}</p>}

          <input
            type="text"
            placeholder="Username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />

          <input
            type="password"
            placeholder="Password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button type="submit">Login</button>
        </form>

        <p className="switch-link">
          Don’t have an account?&nbsp;
          <Link to="/register">Register here</Link>
        </p>
      </div>
    </div>
  );
}

export default LoginPage;