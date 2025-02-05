#!/usr/bin/env python
import logging
import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, BinaryIO, Dict, List, Tuple

from binreader import BinaryReader

from .package_parser import loads

logger = logging.getLogger(__name__)


@dataclass
class Package:
	path: str
	parent_path: str
	data: bytes

	@property
	def content(self) -> Dict[str, Any]:
		return loads(self.data.decode())

	def get_full_content(self, packages_file: "PackagesFile") -> dict:
		if not self.parent_path:
			return self.content

		if self.parent_path not in packages_file._packages:
			content = {}
		else:
			parent_package = packages_file._packages[self.parent_path]
			content = parent_package.get_full_content(packages_file)
		content.update(self.content)
		return content


class PackagesFile:
	def __init__(self, bin_file: BinaryIO) -> None:
		self._packages: Dict[str, Package] = {}
		reader = BinaryReader(bin_file)
		self.hash = reader.read(29)

		def read_length_prefixed_str() -> str:
			sz = reader.read_int32()
			return reader.read_string(sz)

		self.structs: List[Tuple[str, int]] = []
		num_structs = reader.read_int32()
		for _ in range(num_structs):
			name = read_length_prefixed_str()
			unk = reader.read_int32()
			self.structs.append((name, unk))

		chunks: List[bytes] = []
		chunksize = reader.read_int32()
		chunk_reader = BinaryReader(BytesIO(reader.read(chunksize)))
		num_chunks = reader.read_int32()

		for i in range(num_chunks):
			chunks.append(chunk_reader.read_cstring())

		for chunk in chunks:
			base_path = read_length_prefixed_str()
			name = read_length_prefixed_str()
			reader.read(5)
			parent_path = read_length_prefixed_str()
			reader.read(4)  # always 0

			path = os.path.join(base_path, name)
			if parent_path:
				parent_path = os.path.join(base_path, parent_path)

			self._packages[path] = Package(path, parent_path, chunk)

	def __getitem__(self, key: str) -> Dict[str, Any]:
		return self._packages[key].get_full_content(self)

	@property
	def packages(self):
		return list(self._packages.values())
