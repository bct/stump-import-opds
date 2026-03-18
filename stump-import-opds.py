#!/usr/bin/env python3

import argparse
import base64
import dataclasses
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


@dataclasses.dataclass
class Entry:
    title: str | None
    author: str | None
    summary: str | None
    download_url: str | None


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
        title_element = entry_element.find("atom:title", OPDS_NS)
        title = title_element.text if title_element is not None else None

        author_element = entry_element.find("atom:author", OPDS_NS)
        author = None
        if author_element is not None:
            name_element = author_element.find("atom:name", OPDS_NS)
            if name_element is not None:
                author = name_element.text if name_element.text else ""

        summary_element = entry_element.find("atom:summary", OPDS_NS)
        summary = summary_element.text if summary_element is not None else None

        link_element = entry_element.find(
            "./atom:link[@rel='http://opds-spec.org/acquisition']", OPDS_NS
        )
        download_url = link_element.get("href") if link_element is not None else None

        entry = Entry(
            title=title, author=author, download_url=download_url, summary=summary
        )
        entries.append(entry)

    return entries


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

    args = parser.parse_args()

    config = {
        "opds_catalog": args.opds_catalog,
        "stump_url": args.stump_url,
        "stump_api_key": args.stump_api_key,
    }

    print(repr(fetch_catalog(config["opds_catalog"])))


if __name__ == "__main__":
    main()
