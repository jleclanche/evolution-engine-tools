#!/usr/bin/env python
import json
import logging
import os
import sys
from typing import Set

import requests
from evoeng.packages_extract import PackagesFile


logger = logging.getLogger(__name__)


MANIFEST_URL = "http://content.warframe.com/MobileExport/Manifest/ExportManifest.json"


def get_texture_manifest() -> dict:
	print(f"Downloading {MANIFEST_URL}")
	manifest = requests.get(MANIFEST_URL).json().get("Manifest", [])
	return {o["uniqueName"]: o["textureLocation"].replace("\\", "/") for o in manifest}


class Extractor:
	def __init__(self, args):
		bin_path = args[0]

		if not os.path.exists("ids.json"):
			raise RuntimeError("Cannot find `ids.json`.")

		with open("ids.json", "r") as f:
			self.ids = json.load(f)

		if self.ids:
			self.max_id = max(self.ids.values())
		else:
			self.max_id = 0

		self.texture_manifest = get_texture_manifest()

		with open(bin_path, "rb") as bin_file:
			print(f"Parsing {bin_path}")
			self.packages = PackagesFile(bin_file)

	def get_or_save_id(self, key: str) -> int:
		if key in self.ids:
			return self.ids[key]
		else:
			self.max_id += 1
			self.ids[key] = self.max_id
			print(f"New id: {self.max_id} - {key}")
			return self.max_id

	def extract_for_filter(self, tag_filter: str) -> list:
		print(f"Extracting: {tag_filter!r}")
		manifest = self.packages["/Lotus/Types/Lore/PrimaryCodexManifest"]
		ret = []
		entries = manifest.get("Entries", []) + manifest.get("AutoGeneratedEntries", [])

		all_keys: Set[str] = set()
		orphans: Set[str] = set()

		def _get_package(key, pkgobj):
			all_keys.add(key)
			orphans.discard(key)
			d = {"path": key, "id": self.get_or_save_id(key)}
			if key in self.texture_manifest:
				d["texture"] = self.texture_manifest[key]
			if pkgobj.parent_path:
				d["parent"] = pkgobj.parent_path
				if pkgobj.parent_path not in all_keys:
					orphans.add(pkgobj.parent_path)
			return d

		for entry in entries:
			if entry.get("tag", "") == tag_filter:
				key = entry["type"]

				pkgobj = self.packages._packages[key]
				d = _get_package(key, pkgobj)
				d["data"] = pkgobj.get_full_content(self.packages)

				ret.append(d)

		print("Processing orphan keys…")
		while orphans:
			for key in list(orphans):
				try:
					pkgobj = self.packages._packages[key]
					ret.append(_get_package(key, pkgobj))
				except KeyError:
					orphans.discard(key)
					ret.append({"path": key, "id": self.get_or_save_id(key)})

		return ret

	def extract_all(self) -> dict:
		warframes = self.extract_for_filter("Warframe")
		mods = self.extract_for_filter("Mod")
		weapons = self.extract_for_filter("Weapon")
		return {"warframes": warframes, "mods": mods, "weapons": weapons}


def main() -> None:
	extractor = Extractor(sys.argv[1:])
	data = extractor.extract_all()

	with open("ids.json", "w") as f:
		json.dump(extractor.ids, f, indent="\t", sort_keys=True)

	with open(f"data.json", "w") as f:
		json.dump(data, f, indent="\t", sort_keys=True)


if __name__ == "__main__":
	main()
