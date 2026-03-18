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


def extract_username_and_password_from_url(
    url: str,
) -> tuple[str, tuple[str, str] | None]:
    parsed = urllib.parse.urlsplit(url)
    if not parsed.username or not parsed.password:
        return url, None

    auth = (parsed.username, parsed.password)
    parsed = parsed._replace(netloc=parsed.netloc.split("@")[-1])
    return parsed.geturl(), auth


def fetch_catalog(url: str) -> list[Entry]:
    url, auth = extract_username_and_password_from_url(url)

    request = urllib.request.Request(url)

    if auth:
        b64auth = base64.standard_b64encode(("%s:%s" % auth).encode()).decode()
        request.add_header("Authorization", f"Basic {b64auth}")

    with urllib.request.urlopen(request) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)

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

    return entries


def download_catalog_entries(
    opds_url: str, entries: list[Entry], output_dir: str
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

        author_path = os.path.join(output_dir, author)
        try:
            os.makedirs(author_path, exist_ok=True)
        except FileExistsError:
            print(f"Skipping '{human_id}': {author_path} exists and is not a directory")
            continue

        base_url, auth = extract_username_and_password_from_url(opds_url)
        download_url = urllib.parse.urljoin(base_url, entry.download_url)

        request = urllib.request.Request(download_url)
        if auth:
            b64auth = base64.standard_b64encode(("%s:%s" % auth).encode()).decode()
            request.add_header("Authorization", f"Basic {b64auth}")

        print(f"Downloading '{human_id}'...")
        with urllib.request.urlopen(request) as response:
            content_disposition = response.headers["content-disposition"]
            if not content_disposition:
                print(f"Skipping '{human_id}': server sent no content-disposition")
                continue

            msg = email.message.Message()
            msg["content-disposition"] = content_disposition
            orig_filename = msg.get_filename()
            if not orig_filename:
                print(f"Skipping '{human_id}': server provided no original filename")
                continue
            orig_extension = orig_filename.rsplit(".", 1)[-1]

            filepath = os.path.join(author_path, f"{title}.{orig_extension}")
            if os.path.exists(filepath):
                print(f"Skipping '{human_id}': file already exists")
                continue

            with open(filepath, "wb") as f:
                f.write(response.read())

    return True


def list_stump_libraries(stump_url: str, stump_api_key: str) -> list[StumpLibrary]:
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

    with urllib.request.urlopen(request) as response:
        data = json.loads(response.read().decode())

    return [
        StumpLibrary(id=node["id"], name=node["name"], path=node["path"])
        for node in data["data"]["libraries"]["nodes"]
    ]


def main():
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

    args = parser.parse_args()

    config = {
        "opds_catalog": args.opds_catalog,
        "stump_url": args.stump_url,
        "stump_api_key": args.stump_api_key,
        "stump_library_name": args.stump_library_name,
    }

    stump_libraries = list_stump_libraries(config["stump_url"], config["stump_api_key"])

    target_library: StumpLibrary | None = None
    for l in stump_libraries:
        if l.name == config["stump_library_name"]:
            target_library = l
            break

    if not target_library:
        print(f"Could not find library with name: {config["stump_library_name"]!r}")
        print()
        print("  Found libraries:")
        for l in stump_libraries:
            print(l.name)
        sys.exit(1)

    catalog_entries = fetch_catalog(config["opds_catalog"])
    download_catalog_entries(
        config["opds_catalog"], catalog_entries, target_library.path
    )


if __name__ == "__main__":
    main()
