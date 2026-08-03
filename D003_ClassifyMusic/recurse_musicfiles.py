from datetime import datetime
from pathlib import Path
import sys

def generate_file_list(folder_path_str):
    # Convert the input string to a Path object and resolve its absolute path
    root_dir = Path(folder_path_str).resolve()
    
    # Check if the folder exists and is a valid directory
    if not root_dir.exists() or not root_dir.is_dir():
        print(f"Error: '{folder_path_str}' is not a valid directory.")
        return

    # Extract the folder name and current date
    folder_name = root_dir.name
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Construct the output filename (saved in the current working directory)
    output_filename = f"{folder_name}_{date_str}.txt"
    
    # List to store all relative file paths
    relative_paths = []
    
    # Recursively traverse all contents in the directory using rglob("*")
    for file_path in root_dir.rglob("*"):
        # Process only files (ignore directories)
        if file_path.is_file():
            # Calculate the relative path from the root directory
            rel_path = file_path.relative_to(root_dir)
            relative_paths.append(str(rel_path))
    
    # Sort the paths for better readability
    relative_paths.sort()
    
    # Write paths to the output txt file (using UTF-8 encoding)
    with open(output_filename, "w", encoding="utf-8") as f:
        for path_str in relative_paths:
            f.write(path_str + "\n")
            
    print("Processing complete!")
    print(f"Generated file list: {output_filename}")
    print(f"Total files recorded: {len(relative_paths)}")

if __name__ == "__main__":
    # Use the command-line argument if provided
    if len(sys.argv) > 1:
        input_folder = sys.argv[1]
    else:
        # Otherwise, prompt the user to input the directory path interactively
        input_folder = input("Please enter the folder path to scan: ").strip()
        
    generate_file_list(input_folder)