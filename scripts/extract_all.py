#!/usr/bin/env python
import json
import logging
import os
import sys

import requests

from evoeng.packages_extract import PackagesFile

logger = logging.getLogger(__name__)


MANIFEST_URL = "http://content.warframe.com/MobileExport/Manifest/ExportManifest.json"


def get_texture_manifest() -> dict:
	print(f"Downloading {MANIFEST_URL}")
	manifest = requests.get(MANIFEST_URL).json().get("Manifest", [])
	return {o["uniqueName"]: o["textureLocation"].replace("\\", "/") for o in manifest}


def main() -> None:
	bin_path = sys.argv[1]

	texture_manifest = get_texture_manifest()

	with open(bin_path, "rb") as bin_file:
		print(f"Parsing {bin_path}")
		packages = PackagesFile(bin_file)

	warframes = extract_for_filter(packages, texture_manifest, "Warframe")
	mods = extract_for_filter(packages, texture_manifest, "Mod")
	weapons = extract_for_filter(packages, texture_manifest, "Weapon")

	data = {"warframes": warframes, "mods": mods, "weapons": weapons}
	with open(f"data.json", "w") as f:
		json.dump(data, f)


def extract_for_filter(packages, texture_manifest: dict, tag_filter: str) -> list:
	print(f"Extracting: {tag_filter!r}")
	manifest = packages["/Lotus/Types/Lore/PrimaryCodexManifest"]
	ret = []
	entries = manifest.get("Entries", []) + manifest.get("AutoGeneratedEntries", [])
	for entry in entries:
		if entry.get("tag", "") == tag_filter:
			key = entry["type"]
			package = packages[key]
			d = {"path": key, "data": package}
			if key in texture_manifest:
				d["texture"] = texture_manifest[key]
			ret.append(d)

	return ret


if __name__ == "__main__":
	main()