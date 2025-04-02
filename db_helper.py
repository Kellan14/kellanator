import sqlite3
import json
import os
import base64
import requests
import streamlit as st
import glob
import re

# Local database for fallback/development
DB_FILE = "global_settings.db"

# Flag to determine whether to use GitHub or local storage
USE_GITHUB = False
repository_url = 'https://github.com/Invader-Zim/mnp-data-archive'
repo_dir = "mnp-data-archive"
###########################################
# GitHub Integration Functions
###########################################

# You'll need to set these in your Streamlit secrets
# (.streamlit/secrets.toml locally or via Streamlit Cloud dashboard)
def get_github_credentials():
    if 'github' in st.secrets:
        return {
            'token': st.secrets['github']['token'],
            'repo_owner': st.secrets['github']['repo_owner'],
            'repo_name': st.secrets['github']['repo_name'],
            'branch': st.secrets['github'].get('branch', 'main')
        }
    else:
        st.error("GitHub credentials not found in secrets! Please add them to continue.")
        return None

def get_file_contents(path):
    """
    Retrieve a file from the GitHub repository.
    
    Parameters:
    path (str): Path to the file in the repository
    
    Returns:
    dict or None: The file contents as a dictionary, or None if the file doesn't exist
    """
    credentials = get_github_credentials()
    if not credentials:
        return None, None
    
    url = f"https://api.github.com/repos/{credentials['repo_owner']}/{credentials['repo_name']}/contents/{path}"
    headers = {
        "Authorization": f"token {credentials['token']}",
        "Accept": "application/vnd.github.v3+json"
    }
    params = {"ref": credentials['branch']}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        # File exists, decode the content
        content_data = response.json()
        content = base64.b64decode(content_data['content']).decode('utf-8')
        try:
            return json.loads(content), content_data['sha']
        except json.JSONDecodeError:
            st.error(f"Error parsing JSON from {path}")
            return None, None
    elif response.status_code == 404:
        # File doesn't exist yet
        return None, None
    else:
        st.error(f"Error retrieving file: {response.status_code} - {response.text}")
        return None, None

def save_file_contents(path, content, message, sha=None):
    """
    Save content to a file in the GitHub repository.
    
    Parameters:
    path (str): Path where the file should be saved
    content (dict): The content to save
    message (str): Commit message
    sha (str, optional): The SHA of the file if it already exists
    
    Returns:
    bool: True if successful, False otherwise
    """
    credentials = get_github_credentials()
    if not credentials:
        return False
    
    url = f"https://api.github.com/repos/{credentials['repo_owner']}/{credentials['repo_name']}/contents/{path}"
    headers = {
        "Authorization": f"token {credentials['token']}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Convert content to JSON and encode as base64
    content_json = json.dumps(content, indent=2)
    content_bytes = content_json.encode('utf-8')
    content_base64 = base64.b64encode(content_bytes).decode('utf-8')
    
    data = {
        "message": message,
        "content": content_base64,
        "branch": credentials['branch']
    }
    
    if sha:
        data["sha"] = sha
    
    response = requests.put(url, headers=headers, json=data)
    
    if response.status_code in (200, 201):
        return True
    else:
        st.error(f"Error saving file: {response.status_code} - {response.text}")
        return False

# Functions for score limits
def get_score_limits_github():
    """Get score limits from GitHub."""
    data, sha = get_file_contents("kellanator/score_limits.json")
    return data or {}, sha

def set_score_limit_github(machine, score_limit):
    """Set a score limit and save to GitHub."""
    score_limits, sha = get_score_limits_github()
    score_limits[machine.lower()] = score_limit
    return save_file_contents(
        "kellanator/score_limits.json", 
        score_limits, 
        f"Update score limit for {machine}", 
        sha
    )

def delete_score_limit_github(machine):
    """Delete a score limit and update GitHub."""
    score_limits, sha = get_score_limits_github()
    if machine.lower() in score_limits:
        del score_limits[machine.lower()]
        return save_file_contents(
            "kellanator/score_limits.json", 
            score_limits, 
            f"Delete score limit for {machine}", 
            sha
        )
    return True

# Functions for venue machine lists
def get_venue_machine_lists_github():
    """Get venue machine lists from GitHub."""
    data, sha = get_file_contents("kellanator/venue_machine_lists.json")
    return data or {}, sha

def get_venue_machine_list_github(venue, list_type):
    """Get a specific venue machine list from GitHub."""
    venue_lists, _ = get_venue_machine_lists_github()
    venue_key = venue.lower()
    list_key = list_type.lower()
    
    if venue_key not in venue_lists:
        return []
    if list_key not in venue_lists[venue_key]:
        return []
    
    return venue_lists[venue_key][list_key]

def add_machine_to_venue_github(venue, list_type, machine):
    """Add a machine to a venue list and save to GitHub."""
    venue_lists, sha = get_venue_machine_lists_github()
    venue_key = venue.lower()
    list_key = list_type.lower()
    machine_key = machine.lower()
    
    # Initialize nested dictionaries if they don't exist
    if venue_key not in venue_lists:
        venue_lists[venue_key] = {}
    if list_key not in venue_lists[venue_key]:
        venue_lists[venue_key][list_key] = []
    
    # Add machine if not already in the list
    if machine_key not in venue_lists[venue_key][list_key]:
        venue_lists[venue_key][list_key].append(machine_key)
        
    return save_file_contents(
        "kellanator/venue_machine_lists.json", 
        venue_lists, 
        f"Add {machine} to {list_type} list for {venue}", 
        sha
    )

def delete_machine_from_venue_github(venue, list_type, machine):
    """Remove a machine from a venue list and update GitHub."""
    venue_lists, sha = get_venue_machine_lists_github()
    venue_key = venue.lower()
    list_key = list_type.lower()
    machine_key = machine.lower()
    
    # Check if the keys exist and the machine is in the list
    if (venue_key in venue_lists and 
        list_key in venue_lists[venue_key] and 
        machine_key in venue_lists[venue_key][list_key]):
        
        venue_lists[venue_key][list_key].remove(machine_key)
        
        return save_file_contents(
            "kellanator/venue_machine_lists.json", 
            venue_lists, 
            f"Remove {machine} from {list_type} list for {venue}", 
            sha
        )
    
    return True

# Functions for machine mapping
def get_machine_mapping_github():
    """Get machine mapping from GitHub."""
    data, sha = get_file_contents("kellanator/machine_mapping.json")
    # Provide default mapping if none exists
    if not data:
        data = {
            'pulp': 'pulp fiction',
            'bksor': 'black knight sor'
        }
    return data, sha

def save_machine_mapping_github(mapping):
    """Save machine mapping to GitHub."""
    _, sha = get_machine_mapping_github()
    return save_file_contents(
        "kellanator/machine_mapping.json", 
        mapping, 
        "Update machine mapping", 
        sha
    )

###########################################
# Database Functions
###########################################

def init_db():
    """Initialize the database and create tables if they don't exist."""
    # Always initialize local DB for fallback/development
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Table for score limits: each row is (machine TEXT PRIMARY KEY, score_limit INTEGER)
    c.execute('''
        CREATE TABLE IF NOT EXISTS score_limits (
            machine TEXT PRIMARY KEY,
            score_limit INTEGER
        )
    ''')
    # Table for venue machine lists:
    # Each row: (venue TEXT, list_type TEXT, machine TEXT)
    # list_type is either "included" or "excluded".
    c.execute('''
        CREATE TABLE IF NOT EXISTS venue_machine_lists (
            venue TEXT,
            list_type TEXT,
            machine TEXT,
            PRIMARY KEY (venue, list_type, machine)
        )
    ''')
    conn.commit()
    conn.close()

    # Check if we're running in Streamlit Cloud by looking for 'github' in secrets
    global USE_GITHUB
    USE_GITHUB = 'github' in st.secrets if hasattr(st, 'secrets') else False

def get_score_limits():
    """Retrieve the score limits as a dictionary {machine: score_limit}."""
    if USE_GITHUB:
        limits, _ = get_score_limits_github()
        return limits
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT machine, score_limit FROM score_limits")
        rows = c.fetchall()
        conn.close()
        return {machine: score_limit for machine, score_limit in rows}

def set_score_limit(machine, score_limit):
    """Set or update a score limit for a machine."""
    if USE_GITHUB:
        return set_score_limit_github(machine, score_limit)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO score_limits (machine, score_limit) VALUES (?, ?)",
                (machine, score_limit))
        conn.commit()
        conn.close()
        return True

def delete_score_limit(machine):
    """Delete a score limit for a machine."""
    if USE_GITHUB:
        return delete_score_limit_github(machine)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM score_limits WHERE machine = ?", (machine,))
        conn.commit()
        conn.close()
        return True

def get_venue_machine_list(venue, list_type):
    """Retrieve the machine list for a given venue and list type ('included' or 'excluded').  
    Returns a list of machine names."""
    if USE_GITHUB:
        return get_venue_machine_list_github(venue, list_type)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT machine FROM venue_machine_lists WHERE venue = ? AND list_type = ?", (venue, list_type))
        rows = c.fetchall()
        conn.close()
        return [row[0] for row in rows]

def add_machine_to_venue(venue, list_type, machine):
    """Add a machine to the venue machine list."""
    if USE_GITHUB:
        return add_machine_to_venue_github(venue, list_type, machine)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO venue_machine_lists (venue, list_type, machine) VALUES (?, ?, ?)",
                (venue, list_type, machine))
        conn.commit()
        conn.close()
        return True

def delete_machine_from_venue(venue, list_type, machine):
    """Remove a machine from the venue machine list."""
    if USE_GITHUB:
        return delete_machine_from_venue_github(venue, list_type, machine)
    else:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM venue_machine_lists WHERE venue = ? AND list_type = ? AND machine = ?",
                (venue, list_type, machine))
        conn.commit()
        conn.close()
        return True

def load_machine_mapping(file_path=None):
    """Load machine mapping from GitHub or local JSON file."""
    if USE_GITHUB:
        mapping, _ = get_machine_mapping_github()
        return mapping
    else:
        if file_path and os.path.exists(file_path):
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

def save_machine_mapping(mapping, file_path="kellanator/machine_mapping.json"):
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, indent=2)
        return True
    except Exception as e:
        st.error(f"Error saving machine mapping: {e}")
        return False

def save_machine_mapping_strategy(mapping):
    # Try local save
    local_save_success = save_machine_mapping(mapping)
    
    # If GitHub integration is enabled, also try GitHub save
    if 'github' in st.secrets:
        github_save_success = save_machine_mapping_github(mapping)
        return local_save_success and github_save_success
    
    return local_save_success

def load_team_rosters(repo_dir):
    """
    Load team rosters with priority:
    1. team_rosters/(team_abbreviation)_roster.py files
    2. rosters.csv in the latest season
    
    Returns a dictionary mapping team abbreviations to a list of player names.
    """
    roster_data = {}
    
    # First, check for Python roster files
    team_rosters_dir = os.path.join(repo_dir, "team_rosters")
    
    # If the team_rosters directory exists, look for Python files
    if os.path.exists(team_rosters_dir):
        for filename in os.listdir(team_rosters_dir):
            if filename.endswith("_roster.py"):
                team_abbr = filename.replace("_roster.py", "")
                try:
                    # Dynamically import the roster file
                    spec = importlib.util.spec_from_file_location(
                        f"{team_abbr}_roster", 
                        os.path.join(team_rosters_dir, filename)
                    )
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Assume the roster is defined as a list called 'roster'
                    if hasattr(module, 'roster'):
                        roster_data[team_abbr] = module.roster
                except Exception as e:
                    st.error(f"Error loading roster for {team_abbr}: {e}")
    
    # If no Python rosters found, fall back to CSV
    if not roster_data:
        latest_season = get_latest_season(repo_dir)
        if latest_season is not None:
            csv_path = os.path.join(repo_dir, f"season-{latest_season}", "rosters.csv")
            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split(',')
                        if len(parts) < 2:
                            continue
                        player_name = parts[0].strip()
                        team_abbr = parts[1].strip()
                        if team_abbr not in roster_data:
                            roster_data[team_abbr] = []
                        roster_data[team_abbr].append(player_name)
            except Exception as e:
                st.error(f"Error reading rosters CSV: {e}")
    
    return roster_data

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

# Initialize the database when the module is imported.
init_db()

