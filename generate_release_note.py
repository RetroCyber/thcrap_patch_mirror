def extract_release_notes(input_file='history.md', output_file='release_note.md'):
    with open(input_file, 'r', encoding='utf-8') as file:
        content = file.read()

    # Split content by lines and find the first section between "## xxxx"
    lines = content.splitlines()
    release_notes = []
    start_collecting = False

    for line in lines:
        # Check if the line starts with "## " indicating a new section
        if line.startswith('## '):
            if start_collecting:
                # Stop if we reach the second "## xxxx"
                break
            else:
                # Start collecting lines after the first "## xxxx"
                start_collecting = True
        elif start_collecting:
            # Collect lines until the next "## xxxx"
            release_notes.append(line.strip())

    # Join collected lines and remove leading/trailing whitespace
    release_notes_text = '\n'.join(release_notes).strip()

    # Write the extracted release notes to the output file
    with open(output_file, 'w', encoding='utf-8') as file:
        file.write(release_notes_text)

# Run the function to extract release notes
extract_release_notes()