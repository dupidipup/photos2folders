import os
import pdfplumber
import pandas as pd
import re
from datetime import datetime, timedelta
from PIL import Image
from PIL.ExifTags import TAGS
import shutil
import argparse

# Set up argument parsing
parser = argparse.ArgumentParser(description="Sort photos based on sessions extracted from PDF(s).")
parser.add_argument('--name-only', action='store_true', help="Use only the person's name for the main folder.")
args = parser.parse_args()

# List of valid photo file extensions
VALID_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.heic'}

# THE ONLY PLACE YOU CAN DO CHANGES starts here!!!
# Directories
# To use custom directories, repalce os.path.join(.....) with desired directory 
# Like that: pdf_directory = 'C:\Users\username\MyPhotoLibrary\SortedPhotos\'

script_directory = os.path.dirname(__file__)
pdf_directory = os.path.join(script_directory, 'schedule')  # Folder containing PDF files
photo_directory = os.path.join(script_directory, 'photos')  # Unsorted photos
output_directory = os.path.join(script_directory, 'output')  # Output folder

# THE ONLY PLACE YOU CAN DO CHANGES ended here!!! unless you know what you...

def extract_sessions_from_pdfs(pdf_directory):
    all_data = []

    for pdf_file in os.listdir(pdf_directory):
        if not pdf_file.lower().endswith('.pdf'):
            continue

        pdf_path = os.path.join(pdf_directory, pdf_file)
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                lines = text.splitlines()

                # Extract the date from the first line
                first_line = lines[0]
                date_match = re.search(r'\((\s*\w+\s+(\d{2}\.\d{2}\.\d{4}))\s*\)', first_line)
                if not date_match:
                    continue
                date_str = date_match.group(2)
                date_obj = datetime.strptime(date_str, '%d.%m.%Y').date()

                # Locate the table header
                table_start_idx = next((i + 1 for i, line in enumerate(lines) 
                                       if 'Kell' in line and 'Pikkus' in line and 'Patsient' in line and 'Isikukood' in line), None)
                if table_start_idx is None:
                    continue

                # Process table data rows
                for line in lines[table_start_idx:]:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Extract time, duration, and remaining text
                    time_match = re.search(r'\b(\d{2}:\d{2})\b', line)
                    duration_match = re.search(r'(\d+)\s*min', line)
                    if not time_match or not duration_match:
                        continue
                    
                    time_str = time_match.group(1)
                    duration_str = duration_match.group(1)
                    remaining_text = line[duration_match.end():].strip()

                    # Split remaining text into name and personal code
                    parts = remaining_text.rsplit(' ', 1)
                    if len(parts) != 2:
                        continue
                    
                    name, personal_code = map(str.strip, parts)
                    datetime_obj = datetime.strptime(f"{date_str} {time_str}:00", '%d.%m.%Y %H:%M:%S')

                    # Append the processed data to all_data
                    all_data.append({
                        'datetime': datetime_obj,
                        'duration_minutes': int(duration_str),
                        'name': name,
                        'personal_code': personal_code,
                        'end_datetime': datetime_obj + timedelta(minutes=int(duration_str))
                    })

    return pd.DataFrame(all_data)

def create_folders_and_copy_photos(photo_directory, sessions_df, output_directory, name_only=False):
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)

    copied_photos = []
    skipped_photos = []
    already_exists_skipped_photos = []

    for root, _, files in os.walk(photo_directory):
        for photo_name in files:
            photo_path = os.path.join(root, photo_name)

            # Ignore non-photo files
            _, ext = os.path.splitext(photo_name.lower())
            if ext not in VALID_EXTENSIONS:
                skipped_photos.append((photo_name, "Non-photo file"))
                continue

            if not os.path.isfile(photo_path):
                continue

            photo_datetime = get_photo_datetime(photo_path)
            if not photo_datetime:
                skipped_photos.append((photo_name, "No EXIF datetime found"))
                continue

            matching_session = sessions_df[
                (sessions_df['datetime'] <= photo_datetime) &
                (sessions_df['end_datetime'] >= photo_datetime)
            ]

            if matching_session.empty:
                skipped_photos.append((photo_name, "No matching session in past appointments"))
            else:
                for _, session in matching_session.iterrows():
                    # Determine folder name based on the name_only argument
                    if name_only:
                        folder_name = session['name']
                    else:
                        folder_name = f"{session['name']} -- {session['personal_code']}"
                        
                    date_folder_name = session['datetime'].strftime('%Y-%m-%d')
                    folder_path = os.path.join(output_directory, folder_name, date_folder_name)

                    # Create folders if they do not exist
                    os.makedirs(folder_path, exist_ok=True)

                    destination_path = os.path.join(folder_path, photo_name)

                    # Skip copying if the file already exists
                    if os.path.exists(destination_path):
                        already_exists_skipped_photos.append((photo_name, f"Already exists in {folder_name}/{date_folder_name}"))
                        continue

                    shutil.copy2(photo_path, destination_path)  # Preserve metadata during copy
                    copied_photos.append((photo_name, folder_name, date_folder_name))

    return copied_photos, skipped_photos, already_exists_skipped_photos

def get_photo_datetime(photo_path):
    try:
        # Extract the creation date from the photo's EXIF data
        with Image.open(photo_path) as img:
            exif = img._getexif()
            if exif is not None:
                for tag, value in exif.items():
                    if TAGS.get(tag) == 'DateTime':
                        return datetime.strptime(value, '%Y:%m:%d %H:%M:%S')
    except Exception as e:
        print(f"Error reading photo datetime from {photo_path}: {e}")
    return None

if __name__ == '__main__':
    sessions_df = extract_sessions_from_pdfs(pdf_directory)
    copied_photos, skipped_photos, already_exists_skipped_photos = create_folders_and_copy_photos(photo_directory, sessions_df, output_directory, args.name_only)

    # Summary
    total_photos = len(copied_photos) + len(skipped_photos) + len(already_exists_skipped_photos)
    print("\nSummary:")
    print(f"Copied Photos ({len(copied_photos)} out of {total_photos}):")
    for photo_name, folder_name, date_folder in copied_photos:
        print(f"  Photo: {photo_name} -> Folder: {folder_name}/{date_folder}")

    print(f"\nSkipped Photos ({len(skipped_photos)}) out of {total_photos}):")
    for photo_name, reason in skipped_photos:
        print(f"  Photo: {photo_name} -> Reason: {reason}")

    print(f"\nAlready Exists ({len(already_exists_skipped_photos)}) out of {total_photos}):")
    for photo_name, reason in already_exists_skipped_photos:
        print(f"  Photo: {photo_name} -> Reason: {reason}")
