// src/pages/RegisterPage.jsx
import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Link } from 'react-router-dom';

function RegisterPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const { register } = useAuth();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    try {
      await register(username, password);
      setSuccess('Registration successful! You can now log in.');
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed.');
      console.error(err);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-form">
        <h2>Create an Account</h2>
        <form onSubmit={handleSubmit}>
          {error && <p className="error">{error}</p>}
          {success && <p style={{ color: '#28a745', textAlign: 'center' }}>{success}</p>}
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="submit">Register</button>
        </form>
        <p className="switch-link">
          Already have an account? <Link to="/login">Login here</Link>
        </p>
      </div>
    </div>
  );
}

export default RegisterPage;