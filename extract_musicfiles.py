from datetime import datetime
from pathlib import Path
import sys

def generate_filename_list(folder_path_str):
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
    
    # List to store only the file names (without parent directory paths)
    file_names = []
    
    # Recursively traverse all contents in the directory using rglob("*")
    for file_path in root_dir.rglob("*"):
        # Process only files (ignore directories)
        if file_path.is_file():
            # Extract only the final file name (e.g., "document.pdf")
            file_names.append(file_path.name)
    
    # Sort the filenames alphabetically for better readability
    file_names.sort()
    
    # Write filenames to the output txt file (using UTF-8 encoding)
    with open(output_filename, "w", encoding="utf-8") as f:
        for name in file_names:
            f.write(name + "\n")
            
    print("Processing complete!")
    print(f"Generated filename list: {output_filename}")
    print(f"Total files recorded: {len(file_names)}")

if __name__ == "__main__":
    # Use the command-line argument if provided
    if len(sys.argv) > 1:
        input_folder = sys.argv[1]
    else:
        # Otherwise, prompt the user to input the directory path interactively
        input_folder = input("Please enter the folder path to scan: ").strip()
        
    generate_filename_list(input_folder)