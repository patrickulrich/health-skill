#!/usr/bin/env node

/**
 * Fitbit Authorization Server
 *
 * Handles OAuth2 authorization flow with Fitbit using PKCE.
 * Run this once to authorize the app and get access tokens.
 *
 * Usage:
 *   node auth-server.js
 *
 * Then visit: http://localhost:3000/auth
 */

const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '.env') });
const express = require('express');
const axios = require('axios');
const fs = require('fs');
const crypto = require('crypto');

const app = express();
const PORT = process.env.PORT || 3000;

// Fitbit OAuth2 endpoints
const FITBIT_AUTH_URL = 'https://www.fitbit.com/oauth2/authorize';
const FITBIT_TOKEN_URL = 'https://api.fitbit.com/oauth2/token';

// Token storage
const TOKENS_PATH = path.join(require('os').homedir(), '.fitbit-tokens.json');
const VERIFIER_PATH = path.join(require('os').homedir(), '.fitbit-verifier.json');

// Generate PKCE code verifier and challenge
function generatePKCE() {
    const verifier = crypto.randomBytes(32).toString('base64url');
    const challenge = crypto.createHash('sha256').update(verifier).digest('base64url');
    return { verifier, challenge };
}

// Load tokens from file
function loadTokens() {
    try {
        if (fs.existsSync(TOKENS_PATH)) {
            return JSON.parse(fs.readFileSync(TOKENS_PATH, 'utf8'));
        }
    } catch (error) {
        console.error('Error loading tokens:', error.message);
    }
    return null;
}

// Save tokens to file
function saveTokens(tokens) {
    fs.writeFileSync(TOKENS_PATH, JSON.stringify(tokens, null, 2));
    console.log('✓ Tokens saved to:', TOKENS_PATH);
}

// Save code verifier
function saveVerifier(verifier, state) {
    fs.writeFileSync(VERIFIER_PATH, JSON.stringify({ verifier, state, timestamp: Date.now() }, null, 2));
}

// Load and clear code verifier
function loadAndClearVerifier() {
    try {
        if (fs.existsSync(VERIFIER_PATH)) {
            const data = JSON.parse(fs.readFileSync(VERIFIER_PATH, 'utf8'));
            fs.unlinkSync(VERIFIER_PATH);
            return data;
        }
    } catch (error) {
        console.error('Error loading verifier:', error.message);
    }
    return null;
}

// Refresh access token
async function refreshAccessToken(refreshToken) {
    try {
        const basicAuth = Buffer.from(`${process.env.FITBIT_CLIENT_ID}:${process.env.FITBIT_CLIENT_SECRET}`).toString('base64');
        const response = await axios.post(FITBIT_TOKEN_URL, {
            grant_type: 'refresh_token',
            refresh_token: refreshToken
        }, {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Authorization': `Basic ${basicAuth}`
            },
            transformRequest: [(data) => {
                return new URLSearchParams(data).toString();
            }]
        });

        const tokens = {
            access_token: response.data.access_token,
            refresh_token: response.data.refresh_token,
            expires_at: Date.now() + (response.data.expires_in * 1000),
            token_type: response.data.token_type
        };

        saveTokens(tokens);
        return tokens;
    } catch (error) {
        console.error('Error refreshing token:', error.response?.data || error.message);
        throw error;
    }
}

// Get valid access token
async function getAccessToken() {
    let tokens = loadTokens();

    if (!tokens) {
        throw new Error('No tokens found. Please run authorization flow first.');
    }

    // Check if token is expired or about to expire (5 min buffer)
    if (Date.now() >= tokens.expires_at - 300000) {
        console.log('Access token expired, refreshing...');
        tokens = await refreshAccessToken(tokens.refresh_token);
    }

    return tokens.access_token;
}

// Middleware to ensure valid token
app.use(async (req, res, next) => {
    if (req.path === '/auth' || req.path === '/callback') {
        return next();
    }

    try {
        req.accessToken = await getAccessToken();
        next();
    } catch (error) {
        res.status(401).json({ error: error.message });
    }
});

// Start authorization flow
app.get('/auth', (req, res) => {
    const { verifier, challenge } = generatePKCE();
    const state = crypto.randomBytes(16).toString('hex');

    // Save code verifier for callback
    saveVerifier(verifier, state);

    const authUrl = new URL(FITBIT_AUTH_URL);
    authUrl.searchParams.append('response_type', 'code');
    authUrl.searchParams.append('client_id', process.env.FITBIT_CLIENT_ID);
    authUrl.searchParams.append('scope', 'activity heartrate location nutrition profile settings sleep social weight');
    authUrl.searchParams.append('redirect_uri', `http://localhost:${PORT}/callback`);
    authUrl.searchParams.append('state', state);
    authUrl.searchParams.append('code_challenge', challenge);
    authUrl.searchParams.append('code_challenge_method', 'S256');

    console.log('\n=== Fitbit Authorization ===');
    console.log('Visit this URL to authorize:');
    console.log(authUrl.toString());
    console.log('===========================\n');

    res.send(`
<!DOCTYPE html>
<html>
<head><title>Fitbit Authorization</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 50px auto; padding: 20px;">
    <h1>Fitbit Authorization</h1>
    <p>Click link below to authorize this app to access your Fitbit data:</p>
    <p><a href="${authUrl.toString()}" style="display: inline-block; padding: 15px 30px; background: #00B0B9; color: white; text-decoration: none; border-radius: 5px;">Authorize with Fitbit</a></p>
    <p><strong>Scopes requested:</strong></p>
    <ul>
        <li>activity - Steps, distance, calories</li>
        <li>heartrate - Heart rate data</li>
        <li>sleep - Sleep data</li>
        <li>weight - Weight logs</li>
        <li>profile - Basic profile info</li>
    </ul>
</body>
</html>
    `);
});

// OAuth callback
app.get('/callback', async (req, res) => {
    const { code, state, error } = req.query;

    if (error) {
        console.error('Authorization error:', error);
        return res.status(400).send(`
<!DOCTYPE html>
<html>
<head><title>Authorization Failed</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 50px auto; padding: 20px;">
    <h1 style="color: red;">✗ Authorization Failed</h1>
    <p>Error: ${error}</p>
    <p>Please try again by visiting <a href="/auth">/auth</a></p>
</body>
</html>
        `);
    }

    if (!code) {
        return res.status(400).send('Authorization failed: No code received');
    }

    try {
        // Load and verify code verifier
        const verifierData = loadAndClearVerifier();

        if (!verifierData) {
            throw new Error('Code verifier not found. Authorization may have expired.');
        }

        if (state !== verifierData.state) {
            throw new Error('State mismatch. Possible CSRF attack.');
        }

        // Exchange code for tokens
        const basicAuth = Buffer.from(`${process.env.FITBIT_CLIENT_ID}:${process.env.FITBIT_CLIENT_SECRET}`).toString('base64');
        const response = await axios.post(FITBIT_TOKEN_URL, {
            grant_type: 'authorization_code',
            code: code,
            redirect_uri: `http://localhost:${PORT}/callback`,
            code_verifier: verifierData.verifier
        }, {
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Authorization': `Basic ${basicAuth}`
            },
            transformRequest: [(data) => {
                return new URLSearchParams(data).toString();
            }]
        });

        const tokens = {
            access_token: response.data.access_token,
            refresh_token: response.data.refresh_token,
            expires_at: Date.now() + (response.data.expires_in * 1000),
            token_type: response.data.token_type,
            user_id: response.data.user_id
        };

        saveTokens(tokens);

        res.send(`
<!DOCTYPE html>
<html>
<head><title>Authorization Successful</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 50px auto; padding: 20px;">
    <h1 style="color: green;">✓ Authorization Successful!</h1>
    <p>Your Fitbit account has been authorized.</p>
    <p><strong>Token expires in:</strong> 8 hours</p>
    <p><strong>Tokens saved to:</strong> ${TOKENS_PATH}</p>
    <p>The server will automatically refresh tokens when needed.</p>
    <p><strong>Next steps:</strong></p>
    <ol>
        <li>Test fetching data: <code>node fetch-data.js</code></li>
        <li>Set up automation (cron job or systemd)</li>
    </ol>
    <p><strong>Ready to fetch data!</strong></p>
</body>
</html>
        `);

    } catch (error) {
        console.error('Error exchanging code for tokens:', error.response?.data || error.message);
        res.status(500).send(`
<!DOCTYPE html>
<html>
<head><title>Authorization Failed</title></head>
<body style="font-family: sans-serif; max-width: 800px; margin: 50px auto; padding: 20px;">
    <h1 style="color: red;">✗ Authorization Failed</h1>
    <p>Error: ${error.response?.data?.errors?.[0]?.message || error.message}</p>
    <p>Please try again by visiting <a href="/auth">/auth</a></p>
</body>
</html>
        `);
    }
});

// Health check
app.get('/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Get today's data
app.get('/api/fitbit/today', async (req, res) => {
    try {
        const today = new Date().toISOString().split('T')[0];
        const data = await fetchFitbitData(today, req.accessToken);
        res.json(data);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Get data for specific date
app.get('/api/fitbit/date/:date', async (req, res) => {
    try {
        const data = await fetchFitbitData(req.params.date, req.accessToken);
        res.json(data);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Fetch Fitbit data for a specific date
async function fetchFitbitData(date, accessToken) {
    const headers = {
        'Authorization': `Bearer ${accessToken}`,
        'Accept': 'application/json'
    };

    const fetchWithRetry = async (url, retries = 3) => {
        for (let i = 0; i < retries; i++) {
            try {
                const response = await axios.get(url, { headers });
                return response.data;
            } catch (error) {
                if (i === retries - 1) throw error;
                await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)));
            }
        }
    };

    try {
        // Fetch all data in parallel
        const [steps, heart, sleep, weight, calories, distance, activities] = await Promise.all([
            fetchWithRetry(`https://api.fitbit.com/1/user/-/activities/steps/date/${date}/1d/15min.json`),
            fetchWithRetry(`https://api.fitbit.com/1/user/-/activities/heart/date/${date}/1d/1min.json`),
            fetchWithRetry(`https://api.fitbit.com/1.2/user/-/sleep/date/${date}.json`),
            fetchWithRetry(`https://api.fitbit.com/1/user/-/body/log/weight/date/${date}/1m.json`),
            fetchWithRetry(`https://api.fitbit.com/1/user/-/activities/calories/date/${date}/1d.json`),
            fetchWithRetry(`https://api.fitbit.com/1/user/-/activities/distance/date/${date}/1d.json`),
            fetchWithRetry(`https://api.fitbit.com/1/user/-/activities/list.json?afterDate=${date}&sort=asc&limit=20&offset=0`)
        ]);

        return {
            date,
            steps,
            heart,
            sleep,
            weight,
            calories,
            distance,
            activities,
            fetchedAt: new Date().toISOString()
        };
    } catch (error) {
        console.error('Error fetching Fitbit data:', error.message);
        throw error;
    }
}

// Start server
app.listen(PORT, () => {
    console.log('╔════════════════════════════════════════════╗');
    console.log('║  Fitbit Authorization Server                ║');
    console.log('╚════════════════════════════════════════════╝');
    console.log('');
    console.log(`🚀 Server running on port ${PORT}`);
    console.log('');
    console.log('🔐 To authorize Fitbit access:');
    console.log(`   1. Open: http://localhost:${PORT}/auth`);
    console.log('   2. Click the authorization link');
    console.log('   3. Grant permissions');
    console.log('');
    console.log(`📁 Tokens will be saved to: ${TOKENS_PATH}`);
    console.log('');
    console.log('⚡ Ready...\n');
});

// Export getAccessToken for use in fetch-data.js
module.exports = { getAccessToken, fetchFitbitData };
