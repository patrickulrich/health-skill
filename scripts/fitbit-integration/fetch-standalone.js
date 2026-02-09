#!/usr/bin/env node

/**
 * Fitbit Data Fetcher (Standalone)
 *
 * Fetches fitness data from Fitbit API and logs to fitness files.
 * This is a standalone version for cron jobs - doesn't start the server.
 *
 * Usage:
 *   node fetch-standalone.js [date]
 *
 * If no date specified, fetches today's data.
 *
 * Date format: YYYY-MM-DD
 */

require('dotenv').config();
const fsSync = require('fs');
const fs = require('fs').promises;
const path = require('path');
const crypto = require('crypto');
const axios = require('axios');

// Configuration
const WORKSPACE = path.join(__dirname, '../../');
const FITNESS_DIR = path.join(WORKSPACE, 'fitness');
const FITBIT_DIR = path.join(FITNESS_DIR, 'fitbit');

// Fitbit API endpoints
const FITBIT_TOKEN_URL = 'https://api.fitbit.com/oauth2/token';

// Token storage
const TOKENS_PATH = path.join(require('os').homedir(), '.fitbit-tokens.json');

// Get date from args or use today
const dateArg = process.argv[2];
const targetDate = dateArg || new Date().toISOString().split('T')[0];

async function initDirectories() {
    try {
        await fs.mkdir(FITNESS_DIR, { recursive: true });
        await fs.mkdir(FITBIT_DIR, { recursive: true });
    } catch (error) {
        console.error('Error initializing directories:', error.message);
        process.exit(1);
    }
}

async function fetchAndLogData() {
    console.log(`\n=== Fetching Fitbit Data for ${targetDate} ===\n`);

    try {
        // Get access token
        console.log('Getting access token...');
        const accessToken = await getAccessToken();

        // Fetch data from Fitbit
        console.log('Fetching data from Fitbit...');
        const data = await fetchFitbitData(targetDate, accessToken);

        // Save raw JSON
        const jsonPath = path.join(FITBIT_DIR, `${targetDate}.json`);
        await fs.writeFile(jsonPath, JSON.stringify(data, null, 2));
        console.log(`✓ Raw data saved to: ${jsonPath}`);

        // Update fitness log
        await updateFitnessLog(data, targetDate);

        console.log('\n=== Summary ===');
        console.log(`Steps: ${data.steps['activities-steps'][0]?.value || 0}`);
        console.log(`Heart Rate Avg: ${data.heart['activities-heart'][0]?.value?.restingHeartRate || 'N/A'} bpm`);
        console.log(`Sleep Duration: ${formatSleepDuration(data.sleep)}`);
        console.log(`Weight: ${data.weight.weight?.[0]?.weight || 'N/A'} kg`);
        console.log(`Calories: ${data.calories['activities-calories']?.[0]?.value || 0} kcal`);
        console.log('=================\n');

    } catch (error) {
        console.error('✗ Error:', error.message);
        process.exit(1);
    }
}

async function loadTokens() {
    try {
        const stat = await fs.stat(TOKENS_PATH).catch(() => null);
        if (stat) {
            return JSON.parse(await fs.readFile(TOKENS_PATH, 'utf8'));
        }
    } catch (error) {
        console.error('Error loading tokens:', error.message);
    }
    return null;
}

async function saveTokens(tokens) {
    // Write to temp file first, then rename for atomicity
    const tmpPath = TOKENS_PATH + '.tmp';
    await fs.writeFile(tmpPath, JSON.stringify(tokens, null, 2));
    await fs.rename(tmpPath, TOKENS_PATH);
    console.log('✓ Tokens saved to:', TOKENS_PATH);
}

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

        await saveTokens(tokens);
        return tokens;
    } catch (error) {
        console.error('Error refreshing token:', error.response?.data || error.message);
        throw error;
    }
}

async function getAccessToken() {
    let tokens = await loadTokens();

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

async function updateFitnessLog(data, date) {
    const logPath = path.join(FITNESS_DIR, `${date}.md`);
    let logContent = '';

    // Check if log exists
    try {
        logContent = await fs.readFile(logPath, 'utf8');
    } catch (error) {
        // New log - create basic structure
        logContent = `# Fitness Log - ${date}

## Workout
*No workouts logged*

## Fitbit Data
*Imported from Fitbit*

## Daily Stats
- Steps: [from Fitbit or manual]
- Weight: [from Fitbit or manual]
- Sleep: [from Fitbit or manual]
- Energy level (1-10): [manual]

## Notes/Observations
`;
    }

    // Generate Fitbit section
    const fitbitSection = generateFitbitSection(data);

    // Check if Fitbit Data section exists
    const fitbitSectionRegex = /## Fitbit Data\n([\s\S]*?)(?=\n##|$)/;
    const match = logContent.match(fitbitSectionRegex);

    if (match) {
        // Replace existing section
        logContent = logContent.replace(
            fitbitSectionRegex,
            `## Fitbit Data${fitbitSection}`
        );
    } else {
        // Insert after Workout section
        logContent = logContent.replace(
            /(## Workout\n[\s\S]*?)(?=\n##|$)/,
            `$1${fitbitSection}\n\n## Daily Stats`
        );
    }

    // Update Daily Stats section
    logContent = updateDailyStats(logContent, data);

    // Save updated log
    await fs.writeFile(logPath, logContent);
    console.log(`✓ Fitness log updated: ${logPath}`);
}

function generateFitbitSection(data) {
    let section = '\n\n### Steps\n';
    const stepsData = data.steps['activities-steps']?.[0];
    if (stepsData) {
        section += `- Total: ${parseInt(stepsData.value).toLocaleString()}\n`;
        // Check for intraday data
        if (stepsData['activities-steps-intraday']?.dataset) {
            section += `- Intraday: ${stepsData['activities-steps-intraday'].dataset.length} data points\n`;
        }
    }

    section += '\n### Heart Rate\n';
    const heartData = data.heart['activities-heart']?.[0];
    if (heartData) {
        section += `- Resting: ${heartData.value?.restingHeartRate || 'N/A'} bpm\n`;
        if (heartData.value?.heartRateZones) {
            section += '- Zones: ';
            const zones = heartData.value.heartRateZones.map(zone => {
                const minutes = Math.round(zone.minutes);
                return `${zone.name}: ${minutes}m`;
            }).join(', ');
            section += `${zones}\n`;
        }
    }

    // Sleep data
    section += '\n### Sleep\n';
    if (data.sleep?.sleep) {
        const sleep = data.sleep.sleep[0] || data.sleep;
        const duration = sleep.duration || sleep.totalMinutes || 0;
        const hours = Math.floor(duration / 60);
        const minutes = Math.round(duration % 60);

        section += `- Duration: ${hours}h ${minutes}m\n`;
        if (sleep.efficiency) section += `- Efficiency: ${sleep.efficiency}%\n`;
        if (sleep.startTime) section += `- Start: ${new Date(sleep.startTime).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}\n`;
        if (sleep.endTime) section += `- End: ${new Date(sleep.endTime).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}\n`;

        if (sleep.levels?.data) {
            const stages = {};
            sleep.levels.data.forEach(level => {
                stages[level.level] = (stages[level.level] || 0) + level.seconds;
            });
            section += '- Stages: ';
            section += Object.entries(stages)
                .map(([level, seconds]) => {
                    const mins = Math.round(seconds / 60);
                    const levelName = level === 'wake' ? 'Awake' :
                                      level === 'rem' ? 'REM' :
                                      level === 'deep' ? 'Deep' :
                                      level === 'light' ? 'Light' : level;
                    return `${levelName} ${mins}m`;
                })
                .join(', ');
            section += '\n';
        }
    } else {
        section += '*No sleep data available*\n';
    }

    // Weight
    if (data.weight?.weight?.length > 0) {
        const weight = data.weight.weight[0];
        section += '\n### Weight\n';
        section += `- ${parseFloat(weight.weight).toFixed(1)} kg`;
        if (weight.date) section += ` (${new Date(weight.date).toLocaleDateString()})`;
        section += '\n';
    }

    // Calories
    section += '\n### Calories\n';
    const caloriesData = data.calories['activities-calories']?.[0];
    if (caloriesData) {
        const totalCalories = parseInt(caloriesData.value);
        section += `- Total: ${totalCalories.toLocaleString()} kcal\n`;
    }

    // Distance
    section += '\n### Distance\n';
    const distanceData = data.distance['activities-distance']?.[0];
    if (distanceData) {
        const distanceKm = parseFloat(distanceData.value);
        section += `- ${distanceKm.toFixed(2)} km\n`;
    }

    // Activities/Workouts
    section += '\n### Activities\n';
    if (data.activities?.activities?.length > 0) {
        data.activities.activities.forEach(activity => {
            section += `**${activity.activityName || activity.name}**\n`;
            const startTime = activity.startTime ? new Date(activity.startTime).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }) : 'N/A';
            section += `- Time: ${startTime}\n`;
            if (activity.duration) {
                const mins = Math.round(activity.duration / 60000);
                section += `- Duration: ${mins} min\n`;
            }
            if (activity.calories) section += `- Calories: ${Math.round(activity.calories)} kcal\n`;
            if (activity.steps) section += `- Steps: ${activity.steps.toLocaleString()}\n`;
            if (activity.distance) section += `- Distance: ${activity.distance.toFixed(2)} km\n`;
            if (activity.averageHeartRate) section += `- Avg HR: ${Math.round(activity.averageHeartRate)} bpm\n`;
            section += '\n';
        });
    } else {
        section += '*No activities logged*\n';
    }

    const syncTime = new Date(data.fetchedAt).toLocaleString('en-US', {
        dateStyle: 'medium',
        timeStyle: 'short'
    });
    section += `\n\n*Last sync: ${syncTime}*`;

    return section;
}

function updateDailyStats(logContent, data) {
    let updated = logContent;

    // Update steps
    const stepsValue = data.steps['activities-steps']?.[0]?.value;
    if (stepsValue) {
        updated = updated.replace(
            /- Steps: \[.*?\]/,
            `- Steps: ${parseInt(stepsValue).toLocaleString()}`
        );
    }

    // Update weight
    if (data.weight?.weight?.length > 0) {
        const weightValue = parseFloat(data.weight.weight[0].weight).toFixed(1);
        updated = updated.replace(
            /- Weight: \[.*?\]/,
            `- Weight: ${weightValue} kg`
        );
    }

    // Update sleep
    if (data.sleep?.sleep) {
        const sleep = data.sleep.sleep[0] || data.sleep;
        const duration = sleep.duration || sleep.totalMinutes || 0;
        const hours = (duration / 60).toFixed(1);
        updated = updated.replace(
            /- Sleep: \[.*?\]/,
            `- Sleep: ${hours} h`
        );
    }

    return updated;
}

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

function formatSleepDuration(sleepData) {
    if (!sleepData?.sleep && !sleepData.summary) return 'N/A';

    const sleep = sleepData.sleep?.[0] || sleepData;
    const duration = sleep.duration || sleep.totalMinutes || sleep.summary?.totalMinutes || 0;
    const hours = Math.floor(duration / 60);
    const minutes = Math.round(duration % 60);

    return `${hours}h ${minutes}m`;
}

// Main
(async () => {
    await initDirectories();
    await fetchAndLogData();
})();
