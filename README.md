This repository contains a script for importing files from an OPDS v1 server into [Stump](https://www.stumpapp.dev/).

It has been tested against BookLore v1.18.5.

# Setup

Generate a Stump API key in "Settings -> API Keys".

## BookLore

Enable OPDS in "Settings -> OPDS". Enable the OPDS server, and create an OPDS username (& password).

BookLore provides several different catalogs:

- `/api/v1/opds/catalog`: all books in the library
- `/api/v1/opds/catalog?libraryId=1`: all books in library 1
- `/api/v1/opds/catalog?shelfId=1`: all books in shelf 1
- and more.

# Example

    ./stump-import-opds.py \
        --opds-catalog http://username:password@your-booklore-host/api/v1/opds/catalog\?libraryId=1 \
        --stump-url "http://your-stump-host/" \
        --stump-api-key "stump_aoeu1234" \
        --stump-library-name "fiction"

# Limitations

The script does not sync reading status or reading position, because I don't know a reliable way to get that information.
