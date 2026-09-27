import sqlite3
import pandas as pd  # Optional, or pure Python csv module

def export_to_csv():
    # Connect to your SQLite database
    conn = sqlite3.connect('job_system.db')
    
    # Read the jobs table into a pandas dataframe (or use standard sqlite3 fetchall)
    query = "SELECT * FROM jobs"
    df = pd.read_sql(query, conn)
    conn.close()
    
    # Export to a CSV file
    output_file = "job_history_export.csv"
    df.to_csv(output_file, index=False)
    print(f"Job history successfully exported to {output_file}!")

if __name__ == "__main__":
    export_to_csv()