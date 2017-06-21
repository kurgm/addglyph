# -*- coding: utf-8 -*-

from distutils.core import setup

import py2exe  # NOQA

from addglyph import version

setup(
	options={
		"py2exe": {
			"compressed": 0,
			"optimize": 2,
			"bundle_files": 1
		}
	},
	console=[{"script": "addglyph.py"}],
	zipfile=None,
	data_files=["usage.txt"],
	name="Add Glyphs",
	version=version,
	description="Adds blank glyphs to a font file",
	author="Kurogoma"
)
