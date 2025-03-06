import streamlit as st
import json
import pandas as pd
import subprocess
import os
import glob

# For dynamic scraping
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ----- Repository Management -----

def ensure_repo(repo_url, repo_dir):
    """Clone the repository if it doesn't exist or isn't a valid git repo."""
    git_folder = os.path.join(repo_dir, ".git")
    if not os.path.exists(repo_dir) or not os.path.exists(git_folder):
        st.info("Repository not found. Cloning repository...")
        result = subprocess.run(["git", "clone", repo_url, repo_dir], capture_output=True, text=True)
        if result.returncode == 0:
            return "Repository cloned successfully."
        else:
            return f"Error cloning repository: {result.stderr}"
    else:
        return "Repository is already cloned."

repository_url = 'https://github.com/Invader-Zim/mnp-data-archive'
repo_dir = os.path.join(os.getcwd(), "mnp-data-archive")
clone_status = ensure_repo(repository_url, repo_dir)
st.info(clone_status)

def update_repo(repo_path):
    """
    Runs 'git pull' in the specified repository directory and returns the output.
    """
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
    st.success(f"Repository update result:\n{update_output}")

# ----- Dynamic Teams and Venues Scraping -----
# This function scrapes the teams page for venues and team names.
# It uses the provided XPath expressions:
# - Venues: /html/body/div[2]/table/tbody/tr[i]/td[1]
# - Teams:   /html/body/div[2]/table/tbody/tr[i]/td[2]/a

@st.cache_data(show_spinner=True)
def get_dynamic_teams_and_venues():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://mondaynightpinball.com/teams")
    driver.implicitly_wait(5)
    
    # Find all rows in the table
    rows = driver.find_elements(By.XPATH, "/html/body/div[2]/table/tbody/tr")
    venues = []
    teams = []
    for row in rows:
        try:
            # Extract venue text from first cell
            venue_element = row.find_element(By.XPATH, "./td[1]")
            # Extract team name from second cell's anchor
            team_element = row.find_element(By.XPATH, "./td[2]/a")
            venues.append(venue_element.text.strip())
            teams.append(team_element.text.strip())
        except Exception:
            continue
    
    # Remove duplicate venues while preserving order
    unique_venues = list(dict.fromkeys(venues))
    driver.quit()
    return unique_venues, teams

st.info("Loading dynamic teams and venues...")
dynamic_venues, dynamic_teams = get_dynamic_teams_and_venues()
st.success("Dynamic teams and venues loaded!")

# ----- User Selections -----
selected_venue = st.selectbox("Select Venue", dynamic_venues)
selected_team = st.selectbox("Select Team", dynamic_teams)

# ----- Data Processing (File Uploader) -----
def process_data(data, venue, team):
    # Replace this placeholder with your full processing logic
    df = pd.DataFrame(data)
    df["Selected Venue"] = venue
    df["Selected Team"] = team
    return df

st.markdown("Upload your JSON file to process the data:")

uploaded_file = st.file_uploader("Choose a JSON file", type=["json"])
if uploaded_file is not None:
    try:
        data = json.load(uploaded_file)
        result_df = process_data(data, selected_venue, selected_team)
        st.success("Data processed successfully!")
        st.dataframe(result_df)
    except Exception as e:
        st.error(f"Error processing file: {e}")

# ----- Roster Scraping with Selenium (Existing Code) -----
if st.button("Scrape Team Rosters"):
    with st.spinner("Scraping team rosters... This may take a moment."):
        BASE_URL = "https://mondaynightpinball.com/teams/"
        team_abbreviations = [
            "ADB", "BAD", "CRA", "CDC", "DTP", "DSV", "DIH", "ETB",
            "FBP", "HHS", "ICB", "KNR", "LAS", "RMS", "JMF", "NMC",
            "NLT", "CPO", "PYC", "PGN", "PKT", "PBR", "RTR", "SSD",
            "SCN", "SHK", "SSS", "SKP", "SWL", "TBT", "POW", "DOG",
            "TTT", "TWC"
        ]
        OUTPUT_DIR = "team_rosters"
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

        def fetch_team_roster(team_abbr):
            team_url = f"{BASE_URL}{team_abbr}"
            driver.get(team_url)
            driver.implicitly_wait(5)
            players = [elem.text for elem in driver.find_elements(By.XPATH, "//table[2]//tr/td[1]/a")]
            return players if players else None

        def save_roster(team_abbr, players):
            filename = f"{team_abbr.lower()}_roster.py"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("team_roster = [\n")
                for player in players:
                    f.write(f'    "{player}",\n')
                f.write("]\n")
            return filepath

        roster_files = {}
        for team_abbr in team_abbreviations:
            roster = fetch_team_roster(team_abbr)
            if roster:
                saved_path = save_roster(team_abbr, roster)
                roster_files[team_abbr] = saved_path

        driver.quit()

    if roster_files:
        st.success("Team rosters have been scraped and saved!")
        st.write("Roster files:")
        for team_abbr, path in roster_files.items():
            st.write(f"{team_abbr}: {path}")
    else:
        st.error("No rosters were scraped.")
