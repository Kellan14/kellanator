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
import re
import requests
from bs4 import BeautifulSoup
from st_aggrid import AgGrid, GridOptionsBuilder

# Import database helper functions (ensure you have db_helper.py in your repo)
from db_helper import init_db, get_score_limits, set_score_limit, delete_score_limit, \
    get_venue_machine_list, add_machine_to_venue, delete_machine_from_venue

# Initialize database (if not already)
init_db()

# Initialize session state flags
if "roster_data" not in st.session_state:
    st.session_state.roster_data = None
if "rosters_scraped" not in st.session_state:
    st.session_state.rosters_scraped = False
if "modify_menu_open" not in st.session_state:
    st.session_state.modify_menu_open = False
if "column_options_open" not in st.session_state:
    st.session_state.column_options_open = False
if "set_score_limit_open" not in st.session_state:
    st.session_state.set_score_limit_open = False

##############################################
# Section 1.1: Load All JSON Files from Repository
##############################################
def load_all_json_files(repo_dir, seasons):
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
# Section 1.1: Season Selection
##############################################
def parse_seasons(season_str):
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

season_input = st.text_input("Enter season(s) to process (e.g., '19' or '20-21')", "20-21")
seasons_to_process = parse_seasons(season_input)

##############################################
# Section 2: Repository Management
##############################################

# Path to store the machine mapping file.
MACHINE_MAPPING_FILE = "machine_mapping.json"

def load_machine_mapping(file_path):
    """Load machine mapping from a JSON file. Return default mapping if file doesn't exist."""
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading machine mapping: {e}")
            return {}
    else:
        # Default mapping.
        return {
            'pulp': 'pulp fiction',
            'bksor': 'black knight sor'
        }

# Initialize persistent machine mapping in session state if not already set.
if "machine_mapping" not in st.session_state:
    st.session_state.machine_mapping = load_machine_mapping(MACHINE_MAPPING_FILE)

def save_machine_mapping(file_path, mapping):
    """Save the machine mapping to a JSON file."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2)
    except Exception as e:
        st.error(f"Error saving machine mapping: {e}")

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
# Update this path as needed
repo_dir = r"D:\Streamlit Apps\mnp-data-archive"
ensure_repo(repository_url, repo_dir)

st.title("The Kellanator 9000")
if st.button("Check for Updates from GitHub", key="update_repo_btn"):
    update_output = update_repo(repo_dir)
    update_placeholder = st.empty()
    update_placeholder.success(f"Repository update result:\n{update_output}")
    time.sleep(1)
    update_placeholder.empty()

##############################################
# Section 3: Dynamic Teams & Venues from JSON Files (Most Recent Season Only)
##############################################
import glob
import json
import os
import re

def get_latest_season(repo_dir):
    """
    Scans the repository directory for folders named "season-<number>" 
    and returns the highest season number found.
    """
    season_dirs = glob.glob(os.path.join(repo_dir, "season-*"))
    season_numbers = []
    for season_dir in season_dirs:
        match = re.search(r"season-(\d+)", season_dir)
        if match:
            season_numbers.append(int(match.group(1)))
    if season_numbers:
        return max(season_numbers)
    else:
        return None

@st.cache_data(show_spinner=True)
def get_teams_and_venues_from_json(repo_dir):
    """
    Scans through the JSON files for the most recent season and extracts:
      - Venues: from data["venue"]["name"]
      - Teams: from data["away"] and data["home"] (using their "name" and "key")
    Returns:
      - A sorted list of unique venue names.
      - A sorted list of unique team names.
      - A dictionary mapping team names to their abbreviations (keys).
    """
    latest_season = get_latest_season(repo_dir)
    if latest_season is None:
        st.error("No season directories found in the repository.")
        return [], [], {}
    
    venues = set()
    team_abbr_dict = {}
    directory = os.path.join(repo_dir, f"season-{latest_season}", "matches")
    json_files = glob.glob(os.path.join(directory, "**", "*.json"), recursive=True)
    
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Extract venue
                venue_name = data.get("venue", {}).get("name", "")
                if venue_name:
                    venues.add(venue_name)
                
                # Extract away team info
                away = data.get("away", {})
                if away:
                    team_name = away.get("name", "")
                    team_key = away.get("key", "")
                    if team_name:
                        team_abbr_dict[team_name] = team_key
                
                # Extract home team info
                home = data.get("home", {})
                if home:
                    team_name = home.get("name", "")
                    team_key = home.get("key", "")
                    if team_name:
                        team_abbr_dict[team_name] = team_key
        except Exception as e:
            st.error(f"Error loading {file_path}: {e}")
    
    # Sort the results alphabetically
    venues_list = sorted(list(venues))
    team_names = sorted(list(team_abbr_dict.keys()))
    return venues_list, team_names, team_abbr_dict

# Retrieve teams and venues from JSON files (most recent season only)
dynamic_venues, dynamic_team_names, team_abbr_dict = get_teams_and_venues_from_json(repo_dir)

# Use these select boxes (only one set)
selected_venue = st.selectbox("Select Venue", dynamic_venues, key="select_venue_json")
selected_team = st.selectbox("Select Team", dynamic_team_names, key="select_team_json")

##############################################
# Section 4: Get Unique Machine List from JSON Data
##############################################
@st.cache_data(show_spinner=True)
def get_all_machines(repo_dir):
    """
    Scans JSON files (seasons 14-21) and returns a sorted list of unique machine names.
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
# Section 5.1: Toggle and Display Column Options (Persistent)
##############################################
# Initialize persistent column configuration if not already set.
if "column_config" not in st.session_state:
    default_twcs = True if selected_venue.lower() == "georgetown pizza and arcade" else False
    st.session_state.column_config = {
         'Team Average': {'include': True, 'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
         'TWC Average': {'include': True, 'seasons': (20, 21), 'venue_specific': default_twcs, 'backfill': False},
         'Venue Average': {'include': True, 'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
         'Team Highest Score': {'include': True, 'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
         '% of V. Avg.': {'include': True, 'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
         'TWC % V. Avg.': {'include': True, 'seasons': (20, 21), 'venue_specific': default_twcs, 'backfill': False},
         'Times Played': {'include': True, 'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
         'TWC Times Played': {'include': True, 'seasons': (20, 21), 'venue_specific': default_twcs, 'backfill': False},
         'Times Picked': {'include': True, 'seasons': (20, 21), 'venue_specific': True, 'backfill': False},
         'TWC Times Picked': {'include': True, 'seasons': (20, 21), 'venue_specific': default_twcs, 'backfill': False}
    }

# Toggle Column Options display.
if st.button("Hide Column Options" if st.session_state.column_options_open else "Show Column Options", key="toggle_column_options"):
    st.session_state.column_options_open = not st.session_state.column_options_open
    st.rerun()

# When open, display the options and update the persistent config.
if st.session_state.column_options_open:
    st.markdown("#### Column Options")
    current_config = st.session_state.column_config  # Use the saved config
    updated_config = {}
    for col, config in current_config.items():
        col1, col2 = st.columns([0.6, 0.4])
        with col1:
            include_column = st.checkbox(f"{col}", value=config.get("include", True), key=f"inc_{col}")
        with col2:
            venue_spec = st.checkbox("Venue Specific", value=config.get("venue_specific", False), key=f"vs_{col}")
        updated_config[col] = {
            'include': include_column,
            'seasons': config['seasons'],  # Assume seasons/backfill remain unchanged.
            'venue_specific': venue_spec,
            'backfill': config['backfill']
        }
    # Update the persistent column_config.
    st.session_state.column_config = updated_config


##############################################
# Section 5.2: Toggle and Display Set Machine Score Limits
##############################################
if st.button("Hide Machine Score Limits" if st.session_state.set_score_limit_open else "Set Machine Score Limits", key="toggle_machine_score_limits"):
    st.session_state.set_score_limit_open = not st.session_state.set_score_limit_open
    st.rerun()

if st.session_state.set_score_limit_open:
    st.markdown("#### Set Machine Score Limits")
    st.markdown("##### Add New Score Limit")
    available_machines = [m for m in all_machines_from_data if m not in get_score_limits()]
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

    st.markdown("##### Current Score Limits")
    current_score_limits = get_score_limits()
    for machine, limit in current_score_limits.items():
        col1, col2, col3 = st.columns([0.5, 0.3, 0.2])
        col1.write(machine)
        col2.write(f"{limit:,}")
        if col3.button("🗑️", key=f"del_score_{machine}"):
            delete_score_limit(machine)
            st.rerun()
        new_edit_score = st.text_input(f"Edit {machine} Score Limit", value=f"{limit:,}", key=f"edit_{machine}")
        if st.button("Update", key=f"update_{machine}"):
            try:
                updated_score = int(new_edit_score.replace(",", "").strip())
                set_score_limit(machine, updated_score)
                st.success(f"Updated {machine} score limit to {updated_score:,}")
                st.rerun()
            except Exception as e:
                st.error("Invalid score. Please enter a valid number.")

##############################################
# Section 5.3: Toggle and Display Modify Venue Machine List
##############################################
if st.button("Hide Modify Venue Machine List" if st.session_state.modify_menu_open else "Modify Venue Machine List", key="toggle_modify_venue_machine_list"):
    st.session_state.modify_menu_open = not st.session_state.modify_menu_open
    st.rerun()

if st.session_state.modify_menu_open:
    st.markdown("#### Modify Venue Machine List")
    st.markdown("##### Included Machines")
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
        
    st.markdown("##### Excluded Machines")
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

##############################################
# Section 5.4: Standardize Machines (Add/Edit) - Persistent Across Refreshes
##############################################
# Toggle state for Standardize Machines UI.
if "standardize_machines_open" not in st.session_state:
    st.session_state.standardize_machines_open = False

if st.button("Hide Standardize Machines" if st.session_state.standardize_machines_open else "Show Standardize Machines", key="toggle_standardize_machines"):
    st.session_state.standardize_machines_open = not st.session_state.standardize_machines_open
    st.rerun()

if st.session_state.standardize_machines_open:
    st.markdown("### Standardize Machines")
    
    # --- Section for adding a new machine mapping ---
    st.markdown("#### Add New Machine Mapping")
    # Dropdown with all games (from all_machines_from_data) and a text field for manual entry.
    new_alias_dropdown = st.selectbox("Select a machine alias from existing games", all_machines_from_data, key="new_alias_dropdown")
    new_alias_manual = st.text_input("Or type a new machine alias", "", key="new_alias_text")
    # Use manual input if provided; otherwise, use dropdown.
    alias_to_add = new_alias_manual.strip() if new_alias_manual.strip() else new_alias_dropdown
    # Text input for the standardized name, defaulting to the alias.
    new_standardized = st.text_input("Enter standardized name for this machine", alias_to_add, key="new_standardized")
    
    if st.button("Add Machine Mapping", key="add_machine_mapping"):
        mapping = st.session_state.machine_mapping
        if alias_to_add:
            mapping[alias_to_add] = new_standardized.strip() if new_standardized.strip() else alias_to_add.lower()
            st.session_state.machine_mapping = mapping
            save_machine_mapping(MACHINE_MAPPING_FILE, mapping)  # Save changes
            st.success(f"Added mapping: {alias_to_add} -> {st.session_state.machine_mapping[alias_to_add]}")
            st.rerun()

    # --- Section for displaying current mappings with edit/delete options ---
    st.markdown("#### Current Machine Mappings")
    mapping = st.session_state.machine_mapping
    # Use a copy to safely iterate while modifying.
    for alias, std_val in mapping.copy().items():
        col1, col2, col3, col4 = st.columns([0.3, 0.3, 0.2, 0.2])
        with col1:
            st.write(f"Alias: {alias}")
        with col2:
            st.write(f"Standardized: {std_val}")
        with col3:
            # Edit: show a text input and an "Update" button.
            new_val = st.text_input("New Standardized Name", std_val, key=f"edit_input_{alias}")
            if st.button("Update", key=f"update_{alias}"):
                mapping[alias] = new_val.strip() if new_val.strip() else alias.lower()
                st.session_state.machine_mapping = mapping
                save_machine_mapping(MACHINE_MAPPING_FILE, mapping)  # Save changes
                st.success(f"Updated mapping for {alias}")
                st.rerun()
        with col4:
            if st.button("Delete", key=f"delete_{alias}"):
                mapping.pop(alias)
                st.session_state.machine_mapping = mapping
                save_machine_mapping(MACHINE_MAPPING_FILE, mapping)  # Save changes
                st.success(f"Deleted mapping for {alias}")
                st.rerun()

##############################################
# Section 5.5: Edit Roster (Players Cannot Be Deleted; Original Roster Uneditable)
##############################################

# Helper function: Get available players for the team from already loaded all_data.
def get_available_players_for_team(team, all_data):
    players_set = set()
    for match in all_data:
        # Check home team.
        if match.get('home', {}).get('name', "").strip().lower() == team.strip().lower():
            for player in match.get('home', {}).get('lineup', []):
                players_set.add(player.get("name", "").strip())
        # Check away team.
        if match.get('away', {}).get('name', "").strip().lower() == team.strip().lower():
            for player in match.get('away', {}).get('lineup', []):
                players_set.add(player.get("name", "").strip())
    return sorted(players_set)

# Ensure that all_data is loaded in session state.
if "all_data" not in st.session_state:
    st.session_state.all_data = load_all_json_files(repo_dir, seasons_to_process)

# Toggle the Edit Roster section.
if st.button("Hide Edit Roster" if st.session_state.get("edit_roster_open", False) else "Edit Roster", key="toggle_edit_roster"):
    st.session_state.edit_roster_open = not st.session_state.get("edit_roster_open", False)
    st.rerun()

if st.session_state.get("edit_roster_open", False):
    st.markdown("### Edit Roster")
    # Determine the team abbreviation for the selected team.
    team_abbr = team_abbr_dict.get(selected_team)
    if not team_abbr:
        st.error("No team abbreviation found for the selected team.")
    else:
        # Initialize a persistent edited roster for the team if not already set.
        # Original CSV players are stored as non-editable.
        if f"edited_roster_{team_abbr}" not in st.session_state:
            original_roster = st.session_state.roster_data.get(team_abbr, [])
            st.session_state[f"edited_roster_{team_abbr}"] = [
                {"name": p, "include": True, "editable": False} for p in original_roster
            ]
        edited_roster = st.session_state[f"edited_roster_{team_abbr}"]
        
        st.markdown(f"**Current Roster for {selected_team} ({team_abbr}):**")
        # Display each roster entry.
        for i, entry in enumerate(edited_roster.copy()):
            player = entry["name"]
            included = entry["include"]
            editable = entry.get("editable", False)
            col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
            with col1:
                st.write(player)
            with col2:
                # Checkbox to toggle inclusion (unchecking excludes the player but does not remove it).
                new_included = st.checkbox("", value=included, key=f"include_{team_abbr}_{i}")
                if new_included != included:
                    edited_roster[i]["include"] = new_included
                    st.session_state[f"edited_roster_{team_abbr}"] = edited_roster
                    # Update global roster_data: include only players that are checked.
                    st.session_state.roster_data[team_abbr] = [e["name"] for e in edited_roster if e["include"]]
                    st.rerun()
            with col3:
                # Show an Edit button only if the entry is editable.
                if editable:
                    if st.button("Edit", key=f"edit_roster_{team_abbr}_{i}"):
                        new_name = st.text_input("New name", player, key=f"edit_input_roster_{team_abbr}_{i}")
                        if new_name:
                            edited_roster[i]["name"] = new_name.strip()
                            st.session_state[f"edited_roster_{team_abbr}"] = edited_roster
                            st.session_state.roster_data[team_abbr] = [e["name"] for e in edited_roster if e["include"]]
                            st.rerun()
        
        # Compute available players for the selected team from all_data.
        available_players = get_available_players_for_team(selected_team, st.session_state.all_data)
        # Exclude those already in the roster.
        existing_players = set(e["name"] for e in edited_roster)
        available_players = sorted(set(available_players) - existing_players)
        if not available_players:
            available_players = ["No available players"]
        
        st.markdown("#### Add Player to Roster")
        new_player_dropdown = st.selectbox("Select a player", available_players, key="new_player_dropdown")
        new_player_manual = st.text_input("Or type a new player's name", "", key="new_player_manual")
        # Manual input takes precedence.
        if new_player_manual.strip():
            player_to_add = new_player_manual.strip()
        else:
            player_to_add = new_player_dropdown if new_player_dropdown != "No available players" else ""
        
        if st.button("Add Player", key="add_player_btn"):
            if player_to_add:
                if player_to_add not in [e["name"] for e in edited_roster]:
                    # New players are marked as editable.
                    edited_roster.append({"name": player_to_add, "include": True, "editable": True})
                    st.session_state[f"edited_roster_{team_abbr}"] = edited_roster
                    st.session_state.roster_data[team_abbr] = [e["name"] for e in edited_roster if e["include"]]
                    st.success(f"Added {player_to_add} to the roster.")
                    st.rerun()
                else:
                    st.warning(f"{player_to_add} is already in the roster.")
            else:
                st.warning("Please enter a player's name.")


##############################################
# Section 6: Load Team Rosters from CSV Files
##############################################
@st.cache_data(show_spinner=True)
def load_team_rosters_from_csv(repo_dir):
    """
    Loads the team rosters from the rosters.csv file in the most recent season folder.
    The CSV is expected to have lines formatted as:
      Player Name,TeamAbbr,Letter
    The third field is ignored.
    
    Returns a dictionary mapping team abbreviations to a list of player names.
    """
    latest_season = get_latest_season(repo_dir)
    if latest_season is None:
        st.error("No season directories found in the repository.")
        return {}
    
    csv_path = os.path.join(repo_dir, f"season-{latest_season}", "rosters.csv")
    roster_data = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Split by comma; expect at least two parts: name and team abbreviation.
                parts = line.split(',')
                if len(parts) < 2:
                    continue
                player_name = parts[0].strip()
                team_abbr = parts[1].strip()
                # Add player_name under the team abbreviation key.
                if team_abbr not in roster_data:
                    roster_data[team_abbr] = []
                roster_data[team_abbr].append(player_name)
    except Exception as e:
        st.error(f"Error reading rosters CSV: {e}")
    return roster_data

# Load roster data if not already loaded.
if not st.session_state.rosters_scraped:
    st.session_state.roster_data = load_team_rosters_from_csv(repo_dir)
    st.session_state.rosters_scraped = True


##############################################
# Section 9: Processing Functions
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
    """
    Determines if the given player_name is on the roster for the team.
    Since the CSV-based rosters are keyed by team abbreviation, we first
    convert the full team name (as used in the match data) to its abbreviation
    using the global team_abbr_dict. If roster data is missing, returns False.
    """
    if team_roster is None:
        return False
    # Convert full team name to abbreviation using team_abbr_dict.
    abbr = team_abbr_dict.get(team)
    if not abbr:
        return False
    return player_name in team_roster.get(abbr, [])

def process_all_rounds_and_games(all_data, team_name, venue_name, twc_team_name, team_roster, included_machines_for_venue, excluded_machines_for_venue):
    processed_data = []
    recent_machines = set(included_machines_for_venue or [])
    overall_latest_season = max(int(match['key'].split('-')[1]) for match in all_data)
    current_limits = get_score_limits()  # Use user-defined score limits from the database

    for match in all_data:
        match_venue = match['venue']['name']
        season = int(match['key'].split('-')[1])
        home_team = match['home']['name']
        away_team = match['away']['name']

        # Determine the selected team's role based on the match.
        if team_name == home_team:
            selected_team_role = "home"
        elif team_name == away_team:
            selected_team_role = "away"
        else:
            # Fallback if team_name does not match either team (should not happen)
            selected_team_role = "away"

        # TWC's role is the opposite of the selected team.
        twc_role = "home" if selected_team_role == "away" else "away"

        # Define pick rounds based on role:
        # Away picks in rounds 1 and 3; Home picks in rounds 2 and 4.
        selected_team_pick_rounds = [1, 3] if selected_team_role == "away" else [2, 4]
        twc_pick_rounds = [1, 3] if twc_role == "away" else [2, 4]

        for round_info in match['rounds']:
            round_number = round_info['n']
            team_picks_this_round = set()
            twc_picks_this_round = set()
            for game in round_info['games']:
                machine = standardize_machine_name(game.get('machine', '').lower())
                if not machine:
                    continue

                if season == overall_latest_season and match_venue == venue_name:
                    if not excluded_machines_for_venue or machine not in excluded_machines_for_venue:
                        recent_machines.add(machine)

                is_team_pick = False
                is_twc_pick = False

                # Flag a pick for the selected team if the round is one of its pick rounds.
                if machine not in team_picks_this_round and round_number in selected_team_pick_rounds:
                    is_team_pick = True
                    team_picks_this_round.add(machine)

                # Independently, flag a pick for TWC if the round is one of its pick rounds.
                if machine not in twc_picks_this_round and round_number in twc_pick_rounds:
                    is_twc_pick = True
                    twc_picks_this_round.add(machine)

                # Ensure that both flags cannot be True simultaneously for the same game.
                if is_team_pick and is_twc_pick:
                    is_twc_pick = False

                for pos in ['1', '2', '3', '4']:
                    player_key = game.get(f'player_{pos}')
                    score = game.get(f'score_{pos}', 0)
                    if score == 0:
                        continue
                    limit = current_limits.get(machine)
                    if limit is not None and score > limit:
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
                        # This "picked_by" remains for reference – it reflects the team that was designated to pick for that round.
                        'picked_by': away_team if round_number in [1, 3] else home_team,
                        'is_pick': is_team_pick,
                        'is_pick_twc': is_twc_pick,
                        'is_roster_player': is_roster_player(player_name, player_team, team_roster)
                    })
    return pd.DataFrame(processed_data), recent_machines


def filter_data(df, team=None, seasons=None, venue=None, roster_only=False):
    filtered = df.copy()
    if team:
        # Perform a case-insensitive comparison after stripping extra whitespace
        filtered = filtered[filtered['team'].str.strip().str.lower() == team.strip().lower()]
        if roster_only:
            filtered = filtered[filtered['is_roster_player']]
    if seasons:
        filtered = filtered[filtered['season'].between(seasons[0], seasons[1])]
    if venue:
        # You can also do similar normalization for venue if needed
        filtered = filtered[filtered['venue'].str.strip() == venue.strip()]
    return filtered


def calculate_stats(df, machine, pick_flag='is_pick'):
    """
    Calculate statistics for a given machine from the provided DataFrame.
    Only rows matching the machine are considered.
    times_picked is computed based on the given pick_flag (either 'is_pick' or 'is_pick_twc').
    """
    machine_data = df[df['machine'] == machine]
    
    if len(machine_data) == 0:
        return {
            'average': np.nan,
            'highest': 0,
            'times_played': 0,
            'times_picked': 0
        }
    
    # For times_played, we need to count unique matches+rounds
    # Group by match and round to get unique games
    unique_games = machine_data.groupby(['match', 'round']).first().reset_index()
    times_played = len(unique_games)
    
    # For times_picked, we need games where the pick flag is True
    # First get unique games, then filter those where pick flag is True
    times_picked = len(unique_games[unique_games[pick_flag] == True])
    
    # Calculate score statistics
    scores = machine_data['score'].tolist()
    average = np.mean(scores) if scores else np.nan
    highest = max(scores) if scores else 0
    
    return {
        'average': average,
        'highest': highest,
        'times_played': times_played,
        'times_picked': times_picked
    }

def backfill_stat(df, machine, team, seasons, venue_specific, stat_type, pick_flag='is_pick'):
    for season in range(seasons[0]-1, 0, -1):
        backfill_df = filter_data(df, team, (season, season), venue if venue_specific else None)
        stats = calculate_stats(backfill_df, machine, pick_flag)
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
    """
    Build the final result DataFrame.
    For columns starting with 'Team', filter the DataFrame by the selected team and use the is_pick flag.
    For columns starting with 'TWC', filter by TWC team and use the is_pick_twc flag.
    If a column is not venue specific, then the venue filter is omitted.
    """
    data = []
    for machine in sorted(recent_machines):
        row = {'Machine': machine.title()}
        for column, config in column_config.items():
            if not config.get('include', True):
                continue
            seasons = config.get('seasons', (1, 9999))
            venue_specific = config.get('venue_specific', False)
            # When roster_only is True, filter_data will further restrict the rows.
            roster_only = True if column.startswith('Team') or column.startswith('TWC') else False

            if column.startswith('Team'):
                filtered_df = filter_data(df, team_name, seasons, venue_name if venue_specific else None, roster_only=roster_only)
                pick_flag = 'is_pick'
            elif column.startswith('TWC'):
                filtered_df = filter_data(df, twc_team_name, seasons, venue_name if venue_specific else None, roster_only=roster_only)
                pick_flag = 'is_pick_twc'
            else:
                filtered_df = filter_data(df, None, seasons, venue_name if venue_specific else None, roster_only=roster_only)
                pick_flag = 'is_pick'
            
            stats = calculate_stats(filtered_df, machine, pick_flag)
            value = np.nan
            if column == 'Team Highest Score':
                value = stats['highest']
            elif 'Average' in column:
                value = stats['average']
            elif 'Times Played' in column:
                value = stats['times_played']
            elif 'Times Picked' in column:
                value = stats['times_picked']
            
            # (Backfill logic could be added here if needed)
            if not np.isnan(value):
                if 'Average' in column:
                    formatted = f"{value:,.2f}"
                else:
                    formatted = f"{value:,}"
                row[column] = formatted
            else:
                row[column] = "N/A"
        # Calculate percentage columns (these assume the existence of "Team Average", "TWC Average", and "Venue Average")
        def safe_get(key):
            v = row.get(key, "N/A")
            try:
                return float(v.replace(",", "").split("*")[0])
            except Exception:
                return np.nan
        team_avg = safe_get("Team Average")
        twc_avg = safe_get("TWC Average")
        venue_avg = safe_get("Venue Average")
        row["% of V. Avg."] = f"{(team_avg / venue_avg * 100):.2f}%" if not np.isnan(team_avg) and not np.isnan(venue_avg) and venue_avg != 0 else "N/A"
        row["TWC % V. Avg."] = f"{(twc_avg / venue_avg * 100):.2f}%" if not np.isnan(twc_avg) and not np.isnan(venue_avg) and venue_avg != 0 else "N/A"
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

def generate_player_stats_tables(df, team_name, venue_name, seasons_to_process, roster_data):
    """
    Generate player statistics tables for the selected team and TWC at the selected venue.
    
    Parameters:
    df (DataFrame): Processed data from process_all_rounds_and_games
    team_name (str): Name of the selected team
    venue_name (str): Name of the selected venue
    seasons_to_process (list): List of seasons to include
    roster_data (dict): Dictionary mapping team abbreviations to roster player lists
    
    Returns:
    tuple: (team_table, twc_table) - DataFrames for the selected team and TWC
    """
    # Use the is_roster_player flag that's already in the data
    # That flag should have been set correctly during processing
    
    # Function to process team data
    def process_team_data(df, team_name, venue_name):
        # Filter for this team and venue
        team_data = df[(df['team'] == team_name) & (df['venue'] == venue_name)]
        team_data = team_data[team_data['season'].isin(seasons_to_process)]
        
        # Get all machines played by this team at this venue
        machines = team_data['machine'].unique()
        
        player_machine_stats = {}
        for machine in machines:
            machine_data = team_data[team_data['machine'] == machine]
            
            # Group players by roster status
            roster_players = []
            substitutes = []
            
            # Get unique players
            for player in machine_data['player_name'].unique():
                # Check if this player is flagged as a roster player
                is_roster = machine_data[machine_data['player_name'] == player]['is_roster_player'].any()
                if is_roster:
                    roster_players.append(player)
                else:
                    substitutes.append(player)
            
            player_machine_stats[machine] = {
                'Roster Players Count': len(roster_players),
                'Roster Players': ', '.join(sorted(roster_players)),
                'Number of Substitutes': len(substitutes),
                'Substitutes': ', '.join(sorted(substitutes))
            }
        
        # Convert to DataFrame and sort by roster player count in descending order
        result_df = pd.DataFrame.from_dict(player_machine_stats, orient='index')
        if not result_df.empty:
            result_df = result_df.sort_values(by='Roster Players Count', ascending=False)
        result_df.index.name = 'Machine'
        result_df.reset_index(inplace=True)
        
        return result_df
    
    # Generate tables for both teams
    team_table = process_team_data(df, team_name, venue_name)
    twc_table = process_team_data(df, "The Wrecking Crew", venue_name)
    
    return team_table, twc_table

def main(all_data, selected_team, selected_venue, team_roster, column_config):
    team_name = selected_team
    twc_team_name = "The Wrecking Crew"
    # Refresh the included and excluded machine lists from your persistent store.
    included_list = get_venue_machine_list(selected_venue, "included")
    excluded_list = get_venue_machine_list(selected_venue, "excluded")
    
    all_data_df, recent_machines = process_all_rounds_and_games(
        all_data, team_name, selected_venue, twc_team_name, team_roster,
        included_list, excluded_list
    )
    debug_outputs = generate_debug_outputs(all_data_df, team_name, twc_team_name, selected_venue)
    result_df = calculate_averages(all_data_df, recent_machines, team_name, twc_team_name, selected_venue, column_config)
    result_df = result_df.sort_values('% of V. Avg.', ascending=False, na_position='last')
    
    # Generate player statistics tables
    team_player_stats, twc_player_stats = generate_player_stats_tables(
        all_data_df, team_name, selected_venue, seasons_to_process, team_roster
    )
    
    return result_df, debug_outputs, team_player_stats, twc_player_stats



##############################################
# Section 12: "Kellanate" Button, Persistent Output & Excel Download
##############################################
if st.button("Kellanate", key="kellanate_btn"):
    with st.spinner("Loading JSON files from repository and processing data..."):
        all_data = load_all_json_files(repo_dir, seasons_to_process)
        result_df, debug_outputs, team_player_stats, twc_player_stats = main(
            all_data, selected_team, selected_venue, st.session_state.roster_data, st.session_state["column_config"]
        )
        # Store results in session state so they persist.
        st.session_state["result_df"] = result_df
        st.session_state["team_player_stats"] = team_player_stats
        st.session_state["twc_player_stats"] = twc_player_stats
        
        # Create Excel file with multiple sheets
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Results')
            team_player_stats.to_excel(writer, index=False, sheet_name=f'{selected_team} Players')
            twc_player_stats.to_excel(writer, index=False, sheet_name='TWC Players')
            
        st.session_state["processed_excel"] = output.getvalue()
        st.session_state["debug_outputs"] = debug_outputs
        st.session_state["kellanate_output"] = True
    st.success("Data processed successfully!")

# Only display the output if results exist.
if st.session_state.get("kellanate_output", False) and "result_df" in st.session_state:
    # Display a row with an "X" button to close the output.
    col1, col2 = st.columns([0.9, 0.1])
    with col2:
        if st.button("X", key="close_kellanate_output"):
            st.session_state.pop("kellanate_output", None)
            st.session_state.pop("result_df", None)
            st.session_state.pop("team_player_stats", None)
            st.session_state.pop("twc_player_stats", None)
            st.session_state.pop("processed_excel", None)
            st.session_state.pop("debug_outputs", None)
            st.rerun()
    # Reset index to hide it.
    result_df_reset = st.session_state["result_df"].reset_index(drop=True)
    
    # Configure AgGrid with flex sizing for the main results.
    from st_aggrid import AgGrid, GridOptionsBuilder
    gb = GridOptionsBuilder.from_dataframe(result_df_reset)
    # Set flex property to auto-size columns relative to available space.
    gb.configure_default_column(flex=1, resizable=True)
    # Pin the "Machine" column to the left.
    gb.configure_column("Machine", pinned='left', flex=1)
    gridOptions = gb.build()
    
    # Display the DataFrame with AgGrid.
    st.markdown("### Machine Statistics")
    AgGrid(result_df_reset, gridOptions=gridOptions, height=400, fit_columns_on_grid_load=True)
    
    # Display the player statistics tables
    st.markdown(f"### {selected_team} Player Statistics at {selected_venue}")
    AgGrid(st.session_state["team_player_stats"], height=400, fit_columns_on_grid_load=True)
    
    st.markdown(f"### TWC Player Statistics at {selected_venue}")
    AgGrid(st.session_state["twc_player_stats"], height=400, fit_columns_on_grid_load=True)
    
    # Download button for the Excel file.
    st.download_button(
        label="Download Excel file",
        data=st.session_state["processed_excel"],
        file_name="final_stats.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.write("Press 'Kellanate' to Kellanate.")


##############################################
# Section 12.5: Optional Debug Outputs Toggle
##############################################
if st.checkbox("Show Debug Outputs", key="debug_toggle"):
    if "debug_outputs" in st.session_state:
        for name, debug_df in st.session_state.debug_outputs.items():
            st.markdown(f"### Debug Output: {name}")
            st.dataframe(debug_df)
    else:
        st.info("No debug outputs available. Please run 'Kellanate' first.")


##############################################
# Debug Info Toggle for Roster, Team Names, Venues, and Abbreviations
##############################################
if st.checkbox("Debug Info", key="debug_info_toggle"):
    st.markdown("### Debug Information")
    st.write("**DEBUG: Sorted Venues extracted from JSON:**", dynamic_venues)
    st.write("**DEBUG: Sorted Teams extracted from JSON:**", dynamic_team_names)
    st.write("**DEBUG: Team Abbreviations:**", team_abbr_dict)
    # Display the roster for the selected team (if available)
    if selected_team and team_abbr_dict and st.session_state.roster_data:
        team_abbr = team_abbr_dict.get(selected_team)
        if team_abbr:
            selected_team_roster = st.session_state.roster_data.get(team_abbr, [])
            st.write(f"**DEBUG: Roster for {selected_team} ({team_abbr}):**", selected_team_roster)
        else:
            st.write(f"**DEBUG: No team abbreviation found for {selected_team}.**")
    else:
        st.write("**DEBUG: Team roster data is not available.**")



