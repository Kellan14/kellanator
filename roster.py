from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Setup Selenium WebDriver
options = webdriver.ChromeOptions()
options.add_argument("--headless")  # Run in headless mode (no visible browser)
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Load the TWC team page
team_url = "https://mondaynightpinball.com/teams/TWC"
driver.get(team_url)

# Wait for JavaScript to load
driver.implicitly_wait(5)

# Extract all player names from the anchor tags inside the table
players = [elem.text for elem in driver.find_elements(By.XPATH, "//table[2]//tr/td[1]/a")]

# Print or save results
print("Players on TWC:", players)

# Save to a file
with open("twc_roster.py", "w", encoding="utf-8") as f:
    f.write("team_roster = [\n")
    for player in players:
        f.write(f'    "{player}",\n')
    f.write("]\n")

print("Roster saved to twc_roster.py")

# Close browser
driver.quit()
