import streamlit as st
from datetime import datetime
from main import EditorSession, BashSession, SessionLogger
import os
import uuid
import json
import pandas as pd

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
