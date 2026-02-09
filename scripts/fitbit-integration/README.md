# Fitbit Integration

Fetch fitness data directly from Fitbit's API - no Android app needed!

## Quick Start

### 1. Create Fitbit Developer Account

1. Go to https://dev.fitbit.com/
2. Sign in with your Fitbit account
3. Create a new app:
   - **App Type**: Personal (for your own data)
   - **OAuth 2.0 Application Type**: Confidential (if using server) or Public (if easier)
   - **Callback URL**: `http://localhost:3000/callback` (we'll set this up)
   - **Default Access Type**: Read-only (we only need to read data)
4. Note down:
   - **Client ID**
   - **Client Secret**

### 2. Install Dependencies

```bash
cd /path/to/skill/scripts/fitbit-integration
npm install express axios dotenv
```

### 3. Configure

Copy the `.env.example` template in the skill root and fill in your credentials:

```bash
cp ../../.env.example ../../.env
```

Edit `../../.env` with your Fitbit client ID/secret and USDA API key.

### 4. Start Auth Server

```bash
node auth-server.js
```

Follow the instructions to authorize the app with your Fitbit account.

### 5. Fetch Data

Once authorized, you can fetch data:

```bash
node fetch-data.js
```

Or use the API endpoint:

```bash
curl http://localhost:3000/api/fitbit/today
```

## API Endpoints

### Server Endpoints

- `GET /health` - Health check
- `GET /auth` - Start OAuth flow (opens Fitbit authorization)
- `GET /callback` - OAuth callback ( Fitbit redirects here)
- `GET /api/fitbit/today` - Get today's fitness data
- `GET /api/fitbit/date/:date` - Get data for specific date (YYYY-MM-DD)
- `GET /api/fitbit/weekly` - Get last 7 days
- `GET /api/fitbit/steps` - Get steps data
- `GET /api/fitbit/heart-rate` - Get heart rate data
- `GET /api/fitbit/sleep` - Get sleep data
- `GET /api/fitbit/weight` - Get weight data

### Fitbit API Endpoints Used

We'll use these Fitbit API endpoints:

| Data | Endpoint | What we get |
|------|----------|-------------|
| Steps | `/1/user/-/activities/steps/date/today/1d/15min.json` | Intraday steps |
| Heart Rate | `/1/user/-/activities/heart/date/today/1d/1min.json` | Intraday heart rate |
| Sleep | `/1.2/user/-/sleep/date/today.json` | Sleep stages, duration |
| Weight | `/1/user/-/body/log/weight/date/today/1m.json` | Weight logs |
| Calories | `/1/user/-/activities/calories/date/today/1d.json` | Active calories |
| Distance | `/1/user/-/activities/distance/date/today/1d.json` | Distance covered |
| Activities | `/1/user/-/activities/list.json` | Workout sessions |

See https://dev.fitbit.com/reference/web-api/ for full API docs.

## Data Retrieved

For each day, we'll capture:

- **Steps**: Total count, intraday data (every 15 min)
- **Heart Rate**: Average, resting, intraday data (every min)
- **Sleep**: Duration, stages (light, deep, REM, awake), efficiency
- **Weight**: Latest reading
- **Calories**: Total, active, resting
- **Distance**: Total distance
- **Activities**: Workout sessions (type, duration, calories)
- **Activity Summary**: Sedentary, lightly active, fairly active, very active minutes

## Integration with Fitness Tracking

Data is automatically logged to `fitness/YYYY-MM-DD.md` in this format:

```markdown
## Fitbit Data

### Steps
- Total: 8,432
- Distance: 6.2 km

### Heart Rate
- Average: 72 bpm
- Resting: 62 bpm
- Max: 145 bpm

### Sleep
- Duration: 7h 45m
- Efficiency: 85%
- Stages: Light 3h, Deep 2h, REM 2h, Awake 45m

### Weight
- Current: 82.5 kg

### Activities
- Walking (45 min) - 210 cal
- Running (30 min) - 350 cal

### Summary
- Sedentary: 12h 30m
- Lightly active: 4h 15m
- Fairly active: 1h 15m
- Very active: 45m
```

## Automation

### Cron Job

Add to crontab to fetch data daily:

```bash
# Edit crontab
crontab -e

# Add this line to fetch at 9 PM daily
0 21 * * * cd /path/to/skill/scripts/fitbit-integration && node fetch-data.js >> /var/log/fitbit-sync.log 2>&1
```

### Systemd Service

Create `/etc/systemd/system/fitbit-sync.service`:

```ini
[Unit]
Description=Fitbit Data Sync
After=network.target

[Service]
Type=oneshot
User=your-user
WorkingDirectory=/path/to/your/workspace/skills/health-skill/scripts/fitbit-integration
ExecStart=/usr/bin/node fetch-data.js

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable fitbit-sync.timer
```

Create timer `/etc/systemd/system/fitbit-sync.timer`:

```ini
[Unit]
Description=Run Fitbit sync daily at 9 PM

[Timer]
OnCalendar=*-*-* 21:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Start timer:
```bash
sudo systemctl start fitbit-sync.timer
```

## Troubleshooting

### Token Expired

Fitbit tokens expire after 8 hours. The server handles refresh automatically, but if you see errors:

1. Check tokens file exists: `cat ~/.fitbit-tokens.json`
2. If missing, re-run auth: `node auth-server.js` and visit http://localhost:3000/auth
3. Check client ID/secret in root `.env` are correct

### Rate Limiting

Fitbit has rate limits (150 calls per hour). We fetch data in batches to minimize calls.

### No Data Returned

- Check your Fitbit device synced recently
- Verify date format (YYYY-MM-DD)
- Check Fitbit API status: https://dev.fitbit.com/reference/web-api/availability
- Review server logs: `tail -f server.log`

### 401 Unauthorized

- Token expired or revoked
- Re-run authorization flow
- Check `.env` has correct credentials

## Security

- **Tokens** stored in `~/.fitbit-tokens.json` (home directory, not workspace)
- **Credentials** in root `.env` (not committed to git)
- **HTTPS** recommended for production (use ngrok or similar for local dev)

## Next Steps

1. Create Fitbit developer account and app
2. Run authorization flow once
3. Test fetch with `node fetch-data.js`
4. Set up automation (cron or systemd)
5. Your AI agent will analyze data automatically in heartbeats

 Your AI agent will have full access to your Fitbit data for coaching and insights!
