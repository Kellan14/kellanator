import streamlit as st
import json
import pandas as pd
import subprocess
import os
import glob
import numpy as np
from io import BytesIO
import time

# For dynamic scraping with Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

#####################################
# 1. Repository Management
#####################################
def ensure_repo(repo_url, repo_dir):
    """Clone the repository if it doesn't exist or isn't a valid git repo."""
    git_folder = os.path.join(repo_dir, ".git")
    if not os.path.exists(repo_dir) or not os.path.exists(git_folder):
        placeholder = st.empty()
        placeholder.info("Repository not found. Cloning repository...")
        result = subprocess.run(["git", "clone", repo_url, repo_dir], capture_output=True, text=True)
        if result.returncode == 0:
            placeholder.success("Repository cloned successfully!")
        else:
            placeholder.error(f"Error cloning repository: {result.stderr}")
        time.sleep(1)
        placeholder.empty()
        return ""
    else:
        placeholder = st.empty()
        placeholder.info("Repository is already cloned.")
        time.sleep(1)
        placeholder.empty()
        return ""

repository_url = 'https://github.com/Invader-Zim/mnp-data-archive'
repo_dir = os.path.join(os.getcwd(), "mnp-data-archive")
ensure_repo(repository_url, repo_dir)

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

st.title("MNP Data Archive Processor")

if st.button("Check for Updates from GitHub"):
    update_output = update_repo(repo_dir)
    update_placeholder = st.empty()
    update_placeholder.success(f"Repository update result:\n{update_output}")
    time.sleep(1)
    update_placeholder.empty()

#####################################
# 2. Dynamic Scraping: Teams & Venues
#####################################
@st.cache_data(show_spinner=True)
def get_dynamic_teams_and_venues():
    """
    Scrapes the teams page to obtain:
      - Unique venue names (from the first column)
      - A list of full team names (from the link text in the second column)
      - A dictionary mapping full team name -> abbreviation (extracted from the link URL)
    """
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://mondaynightpinball.com/teams")
    driver.implicitly_wait(5)
    
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

#####################################
# 3. User Selections
#####################################
selected_venue = st.selectbox("Select Venue", dynamic_venues)
selected_team = st.selectbox("Select Team", dynamic_team_names)

#####################################
# 4. Automatic Roster Scraping
#####################################
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

with st.spinner("Automatically scraping team rosters..."):
    roster_data = get_team_rosters(team_abbr_dict)

roster_placeholder = st.empty()
with roster_placeholder.container():
    st.markdown("### Roster Scraping Results")
    for team, roster in roster_data.items():
        if roster:
            st.write(f"✅ {team}: {len(roster)} players found")
        else:
            st.write(f"❌ {team}: No roster found")
time.sleep(1)
roster_placeholder.empty()

#####################################
# 5. Column Options for Venue Specific Toggle
#####################################
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
for col, config in initial_column_config.items():
    venue_spec = st.checkbox(f"{col} Venue Specific", value=config['venue_specific'])
    column_config[col] = {
        'seasons': config['seasons'],
        'venue_specific': venue_spec,
        'backfill': config['backfill']
    }

#####################################
# 6. Season Selection
#####################################
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

#####################################
# 7. Load All JSON Files from the Repository
#####################################
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

#####################################
# 8. Processing Functions (Full Logic)
#####################################
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

included_machines = []
excluded_machines = ['whitewater', 'mousin', 'spiderman']
max_scores = {'jaws': 10000000000, 'godzilla':20000000000}

def process_all_rounds_and_games(all_data, team_name, venue_name, twc_team_name, team_roster):
    processed_data = []
    recent_machines = set(included_machines or [])
    overall_latest_season = max(int(match['key'].split('-')[1]) for match in all_data)
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
                if season == overall_latest_season and match_venue == venue_name:
                    if not excluded_machines or machine not in excluded_machines:
                        recent_machines.add(machine)
                is_team_pick = False
                if machine not in machines_played_this_round:
                    if team_name == away_team and round_number in [1,3]:
                        is_team_pick = True
                    elif team_name == home_team and round_number in [2,4]:
                        is_team_pick = True
                machines_played_this_round.add(machine)
                for pos in ['1','2','3','4']:
                    player_key = game.get(f'player_{pos}')
                    score = game.get(f'score_{pos}', 0)
                    if score == 0:
                        continue
                    if machine in max_scores and score > max_scores[machine]:
                        continue
                    player_name = get_player_name(player_key, match)
                    player_team = home_team if any(player['key'] == player_key for player in match['home']['lineup']) else away_team
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
        backfill_df = filter_data(df, team, (season, season), venue_name if venue_specific else None)
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
            seasons = config['seasons']
            venue_specific = config['venue_specific']
            backfill = config['backfill']
            roster_only = False
            if column.startswith('Team') or column.startswith('TWC'):
                roster_only = True
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
            row[column] = format_value(value, backfilled_season)
        try:
            team_avg = float(row['Team Average'].split('*')[0].replace(',', ''))
        except:
            team_avg = np.nan
        try:
            twc_avg = float(row['TWC Average'].split('*')[0].replace(',', ''))
        except:
            twc_avg = np.nan
        try:
            venue_avg = float(row['Venue Average'].split('*')[0].replace(',', ''))
        except:
            venue_avg = np.nan
        if not np.isnan(team_avg) and not np.isnan(venue_avg) and venue_avg != 0:
            row['% of V. Avg.'] = f"{(team_avg / venue_avg * 100):.2f}%"
        else:
            row['% of V. Avg.'] = "N/A"
        if not np.isnan(twc_avg) and not np.isnan(venue_avg) and venue_avg != 0:
            row['TWC % V. Avg.'] = f"{(twc_avg / venue_avg * 100):.2f}%"
            if '*' in row['TWC Average']:
                row['TWC % V. Avg.'] += '*' + row['TWC Average'].split('*')[1]
        else:
            row['TWC % V. Avg.'] = "N/A"
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
    all_data_df, recent_machines = process_all_rounds_and_games(all_data, team_name, selected_venue, twc_team_name, team_roster)
    debug_outputs = generate_debug_outputs(all_data_df, team_name, twc_team_name, selected_venue)
    result_df = calculate_averages(all_data_df, recent_machines, team_name, twc_team_name, selected_venue, column_config)
    return result_df, debug_outputs

#####################################
# 9. "Kellanate" Button & Excel Download
#####################################
if st.button("Kellanate"):
    with st.spinner("Loading JSON files from repository and processing data..."):
        all_data = load_all_json_files(repo_dir, seasons_to_process)
        result_df, debug_outputs = main(all_data, selected_team, selected_venue, roster_data, column_config)
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
