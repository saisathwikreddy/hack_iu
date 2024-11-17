import streamlit as st
from datetime import datetime
from main import EditorSession, BashSession, SessionLogger
import os
import uuid
import json
import pandas as pd
from collections import Counter

DATA_FILE = "data/output.jsonl"

# Initialize in-memory key-value store
if "database" not in st.session_state:
    st.session_state.database = {}

SESSIONS_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Create a shared session ID for the web app
session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
session_logger = SessionLogger(session_id, SESSIONS_DIR)

# Initialize sessions
editor_session = EditorSession(session_id=session_id)
editor_session.set_logger(session_logger)

bash_session = BashSession(session_id=session_id)
bash_session.set_logger(session_logger)

def read_data():
    try:
        with open(DATA_FILE, "r") as f:
            return [json.loads(line) for line in f if line.strip()]
    except Exception as e:
        st.error(f"Error reading data: {str(e)}")
        return []

# Function to handle commands
def process_command(command: str):
    cur_date_time = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    command += f'. use the current datetime as neeeded: {cur_date_time}'
    messages = editor_session.process_edit(command)
    try:
        data = read_data()
        print(messages[-1]["content"][0]["text"])
        return messages[-1]["content"][0]["text"]
    except Exception as e:
        return f"Error processing command: {str(e)}"

# Streamlit UI
st.title("Key-Value Store Manager")

# Command input
st.subheader("Enter a command:")
user_input = st.text_input("Command:", placeholder="e.g., Insert key 'user1' with value 'John Doe'")

# Display feedback and database state
if user_input:
    feedback = process_command(user_input)
    st.text_area("Feedback:", value=feedback, height=100, key="feedback")

# Display the current state of the database
st.subheader("Database State:")
data = read_data()
if data:
    # Convert the list of dictionaries into a DataFrame
    df = pd.DataFrame(data)
    # Display the DataFrame as a table
    st.dataframe(df, use_container_width=True)
else:
    st.info("The database is currently empty.")
# if st.session_state.database:
#     for key, value in st.session_state.database.items():
#         st.write(f"**{key}**: {value['value']} (Created: {value['created_at']}, Updated: {value['updated_at']})")
# else:
#     st.info("The database is currently empty.")

# image_url = "https://example.com/image.jpg"

# st.image(image_url, caption="Sample Image", use_column_width=True)

def extract_hour(filename):
    try:
        # Extract the date-time part from the filename
        datetime_part = filename.split("-")[0:2]  # ['20241117', '083715']
        time_part = datetime_part[1]  # '083715'
        hour = time_part[:2]  # Extract '08' from '083715'
        return int(hour)
    except (IndexError, ValueError):
        return None  # Return None if the filename is malformed
    
folder_path = './logs/'
log_filenames = [f for f in os.listdir(folder_path) if f.endswith(".log")]

# Extract hours from filenames
hours = [extract_hour(f) for f in log_filenames if extract_hour(f) is not None]
hour_counts = Counter(hours)

# Convert to a DataFrame for plotting
df = pd.DataFrame(list(hour_counts.items()), columns=["Hour", "Log Count"])
df = df.sort_values("Hour")  # Sort by hour for better visualization

# Display the table
# st.subheader("Log Counts by Hour")
# st.dataframe(df)

# Plot the histogram
st.subheader("Logs by Hour (Histogram)")
st.bar_chart(df.set_index("Hour"))
