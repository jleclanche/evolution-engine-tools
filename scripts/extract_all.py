#!/usr/bin/env python
import json
import logging
import os
import posixpath
import sys
from typing import Dict, List, Set

import requests

from evoeng.packages_extract import PackagesFile

logger = logging.getLogger(__name__)


MANIFEST_URL = "http://content.warframe.com/MobileExport/Manifest/ExportManifest.json"

TOP_LEVEL_KEYS_BLACKLIST = {
	"AimStartSound",
	"AimStopSound",
	"AttachedFX",
	"CastSounds",
	"ChannelingKillScript",
	"CustomHudMovie",
	"DarkSectorAttachmentsToCreate",
	"DarkSectorAuxiliaryAttachments",
	"DarkSectorCustomAltFireAnimation",
	"DarkSectorCustomAltFireReloadAnimation",
	"DarkSectorHolsterPosOffset",
	"DarkSectorHolsterRotOffset",
	"DarkSectorStateAnimations",
	"DefaultAnimControllerOverride",
	"DefaultCustomization",
	"DisabledScript",
	"DM_AIM",
	"DropSound",
	"EnabledScript",
	"EXTRA1",
	"EXTRA2",
	"FireModes",
	"GripPositionOffset",
	"GripRotationOffset",
	"HeavySlamStartSound",
	"HitHeadSound",
	"HitSound",
	"HolsterBone1Name",
	"HolsterBone1Position",
	"HolsterBone1Rotation",
	"HolsterPosOffset",
	"Links",
	"MAIN_HAND",
	"Mesh",
	"OFF_HAND",
	"OnRemovedScript",
	"OwnerSetScript",
	"ParryActivatedSound",
	"ParryComboStartSound",
	"ParryDeactivatedSound",
	"PickUpMesh",
	"PvpSlams",
	"QuickSlamStartSound",
	"ScanLocalSoundEffect",
	"ScanOnKillScript",
	"SimCollision",
	"Slams",
	"SoundEvents",
	"SpecialEventInfectedScript",
	"StateAnimations",
	"THIRD_PERSON_ATTACHMENT",
	"WeaponHandAimOffset",
	"ZoomLevels",
}


def get_texture_manifest() -> dict:
	print(f"Downloading {MANIFEST_URL}")
	manifest = requests.get(MANIFEST_URL).json().get("Manifest", [])
	return {o["uniqueName"]: o["textureLocation"].replace("\\", "/") for o in manifest}


def make_absolute(key: str, base_key: str) -> str:
	base_dir = posixpath.dirname(base_key)
	return posixpath.join(base_dir, key)


def get_top_level_parent(package, packages):
	while package.parent_path:
		package = packages[package.parent_path]

	return package


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
		self.all_keys: Set[str] = set()
		self.orphans: Set[str] = set()
		self.exalted_items: Set[str] = set()
		self.mod_sets: Set[str] = set()

		with open(bin_path, "rb") as bin_file:
			print(f"Parsing {bin_path}")
			self.packages = PackagesFile(bin_file)

	def get_or_save_id(self, key: str) -> int:
		assert key, "Key should never be an empty string"
		if key in self.ids:
			return self.ids[key]
		else:
			self.max_id += 1
			self.ids[key] = self.max_id
			print(f"New id: {self.max_id} - {key}")
			return self.max_id

	def process_orphans(self, ret):
		while self.orphans:
			for key in list(self.orphans):
				try:
					pkgobj = self.packages._packages[key]
					ret[key] = self.do_get_package(key, pkgobj)
					self._clean_keys(ret, key)
				except KeyError as e:
					print(f"Cannot find key={key} ({e})")
					self.orphans.discard(key)
					ret[key] = {"path": key, "id": self.get_or_save_id(key), "data": {}}

		return ret

	def do_get_package(self, key: str, pkgobj):
		self.all_keys.add(key)
		self.orphans.discard(key)
		ret = {
			"path": key,
			"id": self.get_or_save_id(key),
			"data": pkgobj.get_full_content(self.packages),
		}

		manifest_key = self.texture_manifest.get(key, "")
		icon_texture = ret["data"].get("IconTexture", "")
		if manifest_key and manifest_key != icon_texture:
			ret["texture"] = self.texture_manifest[key]
		if pkgobj.parent_path:
			ret["parent"] = pkgobj.parent_path
			if pkgobj.parent_path not in self.all_keys:
				self.orphans.add(pkgobj.parent_path)

		item_compat = ret["data"].get("ItemCompatibility", "")
		if item_compat:
			# Resolve non-absolute paths
			if not item_compat.startswith("/"):
				# Hack for `PowerSuits/PlayerPowerSuit`.
				# I have no idea why that one is different.
				# Send help.
				if item_compat == "PowerSuits/PlayerPowerSuit":
					ret["data"]["ItemCompatibility"] = "/Lotus/Types/Game/PowerSuits/PlayerPowerSuit"
				else:
					ret["data"]["ItemCompatibility"] = make_absolute(item_compat, key)

		return ret

	def _clean_keys(self, d, key):
		# Resolve behaviors packages
		data = d[key]["data"]
		for behavior in data.get("Behaviors", []):
			for k, v in behavior.items():
				for path_key in ["projectileType", "AIMED_ACCURACY"]:
					if path_key in v:
						if len(v[path_key]) > 0:
							k = make_absolute(v[path_key], key)
							_pkgobj = self.packages._packages[k]
							v[path_key] = _pkgobj.get_full_content(self.packages)
						else:
							v[path_key] = {}

		# Clean keys we know we don't want
		for blacklisted_key in TOP_LEVEL_KEYS_BLACKLIST:
			if blacklisted_key in data:
				del data[blacklisted_key]

		# LocTags can sometimes be "Lotus/Language/Foo/..."
		# These appear to always be relative to the root (/)
		# so we can safely do "/" + LocTag
		if data.get("LocTag", "").startswith("Lotus/"):
			data = "/" + data

		for upgrade in data.get("Upgrades", []):
			loctag = upgrade.get("LocTag", "")
			if loctag.startswith("Lotus/"):
				upgrade["LocTag"] = "/" + loctag

		for i, additional_item in enumerate(data.get("AdditionalItems", [])):
			if not additional_item.startswith("/Lotus"):
				additional_item = make_absolute(additional_item, key)
				data["AdditionalItems"][i] = additional_item
				# Add it to the orphans so we parse them.
				# Note that we generally don't want the ones that
				# already start with /Lotus (they're skins…)
				self.orphans.add(additional_item)
				self.exalted_items.add(additional_item)

		# Add ModSet to the mod sets for later use
		if data.get("ModSet", ""):
			# Ensure it's absolute (it never is)
			data["ModSet"] = make_absolute(data["ModSet"], key)
			self.mod_sets.add(data["ModSet"])

	def extract_for_filters(self, tag_filters: List[str]) -> Dict[str, dict]:
		print(f"Extracting: {tag_filters!r}")
		manifest = self.packages["/Lotus/Types/Lore/PrimaryCodexManifest"]
		entries = manifest.get("Entries", []) + manifest.get("AutoGeneratedEntries", [])

		ret: Dict[str, dict] = {}

		for entry in entries:
			if "tag" in entry and entry["tag"] in tag_filters:
				key = entry["type"]

				pkgobj = self.packages._packages[key]
				d = self.do_get_package(key, pkgobj)
				d["tag"] = entry["tag"]

				if entry["tag"] == "RelicsAndArcanes" and (
					"UpgradeResults" in d["data"] or key.startswith("/Lotus/Types/Game/Projections/")
				):
					# We don't want relics
					continue

				ret[key] = d
				self._clean_keys(ret, key)

		print("Processing orphan keys…")
		self.process_orphans(ret)

		return ret

	def get_mod_set(self, key: str):
		return self.packages[key]

	def extract_all(self) -> dict:
		ret = {
			"Mods": self.extract_for_filters(["Mod", "RelicsAndArcanes"]),
			"Items": self.extract_for_filters(
				["Sentinel", "SentinelWeapon", "Warframe", "Weapon"]
			),
			"ModSets": {},
		}

		# Unknown key discovery
		# Can't do this inside extract_for_filters() because it's cross-db.
		print("Processing item compatibility orphans…")
		self.orphans.clear()
		for item in ret["Mods"].values():
			item_compat = item.get("data", {}).get("ItemCompatibility", "")
			if not item_compat:
				continue

			# Discovery for unknown keys
			if item_compat not in self.all_keys:
				self.orphans.add(item_compat)

		self.process_orphans(ret["Items"])

		# Clean exalted items so they're usable later…
		for key in self.exalted_items:
			item = ret["Items"][key]
			if item["data"].get("ProductCategory", "") == "SpecialItems":
				item["tag"] = "ExaltedItems"
				obj = self.packages._packages[key]
				# Iterate through parents
				while obj.parent_path:
					obj = self.packages._packages[obj.parent_path]
					obj_data = obj.get_full_content(self.packages)
					category = obj_data.get("ProductCategory", "")
					# Find the first category that is not SpecialItems
					if category and category != "SpecialItems":
						item["data"]["ProductCategory"] = category
						break

		# do modsets
		for key in self.mod_sets:
			ret["ModSets"][key] = self.get_mod_set(key)

		return ret


def main() -> None:
	extractor = Extractor(sys.argv[1:])
	data = extractor.extract_all()

	with open("ids.json", "w") as f:
		json.dump(extractor.ids, f, indent="\t", sort_keys=True)

	with open(f"data.json", "w") as f:
		json.dump(data, f, indent="\t", sort_keys=True, ensure_ascii=False)


if __name__ == "__main__":
	main()
