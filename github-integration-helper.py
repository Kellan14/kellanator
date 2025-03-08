import os
import json
import base64
import requests
import streamlit as st

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
        return None
    
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
