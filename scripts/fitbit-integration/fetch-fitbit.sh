#!/bin/bash

# Fitbit Data Fetch (Comprehensive Version)
# Fetches all available data from Fitbit API and logs to fitness files

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

# Validate API response - returns empty JSON if response contains errors
validate_response() {
    local response="$1"
    local endpoint="$2"
    if echo "$response" | jq -e '.errors | length > 0' >/dev/null 2>&1; then
        log "WARNING: API error for $endpoint: $(echo "$response" | jq -c '.errors')"
        echo "{}"
    else
        echo "$response"
    fi
}

# Fetch data
fetch_data() {
    log "Fetching Fitbit data for $DATE..."

    local access_token=$(get_access_token)

    # Create directories
    mkdir -p "$FITBIT_DIR" "$FITNESS_DIR"

    log "Fetching data..."

    # === CORE ACTIVITY DATA ===
    local steps=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/steps/date/$DATE/1d.json")
    steps=$(validate_response "$steps" "steps")

    local calories=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/calories/date/$DATE/1d.json")
    calories=$(validate_response "$calories" "calories")

    local distance=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/distance/date/$DATE/1d.json")
    distance=$(validate_response "$distance" "distance")

    local floors=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/floors/date/$DATE/1d.json")
    floors=$(validate_response "$floors" "floors")

    local elevation=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/elevation/date/$DATE/1d.json")
    elevation=$(validate_response "$elevation" "elevation")

    # === ACTIVE MINUTES ===
    local minutes_sedentary=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/minutesSedentary/date/$DATE/1d.json")
    minutes_sedentary=$(validate_response "$minutes_sedentary" "minutesSedentary")

    local minutes_lightly_active=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/minutesLightlyActive/date/$DATE/1d.json")
    minutes_lightly_active=$(validate_response "$minutes_lightly_active" "minutesLightlyActive")

    local minutes_fairly_active=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/minutesFairlyActive/date/$DATE/1d.json")
    minutes_fairly_active=$(validate_response "$minutes_fairly_active" "minutesFairlyActive")

    local minutes_very_active=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/minutesVeryActive/date/$DATE/1d.json")
    minutes_very_active=$(validate_response "$minutes_very_active" "minutesVeryActive")

    # === HEART RATE ===
    local heart=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/heart/date/$DATE/1d.json")
    heart=$(validate_response "$heart" "heart")

    # Heart rate intraday (per-minute breakdown)
    local heart_intraday=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/heart/date/$DATE/1d/1min.json")
    heart_intraday=$(validate_response "$heart_intraday" "heart_intraday")

    # === HRV (Heart Rate Variability) ===
    local hrv=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/hrv/date/$DATE/all.json")
    hrv=$(validate_response "$hrv" "hrv")

    # === SLEEP ===
    local sleep=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1.2/user/-/sleep/date/$DATE.json")
    sleep=$(validate_response "$sleep" "sleep")

    # === BODY COMPOSITION ===
    local weight=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/body/log/weight/date/$DATE/1m.json")
    weight=$(validate_response "$weight" "weight")

    local body_fat=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/body/log/fat/date/$DATE/1m.json")
    body_fat=$(validate_response "$body_fat" "body_fat")

    # === ACTIVITIES ===
    local activities=$(curl -s -H "Authorization: Bearer $access_token" \
        "https://api.fitbit.com/1/user/-/activities/date/$DATE.json")
    activities=$(validate_response "$activities" "activities")

    # === COMBINE AND SAVE RAW JSON ===
    local combined=$(jq -n \
        --arg steps "$steps" \
        --arg calories "$calories" \
        --arg distance "$distance" \
        --arg floors "$floors" \
        --arg elevation "$elevation" \
        --arg minutes_sedentary "$minutes_sedentary" \
        --arg minutes_lightly_active "$minutes_lightly_active" \
        --arg minutes_fairly_active "$minutes_fairly_active" \
        --arg minutes_very_active "$minutes_very_active" \
        --arg heart "$heart" \
        --arg heart_intraday "$heart_intraday" \
        --arg hrv "$hrv" \
        --arg sleep "$sleep" \
        --arg weight "$weight" \
        --arg body_fat "$body_fat" \
        --arg activities "$activities" \
        --arg date "$DATE" \
        '{
            date: $date,
            steps: $steps,
            calories: $calories,
            distance: $distance,
            floors: $floors,
            elevation: $elevation,
            minutes_sedentary: $minutes_sedentary,
            minutes_lightly_active: $minutes_lightly_active,
            minutes_fairly_active: $minutes_fairly_active,
            minutes_very_active: $minutes_very_active,
            heart: $heart,
            heart_intraday: $heart_intraday,
            hrv: $hrv,
            sleep: $sleep,
            weight: $weight,
            body_fat: $body_fat,
            activities: $activities,
            fetchedAt: (now | todateiso8601)
        }')

    echo "$combined" | jq '.' > "$FITBIT_DIR/$DATE.json"
    log "Saved raw data to $FITBIT_DIR/$DATE.json"

    # === EXTRACT VALUES FOR LOG ===
    local steps_value=$(echo "$steps" | jq -r '.["activities-steps"][0].value // "0"')
    local heart_resting=$(echo "$heart" | jq -r '.["activities-heart"][0].value.restingHeartRate // "N/A"')
    
    # Sleep: sum all sleep sessions for total
    local sleep_total_minutes=$(echo "$sleep" | jq -r '.summary.totalMinutesAsleep // 0')
    local sleep_hours=$((sleep_total_minutes / 60))
    local sleep_minutes=$((sleep_total_minutes % 60))
    
    local weight_value=$(echo "$weight" | jq -r '.weight[0].weight // empty')
    local calories_value=$(echo "$calories" | jq -r '.["activities-calories"][0].value // "0"')
    local distance_value=$(echo "$distance" | jq -r '.["activities-distance"][0].value // "0"')
    
    # New fields
    local floors_value=$(echo "$floors" | jq -r '.["activities-floors"][0].value // "0"')
    local elevation_value=$(echo "$elevation" | jq -r '.["activities-elevation"][0].value // "0"')
    local sedentary_value=$(echo "$minutes_sedentary" | jq -r '.["activities-minutesSedentary"][0].value // "0"')
    local lightly_active_value=$(echo "$minutes_lightly_active" | jq -r '.["activities-minutesLightlyActive"][0].value // "0"')
    local fairly_active_value=$(echo "$minutes_fairly_active" | jq -r '.["activities-minutesFairlyActive"][0].value // "0"')
    local very_active_value=$(echo "$minutes_very_active" | jq -r '.["activities-minutesVeryActive"][0].value // "0"')
    local body_fat_value=$(echo "$body_fat" | jq -r '.fat[0].fat // empty')
    local bmi_value=$(echo "$weight" | jq -r '.weight[0].bmi // empty')
    
    # HRV - get daily average if available
    local hrv_daily_rmssd=$(echo "$hrv" | jq -r '[.hrv[0].minutes[]?.value.rmssd] | if length > 0 then (add / length * 10 | round / 10) else empty end' 2>/dev/null)
    
    # Sleep score (if available in Premium)
    local sleep_score=$(echo "$sleep" | jq -r '.sleep[0].efficiency // empty')

    # Update fitness log
    update_fitness_log \
        "$steps_value" "$heart_resting" "$sleep_hours" "$sleep_minutes" \
        "$weight_value" "$calories_value" "$distance_value" \
        "$floors_value" "$elevation_value" \
        "$sedentary_value" "$lightly_active_value" "$fairly_active_value" "$very_active_value" \
        "$body_fat_value" "$bmi_value" "$hrv_daily_rmssd" "$sleep_score" \
        "$DATE"

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
    local floors_value="$8"
    local elevation_value="$9"
    local sedentary_value="${10}"
    local lightly_active_value="${11}"
    local fairly_active_value="${12}"
    local very_active_value="${13}"
    local body_fat_value="${14}"
    local bmi_value="${15}"
    local hrv_rmssd="${16}"
    local sleep_efficiency="${17}"
    local date="${18}"

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
    cat > /tmp/fitbit-section.txt << EOF
## Fitbit Data

### Activity
- Steps: $steps_value
- Distance: $(printf '%.2f' "$distance_value") km
- Floors: $floors_value
- Elevation: $elevation_value meters

### Active Minutes
- Sedentary: $sedentary_value min
- Lightly Active: $lightly_active_value min
- Fairly Active: $fairly_active_value min
- Very Active: $very_active_value min

### Heart Rate
- Resting: $heart_resting bpm

### Heart Rate Variability (HRV)
- Daily RMSSD: ${hrv_rmssd:-N/A} ms

### Sleep
- Duration: ${sleep_hours}h ${sleep_minutes}m
- Efficiency: ${sleep_efficiency:-N/A}%

### Body Composition
EOF

    # Weight (if available)
    if [ -n "$weight_value" ] && [ "$weight_value" != "null" ]; then
        printf -- "- Weight: %.1f kg\n" "$weight_value" >> /tmp/fitbit-section.txt
    fi
    
    # BMI (if available)
    if [ -n "$bmi_value" ] && [ "$bmi_value" != "null" ]; then
        printf -- "- BMI: %.1f\n" "$bmi_value" >> /tmp/fitbit-section.txt
    fi
    
    # Body Fat (if available)
    if [ -n "$body_fat_value" ] && [ "$body_fat_value" != "null" ]; then
        printf -- "- Body Fat: %.1f%%\n" "$body_fat_value" >> /tmp/fitbit-section.txt
    fi

    echo "" >> /tmp/fitbit-section.txt
    echo "### Calories" >> /tmp/fitbit-section.txt
    echo "- Total Burned: $calories_value kcal" >> /tmp/fitbit-section.txt
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
    
    # Insert Fitbit section - try after Workout section, or append if no Workout section
    if grep -q "^## Workout" "$log_file"; then
        sed -i '/^## Workout/r /tmp/fitbit-section.txt' "$log_file"
    else
        # Prepend Fitbit section at the beginning (after any header)
        local header_line=$(head -1 "$log_file")
        local rest_content=$(tail -n +2 "$log_file")
        echo "$header_line" > "${log_file}.tmp"
        cat /tmp/fitbit-section.txt >> "${log_file}.tmp"
        echo "$rest_content" >> "${log_file}.tmp"
        mv "${log_file}.tmp" "$log_file"
    fi

    # Update daily stats
    local sleep_decimal=$(awk "BEGIN {printf \"%.1f\", $sleep_hours + $sleep_minutes/60}")
    
    if grep -q "^## Daily Stats" "$log_file"; then
        sed -i "s/- Steps: .*/- Steps: $steps_value/" "$log_file"
        sed -i "s/- Sleep: .*/- Sleep: ${sleep_decimal} h/" "$log_file"
        if [ -n "$weight_value" ] && [ "$weight_value" != "null" ]; then
            local weight_fmt=$(printf '%.1f' "$weight_value")
            sed -i "s/- Weight: .*/- Weight: $weight_fmt kg/" "$log_file"
        fi
    else
        # Add Daily Stats section
        echo "" >> "$log_file"
        echo "## Daily Stats" >> "$log_file"
        echo "- Steps: $steps_value" >> "$log_file"
        echo "- Sleep: ${sleep_decimal} h" >> "$log_file"
        if [ -n "$weight_value" ] && [ "$weight_value" != "null" ]; then
            local weight_fmt=$(printf '%.1f' "$weight_value")
            echo "- Weight: $weight_fmt kg" >> "$log_file"
        else
            echo "- Weight: [from Fitbit or manual]" >> "$log_file"
        fi
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
