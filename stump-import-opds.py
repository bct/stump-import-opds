#!/usr/bin/env python3

import argparse
import base64
import dataclasses
import email.message
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


@dataclasses.dataclass
class Config:
    opds_catalog: str
    stump_url: str
    stump_api_key: str
    stump_library_name: str
    verbose: bool


@dataclasses.dataclass
class Entry:
    id: str | None
    title: str | None
    author: str | None
    summary: str | None
    download_url: str | None


@dataclasses.dataclass
class StumpLibrary:
    id: str
    name: str
    path: str


OPDS_NS = {
    "atom": "http://www.w3.org/2005/Atom",
}


def parse_config():
    parser = argparse.ArgumentParser(description="Import OPDS catalog into Stump")
    parser.add_argument(
        "--opds-catalog", type=str, required=True, help="URL to OPDS catalog"
    )
    parser.add_argument(
        "--stump-url", type=str, required=True, help="URL to Stump server"
    )
    parser.add_argument(
        "--stump-api-key", type=str, required=True, help="Stump API key"
    )
    parser.add_argument(
        "--stump-library-name",
        type=str,
        required=True,
        help="Name of target Stump library",
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    return Config(
        opds_catalog=args.opds_catalog,
        stump_url=args.stump_url,
        stump_api_key=args.stump_api_key,
        stump_library_name=args.stump_library_name,
        verbose=args.verbose,
    )


def extract_username_and_password_from_url(
    url: str,
) -> tuple[str, tuple[str, str] | None]:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.username or not parsed.password:
        return url, None

    auth = (parsed.username, parsed.password)
    parsed = parsed._replace(netloc=parsed.netloc.split("@")[-1])
    return parsed.geturl(), auth


def get_with_basic_auth(base_url: str, relative_url: str | None, *, verbose: bool):
    url, auth = extract_username_and_password_from_url(base_url)
    if relative_url:
        url = urllib.parse.urljoin(url, relative_url)

    request = urllib.request.Request(url)

    if auth:
        b64auth = base64.standard_b64encode(("%s:%s" % auth).encode()).decode()
        request.add_header("Authorization", f"Basic {b64auth}")

    if verbose:
        print(f"HTTP GET {request.full_url}")
    return urllib.request.urlopen(request)


def fetch_catalog(url: str, *, verbose: bool) -> list[Entry]:
    with get_with_basic_auth(url, None, verbose=verbose) as response:
        if verbose:
            print(f"HTTP {response.status}")

        xml_data = response.read()

    entries, next_url = parse_catalog(xml_data)

    while next_url:
        with get_with_basic_auth(url, next_url, verbose=verbose) as response:
            if verbose:
                print(f"HTTP {response.status}")
            xml_data = response.read()

        next_entries, next_url = parse_catalog(xml_data)
        entries.extend(next_entries)

    return entries


def parse_catalog(feed_xml: str) -> tuple[list[Entry], str | None]:
    root = ET.fromstring(feed_xml)

    entries = []
    for entry_element in root.findall("atom:entry", OPDS_NS):
        id_element = entry_element.find("atom:id", OPDS_NS)
        id = id_element.text if id_element is not None else None

        title_element = entry_element.find("atom:title", OPDS_NS)
        title = title_element.text if title_element is not None else None

        author_element = entry_element.find("atom:author", OPDS_NS)
        author = None
        if author_element is not None:
            name_element = author_element.find("atom:name", OPDS_NS)
            if name_element is not None:
                author = name_element.text

        summary_element = entry_element.find("atom:summary", OPDS_NS)
        summary = summary_element.text if summary_element is not None else None

        link_element = entry_element.find(
            "./atom:link[@rel='http://opds-spec.org/acquisition']", OPDS_NS
        )
        download_url = link_element.get("href") if link_element is not None else None

        entry = Entry(
            id=id,
            title=title,
            author=author,
            download_url=download_url,
            summary=summary,
        )
        entries.append(entry)

    next_url = None
    next_link_element = root.find("./atom:link[@rel='next']", OPDS_NS)
    next_url = next_link_element.get("href") if next_link_element is not None else None

    return entries, next_url


def download_catalog_entries(
    opds_url: str, entries: list[Entry], output_dir: str, *, verbose: bool
) -> bool:
    if not os.path.isdir(output_dir):
        print(f"{output_dir} is not a directory!")
        return False

    for entry in entries:
        author = entry.author
        title = entry.title
        if not author or not title:
            human_id = entry.id or "unidentified entry"
            print(f"Skipping '{human_id}': missing author or title")
            continue

        human_id = f"{author} - {title}"

        if not entry.download_url:
            print(f"Skipping '{human_id}': no download URL")
            continue

        if verbose:
            print(f"Downloading '{human_id}'...")
        with get_with_basic_auth(
            opds_url, entry.download_url, verbose=verbose
        ) as response:
            if verbose:
                print(f"HTTP {response.status}")

            content_disposition = response.headers["content-disposition"]
            if not content_disposition:
                print(f"Skipping '{human_id}': server sent no content-disposition")
                continue

            orig_filename = get_original_filename(content_disposition)
            if not orig_filename:
                print(f"Skipping '{human_id}': server provided no original filename")
                continue

            file_path = determine_output_file_path(entry, orig_filename)
            file_path = os.path.join(output_dir, file_path)

            file_dir = os.path.dirname(file_path)
            try:
                os.makedirs(file_dir, exist_ok=True)
            except FileExistsError:
                print(
                    f"Skipping '{human_id}': {file_dir} exists and is not a directory"
                )
                continue

            if os.path.exists(file_path):
                print(f"Skipping '{human_id}': file already exists")
                continue

            with open(file_path, "wb") as f:
                f.write(response.read())

    return True


def get_original_filename(content_disposition: str) -> str | None:
    msg = email.message.Message()
    msg["content-disposition"] = content_disposition
    return msg.get_filename()


def determine_output_file_path(entry: Entry, orig_filename: str) -> str:
    orig_extension = orig_filename.rsplit(".", 1)[-1]
    return f"{entry.author}/{entry.title}.{orig_extension}"


def list_stump_libraries(
    stump_url: str, stump_api_key: str, *, verbose: bool
) -> list[StumpLibrary]:
    graphql_url = f"{stump_url}/api/graphql"
    query = """{ libraries { nodes { id name path } } }"""

    request = urllib.request.Request(
        graphql_url,
        data=json.dumps({"query": query}).encode(),
        headers={
            "Authorization": f"Bearer {stump_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    if verbose:
        print(f"HTTP {request.method} {request.full_url}")
    with urllib.request.urlopen(request) as response:
        if verbose:
            print(f"HTTP {response.status}")
        data = json.loads(response.read().decode())

    return [
        StumpLibrary(id=node["id"], name=node["name"], path=node["path"])
        for node in data["data"]["libraries"]["nodes"]
    ]


def main():
    config = parse_config()

    stump_libraries = list_stump_libraries(
        config.stump_url, config.stump_api_key, verbose=config.verbose
    )

    target_library: StumpLibrary | None = None
    for l in stump_libraries:
        if l.name == config.stump_library_name:
            target_library = l
            break

    if not target_library:
        print(f"Could not find library with name: {config.stump_library_name!r}")
        print()
        print("  Found libraries:")
        for l in stump_libraries:
            print(l.name)
        sys.exit(1)

    catalog_entries = fetch_catalog(config.opds_catalog, verbose=config.verbose)

    download_catalog_entries(
        config.opds_catalog,
        catalog_entries,
        target_library.path,
        verbose=config.verbose,
    )

    # TODO: download these to a temporary directory.
    # then copy them to the library
    # then scan the library
    # then copy the metadata


if __name__ == "__main__":
    main()
