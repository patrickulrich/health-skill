#!/bin/bash

# Fitbit Data Fetch (Simple Bash Version)
# Fetches data from Fitbit and logs to fitness files

# Configuration
WORKSPACE="${HEALTH_SKILL_WORKSPACE:-$(dirname "$(dirname "$(dirname "$(dirname "$(cd "$(dirname "$0")" && pwd)")")")")}"
FITNESS_DIR="$WORKSPACE/fitness"
FITBIT_DIR="$FITNESS_DIR/fitbit"
TOKENS_FILE="$HOME/.fitbit-tokens.json"
LOG_FILE="$WORKSPACE/fitbit-sync.log"

# Load credentials from root .env (skill root is two levels up from this script)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$(dirname "$(dirname "$SCRIPT_DIR")")/.env"
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | grep -v '^\s*$' | xargs)
fi

# Verify credentials are available
if [ -z "$FITBIT_CLIENT_ID" ] || [ -z "$FITBIT_CLIENT_SECRET" ]; then
    echo "ERROR: FITBIT_CLIENT_ID and FITBIT_CLIENT_SECRET must be set in $ENV_FILE or environment" >&2
    exit 1
fi

# Get date (today by default)
DATE="${1:-$(date +%Y-%m-%d)}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Refresh token
refresh_token() {
    local refresh_token=$(jq -r '.refresh_token' "$TOKENS_FILE")
    log "Refreshing token..."

    # Unlock tokens file temporarily
    chmod 600 "$TOKENS_FILE"

    local auth_header=$(echo -n "${FITBIT_CLIENT_ID}:${FITBIT_CLIENT_SECRET}" | base64 -w 0)

    local response=$(curl -s -X POST https://api.fitbit.com/oauth2/token \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -H "Authorization: Basic $auth_header" \
        --data-urlencode "grant_type=refresh_token" \
        --data-urlencode "refresh_token=$refresh_token")

    # Validate response before writing
    local access_token=$(echo "$response" | jq -r '.access_token // empty')
    if [ -z "$access_token" ]; then
        log "ERROR: Failed to refresh token - invalid response: $(echo "$response" | jq -c '.errors // .')"
        chmod 400 "$TOKENS_FILE"
        return 1
    fi

    # Create backup before writing
    cp "$TOKENS_FILE" "${TOKENS_FILE}.backup"

    # Write to temp file first to avoid truncating on failure
    local now_ms=$(date +%s%3N)
    local tmpfile="${TOKENS_FILE}.tmp"
    if echo "$response" | jq --argjson now "$now_ms" \
        '{access_token, refresh_token, expires_at: ((.expires_in * 1000) + $now), token_type, user_id}' \
        > "$tmpfile" 2>/dev/null; then
        mv "$tmpfile" "$TOKENS_FILE"
        chmod 400 "$TOKENS_FILE"
        log "Token refreshed successfully"
    else
        log "ERROR: Failed to save refreshed tokens (jq error)"
        # Restore backup since we consumed the old refresh token but failed to save the new one
        cp "${TOKENS_FILE}.backup" "$TOKENS_FILE"
        chmod 400 "$TOKENS_FILE"
        rm -f "$tmpfile"
        return 1
    fi
}

# Check if token needs refresh
check_token() {
    local expires_at=$(jq -r '.expires_at // 0' "$TOKENS_FILE")
    local now=$(date +%s%3N)

    if [ "$now" -ge "$expires_at" ] 2>/dev/null; then
        refresh_token || return 1
    fi
}

# Get access token
get_access_token() {
    jq -r '.access_token' "$TOKENS_FILE"
}

# Fetch data
fetch_data() {
    log "Fetching Fitbit data for $DATE..."

    local access_token=$(get_access_token)

    # Create directories
    mkdir -p "$FITBIT_DIR" "$FITNESS_DIR"

    # Fetch data in parallel
    log "Fetching data..."

    local steps=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/steps/date/$DATE/1d.json")

    local heart=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/heart/date/$DATE/1d.json")

    local sleep=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1.2/user/-/sleep/date/$DATE.json")

    local weight=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/body/log/weight/date/$DATE/1m.json")

    local calories=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/calories/date/$DATE/1d.json")

    local distance=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/distance/date/$DATE/1d.json")

    local activities=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/list.json?afterDate=$DATE&sort=asc&limit=20&offset=0")

    # Combine and save raw JSON
    local combined=$(jq -n \
        --arg steps "$steps" \
        --arg heart "$heart" \
        --arg sleep "$sleep" \
        --arg weight "$weight" \
        --arg calories "$calories" \
        --arg distance "$distance" \
        --arg activities "$activities" \
        --arg date "$DATE" \
        '{date: $date, steps: $steps, heart: $heart, sleep: $sleep, weight: $weight, calories: $calories, distance: $distance, activities: $activities, fetchedAt: (now | todateiso8601)}')

    echo "$combined" | jq '.' > "$FITBIT_DIR/$DATE.json"
    log "Saved raw data to $FITBIT_DIR/$DATE.json"

    # Extract values
    local steps_value=$(echo "$steps" | jq -r '.["activities-steps"][0].value // "0"')
    local heart_resting=$(echo "$heart" | jq -r '.["activities-heart"][0].value.restingHeartRate // "N/A"')
    # Sleep duration comes in milliseconds, convert to minutes
    local sleep_ms=$(echo "$sleep" | jq -r '.sleep[0].duration // .summary.totalMinutes // 0')
    local sleep_duration=$((sleep_ms / 60000))
    local sleep_hours=$((sleep_duration / 60))
    local sleep_minutes=$((sleep_duration % 60))
    local weight_value=$(echo "$weight" | jq -r '.weight[0].weight // empty')
    local calories_value=$(echo "$calories" | jq -r '.["activities-calories"][0].value // "0"')
    local distance_value=$(echo "$distance" | jq -r '.["activities-distance"][0].value // "0"')

    # Update fitness log
    update_fitness_log "$steps_value" "$heart_resting" "$sleep_hours" "$sleep_minutes" "$weight_value" "$calories_value" "$distance_value" "$DATE"

    log "Fitbit data sync complete for $DATE"
}

update_fitness_log() {
    local steps_value="$1"
    local heart_resting="$2"
    local sleep_hours="$3"
    local sleep_minutes="$4"
    local weight_value="$5"
    local calories_value="$6"
    local distance_value="$7"
    local date="$8"

    local log_file="$FITNESS_DIR/$date.md"

    if [ ! -f "$log_file" ]; then
        # Create new log
        echo "# Fitness Log - $date" > "$log_file"
        echo "" >> "$log_file"
        echo "## Workout" >> "$log_file"
        echo "*No workouts logged*" >> "$log_file"
        echo "" >> "$log_file"
    fi

    # Build Fitbit section
    echo "## Fitbit Data" > /tmp/fitbit-section.txt
    echo "" >> /tmp/fitbit-section.txt
    echo "### Steps" >> /tmp/fitbit-section.txt
    echo "- Total: $steps_value" >> /tmp/fitbit-section.txt
    echo "" >> /tmp/fitbit-section.txt
    echo "### Heart Rate" >> /tmp/fitbit-section.txt
    echo "- Resting: $heart_resting bpm" >> /tmp/fitbit-section.txt
    echo "" >> /tmp/fitbit-section.txt
    echo "### Sleep" >> /tmp/fitbit-section.txt
    echo "- Duration: ${sleep_hours}h ${sleep_minutes}m" >> /tmp/fitbit-section.txt
    echo "" >> /tmp/fitbit-section.txt

    # Weight (optional)
    if [ "$weight_value" != "null" ] && [ -n "$weight_value" ]; then
        echo "### Weight" >> /tmp/fitbit-section.txt
        local weight_formatted=$(printf '%.1f' $weight_value)
        echo "- $weight_formatted kg" >> /tmp/fitbit-section.txt
        echo "" >> /tmp/fitbit-section.txt
    fi

    echo "### Calories" >> /tmp/fitbit-section.txt
    echo "- Total: $calories_value kcal" >> /tmp/fitbit-section.txt
    echo "" >> /tmp/fitbit-section.txt
    echo "### Distance" >> /tmp/fitbit-section.txt
    local dist_formatted=$(printf '%.2f' $distance_value)
    echo "- $dist_formatted km" >> /tmp/fitbit-section.txt
    echo "" >> /tmp/fitbit-section.txt
    echo "### Activities" >> /tmp/fitbit-section.txt
    echo "*No activities logged*" >> /tmp/fitbit-section.txt
    echo "" >> /tmp/fitbit-section.txt

    local sync_time=$(date '+%b %d, %Y at %I:%M %p')
    echo "*Last sync: $sync_time*" >> /tmp/fitbit-section.txt

    # Append or replace section in log file
    if grep -q "^## Fitbit Data" "$log_file"; then
        # Remove old Fitbit section (from ## Fitbit Data to next ## heading or EOF)
        awk '
            /^## Fitbit Data/ { skip=1; next }
            /^## / && skip { skip=0 }
            !skip
        ' "$log_file" > "${log_file}.tmp"
        mv "${log_file}.tmp" "$log_file"
    fi
    # Insert Fitbit section after the Workout section header line
    sed -i '/^## Workout/r /tmp/fitbit-section.txt' "$log_file"

    # Update daily stats
    if grep -q "^## Daily Stats" "$log_file"; then
        sed -i "s/- Steps: \[.*\]/- Steps: $steps_value/" "$log_file"
        if [ "$weight_value" != "null" ] && [ -n "$weight_value" ]; then
            local weight_fmt=$(printf '%.1f' $weight_value)
            sed -i "s/- Weight: \[.*\]/- Weight: $weight_fmt kg/" "$log_file"
        fi
        # Fix sleep duration format (e.g., "4.4 h" instead of "4h 24m")
        local sleep_decimal=$(awk "BEGIN {printf \"%.1f\", $sleep_hours + $sleep_minutes/60}")
        sed -i "s/- Sleep: \[.*\]/- Sleep: ${sleep_decimal} h/" "$log_file"
    else
        # Add Daily Stats section
        echo "" >> "$log_file"
        echo "## Daily Stats" >> "$log_file"
        echo "- Steps: $steps_value" >> "$log_file"
        if [ "$weight_value" != "null" ] && [ -n "$weight_value" ]; then
            local weight_fmt=$(printf '%.1f' $weight_value)
            echo "- Weight: $weight_fmt kg" >> "$log_file"
        else
            echo "- Weight: [from Fitbit or manual]" >> "$log_file"
        fi
        # Fix sleep duration format
        local sleep_decimal=$(awk "BEGIN {printf \"%.1f\", $sleep_hours + $sleep_minutes/60}")
        echo "- Sleep: ${sleep_decimal} h" >> "$log_file"
        echo "- Energy level (1-10): [manual]" >> "$log_file"
        echo "" >> "$log_file"
        echo "## Notes/Observations" >> "$log_file"
    fi

    log "Updated fitness log: $log_file"
}

# Main
log "Starting Fitbit sync for $DATE..."

if ! check_token; then
    log "ERROR: Token refresh failed, aborting sync"
    exit 1
fi

fetch_data

log "Sync completed successfully"
