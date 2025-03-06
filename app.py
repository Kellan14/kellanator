##############################################
# Section 1: Imports & Session State Setup
##############################################
import streamlit as st
import json
import pandas as pd
import subprocess
import os
import glob
import numpy as np
from io import BytesIO
import time

from db_helper import init_db, get_score_limits, set_score_limit, delete_score_limit, get_venue_machine_list, add_machine_to_venue, delete_machine_from_venue


# For dynamic scraping with Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Initialize session state variables if not present
if "roster_data" not in st.session_state:
    st.session_state.roster_data = None
if "rosters_scraped" not in st.session_state:
    st.session_state.rosters_scraped = False
if "modify_menu_open" not in st.session_state:
    st.session_state.modify_menu_open = False

##############################################
# Section 2: Repository Management
##############################################
def ensure_repo(repo_url, repo_dir):
    """Clone the repository if it doesn't exist or isn't a valid git repo."""
    git_folder = os.path.join(repo_dir, ".git")
    placeholder = st.empty()
    if not os.path.exists(repo_dir) or not os.path.exists(git_folder):
        placeholder.info("Repository not found. Cloning repository...")
        result = subprocess.run(["git", "clone", repo_url, repo_dir], capture_output=True, text=True)
        if result.returncode == 0:
            placeholder.success("Repository cloned successfully!")
        else:
            placeholder.error(f"Error cloning repository: {result.stderr}")
        time.sleep(1)
        placeholder.empty()
    else:
        placeholder.info("Repository is already cloned.")
        time.sleep(1)
        placeholder.empty()

def update_repo(repo_path):
    """Runs 'git pull' in the specified repository directory."""
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "pull"],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        return f"An error occurred: {e.stderr}"

repository_url = 'https://github.com/Invader-Zim/mnp-data-archive'
# Update this path to your new absolute or relative path:
repo_dir = r"D:\Streamlit Apps\mnp-data-archive"
ensure_repo(repository_url, repo_dir)

st.title("MNP Data Archive Processor")
if st.button("Check for Updates from GitHub"):
    update_output = update_repo(repo_dir)
    update_placeholder = st.empty()
    update_placeholder.success(f"Repository update result:\n{update_output}")
    time.sleep(1)
    update_placeholder.empty()

##############################################
# Section 3: Dynamic Scraping – Teams & Venues
##############################################
@st.cache_data(show_spinner=True)
def get_dynamic_teams_and_venues():
    """
    Scrapes the teams page to obtain:
      - Unique venue names (first column)
      - A list of full team names (link text from the second column)
      - A dictionary mapping full team name -> abbreviation (from the link URL)
    """
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # Uncomment and adjust the following line if needed (check your logs for the correct binary location)
    # options.binary_location = "/usr/bin/chromium-browser"
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://mondaynightpinball.com/teams")
    driver.implicitly_wait(10)  # Increase wait time if needed
    
    rows = driver.find_elements(By.XPATH, "/html/body/div[2]/table/tbody/tr")
    venues = []
    team_names = []
    team_abbr_dict = {}
    for row in rows:
        try:
            venue_text = row.find_element(By.XPATH, "./td[1]").text.strip()
            venues.append(venue_text)
            team_link = row.find_element(By.XPATH, "./td[2]/a")
            full_team_name = team_link.text.strip()
            team_names.append(full_team_name)
            href = team_link.get_attribute("href")
            abbr = href.rstrip("/").split("/")[-1]
            team_abbr_dict[full_team_name] = abbr
        except Exception:
            continue
    unique_venues = list(dict.fromkeys(venues))
    driver.quit()
    return unique_venues, team_names, team_abbr_dict




teams_status = st.empty()
teams_status.info("Loading dynamic teams and venues...")
dynamic_venues, dynamic_team_names, team_abbr_dict = get_dynamic_teams_and_venues()
teams_status.success("Dynamic teams and venues loaded!")
time.sleep(1)
teams_status.empty()

##############################################
# Section 4: Get Unique Machine List from JSON Data
##############################################
@st.cache_data(show_spinner=True)
def get_all_machines(repo_dir):
    """
    Scans all JSON files in the repository (for seasons 14-21) and returns a sorted list of
    unique machine names from the 'machine' field.
    """
    machine_set = set()
    for season in range(14, 22):
        directory = os.path.join(repo_dir, f"season-{season}", "matches")
        json_files = glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)
        for file_path in json_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for round_info in data.get("rounds", []):
                        for game in round_info.get("games", []):
                            machine = game.get("machine", "").strip()
                            if machine:
                                machine_set.add(machine.lower())
            except Exception:
                continue
    return sorted(machine_set)

all_machines_from_data = get_all_machines(repo_dir)

##############################################
# Section 5: User Selections
##############################################
selected_venue = st.selectbox("Select Venue", dynamic_venues)
selected_team = st.selectbox("Select Team", dynamic_team_names)

##############################################
# Section 6: Column Options for Venue Specific Toggle & Column Inclusion
##############################################
st.markdown("### Column Options")

initial_column_config = {
    'Team Average': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'TWC Average': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'Venue Average': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'Team Highest Score': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    '% of V. Avg.': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'TWC % V. Avg.': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'Times Played': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'TWC Times Played': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'Times Picked': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
    'TWC Times Picked': {'seasons': (20, 21), 'venue_specific': True, 'backfill': False}
}

column_config = {}

st.markdown("#### Select Columns to Include & Venue Specific Settings")
for col, config in initial_column_config.items():
    col1, col2 = st.columns([0.6, 0.4])  # First column (Include), Second column (Venue Specific)
    
    with col1:
        include_column = st.checkbox(f"Include {col}", value=True, key=f"inc_{col}")
    
    with col2:
        venue_spec = st.checkbox(f"Venue Specific", value=config['venue_specific'], key=f"vs_{col}")

    column_config[col] = {
        'include': include_column,  # Controls whether to compute this column
        'seasons': config['seasons'],
        'venue_specific': venue_spec,
        'backfill': config['backfill']
    }
    
##############################################
# Section 6.5: Set Machine Score Limit (Database Version using st.rerun())
##############################################
import re  # For cleaning up score strings

st.markdown("### Set Machine Score Limit (Persistent)")

# Retrieve current score limits from the database.
current_score_limits = get_score_limits()
st.write("Current Score Limits:", current_score_limits)

# Allow the user to add a new score limit.
available_machines = [m for m in all_machines_from_data if m not in current_score_limits]
new_machine = st.selectbox("Select Machine", options=available_machines, key="score_limit_machine_dropdown")
new_machine_text = st.text_input("Or type machine name", "", key="score_limit_machine_text")
machine_to_add = new_machine_text.strip() if new_machine_text.strip() else new_machine

new_score_str = st.text_input("Enter Score Limit", "", key="score_limit_value")
if st.button("Add Score Limit", key="add_score_limit_btn"):
    try:
        cleaned = re.sub(r"[^\d,]", "", new_score_str)
        score_limit = int(cleaned.replace(",", "").strip())
        if machine_to_add:
            set_score_limit(machine_to_add, score_limit)
            st.success(f"Score limit for {machine_to_add} set to {score_limit:,}")
            st.rerun()
    except Exception as e:
        st.error("Invalid score input. Please enter a valid number (commas allowed).")

# Display current score limits with options to edit or delete.
for machine, limit in current_score_limits.items():
    col1, col2, col3 = st.columns([0.5, 0.3, 0.2])
    col1.write(machine)
    col2.write(f"{limit:,}")  # display with comma formatting
    if col3.button("🗑️", key=f"del_score_{machine}"):
        delete_score_limit(machine)
        st.rerun()
    # Inline editing (not nested in an expander)
    new_edit_score = st.text_input(f"Edit {machine} Score Limit", value=f"{limit:,}", key=f"edit_{machine}")
    if st.button("Update", key=f"update_{machine}"):
        try:
            updated_score = int(new_edit_score.replace(",", "").strip())
            set_score_limit(machine, updated_score)
            st.success(f"Updated {machine} score limit to {updated_score:,}")
            st.rerun()
        except Exception as e:
            st.error("Invalid score. Please enter a valid number.")

if st.button("Refresh Score Limits"):
    st.rerun()



##############################################
# Section 7: Modify Venue Machine List (Database Version)
##############################################
if st.button("Modify Venue Machine List"):
    st.session_state.modify_menu_open = True

if st.session_state.modify_menu_open:
    with st.expander("Modify Venue Machine List", expanded=True):
        st.markdown("#### Included Machines")
        # Retrieve included machines from the database for the selected venue.
        included_machines = get_venue_machine_list(selected_venue, "included")
        for machine in included_machines:
            col1, col2 = st.columns([0.8, 0.2])
            col1.write(machine)
            if col2.button("🗑️", key=f"del_inc_{machine}_{selected_venue}"):
                delete_machine_from_venue(selected_venue, "included", machine)
                st.rerun()
        
        st.markdown("Add machine to **Included**:")
        available_included = [m for m in all_machines_from_data if m not in included_machines]
        add_inc_dropdown = st.selectbox("Select from list", options=available_included, key=f"add_inc_dropdown_{selected_venue}")
        add_inc_text = st.text_input("Or type machine name (must match format)", "", key=f"add_inc_text_{selected_venue}")
        if st.button("Add to Included", key=f"add_inc_btn_{selected_venue}"):
            new_machine = add_inc_text.strip() if add_inc_text.strip() else add_inc_dropdown
            if new_machine:
                add_machine_to_venue(selected_venue, "included", new_machine)
                st.rerun()
        
        st.markdown("#### Excluded Machines")
        excluded_machines = get_venue_machine_list(selected_venue, "excluded")
        for machine in excluded_machines:
            col1, col2 = st.columns([0.8, 0.2])
            col1.write(machine)
            if col2.button("🗑️", key=f"del_exc_{machine}_{selected_venue}"):
                delete_machine_from_venue(selected_venue, "excluded", machine)
                st.rerun()
        st.markdown("Add machine to **Excluded**:")
        available_excluded = [m for m in all_machines_from_data if m not in excluded_machines]
        add_exc_dropdown = st.selectbox("Select from list", options=available_excluded, key=f"add_exc_dropdown_{selected_venue}")
        add_exc_text = st.text_input("Or type machine name (must match format)", "", key=f"add_exc_text_{selected_venue}")
        if st.button("Add to Excluded", key=f"add_exc_btn_{selected_venue}"):
            new_machine = add_exc_text.strip() if add_exc_text.strip() else add_exc_dropdown
            if new_machine:
                add_machine_to_venue(selected_venue, "excluded", new_machine)
                st.rerun()
        
        if st.button("Close Modify Menu"):
            st.session_state.modify_menu_open = False
            st.rerun()
    st.stop()


##############################################
# Section 8: Automatic Roster Scraping (Once)
##############################################
@st.cache_data(show_spinner=True)
def get_team_rosters(team_abbr_dict):
    """
    Automatically scrapes rosters for all teams using their abbreviations.
    Returns a dictionary mapping full team names to their roster (list of players) or None.
    """
    rosters = {}
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    for team_full, abbr in team_abbr_dict.items():
        team_url = f"https://mondaynightpinball.com/teams/{abbr}"
        driver.get(team_url)
        driver.implicitly_wait(5)
        try:
            players = [elem.text for elem in driver.find_elements(By.XPATH, "//table[2]//tr/td[1]/a")]
            rosters[team_full] = players if players else None
        except Exception:
            rosters[team_full] = None
    driver.quit()
    return rosters

if not st.session_state.rosters_scraped:
    with st.spinner("Automatically scraping team rosters..."):
        st.session_state.roster_data = get_team_rosters(team_abbr_dict)
        st.session_state.rosters_scraped = True
    roster_placeholder = st.empty()
    with roster_placeholder.container():
        st.markdown("### Roster Scraping Results")
        for team, roster in st.session_state.roster_data.items():
            if roster:
                st.write(f"✅ {team}: {len(roster)} players found")
            else:
                st.write(f"❌ {team}: No roster found")
    time.sleep(1)
    roster_placeholder.empty()

##############################################
# Section 9: Season Selection
##############################################
def parse_seasons(season_str):
    """Parses the season input string into a list of integers."""
    season_str = season_str.replace(" ", "")
    seasons = []
    if "-" in season_str:
        parts = season_str.split("-")
        try:
            start = int(parts[0])
            end = int(parts[1])
            seasons = list(range(start, end + 1))
        except:
            st.error("Invalid season range format. Please enter something like '20-21'.")
    elif "," in season_str:
        parts = season_str.split(",")
        try:
            seasons = [int(p) for p in parts]
        except:
            st.error("Invalid season list format. Please enter something like '14,16,19'.")
    else:
        try:
            seasons = [int(season_str)]
        except:
            st.error("Invalid season format. Please enter a number, e.g. '19'.")
    return seasons

season_input = st.text_input("Enter season(s) to process (e.g., '19' or '20-21')", "14-21")
seasons_to_process = parse_seasons(season_input)

##############################################
# Section 10: Load All JSON Files from Repository
##############################################
def load_all_json_files(repo_dir, seasons):
    """
    Scans the repository for JSON files in season directories (e.g., season-14/matches, etc.).
    Shows a warning if no files are found for a season.
    """
    all_data = []
    for season in seasons:
        directory = os.path.join(repo_dir, f"season-{season}", "matches")
        json_files = glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)
        if not json_files:
            st.warning(f"No JSON files found for season {season}.")
        for file_path in json_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    all_data.append(data)
            except Exception as e:
                st.error(f"Error loading {file_path}: {e}")
    return all_data

##############################################
# Section 11: Processing Functions (Full Logic)
##############################################
def standardize_machine_name(machine_name):
    machine_mapping = {
        'pulp': 'pulp fiction',
        'pulp fiction': 'pulp fiction',
        'bksor': 'black knight sor',
    }
    return machine_mapping.get(machine_name.lower(), machine_name.lower())

def get_player_name(player_key, match):
    for team in ['home', 'away']:
        for player in match[team]['lineup']:
            if player['key'] == player_key:
                return player['name']
    return player_key

def is_roster_player(player_name, team, team_roster):
    return player_name in team_roster.get(team, [])

def process_all_rounds_and_games(all_data, team_name, venue_name, twc_team_name, team_roster, included_machines_for_venue, excluded_machines_for_venue):
    processed_data = []
    # Initialize recent_machines from the included list (if provided)
    recent_machines = set(included_machines_for_venue or [])
    overall_latest_season = max(int(match['key'].split('-')[1]) for match in all_data)
    
    # Retrieve the current user-defined score limits from the database.
    current_limits = get_score_limits()  # This returns a dict: {machine: score_limit}

    for match in all_data:
        match_venue = match['venue']['name']
        season = int(match['key'].split('-')[1])
        home_team = match['home']['name']
        away_team = match['away']['name']

        for round_info in match['rounds']:
            round_number = round_info['n']
            picking_team = away_team if round_number in [1, 3] else home_team
            machines_played_this_round = set()

            for game in round_info['games']:
                machine = standardize_machine_name(game.get('machine', '').lower())
                if not machine:
                    continue

                # If the match is in the latest season at the selected venue,
                # and if the machine isn't excluded, add it to recent_machines.
                if season == overall_latest_season and match_venue == venue_name:
                    if not excluded_machines_for_venue or machine not in excluded_machines_for_venue:
                        recent_machines.add(machine)

                # Determine if this game is a pick for the team.
                is_team_pick = False
                if machine not in machines_played_this_round:
                    if team_name == away_team and round_number in [1, 3]:
                        is_team_pick = True
                    elif team_name == home_team and round_number in [2, 4]:
                        is_team_pick = True
                machines_played_this_round.add(machine)

                for pos in ['1', '2', '3', '4']:
                    player_key = game.get(f'player_{pos}')
                    score = game.get(f'score_{pos}', 0)
                    if score == 0:
                        continue

                    # Check if a user-defined score limit exists for this machine.
                    limit = current_limits.get(machine)
                    # If a limit exists and the score exceeds it, skip this score.
                    if limit is not None and score > limit:
                        continue

                    player_name = get_player_name(player_key, match)
                    player_team = (home_team if any(player['key'] == player_key for player in match['home']['lineup'])
                                   else away_team)

                    processed_data.append({
                        'season': season,
                        'machine': machine,
                        'player_name': player_name,
                        'score': score,
                        'team': player_team,
                        'match': match['key'],
                        'round': round_number,
                        'game_number': game['n'],
                        'venue': match_venue,
                        'picked_by': picking_team,
                        'is_pick': is_team_pick,
                        'is_roster_player': is_roster_player(player_name, player_team, team_roster)
                    })

    return pd.DataFrame(processed_data), recent_machines

def filter_data(df, team=None, seasons=None, venue=None, roster_only=False):
    filtered = df.copy()
    if team:
        filtered = filtered[filtered['team'] == team]
        if roster_only:
            filtered = filtered[filtered['is_roster_player']]
    if seasons:
        filtered = filtered[filtered['season'].between(seasons[0], seasons[1])]
    if venue:
        filtered = filtered[filtered['venue'] == venue]
    return filtered

def calculate_stats(df, machine):
    machine_data = df[df['machine'] == machine]
    unique_rounds = machine_data.groupby(['match', 'round']).size().reset_index(name='count')
    times_played = len(unique_rounds)
    unique_picks = machine_data[machine_data['is_pick']].groupby(['match', 'round']).size().reset_index(name='count')
    times_picked = len(unique_picks)
    scores = machine_data['score'].tolist()
    return {
        'average': np.mean(scores) if scores else np.nan,
        'highest': max(scores) if scores else 0,
        'times_played': times_played,
        'times_picked': times_picked
    }

def backfill_stat(df, machine, team, seasons, venue_specific, stat_type):
    for season in range(seasons[0]-1, 0, -1):
        backfill_df = filter_data(df, team, (season, season), venue if venue_specific else None)
        stats = calculate_stats(backfill_df, machine)
        if stat_type in stats and stats[stat_type] > 0:
            return stats[stat_type], season
    return np.nan, None

def format_value(value, backfilled_season=None):
    if isinstance(value, (int, float)):
        formatted = f"{value:,.0f}"
    elif isinstance(value, str):
        formatted = value
    else:
        formatted = "N/A"
    if backfilled_season is not None:
        formatted += f"*S{backfilled_season}"
    return formatted

def calculate_averages(df, recent_machines, team_name, twc_team_name, venue_name, column_config):
    data = []
    for machine in sorted(recent_machines):
        row = {'Machine': machine.title()}
        for column, config in column_config.items():
            # Skip this column if it's not included.
            if not config.get('include', True):
                continue

            seasons = config['seasons']
            venue_specific = config['venue_specific']
            backfill = config['backfill']
            roster_only = True if column.startswith('Team') or column.startswith('TWC') else False

            # Decide which team to use for filtering.
            if column.startswith('Team') or column == 'Times Played' or column == 'Times Picked':
                team = team_name
            elif column.startswith('TWC'):
                team = twc_team_name
            else:
                team = None

            filtered_df = filter_data(df, team, seasons, venue_name if venue_specific else None, roster_only=roster_only)
            stats = calculate_stats(filtered_df, machine)
            
            if column == 'Team Highest Score':
                value = stats['highest']
            elif 'Average' in column:
                value = stats['average']
            elif 'Times Played' in column:
                value = stats['times_played']
            elif 'Times Picked' in column:
                value = stats['times_picked']
            else:
                value = np.nan

            backfilled_season = None
            if backfill and (np.isnan(value) or value == 0):
                stat_type = 'average' if 'Average' in column else 'times_played' if 'Times Played' in column else 'times_picked'
                value, backfilled_season = backfill_stat(df, machine, team, seasons, venue_specific, stat_type)
            
            # Format the value for display.
            if not np.isnan(value):
                if 'Average' in column:
                    formatted = f"{value:,.2f}"
                else:
                    formatted = f"{value:,}"
                if backfilled_season is not None:
                    formatted += f"*S{backfilled_season}"
                row[column] = formatted
            else:
                row[column] = "N/A"

        # Safely retrieve the three main averages.
        def safe_get(key):
            v = row.get(key, "N/A")
            try:
                # Remove commas, split on '*' if present.
                return float(v.replace(",", "").split("*")[0])
            except Exception:
                return np.nan

        team_avg = safe_get("Team Average")
        twc_avg = safe_get("TWC Average")
        venue_avg = safe_get("Venue Average")

        # Calculate percentages if possible.
        if not np.isnan(team_avg) and not np.isnan(venue_avg) and venue_avg != 0:
            row["% of V. Avg."] = f"{(team_avg / venue_avg * 100):.2f}%"
        else:
            row["% of V. Avg."] = "N/A"

        if not np.isnan(twc_avg) and not np.isnan(venue_avg) and venue_avg != 0:
            row["TWC % V. Avg."] = f"{(twc_avg / venue_avg * 100):.2f}%"
        else:
            row["TWC % V. Avg."] = "N/A"

        data.append(row)

    return pd.DataFrame(data)


def generate_debug_outputs(df, team_name, twc_team_name, venue_name):
    debug_outputs = {
        'all_data': df,
        'filtered_data_by_team': filter_data(df, team_name),
        'filtered_data_by_team_and_seasons': filter_data(df, team_name, (20, 21)),
        'filtered_data_by_team_seasons_and_venue': filter_data(df, team_name, (20, 21), venue_name),
        'filtered_data_by_twc': filter_data(df, twc_team_name),
        'filtered_data_by_twc_and_seasons': filter_data(df, twc_team_name, (20, 21)),
        'filtered_data_by_twc_seasons_and_venue': filter_data(df, twc_team_name, (20, 21), venue_name),
    }
    return debug_outputs

def main(all_data, selected_team, selected_venue, team_roster, column_config):
    team_name = selected_team
    twc_team_name = "The Wrecking Crew"
    key_inc = f'included_machines_{selected_venue}'
    key_exc = f'excluded_machines_{selected_venue}'
    included_list = st.session_state.get(key_inc, [])
    excluded_list = st.session_state.get(key_exc, ['whitewater', 'mousin', 'spiderman'])
    all_data_df, recent_machines = process_all_rounds_and_games(
        all_data, team_name, selected_venue, twc_team_name, team_roster,
        included_list, excluded_list
    )
    debug_outputs = generate_debug_outputs(all_data_df, team_name, twc_team_name, selected_venue)
    result_df = calculate_averages(all_data_df, recent_machines, team_name, twc_team_name, selected_venue, column_config)
    return result_df, debug_outputs

##############################################
# Section 12: "Kellanate" Button & Excel Download
##############################################
if st.button("Kellanate"):
    with st.spinner("Loading JSON files from repository and processing data..."):
        all_data = load_all_json_files(repo_dir, seasons_to_process)
        result_df, debug_outputs = main(all_data, selected_team, selected_venue, st.session_state.roster_data, column_config)
        # Save debug outputs in session state for later use.
        st.session_state.debug_outputs = debug_outputs
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Results')
        processed_excel = output.getvalue()
    success_placeholder = st.empty()
    success_placeholder.success("Data processed successfully!")
    time.sleep(1)
    success_placeholder.empty()
    st.download_button(
        label="Download Excel file",
        data=processed_excel,
        file_name="final_stats.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    st.dataframe(result_df)


##############################################
# Section 12.5: Optional Debug Outputs Toggle
##############################################
if st.checkbox("Show Debug Outputs"):
    if "debug_outputs" in st.session_state:
        for name, debug_df in st.session_state.debug_outputs.items():
            st.markdown(f"### Debug Output: {name}")
            st.dataframe(debug_df)
    else:
        st.info("No debug outputs available. Please run 'Kellanate' first.")


